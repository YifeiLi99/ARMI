"""Public contracts of the independent Mind owner."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID

from armi_kernel.application import (
    ConsiderationSignal,
)
from armi_runtime_foundation import AdminContentPort as MindAdminContentPort
from armi_runtime_foundation import PostgreSQLAdminTransaction, PostgreSQLTransaction

from ._domain import initial_mind_state
from ._event_questions import (
    MindEvaluationTarget,
    mind_event_questions,
    parse_mind_event_answers,
)
from ._projection import (
    mind_attention_projection,
    mind_context_items,
    mind_motivation_projection,
    mind_signals,
)
from ._state_algorithm import (
    MIND_PARAMETERS,
    Association,
    DerivedMindState,
    GroundedObject,
    MindChoice,
    MindEvidence,
    MindObjectState,
    MindParameters,
    MindVariable,
    Opportunity,
    VariableState,
    derive_mind,
    mind_attention_weight,
    mind_condition_eligible,
    update_mind_object,
)
from ._state_projection import project_mind_object


class MindViolation(RuntimeError):
    def __init__(self, code: str, field_path: tuple[str | int, ...] = ()) -> None:
        if not code.startswith("MIND-"):
            raise ValueError("invalid Mind error code")
        self.code = code
        self.field_path = field_path
        super().__init__(code)


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


class MindEventPort(Protocol):
    async def apply_event(
        self,
        transaction: PostgreSQLTransaction,
        *,
        subject_id: UUID,
        assessment_id: UUID,
        expected_version: int,
        evidence: tuple[MindEvidence, ...],
    ) -> tuple[bool, UUID]: ...


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
    "MIND_PARAMETERS",
    "Association",
    "DerivedMindState",
    "GroundedObject",
    "MindAdminContentPort",
    "MindAdminCorrectionPort",
    "MindAdminReadPort",
    "MindAdminState",
    "MindBirthContinuity",
    "MindBirthPort",
    "MindChoice",
    "MindCorrectionHead",
    "MindEvaluationTarget",
    "MindEventPort",
    "MindEvidence",
    "MindHead",
    "MindObjectState",
    "MindParameters",
    "MindReadPort",
    "MindRevision",
    "MindVariable",
    "MindViolation",
    "Opportunity",
    "VariableState",
    "derive_mind",
    "initial_mind_state",
    "mind_attention_projection",
    "mind_attention_weight",
    "mind_condition_eligible",
    "mind_context_items",
    "mind_event_questions",
    "mind_motivation_projection",
    "mind_signals",
    "parse_mind_event_answers",
    "project_mind_object",
    "update_mind_object",
)
