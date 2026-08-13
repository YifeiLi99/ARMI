"""Stable public contract of the relationship owner."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Final, Protocol, runtime_checkable
from uuid import UUID

from armi_kernel.application import CandidateFactClass, CandidateOwnerDraft
from armi_runtime_foundation import PostgreSQLTransaction

RELATIONSHIP_MECHANISM_IDENTITY: Final = "armi.relationship.lifecycle-v2"
RELATIONSHIP_PROJECTION_VERSION: Final = "creator-relationship.v2"
_REF = re.compile(r"^proposal:[1-9][0-9]{0,2}$", re.ASCII)


class RelationshipViolation(RuntimeError):
    __slots__ = ("code",)

    def __init__(self, code: str) -> None:
        if type(code) is not str or not code.startswith("RELATIONSHIP-"):
            raise ValueError("relationship violation code is invalid")
        self.code = code
        super().__init__("relationship operation failed")

    def __str__(self) -> str:
        return f"{self.code}: relationship operation failed"


class RelationshipFactKind(StrEnum):
    SHARED_EXPERIENCE = "shared_experience"
    PARTY_EXPRESSION = "party_expression"


class RelationshipFactOperationKind(StrEnum):
    ADD = "add"
    REVISE = "revise"
    REMOVE = "remove"


class RelationshipPartyRole(StrEnum):
    SUBJECT = "subject"
    OTHER = "other"


class RelationshipBoundaryKind(StrEnum):
    CONTACT = "contact"
    ADDRESS = "address"
    PRIVACY = "privacy"
    DISCLOSURE = "disclosure"
    EXIT = "exit"


class RelationshipBoundaryAction(StrEnum):
    REFUSE = "refuse"
    RESTRICT = "restrict"
    END_CONTACT = "end_contact"


class RelationshipBoundaryOperationKind(StrEnum):
    SET = "set"
    REMOVE = "remove"


class RelationshipStatus(StrEnum):
    ACTIVE = "active"
    ENDED = "ended"


class RelationshipCommitmentStatus(StrEnum):
    ACTIVE = "active"
    FULFILLED = "fulfilled"
    WITHDRAWN = "withdrawn"
    FORGOTTEN = "forgotten"
    VIOLATED = "violated"


class RelationshipCommitmentEventKind(StrEnum):
    ESTABLISHED = "established"
    MODIFIED = "modified"
    FULFILLED = "fulfilled"
    WITHDRAWN = "withdrawn"
    FORGOTTEN = "forgotten"
    VIOLATED = "violated"
    CONFLICT_NOTED = "conflict_noted"


class RelationshipIssueKind(StrEnum):
    CONTRADICTORY_COMMITMENTS = "contradictory_commitments"
    COMMITMENT_VIOLATION = "commitment_violation"


class RelationshipIssueStatus(StrEnum):
    OPEN = "open"
    RESOLVED = "resolved"


def _uuid7(value: object) -> bool:
    return type(value) is UUID and value.version == 7


def _text(value: object, maximum: int) -> bool:
    return type(value) is str and 1 <= len(value) <= maximum


@dataclass(frozen=True, slots=True)
class RelationshipFact:
    fact_id: UUID
    kind: RelationshipFactKind
    summary: str

    def __post_init__(self) -> None:
        if (
            not _uuid7(self.fact_id)
            or type(self.kind) is not RelationshipFactKind
            or not _text(self.summary, 512)
        ):
            raise RelationshipViolation("RELATIONSHIP-FACT")


@dataclass(frozen=True, slots=True)
class RelationshipFactOperation:
    kind: RelationshipFactOperationKind
    fact_id: UUID | None
    fact: RelationshipFact | None
    context_ref: str | None = None

    def __post_init__(self) -> None:
        if type(self.kind) is not RelationshipFactOperationKind:
            raise RelationshipViolation("RELATIONSHIP-FACT-OPERATION")
        if self.kind is RelationshipFactOperationKind.ADD:
            valid = (
                self.fact_id is None
                and type(self.fact) is RelationshipFact
                and self.context_ref is None
            )
        elif self.kind is RelationshipFactOperationKind.REVISE:
            valid = (
                _uuid7(self.fact_id)
                and type(self.fact) is RelationshipFact
                and self.fact.fact_id == self.fact_id
                and _text(self.context_ref, 256)
            )
        else:
            valid = (
                _uuid7(self.fact_id)
                and self.fact is None
                and _text(self.context_ref, 256)
            )
        if not valid:
            raise RelationshipViolation("RELATIONSHIP-FACT-OPERATION")


@dataclass(frozen=True, slots=True)
class RelationshipBoundary:
    party_role: RelationshipPartyRole
    kind: RelationshipBoundaryKind
    action: RelationshipBoundaryAction
    summary: str

    def __post_init__(self) -> None:
        if (
            type(self.party_role) is not RelationshipPartyRole
            or type(self.kind) is not RelationshipBoundaryKind
            or type(self.action) is not RelationshipBoundaryAction
            or not _text(self.summary, 512)
            or (self.action is RelationshipBoundaryAction.END_CONTACT)
            != (self.kind is RelationshipBoundaryKind.EXIT)
        ):
            raise RelationshipViolation("RELATIONSHIP-BOUNDARY")


@dataclass(frozen=True, slots=True)
class RelationshipBoundaryOperation:
    kind: RelationshipBoundaryOperationKind
    party_role: RelationshipPartyRole
    boundary_kind: RelationshipBoundaryKind
    boundary: RelationshipBoundary | None = None

    def __post_init__(self) -> None:
        if (
            type(self.kind) is not RelationshipBoundaryOperationKind
            or type(self.party_role) is not RelationshipPartyRole
            or type(self.boundary_kind) is not RelationshipBoundaryKind
            or (
                self.kind is RelationshipBoundaryOperationKind.SET
                and (
                    type(self.boundary) is not RelationshipBoundary
                    or self.boundary.party_role is not self.party_role
                    or self.boundary.kind is not self.boundary_kind
                )
            )
            or (
                self.kind is RelationshipBoundaryOperationKind.REMOVE
                and self.boundary is not None
            )
        ):
            raise RelationshipViolation("RELATIONSHIP-BOUNDARY-OPERATION")


@dataclass(frozen=True, slots=True)
class RelationshipCommitment:
    commitment_id: UUID
    party_role: RelationshipPartyRole
    scope: str
    content: str
    status: RelationshipCommitmentStatus
    last_event_kind: RelationshipCommitmentEventKind
    last_event_summary: str

    def __post_init__(self) -> None:
        expected = {
            RelationshipCommitmentEventKind.ESTABLISHED: RelationshipCommitmentStatus.ACTIVE,
            RelationshipCommitmentEventKind.MODIFIED: RelationshipCommitmentStatus.ACTIVE,
            RelationshipCommitmentEventKind.FULFILLED: RelationshipCommitmentStatus.FULFILLED,
            RelationshipCommitmentEventKind.WITHDRAWN: RelationshipCommitmentStatus.WITHDRAWN,
            RelationshipCommitmentEventKind.FORGOTTEN: RelationshipCommitmentStatus.FORGOTTEN,
            RelationshipCommitmentEventKind.VIOLATED: RelationshipCommitmentStatus.VIOLATED,
            RelationshipCommitmentEventKind.CONFLICT_NOTED: self.status,
        }.get(self.last_event_kind)
        if (
            not _uuid7(self.commitment_id)
            or type(self.party_role) is not RelationshipPartyRole
            or not _text(self.scope, 512)
            or not _text(self.content, 1024)
            or type(self.status) is not RelationshipCommitmentStatus
            or type(self.last_event_kind) is not RelationshipCommitmentEventKind
            or not _text(self.last_event_summary, 512)
            or expected is not self.status
        ):
            raise RelationshipViolation("RELATIONSHIP-COMMITMENT")


@dataclass(frozen=True, slots=True)
class RelationshipIssue:
    issue_id: UUID
    kind: RelationshipIssueKind
    commitment_ids: tuple[UUID, ...]
    summary: str
    status: RelationshipIssueStatus = RelationshipIssueStatus.OPEN

    def __post_init__(self) -> None:
        count = 2 if self.kind is RelationshipIssueKind.CONTRADICTORY_COMMITMENTS else 1
        if (
            not _uuid7(self.issue_id)
            or type(self.kind) is not RelationshipIssueKind
            or len(self.commitment_ids) != count
            or len(set(self.commitment_ids)) != count
            or any(not _uuid7(value) for value in self.commitment_ids)
            or not _text(self.summary, 512)
            or type(self.status) is not RelationshipIssueStatus
        ):
            raise RelationshipViolation("RELATIONSHIP-ISSUE")


@dataclass(frozen=True, slots=True)
class IssueResolution:
    issue_id: UUID
    status: RelationshipIssueStatus
    resolution_summary: str

    def __post_init__(self) -> None:
        if (
            not _uuid7(self.issue_id)
            or self.status is not RelationshipIssueStatus.RESOLVED
            or not _text(self.resolution_summary, 512)
        ):
            raise RelationshipViolation("RELATIONSHIP-ISSUE-RESOLUTION")


@dataclass(frozen=True, slots=True)
class RelationshipCommitmentEvent:
    commitment_id: UUID
    kind: RelationshipCommitmentEventKind
    summary: str
    related_commitment_id: UUID | None = None

    def __post_init__(self) -> None:
        if (
            not _uuid7(self.commitment_id)
            or type(self.kind) is not RelationshipCommitmentEventKind
            or not _text(self.summary, 512)
            or (
                self.related_commitment_id is not None
                and (
                    not _uuid7(self.related_commitment_id)
                    or self.related_commitment_id == self.commitment_id
                )
            )
            or (self.kind is RelationshipCommitmentEventKind.CONFLICT_NOTED)
            != (self.related_commitment_id is not None)
        ):
            raise RelationshipViolation("RELATIONSHIP-COMMITMENT-EVENT")


@dataclass(frozen=True, slots=True)
class CandidateRelationshipDraft:
    proposal_ref: str
    atomic_group_ref: str
    basis_ordinals: tuple[int, ...]
    fact_class: CandidateFactClass
    relationship_id: UUID
    subject_party_id: UUID
    other_party_id: UUID
    current_revision_id: UUID | None
    expected_head_version: int
    source_experience_ref: str
    facts: tuple[RelationshipFact, ...]
    interpretation: str
    boundaries: tuple[RelationshipBoundary, ...]
    status: RelationshipStatus
    commitments: tuple[RelationshipCommitment, ...] = ()
    open_issues: tuple[RelationshipIssue, ...] = ()
    commitment_event: RelationshipCommitmentEvent | None = None
    issue_resolution: IssueResolution | None = None
    reopen: bool = False
    scope: str = "creator_social"
    mechanism_identity: str = RELATIONSHIP_MECHANISM_IDENTITY
    privacy_scope: str = "private"

    def __post_init__(self) -> None:
        if (
            not _REF.fullmatch(self.proposal_ref)
            or not self.atomic_group_ref.startswith("group:")
            or not self.basis_ordinals
            or self.fact_class is not CandidateFactClass.SUBJECTIVE_UNDERSTANDING
            or any(
                not _uuid7(value)
                for value in (
                    self.relationship_id,
                    self.subject_party_id,
                    self.other_party_id,
                )
            )
            or self.subject_party_id == self.other_party_id
            or (self.current_revision_id is None) != (self.expected_head_version == 0)
            or type(self.expected_head_version) is not int
            or self.expected_head_version < 0
            or (
                self.current_revision_id is not None
                and not _uuid7(self.current_revision_id)
            )
            or not _REF.fullmatch(self.source_experience_ref)
            or self.source_experience_ref == self.proposal_ref
            or not 1 <= len(self.facts) <= 64
            or any(type(item) is not RelationshipFact for item in self.facts)
            or len({item.fact_id for item in self.facts}) != len(self.facts)
            or not _text(self.interpretation, 1024)
            or len(self.boundaries) > 16
            or any(type(item) is not RelationshipBoundary for item in self.boundaries)
            or len({(item.party_role, item.kind) for item in self.boundaries})
            != len(self.boundaries)
            or (self.status is RelationshipStatus.ENDED)
            != any(
                item.action is RelationshipBoundaryAction.END_CONTACT
                for item in self.boundaries
            )
            or type(self.status) is not RelationshipStatus
            or len(self.commitments) > 16
            or any(
                type(item) is not RelationshipCommitment for item in self.commitments
            )
            or len({item.commitment_id for item in self.commitments})
            != len(self.commitments)
            or len(self.open_issues) > 32
            or any(type(item) is not RelationshipIssue for item in self.open_issues)
            or any(
                item.status is not RelationshipIssueStatus.OPEN
                for item in self.open_issues
            )
            or len({item.issue_id for item in self.open_issues})
            != len(self.open_issues)
            or any(
                commitment_id not in {item.commitment_id for item in self.commitments}
                for issue in self.open_issues
                for commitment_id in issue.commitment_ids
            )
            or (
                self.commitment_event is not None
                and self.commitment_event.commitment_id
                not in {item.commitment_id for item in self.commitments}
            )
            or self.scope not in {"creator_social", "other_human_social"}
            or self.mechanism_identity != RELATIONSHIP_MECHANISM_IDENTITY
            or self.privacy_scope != "private"
        ):
            raise RelationshipViolation("RELATIONSHIP-CANDIDATE")
        if self.reopen and (
            self.current_revision_id is None
            or self.status is not RelationshipStatus.ACTIVE
            or any(
                item.kind is RelationshipBoundaryKind.EXIT for item in self.boundaries
            )
        ):
            raise RelationshipViolation("RELATIONSHIP-REOPEN")
        if self.issue_resolution is not None and any(
            item.issue_id == self.issue_resolution.issue_id for item in self.open_issues
        ):
            raise RelationshipViolation("RELATIONSHIP-ISSUE-RESOLUTION")

    def owner_draft(self, canonical_payload: bytes) -> CandidateOwnerDraft:
        return CandidateOwnerDraft(
            self.proposal_ref,
            self.atomic_group_ref,
            self.basis_ordinals,
            self.fact_class,
            "relationship",
            canonical_payload,
        )


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
    issue_resolution: IssueResolution | None = None

    def __post_init__(self) -> None:
        if (
            not _uuid7(self.relationship_revision_id)
            or type(self.revision_no) is not int
            or self.revision_no < 1
            or not 1 <= len(self.facts) <= 64
            or any(type(item) is not RelationshipFact for item in self.facts)
            or not _text(self.interpretation, 1024)
            or len(self.boundaries) > 16
            or len(self.commitments) > 16
            or len(self.open_issues) > 32
            or type(self.status) is not RelationshipStatus
            or type(self.occurred_at) is not datetime
            or self.occurred_at.tzinfo is None
        ):
            raise RelationshipViolation("RELATIONSHIP-QUERY-REVISION")


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
            or self.head_version != self.current.revision_no
            or type(self.created_at) is not datetime
            or self.created_at.tzinfo is None
            or self.created_at > self.current.occurred_at
        ):
            raise RelationshipViolation("RELATIONSHIP-QUERY-ITEM")


@dataclass(frozen=True, slots=True)
class CreatorRelationshipTimeline:
    relationship_id: UUID
    items: tuple[CreatorRelationshipRevision, ...]
    truncated: bool

    def __post_init__(self) -> None:
        if (
            not _uuid7(self.relationship_id)
            or len(self.items) > 100
            or any(type(item) is not CreatorRelationshipRevision for item in self.items)
            or len({item.revision_no for item in self.items}) != len(self.items)
            or any(
                newer.revision_no <= older.revision_no
                for newer, older in zip(self.items, self.items[1:], strict=False)
            )
            or type(self.truncated) is not bool
        ):
            raise RelationshipViolation("RELATIONSHIP-QUERY-TIMELINE")


@dataclass(frozen=True, slots=True)
class RelationshipSnapshot:
    relationship_id: UUID
    current_revision_id: UUID
    head_version: int
    subject_party_id: UUID
    other_party_id: UUID
    scope: str
    revision: CreatorRelationshipRevision


@dataclass(frozen=True, slots=True)
class RelationshipContextBundle:
    relationships: tuple[tuple[UUID, int, bytes], ...]
    commitments: tuple[tuple[UUID, int, bytes, str], ...]
    open_issues: tuple[tuple[UUID, int, bytes], ...]


@runtime_checkable
class RelationshipReadPort(Protocol):
    async def current(self) -> CreatorRelationshipItem | None: ...
    async def timeline(self, relationship_id: UUID) -> CreatorRelationshipTimeline: ...
    async def context_sources(self, party_id: UUID) -> tuple[object, ...]: ...
    async def candidate_snapshot(self, party_id: UUID) -> object | None: ...
    async def life_record_branch(self, party_id: UUID) -> tuple[object, ...]: ...
    async def outreach_basis(self, party_id: UUID) -> object | None: ...

    async def current_for_party(
        self,
        transaction: PostgreSQLTransaction,
        *,
        subject_id: UUID,
        generation_id: UUID,
        other_party_id: UUID,
        scope: str,
        expected_head_version: int | None = None,
    ) -> RelationshipSnapshot | None: ...

    async def all_current(
        self,
        transaction: PostgreSQLTransaction,
        *,
        subject_id: UUID,
        generation_id: UUID,
    ) -> tuple[RelationshipSnapshot, ...]: ...

    async def context_bundle(
        self,
        transaction: PostgreSQLTransaction,
        *,
        subject_id: UUID,
        generation_id: UUID,
        other_party_id: UUID | None,
        scope: str | None,
    ) -> RelationshipContextBundle: ...


@runtime_checkable
class RelationshipCognitionPort(Protocol):
    def bind(self, candidate: object) -> CandidateOwnerDraft: ...
    def decode_change_set(self, payload: bytes) -> CandidateRelationshipDraft: ...


@runtime_checkable
class RelationshipPolicyPort(Protocol):
    def allows_contact(self, relationship: CandidateRelationshipDraft) -> bool: ...
    def allows_reply(self, relationship: CandidateRelationshipDraft) -> bool: ...
    def allows_outreach(self, relationship: CandidateRelationshipDraft) -> bool: ...

    def allows_snapshot_contact(self, relationship: RelationshipSnapshot) -> bool: ...

    def allows_snapshot_outreach(self, relationship: RelationshipSnapshot) -> bool: ...


@runtime_checkable
class RelationshipCommitPort(Protocol):
    async def commit(
        self,
        transaction: PostgreSQLTransaction,
        *,
        subject_id: UUID,
        generation_id: UUID,
        commit_id: UUID,
        validation_id: UUID,
        experience_ids: dict[str, UUID],
        drafts: tuple[CandidateRelationshipDraft, ...],
    ) -> tuple[UUID, ...]: ...

    async def affected_relationship_ids(
        self, transaction: PostgreSQLTransaction, validation_id: UUID
    ) -> tuple[UUID, ...]: ...


@runtime_checkable
class RelationshipDataRightsParticipant(Protocol):
    async def find_for_party(
        self, transaction: PostgreSQLTransaction, party_id: UUID
    ) -> tuple[UUID, ...]: ...
    async def tombstone(
        self,
        transaction: PostgreSQLTransaction,
        *,
        relationship_id: UUID,
        order_id: UUID,
        tombstoned_at: datetime,
    ) -> None: ...


__all__ = (
    "RELATIONSHIP_MECHANISM_IDENTITY",
    "RELATIONSHIP_PROJECTION_VERSION",
    "CandidateRelationshipDraft",
    "CreatorRelationshipItem",
    "CreatorRelationshipRevision",
    "CreatorRelationshipTimeline",
    "IssueResolution",
    "RelationshipBoundary",
    "RelationshipBoundaryAction",
    "RelationshipBoundaryKind",
    "RelationshipBoundaryOperation",
    "RelationshipBoundaryOperationKind",
    "RelationshipCognitionPort",
    "RelationshipCommitPort",
    "RelationshipCommitment",
    "RelationshipCommitmentEvent",
    "RelationshipCommitmentEventKind",
    "RelationshipCommitmentStatus",
    "RelationshipContextBundle",
    "RelationshipDataRightsParticipant",
    "RelationshipFact",
    "RelationshipFactKind",
    "RelationshipFactOperation",
    "RelationshipFactOperationKind",
    "RelationshipIssue",
    "RelationshipIssueKind",
    "RelationshipIssueStatus",
    "RelationshipPartyRole",
    "RelationshipPolicyPort",
    "RelationshipReadPort",
    "RelationshipSnapshot",
    "RelationshipStatus",
    "RelationshipViolation",
)
