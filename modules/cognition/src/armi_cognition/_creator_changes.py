"""Typed Creator changes, shared by text and voice before Owner binding."""

from __future__ import annotations

from typing import Annotated, Literal

from armi_kernel.contracts import NONBLANK_TEXT_PATTERN, NUL_FREE_TEXT_PATTERN
from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from ._dialogue_contract import (
    ContextRef,
    DialogueCommitmentChange,
    DialogueMaterialContentChange,
    DialogueMaterialStateChange,
    DialogueRelationshipBoundary,
    DialogueRelationshipChange,
    DialogueRelationshipFact,
    Summary,
)


class _Change(BaseModel, frozen=True):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


Content = Annotated[
    str, StringConstraints(min_length=1, max_length=1024, pattern=NONBLANK_TEXT_PATTERN)
]
MaterialTitle = Annotated[
    str, StringConstraints(min_length=1, max_length=256, pattern=NONBLANK_TEXT_PATTERN)
]
MaterialBody = Annotated[
    str,
    StringConstraints(min_length=1, max_length=65536, pattern=NONBLANK_TEXT_PATTERN),
]
MaterialMetadata = dict[
    Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9._-]{0,63}$")],
    Annotated[str, StringConstraints(max_length=512, pattern=NUL_FREE_TEXT_PATTERN)],
]


class MaterialContent(_Change, frozen=True):
    title: MaterialTitle
    body: MaterialBody
    metadata: MaterialMetadata = Field(default_factory=dict, max_length=32)
    material_status: Literal["active", "archived"] = "active"


class MaterialCreate(_Change, frozen=True):
    op: Literal["material.create"]
    material_kind: Literal["diary", "work", "collection", "draft"]
    content: MaterialContent


class MaterialUpdate(_Change, frozen=True):
    op: Literal["material.update"]
    target_ref: ContextRef
    content: MaterialContent


class MaterialVisibility(_Change, frozen=True):
    op: Literal["material.visibility"]
    target_ref: ContextRef
    visibility: Literal["set_private", "set_creator_visible"]


class MaterialDelete(_Change, frozen=True):
    op: Literal["material.delete"]
    target_ref: ContextRef


class RelationshipInterpretation(_Change, frozen=True):
    op: Literal["relationship.interpret"]
    text: Summary


class RelationshipFact(_Change, frozen=True):
    op: Literal["relationship.fact"]
    text: Summary


class RestrictedBoundary(_Change, frozen=True):
    kind: Literal["contact", "address", "privacy", "disclosure"]
    action: Literal["refuse", "restrict"]


class ExitBoundary(_Change, frozen=True):
    kind: Literal["exit"]
    action: Literal["end_contact"]


class RelationshipBoundary(_Change, frozen=True):
    op: Literal["relationship.boundary"]
    party: Literal["armi", "creator"]
    boundary: Annotated[RestrictedBoundary | ExitBoundary, Field(discriminator="kind")]
    text: Summary


class CommitmentEstablish(_Change, frozen=True):
    op: Literal["commitment.establish"]
    party: Literal["armi", "creator"]
    scope: Summary
    content: Content
    event_summary: Summary
    conflicts_with_ref: ContextRef | None = None


class CommitmentScopeUpdate(_Change, frozen=True):
    kind: Literal["scope"]
    scope: Summary
    content: Content | None = None


class CommitmentContentUpdate(_Change, frozen=True):
    kind: Literal["content"]
    content: Content


class CommitmentModify(_Change, frozen=True):
    op: Literal["commitment.modify"]
    target_ref: ContextRef
    update: Annotated[
        CommitmentScopeUpdate | CommitmentContentUpdate, Field(discriminator="kind")
    ]
    event_summary: Summary
    conflicts_with_ref: ContextRef | None = None


class CommitmentEvent(_Change, frozen=True):
    op: Literal[
        "commitment.fulfill",
        "commitment.withdraw",
        "commitment.forget",
        "commitment.violate",
    ]
    target_ref: ContextRef
    text: Summary


class CommitmentConflict(_Change, frozen=True):
    op: Literal["commitment.conflict"]
    target_ref: ContextRef
    related_ref: ContextRef
    text: Summary


CreatorChange = Annotated[
    MaterialCreate
    | MaterialUpdate
    | MaterialVisibility
    | MaterialDelete
    | RelationshipInterpretation
    | RelationshipFact
    | RelationshipBoundary
    | CommitmentEstablish
    | CommitmentModify
    | CommitmentEvent
    | CommitmentConflict,
    Field(discriminator="op"),
]


def change_context_refs(change: CreatorChange) -> tuple[ContextRef, ...]:
    refs: list[ContextRef] = []
    if isinstance(
        change,
        (
            MaterialUpdate,
            MaterialVisibility,
            MaterialDelete,
            CommitmentModify,
            CommitmentEvent,
            CommitmentConflict,
        ),
    ):
        refs.append(change.target_ref)
    if isinstance(change, CommitmentConflict):
        refs.append(change.related_ref)
    if (
        isinstance(change, (CommitmentEstablish, CommitmentModify))
        and change.conflicts_with_ref is not None
    ):
        refs.append(change.conflicts_with_ref)
    return tuple(refs)


def translate_creator_changes(changes: tuple[CreatorChange, ...]) -> dict[str, object]:
    """Map trusted typed fields; Owner binding still checks references and semantics."""
    result: dict[str, object] = {}
    relationship: dict[str, object] = {}

    def put(target: dict[str, object], key: str, value: object) -> None:
        if key in target:
            raise ValueError("Creator change owner is duplicated")
        target[key] = value

    for change in changes:
        if isinstance(change, (MaterialCreate, MaterialUpdate)):
            put(
                result,
                "material_change",
                DialogueMaterialContentChange.model_construct(
                    action="create" if isinstance(change, MaterialCreate) else "update",
                    material_ref=change.target_ref
                    if isinstance(change, MaterialUpdate)
                    else None,
                    material_kind=change.material_kind
                    if isinstance(change, MaterialCreate)
                    else None,
                    title=change.content.title,
                    body=change.content.body,
                    metadata=change.content.metadata,
                    material_status=change.content.material_status,
                ),
            )
        elif isinstance(change, (MaterialVisibility, MaterialDelete)):
            put(
                result,
                "material_change",
                DialogueMaterialStateChange.model_construct(
                    action=change.visibility
                    if isinstance(change, MaterialVisibility)
                    else "delete",
                    material_ref=change.target_ref,
                ),
            )
        elif isinstance(change, RelationshipInterpretation):
            put(relationship, "interpretation", change.text)
        elif isinstance(change, RelationshipFact):
            put(
                relationship,
                "fact",
                DialogueRelationshipFact.model_construct(
                    kind="party_expression",
                    summary=change.text,
                ),
            )
        elif isinstance(change, RelationshipBoundary):
            put(
                relationship,
                "boundary",
                DialogueRelationshipBoundary.model_construct(
                    party=change.party,
                    kind=change.boundary.kind,
                    action=change.boundary.action,
                    summary=change.text,
                ),
            )
        else:
            if isinstance(change, CommitmentEstablish):
                commitment = DialogueCommitmentChange.model_construct(
                    action="establish",
                    party=change.party,
                    scope=change.scope,
                    content=change.content,
                    event_summary=change.event_summary,
                    conflicts_with_ref=change.conflicts_with_ref,
                )
            elif isinstance(change, CommitmentModify):
                commitment = DialogueCommitmentChange.model_construct(
                    action="modify",
                    commitment_ref=change.target_ref,
                    scope=(
                        change.update.scope
                        if isinstance(change.update, CommitmentScopeUpdate)
                        else None
                    ),
                    content=change.update.content,
                    event_summary=change.event_summary,
                    conflicts_with_ref=change.conflicts_with_ref,
                )
            else:
                commitment = DialogueCommitmentChange.model_construct(
                    action="note_conflict"
                    if isinstance(change, CommitmentConflict)
                    else change.op.removeprefix("commitment."),
                    commitment_ref=change.target_ref,
                    event_summary=change.text,
                    conflicts_with_ref=change.related_ref
                    if isinstance(change, CommitmentConflict)
                    else None,
                )
            put(relationship, "commitment_change", commitment)
    if relationship:
        result["relationship_change"] = DialogueRelationshipChange.model_construct(
            _fields_set=None, **relationship
        )
    return result
