"""Public contracts of the independent Mind owner."""

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
from armi_runtime_foundation import AdminContentPort as MindAdminContentPort
from armi_runtime_foundation import PostgreSQLAdminTransaction, PostgreSQLTransaction

from ._appraisal import (
    MIND_APPRAISAL_INSTRUCTIONS,
    MindAppraisal,
    MotivationalProjection,
    MotivationalState,
    evaluate_motivation,
    project_motivation,
)
from ._cognitive_binding import bind_concern_changes, bind_mind_change
from ._cognitive_contract import (
    MIND_COGNITIVE_INSTRUCTIONS,
    MIND_CONTEXT_REFERENCES,
    DialogueMindChange,
    GroundedMindChange,
    MindState,
    apply_mind_text_change,
)
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
from ._domain import initial_mind_state, prepare_mind_change
from ._motivation import BoundMindAppraisal, bind_mind_appraisals
from ._projection import (
    mind_attention_projection,
    mind_context_items,
    mind_editable_state,
    mind_motivation_projection,
    mind_signals,
)


class MindViolation(RuntimeError):
    def __init__(self, code: str, field_path: tuple[str | int, ...] = ()) -> None:
        if not code.startswith("MIND-"):
            raise ValueError("invalid Mind error code")
        self.code = code
        self.field_path = field_path
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class CandidateMindDraft:
    proposal_ref: str
    atomic_group_ref: str
    basis_ordinals: tuple[int, ...]
    fact_class: CandidateFactClass
    expected_version: int
    canonical_next_state: bytes
    concern_changes: tuple[ConcernChange, ...] = ()
    mind_appraisals: tuple[BoundMindAppraisal, ...] = ()

    def __post_init__(self) -> None:
        from ._domain import validate_candidate

        validate_candidate(self)


@dataclass(frozen=True, slots=True)
class MindHead:
    current_revision_id: UUID
    version: int
    canonical_state: bytes


@dataclass(frozen=True, slots=True)
class MindAdminState:
    version: int
    privacy_scope: str
    payload: object | None


@dataclass(frozen=True, slots=True)
class MindCorrectionHead:
    current_revision_id: UUID
    current_version: int
    current_payload: object
    maximum_version: int


@dataclass(frozen=True, slots=True)
class MindBirthContinuity:
    head_count: int
    revision_count: int


@dataclass(frozen=True, slots=True)
class MindRevision:
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


class MindReadPort(Protocol):
    async def motivation_status(
        self,
        transaction: PostgreSQLTransaction,
        *,
        subject_id: UUID,
        as_of: datetime,
        consumed: frozenset[tuple[str, str, str]],
    ) -> list[dict[str, object]]: ...

    async def history(
        self,
        transaction: PostgreSQLTransaction,
        *,
        subject_id: UUID,
        before_version: int | None = None,
        limit: int = 50,
    ) -> tuple[MindRevision, ...]: ...

    async def history_is_continuous(
        self, transaction: PostgreSQLTransaction, *, subject_id: UUID
    ) -> bool: ...

    async def current_head(
        self, transaction: PostgreSQLTransaction, *, subject_id: UUID
    ) -> MindHead: ...
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


class MindCognitionPort(Protocol):
    def bind(self, value: CandidateMindDraft) -> CandidateOwnerDraft: ...
    def decode(self, payload: bytes) -> CandidateMindDraft: ...


class MindCommitPort(Protocol):
    async def heads_match(
        self,
        transaction: PostgreSQLTransaction,
        *,
        subject_id: UUID,
        drafts: tuple[CandidateMindDraft, ...],
    ) -> bool: ...
    async def commit(
        self,
        transaction: PostgreSQLTransaction,
        *,
        subject_id: UUID,
        commit_id: UUID,
        drafts: tuple[CandidateMindDraft, ...],
    ) -> None: ...


class MindBirthPort(Protocol):
    def continuity(
        self, transaction: PostgreSQLAdminTransaction, *, subject_id: UUID | None
    ) -> MindBirthContinuity: ...
    async def initialize(
        self, transaction: PostgreSQLTransaction, *, subject_id: UUID
    ) -> None: ...


class MindAdminReadPort(Protocol):
    def current(
        self, transaction: PostgreSQLAdminTransaction, *, private: bool
    ) -> MindAdminState: ...


class MindAdminCorrectionPort(Protocol):
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
    ) -> MindCorrectionHead | None: ...
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
    "MIND_APPRAISAL_INSTRUCTIONS",
    "MIND_COGNITIVE_INSTRUCTIONS",
    "MIND_CONTEXT_REFERENCES",
    "ActivityReview",
    "BoundMindAppraisal",
    "CandidateMindDraft",
    "CloseConcern",
    "ConcernChange",
    "ConcernRecord",
    "CreateConcern",
    "CreatorInputReview",
    "DialogueMindChange",
    "GroundedMindChange",
    "MindAdminContentPort",
    "MindAdminCorrectionPort",
    "MindAdminReadPort",
    "MindAdminState",
    "MindAppraisal",
    "MindBirthContinuity",
    "MindBirthPort",
    "MindCognitionPort",
    "MindCommitPort",
    "MindCorrectionHead",
    "MindHead",
    "MindReadPort",
    "MindRevision",
    "MindState",
    "MindViolation",
    "MotivationalProjection",
    "MotivationalState",
    "TimedReview",
    "UpdateConcern",
    "apply_mind_text_change",
    "bind_concern_changes",
    "bind_mind_appraisals",
    "bind_mind_change",
    "concern_attention_status",
    "evaluate_motivation",
    "initial_mind_state",
    "mind_attention_projection",
    "mind_context_items",
    "mind_editable_state",
    "mind_motivation_projection",
    "mind_signals",
    "prepare_mind_change",
    "project_motivation",
)
