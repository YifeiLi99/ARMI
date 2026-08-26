# ruff: noqa: E741, RUF001

"""Single-call Creator cognition contracts.

The verbose contract is the canonical internal meaning.  The compact voice
contract is only a wire representation and is expanded immediately after the
provider response is received.
"""

from __future__ import annotations

from typing import Annotated, Literal, cast

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    TypeAdapter,
    model_validator,
)

from ._creator_appraisal_contract import (
    AppraisalEventSignalV2,
    CreatorAppraisalExperience,
)
from ._dialogue_contract import (
    CompactChangeOp,
    ContextRef,
    DialogueCompactChange,
    Summary,
)
from ._strict_model_json import strict_model_value

CREATOR_COGNITIVE_ACT_VERSION = "armi.creator-cognitive-act-candidate.v1"
CREATOR_VOICE_ACT_VERSION = "armi.creator-voice-act-candidate.v1"

CREATOR_COGNITIVE_ACT_INSTRUCTIONS = """\
你要一次完成本轮对 Creator 输入的完整认知，只输出一份严格 JSON：同时决定表达或查询、主观经历、Mood v3 语义评价，以及关系、承诺、资料或 Codex 提议。
模型不得填写主体 ID、主体版本、权限结果、情绪数值、VAD、强度、持续时间、半衰期或任何现实执行结果。Runtime 与各领域 Owner 会分别校验提议，并最多提交一次主体变化。
kind=reply 时只填写 content；kind=exact_life_query 时只填写 record_kind；kind=web_research 时只填写 query；其他 kind 的三个字段都必须为空。只有 Creator 在当前输入中明确要求记住时，experience.remember 才可为 true 且必须给出 memory_summary。
appraisal 只能使用 Schema 中的语义标签和冻结 Context 引用。new 不引用既有 episode；reinforce、reappraise、resolve 必须引用冻结资料。changes 最多 8 项，只允许关系、承诺、资料和 Codex 操作。
不要解释 Schema，不要输出 JSON 以外的文字。"""

CREATOR_VOICE_ACT_INSTRUCTIONS = """\
实时语音。一次完成本轮认知，只输出 armi.creator-voice-act-candidate.v1 的严格紧凑 JSON。它与文字认知语义完全相同，只缩短字段名；回复 text 最多 60 个汉字。关闭工具，不输出解释或额外文字。"""


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


ResponseKind = Literal[
    "reply",
    "decline",
    "no_action",
    "no_change",
    "defer",
    "need_information",
    "exact_life_query",
    "web_research",
]
RecordKind = Literal[
    "activity", "conversation", "material", "memory", "relationship", "self_change"
]
_OPS = frozenset(
    {
        "material.create",
        "material.update",
        "material.visibility",
        "material.delete",
        "codex.request",
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


class CreatorCognitiveActCandidate(_StrictModel):
    kind: ResponseKind
    content: (
        Annotated[str, StringConstraints(min_length=1, max_length=65536)] | None
    ) = None
    record_kind: RecordKind | None = None
    query: Annotated[str, StringConstraints(min_length=1, max_length=16384)] | None = (
        None
    )
    experience: CreatorAppraisalExperience | None = None
    appraisal: AppraisalEventSignalV2 | None = None
    changes: tuple[DialogueCompactChange, ...] = Field(default=(), max_length=8)

    @property
    def schema_version(self) -> str:
        return CREATOR_COGNITIVE_ACT_VERSION

    @model_validator(mode="after")
    def validate_act(self) -> CreatorCognitiveActCandidate:
        if any(change.op not in _OPS for change in self.changes):
            raise ValueError("creator act contains an out-of-scope operation")
        if (
            any(
                change.op.startswith(("relationship.", "commitment."))
                for change in self.changes
            )
            and self.experience is None
        ):
            raise ValueError(
                "relationship and commitment changes require an experience"
            )
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
            ):
                raise ValueError("life query shape is invalid")
        elif self.kind == "web_research":
            if (
                self.query is None
                or self.content is not None
                or self.record_kind is not None
            ):
                raise ValueError("web research shape is invalid")
        elif any(
            value is not None for value in (self.content, self.record_kind, self.query)
        ):
            raise ValueError("terminal response shape is invalid")
        return self


class VoiceExperience(_StrictModel):
    g: Annotated[str, StringConstraints(min_length=1, max_length=1024)]
    u: Summary | None = None
    m: Summary | None = None


class VoiceConcern(_StrictModel):
    t: Literal["self_goal", "relationship", "social_order"]
    s: Literal["peripheral", "direct", "core", "unknown"]
    d: Literal[
        "major_setback",
        "setback",
        "unchanged",
        "progress",
        "fulfilled",
        "mixed",
        "unknown",
    ]


class VoiceDemand(_StrictModel):
    u: Literal["none", "can_wait", "soon", "immediate", "unknown"]
    e: Literal["none", "light", "substantial", "extreme", "unknown"]


class VoiceCausality(_StrictModel):
    a: Literal["self", "other", "shared", "circumstance", "unknown"]
    i: Literal["accidental", "unclear", "deliberate", "not_applicable", "unknown"]


class VoiceCoping(_StrictModel):
    r: Literal["none", "indirect", "direct", "resolved", "unknown"]
    p: Literal["overmatched", "limited", "balanced", "advantaged", "unknown"]
    a: Literal["blocked", "difficult", "manageable", "easy", "unknown"]


class VoiceStandards(_StrictModel):
    s: Literal["violation", "tension", "aligned", "mixed", "not_applicable", "unknown"]
    n: Literal["violation", "tension", "aligned", "mixed", "not_applicable", "unknown"]
    o: Literal["none", "action", "global"]


class VoiceSemanticAppraisal(_StrictModel):
    c: tuple[VoiceConcern, ...] = Field(min_length=1, max_length=3)
    e: Literal["expected", "somewhat_unexpected", "expectation_broken", "unknown"]
    o: Literal["open", "uncertain", "likely", "settled", "unknown"]
    q: Literal[
        "strongly_aversive",
        "unpleasant",
        "neutral",
        "pleasant",
        "strongly_pleasant",
        "mixed",
        "unknown",
    ]
    i: Literal["none", "limited", "important", "identity_level", "unknown"]
    d: VoiceDemand | None = None
    a: VoiceCausality | None = None
    p: VoiceCoping | None = None
    s: VoiceStandards | None = None


class VoiceAppraisal(_StrictModel):
    t: Literal["new", "reinforce", "reappraise", "resolve"]
    r: ContextRef | None = None
    p: Literal["anticipated", "ongoing", "realized", "averted"]
    g: Annotated[str, StringConstraints(min_length=1, max_length=64)]
    d: Literal["improved", "unchanged", "worsened", "mixed", "unknown"] | None = None
    a: VoiceSemanticAppraisal
    b: tuple[ContextRef, ...] = Field(min_length=1, max_length=8)

    def expand(self) -> AppraisalEventSignalV2:
        value = self.a
        return AppraisalEventSignalV2.model_validate(
            {
                "transition": self.t,
                "episode_ref": self.r,
                "event_phase": self.p,
                "gist": self.g,
                "change_from_previous": self.d,
                "appraisal": {
                    "concerns": tuple(
                        {"target": item.t, "significance": item.s, "direction": item.d}
                        for item in value.c
                    ),
                    "expectedness": value.e,
                    "outcome_certainty": value.o,
                    "intrinsic_quality": value.q,
                    "self_involvement": value.i,
                    "demand": None
                    if value.d is None
                    else {"urgency": value.d.u, "effort": value.d.e},
                    "causality": None
                    if value.a is None
                    else {"agency": value.a.a, "intentionality": value.a.i},
                    "coping": None
                    if value.p is None
                    else {
                        "response_access": value.p.r,
                        "power_balance": value.p.p,
                        "adjustment": value.p.a,
                    },
                    "standards": None
                    if value.s is None
                    else {
                        "self_compatibility": value.s.s,
                        "norm_compatibility": value.s.n,
                        "self_scope": value.s.o,
                    },
                },
                "basis_refs": self.b,
            },
            strict=True,
        )


class VoiceChange(_StrictModel):
    o: CompactChangeOp
    r: ContextRef | None = None
    l: ContextRef | None = None
    f: Summary | None = None
    p: Literal["armi", "creator"] | None = None
    t: Annotated[str, StringConstraints(min_length=1, max_length=65536)] | None = None
    i: tuple[Summary, ...] | None = Field(default=None, max_length=16)
    m: dict[
        Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9._-]{0,63}$")],
        Annotated[str, StringConstraints(max_length=2048)],
    ] = Field(default_factory=dict, max_length=32)

    def expand(self) -> DialogueCompactChange:
        return DialogueCompactChange.model_validate(
            {
                "op": self.o,
                "target_ref": self.r,
                "related_ref": self.l,
                "field": self.f,
                "party": self.p,
                "text": self.t,
                "items": self.i,
                "metadata": self.m,
            },
            strict=True,
        )


class CreatorVoiceActCandidate(_StrictModel):
    k: ResponseKind
    text: Annotated[str, StringConstraints(min_length=1, max_length=60)] | None = None
    record: RecordKind | None = None
    query: Annotated[str, StringConstraints(min_length=1, max_length=16384)] | None = (
        None
    )
    exp: VoiceExperience | None = None
    app: VoiceAppraisal | None = None
    ops: tuple[VoiceChange, ...] = Field(default=(), max_length=8)

    def expand(self) -> CreatorCognitiveActCandidate:
        experience = (
            None
            if self.exp is None
            else CreatorAppraisalExperience(
                first_person_gist=self.exp.g,
                uncertainty=self.exp.u,
                remember=self.exp.m is not None,
                memory_summary=self.exp.m,
            )
        )
        return CreatorCognitiveActCandidate(
            kind=self.k,
            content=self.text,
            record_kind=self.record,
            query=self.query,
            experience=experience,
            appraisal=None if self.app is None else self.app.expand(),
            changes=tuple(item.expand() for item in self.ops),
        )


_ACT = TypeAdapter(CreatorCognitiveActCandidate)
_VOICE = TypeAdapter(CreatorVoiceActCandidate)


def creator_cognitive_act_schema(*, web_search: bool = True) -> dict[str, object]:
    schema = cast(dict[str, object], _ACT.json_schema())
    if not web_search:
        kind = cast(
            dict[str, object], cast(dict[str, object], schema["properties"])["kind"]
        )
        kind["enum"] = [
            item for item in cast(list[str], kind["enum"]) if item != "web_research"
        ]
    return schema


def creator_voice_act_schema() -> dict[str, object]:
    return cast(dict[str, object], _VOICE.json_schema())


def _check_refs(
    candidate: CreatorCognitiveActCandidate, allowed: frozenset[str]
) -> None:
    refs: set[ContextRef] = set()
    if candidate.appraisal is not None:
        refs.update(candidate.appraisal.basis_refs)
        if candidate.appraisal.episode_ref is not None:
            refs.add(candidate.appraisal.episode_ref)
    for change in candidate.changes:
        refs.update(
            ref for ref in (change.target_ref, change.related_ref) if ref is not None
        )
    if not refs.issubset(allowed):
        raise ValueError("creator act references unavailable context")


def parse_creator_cognitive_act(
    value: object, *, allowed_context_refs: frozenset[str], web_search: bool = True
) -> CreatorCognitiveActCandidate:
    candidate = _ACT.validate_python(strict_model_value(value), strict=True)
    if candidate.kind == "web_research" and not web_search:
        raise ValueError("web research is unavailable")
    _check_refs(candidate, allowed_context_refs)
    return candidate


def parse_creator_voice_act(
    value: object, *, allowed_context_refs: frozenset[str]
) -> CreatorCognitiveActCandidate:
    candidate = _VOICE.validate_python(strict_model_value(value), strict=True).expand()
    _check_refs(candidate, allowed_context_refs)
    return candidate


__all__ = (
    "CREATOR_COGNITIVE_ACT_INSTRUCTIONS",
    "CREATOR_COGNITIVE_ACT_VERSION",
    "CREATOR_VOICE_ACT_INSTRUCTIONS",
    "CREATOR_VOICE_ACT_VERSION",
    "CreatorCognitiveActCandidate",
    "CreatorVoiceActCandidate",
    "creator_cognitive_act_schema",
    "creator_voice_act_schema",
    "parse_creator_cognitive_act",
    "parse_creator_voice_act",
)
