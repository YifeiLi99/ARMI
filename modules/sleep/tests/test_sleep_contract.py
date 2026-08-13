import json
from uuid import uuid7

import pytest
import rfc8785
from armi_kernel.application import CandidateFactClass
from armi_sleep.api import (
    CandidateMaintenanceDecisionDraft,
    CandidateSleepDecisionDraft,
    MaintenancePhase,
    MaintenancePhaseState,
    MaintenanceResultStatus,
    MaintenanceViolation,
    MaintenanceWorkOutcome,
    SleepDecisionKind,
    SleepViolation,
    plan_maintenance_checkpoint,
    validate_maintenance_advance,
)
from armi_sleep.bootstrap import bootstrap_sleep_cognition


def test_sleep_decision_round_trip_uses_canonical_owner_payload() -> None:
    cognition = bootstrap_sleep_cognition()
    decision = CandidateSleepDecisionDraft(
        "proposal:1",
        "group:1",
        (1,),
        SleepDecisionKind.SLEEP,
        uuid7(),
    )

    draft = cognition.bind_sleep(decision)

    assert draft.owner == "sleep"
    assert draft.fact_class is CandidateFactClass.SUBJECTIVE_UNDERSTANDING
    assert cognition.decode(draft.canonical_payload) == decision
    assert rfc8785.dumps(json.loads(draft.canonical_payload)) == (
        draft.canonical_payload
    )


def test_maintenance_result_round_trip_preserves_exact_head_and_memory_ref() -> None:
    cognition = bootstrap_sleep_cognition()
    decision = CandidateMaintenanceDecisionDraft(
        "proposal:2",
        "group:1",
        (1, 2),
        uuid7(),
        uuid7(),
        4,
        MaintenancePhase.MEMORY_MAINTENANCE,
        MaintenanceWorkOutcome.MEMORY_CHANGED,
        "完成一次记忆维护。",
        None,
        "proposal:1",
    )

    draft = cognition.bind_maintenance(decision)

    assert cognition.decode(draft.canonical_payload) == decision
    assert cognition.bind_wire(decision, maintenance=True) == draft


def test_maintenance_result_rejects_cross_phase_or_missing_memory_reference() -> None:
    with pytest.raises(SleepViolation):
        CandidateMaintenanceDecisionDraft(
            "proposal:1",
            "group:1",
            (1,),
            uuid7(),
            uuid7(),
            1,
            MaintenancePhase.SELF_CHECK,
            MaintenanceWorkOutcome.MEMORY_CHANGED,
            "非法的跨阶段结果。",
        )

    with pytest.raises(SleepViolation):
        CandidateMaintenanceDecisionDraft(
            "proposal:2",
            "group:1",
            (1,),
            uuid7(),
            uuid7(),
            1,
            MaintenancePhase.MEMORY_MAINTENANCE,
            MaintenanceWorkOutcome.MEMORY_CHANGED,
            "缺少记忆提案引用。",
        )


def test_maintenance_lifecycle_is_ordered_interruptible_and_terminal() -> None:
    preparing = MaintenancePhaseState(
        MaintenancePhase.PREPARING,
        MaintenanceResultStatus.RUNNING,
    )
    memory = MaintenancePhaseState(
        MaintenancePhase.MEMORY_MAINTENANCE,
        MaintenanceResultStatus.RUNNING,
    )
    validate_maintenance_advance(preparing, memory)

    with pytest.raises(MaintenanceViolation):
        validate_maintenance_advance(
            preparing,
            MaintenancePhaseState(
                MaintenancePhase.SELF_CHECK,
                MaintenanceResultStatus.RUNNING,
            ),
        )

    interrupted = plan_maintenance_checkpoint(
        preparing,
        wake_requested=True,
        quiet_elapsed=False,
    )
    assert interrupted is not None
    assert interrupted.terminal
    assert interrupted.following.result_status is MaintenanceResultStatus.INTERRUPTED


def test_historical_sleep_shape_is_normalized_to_current_owner_payload() -> None:
    cognition = bootstrap_sleep_cognition()
    cycle_anchor_ref = uuid7()
    owner = cognition.bind_wire(
        {
            "proposal_ref": "proposal:1",
            "atomic_group_ref": "group:1",
            "basis_ordinals": [1],
            "decision_kind": "defer",
            "cycle_anchor_ref": str(cycle_anchor_ref),
        },
        maintenance=False,
    )

    decoded = cognition.decode(owner.canonical_payload)
    assert isinstance(decoded, CandidateSleepDecisionDraft)
    assert decoded.decision_kind is SleepDecisionKind.DEFER
    assert decoded.cycle_anchor_ref == cycle_anchor_ref
