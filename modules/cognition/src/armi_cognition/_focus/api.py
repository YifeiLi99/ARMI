"""Public contracts of the independent Focus owner."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID

from armi_kernel.application import (
    CandidateFactClass,
    CandidateOwnerDraft,
    ConsiderationSignal,
)
from armi_runtime_foundation import AdminContentPort as FocusAdminContentPort
from armi_runtime_foundation import PostgreSQLAdminTransaction, PostgreSQLTransaction

from ._cognitive_binding import bind_concern_changes
from ._cognitive_contract import FOCUS_COGNITIVE_INSTRUCTIONS, FOCUS_CONTEXT_REFERENCES
from ._concerns import (
    CONCERN_CHANGES,
    CONCERN_RECORDS,
    ActivityReview,
    CloseConcern,
    ConcernChange,
    ConcernRecord,
    CreateConcern,
    CreatorInputReview,
    TimedReview,
    UpdateConcern,
    concern_attention_status,
)
from ._domain import initial_focus_state, prepare_focus_change
from ._projection import (
    focus_attention_projection,
    focus_context_items,
    focus_editable_state,
    focus_signals,
)


class FocusViolation(RuntimeError):
    def __init__(self, code: str, field_path: tuple[str | int, ...] = ()) -> None:
        if not code.startswith("FOCUS-"):
            raise ValueError("invalid Focus error code")
        self.code = code
        self.field_path = field_path
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class CandidateFocusDraft:
    proposal_ref: str
    atomic_group_ref: str
    basis_ordinals: tuple[int, ...]
    fact_class: CandidateFactClass
    expected_version: int
    canonical_next_state: bytes
    concern_changes: tuple[ConcernChange, ...] = ()

    def __post_init__(self) -> None:
        from ._domain import validate_candidate

        validate_candidate(self)


@dataclass(frozen=True, slots=True)
class FocusHead:
    current_revision_id: UUID
    version: int
    canonical_state: bytes


@dataclass(frozen=True, slots=True)
class FocusAdminState:
    version: int
    privacy_scope: str
    payload: object | None


@dataclass(frozen=True, slots=True)
class FocusCorrectionHead:
    current_revision_id: UUID
    current_version: int
    current_payload: object
    maximum_version: int


@dataclass(frozen=True, slots=True)
class FocusBirthContinuity:
    head_count: int
    revision_count: int


@dataclass(frozen=True, slots=True)
class FocusRevision:
    revision_id: UUID
    version: int
    previous_revision_id: UUID | None
    origin_kind: str
    origin_ref: UUID
    subject_commit_id: UUID | None
    admin_change_id: UUID | None
    created_at: datetime
    redacted_at: datetime | None
    canonical_state: bytes


class FocusReadPort(Protocol):
    async def history(
        self,
        transaction: PostgreSQLTransaction,
        *,
        subject_id: UUID,
        before_version: int | None = None,
        limit: int = 50,
    ) -> tuple[FocusRevision, ...]: ...

    async def history_is_continuous(
        self, transaction: PostgreSQLTransaction, *, subject_id: UUID
    ) -> bool: ...

    async def current_head(
        self, transaction: PostgreSQLTransaction, *, subject_id: UUID
    ) -> FocusHead: ...
    async def current_head_count(
        self, transaction: PostgreSQLTransaction, *, subject_id: UUID
    ) -> int: ...
    async def attention_status(
        self,
        transaction: PostgreSQLTransaction,
        *,
        subject_id: UUID,
        as_of: datetime,
        consumed: frozenset[tuple[str, str, str]],
    ) -> list[dict[str, object]]: ...
    async def consideration_signals(
        self,
        transaction: PostgreSQLTransaction,
        *,
        subject_id: UUID,
        event_purpose: str | None = None,
        event_ref: UUID | None = None,
        event_at: datetime | None = None,
        activity_id: UUID | None = None,
    ) -> tuple[ConsiderationSignal, ...]: ...


class FocusCognitionPort(Protocol):
    def bind(self, value: CandidateFocusDraft) -> CandidateOwnerDraft: ...
    def decode(self, payload: bytes) -> CandidateFocusDraft: ...


class FocusCommitPort(Protocol):
    async def heads_match(
        self,
        transaction: PostgreSQLTransaction,
        *,
        subject_id: UUID,
        drafts: tuple[CandidateFocusDraft, ...],
    ) -> bool: ...
    async def commit(
        self,
        transaction: PostgreSQLTransaction,
        *,
        subject_id: UUID,
        commit_id: UUID,
        drafts: tuple[CandidateFocusDraft, ...],
    ) -> None: ...


class FocusBirthPort(Protocol):
    def continuity(
        self, transaction: PostgreSQLAdminTransaction, *, subject_id: UUID | None
    ) -> FocusBirthContinuity: ...
    async def initialize(
        self, transaction: PostgreSQLTransaction, *, subject_id: UUID
    ) -> None: ...


class FocusAdminReadPort(Protocol):
    def current(
        self, transaction: PostgreSQLAdminTransaction, *, private: bool
    ) -> FocusAdminState: ...


class FocusAdminCorrectionPort(Protocol):
    def canonicalize_replacement(
        self, *, kind: str, replacement: object
    ) -> dict[str, object]: ...
    def current_head(
        self,
        transaction: PostgreSQLAdminTransaction,
        *,
        subject_id: str,
        kind: str,
        for_update: bool,
    ) -> FocusCorrectionHead | None: ...
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
    "CONCERN_CHANGES",
    "CONCERN_RECORDS",
    "FOCUS_COGNITIVE_INSTRUCTIONS",
    "FOCUS_CONTEXT_REFERENCES",
    "ActivityReview",
    "CandidateFocusDraft",
    "CloseConcern",
    "ConcernChange",
    "ConcernRecord",
    "CreateConcern",
    "CreatorInputReview",
    "FocusAdminContentPort",
    "FocusAdminCorrectionPort",
    "FocusAdminReadPort",
    "FocusAdminState",
    "FocusBirthContinuity",
    "FocusBirthPort",
    "FocusCognitionPort",
    "FocusCommitPort",
    "FocusCorrectionHead",
    "FocusHead",
    "FocusReadPort",
    "FocusRevision",
    "FocusViolation",
    "TimedReview",
    "UpdateConcern",
    "bind_concern_changes",
    "concern_attention_status",
    "focus_attention_projection",
    "focus_context_items",
    "focus_editable_state",
    "focus_signals",
    "initial_focus_state",
    "prepare_focus_change",
)
