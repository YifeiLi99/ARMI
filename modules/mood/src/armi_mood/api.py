"""Stable public contract of the mood owner."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable
from uuid import UUID

from armi_runtime_foundation import AdminContentPort as MoodAdminContentPort
from armi_runtime_foundation import PostgreSQLAdminTransaction, PostgreSQLTransaction

from ._evaluation_contract import (
    MoodAppraiserPort,
    MoodAssessment,
    MoodAssessmentReadPort,
    MoodEvaluationPort,
    MoodEvent,
    MoodEventStorePort,
    MoodView,
)
from ._projection import (
    active_mood_episodes,
    active_mood_gists,
    mood_context_items,
    mood_dialogue_text,
    mood_snapshot_bytes,
)
from ._psychology import (
    Affect,
    Appraisal,
    DynamicsParameters,
    EmotionKind,
    GoalAppraisal,
    MoodDynamics,
    advance,
    apply_appraisal,
    current_affect,
    derive_response,
    initial_dynamics,
)
from ._questions import (
    MODEL as JEV_MODEL,
)
from ._questions import (
    EvaluatedAppraisal,
    appraisal_questions,
    parse_appraisal_response,
)


class MoodViolation(RuntimeError):
    __slots__ = ("code",)

    def __init__(self, code: str) -> None:
        if type(code) is not str or not code.startswith("MOOD-"):
            raise ValueError("mood violation code is invalid")
        self.code = code
        super().__init__("mood operation failed")

    def __str__(self) -> str:
        return f"{self.code}: mood operation failed"


@dataclass(frozen=True, slots=True)
class MoodHead:
    current_revision_id: UUID
    version: int
    canonical_state: bytes


@dataclass(frozen=True, slots=True)
class MoodAdminComponent:
    kind: str
    version: int
    privacy_scope: str
    payload: object | None


@dataclass(frozen=True, slots=True)
class MoodCorrectionHead:
    current_revision_id: UUID
    current_version: int
    current_payload: object
    maximum_version: int


@runtime_checkable
class MoodReadPort(Protocol):
    async def current(
        self, transaction: PostgreSQLTransaction, *, subject_id: UUID
    ) -> MoodHead: ...

    async def snapshot(
        self, transaction: PostgreSQLTransaction, *, subject_id: UUID
    ) -> MoodView: ...

    async def current_head_count(
        self, transaction: PostgreSQLTransaction, *, subject_id: UUID
    ) -> int: ...


@runtime_checkable
class MoodBirthPort(Protocol):
    def continuity(
        self, transaction: PostgreSQLAdminTransaction, *, subject_id: UUID | None
    ) -> MoodBirthContinuity: ...

    async def initialize(
        self, transaction: PostgreSQLTransaction, *, subject_id: UUID
    ) -> None: ...


@dataclass(frozen=True, slots=True)
class MoodBirthContinuity:
    head_count: int
    revision_count: int


@runtime_checkable
class MoodAdminReadPort(Protocol):
    def current_component(
        self, transaction: PostgreSQLAdminTransaction, *, private: bool
    ) -> MoodAdminComponent | None: ...


@runtime_checkable
class MoodAdminCorrectionPort(Protocol):
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
    ) -> MoodCorrectionHead | None: ...

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
    "JEV_MODEL",
    "Affect",
    "Appraisal",
    "DynamicsParameters",
    "EmotionKind",
    "EvaluatedAppraisal",
    "GoalAppraisal",
    "MoodAdminComponent",
    "MoodAdminContentPort",
    "MoodAdminCorrectionPort",
    "MoodAdminReadPort",
    "MoodAppraiserPort",
    "MoodAssessment",
    "MoodAssessmentReadPort",
    "MoodBirthContinuity",
    "MoodBirthPort",
    "MoodCorrectionHead",
    "MoodDynamics",
    "MoodEvaluationPort",
    "MoodEvent",
    "MoodEventStorePort",
    "MoodHead",
    "MoodReadPort",
    "MoodView",
    "MoodViolation",
    "active_mood_episodes",
    "active_mood_gists",
    "advance",
    "apply_appraisal",
    "appraisal_questions",
    "current_affect",
    "derive_response",
    "initial_dynamics",
    "mood_context_items",
    "mood_dialogue_text",
    "mood_snapshot_bytes",
    "parse_appraisal_response",
)
