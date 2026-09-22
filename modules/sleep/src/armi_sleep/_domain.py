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
    REFLECT_SELF = "reflect_self"
    REFLECT_MIND = "reflect_mind"
    REFLECT_PROMPT = "reflect_prompt"
    LIFE_QUIET = "life_quiet"
    RESUME_CHECK = "resume_check"
    COMPLETED = "completed"


class MaintenanceResultStatus(StrEnum):
    RUNNING = "running"
    COMPLETED = "completed"
    INTERRUPTED = "interrupted"
    FAILED = "failed"


class MaintenanceWorkOutcome(StrEnum):
    MEMORY_CHANGED = "memory_changed"
    MEMORY_UNCHANGED = "memory_unchanged"
    ISSUE_FOUND = "issue_found"
    NO_ISSUE = "no_issue"
    REFLECTION_CHANGED = "reflection_changed"
    REFLECTION_UNCHANGED = "reflection_unchanged"


@dataclass(frozen=True, slots=True)
class MaintenanceCheckpointPlan:
    following: MaintenancePhaseState
    transition_kind: str
    terminal: bool


_NEXT_PHASE = {
    MaintenancePhase.PREPARING: MaintenancePhase.MEMORY_MAINTENANCE,
    MaintenancePhase.MEMORY_MAINTENANCE: MaintenancePhase.SELF_CHECK,
    MaintenancePhase.SELF_CHECK: MaintenancePhase.REFLECT_SELF,
    MaintenancePhase.REFLECT_SELF: MaintenancePhase.REFLECT_MIND,
    MaintenancePhase.REFLECT_MIND: MaintenancePhase.REFLECT_PROMPT,
    MaintenancePhase.REFLECT_PROMPT: MaintenancePhase.LIFE_QUIET,
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


def plan_maintenance_checkpoint(
    current: MaintenancePhaseState,
    *,
    wake_requested: bool,
    quiet_elapsed: bool,
) -> MaintenanceCheckpointPlan | None:
    """Choose the next durable checkpoint without performing side effects."""

    if current.result_status is not MaintenanceResultStatus.RUNNING:
        raise MaintenanceViolation("terminal maintenance session cannot advance")
    if wake_requested:
        following = MaintenancePhaseState(
            current.phase,
            MaintenanceResultStatus.INTERRUPTED,
        )
        validate_maintenance_advance(current, following)
        return MaintenanceCheckpointPlan(following, "interrupted", True)
    if current.phase is MaintenancePhase.LIFE_QUIET and not quiet_elapsed:
        return None
    following_phase = _NEXT_PHASE.get(current.phase)
    if following_phase is None:
        raise MaintenanceViolation("completed maintenance session cannot advance")
    following_result = (
        MaintenanceResultStatus.COMPLETED
        if following_phase is MaintenancePhase.COMPLETED
        else MaintenanceResultStatus.RUNNING
    )
    following = MaintenancePhaseState(following_phase, following_result)
    validate_maintenance_advance(current, following)
    return MaintenanceCheckpointPlan(
        following,
        "completed"
        if following_result is MaintenanceResultStatus.COMPLETED
        else "advanced",
        following_result is MaintenanceResultStatus.COMPLETED,
    )


__all__ = (
    "MaintenanceCheckpointPlan",
    "MaintenancePhase",
    "MaintenancePhaseState",
    "MaintenanceResultStatus",
    "MaintenanceTriggerKind",
    "MaintenanceViolation",
    "MaintenanceWorkOutcome",
    "SleepDecisionKind",
    "plan_maintenance_checkpoint",
    "validate_maintenance_advance",
)
