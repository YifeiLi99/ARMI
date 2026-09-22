"""Independent Mood policy and public projection behavior."""

import json
from datetime import UTC, datetime, timedelta
from uuid import uuid7

import pytest
from armi_mood.api import (
    Appraisal,
    DynamicsParameters,
    EmotionKind,
    MoodDynamics,
    MoodView,
    active_mood_episodes,
    apply_appraisal,
    current_affect,
    derive_response,
    initial_dynamics,
    mood_context_items,
    mood_snapshot_bytes,
)
from pydantic import ValidationError


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
    )
    return Appraisal.model_validate(values | changes)


@pytest.mark.parametrize(
    "intent,anger", [("unknown", False), ("accidental", False), ("deliberate", True)]
)
def test_anger_requires_evidence_of_intended_consequences(intent, anger):
    result = derive_response(
        appraisal(
            relevance=1,
            loss=1,
            phase="realized",
            agency="other",
            intent=intent,
            social_violation=1,
        )
    )
    assert (EmotionKind.ANGER in {item.kind for item in result.emotions}) is anger


@pytest.mark.parametrize(
    "scope,expected",
    [("action", EmotionKind.GUILT), ("global", EmotionKind.SHAME), ("unknown", None)],
)
def test_guilt_and_shame_need_distinct_self_evaluation(scope, expected):
    result = derive_response(
        appraisal(
            relevance=1,
            phase="realized",
            agency="self",
            self_scope=scope,
            self_violation=1,
        )
    )
    assert {item.kind for item in result.emotions} == (
        set() if expected is None else {expected}
    )


def test_unknown_appraisal_does_not_invent_emotion():
    result = derive_response(appraisal())
    assert result.affect.valence == result.affect.arousal == 0
    assert result.emotions == ()
    assert "gain" in result.unknown


def test_realized_gain_and_anticipated_gain_have_distinct_emotions():
    value = appraisal(relevance=1, gain=1, likelihood=0.5, phase="anticipated")
    assert {item.kind for item in derive_response(value).emotions} == {EmotionKind.HOPE}
    assert {
        item.kind
        for item in derive_response(
            value.model_copy(update={"phase": "realized"})
        ).emotions
    } == {EmotionKind.JOY}


def test_disappointment_requires_a_previous_expected_benefit():
    outcome = appraisal(
        relevance=1, gain=0, loss=0, phase="realized", outcome_change="benefit_lost"
    )
    assert derive_response(outcome).emotions == ()
    expectation = appraisal(relevance=1, gain=1, likelihood=0.75, phase="anticipated")
    assert {item.kind for item in derive_response(outcome, expectation).emotions} == {
        EmotionKind.DISAPPOINTMENT
    }


def test_second_independent_event_can_increase_affect():
    now = datetime(2026, 9, 22, tzinfo=UTC)
    state = initial_dynamics(now, DynamicsParameters())
    value = appraisal(relevance=1, gain=0.25, phase="realized")
    first = apply_appraisal(
        state, event_id="one", situation_id="one", appraisal=value, at=now
    )
    second = apply_appraisal(
        first, event_id="two", situation_id="two", appraisal=value, at=now
    )
    assert current_affect(second, now).valence > current_affect(first, now).valence > 0


def test_state_round_trip_and_invalid_clock_rejection():
    now = datetime(2026, 9, 22, tzinfo=UTC)
    state = initial_dynamics(now, DynamicsParameters())
    assert MoodDynamics.model_validate_json(state.model_dump_json()) == state
    with pytest.raises(ValidationError):
        MoodDynamics.model_validate(state.model_dump() | {"dominance": 0})
    with pytest.raises(ValueError, match="backwards"):
        current_affect(state, now - timedelta(seconds=1))


def test_private_event_content_is_separate_from_overall_affect():
    now = datetime(2026, 9, 22, tzinfo=UTC)
    event_id, situation_id = uuid7(), uuid7()
    state = apply_appraisal(
        initial_dynamics(now, DynamicsParameters()),
        event_id=str(event_id),
        situation_id=str(situation_id),
        appraisal=appraisal(relevance=1, gain=1, phase="realized"),
        at=now,
        summary="private event content",
    )
    view = MoodView(
        uuid7(), 2, now, current_affect(state, now), state, "applied", event_id, None
    )
    payload = mood_snapshot_bytes(view)
    document = json.loads(payload)
    assert set(document["current"]) == {"valence", "arousal"}
    assert document["quality"]["status"] == "applied"
    assert active_mood_episodes(payload)[0][0] == situation_id
    items = mood_context_items(
        payload, revision_id=view.current_revision_id, version=view.version
    )
    assert "private event content" not in items[0].content
    assert any("private event content" in item.content for item in items[1:])
