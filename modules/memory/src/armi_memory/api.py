"""Stable public contract of the subjective-memory owner."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Protocol, runtime_checkable
from uuid import UUID

from armi_kernel.application import CandidateFactClass, CandidateOwnerDraft
from armi_kernel.contracts import Instant, OpaqueCursor
from armi_runtime_foundation import PostgreSQLTransaction

MEMORY_FORMATION_MECHANISM_IDENTITY = "armi.memory-formation.contextual-v1"
MEMORY_REVISION_MECHANISM_IDENTITY = "armi.memory-revision.contextual-v1"
CREATOR_MEMORY_PROJECTION_VERSION = "creator-memory.v1"
_REF = re.compile(r"^proposal:[1-9][0-9]{0,2}$", re.ASCII)
_GROUP = re.compile(r"^group:[1-9][0-9]{0,2}$", re.ASCII)


class MemoryViolation(RuntimeError):
    __slots__ = ("code",)

    def __init__(self, code: str) -> None:
        if type(code) is not str or not code.startswith("MEMORY-"):
            raise ValueError("memory violation code is invalid")
        self.code = code
        super().__init__("memory operation failed")

    def __str__(self) -> str:
        return f"{self.code}: memory operation failed"


class MemorySourceKind(StrEnum):
    EXPERIENCED = "experienced"
    REPORTED = "reported"
    INFERRED = "inferred"
    QUERIED = "queried"
    UNKNOWN = "unknown"


class MemoryAccessibility(StrEnum):
    AVAILABLE = "available"
    FADED = "faded"
    FORGOTTEN = "forgotten"


class MemoryRevisionKind(StrEnum):
    FORMED = "formed"
    RECALLED = "recalled"
    FADED = "faded"
    FORGOTTEN = "forgotten"
    REINTERPRETED = "reinterpreted"


class MemoryRelationKind(StrEnum):
    SUPPORTS = "supports"
    CONTRADICTS = "contradicts"
    REINTERPRETS = "reinterprets"


def _uuid7(value: object) -> bool:
    return type(value) is UUID and value.version == 7


def _text(value: object, maximum: int, *, optional: bool = False) -> bool:
    if value is None:
        return optional
    return type(value) is str and 1 <= len(value) <= maximum and "\x00" not in value


@dataclass(frozen=True, slots=True)
class MemoryFormationRequest:
    proposal_ref: str
    atomic_group_ref: str
    basis_ordinals: tuple[int, ...]
    fact_class: CandidateFactClass
    source_experience_ref: str
    source_kind: MemorySourceKind
    summary: str


@dataclass(frozen=True, slots=True)
class MemoryRevisionRequest:
    proposal_ref: str
    atomic_group_ref: str
    basis_ordinals: tuple[int, ...]
    fact_class: CandidateFactClass
    memory_id: UUID
    current_revision_id: UUID
    expected_head_version: int
    revision_kind: MemoryRevisionKind
    accessibility: MemoryAccessibility
    source_kind: MemorySourceKind
    summary: str
    uncertainty: str | None
    related_memory_id: UUID | None = None
    relation_kind: MemoryRelationKind | None = None
    mechanism_config_identity: str = "natural-dialogue-v1"


@dataclass(frozen=True, slots=True)
class CandidateMemoryDraft:
    proposal_ref: str
    atomic_group_ref: str
    basis_ordinals: tuple[int, ...]
    fact_class: CandidateFactClass
    source_experience_ref: str
    source_kind: MemorySourceKind
    summary: str
    mechanism_identity: str = MEMORY_FORMATION_MECHANISM_IDENTITY
    privacy_scope: str = "private"

    def __post_init__(self) -> None:
        if (
            _REF.fullmatch(self.proposal_ref) is None
            or _GROUP.fullmatch(self.atomic_group_ref) is None
            or not self.basis_ordinals
            or any(
                type(value) is not int or value <= 0 for value in self.basis_ordinals
            )
            or type(self.fact_class) is not CandidateFactClass
            or _REF.fullmatch(self.source_experience_ref) is None
            or self.source_experience_ref == self.proposal_ref
            or type(self.source_kind) is not MemorySourceKind
            or not _text(self.summary, 512)
            or not _memory_source_supported(self.source_kind, self.fact_class)
            or self.mechanism_identity != MEMORY_FORMATION_MECHANISM_IDENTITY
            or self.privacy_scope != "private"
        ):
            raise MemoryViolation("MEMORY-FORMATION")

    def owner_draft(self, canonical_payload: bytes) -> CandidateOwnerDraft:
        return CandidateOwnerDraft(
            self.proposal_ref,
            self.atomic_group_ref,
            self.basis_ordinals,
            self.fact_class,
            "memory",
            canonical_payload,
        )


@dataclass(frozen=True, slots=True)
class CandidateMemoryRevisionDraft:
    proposal_ref: str
    atomic_group_ref: str
    basis_ordinals: tuple[int, ...]
    fact_class: CandidateFactClass
    memory_id: UUID
    current_revision_id: UUID
    expected_head_version: int
    revision_kind: MemoryRevisionKind
    accessibility: MemoryAccessibility
    source_kind: MemorySourceKind
    summary: str
    uncertainty: str | None
    related_memory_id: UUID | None = None
    relation_kind: MemoryRelationKind | None = None
    mechanism_identity: str = MEMORY_REVISION_MECHANISM_IDENTITY
    mechanism_config_identity: str = "natural-dialogue-v1"
    privacy_scope: str = "private"

    def __post_init__(self) -> None:
        if (
            _REF.fullmatch(self.proposal_ref) is None
            or _GROUP.fullmatch(self.atomic_group_ref) is None
            or not self.basis_ordinals
            or type(self.fact_class) is not CandidateFactClass
            or not _uuid7(self.memory_id)
            or not _uuid7(self.current_revision_id)
            or type(self.expected_head_version) is not int
            or self.expected_head_version <= 0
            or type(self.revision_kind) is not MemoryRevisionKind
            or self.revision_kind is MemoryRevisionKind.FORMED
            or type(self.accessibility) is not MemoryAccessibility
            or type(self.source_kind) is not MemorySourceKind
            or not _text(self.summary, 512)
            or not _text(self.uncertainty, 512, optional=True)
            or self.mechanism_identity != MEMORY_REVISION_MECHANISM_IDENTITY
            or self.mechanism_config_identity
            not in {"natural-dialogue-v1", "sleep-maintenance-v1"}
            or self.privacy_scope != "private"
        ):
            raise MemoryViolation("MEMORY-REVISION")
        expected = {
            MemoryRevisionKind.RECALLED: MemoryAccessibility.AVAILABLE,
            MemoryRevisionKind.FADED: MemoryAccessibility.FADED,
            MemoryRevisionKind.FORGOTTEN: MemoryAccessibility.FORGOTTEN,
            MemoryRevisionKind.REINTERPRETED: self.accessibility,
        }[self.revision_kind]
        if self.accessibility is not expected or (
            self.revision_kind is MemoryRevisionKind.REINTERPRETED
            and self.accessibility is MemoryAccessibility.FORGOTTEN
        ):
            raise MemoryViolation("MEMORY-REVISION-SHAPE")
        relation = (self.related_memory_id, self.relation_kind)
        if any(value is not None for value in relation) != all(
            value is not None for value in relation
        ):
            raise MemoryViolation("MEMORY-RELATION")
        if self.related_memory_id is not None and (
            not _uuid7(self.related_memory_id)
            or self.related_memory_id == self.memory_id
            or self.revision_kind is not MemoryRevisionKind.REINTERPRETED
            or type(self.relation_kind) is not MemoryRelationKind
        ):
            raise MemoryViolation("MEMORY-RELATION")

    def owner_draft(self, canonical_payload: bytes) -> CandidateOwnerDraft:
        return CandidateOwnerDraft(
            self.proposal_ref,
            self.atomic_group_ref,
            self.basis_ordinals,
            self.fact_class,
            "memory",
            canonical_payload,
        )


@dataclass(frozen=True, slots=True)
class MemoryContextItem:
    memory_id: UUID
    current_revision_id: UUID
    head_version: int
    fact_class: CandidateFactClass
    source_kind: MemorySourceKind
    summary: str
    uncertainty: str | None
    accessibility: MemoryAccessibility

    def __post_init__(self) -> None:
        if (
            not _uuid7(self.memory_id)
            or not _uuid7(self.current_revision_id)
            or type(self.head_version) is not int
            or self.head_version <= 0
            or type(self.fact_class) is not CandidateFactClass
            or type(self.source_kind) is not MemorySourceKind
            or not _text(self.summary, 512)
            or not _text(self.uncertainty, 512, optional=True)
            or type(self.accessibility) is not MemoryAccessibility
            or self.accessibility is MemoryAccessibility.FORGOTTEN
        ):
            raise MemoryViolation("MEMORY-CONTEXT")


@dataclass(frozen=True, slots=True)
class CreatorMemoryItem:
    memory_id: UUID
    summary: str
    uncertainty: str | None
    source_kind: str
    source_fact_class: str
    accessibility: MemoryAccessibility
    revision_kind: MemoryRevisionKind
    revision_no: int
    head_version: int
    created_at: Instant
    updated_at: Instant


@dataclass(frozen=True, slots=True)
class CreatorMemoryPage:
    items: tuple[CreatorMemoryItem, ...]
    next_cursor: OpaqueCursor | None = None
    projection_version: str = CREATOR_MEMORY_PROJECTION_VERSION


@dataclass(frozen=True, slots=True)
class CreatorMemoryTimelineItem:
    revision_id: UUID
    revision_no: int
    revision_kind: MemoryRevisionKind
    accessibility: MemoryAccessibility
    summary: str
    uncertainty: str | None
    source_kind: str
    source_fact_class: str
    relation_kind: MemoryRelationKind | None
    related_memory_id: UUID | None
    occurred_at: Instant


@dataclass(frozen=True, slots=True)
class CreatorMemoryTimeline:
    memory_id: UUID
    items: tuple[CreatorMemoryTimelineItem, ...]
    next_cursor: OpaqueCursor | None = None
    projection_version: str = CREATOR_MEMORY_PROJECTION_VERSION


@dataclass(frozen=True, slots=True)
class MemoryLifeRecordItem:
    memory_id: UUID
    summary: str
    source_kind: str
    occurred_at: datetime
    naturally_recallable: bool


@dataclass(frozen=True, slots=True)
class MemoryProjectionSource:
    subject_id: UUID
    generation_id: UUID
    memory_id: UUID
    head_version: int
    text: str


@dataclass(frozen=True, slots=True)
class MemoryCandidateSourceRef:
    memory_id: UUID
    head_version: int

    def __post_init__(self) -> None:
        if (
            not _uuid7(self.memory_id)
            or type(self.head_version) is not int
            or self.head_version <= 0
        ):
            raise MemoryViolation("MEMORY-SOURCE-REF")


@runtime_checkable
class MemoryReadPort(Protocol):
    async def maintenance_context(
        self,
        transaction: PostgreSQLTransaction,
        *,
        subject_id: UUID,
        generation_id: UUID,
        enabled: bool,
        limit: int = 8,
    ) -> tuple[MemoryContextItem, ...]: ...

    async def candidate_context(
        self,
        transaction: PostgreSQLTransaction,
        *,
        subject_id: UUID,
        sources: tuple[MemoryCandidateSourceRef, ...],
    ) -> tuple[MemoryContextItem, ...]: ...

    async def life_record_branch(
        self,
        transaction: PostgreSQLTransaction,
        *,
        subject_id: UUID,
        query_text: str | None,
        before: tuple[datetime, str, UUID] | None,
        limit: int,
    ) -> tuple[MemoryLifeRecordItem, ...]: ...

    async def list_current(
        self,
        *,
        limit: int,
        query_text: str | None = None,
        cursor: OpaqueCursor | None = None,
    ) -> CreatorMemoryPage: ...

    async def timeline(
        self,
        memory_id: UUID,
        *,
        limit: int,
        cursor: OpaqueCursor | None = None,
    ) -> CreatorMemoryTimeline: ...


@runtime_checkable
class MemoryCandidateContextPort(Protocol):
    async def memory_sources(
        self,
        transaction: PostgreSQLTransaction,
        *,
        episode_id: UUID,
    ) -> tuple[MemoryCandidateSourceRef, ...]: ...


@runtime_checkable
class MemoryCognitionPort(Protocol):
    def bind_formation(
        self, request: MemoryFormationRequest
    ) -> CandidateOwnerDraft: ...
    def bind_revision(self, request: MemoryRevisionRequest) -> CandidateOwnerDraft: ...
    def decode(
        self, payload: bytes
    ) -> CandidateMemoryDraft | CandidateMemoryRevisionDraft: ...
    def bind_wire(self, value: object, *, revision: bool) -> CandidateOwnerDraft: ...


@dataclass(frozen=True, slots=True)
class MemoryExperienceSource:
    proposal_ref: str
    experience_id: UUID
    uncertainty: str | None


@runtime_checkable
class MemoryCommitPort(Protocol):
    async def heads_match(
        self,
        transaction: PostgreSQLTransaction,
        *,
        subject_id: UUID,
        drafts: tuple[CandidateMemoryDraft | CandidateMemoryRevisionDraft, ...],
    ) -> bool: ...

    async def commit(
        self,
        transaction: PostgreSQLTransaction,
        *,
        subject_id: UUID,
        generation_id: UUID,
        commit_id: UUID,
        validation_id: UUID,
        drafts: tuple[CandidateMemoryDraft | CandidateMemoryRevisionDraft, ...],
        experience_sources: tuple[MemoryExperienceSource, ...],
    ) -> tuple[UUID, ...]: ...

    async def affected_memory_ids(
        self, transaction: PostgreSQLTransaction, validation_id: UUID
    ) -> tuple[UUID, ...]: ...


@runtime_checkable
class MemoryProjectionPort(Protocol):
    async def projection_sources(
        self,
        transaction: PostgreSQLTransaction,
        *,
        subject_id: UUID | None = None,
        generation_id: UUID | None = None,
    ) -> tuple[MemoryProjectionSource, ...]: ...

    async def load_source(
        self, transaction: PostgreSQLTransaction, memory_id: UUID
    ) -> MemoryProjectionSource | None: ...


def _memory_source_supported(
    source_kind: MemorySourceKind, fact_class: CandidateFactClass
) -> bool:
    return (
        fact_class
        in {
            MemorySourceKind.EXPERIENCED: {
                CandidateFactClass.OBJECTIVE_FACT,
                CandidateFactClass.SUBJECTIVE_UNDERSTANDING,
            },
            MemorySourceKind.REPORTED: {CandidateFactClass.EXTERNAL_CLAIM},
            MemorySourceKind.INFERRED: {CandidateFactClass.INFERENCE},
            MemorySourceKind.QUERIED: {
                CandidateFactClass.OBJECTIVE_FACT,
                CandidateFactClass.EXTERNAL_CLAIM,
                CandidateFactClass.SUBJECTIVE_UNDERSTANDING,
            },
            MemorySourceKind.UNKNOWN: {CandidateFactClass.UNKNOWN},
        }[source_kind]
    )


__all__ = (
    "CREATOR_MEMORY_PROJECTION_VERSION",
    "MEMORY_FORMATION_MECHANISM_IDENTITY",
    "MEMORY_REVISION_MECHANISM_IDENTITY",
    "CandidateMemoryDraft",
    "CandidateMemoryRevisionDraft",
    "CreatorMemoryItem",
    "CreatorMemoryPage",
    "CreatorMemoryTimeline",
    "CreatorMemoryTimelineItem",
    "MemoryAccessibility",
    "MemoryCandidateContextPort",
    "MemoryCandidateSourceRef",
    "MemoryCognitionPort",
    "MemoryCommitPort",
    "MemoryContextItem",
    "MemoryExperienceSource",
    "MemoryFormationRequest",
    "MemoryLifeRecordItem",
    "MemoryProjectionPort",
    "MemoryProjectionSource",
    "MemoryReadPort",
    "MemoryRelationKind",
    "MemoryRevisionKind",
    "MemoryRevisionRequest",
    "MemorySourceKind",
    "MemoryViolation",
)
