"""Creator actions share one semantic contract across text and voice."""

# ruff: noqa: RUF001

from __future__ import annotations

from typing import Annotated, Literal, cast

from armi_mind.api import MIND_COGNITIVE_INSTRUCTIONS, ConcernChange
from armi_mood.api import AppraisalEventSignalV2
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, TypeAdapter

from ._creator_appraisal_contract import (
    CreatorAppraisalExperience,
)
from ._creator_changes import CreatorChange, change_context_refs
from ._dialogue_contract import ContextRef
from ._expression_instructions import CONVERSATIONAL_EXPRESSION_INSTRUCTIONS
from ._strict_model_json import strict_model_value

CREATOR_COGNITIVE_ACT_VERSION = "armi.creator-cognitive-act-candidate.v5"
CREATOR_VOICE_ACT_VERSION = "armi.creator-voice-act-candidate.v5"

CREATOR_COGNITIVE_ACT_INSTRUCTIONS = (
    f"""一次完成对 Creator 输入的认知：决定行动，以及是否形成经历、评价、关系、承诺或资料变化。
拒绝、需要信息、延期和没有变化也可以附带表达；没有表达时保持沉默。
只依据冻结 Context；不虚构主体身份、权限、情绪数值或现实执行结果。
只有 Creator 明确要求记住时才提出记忆摘要；评价使用语义标签，保留来源与不确定性。
{MIND_COGNITIVE_INSTRUCTIONS}
"""
    + CONVERSATIONAL_EXPRESSION_INSTRUCTIONS
)
CREATOR_VOICE_ACT_INSTRUCTIONS = CREATOR_COGNITIVE_ACT_INSTRUCTIONS + (
    "实时语音采用相同业务语义及紧凑顶层字段，表达最多 60 字。"
)


class _StrictModel(BaseModel, frozen=True):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


Content = Annotated[str, StringConstraints(min_length=1, max_length=65536)]
RecordKind = Literal[
    "activity", "conversation", "material", "memory", "relationship", "self_change"
]


class ReplyDecision(_StrictModel, frozen=True):
    kind: Literal["reply"]
    content: Content


class TerminalDecision(_StrictModel, frozen=True):
    kind: Literal["decline", "no_action", "no_change", "defer", "need_information"]
    content: Content | None = None


class ExactLifeQueryDecision(_StrictModel, frozen=True):
    kind: Literal["exact_life_query"]
    record_kind: RecordKind
    query: Annotated[str, StringConstraints(min_length=1, max_length=1024)] | None = (
        None
    )


class WebResearchDecision(_StrictModel, frozen=True):
    kind: Literal["web_research"]
    query: Annotated[str, StringConstraints(min_length=1, max_length=16384)]


class VisualObservationDecision(_StrictModel, frozen=True):
    kind: Literal["visual_observation"]
    source_kind: Literal["camera", "screen"]


Decision = Annotated[
    ReplyDecision
    | TerminalDecision
    | ExactLifeQueryDecision
    | WebResearchDecision
    | VisualObservationDecision,
    Field(discriminator="kind"),
]


class CreatorCognitiveActCandidate(_StrictModel, frozen=True):
    concern_changes: tuple[ConcernChange, ...] = Field(default=(), max_length=4)
    decision: Decision
    experience: CreatorAppraisalExperience | None = None
    appraisal: AppraisalEventSignalV2 | None = None
    changes: tuple[CreatorChange, ...] = Field(default=(), max_length=8)

    @property
    def schema_version(self) -> str:
        return CREATOR_COGNITIVE_ACT_VERSION

    @property
    def kind(self):
        return self.decision.kind

    @property
    def content(self) -> str | None:
        return (
            self.decision.content
            if isinstance(self.decision, (ReplyDecision, TerminalDecision))
            else None
        )

    @property
    def record_kind(self) -> RecordKind | None:
        return (
            self.decision.record_kind
            if isinstance(self.decision, ExactLifeQueryDecision)
            else None
        )

    @property
    def query(self) -> str | None:
        return (
            self.decision.query
            if isinstance(self.decision, WebResearchDecision)
            else None
        )

    @property
    def source_kind(self) -> Literal["camera", "screen"] | None:
        return (
            self.decision.source_kind
            if isinstance(self.decision, VisualObservationDecision)
            else None
        )


class VoiceReplyDecision(ReplyDecision, frozen=True):
    content: Annotated[str, StringConstraints(min_length=1, max_length=60)]


class VoiceTerminalDecision(TerminalDecision, frozen=True):
    content: Annotated[str, StringConstraints(min_length=1, max_length=60)] | None = (
        None
    )


VoiceDecision = Annotated[
    VoiceReplyDecision
    | VoiceTerminalDecision
    | ExactLifeQueryDecision
    | WebResearchDecision
    | VisualObservationDecision,
    Field(discriminator="kind"),
]


class CreatorVoiceActCandidate(CreatorCognitiveActCandidate, frozen=True):
    decision: VoiceDecision = Field(alias="d")
    experience: CreatorAppraisalExperience | None = Field(default=None, alias="exp")
    appraisal: AppraisalEventSignalV2 | None = Field(default=None, alias="app")
    changes: tuple[CreatorChange, ...] = Field(default=(), max_length=8, alias="ops")

    @property
    def schema_version(self) -> str:
        return CREATOR_VOICE_ACT_VERSION


_ACT = TypeAdapter(CreatorCognitiveActCandidate)
_VOICE = TypeAdapter(CreatorVoiceActCandidate)


def creator_cognitive_act_schema(*, web_search: bool = True) -> dict[str, object]:
    schema = _ACT.json_schema()
    if not web_search:
        decision = schema["properties"]["decision"]
        decision["oneOf"] = [
            item
            for item in decision["oneOf"]
            if item["$ref"] != "#/$defs/WebResearchDecision"
        ]
        decision["discriminator"]["mapping"].pop("web_research")
        schema["$defs"].pop("WebResearchDecision")
    return cast(dict[str, object], schema)


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
        refs.update(change_context_refs(change))
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
    candidate = _VOICE.validate_python(strict_model_value(value), strict=True)
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
