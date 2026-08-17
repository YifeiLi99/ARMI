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
CREATOR_APPRAISAL_CANDIDATE_VERSION = "armi.creator-appraisal-candidate.v1"
CREATOR_DIALOGUE_AGGREGATE_VERSION = "armi.creator-dialogue-aggregate.v1"

CREATOR_RESPONSE_INSTRUCTIONS = """\
你只负责本轮对 Creator 的表达与明确行动决定。根据冻结资料独立决定回复、拒绝、沉默、延后、追问、精确生活查询或公共网页研究。
不得生成 Experience、心情、关系、记忆、Self、Mind 或主体 Prompt。changes 只允许 Creator 明确要求的 material.* 与 codex.request；不要因为资料重要就顺手保存记忆。
只输出给定 JSON Schema，不解释 Schema，不输出额外文字。"""

CREATOR_APPRAISAL_INSTRUCTIONS = """\
你只负责判断本轮输入是否真正成为 ARMI 的主观经历，以及它带来的有限情绪、关系或承诺事件。你与表达分支并行，不能假设 ARMI 将说什么。
不得生成对外回复、查询、委托、资料动作、完整 MoodState、Self、Mind、主体 Prompt，也不得淡化、遗忘或改写既有记忆。只有 Creator 在当前输入中明确要求“记住”时，remember 才能为 true 并提供 memory_summary。
情绪只返回本轮事件信号；最终 Mood 由 Runtime 的 Mood Owner 演算。只输出给定 JSON Schema，不输出额外文字。"""


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


class AffectiveEventSignal(_StrictModel):
    valence: Literal["negative", "neutral", "positive", "mixed"]
    activation: Literal["low", "medium", "high"]
    intensity: Literal["low", "medium", "high"]
    emotions: tuple[Summary, ...] = Field(max_length=3)
    mood_tendency: Summary | None = None
    basis_refs: tuple[ContextRef, ...] = Field(min_length=1, max_length=8)

    @model_validator(mode="after")
    def validate_signal(self) -> AffectiveEventSignal:
        if len(self.emotions) != len(set(self.emotions)):
            raise ValueError("affective emotions contain duplicates")
        if (
            self.valence == "neutral"
            and not self.emotions
            and self.mood_tendency is not None
        ):
            raise ValueError("neutral empty signal cannot replace mood")
        return self


class CreatorAppraisalCandidate(_StrictModel):
    experience: CreatorAppraisalExperience | None = None
    affect: AffectiveEventSignal | None = None
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
            and self.affect is None
            and not self.relationship_events
        ):
            raise ValueError("appraisal is empty")
        return self


class CreatorDialogueAggregate(_StrictModel):
    schema_version: Literal["armi.creator-dialogue-aggregate.v1"]
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
        set(candidate.affect.basis_refs) if candidate.affect is not None else set()
    )
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
    "AffectiveEventSignal",
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
