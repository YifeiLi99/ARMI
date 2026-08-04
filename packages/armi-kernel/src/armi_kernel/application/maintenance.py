"""Sleep decisions and maintenance-session phase authority."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class MaintenanceViolation(ValueError):
    pass


class SleepDecisionKind(StrEnum):
    SLEEP = "sleep"
    STAY_AWAKE = "stay_awake"
    DEFER = "defer"
    NEED_INFORMATION = "need_information"


class MaintenanceTriggerKind(StrEnum):
    SUBJECT_CHOICE = "subject_choice"
    SYSTEM_DEADLINE = "system_deadline"


class MaintenancePhase(StrEnum):
    PREPARING = "preparing"
    MEMORY_MAINTENANCE = "memory_maintenance"
    SELF_CHECK = "self_check"
    LIFE_QUIET = "life_quiet"
    RESUME_CHECK = "resume_check"
    COMPLETED = "completed"


class MaintenanceResultStatus(StrEnum):
    RUNNING = "running"
    COMPLETED = "completed"
    INTERRUPTED = "interrupted"
    FAILED = "failed"


_NEXT_PHASE = {
    MaintenancePhase.PREPARING: MaintenancePhase.MEMORY_MAINTENANCE,
    MaintenancePhase.MEMORY_MAINTENANCE: MaintenancePhase.SELF_CHECK,
    MaintenancePhase.SELF_CHECK: MaintenancePhase.LIFE_QUIET,
    MaintenancePhase.LIFE_QUIET: MaintenancePhase.RESUME_CHECK,
    MaintenancePhase.RESUME_CHECK: MaintenancePhase.COMPLETED,
}


@dataclass(frozen=True, slots=True)
class MaintenancePhaseState:
    phase: MaintenancePhase
    result_status: MaintenanceResultStatus

    def __post_init__(self) -> None:
        if self.phase is MaintenancePhase.COMPLETED:
            if self.result_status is not MaintenanceResultStatus.COMPLETED:
                raise MaintenanceViolation("completed phase requires completed result")
        elif self.result_status is MaintenanceResultStatus.COMPLETED:
            raise MaintenanceViolation("completed result requires completed phase")


def validate_maintenance_advance(
    current: MaintenancePhaseState,
    following: MaintenancePhaseState,
) -> None:
    if current.result_status is not MaintenanceResultStatus.RUNNING:
        raise MaintenanceViolation("terminal maintenance session cannot advance")
    if following.result_status in {
        MaintenanceResultStatus.INTERRUPTED,
        MaintenanceResultStatus.FAILED,
    }:
        if following.phase is not current.phase:
            raise MaintenanceViolation("terminal result must remain in current phase")
        return
    if _NEXT_PHASE.get(current.phase) is not following.phase:
        raise MaintenanceViolation("maintenance phases must advance in order")


__all__ = (
    "MaintenancePhase",
    "MaintenancePhaseState",
    "MaintenanceResultStatus",
    "MaintenanceTriggerKind",
    "MaintenanceViolation",
    "SleepDecisionKind",
    "validate_maintenance_advance",
)
