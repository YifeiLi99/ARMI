"""Compact model output contract for ordinary Creator dialogue."""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    TypeAdapter,
    model_validator,
)

DIALOGUE_CANDIDATE_VERSION = "armi.creator-dialogue-candidate.v3"
WEB_DIALOGUE_CANDIDATE_VERSION = "armi.creator-dialogue-candidate.v4"

Summary = Annotated[str, StringConstraints(min_length=1, max_length=512)]
ContextRef = Annotated[
    str,
    StringConstraints(pattern=r"^ctx:[1-9][0-9]{0,2}$", max_length=7),
]


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class DialogueExperience(_StrictModel):
    first_person_gist: Annotated[
        str,
        StringConstraints(min_length=1, max_length=1024),
    ]
    uncertainty: Summary | None = None
    memory_summary: Summary | None = None


class DialogueMemoryChange(_StrictModel):
    action: Literal["recall", "fade", "forget", "reinterpret"]
    memory_ref: ContextRef
    summary: Summary | None = None
    uncertainty: Summary | None = None
    related_memory_ref: ContextRef | None = None
    relation_kind: Literal["supports", "contradicts", "reinterprets"] | None = None

    @model_validator(mode="after")
    def validate_shape(self) -> DialogueMemoryChange:
        if self.action == "reinterpret":
            if self.summary is None:
                raise ValueError("reinterpret requires a summary")
            if (self.related_memory_ref is None) != (self.relation_kind is None):
                raise ValueError("memory relation is incomplete")
            if self.related_memory_ref == self.memory_ref:
                raise ValueError("memory cannot relate to itself")
        elif any(
            value is not None
            for value in (
                self.summary,
                self.uncertainty,
                self.related_memory_ref,
                self.relation_kind,
            )
        ):
            raise ValueError("only reinterpret accepts new meaning")
        return self


class DialogueRelationshipFact(_StrictModel):
    kind: Literal["party_expression"]
    summary: Summary


class DialogueRelationshipBoundary(_StrictModel):
    party: Literal["armi", "creator"]
    kind: Literal["contact", "address", "privacy", "disclosure", "exit"]
    action: Literal["refuse", "restrict", "end_contact"]
    summary: Summary

    @model_validator(mode="after")
    def validate_shape(self) -> DialogueRelationshipBoundary:
        if (self.action == "end_contact") != (self.kind == "exit"):
            raise ValueError("only an exit boundary can end contact")
        return self


class DialogueRelationshipChange(_StrictModel):
    interpretation: Summary | None = None
    fact: DialogueRelationshipFact | None = None
    boundary: DialogueRelationshipBoundary | None = None

    @model_validator(mode="after")
    def validate_shape(self) -> DialogueRelationshipChange:
        if self.interpretation is None and self.fact is None and self.boundary is None:
            raise ValueError("relationship change is empty")
        return self


class CreatorDialogueCandidate(_StrictModel):
    """A subjective dialogue choice; wire metadata belongs to the adapter."""

    @property
    def schema_version(self) -> str:
        raise NotImplementedError


class _CreatorDialogueCandidateV3(CreatorDialogueCandidate):
    @property
    def schema_version(self) -> str:
        return DIALOGUE_CANDIDATE_VERSION


class _CreatorDialogueCandidateV4(CreatorDialogueCandidate):
    @property
    def schema_version(self) -> str:
        return WEB_DIALOGUE_CANDIDATE_VERSION


class DialogueReplyDecision(_CreatorDialogueCandidateV3):
    kind: Literal["reply"]
    content: Annotated[str, StringConstraints(min_length=1, max_length=65536)]
    experience: DialogueExperience | None = None
    memory_change: DialogueMemoryChange | None = None
    relationship_change: DialogueRelationshipChange | None = None

    @model_validator(mode="after")
    def validate_relationship_source(self) -> DialogueReplyDecision:
        if self.relationship_change is not None and self.experience is None:
            raise ValueError("relationship change requires an experience")
        return self


class DialogueTerminalDecision(_CreatorDialogueCandidateV3):
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


class DialogueReplyDecisionV4(_CreatorDialogueCandidateV4):
    kind: Literal["reply"]
    content: Annotated[str, StringConstraints(min_length=1, max_length=65536)]
    experience: DialogueExperience | None = None
    memory_change: DialogueMemoryChange | None = None
    relationship_change: DialogueRelationshipChange | None = None

    @model_validator(mode="after")
    def validate_relationship_source(self) -> DialogueReplyDecisionV4:
        if self.relationship_change is not None and self.experience is None:
            raise ValueError("relationship change requires an experience")
        return self


class DialogueTerminalDecisionV4(_CreatorDialogueCandidateV4):
    kind: Literal[
        "decline",
        "no_action",
        "no_change",
        "defer",
        "need_information",
    ]


class DialogueWebResearchDecision(_CreatorDialogueCandidateV4):
    kind: Literal["web_research"]
    query: Annotated[str, StringConstraints(min_length=1, max_length=16384)]


DialogueDecisionV4 = Annotated[
    DialogueReplyDecisionV4 | DialogueTerminalDecisionV4 | DialogueWebResearchDecision,
    Field(discriminator="kind"),
]

_ADAPTER_V3: TypeAdapter[DialogueDecision] = TypeAdapter(DialogueDecision)
_ADAPTER_V4: TypeAdapter[DialogueDecisionV4] = TypeAdapter(DialogueDecisionV4)


def dialogue_candidate_schema(
    version: str = DIALOGUE_CANDIDATE_VERSION,
) -> dict[str, Any]:
    if version == DIALOGUE_CANDIDATE_VERSION:
        return _ADAPTER_V3.json_schema()
    if version == WEB_DIALOGUE_CANDIDATE_VERSION:
        return _ADAPTER_V4.json_schema()
    raise ValueError("unsupported dialogue candidate version")


def parse_dialogue_candidate(
    value: object,
    *,
    version: str = DIALOGUE_CANDIDATE_VERSION,
) -> CreatorDialogueCandidate:
    if version == DIALOGUE_CANDIDATE_VERSION:
        return _ADAPTER_V3.validate_python(value, strict=True)
    if version == WEB_DIALOGUE_CANDIDATE_VERSION:
        return _ADAPTER_V4.validate_python(value, strict=True)
    raise ValueError("unsupported dialogue candidate version")


__all__ = (
    "DIALOGUE_CANDIDATE_VERSION",
    "WEB_DIALOGUE_CANDIDATE_VERSION",
    "CreatorDialogueCandidate",
    "DialogueExperience",
    "DialogueMemoryChange",
    "DialogueRelationshipBoundary",
    "DialogueRelationshipChange",
    "DialogueRelationshipFact",
    "DialogueReplyDecision",
    "DialogueReplyDecisionV4",
    "DialogueTerminalDecision",
    "DialogueTerminalDecisionV4",
    "DialogueWebResearchDecision",
    "dialogue_candidate_schema",
    "parse_dialogue_candidate",
)
