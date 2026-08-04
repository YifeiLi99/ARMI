"""Compact model output contract for ordinary Creator dialogue."""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, TypeAdapter

DIALOGUE_CANDIDATE_VERSION = "armi.creator-dialogue-candidate.v1"
WEB_DIALOGUE_CANDIDATE_VERSION = "armi.creator-dialogue-candidate.v2"

Summary = Annotated[str, StringConstraints(min_length=1, max_length=512)]


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class DialogueExperience(_StrictModel):
    first_person_gist: Annotated[
        str,
        StringConstraints(min_length=1, max_length=1024),
    ]
    uncertainty: Summary | None = None


class CreatorDialogueCandidate(_StrictModel):
    """A subjective dialogue choice; wire metadata belongs to the adapter."""

    @property
    def schema_version(self) -> str:
        raise NotImplementedError


class _CreatorDialogueCandidateV1(CreatorDialogueCandidate):
    @property
    def schema_version(self) -> str:
        return DIALOGUE_CANDIDATE_VERSION


class _CreatorDialogueCandidateV2(CreatorDialogueCandidate):
    @property
    def schema_version(self) -> str:
        return WEB_DIALOGUE_CANDIDATE_VERSION


class DialogueReplyDecision(_CreatorDialogueCandidateV1):
    kind: Literal["reply"]
    content: Annotated[str, StringConstraints(min_length=1, max_length=65536)]
    experience: DialogueExperience | None = None


class DialogueTerminalDecision(_CreatorDialogueCandidateV1):
    kind: Literal[
        "decline",
        "no_action",
        "no_change",
        "defer",
        "need_information",
    ]


DialogueDecision = Annotated[
    DialogueReplyDecision | DialogueTerminalDecision,
    Field(discriminator="kind"),
]


class DialogueReplyDecisionV2(_CreatorDialogueCandidateV2):
    kind: Literal["reply"]
    content: Annotated[str, StringConstraints(min_length=1, max_length=65536)]
    experience: DialogueExperience | None = None


class DialogueTerminalDecisionV2(_CreatorDialogueCandidateV2):
    kind: Literal[
        "decline",
        "no_action",
        "no_change",
        "defer",
        "need_information",
    ]


class DialogueWebResearchDecision(_CreatorDialogueCandidateV2):
    kind: Literal["web_research"]
    query: Annotated[str, StringConstraints(min_length=1, max_length=16384)]


DialogueDecisionV2 = Annotated[
    DialogueReplyDecisionV2 | DialogueTerminalDecisionV2 | DialogueWebResearchDecision,
    Field(discriminator="kind"),
]

_ADAPTER_V1: TypeAdapter[DialogueDecision] = TypeAdapter(DialogueDecision)
_ADAPTER_V2: TypeAdapter[DialogueDecisionV2] = TypeAdapter(DialogueDecisionV2)


def dialogue_candidate_schema(
    version: str = DIALOGUE_CANDIDATE_VERSION,
) -> dict[str, Any]:
    if version == DIALOGUE_CANDIDATE_VERSION:
        return _ADAPTER_V1.json_schema()
    if version == WEB_DIALOGUE_CANDIDATE_VERSION:
        return _ADAPTER_V2.json_schema()
    raise ValueError("unsupported dialogue candidate version")


def parse_dialogue_candidate(
    value: object,
    *,
    version: str = DIALOGUE_CANDIDATE_VERSION,
) -> CreatorDialogueCandidate:
    if version == DIALOGUE_CANDIDATE_VERSION:
        return _ADAPTER_V1.validate_python(value, strict=True)
    if version == WEB_DIALOGUE_CANDIDATE_VERSION:
        return _ADAPTER_V2.validate_python(value, strict=True)
    raise ValueError("unsupported dialogue candidate version")


__all__ = (
    "DIALOGUE_CANDIDATE_VERSION",
    "WEB_DIALOGUE_CANDIDATE_VERSION",
    "CreatorDialogueCandidate",
    "DialogueExperience",
    "DialogueReplyDecision",
    "DialogueReplyDecisionV2",
    "DialogueTerminalDecision",
    "DialogueTerminalDecisionV2",
    "DialogueWebResearchDecision",
    "dialogue_candidate_schema",
    "parse_dialogue_candidate",
)
