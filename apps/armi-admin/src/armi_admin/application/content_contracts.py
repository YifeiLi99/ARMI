"""Closed online content commands; authority and provenance are server-owned."""

from __future__ import annotations

from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    field_validator,
    model_validator,
)

from .contracts import EnvironmentRequest


class ContentModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)


class MemoryPayload(ContentModel):
    summary: str = Field(min_length=1, max_length=512)
    uncertainty: str | None = None
    accessibility: Literal["available", "faded"] = "available"


class RelationshipFactPayload(ContentModel):
    fact_id: str
    kind: Literal["shared_experience", "party_expression"]
    summary: str = Field(min_length=1, max_length=512)


class RelationshipBoundaryPayload(ContentModel):
    party_role: Literal["subject", "other"]
    kind: Literal["contact", "address", "privacy", "disclosure", "exit"]
    action: Literal["refuse", "restrict", "end_contact"]
    summary: str = Field(min_length=1, max_length=512)


class RelationshipCommitmentPayload(ContentModel):
    commitment_id: str
    party_role: Literal["subject", "other"]
    scope: str = Field(min_length=1, max_length=512)
    content: str = Field(min_length=1, max_length=1024)
    status: Literal["active", "fulfilled", "withdrawn", "forgotten", "violated"]
    last_event_kind: Literal[
        "established",
        "modified",
        "fulfilled",
        "withdrawn",
        "forgotten",
        "violated",
        "conflict_noted",
    ]
    last_event_summary: str = Field(min_length=1, max_length=512)


class RelationshipIssuePayload(ContentModel):
    issue_id: str
    kind: Literal["contradictory_commitments", "commitment_violation"]
    commitment_ids: list[str] = Field(min_length=1, max_length=2)
    summary: str = Field(min_length=1, max_length=512)
    status: Literal["open"] = "open"


class RelationshipPayload(ContentModel):
    other_party_id: str | None = None
    facts: list[RelationshipFactPayload] = Field(min_length=1, max_length=64)
    interpretation: str = Field(min_length=1, max_length=1024)
    boundaries: list[RelationshipBoundaryPayload] = Field(
        default_factory=list[RelationshipBoundaryPayload], max_length=16
    )
    commitments: list[RelationshipCommitmentPayload] = Field(
        default_factory=list[RelationshipCommitmentPayload], max_length=16
    )
    open_issues: list[RelationshipIssuePayload] = Field(
        default_factory=list[RelationshipIssuePayload], max_length=32
    )
    status: Literal["active", "ended"] = "active"


class MaterialPayload(ContentModel):
    material_kind: Literal["diary", "work", "collection", "draft"] | None = None
    title: str = Field(min_length=1, max_length=256)
    body: str = Field(min_length=1, max_length=65536)
    metadata: dict[str, str] = Field(default_factory=dict, max_length=32)
    privacy_status: Literal["creator_visible", "private"] = "creator_visible"
    material_status: Literal["active", "archived"] = "active"


class ActivityPayload(ContentModel):
    status: Literal["ready", "paused"] = "ready"
    goal: str = Field(min_length=1, max_length=8192)
    progress_summary: str | None = None
    next_safe_step: str = Field(min_length=1, max_length=4096)


class PromptPayload(ContentModel):
    prompt_kind: Literal["creator_guidance", "subject_guidance"]
    content: str | dict[str, JsonValue]


class ComponentPayload(ContentModel):
    component_kind: Literal["self", "mind", "life_mode", "mood"]
    replacement: dict[str, JsonValue]


class ContentChange(ContentModel):
    action: Literal["create", "update", "delete"]
    object_id: str
    expected_version: int = Field(ge=0)

    @field_validator("object_id")
    @classmethod
    def uuid7_id(cls, value: str) -> str:
        parsed = UUID(value)
        if parsed.version != 7 or str(parsed) != value:
            raise ValueError("ADMIN-CONTENT-ID")
        return value


class MemoryChange(ContentChange):
    owner: Literal["memory"]
    data: MemoryPayload | None = None


class RelationshipChange(ContentChange):
    owner: Literal["relationship"]
    data: RelationshipPayload | None = None


class MaterialChange(ContentChange):
    owner: Literal["material"]
    data: MaterialPayload | None = None


class ActivityChange(ContentChange):
    owner: Literal["activity"]
    data: ActivityPayload | None = None


class PromptChange(ContentChange):
    owner: Literal["prompt"]
    data: PromptPayload | None = None


class ComponentChange(ContentChange):
    owner: Literal["subject_state", "mood"]
    data: ComponentPayload


class ContentWriteRequest(EnvironmentRequest):
    idempotency_key: str = Field(pattern=r"^[A-Za-z0-9._:-]{1,128}$")
    reason: str = Field(min_length=1, max_length=1024)
    expected_generation_id: str
    change: Annotated[
        MemoryChange
        | RelationshipChange
        | MaterialChange
        | ActivityChange
        | PromptChange
        | ComponentChange,
        Field(discriminator="owner"),
    ]

    @field_validator("expected_generation_id")
    @classmethod
    def generation(cls, value: str) -> str:
        return ContentChange.uuid7_id(value)

    @model_validator(mode="after")
    def operation(self) -> Self:
        change = self.change
        if (change.action == "create") != (change.expected_version == 0) or (
            change.action == "delete"
        ) != (change.data is None):
            raise ValueError("ADMIN-CONTENT-OPERATION")
        if isinstance(change, ComponentChange) and (
            change.action != "update"
            or (change.owner == "mood") != (change.data.component_kind == "mood")
        ):
            raise ValueError("ADMIN-CONTENT-COMPONENT-OPERATION")
        if isinstance(change, RelationshipChange) and change.data is not None:
            if (change.action == "create") != (change.data.other_party_id is not None):
                raise ValueError("ADMIN-CONTENT-PARTY")
            if change.data.other_party_id is not None:
                ContentChange.uuid7_id(change.data.other_party_id)
        if (
            isinstance(change, MaterialChange)
            and change.data is not None
            and (change.action == "create") != (change.data.material_kind is not None)
        ):
            raise ValueError("ADMIN-CONTENT-MATERIAL-KIND")
        return self


__all__ = ("ContentWriteRequest",)
