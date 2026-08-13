"""Stable public contract of the Self, Mind, and life-mode owner."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Protocol, runtime_checkable
from uuid import UUID

from armi_kernel.application import CandidateFactClass, CandidateOwnerDraft
from armi_runtime_foundation import PostgreSQLAdminTransaction, PostgreSQLTransaction


class SubjectStateKind(StrEnum):
    SELF = "self"
    MIND = "mind"
    LIFE_MODE = "life_mode"


class SubjectStateViolation(RuntimeError):
    __slots__ = ("code",)

    def __init__(self, code: str) -> None:
        if type(code) is not str or not code.startswith("SUBJECT-STATE-"):
            raise ValueError("subject-state violation code is invalid")
        self.code = code
        super().__init__("subject-state operation failed")

    def __str__(self) -> str:
        return f"{self.code}: subject-state operation failed"


@dataclass(frozen=True, slots=True)
class CandidateSubjectStateDraft:
    proposal_ref: str
    atomic_group_ref: str
    basis_ordinals: tuple[int, ...]
    fact_class: CandidateFactClass
    kind: SubjectStateKind
    expected_version: int
    canonical_next_state: bytes

    def __post_init__(self) -> None:
        from ._domain import validate_candidate

        validate_candidate(self)


@dataclass(frozen=True, slots=True)
class SubjectStateHead:
    kind: SubjectStateKind
    current_revision_id: UUID
    version: int
    canonical_state: bytes


@dataclass(frozen=True, slots=True)
class LifeModeHead:
    current_revision_id: UUID
    version: int
    active_activity_ids: tuple[UUID, ...]


@dataclass(frozen=True, slots=True)
class SubjectStateLifeRecordItem:
    revision_id: UUID
    summary: str
    source_kind: str
    occurred_at: datetime


@dataclass(frozen=True, slots=True)
class SubjectComponentSummary:
    kind: SubjectStateKind
    version: int
    schema_version: str
    content_visibility: str = "private"

    def __post_init__(self) -> None:
        expected = {
            SubjectStateKind.SELF: "armi.self.v1",
            SubjectStateKind.MIND: "armi.mind.v2",
            SubjectStateKind.LIFE_MODE: "armi.life-mode.v1",
        }
        if (
            type(self.kind) is not SubjectStateKind
            or type(self.version) is not int
            or self.version <= 0
            or self.schema_version != expected[self.kind]
            or self.content_visibility != "private"
        ):
            raise SubjectStateViolation("SUBJECT-STATE-SUMMARY")


@dataclass(frozen=True, slots=True)
class SubjectSummary:
    subject_version: int
    components: tuple[SubjectComponentSummary, ...]
    latest_commit_ref: UUID | None
    observed_at: datetime

    def __post_init__(self) -> None:
        if (
            type(self.subject_version) is not int
            or self.subject_version < 0
            or tuple(item.kind for item in self.components)
            != (
                SubjectStateKind.SELF,
                SubjectStateKind.MIND,
                SubjectStateKind.LIFE_MODE,
            )
            or (
                self.latest_commit_ref is not None
                and (
                    type(self.latest_commit_ref) is not UUID
                    or self.latest_commit_ref.version != 7
                )
            )
            or type(self.observed_at) is not datetime
            or self.observed_at.tzinfo is None
        ):
            raise SubjectStateViolation("SUBJECT-STATE-SUMMARY")


@dataclass(frozen=True, slots=True)
class SubjectStateAdminComponent:
    kind: SubjectStateKind
    version: int
    privacy_scope: str
    payload: object | None


@dataclass(frozen=True, slots=True)
class SubjectStateCorrectionHead:
    current_revision_id: UUID
    current_version: int
    current_payload: object
    maximum_version: int


@runtime_checkable
class SubjectStateReadPort(Protocol):
    async def active_activity_ids(
        self, transaction: PostgreSQLTransaction, *, subject_id: UUID
    ) -> tuple[UUID, ...]: ...

    async def current_heads(
        self, transaction: PostgreSQLTransaction, *, subject_id: UUID
    ) -> tuple[SubjectStateHead, ...]: ...

    async def life_mode(
        self, transaction: PostgreSQLTransaction, *, subject_id: UUID
    ) -> LifeModeHead: ...

    async def life_record_branch(
        self,
        transaction: PostgreSQLTransaction,
        *,
        subject_id: UUID,
        query_text: str | None,
        before: tuple[datetime, str, UUID] | None,
        limit: int,
    ) -> tuple[SubjectStateLifeRecordItem, ...]: ...

    async def current_head_count(
        self, transaction: PostgreSQLTransaction, *, subject_id: UUID
    ) -> int: ...


@runtime_checkable
class SubjectStateCognitionPort(Protocol):
    def bind(self, value: CandidateSubjectStateDraft) -> CandidateOwnerDraft: ...
    def decode(self, payload: bytes) -> CandidateSubjectStateDraft: ...


@runtime_checkable
class SubjectStateCommitPort(Protocol):
    async def heads_match(
        self,
        transaction: PostgreSQLTransaction,
        *,
        subject_id: UUID,
        drafts: tuple[CandidateSubjectStateDraft, ...],
    ) -> bool: ...

    async def commit(
        self,
        transaction: PostgreSQLTransaction,
        *,
        subject_id: UUID,
        commit_id: UUID,
        drafts: tuple[CandidateSubjectStateDraft, ...],
    ) -> tuple[SubjectStateKind, ...]: ...

    async def update_life_focus(
        self,
        transaction: PostgreSQLTransaction,
        *,
        subject_id: UUID,
        commit_id: UUID,
        activity_id: UUID | None,
        proposal_ref: str,
    ) -> None: ...


@runtime_checkable
class SubjectStateBirthPort(Protocol):
    async def initialize(
        self, transaction: PostgreSQLTransaction, *, subject_id: UUID
    ) -> None: ...


@runtime_checkable
class SubjectStateAdminReadPort(Protocol):
    def current_components(
        self, transaction: PostgreSQLAdminTransaction, *, private: bool
    ) -> tuple[SubjectStateAdminComponent, ...]: ...


@runtime_checkable
class SubjectStateAdminCorrectionPort(Protocol):
    def current_head(
        self,
        transaction: PostgreSQLAdminTransaction,
        *,
        subject_id: str,
        kind: str,
        for_update: bool,
    ) -> SubjectStateCorrectionHead | None: ...

    def revision(
        self,
        transaction: PostgreSQLAdminTransaction,
        *,
        revision_id: str,
        subject_id: str,
        kind: str,
    ) -> tuple[UUID, int] | None: ...

    def replace(
        self,
        transaction: PostgreSQLAdminTransaction,
        *,
        revision_id: str,
        subject_id: str,
        kind: str,
        version: int,
        previous_revision_id: str,
        replacement: object,
    ) -> bool: ...

    def repair_head(
        self,
        transaction: PostgreSQLAdminTransaction,
        *,
        subject_id: str,
        kind: str,
        current_revision_id: str,
        current_version: int,
        target_revision_id: str,
        target_version: int,
    ) -> bool: ...

    def find_current(
        self, transaction: PostgreSQLAdminTransaction, *, kind: str
    ) -> tuple[UUID, int] | None: ...


__all__ = (
    "CandidateSubjectStateDraft",
    "LifeModeHead",
    "SubjectComponentSummary",
    "SubjectStateAdminComponent",
    "SubjectStateAdminCorrectionPort",
    "SubjectStateAdminReadPort",
    "SubjectStateBirthPort",
    "SubjectStateCognitionPort",
    "SubjectStateCommitPort",
    "SubjectStateCorrectionHead",
    "SubjectStateHead",
    "SubjectStateKind",
    "SubjectStateLifeRecordItem",
    "SubjectStateReadPort",
    "SubjectStateViolation",
    "SubjectSummary",
)
