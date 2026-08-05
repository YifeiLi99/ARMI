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

HISTORICAL_DIALOGUE_CANDIDATE_VERSION = "armi.creator-dialogue-candidate.v5"
HISTORICAL_WEB_DIALOGUE_CANDIDATE_VERSION = "armi.creator-dialogue-candidate.v6"
HISTORICAL_MATERIAL_DIALOGUE_CANDIDATE_VERSION = "armi.creator-dialogue-candidate.v7"
HISTORICAL_MATERIAL_WEB_DIALOGUE_CANDIDATE_VERSION = (
    "armi.creator-dialogue-candidate.v8"
)
DIALOGUE_CANDIDATE_VERSION = "armi.creator-dialogue-candidate.v9"
WEB_DIALOGUE_CANDIDATE_VERSION = "armi.creator-dialogue-candidate.v10"

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


class DialogueCommitmentChange(_StrictModel):
    action: Literal[
        "establish",
        "modify",
        "fulfill",
        "withdraw",
        "forget",
        "violate",
        "note_conflict",
    ]
    commitment_ref: ContextRef | None = None
    party: Literal["armi", "creator"] | None = None
    scope: Summary | None = None
    content: Annotated[str, StringConstraints(min_length=1, max_length=1024)] | None = (
        None
    )
    conflicts_with_ref: ContextRef | None = None
    event_summary: Summary

    @model_validator(mode="after")
    def validate_shape(self) -> DialogueCommitmentChange:
        if self.action == "establish":
            if (
                self.commitment_ref is not None
                or self.party is None
                or self.scope is None
                or self.content is None
            ):
                raise ValueError("establish commitment shape is invalid")
        elif self.action == "modify":
            if (
                self.commitment_ref is None
                or self.party is not None
                or (self.scope is None and self.content is None)
            ):
                raise ValueError("modify commitment shape is invalid")
        elif self.action == "note_conflict":
            if (
                self.commitment_ref is None
                or self.conflicts_with_ref is None
                or self.commitment_ref == self.conflicts_with_ref
                or self.party is not None
                or self.scope is not None
                or self.content is not None
            ):
                raise ValueError("commitment conflict shape is invalid")
        elif (
            self.commitment_ref is None
            or self.party is not None
            or self.scope is not None
            or self.content is not None
            or self.conflicts_with_ref is not None
        ):
            raise ValueError("commitment event shape is invalid")
        if (
            self.action not in {"establish", "modify", "note_conflict"}
            and self.conflicts_with_ref is not None
        ):
            raise ValueError("commitment conflict is not allowed for this action")
        if (
            self.commitment_ref is not None
            and self.commitment_ref == self.conflicts_with_ref
        ):
            raise ValueError("commitment cannot conflict with itself")
        return self


class DialogueRelationshipChange(_StrictModel):
    interpretation: Summary | None = None
    fact: DialogueRelationshipFact | None = None
    boundary: DialogueRelationshipBoundary | None = None
    commitment_change: DialogueCommitmentChange | None = None

    @model_validator(mode="after")
    def validate_shape(self) -> DialogueRelationshipChange:
        if (
            self.interpretation is None
            and self.fact is None
            and self.boundary is None
            and self.commitment_change is None
        ):
            raise ValueError("relationship change is empty")
        return self


class DialogueMaterialChangeV7(_StrictModel):
    action: Literal["create", "update"]
    material_ref: ContextRef | None = None
    material_kind: Literal["diary", "work", "collection", "draft"] | None = None
    title: Annotated[str, StringConstraints(min_length=1, max_length=256)]
    body: Annotated[str, StringConstraints(min_length=1, max_length=65536)]
    metadata: dict[
        Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9._-]{0,63}$")],
        Annotated[str, StringConstraints(max_length=512)],
    ] = Field(default_factory=dict, max_length=32)
    material_status: Literal["active", "archived"] = "active"

    @model_validator(mode="after")
    def validate_shape(self) -> DialogueMaterialChangeV7:
        if self.action == "create":
            if self.material_ref is not None or self.material_kind is None:
                raise ValueError("material create shape is invalid")
        elif self.material_ref is None or self.material_kind is not None:
            raise ValueError("material update shape is invalid")
        if (
            not self.title.strip()
            or "\x00" in self.title
            or not self.body.strip()
            or "\x00" in self.body
            or any("\x00" in value for value in self.metadata.values())
        ):
            raise ValueError("material content is invalid")
        return self


class DialogueMaterialContentChange(_StrictModel):
    action: Literal["create", "update"]
    material_ref: ContextRef | None = None
    material_kind: Literal["diary", "work", "collection", "draft"] | None = None
    title: Annotated[str, StringConstraints(min_length=1, max_length=256)]
    body: Annotated[str, StringConstraints(min_length=1, max_length=65536)]
    metadata: dict[
        Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9._-]{0,63}$")],
        Annotated[str, StringConstraints(max_length=512)],
    ] = Field(default_factory=dict, max_length=32)
    material_status: Literal["active", "archived"] = "active"

    @model_validator(mode="after")
    def validate_shape(self) -> DialogueMaterialContentChange:
        if self.action == "create":
            if self.material_ref is not None or self.material_kind is None:
                raise ValueError("material create shape is invalid")
        elif self.material_ref is None or self.material_kind is not None:
            raise ValueError("material update shape is invalid")
        if (
            not self.title.strip()
            or "\x00" in self.title
            or not self.body.strip()
            or "\x00" in self.body
            or any("\x00" in value for value in self.metadata.values())
        ):
            raise ValueError("material content is invalid")
        return self


class DialogueMaterialStateChange(_StrictModel):
    action: Literal["set_private", "set_creator_visible", "delete"]
    material_ref: ContextRef


DialogueMaterialChange = Annotated[
    DialogueMaterialContentChange | DialogueMaterialStateChange,
    Field(discriminator="action"),
]


class CreatorDialogueCandidate(_StrictModel):
    """A subjective dialogue choice; wire metadata belongs to the adapter."""

    @property
    def schema_version(self) -> str:
        raise NotImplementedError


class _CreatorDialogueCandidateV5(CreatorDialogueCandidate):
    @property
    def schema_version(self) -> str:
        return HISTORICAL_DIALOGUE_CANDIDATE_VERSION


class _CreatorDialogueCandidateV6(CreatorDialogueCandidate):
    @property
    def schema_version(self) -> str:
        return HISTORICAL_WEB_DIALOGUE_CANDIDATE_VERSION


class _CreatorDialogueCandidateV7(CreatorDialogueCandidate):
    @property
    def schema_version(self) -> str:
        return HISTORICAL_MATERIAL_DIALOGUE_CANDIDATE_VERSION


class _CreatorDialogueCandidateV8(CreatorDialogueCandidate):
    @property
    def schema_version(self) -> str:
        return HISTORICAL_MATERIAL_WEB_DIALOGUE_CANDIDATE_VERSION


class _CreatorDialogueCandidateV9(CreatorDialogueCandidate):
    @property
    def schema_version(self) -> str:
        return DIALOGUE_CANDIDATE_VERSION


class _CreatorDialogueCandidateV10(CreatorDialogueCandidate):
    @property
    def schema_version(self) -> str:
        return WEB_DIALOGUE_CANDIDATE_VERSION


class DialogueReplyDecisionV5(_CreatorDialogueCandidateV5):
    kind: Literal["reply"]
    content: Annotated[str, StringConstraints(min_length=1, max_length=65536)]
    experience: DialogueExperience | None = None
    memory_change: DialogueMemoryChange | None = None
    relationship_change: DialogueRelationshipChange | None = None

    @model_validator(mode="after")
    def validate_relationship_source(self) -> DialogueReplyDecisionV5:
        if self.relationship_change is not None and self.experience is None:
            raise ValueError("relationship change requires an experience")
        return self


class DialogueTerminalDecisionV5(_CreatorDialogueCandidateV5):
    kind: Literal[
        "decline",
        "no_action",
        "no_change",
        "defer",
        "need_information",
    ]


DialogueDecisionV5 = Annotated[
    DialogueReplyDecisionV5 | DialogueTerminalDecisionV5,
    Field(discriminator="kind"),
]


class DialogueReplyDecisionV6(_CreatorDialogueCandidateV6):
    kind: Literal["reply"]
    content: Annotated[str, StringConstraints(min_length=1, max_length=65536)]
    experience: DialogueExperience | None = None
    memory_change: DialogueMemoryChange | None = None
    relationship_change: DialogueRelationshipChange | None = None

    @model_validator(mode="after")
    def validate_relationship_source(self) -> DialogueReplyDecisionV6:
        if self.relationship_change is not None and self.experience is None:
            raise ValueError("relationship change requires an experience")
        return self


class DialogueTerminalDecisionV6(_CreatorDialogueCandidateV6):
    kind: Literal[
        "decline",
        "no_action",
        "no_change",
        "defer",
        "need_information",
    ]


class DialogueWebResearchDecision(_CreatorDialogueCandidateV6):
    kind: Literal["web_research"]
    query: Annotated[str, StringConstraints(min_length=1, max_length=16384)]


DialogueDecisionV6 = Annotated[
    DialogueReplyDecisionV6 | DialogueTerminalDecisionV6 | DialogueWebResearchDecision,
    Field(discriminator="kind"),
]


class DialogueReplyDecisionV7(_CreatorDialogueCandidateV7):
    kind: Literal["reply"]
    content: Annotated[str, StringConstraints(min_length=1, max_length=65536)]
    experience: DialogueExperience | None = None
    memory_change: DialogueMemoryChange | None = None
    relationship_change: DialogueRelationshipChange | None = None
    material_change: DialogueMaterialChangeV7 | None = None

    @model_validator(mode="after")
    def validate_relationship_source(self) -> DialogueReplyDecisionV7:
        if self.relationship_change is not None and self.experience is None:
            raise ValueError("relationship change requires an experience")
        return self


class DialogueTerminalDecisionV7(_CreatorDialogueCandidateV7):
    kind: Literal[
        "decline",
        "no_action",
        "no_change",
        "defer",
        "need_information",
    ]


DialogueDecisionV7 = Annotated[
    DialogueReplyDecisionV7 | DialogueTerminalDecisionV7,
    Field(discriminator="kind"),
]


class DialogueReplyDecisionV8(_CreatorDialogueCandidateV8):
    kind: Literal["reply"]
    content: Annotated[str, StringConstraints(min_length=1, max_length=65536)]
    experience: DialogueExperience | None = None
    memory_change: DialogueMemoryChange | None = None
    relationship_change: DialogueRelationshipChange | None = None
    material_change: DialogueMaterialChangeV7 | None = None

    @model_validator(mode="after")
    def validate_relationship_source(self) -> DialogueReplyDecisionV8:
        if self.relationship_change is not None and self.experience is None:
            raise ValueError("relationship change requires an experience")
        return self


class DialogueTerminalDecisionV8(_CreatorDialogueCandidateV8):
    kind: Literal[
        "decline",
        "no_action",
        "no_change",
        "defer",
        "need_information",
    ]


class DialogueWebResearchDecisionV8(_CreatorDialogueCandidateV8):
    kind: Literal["web_research"]
    query: Annotated[str, StringConstraints(min_length=1, max_length=16384)]


DialogueDecisionV8 = Annotated[
    DialogueReplyDecisionV8
    | DialogueTerminalDecisionV8
    | DialogueWebResearchDecisionV8,
    Field(discriminator="kind"),
]


class DialogueReplyDecision(_CreatorDialogueCandidateV9):
    kind: Literal["reply"]
    content: Annotated[str, StringConstraints(min_length=1, max_length=65536)]
    experience: DialogueExperience | None = None
    memory_change: DialogueMemoryChange | None = None
    relationship_change: DialogueRelationshipChange | None = None
    material_change: DialogueMaterialChange | None = None

    @model_validator(mode="after")
    def validate_relationship_source(self) -> DialogueReplyDecision:
        if self.relationship_change is not None and self.experience is None:
            raise ValueError("relationship change requires an experience")
        return self


class DialogueTerminalDecision(_CreatorDialogueCandidateV9):
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


class DialogueReplyDecisionV10(_CreatorDialogueCandidateV10):
    kind: Literal["reply"]
    content: Annotated[str, StringConstraints(min_length=1, max_length=65536)]
    experience: DialogueExperience | None = None
    memory_change: DialogueMemoryChange | None = None
    relationship_change: DialogueRelationshipChange | None = None
    material_change: DialogueMaterialChange | None = None

    @model_validator(mode="after")
    def validate_relationship_source(self) -> DialogueReplyDecisionV10:
        if self.relationship_change is not None and self.experience is None:
            raise ValueError("relationship change requires an experience")
        return self


class DialogueTerminalDecisionV10(_CreatorDialogueCandidateV10):
    kind: Literal[
        "decline",
        "no_action",
        "no_change",
        "defer",
        "need_information",
    ]


class DialogueWebResearchDecisionV10(_CreatorDialogueCandidateV10):
    kind: Literal["web_research"]
    query: Annotated[str, StringConstraints(min_length=1, max_length=16384)]


DialogueDecisionV10 = Annotated[
    DialogueReplyDecisionV10
    | DialogueTerminalDecisionV10
    | DialogueWebResearchDecisionV10,
    Field(discriminator="kind"),
]

_ADAPTER_V5: TypeAdapter[DialogueDecisionV5] = TypeAdapter(DialogueDecisionV5)
_ADAPTER_V6: TypeAdapter[DialogueDecisionV6] = TypeAdapter(DialogueDecisionV6)
_ADAPTER_V7: TypeAdapter[DialogueDecisionV7] = TypeAdapter(DialogueDecisionV7)
_ADAPTER_V8: TypeAdapter[DialogueDecisionV8] = TypeAdapter(DialogueDecisionV8)
_ADAPTER_V9: TypeAdapter[DialogueDecision] = TypeAdapter(DialogueDecision)
_ADAPTER_V10: TypeAdapter[DialogueDecisionV10] = TypeAdapter(DialogueDecisionV10)


def dialogue_candidate_schema(
    version: str = DIALOGUE_CANDIDATE_VERSION,
) -> dict[str, Any]:
    if version == DIALOGUE_CANDIDATE_VERSION:
        return _ADAPTER_V9.json_schema()
    if version == WEB_DIALOGUE_CANDIDATE_VERSION:
        return _ADAPTER_V10.json_schema()
    if version == HISTORICAL_MATERIAL_DIALOGUE_CANDIDATE_VERSION:
        return _ADAPTER_V7.json_schema()
    if version == HISTORICAL_MATERIAL_WEB_DIALOGUE_CANDIDATE_VERSION:
        return _ADAPTER_V8.json_schema()
    if version == HISTORICAL_DIALOGUE_CANDIDATE_VERSION:
        return _ADAPTER_V5.json_schema()
    if version == HISTORICAL_WEB_DIALOGUE_CANDIDATE_VERSION:
        return _ADAPTER_V6.json_schema()
    raise ValueError("unsupported dialogue candidate version")


def parse_dialogue_candidate(
    value: object,
    *,
    version: str = DIALOGUE_CANDIDATE_VERSION,
) -> CreatorDialogueCandidate:
    if version == DIALOGUE_CANDIDATE_VERSION:
        return _ADAPTER_V9.validate_python(value, strict=True)
    if version == WEB_DIALOGUE_CANDIDATE_VERSION:
        return _ADAPTER_V10.validate_python(value, strict=True)
    if version == HISTORICAL_MATERIAL_DIALOGUE_CANDIDATE_VERSION:
        return _ADAPTER_V7.validate_python(value, strict=True)
    if version == HISTORICAL_MATERIAL_WEB_DIALOGUE_CANDIDATE_VERSION:
        return _ADAPTER_V8.validate_python(value, strict=True)
    if version == HISTORICAL_DIALOGUE_CANDIDATE_VERSION:
        return _ADAPTER_V5.validate_python(value, strict=True)
    if version == HISTORICAL_WEB_DIALOGUE_CANDIDATE_VERSION:
        return _ADAPTER_V6.validate_python(value, strict=True)
    raise ValueError("unsupported dialogue candidate version")


__all__ = (
    "DIALOGUE_CANDIDATE_VERSION",
    "HISTORICAL_DIALOGUE_CANDIDATE_VERSION",
    "HISTORICAL_MATERIAL_DIALOGUE_CANDIDATE_VERSION",
    "HISTORICAL_MATERIAL_WEB_DIALOGUE_CANDIDATE_VERSION",
    "HISTORICAL_WEB_DIALOGUE_CANDIDATE_VERSION",
    "WEB_DIALOGUE_CANDIDATE_VERSION",
    "CreatorDialogueCandidate",
    "DialogueCommitmentChange",
    "DialogueExperience",
    "DialogueMaterialChange",
    "DialogueMaterialChangeV7",
    "DialogueMaterialContentChange",
    "DialogueMaterialStateChange",
    "DialogueMemoryChange",
    "DialogueRelationshipBoundary",
    "DialogueRelationshipChange",
    "DialogueRelationshipFact",
    "DialogueReplyDecision",
    "DialogueReplyDecisionV5",
    "DialogueReplyDecisionV6",
    "DialogueReplyDecisionV7",
    "DialogueReplyDecisionV8",
    "DialogueReplyDecisionV10",
    "DialogueTerminalDecision",
    "DialogueTerminalDecisionV5",
    "DialogueTerminalDecisionV6",
    "DialogueTerminalDecisionV7",
    "DialogueTerminalDecisionV8",
    "DialogueTerminalDecisionV10",
    "DialogueWebResearchDecision",
    "DialogueWebResearchDecisionV8",
    "DialogueWebResearchDecisionV10",
    "dialogue_candidate_schema",
    "parse_dialogue_candidate",
)
