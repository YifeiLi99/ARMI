"""P0-S004 compact sleep and maintenance phase contracts."""

from __future__ import annotations

import pytest
from armi_kernel.application import (
    MaintenancePhase,
    MaintenancePhaseState,
    MaintenanceResultStatus,
    MaintenanceViolation,
    plan_maintenance_checkpoint,
    validate_maintenance_advance,
)
from armi_runtime.composition.sleep_decision_candidate_contract import (
    parse_sleep_decision_candidate,
)
from pydantic import ValidationError


@pytest.mark.parametrize("kind", ["sleep", "stay_awake", "defer", "need_information"])
def test_sleep_candidate_accepts_only_the_four_compact_decisions(kind: str) -> None:
    assert parse_sleep_decision_candidate({"kind": kind}).kind == kind


@pytest.mark.parametrize(
    "extra",
    [
        {"subject_id": "01980f7d-7b8f-7e2a-8a11-2ab8e1234567"},
        {"deadline_at": "tomorrow"},
        {"phase": "preparing"},
        {"permission": "allow"},
    ],
)
def test_sleep_candidate_rejects_authority_fields(extra: dict[str, str]) -> None:
    with pytest.raises(ValidationError):
        parse_sleep_decision_candidate({"kind": "sleep", **extra})


def test_maintenance_phase_contract_is_ordered_and_terminal() -> None:
    preparing = MaintenancePhaseState(
        MaintenancePhase.PREPARING, MaintenanceResultStatus.RUNNING
    )
    memory = MaintenancePhaseState(
        MaintenancePhase.MEMORY_MAINTENANCE, MaintenanceResultStatus.RUNNING
    )
    validate_maintenance_advance(preparing, memory)
    with pytest.raises(MaintenanceViolation):
        validate_maintenance_advance(
            preparing,
            MaintenancePhaseState(
                MaintenancePhase.LIFE_QUIET, MaintenanceResultStatus.RUNNING
            ),
        )
    interrupted = MaintenancePhaseState(
        MaintenancePhase.PREPARING, MaintenanceResultStatus.INTERRUPTED
    )
    with pytest.raises(MaintenanceViolation):
        validate_maintenance_advance(interrupted, memory)


def test_completed_result_and_phase_are_coupled() -> None:
    with pytest.raises(MaintenanceViolation):
        MaintenancePhaseState(
            MaintenancePhase.COMPLETED, MaintenanceResultStatus.RUNNING
        )
    with pytest.raises(MaintenanceViolation):
        MaintenancePhaseState(
            MaintenancePhase.RESUME_CHECK, MaintenanceResultStatus.COMPLETED
        )


def test_checkpoint_plan_advances_waits_completes_and_interrupts() -> None:
    preparing = MaintenancePhaseState(
        MaintenancePhase.PREPARING, MaintenanceResultStatus.RUNNING
    )
    advanced = plan_maintenance_checkpoint(
        preparing,
        wake_requested=False,
        quiet_elapsed=False,
    )
    assert advanced is not None
    assert advanced.following.phase is MaintenancePhase.MEMORY_MAINTENANCE
    assert advanced.transition_kind == "advanced"
    assert not advanced.terminal

    quiet = MaintenancePhaseState(
        MaintenancePhase.LIFE_QUIET, MaintenanceResultStatus.RUNNING
    )
    assert (
        plan_maintenance_checkpoint(
            quiet,
            wake_requested=False,
            quiet_elapsed=False,
        )
        is None
    )
    resumed = plan_maintenance_checkpoint(
        quiet,
        wake_requested=False,
        quiet_elapsed=True,
    )
    assert resumed is not None
    assert resumed.following.phase is MaintenancePhase.RESUME_CHECK

    completed = plan_maintenance_checkpoint(
        MaintenancePhaseState(
            MaintenancePhase.RESUME_CHECK,
            MaintenanceResultStatus.RUNNING,
        ),
        wake_requested=False,
        quiet_elapsed=True,
    )
    assert completed is not None
    assert completed.following == MaintenancePhaseState(
        MaintenancePhase.COMPLETED,
        MaintenanceResultStatus.COMPLETED,
    )
    assert completed.terminal

    interrupted = plan_maintenance_checkpoint(
        preparing,
        wake_requested=True,
        quiet_elapsed=False,
    )
    assert interrupted is not None
    assert interrupted.following.result_status is MaintenanceResultStatus.INTERRUPTED
    assert interrupted.following.phase is MaintenancePhase.PREPARING
    assert interrupted.terminal
