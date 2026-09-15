"""Current compact model output contract for Creator dialogue."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    model_validator,
)

DIALOGUE_CANDIDATE_VERSION = "armi.creator-dialogue-candidate.v26"

type Summary = Annotated[str, StringConstraints(min_length=1, max_length=512)]
type ContextRef = Annotated[
    str,
    StringConstraints(pattern=r"^ctx:[1-9][0-9]{0,2}$", max_length=7),
]


class _StrictModel(BaseModel, frozen=True):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class DialogueNameReplacement(_StrictModel, frozen=True):
    value: Annotated[str, StringConstraints(min_length=1, max_length=128)] | None

    @model_validator(mode="after")
    def validate_text(self) -> DialogueNameReplacement:
        if self.value is not None and (not self.value.strip() or "\x00" in self.value):
            raise ValueError("name replacement is invalid")
        return self


class DialogueLongTextReplacement(_StrictModel, frozen=True):
    value: Annotated[str, StringConstraints(min_length=1, max_length=2048)] | None

    @model_validator(mode="after")
    def validate_text(self) -> DialogueLongTextReplacement:
        if self.value is not None and (not self.value.strip() or "\x00" in self.value):
            raise ValueError("text replacement is invalid")
        return self


class DialogueSummaryListReplacement(_StrictModel, frozen=True):
    values: tuple[Summary, ...] = Field(max_length=16)

    @model_validator(mode="after")
    def validate_values(self) -> DialogueSummaryListReplacement:
        if any(not value.strip() or "\x00" in value for value in self.values):
            raise ValueError("summary replacement is invalid")
        if len(self.values) != len(set(self.values)):
            raise ValueError("summary replacement contains duplicates")
        return self


class DialogueSelfChange(_StrictModel, frozen=True):
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


class DialogueMindChange(_StrictModel, frozen=True):
    understanding: DialogueSummaryListReplacement | None = None
    attention: DialogueSummaryListReplacement | None = None
    thoughts: DialogueSummaryListReplacement | None = None
    wishes: DialogueSummaryListReplacement | None = None
    motivations: DialogueSummaryListReplacement | None = None

    @model_validator(mode="after")
    def validate_change(self) -> DialogueMindChange:
        if all(getattr(self, field) is None for field in type(self).model_fields):
            raise ValueError("mind change is empty")
        return self


class DialogueSubjectPromptChange(_StrictModel, frozen=True):
    cognition_method: Summary
    expression_method: Summary
    reflection_method: Summary

    @model_validator(mode="after")
    def validate_methods(self) -> DialogueSubjectPromptChange:
        values = (
            self.cognition_method,
            self.expression_method,
            self.reflection_method,
        )
        if any(not value.strip() or "\x00" in value for value in values):
            raise ValueError("subject prompt method is invalid")
        return self


class DialogueExperience(_StrictModel, frozen=True):
    first_person_gist: Annotated[
        str,
        StringConstraints(min_length=1, max_length=1024),
    ]
    uncertainty: Summary | None = None
    memory_summary: Summary | None = None


class DialogueMemoryChange(_StrictModel, frozen=True):
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


class DialogueRelationshipFact(_StrictModel, frozen=True):
    kind: Literal["party_expression"]
    summary: Summary


class DialogueRelationshipBoundary(_StrictModel, frozen=True):
    party: Literal["armi", "creator"]
    kind: Literal["contact", "address", "privacy", "disclosure", "exit"]
    action: Literal["refuse", "restrict", "end_contact"]
    summary: Summary

    @model_validator(mode="after")
    def validate_shape(self) -> DialogueRelationshipBoundary:
        if (self.action == "end_contact") != (self.kind == "exit"):
            raise ValueError("only an exit boundary can end contact")
        return self


class DialogueCommitmentChange(_StrictModel, frozen=True):
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


class DialogueRelationshipChange(_StrictModel, frozen=True):
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


class DialogueMaterialContentChange(_StrictModel, frozen=True):
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


class DialogueMaterialStateChange(_StrictModel, frozen=True):
    action: Literal["set_private", "set_creator_visible", "delete"]
    material_ref: ContextRef


DialogueMaterialChange = Annotated[
    DialogueMaterialContentChange | DialogueMaterialStateChange,
    Field(discriminator="action"),
]


class CreatorDialogueCandidate(_StrictModel, frozen=True):
    """A subjective dialogue choice; wire metadata belongs to the adapter."""

    @property
    def schema_version(self) -> str:
        return DIALOGUE_CANDIDATE_VERSION


class DialogueReplyDecision(CreatorDialogueCandidate, frozen=True):
    kind: Literal["reply"]
    content: Annotated[str, StringConstraints(min_length=1, max_length=65536)]
    experience: DialogueExperience | None = None
    memory_change: DialogueMemoryChange | None = None
    relationship_change: DialogueRelationshipChange | None = None
    material_change: DialogueMaterialChange | None = None
    self_change: DialogueSelfChange | None = None
    mind_change: DialogueMindChange | None = None
    subject_prompt_change: DialogueSubjectPromptChange | None = None

    @model_validator(mode="after")
    def validate_experience_basis(self) -> DialogueReplyDecision:
        if self.relationship_change is not None and self.experience is None:
            raise ValueError("relationship change requires an experience")
        if (
            self.self_change is not None
            or self.mind_change is not None
            or self.subject_prompt_change is not None
        ) and self.experience is None:
            raise ValueError("subject growth requires an experience")
        return self


class DialogueTerminalDecision(CreatorDialogueCandidate, frozen=True):
    kind: Literal[
        "decline",
        "no_action",
        "no_change",
        "defer",
        "need_information",
    ]


class DialogueWebResearchDecision(CreatorDialogueCandidate, frozen=True):
    kind: Literal["web_research"]
    query: Annotated[str, StringConstraints(min_length=1, max_length=16384)]


class DialogueVisualObservationDecision(CreatorDialogueCandidate, frozen=True):
    kind: Literal["visual_observation"]
    source_kind: Literal["camera", "screen"]


class DialogueExactLifeQueryDecision(CreatorDialogueCandidate, frozen=True):
    kind: Literal["exact_life_query"]
    record_kind: Literal[
        "activity",
        "conversation",
        "material",
        "memory",
        "relationship",
        "self_change",
    ]
    query_text: (
        Annotated[str, StringConstraints(min_length=1, max_length=1024)] | None
    ) = None

    @model_validator(mode="after")
    def validate_query_text(self) -> DialogueExactLifeQueryDecision:
        if self.query_text is not None and (
            not self.query_text.strip() or "\x00" in self.query_text
        ):
            raise ValueError("exact life query text is invalid")
        return self


DialogueDecision = Annotated[
    DialogueReplyDecision
    | DialogueTerminalDecision
    | DialogueWebResearchDecision
    | DialogueVisualObservationDecision
    | DialogueExactLifeQueryDecision,
    Field(discriminator="kind"),
]


__all__ = (
    "DIALOGUE_CANDIDATE_VERSION",
    "CreatorDialogueCandidate",
    "DialogueCommitmentChange",
    "DialogueExactLifeQueryDecision",
    "DialogueExperience",
    "DialogueLongTextReplacement",
    "DialogueMaterialChange",
    "DialogueMaterialContentChange",
    "DialogueMaterialStateChange",
    "DialogueMemoryChange",
    "DialogueMindChange",
    "DialogueNameReplacement",
    "DialogueRelationshipBoundary",
    "DialogueRelationshipChange",
    "DialogueRelationshipFact",
    "DialogueReplyDecision",
    "DialogueSelfChange",
    "DialogueSubjectPromptChange",
    "DialogueSummaryListReplacement",
    "DialogueTerminalDecision",
    "DialogueWebResearchDecision",
)
