from dataclasses import replace

import pytest
from armi_attention._activation import Activation
from armi_attention.api import AutonomyPolicy


def state(**values):
    return Activation(
        cycle=0, threshold=1, anchor_seconds=0, weight=50, idling=True, **values
    )


def test_polling_and_fast_forward_have_the_same_crossing():
    policy = AutonomyPolicy()
    current = state()
    due = current.remaining(0, policy)
    assert 1300 < due < 1320
    for step in (1, 5, 60):
        for tick in range(0, int(due), step):
            assert current.project(tick, policy)[0] < current.threshold
            assert tick + current.remaining(tick, policy) == pytest.approx(due)
    assert current.project(due, policy)[0] == pytest.approx(1)
    assert current.remaining(due + 1, policy) == 0


def test_higher_weight_never_delays_the_same_opportunity():
    deadlines = [
        state()
        .changed(
            active=0,
            idling=True,
            need=0,
            policy=AutonomyPolicy(activation_weight=weight),
        )
        .remaining(0, AutonomyPolicy(activation_weight=weight))
        for weight in (0, 20, 50, 80, 100)
    ]
    assert deadlines == sorted(deadlines, reverse=True)


def test_pause_and_restart_preserve_threshold_and_accumulation():
    policy = AutonomyPolicy()
    original = state()
    paused = original.changed(active=300, idling=False, need=0, policy=policy)
    restored = Activation.model_validate_json(paused.model_dump_json())
    assert restored.project(10000, policy)[0] == original.project(300, policy)[0]
    resumed = restored.changed(active=10000, idling=True, need=0, policy=policy)
    assert resumed.threshold == original.threshold
    assert resumed.project(10000, policy)[1] == 0
    assert resumed.remaining(10000, policy) >= 60


def test_need_and_weight_changes_integrate_old_segment_once():
    original, policy = state(), AutonomyPolicy()
    amount = original.project(100, policy)[0]
    updated_policy = replace(policy, activation_weight=80)
    changed = original.changed(active=100, idling=True, need=0.9, policy=updated_policy)
    assert changed.project(100, updated_policy)[0] == amount
    assert (
        changed.changed(active=200, idling=True, need=0.9, policy=updated_policy)
        is changed
    )


def test_quiet_period_and_maximum_idle_are_enforced():
    policy = AutonomyPolicy()
    tiny = state().model_copy(update={"threshold": 1e-9})
    assert tiny.remaining(0, policy) == pytest.approx(60)
    enormous = state().model_copy(update={"threshold": 1000})
    assert enormous.remaining(0, policy) == pytest.approx(7200)
    assert enormous.remaining(7200, policy) == 0


def test_parameter_change_cannot_reprice_previous_idle_time():
    original, policy = state(), AutonomyPolicy()
    amount = original.project(300, policy)[0]
    faster = replace(policy, activation_base_rate=2, idle_maturation_seconds=600)
    changed = original.changed(active=300, idling=True, need=0, policy=faster)
    assert changed.project(300, faster)[0] == amount
    assert changed.threshold == original.threshold
    assert changed.project(600, faster)[0] > original.project(600, policy)[0]


def test_technical_delay_survives_polling_and_restart():
    policy = AutonomyPolicy()
    delayed = state().model_copy(update={"threshold": 1e-9, "retry_after": 300})
    restored = Activation.model_validate_json(delayed.model_dump_json())
    assert restored.remaining(120, policy) == 180
    assert restored.remaining(300, policy) == 0
