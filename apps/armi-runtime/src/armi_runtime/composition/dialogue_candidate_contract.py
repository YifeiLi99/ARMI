"""Compact model output contract for ordinary Creator dialogue.

Historical wire generations stay beside the active union because durable model attempts
must be parsed by their recorded contract version; splitting them would duplicate the
strict dispatch table and make compatibility drift easier.
"""

from __future__ import annotations

import json
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
HISTORICAL_PRIVATE_DIALOGUE_CANDIDATE_VERSION = "armi.creator-dialogue-candidate.v9"
HISTORICAL_PRIVATE_WEB_DIALOGUE_CANDIDATE_VERSION = (
    "armi.creator-dialogue-candidate.v10"
)
HISTORICAL_CAPABILITY_DIALOGUE_CANDIDATE_VERSION = (
    "armi.creator-dialogue-candidate.v11"
)
HISTORICAL_CAPABILITY_WEB_DIALOGUE_CANDIDATE_VERSION = (
    "armi.creator-dialogue-candidate.v12"
)
DIALOGUE_CANDIDATE_VERSION = "armi.creator-dialogue-candidate.v13"
WEB_DIALOGUE_CANDIDATE_VERSION = "armi.creator-dialogue-candidate.v14"

Summary = Annotated[str, StringConstraints(min_length=1, max_length=512)]
ContextRef = Annotated[
    str,
    StringConstraints(pattern=r"^ctx:[1-9][0-9]{0,2}$", max_length=7),
]


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class DialogueCapabilityRequest(_StrictModel):
    capability_ref: ContextRef


class DialogueNameReplacement(_StrictModel):
    value: Annotated[str, StringConstraints(min_length=1, max_length=128)] | None

    @model_validator(mode="after")
    def validate_text(self) -> DialogueNameReplacement:
        if self.value is not None and (
            not self.value.strip() or "\x00" in self.value
        ):
            raise ValueError("name replacement is invalid")
        return self


class DialogueLongTextReplacement(_StrictModel):
    value: Annotated[str, StringConstraints(min_length=1, max_length=2048)] | None

    @model_validator(mode="after")
    def validate_text(self) -> DialogueLongTextReplacement:
        if self.value is not None and (
            not self.value.strip() or "\x00" in self.value
        ):
            raise ValueError("text replacement is invalid")
        return self


class DialogueSummaryListReplacement(_StrictModel):
    values: tuple[Summary, ...] = Field(max_length=16)

    @model_validator(mode="after")
    def validate_values(self) -> DialogueSummaryListReplacement:
        if any(not value.strip() or "\x00" in value for value in self.values):
            raise ValueError("summary replacement is invalid")
        if len(self.values) != len(set(self.values)):
            raise ValueError("summary replacement contains duplicates")
        return self


class DialogueSelfChange(_StrictModel):
    name: DialogueNameReplacement | None = None
    self_description: DialogueLongTextReplacement | None = None
    interests: DialogueSummaryListReplacement | None = None
    values: DialogueSummaryListReplacement | None = None
    preferences: DialogueSummaryListReplacement | None = None
    goals: DialogueSummaryListReplacement | None = None
    self_narrative: DialogueLongTextReplacement | None = None

    @model_validator(mode="after")
    def validate_change(self) -> DialogueSelfChange:
        if all(getattr(self, field) is None for field in type(self).model_fields):
            raise ValueError("self change is empty")
        return self


class DialogueMindChange(_StrictModel):
    understanding: DialogueSummaryListReplacement | None = None
    attention: DialogueSummaryListReplacement | None = None
    emotions: DialogueSummaryListReplacement | None = None
    thoughts: DialogueSummaryListReplacement | None = None
    wishes: DialogueSummaryListReplacement | None = None
    motivations: DialogueSummaryListReplacement | None = None
    mood: DialogueNameReplacement | None = None

    @model_validator(mode="after")
    def validate_change(self) -> DialogueMindChange:
        if all(getattr(self, field) is None for field in type(self).model_fields):
            raise ValueError("mind change is empty")
        return self


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
        return HISTORICAL_PRIVATE_DIALOGUE_CANDIDATE_VERSION


class _CreatorDialogueCandidateV10(CreatorDialogueCandidate):
    @property
    def schema_version(self) -> str:
        return HISTORICAL_PRIVATE_WEB_DIALOGUE_CANDIDATE_VERSION


class _CreatorDialogueCandidateV11(CreatorDialogueCandidate):
    @property
    def schema_version(self) -> str:
        return HISTORICAL_CAPABILITY_DIALOGUE_CANDIDATE_VERSION


class _CreatorDialogueCandidateV12(CreatorDialogueCandidate):
    @property
    def schema_version(self) -> str:
        return HISTORICAL_CAPABILITY_WEB_DIALOGUE_CANDIDATE_VERSION


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


class DialogueReplyDecisionV9(_CreatorDialogueCandidateV9):
    kind: Literal["reply"]
    content: Annotated[str, StringConstraints(min_length=1, max_length=65536)]
    experience: DialogueExperience | None = None
    memory_change: DialogueMemoryChange | None = None
    relationship_change: DialogueRelationshipChange | None = None
    material_change: DialogueMaterialChange | None = None

    @model_validator(mode="after")
    def validate_relationship_source(self) -> DialogueReplyDecisionV9:
        if self.relationship_change is not None and self.experience is None:
            raise ValueError("relationship change requires an experience")
        return self


class DialogueTerminalDecisionV9(_CreatorDialogueCandidateV9):
    kind: Literal[
        "decline",
        "no_action",
        "no_change",
        "defer",
        "need_information",
    ]


DialogueDecisionV9 = Annotated[
    DialogueReplyDecisionV9 | DialogueTerminalDecisionV9,
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


class DialogueReplyDecisionV11(_CreatorDialogueCandidateV11):
    kind: Literal["reply"]
    content: Annotated[str, StringConstraints(min_length=1, max_length=65536)]
    experience: DialogueExperience | None = None
    memory_change: DialogueMemoryChange | None = None
    relationship_change: DialogueRelationshipChange | None = None
    material_change: DialogueMaterialChange | None = None
    capability_request: DialogueCapabilityRequest | None = None

    @model_validator(mode="after")
    def validate_relationship_source(self) -> DialogueReplyDecisionV11:
        if self.relationship_change is not None and self.experience is None:
            raise ValueError("relationship change requires an experience")
        return self


class DialogueTerminalDecisionV11(_CreatorDialogueCandidateV11):
    kind: Literal[
        "decline",
        "no_action",
        "no_change",
        "defer",
        "need_information",
    ]


DialogueDecisionV11 = Annotated[
    DialogueReplyDecisionV11 | DialogueTerminalDecisionV11,
    Field(discriminator="kind"),
]


class DialogueReplyDecision(DialogueReplyDecisionV11):
    self_change: DialogueSelfChange | None = None
    mind_change: DialogueMindChange | None = None

    @property
    def schema_version(self) -> str:
        return DIALOGUE_CANDIDATE_VERSION

    @model_validator(mode="after")
    def validate_growth_source(self) -> DialogueReplyDecision:
        if (
            self.self_change is not None or self.mind_change is not None
        ) and self.experience is None:
            raise ValueError("subject growth requires an experience")
        return self


class DialogueTerminalDecision(DialogueTerminalDecisionV11):
    @property
    def schema_version(self) -> str:
        return DIALOGUE_CANDIDATE_VERSION


DialogueDecision = Annotated[
    DialogueReplyDecision | DialogueTerminalDecision,
    Field(discriminator="kind"),
]


class DialogueReplyDecisionV12(_CreatorDialogueCandidateV12):
    kind: Literal["reply"]
    content: Annotated[str, StringConstraints(min_length=1, max_length=65536)]
    experience: DialogueExperience | None = None
    memory_change: DialogueMemoryChange | None = None
    relationship_change: DialogueRelationshipChange | None = None
    material_change: DialogueMaterialChange | None = None
    capability_request: DialogueCapabilityRequest | None = None

    @model_validator(mode="after")
    def validate_relationship_source(self) -> DialogueReplyDecisionV12:
        if self.relationship_change is not None and self.experience is None:
            raise ValueError("relationship change requires an experience")
        return self


class DialogueTerminalDecisionV12(_CreatorDialogueCandidateV12):
    kind: Literal[
        "decline",
        "no_action",
        "no_change",
        "defer",
        "need_information",
    ]


class DialogueWebResearchDecisionV12(_CreatorDialogueCandidateV12):
    kind: Literal["web_research"]
    query: Annotated[str, StringConstraints(min_length=1, max_length=16384)]


DialogueDecisionV12 = Annotated[
    DialogueReplyDecisionV12
    | DialogueTerminalDecisionV12
    | DialogueWebResearchDecisionV12,
    Field(discriminator="kind"),
]


class DialogueReplyDecisionV14(DialogueReplyDecisionV12):
    self_change: DialogueSelfChange | None = None
    mind_change: DialogueMindChange | None = None

    @property
    def schema_version(self) -> str:
        return WEB_DIALOGUE_CANDIDATE_VERSION

    @model_validator(mode="after")
    def validate_growth_source(self) -> DialogueReplyDecisionV14:
        if (
            self.self_change is not None or self.mind_change is not None
        ) and self.experience is None:
            raise ValueError("subject growth requires an experience")
        return self


class DialogueTerminalDecisionV14(DialogueTerminalDecisionV12):
    @property
    def schema_version(self) -> str:
        return WEB_DIALOGUE_CANDIDATE_VERSION


class DialogueWebResearchDecisionV14(DialogueWebResearchDecisionV12):
    @property
    def schema_version(self) -> str:
        return WEB_DIALOGUE_CANDIDATE_VERSION


DialogueDecisionV14 = Annotated[
    DialogueReplyDecisionV14
    | DialogueTerminalDecisionV14
    | DialogueWebResearchDecisionV14,
    Field(discriminator="kind"),
]

_ADAPTER_V5: TypeAdapter[DialogueDecisionV5] = TypeAdapter(DialogueDecisionV5)
_ADAPTER_V6: TypeAdapter[DialogueDecisionV6] = TypeAdapter(DialogueDecisionV6)
_ADAPTER_V7: TypeAdapter[DialogueDecisionV7] = TypeAdapter(DialogueDecisionV7)
_ADAPTER_V8: TypeAdapter[DialogueDecisionV8] = TypeAdapter(DialogueDecisionV8)
_ADAPTER_V9: TypeAdapter[DialogueDecisionV9] = TypeAdapter(DialogueDecisionV9)
_ADAPTER_V10: TypeAdapter[DialogueDecisionV10] = TypeAdapter(DialogueDecisionV10)
_ADAPTER_V11: TypeAdapter[DialogueDecisionV11] = TypeAdapter(DialogueDecisionV11)
_ADAPTER_V12: TypeAdapter[DialogueDecisionV12] = TypeAdapter(DialogueDecisionV12)
_ADAPTER_V13: TypeAdapter[DialogueDecision] = TypeAdapter(DialogueDecision)
_ADAPTER_V14: TypeAdapter[DialogueDecisionV14] = TypeAdapter(DialogueDecisionV14)


def dialogue_candidate_schema(
    version: str = DIALOGUE_CANDIDATE_VERSION,
) -> dict[str, Any]:
    if version == DIALOGUE_CANDIDATE_VERSION:
        return _ADAPTER_V13.json_schema()
    if version == WEB_DIALOGUE_CANDIDATE_VERSION:
        return _ADAPTER_V14.json_schema()
    if version == HISTORICAL_CAPABILITY_DIALOGUE_CANDIDATE_VERSION:
        return _ADAPTER_V11.json_schema()
    if version == HISTORICAL_CAPABILITY_WEB_DIALOGUE_CANDIDATE_VERSION:
        return _ADAPTER_V12.json_schema()
    if version == HISTORICAL_PRIVATE_DIALOGUE_CANDIDATE_VERSION:
        return _ADAPTER_V9.json_schema()
    if version == HISTORICAL_PRIVATE_WEB_DIALOGUE_CANDIDATE_VERSION:
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
    encoded = json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode(
        "utf-8"
    )
    if version == DIALOGUE_CANDIDATE_VERSION:
        return _ADAPTER_V13.validate_json(encoded, strict=True)
    if version == WEB_DIALOGUE_CANDIDATE_VERSION:
        return _ADAPTER_V14.validate_json(encoded, strict=True)
    if version == HISTORICAL_CAPABILITY_DIALOGUE_CANDIDATE_VERSION:
        return _ADAPTER_V11.validate_json(encoded, strict=True)
    if version == HISTORICAL_CAPABILITY_WEB_DIALOGUE_CANDIDATE_VERSION:
        return _ADAPTER_V12.validate_json(encoded, strict=True)
    if version == HISTORICAL_PRIVATE_DIALOGUE_CANDIDATE_VERSION:
        return _ADAPTER_V9.validate_json(encoded, strict=True)
    if version == HISTORICAL_PRIVATE_WEB_DIALOGUE_CANDIDATE_VERSION:
        return _ADAPTER_V10.validate_json(encoded, strict=True)
    if version == HISTORICAL_MATERIAL_DIALOGUE_CANDIDATE_VERSION:
        return _ADAPTER_V7.validate_json(encoded, strict=True)
    if version == HISTORICAL_MATERIAL_WEB_DIALOGUE_CANDIDATE_VERSION:
        return _ADAPTER_V8.validate_json(encoded, strict=True)
    if version == HISTORICAL_DIALOGUE_CANDIDATE_VERSION:
        return _ADAPTER_V5.validate_json(encoded, strict=True)
    if version == HISTORICAL_WEB_DIALOGUE_CANDIDATE_VERSION:
        return _ADAPTER_V6.validate_json(encoded, strict=True)
    raise ValueError("unsupported dialogue candidate version")


__all__ = (
    "DIALOGUE_CANDIDATE_VERSION",
    "HISTORICAL_CAPABILITY_DIALOGUE_CANDIDATE_VERSION",
    "HISTORICAL_CAPABILITY_WEB_DIALOGUE_CANDIDATE_VERSION",
    "HISTORICAL_DIALOGUE_CANDIDATE_VERSION",
    "HISTORICAL_MATERIAL_DIALOGUE_CANDIDATE_VERSION",
    "HISTORICAL_MATERIAL_WEB_DIALOGUE_CANDIDATE_VERSION",
    "HISTORICAL_PRIVATE_DIALOGUE_CANDIDATE_VERSION",
    "HISTORICAL_PRIVATE_WEB_DIALOGUE_CANDIDATE_VERSION",
    "HISTORICAL_WEB_DIALOGUE_CANDIDATE_VERSION",
    "WEB_DIALOGUE_CANDIDATE_VERSION",
    "CreatorDialogueCandidate",
    "DialogueCapabilityRequest",
    "DialogueCommitmentChange",
    "DialogueExperience",
    "DialogueLongTextReplacement",
    "DialogueMaterialChange",
    "DialogueMaterialChangeV7",
    "DialogueMaterialContentChange",
    "DialogueMaterialStateChange",
    "DialogueMemoryChange",
    "DialogueMindChange",
    "DialogueNameReplacement",
    "DialogueRelationshipBoundary",
    "DialogueRelationshipChange",
    "DialogueRelationshipFact",
    "DialogueReplyDecision",
    "DialogueReplyDecisionV5",
    "DialogueReplyDecisionV6",
    "DialogueReplyDecisionV7",
    "DialogueReplyDecisionV8",
    "DialogueReplyDecisionV9",
    "DialogueReplyDecisionV10",
    "DialogueReplyDecisionV11",
    "DialogueReplyDecisionV12",
    "DialogueReplyDecisionV14",
    "DialogueSelfChange",
    "DialogueSummaryListReplacement",
    "DialogueTerminalDecision",
    "DialogueTerminalDecisionV5",
    "DialogueTerminalDecisionV6",
    "DialogueTerminalDecisionV7",
    "DialogueTerminalDecisionV8",
    "DialogueTerminalDecisionV9",
    "DialogueTerminalDecisionV10",
    "DialogueTerminalDecisionV11",
    "DialogueTerminalDecisionV12",
    "DialogueTerminalDecisionV14",
    "DialogueWebResearchDecision",
    "DialogueWebResearchDecisionV8",
    "DialogueWebResearchDecisionV10",
    "DialogueWebResearchDecisionV12",
    "DialogueWebResearchDecisionV14",
    "dialogue_candidate_schema",
    "parse_dialogue_candidate",
)
