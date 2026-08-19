"""Strict hot-path contracts for Creator response and subjective appraisal.

The two provider calls are deliberately unable to author each other's facts.  Their
outputs are preserved separately and only combined by the deterministic cognition
pipeline after both branches have reached a terminal state.
"""

from __future__ import annotations

# ruff: noqa: RUF001
from typing import Annotated, Literal, cast

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    TypeAdapter,
    model_validator,
)

from ._dialogue_contract import (
    DIALOGUE_CANDIDATE_VERSION,
    WEB_DIALOGUE_CANDIDATE_VERSION,
    ContextRef,
    CreatorDialogueCandidate,
    DialogueCompactChange,
    DialogueExperience,
    Summary,
    parse_dialogue_candidate,
)
from ._strict_model_json import strict_model_value

CREATOR_RESPONSE_CANDIDATE_VERSION = "armi.creator-response-candidate.v1"
CREATOR_APPRAISAL_CANDIDATE_VERSION = "armi.creator-appraisal-candidate.v4"
CREATOR_DIALOGUE_AGGREGATE_VERSION = "armi.creator-dialogue-aggregate.v3"

CREATOR_RESPONSE_INSTRUCTIONS = """\
你只负责本轮对 Creator 的表达与明确行动决定。根据冻结资料独立决定回复、拒绝、沉默、延后、追问、精确生活查询或公共网页研究。
不得生成 Experience、心情、关系、记忆、Self、Mind 或主体 Prompt。changes 只允许 Creator 明确要求的 material.* 与 codex.request；不要因为资料重要就顺手保存记忆。
只输出给定 JSON Schema，不解释 Schema，不输出额外文字。"""

CREATOR_APPRAISAL_INSTRUCTIONS = """\
你只负责判断本轮输入是否真正成为 ARMI 的主观经历，以及事件对 ARMI 意味着什么、关系或承诺是否变化。你与表达分支并行，不能假设 ARMI 将说什么。
不得生成对外回复、查询、委托、资料动作、完整 MoodState、Self、Mind、主体 Prompt，也不得淡化、遗忘或改写既有记忆。只有 Creator 在当前输入中明确要求“记住”时，remember 才能为 true 并提供 memory_summary。
只能用 Schema 给出的语义标签评价事件意义，不能填写任何评价分数、情绪名称、VAD、强度、重要性、持续时间或半衰期。mixed 表示同时存在相反意义，unknown 只表示冻结资料不足；不适用的 demand、causality、coping、standards 整组省略。新事件使用 new，episode_ref 与 change_from_previous 为空；reinforce、reappraise、resolve 必须引用冻结资料中的 active_affective_episode，并填写相对变化。没有新的事件评价时省略 appraisal；情绪激发、轨迹、心境和行动倾向只由 Mood Owner 演算。只输出给定 JSON Schema，不输出额外文字。"""


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


_ResponseKind = Literal[
    "reply",
    "decline",
    "no_action",
    "no_change",
    "defer",
    "need_information",
    "exact_life_query",
    "web_research",
]
_RecordKind = Literal[
    "activity",
    "conversation",
    "material",
    "memory",
    "relationship",
    "self_change",
]
_RESPONSE_OPS = frozenset(
    {
        "material.create",
        "material.update",
        "material.visibility",
        "material.delete",
        "codex.request",
    }
)
_APPRAISAL_OPS = frozenset(
    {
        "relationship.interpret",
        "relationship.fact",
        "relationship.boundary",
        "commitment.establish",
        "commitment.modify",
        "commitment.fulfill",
        "commitment.withdraw",
        "commitment.forget",
        "commitment.violate",
        "commitment.conflict",
    }
)


class CreatorResponseCandidate(_StrictModel):
    kind: _ResponseKind
    content: (
        Annotated[str, StringConstraints(min_length=1, max_length=65536)] | None
    ) = None
    record_kind: _RecordKind | None = None
    query: Annotated[str, StringConstraints(min_length=1, max_length=16384)] | None = (
        None
    )
    changes: tuple[DialogueCompactChange, ...] = Field(default=(), max_length=8)

    @property
    def schema_version(self) -> str:
        return CREATOR_RESPONSE_CANDIDATE_VERSION

    @model_validator(mode="after")
    def validate_scope(self) -> CreatorResponseCandidate:
        if any(change.op not in _RESPONSE_OPS for change in self.changes):
            raise ValueError("response branch contains internal state")
        if self.kind == "reply":
            if (
                self.content is None
                or self.record_kind is not None
                or self.query is not None
            ):
                raise ValueError("reply shape is invalid")
        elif self.kind == "exact_life_query":
            if (
                self.record_kind is None
                or self.content is not None
                or self.query is not None
                or self.changes
            ):
                raise ValueError("life query shape is invalid")
        elif self.kind == "web_research":
            if (
                self.query is None
                or self.content is not None
                or self.record_kind is not None
                or self.changes
            ):
                raise ValueError("web research shape is invalid")
        elif (
            any(
                value is not None
                for value in (self.content, self.record_kind, self.query)
            )
            or self.changes
        ):
            raise ValueError("terminal response shape is invalid")
        return self

    def as_dialogue(self, *, web_search: bool) -> CreatorDialogueCandidate:
        if self.kind == "web_research" and not web_search:
            raise ValueError("web research is unavailable")
        return parse_dialogue_candidate(
            self.model_dump(mode="python"),
            version=(
                WEB_DIALOGUE_CANDIDATE_VERSION
                if web_search
                else DIALOGUE_CANDIDATE_VERSION
            ),
        )


class CreatorAppraisalExperience(_StrictModel):
    first_person_gist: Annotated[str, StringConstraints(min_length=1, max_length=1024)]
    uncertainty: Summary | None = None
    remember: bool
    memory_summary: Summary | None = None

    @model_validator(mode="after")
    def validate_memory(self) -> CreatorAppraisalExperience:
        if self.remember != (self.memory_summary is not None):
            raise ValueError("explicit memory shape is invalid")
        return self

    def as_dialogue_experience(self) -> DialogueExperience:
        return DialogueExperience(
            first_person_gist=self.first_person_gist,
            uncertainty=self.uncertainty,
            memory_summary=self.memory_summary,
        )


class AppraisalVectorSignal(_StrictModel):
    suddenness: Annotated[int, Field(ge=0, le=4)]
    predictability: Annotated[int, Field(ge=0, le=4)]
    outcome_certainty: Annotated[int, Field(ge=0, le=4)]
    self_relevance: Annotated[int, Field(ge=0, le=4)]
    relationship_relevance: Annotated[int, Field(ge=0, le=4)]
    social_order_relevance: Annotated[int, Field(ge=0, le=4)]
    urgency: Annotated[int, Field(ge=0, le=4)]
    effort: Annotated[int, Field(ge=0, le=4)]
    intentionality: Annotated[int, Field(ge=0, le=4)]
    control: Annotated[int, Field(ge=0, le=4)]
    power: Annotated[int, Field(ge=0, le=4)]
    adjustment: Annotated[int, Field(ge=0, le=4)]
    ego_involvement: Annotated[int, Field(ge=0, le=4)]
    intrinsic_pleasantness: Annotated[int, Field(ge=-4, le=4)]
    goal_conduciveness: Annotated[int, Field(ge=-4, le=4)]
    self_compatibility: Annotated[int, Field(ge=-4, le=4)]
    norm_compatibility: Annotated[int, Field(ge=-4, le=4)]
    agency: Literal["self", "other", "shared", "circumstance", "unknown"]
    self_scope: Literal["none", "action", "global"]


class AppraisalEventSignalV1(_StrictModel):
    transition: Literal["new", "reinforce", "reappraise", "resolve"]
    episode_ref: ContextRef | None = None
    event_phase: Literal["anticipated", "ongoing", "realized", "averted"]
    gist: Annotated[str, StringConstraints(min_length=1, max_length=64)]
    appraisal: AppraisalVectorSignal
    basis_refs: tuple[ContextRef, ...] = Field(min_length=1, max_length=8)

    @model_validator(mode="after")
    def validate_signal(self) -> AppraisalEventSignalV1:
        if (self.transition == "new") != (self.episode_ref is None):
            raise ValueError("appraisal transition and episode reference do not match")
        return self


class AppraisalConcernSignal(_StrictModel):
    target: Literal["self_goal", "relationship", "social_order"]
    significance: Literal["peripheral", "direct", "core", "unknown"]
    direction: Literal[
        "major_setback",
        "setback",
        "unchanged",
        "progress",
        "fulfilled",
        "mixed",
        "unknown",
    ]


class AppraisalDemandSignal(_StrictModel):
    urgency: Literal["none", "can_wait", "soon", "immediate", "unknown"]
    effort: Literal["none", "light", "substantial", "extreme", "unknown"]


class AppraisalCausalitySignal(_StrictModel):
    agency: Literal["self", "other", "shared", "circumstance", "unknown"]
    intentionality: Literal[
        "accidental", "unclear", "deliberate", "not_applicable", "unknown"
    ]


class AppraisalCopingSignal(_StrictModel):
    response_access: Literal["none", "indirect", "direct", "resolved", "unknown"]
    power_balance: Literal[
        "overmatched", "limited", "balanced", "advantaged", "unknown"
    ]
    adjustment: Literal["blocked", "difficult", "manageable", "easy", "unknown"]


class AppraisalStandardsSignal(_StrictModel):
    self_compatibility: Literal[
        "violation", "tension", "aligned", "mixed", "not_applicable", "unknown"
    ]
    norm_compatibility: Literal[
        "violation", "tension", "aligned", "mixed", "not_applicable", "unknown"
    ]
    self_scope: Literal["none", "action", "global"]

    @model_validator(mode="after")
    def validate_scope(self) -> AppraisalStandardsSignal:
        conflict = self.self_compatibility in {"violation", "tension", "mixed"}
        if conflict != (self.self_scope != "none"):
            raise ValueError("self compatibility and scope do not match")
        return self


class AppraisalSemanticSignal(_StrictModel):
    concerns: tuple[AppraisalConcernSignal, ...] = Field(min_length=1, max_length=3)
    expectedness: Literal[
        "expected", "somewhat_unexpected", "expectation_broken", "unknown"
    ]
    outcome_certainty: Literal["open", "uncertain", "likely", "settled", "unknown"]
    intrinsic_quality: Literal[
        "strongly_aversive",
        "unpleasant",
        "neutral",
        "pleasant",
        "strongly_pleasant",
        "mixed",
        "unknown",
    ]
    self_involvement: Literal[
        "none", "limited", "important", "identity_level", "unknown"
    ]
    demand: AppraisalDemandSignal | None = None
    causality: AppraisalCausalitySignal | None = None
    coping: AppraisalCopingSignal | None = None
    standards: AppraisalStandardsSignal | None = None

    @model_validator(mode="after")
    def validate_concerns(self) -> AppraisalSemanticSignal:
        if len({item.target for item in self.concerns}) != len(self.concerns):
            raise ValueError("appraisal concern targets must be unique")
        return self


class AppraisalEventSignalV2(_StrictModel):
    transition: Literal["new", "reinforce", "reappraise", "resolve"]
    episode_ref: ContextRef | None = None
    event_phase: Literal["anticipated", "ongoing", "realized", "averted"]
    gist: Annotated[str, StringConstraints(min_length=1, max_length=64)]
    change_from_previous: Literal[
        "improved", "unchanged", "worsened", "mixed", "unknown"
    ] | None = None
    appraisal: AppraisalSemanticSignal
    basis_refs: tuple[ContextRef, ...] = Field(min_length=1, max_length=8)

    @model_validator(mode="after")
    def validate_signal(self) -> AppraisalEventSignalV2:
        is_new = self.transition == "new"
        if is_new != (self.episode_ref is None):
            raise ValueError("appraisal transition and episode reference do not match")
        if is_new != (self.change_from_previous is None):
            raise ValueError("appraisal transition and trajectory do not match")
        return self


class CreatorAppraisalCandidate(_StrictModel):
    experience: CreatorAppraisalExperience | None = None
    appraisal: AppraisalEventSignalV2 | None = None
    relationship_events: tuple[DialogueCompactChange, ...] = Field(
        default=(), max_length=4
    )

    @property
    def schema_version(self) -> str:
        return CREATOR_APPRAISAL_CANDIDATE_VERSION

    @model_validator(mode="after")
    def validate_scope(self) -> CreatorAppraisalCandidate:
        if any(change.op not in _APPRAISAL_OPS for change in self.relationship_events):
            raise ValueError("appraisal branch contains an out-of-scope operation")
        if self.relationship_events and self.experience is None:
            raise ValueError("relationship events require an experience")
        if (
            self.experience is None
            and self.appraisal is None
            and not self.relationship_events
        ):
            raise ValueError("appraisal is empty")
        return self


class CreatorDialogueAggregate(_StrictModel):
    schema_version: Literal["armi.creator-dialogue-aggregate.v3"]
    outcome: Literal["complete", "response_only", "internal_only"]
    response: CreatorResponseCandidate | None = None
    appraisal: CreatorAppraisalCandidate | None = None

    @model_validator(mode="after")
    def validate_outcome(self) -> CreatorDialogueAggregate:
        expected = (
            "complete"
            if self.response is not None and self.appraisal is not None
            else "response_only"
            if self.response is not None
            else "internal_only"
            if self.appraisal is not None
            else None
        )
        if expected is None or self.outcome != expected:
            raise ValueError("aggregate outcome does not match branches")
        return self


_RESPONSE_ADAPTER = TypeAdapter(CreatorResponseCandidate)
_APPRAISAL_ADAPTER = TypeAdapter(CreatorAppraisalCandidate)
_AGGREGATE_ADAPTER = TypeAdapter(CreatorDialogueAggregate)


def creator_response_schema(*, web_search: bool = True) -> dict[str, object]:
    schema = cast(dict[str, object], _RESPONSE_ADAPTER.json_schema())
    if not web_search:
        properties = cast(dict[str, object], schema["properties"])
        kind = cast(dict[str, object], properties["kind"])
        kind["enum"] = [
            item for item in cast(list[str], kind["enum"]) if item != "web_research"
        ]
    return schema


def creator_appraisal_schema() -> dict[str, object]:
    return cast(dict[str, object], _APPRAISAL_ADAPTER.json_schema())


def creator_aggregate_schema() -> dict[str, object]:
    return cast(dict[str, object], _AGGREGATE_ADAPTER.json_schema())


def parse_creator_response(value: object) -> CreatorResponseCandidate:
    return _RESPONSE_ADAPTER.validate_python(strict_model_value(value), strict=True)


def parse_creator_appraisal(
    value: object,
    *,
    allowed_context_refs: frozenset[str],
) -> CreatorAppraisalCandidate:
    candidate = _APPRAISAL_ADAPTER.validate_python(
        strict_model_value(value), strict=True
    )
    refs: set[str] = (
        set(candidate.appraisal.basis_refs)
        if candidate.appraisal is not None
        else set()
    )
    if candidate.appraisal is not None and candidate.appraisal.episode_ref is not None:
        refs.add(candidate.appraisal.episode_ref)
    for change in candidate.relationship_events:
        refs.update(
            ref for ref in (change.target_ref, change.related_ref) if ref is not None
        )
    if not refs.issubset(allowed_context_refs):
        raise ValueError("appraisal references unavailable context")
    return candidate


def parse_creator_aggregate(value: object) -> CreatorDialogueAggregate:
    return _AGGREGATE_ADAPTER.validate_python(strict_model_value(value), strict=True)


__all__ = (
    "CREATOR_APPRAISAL_CANDIDATE_VERSION",
    "CREATOR_APPRAISAL_INSTRUCTIONS",
    "CREATOR_DIALOGUE_AGGREGATE_VERSION",
    "CREATOR_RESPONSE_CANDIDATE_VERSION",
    "CREATOR_RESPONSE_INSTRUCTIONS",
    "AppraisalEventSignalV1",
    "AppraisalEventSignalV2",
    "AppraisalSemanticSignal",
    "AppraisalVectorSignal",
    "CreatorAppraisalCandidate",
    "CreatorDialogueAggregate",
    "CreatorResponseCandidate",
    "creator_aggregate_schema",
    "creator_appraisal_schema",
    "creator_response_schema",
    "parse_creator_aggregate",
    "parse_creator_appraisal",
    "parse_creator_response",
)
