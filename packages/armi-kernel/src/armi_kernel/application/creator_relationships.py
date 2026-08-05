"""Creator-visible, read-only projections of the primary relationship."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Final, Protocol, runtime_checkable
from uuid import UUID

from .candidates import (
    RelationshipBoundary,
    RelationshipBoundaryAction,
    RelationshipCommitment,
    RelationshipCommitmentEvent,
    RelationshipFact,
    RelationshipIssue,
    RelationshipStatus,
)

RELATIONSHIP_PROJECTION_VERSION: Final = "creator-relationship.v1"


class CreatorRelationshipViolation(RuntimeError):
    __slots__ = ("code",)

    def __init__(self, code: str) -> None:
        if type(code) is not str or not code.startswith("RELATIONSHIP-QUERY-"):
            raise ValueError("relationship query violation code is invalid")
        self.code = code
        super().__init__("Creator relationship query failed")

    def __str__(self) -> str:
        return f"{self.code}: Creator relationship query failed"


def _uuid7(value: object) -> bool:
    return type(value) is UUID and value.version == 7


def _instant(value: object) -> bool:
    return type(value) is datetime and value.tzinfo is not None


@dataclass(frozen=True, slots=True)
class CreatorRelationshipRevision:
    relationship_revision_id: UUID
    revision_no: int
    facts: tuple[RelationshipFact, ...]
    interpretation: str
    boundaries: tuple[RelationshipBoundary, ...]
    commitments: tuple[RelationshipCommitment, ...]
    open_issues: tuple[RelationshipIssue, ...]
    commitment_event: RelationshipCommitmentEvent | None
    status: RelationshipStatus
    occurred_at: datetime

    def __post_init__(self) -> None:
        commitments_valid = type(self.commitments) is tuple and all(
            type(item) is RelationshipCommitment for item in self.commitments
        )
        commitment_ids = (
            {item.commitment_id for item in self.commitments}
            if commitments_valid
            else set()
        )
        if (
            not _uuid7(self.relationship_revision_id)
            or type(self.revision_no) is not int
            or self.revision_no < 1
            or type(self.facts) is not tuple
            or not self.facts
            or len(self.facts) > 64
            or any(type(item) is not RelationshipFact for item in self.facts)
            or len(set(self.facts)) != len(self.facts)
            or type(self.interpretation) is not str
            or not self.interpretation
            or len(self.interpretation) > 1024
            or type(self.boundaries) is not tuple
            or len(self.boundaries) > 16
            or any(type(item) is not RelationshipBoundary for item in self.boundaries)
            or len({(item.party_role, item.kind) for item in self.boundaries})
            != len(self.boundaries)
            or not commitments_valid
            or len(self.commitments) > 16
            or len(commitment_ids) != len(self.commitments)
            or type(self.open_issues) is not tuple
            or len(self.open_issues) > 32
            or any(type(item) is not RelationshipIssue for item in self.open_issues)
            or len({item.issue_id for item in self.open_issues})
            != len(self.open_issues)
            or any(
                commitment_id not in commitment_ids
                for issue in self.open_issues
                for commitment_id in issue.commitment_ids
            )
            or (
                self.commitment_event is not None
                and (
                    type(self.commitment_event) is not RelationshipCommitmentEvent
                    or self.commitment_event.commitment_id not in commitment_ids
                    or not any(
                        item.commitment_id == self.commitment_event.commitment_id
                        and item.last_event_kind is self.commitment_event.kind
                        and item.last_event_summary == self.commitment_event.summary
                        for item in self.commitments
                    )
                    or (
                        self.commitment_event.related_commitment_id is not None
                        and self.commitment_event.related_commitment_id
                        not in commitment_ids
                    )
                )
            )
            or type(self.status) is not RelationshipStatus
            or (self.status is RelationshipStatus.ENDED)
            != any(
                item.action is RelationshipBoundaryAction.END_CONTACT
                for item in self.boundaries
            )
            or not _instant(self.occurred_at)
        ):
            raise CreatorRelationshipViolation("RELATIONSHIP-QUERY-REVISION")


@dataclass(frozen=True, slots=True)
class CreatorRelationshipItem:
    relationship_id: UUID
    current_revision_id: UUID
    head_version: int
    current: CreatorRelationshipRevision
    created_at: datetime

    def __post_init__(self) -> None:
        if (
            not _uuid7(self.relationship_id)
            or not _uuid7(self.current_revision_id)
            or type(self.current) is not CreatorRelationshipRevision
            or self.current_revision_id != self.current.relationship_revision_id
            or type(self.head_version) is not int
            or self.head_version < 1
            or self.head_version != self.current.revision_no
            or not _instant(self.created_at)
            or self.created_at > self.current.occurred_at
        ):
            raise CreatorRelationshipViolation("RELATIONSHIP-QUERY-ITEM")


@dataclass(frozen=True, slots=True)
class CreatorRelationshipTimeline:
    relationship_id: UUID
    items: tuple[CreatorRelationshipRevision, ...]
    truncated: bool

    def __post_init__(self) -> None:
        if (
            not _uuid7(self.relationship_id)
            or type(self.items) is not tuple
            or len(self.items) > 100
            or any(
                type(item) is not CreatorRelationshipRevision for item in self.items
            )
            or len({item.revision_no for item in self.items}) != len(self.items)
            or any(
                newer.revision_no <= older.revision_no
                for newer, older in zip(self.items, self.items[1:], strict=False)
            )
            or type(self.truncated) is not bool
        ):
            raise CreatorRelationshipViolation("RELATIONSHIP-QUERY-TIMELINE")


@runtime_checkable
class CreatorRelationshipQueryPort(Protocol):
    async def current(self) -> CreatorRelationshipItem | None: ...

    async def timeline(self, relationship_id: UUID) -> CreatorRelationshipTimeline: ...


__all__ = (
    "RELATIONSHIP_PROJECTION_VERSION",
    "CreatorRelationshipItem",
    "CreatorRelationshipQueryPort",
    "CreatorRelationshipRevision",
    "CreatorRelationshipTimeline",
    "CreatorRelationshipViolation",
)
