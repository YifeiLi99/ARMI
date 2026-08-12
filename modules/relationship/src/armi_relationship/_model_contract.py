"""Strict active model contract fragments for relationship lifecycle v2."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

ContextRef = Annotated[
    str,
    StringConstraints(pattern=r"^ctx:[1-9][0-9]{0,2}$", max_length=7),
]


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class RelationshipFactChangeV22(_StrictModel):
    operation: Literal["add", "revise", "remove"]
    fact_id: str | None = None
    context_ref: ContextRef | None = None
    kind: Literal["shared_experience", "party_expression"] | None = None
    summary: str | None = Field(default=None, max_length=512)

    @model_validator(mode="after")
    def validate_shape(self) -> RelationshipFactChangeV22:
        has_reference = self.fact_id is not None and self.context_ref is not None
        has_content = self.kind is not None and self.summary is not None
        valid = {
            "add": not has_reference and has_content,
            "revise": has_reference and has_content,
            "remove": has_reference and not has_content,
        }[self.operation]
        if not valid:
            raise ValueError("relationship fact operation content is invalid")
        return self


class RelationshipIssueResolutionV22(_StrictModel):
    issue_ref: ContextRef
    resolution_summary: str = Field(min_length=1, max_length=512)


class RelationshipBoundaryChangeV22(_StrictModel):
    operation: Literal["set", "remove"]
    party: Literal["armi", "other"]
    kind: Literal["contact", "address", "privacy", "disclosure", "exit"]
    action: Literal["refuse", "restrict", "end_contact"] | None = None
    summary: str | None = Field(default=None, max_length=512)

    @model_validator(mode="after")
    def validate_shape(self) -> RelationshipBoundaryChangeV22:
        if self.operation == "remove":
            if self.action is not None or self.summary is not None:
                raise ValueError("relationship boundary removal is invalid")
        elif (
            self.action is None
            or self.summary is None
            or not self.summary
            or (self.action == "end_contact") != (self.kind == "exit")
        ):
            raise ValueError("relationship boundary setting is invalid")
        return self


class RelationshipChangeV22(_StrictModel):
    facts: list[RelationshipFactChangeV22] = Field(max_length=64)
    boundaries: list[RelationshipBoundaryChangeV22] = Field(max_length=16)
    interpretation: str = Field(min_length=1, max_length=1024)
    reopen: bool = False
    issue_resolution: RelationshipIssueResolutionV22 | None = None


__all__ = (
    "RelationshipBoundaryChangeV22",
    "RelationshipChangeV22",
    "RelationshipFactChangeV22",
    "RelationshipIssueResolutionV22",
)
