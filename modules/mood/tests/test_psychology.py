from datetime import UTC, datetime, timedelta

import pytest
from armi_mood._psychology import (
    Appraisal,
    DynamicsParameters,
    EmotionKind,
    GoalAppraisal,
    advance,
    apply_appraisal,
    current_affect,
    derive_response,
    initial_dynamics,
)


def appraisal(**changes):
    values: dict[str, object] = {
        name: None
        for name, field in Appraisal.model_fields.items()
        if field.is_required()
    }
    values.update(
        agency="unknown",
        intent="unknown",
        phase="unknown",
        epistemic="confirmed",
        self_scope="none",
        outcome_change="unchanged",
        not_applicable=(),
    )
    return Appraisal.model_validate(values | changes)


def test_backup_is_not_recovery_and_real_recovery_preserves_slow_state():
    now = datetime(2026, 1, 1, tzinfo=UTC)
    loss = appraisal(
        relevance=1,
        loss=1,
        gain=0,
        phase="realized",
        likelihood=1,
        control=0,
        adjustment=0,
    )
    state = apply_appraisal(
        initial_dynamics(now, DynamicsParameters()),
        event_id="loss",
        situation_id="file",
        appraisal=loss,
        at=now,
    )
    backup = loss.model_copy(update={"control": 1.0, "resources": 1.0})
    state = apply_appraisal(
        state,
        event_id="backup",
        situation_id="file",
        appraisal=backup,
        at=now + timedelta(minutes=2),
    )
    assert EmotionKind.RELIEF not in {
        e.kind for e in state.episodes[0].response.emotions
    }
    assert state.slow_valence < 0
    recovered = appraisal(
        relevance=1,
        gain=1,
        loss=0,
        phase="averted",
        likelihood=0,
        outcome_change="threat_averted",
    )
    state = apply_appraisal(
        state,
        event_id="restore",
        situation_id="file",
        appraisal=recovered,
        at=now + timedelta(minutes=3),
    )
    assert EmotionKind.RELIEF in {e.kind for e in state.episodes[0].response.emotions}
    assert state.slow_valence < 0
    assert len(state.episodes) == 1


def test_queries_and_incremental_time_steps_do_not_change_dynamics():
    now = datetime(2026, 1, 1, tzinfo=UTC)
    state = apply_appraisal(
        initial_dynamics(now, DynamicsParameters()),
        event_id="a",
        situation_id="a",
        appraisal=appraisal(relevance=1, gain=1, phase="realized"),
        at=now,
    )
    direct = advance(state, now + timedelta(hours=2))
    stepped = state
    for minute in range(1, 121):
        stepped = advance(stepped, now + timedelta(minutes=minute))
    assert stepped.slow_valence == pytest.approx(direct.slow_valence, abs=1e-12)
    assert current_affect(state, direct.as_of).valence == pytest.approx(
        current_affect(stepped, direct.as_of).valence
    )
    assert state.as_of == now


def test_unknown_coping_does_not_create_helplessness():
    response = derive_response(appraisal(relevance=1, loss=1, phase="realized"))
    assert response.affect.valence < 0
    assert response.affect.arousal == 0
    assert "control" in response.unknown


def test_mixed_emotions_are_not_cancelled_by_neutral_valence():
    response = derive_response(appraisal(relevance=1, loss=1, gain=1, phase="realized"))
    assert response.affect.valence == 0
    assert {e.kind for e in response.emotions} == {EmotionKind.JOY, EmotionKind.SADNESS}


def test_repeated_delivery_and_unchanged_reappraisal_do_not_recharge():
    now = datetime(2026, 1, 1, tzinfo=UTC)
    value = appraisal(relevance=1, loss=1, phase="realized")
    state = apply_appraisal(
        initial_dynamics(now, DynamicsParameters()),
        event_id="a",
        situation_id="file",
        appraisal=value,
        at=now,
    )
    assert (
        apply_appraisal(
            state,
            event_id="a",
            situation_id="file",
            appraisal=value,
            at=now + timedelta(minutes=2),
        )
        == state
    )
    repeated = apply_appraisal(
        state,
        event_id="b",
        situation_id="file",
        appraisal=value,
        at=now + timedelta(minutes=2),
    )
    assert current_affect(repeated, repeated.as_of) == current_affect(
        state, repeated.as_of
    )


def test_reported_loss_does_not_become_confirmed_sadness():
    response = derive_response(
        appraisal(
            relevance=1, loss=1, likelihood=0.5, phase="realized", epistemic="reported"
        )
    )
    assert {e.kind for e in response.emotions} == {EmotionKind.FEAR}


def test_accidental_other_agency_is_not_malicious_anger():
    response = derive_response(
        appraisal(
            relevance=1,
            loss=1,
            phase="realized",
            agency="other",
            intent="accidental",
            social_violation=1,
        )
    )
    assert EmotionKind.ANGER not in {e.kind for e in response.emotions}


def test_distinct_goals_do_not_borrow_each_others_outcome_phase():
    value = appraisal(
        goals=(
            GoalAppraisal(
                reference="lost-work",
                relevance=1,
                gain=0,
                loss=1,
                likelihood=1,
                phase="realized",
            ),
            GoalAppraisal(
                reference="next-job",
                relevance=1,
                gain=1,
                loss=0,
                likelihood=0.5,
                phase="anticipated",
            ),
        )
    )
    response = derive_response(value)
    assert {emotion.kind for emotion in response.emotions} == {
        EmotionKind.SADNESS,
        EmotionKind.HOPE,
    }
    assert any("goal:lost-work" in emotion.basis for emotion in response.emotions)


@pytest.mark.parametrize("fast,slow", [(300, 3600), (300, 300), (3600, 300)])
def test_long_intervals_and_equal_or_reversed_half_lives_remain_finite(fast, slow):
    now = datetime(2026, 1, 1, tzinfo=UTC)
    state = initial_dynamics(
        now,
        DynamicsParameters(fast_half_life_seconds=fast, slow_half_life_seconds=slow),
    )
    state = apply_appraisal(
        state,
        event_id="one",
        situation_id="one",
        at=now,
        appraisal=appraisal(relevance=1, gain=1, phase="realized"),
    )
    result = current_affect(state, now + timedelta(days=100))
    assert result.valence == pytest.approx(0, abs=1e-12)
    assert result.arousal == 0
