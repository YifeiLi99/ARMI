"""Creator-visible maintenance status and emergency-wake contracts."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Final, Literal, Protocol, runtime_checkable
from uuid import UUID

from .maintenance import (
    MaintenancePhase,
    MaintenanceResultStatus,
    MaintenanceTriggerKind,
    MaintenanceWorkOutcome,
)

MAINTENANCE_PROJECTION_VERSION: Final = "creator-maintenance.v2"
type MaintenanceTransitionKind = Literal[
    "started",
    "advanced",
    "completed",
    "interrupted",
    "system_failed",
]


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
                not in {
                    MaintenancePhase.MEMORY_MAINTENANCE,
                    MaintenancePhase.SELF_CHECK,
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


__all__ = (
    "MAINTENANCE_PROJECTION_VERSION",
    "CreatorEmergencyWakePort",
    "CreatorMaintenanceQueryPort",
    "CreatorMaintenanceSession",
    "CreatorMaintenanceStatus",
    "CreatorMaintenanceTimeline",
    "CreatorMaintenanceTimelineItem",
    "CreatorMaintenanceViolation",
    "MaintenanceTransitionKind",
)
