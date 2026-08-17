"""Public contracts for sleep decisions and maintenance sessions."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Final, Literal, Protocol, runtime_checkable
from uuid import UUID

from armi_kernel.application import CandidateOwnerDraft
from armi_runtime_foundation import (
    PostgreSQLRuntimeUnitOfWork,
    PostgreSQLTransaction,
)

from ._domain import (
    MaintenanceCheckpointPlan,
    MaintenancePhase,
    MaintenancePhaseState,
    MaintenanceResultStatus,
    MaintenanceTriggerKind,
    MaintenanceViolation,
    MaintenanceWorkOutcome,
    SleepDecisionKind,
    plan_maintenance_checkpoint,
    validate_maintenance_advance,
)

MAINTENANCE_PROJECTION_VERSION: Final = "creator-maintenance.v2"
type MaintenanceTransitionKind = Literal[
    "started",
    "advanced",
    "completed",
    "interrupted",
    "system_failed",
]


class MaintenanceOpportunityStatus(StrEnum):
    """Outcome of the sleep-owned maintenance source scan."""

    ADMITTED = "admitted"
    DUPLICATE = "duplicate"
    REJECTED = "rejected"


@dataclass(frozen=True, slots=True)
class MaintenanceOpportunityOutcome:
    status: MaintenanceOpportunityStatus
    opportunity_id: UUID | None
    reason_code: str | None = None

    def __post_init__(self) -> None:
        rejected = self.status is MaintenanceOpportunityStatus.REJECTED
        if (
            type(self.status) is not MaintenanceOpportunityStatus
            or rejected != (self.opportunity_id is None)
            or (
                self.opportunity_id is not None
                and (
                    type(self.opportunity_id) is not UUID
                    or self.opportunity_id.version != 7
                )
            )
            or (
                rejected
                and (
                    type(self.reason_code) is not str
                    or not self.reason_code.startswith("LIFE-")
                )
            )
            or (not rejected and self.reason_code is not None)
        ):
            raise SleepViolation("SLEEP-MAINTENANCE-OUTCOME")


_REF = re.compile(r"^proposal:[1-9][0-9]{0,2}$", re.ASCII)
_GROUP = re.compile(r"^group:[1-9][0-9]{0,2}$", re.ASCII)


class SleepViolation(RuntimeError):
    __slots__ = ("code",)

    def __init__(self, code: str) -> None:
        if type(code) is not str or not code.startswith("SLEEP-"):
            raise ValueError("sleep violation code is invalid")
        self.code = code
        super().__init__("sleep operation failed")

    def __str__(self) -> str:
        return f"{self.code}: sleep operation failed"


def _proposal(
    proposal_ref: str,
    atomic_group_ref: str,
    basis_ordinals: tuple[int, ...],
) -> None:
    if (
        type(proposal_ref) is not str
        or _REF.fullmatch(proposal_ref) is None
        or type(atomic_group_ref) is not str
        or _GROUP.fullmatch(atomic_group_ref) is None
        or type(basis_ordinals) is not tuple
        or not basis_ordinals
        or len(basis_ordinals) > 8
        or any(
            type(value) is not int or not 1 <= value <= 999 for value in basis_ordinals
        )
        or len(set(basis_ordinals)) != len(basis_ordinals)
    ):
        raise SleepViolation("SLEEP-CANDIDATE-PROPOSAL")


@dataclass(frozen=True, slots=True)
class CandidateSleepDecisionDraft:
    proposal_ref: str
    atomic_group_ref: str
    basis_ordinals: tuple[int, ...]
    decision_kind: SleepDecisionKind
    cycle_anchor_ref: UUID

    def __post_init__(self) -> None:
        _proposal(self.proposal_ref, self.atomic_group_ref, self.basis_ordinals)
        if (
            type(self.decision_kind) is not SleepDecisionKind
            or type(self.cycle_anchor_ref) is not UUID
            or self.cycle_anchor_ref.version != 7
        ):
            raise SleepViolation("SLEEP-CANDIDATE-DECISION")


@dataclass(frozen=True, slots=True)
class CandidateMaintenanceDecisionDraft:
    proposal_ref: str
    atomic_group_ref: str
    basis_ordinals: tuple[int, ...]
    maintenance_session_id: UUID
    current_revision_id: UUID
    expected_head_version: int
    phase: MaintenancePhase
    outcome: MaintenanceWorkOutcome
    result_summary: str
    creator_visible_problem: str | None = None
    memory_proposal_ref: str | None = None
    issue_target: str | None = None

    def __post_init__(self) -> None:
        _proposal(self.proposal_ref, self.atomic_group_ref, self.basis_ordinals)
        if (
            any(
                type(value) is not UUID or value.version != 7
                for value in (self.maintenance_session_id, self.current_revision_id)
            )
            or type(self.expected_head_version) is not int
            or self.expected_head_version <= 0
            or self.phase
            not in {
                MaintenancePhase.MEMORY_MAINTENANCE,
                MaintenancePhase.SELF_CHECK,
                MaintenancePhase.REFLECT_SELF,
                MaintenancePhase.REFLECT_MIND,
                MaintenancePhase.REFLECT_PROMPT,
            }
            or type(self.outcome) is not MaintenanceWorkOutcome
            or type(self.result_summary) is not str
            or not 1 <= len(self.result_summary) <= 512
            or (
                self.creator_visible_problem is not None
                and (
                    type(self.creator_visible_problem) is not str
                    or not 1 <= len(self.creator_visible_problem) <= 512
                )
            )
            or (
                self.memory_proposal_ref is not None
                and (
                    type(self.memory_proposal_ref) is not str
                    or _REF.fullmatch(self.memory_proposal_ref) is None
                    or self.memory_proposal_ref == self.proposal_ref
                )
            )
            or self.issue_target not in {None, "self", "mind", "prompt"}
        ):
            raise SleepViolation("SLEEP-CANDIDATE-MAINTENANCE")
        memory_phase = self.phase is MaintenancePhase.MEMORY_MAINTENANCE
        memory_changed = self.outcome is MaintenanceWorkOutcome.MEMORY_CHANGED
        if memory_phase != (
            self.outcome
            in {
                MaintenanceWorkOutcome.MEMORY_CHANGED,
                MaintenanceWorkOutcome.MEMORY_UNCHANGED,
            }
        ) or memory_changed != (self.memory_proposal_ref is not None):
            raise SleepViolation("SLEEP-CANDIDATE-MAINTENANCE-SHAPE")
        issue_found = self.outcome is MaintenanceWorkOutcome.ISSUE_FOUND
        if issue_found != (self.creator_visible_problem is not None):
            raise SleepViolation("SLEEP-CANDIDATE-MAINTENANCE-SHAPE")
        if issue_found != (self.issue_target is not None):
            raise SleepViolation("SLEEP-CANDIDATE-MAINTENANCE-SHAPE")
        reflection_phase = self.phase in {
            MaintenancePhase.REFLECT_SELF,
            MaintenancePhase.REFLECT_MIND,
            MaintenancePhase.REFLECT_PROMPT,
        }
        if reflection_phase != (
            self.outcome
            in {
                MaintenanceWorkOutcome.REFLECTION_CHANGED,
                MaintenanceWorkOutcome.REFLECTION_UNCHANGED,
            }
        ):
            raise SleepViolation("SLEEP-CANDIDATE-MAINTENANCE-SHAPE")


@dataclass(frozen=True, slots=True)
class SleepCommitContext:
    validation_id: UUID
    episode_id: UUID
    opportunity_id: UUID
    root_opportunity_id: UUID
    reconsideration_no: int
    subject_id: UUID
    generation_id: UUID
    opportunity_purpose: str
    source_kind: str
    source_ref: UUID
    source_version: int
    base_state_epoch: int
    opportunity_available_after: datetime
    opportunity_expires_at: datetime | None


@dataclass(frozen=True, slots=True)
class MaintenanceProgress:
    session_id: UUID
    phase: MaintenancePhase
    result_status: MaintenanceResultStatus
    head_version: int
    reason_code: str
    opportunity_id: UUID | None = None
    opportunity_admitted: bool = False


@dataclass(frozen=True, slots=True)
class SleepRuntimeSnapshot:
    generation_created_at: datetime
    generation_no: int
    subject_version: int
    state_epoch: int


@runtime_checkable
class SleepRuntimeFactsPort(Protocol):
    async def snapshot(
        self, unit_of_work: PostgreSQLRuntimeUnitOfWork
    ) -> SleepRuntimeSnapshot: ...

    async def safe_for_maintenance(
        self, unit_of_work: PostgreSQLRuntimeUnitOfWork
    ) -> bool: ...


@dataclass(frozen=True, slots=True)
class SleepOpportunityDraft:
    subject_id: UUID
    purpose: str
    source_kind: str
    source_ref: UUID
    source_version: int
    available_after: datetime
    expires_at: datetime | None = None
    predecessor_id: UUID | None = None
    root_id: UUID | None = None
    reconsideration_no: int = 0

    def __post_init__(self) -> None:
        if self.available_after.tzinfo is None:
            raise SleepViolation("SLEEP-OPPORTUNITY-TIME")
        if self.expires_at is not None and (
            self.expires_at.tzinfo is None or self.expires_at <= self.available_after
        ):
            raise SleepViolation("SLEEP-OPPORTUNITY-TIME")


@dataclass(frozen=True, slots=True)
class SleepOpportunityResult:
    opportunity_id: UUID | None
    inserted: bool


@runtime_checkable
class SleepOpportunityPort(Protocol):
    async def admit_sleep(
        self,
        transaction: PostgreSQLTransaction,
        draft: SleepOpportunityDraft,
    ) -> SleepOpportunityResult: ...

    async def cancel_sleep_source(
        self,
        transaction: PostgreSQLTransaction,
        *,
        subject_id: UUID,
        source_kind: str,
        source_ref: UUID,
    ) -> None: ...


@dataclass(frozen=True, slots=True)
class SleepMaintenanceSnapshot:
    session_id: UUID
    current_revision_id: UUID
    head_version: int
    phase: MaintenancePhase
    trigger_kind: MaintenanceTriggerKind

    def __post_init__(self) -> None:
        if (
            not _uuid7(self.session_id)
            or not _uuid7(self.current_revision_id)
            or type(self.head_version) is not int
            or self.head_version <= 0
            or type(self.phase) is not MaintenancePhase
            or type(self.trigger_kind) is not MaintenanceTriggerKind
        ):
            raise SleepViolation("SLEEP-MAINTENANCE-SNAPSHOT")


@runtime_checkable
class SleepCognitionPort(Protocol):
    def bind_sleep(self, value: CandidateSleepDecisionDraft) -> CandidateOwnerDraft: ...

    def bind_maintenance(
        self, value: CandidateMaintenanceDecisionDraft
    ) -> CandidateOwnerDraft: ...

    def decode(
        self, payload: bytes
    ) -> CandidateSleepDecisionDraft | CandidateMaintenanceDecisionDraft: ...

    def bind_wire(self, value: object, *, maintenance: bool) -> CandidateOwnerDraft: ...


@runtime_checkable
class SleepCommitPort(Protocol):
    async def heads_match(
        self,
        transaction: PostgreSQLTransaction,
        *,
        context: SleepCommitContext,
        drafts: tuple[
            CandidateSleepDecisionDraft | CandidateMaintenanceDecisionDraft, ...
        ],
    ) -> bool: ...

    def requests_reconsideration(
        self,
        *,
        context: SleepCommitContext,
        drafts: tuple[
            CandidateSleepDecisionDraft | CandidateMaintenanceDecisionDraft, ...
        ],
    ) -> bool: ...

    async def commit(
        self,
        transaction: PostgreSQLTransaction,
        *,
        context: SleepCommitContext,
        application_id: UUID,
        commit_id: UUID | None,
        resulting_subject_version: int,
        drafts: tuple[
            CandidateSleepDecisionDraft | CandidateMaintenanceDecisionDraft, ...
        ],
        committed_memory_ids: tuple[UUID, ...] = (),
    ) -> None: ...

    async def affected_session_ids(
        self, transaction: PostgreSQLTransaction, validation_id: UUID
    ) -> tuple[UUID, ...]: ...


@runtime_checkable
class SleepMaintenancePort(Protocol):
    async def maintain_window(
        self,
        unit_of_work: PostgreSQLRuntimeUnitOfWork,
        *,
        consideration_after_seconds: int,
        deadline_after_seconds: int,
    ) -> MaintenanceOpportunityOutcome: ...

    async def maintain_active_session(
        self,
        unit_of_work: PostgreSQLRuntimeUnitOfWork,
        *,
        quiet_seconds: int,
    ) -> MaintenanceProgress | None: ...

    async def request_emergency_wake(
        self,
        unit_of_work: PostgreSQLRuntimeUnitOfWork,
        *,
        session_id: UUID,
        request_id: UUID,
    ) -> UUID: ...

    async def active_session_id(
        self, unit_of_work: PostgreSQLRuntimeUnitOfWork
    ) -> UUID | None: ...


class CreatorMaintenanceViolation(RuntimeError):
    __slots__ = ("code",)

    def __init__(self, code: str) -> None:
        if type(code) is not str or not code.startswith("MAINTENANCE-QUERY-"):
            raise ValueError("maintenance query violation code is invalid")
        self.code = code
        super().__init__("Creator maintenance query failed")

    def __str__(self) -> str:
        return f"{self.code}: Creator maintenance query failed"


def _uuid7(value: object) -> bool:
    return type(value) is UUID and value.version == 7


def _instant(value: object) -> bool:
    return type(value) is datetime and value.tzinfo is not None


@dataclass(frozen=True, slots=True)
class CreatorMaintenanceSession:
    session_id: UUID
    trigger_kind: MaintenanceTriggerKind
    phase: MaintenancePhase
    result_status: MaintenanceResultStatus
    revision_no: int
    head_version: int
    wake_requested: bool
    started_at: datetime
    updated_at: datetime
    finished_at: datetime | None

    def __post_init__(self) -> None:
        running = self.result_status is MaintenanceResultStatus.RUNNING
        if (
            not _uuid7(self.session_id)
            or type(self.trigger_kind) is not MaintenanceTriggerKind
            or type(self.phase) is not MaintenancePhase
            or type(self.result_status) is not MaintenanceResultStatus
            or type(self.revision_no) is not int
            or self.revision_no < 1
            or type(self.head_version) is not int
            or self.head_version < 1
            or self.revision_no != self.head_version
            or type(self.wake_requested) is not bool
            or not _instant(self.started_at)
            or not _instant(self.updated_at)
            or (self.finished_at is not None and not _instant(self.finished_at))
            or running == (self.finished_at is not None)
        ):
            raise CreatorMaintenanceViolation("MAINTENANCE-QUERY-SESSION")


@dataclass(frozen=True, slots=True)
class CreatorMaintenanceStatus:
    session: CreatorMaintenanceSession | None
    waiting_input_count: int

    def __post_init__(self) -> None:
        if (
            self.session is not None
            and type(self.session) is not CreatorMaintenanceSession
        ) or (
            type(self.waiting_input_count) is not int
            or self.waiting_input_count < 0
            or (self.session is None and self.waiting_input_count != 0)
            or (
                self.session is not None
                and self.session.result_status is not MaintenanceResultStatus.RUNNING
                and self.waiting_input_count != 0
            )
        ):
            raise CreatorMaintenanceViolation("MAINTENANCE-QUERY-STATUS")


@dataclass(frozen=True, slots=True)
class CreatorMaintenanceTimelineItem:
    revision_id: UUID
    revision_no: int
    phase: MaintenancePhase
    result_status: MaintenanceResultStatus
    transition_kind: MaintenanceTransitionKind
    occurred_at: datetime
    work_outcome: MaintenanceWorkOutcome | None = None
    problem_summary: str | None = None

    def __post_init__(self) -> None:
        if (
            not _uuid7(self.revision_id)
            or type(self.revision_no) is not int
            or self.revision_no < 1
            or type(self.phase) is not MaintenancePhase
            or type(self.result_status) is not MaintenanceResultStatus
            or self.transition_kind
            not in {"started", "advanced", "completed", "interrupted", "system_failed"}
            or not _instant(self.occurred_at)
            or (
                self.work_outcome is not None
                and type(self.work_outcome) is not MaintenanceWorkOutcome
            )
            or (
                self.problem_summary is not None
                and (
                    type(self.problem_summary) is not str
                    or not 1 <= len(self.problem_summary) <= 512
                )
            )
            or (
                self.phase is MaintenancePhase.MEMORY_MAINTENANCE
                and self.work_outcome is not None
                and self.work_outcome
                not in {
                    MaintenanceWorkOutcome.MEMORY_CHANGED,
                    MaintenanceWorkOutcome.MEMORY_UNCHANGED,
                }
            )
            or (
                self.phase is MaintenancePhase.SELF_CHECK
                and self.work_outcome is not None
                and self.work_outcome
                not in {
                    MaintenanceWorkOutcome.ISSUE_FOUND,
                    MaintenanceWorkOutcome.NO_ISSUE,
                }
            )
            or (
                self.phase
                in {
                    MaintenancePhase.REFLECT_SELF,
                    MaintenancePhase.REFLECT_MIND,
                    MaintenancePhase.REFLECT_PROMPT,
                }
                and self.work_outcome is not None
                and self.work_outcome
                not in {
                    MaintenanceWorkOutcome.REFLECTION_CHANGED,
                    MaintenanceWorkOutcome.REFLECTION_UNCHANGED,
                }
            )
            or (
                self.phase
                not in {
                    MaintenancePhase.MEMORY_MAINTENANCE,
                    MaintenancePhase.SELF_CHECK,
                    MaintenancePhase.REFLECT_SELF,
                    MaintenancePhase.REFLECT_MIND,
                    MaintenancePhase.REFLECT_PROMPT,
                }
                and self.work_outcome is not None
            )
            or (
                (self.work_outcome is MaintenanceWorkOutcome.ISSUE_FOUND)
                != (self.problem_summary is not None)
            )
        ):
            raise CreatorMaintenanceViolation("MAINTENANCE-QUERY-TIMELINE")


@dataclass(frozen=True, slots=True)
class CreatorMaintenanceTimeline:
    session_id: UUID
    items: tuple[CreatorMaintenanceTimelineItem, ...]
    truncated: bool

    def __post_init__(self) -> None:
        if (
            not _uuid7(self.session_id)
            or type(self.items) is not tuple
            or len(self.items) > 100
            or any(
                type(item) is not CreatorMaintenanceTimelineItem for item in self.items
            )
            or type(self.truncated) is not bool
        ):
            raise CreatorMaintenanceViolation("MAINTENANCE-QUERY-PAGE")


@runtime_checkable
class CreatorMaintenanceQueryPort(Protocol):
    async def status(self) -> CreatorMaintenanceStatus: ...

    async def timeline(self, session_id: UUID) -> CreatorMaintenanceTimeline: ...


@runtime_checkable
class CreatorEmergencyWakePort(Protocol):
    async def request_emergency_wake(
        self,
        session_id: UUID,
        request_id: UUID,
    ) -> UUID: ...


@runtime_checkable
class SleepReadPort(CreatorMaintenanceQueryPort, Protocol):
    async def active_maintenance(
        self,
        transaction: PostgreSQLTransaction,
        *,
        subject_id: UUID,
    ) -> SleepMaintenanceSnapshot | None: ...

    async def candidate_maintenance(
        self,
        transaction: PostgreSQLTransaction,
        *,
        source_revision_id: UUID | None,
        expected_head_version: int | None,
    ) -> SleepMaintenanceSnapshot | None: ...


__all__ = (
    "MAINTENANCE_PROJECTION_VERSION",
    "CandidateMaintenanceDecisionDraft",
    "CandidateSleepDecisionDraft",
    "CreatorEmergencyWakePort",
    "CreatorMaintenanceQueryPort",
    "CreatorMaintenanceSession",
    "CreatorMaintenanceStatus",
    "CreatorMaintenanceTimeline",
    "CreatorMaintenanceTimelineItem",
    "CreatorMaintenanceViolation",
    "MaintenanceCheckpointPlan",
    "MaintenanceOpportunityOutcome",
    "MaintenanceOpportunityStatus",
    "MaintenancePhase",
    "MaintenancePhaseState",
    "MaintenanceProgress",
    "MaintenanceResultStatus",
    "MaintenanceTransitionKind",
    "MaintenanceTriggerKind",
    "MaintenanceViolation",
    "MaintenanceWorkOutcome",
    "SleepCognitionPort",
    "SleepCommitContext",
    "SleepCommitPort",
    "SleepDecisionKind",
    "SleepMaintenancePort",
    "SleepMaintenanceSnapshot",
    "SleepOpportunityDraft",
    "SleepOpportunityPort",
    "SleepOpportunityResult",
    "SleepReadPort",
    "SleepRuntimeFactsPort",
    "SleepRuntimeSnapshot",
    "SleepViolation",
    "plan_maintenance_checkpoint",
    "validate_maintenance_advance",
)
