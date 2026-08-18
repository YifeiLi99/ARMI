from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from armi_kernel.application import CandidateFactClass
from armi_mood._domain import (
    StoredAffectiveEvent,
    StoredEmotionComponent,
    clamp_home_base,
    derive_effective_state,
    half_life_seconds,
    parse_state,
    state_to_wire,
)
from armi_mood.api import (
    VAD,
    AffectiveEvent,
    CandidateMoodDraft,
    EmotionComponent,
    EmotionFamily,
    MoodCandidateKind,
    MoodViolation,
)
from armi_mood.bootstrap import bootstrap_mood_cognition


def _component(
    family: EmotionFamily = EmotionFamily.HOPE,
    *,
    nuance: str = "期待",
    vad: VAD | None = None,
    intensity: int = 60,
) -> EmotionComponent:
    return EmotionComponent(family, nuance, vad or VAD(60, 40, 20), intensity)


def _candidate(**overrides: Any) -> CandidateMoodDraft:
    values: dict[str, Any] = {
        "proposal_ref": "proposal:1",
        "atomic_group_ref": "group:1",
        "basis_ordinals": (1,),
        "fact_class": CandidateFactClass.SUBJECTIVE_UNDERSTANDING,
        "expected_version": 1,
        "kind": MoodCandidateKind.EVENT,
        "event": AffectiveEvent(70, (_component(),)),
    }
    values.update(overrides)
    return CandidateMoodDraft(**values)


def test_mood_owner_event_round_trip_is_canonical() -> None:
    cognition = bootstrap_mood_cognition()
    candidate = _candidate()
    bound = cognition.bind(candidate)
    assert bound.owner == "mood"
    assert cognition.decode(bound.canonical_payload) == candidate
    assert cognition.bind(cognition.decode(bound.canonical_payload)) == bound


def test_mood_owner_reflection_round_trip_is_canonical() -> None:
    cognition = bootstrap_mood_cognition()
    candidate = _candidate(
        kind=MoodCandidateKind.HOME_BASE_REFLECTION,
        event=None,
        target_home_base=VAD(20, -10, 5),
    )
    assert cognition.decode(cognition.bind(candidate).canonical_payload) == candidate


def test_all_twenty_families_are_stable() -> None:
    assert len(EmotionFamily) == 20
    for family in EmotionFamily:
        assert bootstrap_mood_cognition().decode(
            bootstrap_mood_cognition()
            .bind(_candidate(event=AffectiveEvent(50, (_component(family),))))
            .canonical_payload
        ).event == AffectiveEvent(50, (_component(family),))


@pytest.mark.parametrize("value", [-105, -1, 101])
def test_model_coordinates_require_five_point_steps(value: int) -> None:
    with pytest.raises(MoodViolation):
        _component(vad=VAD(value, 0, 0))


def test_half_life_uses_declared_endpoints() -> None:
    assert half_life_seconds(importance=5, intensity=5) == 900
    assert half_life_seconds(importance=100, intensity=100) == 86_400


def test_opposing_emotions_mix_and_decay_to_home_base() -> None:
    now = datetime(2026, 8, 18, tzinfo=UTC)
    positive = StoredEmotionComponent(
        _component(EmotionFamily.JOY, nuance="开心", vad=VAD(80, 40, 30)), 900
    )
    negative = StoredEmotionComponent(
        _component(
            EmotionFamily.SADNESS,
            nuance="失落",
            vad=VAD(-80, -40, -30),
        ),
        900,
    )
    event = StoredAffectiveEvent(now, (positive, negative))
    current, active = derive_effective_state(VAD(0, 0, 0), (event,), as_of=now)
    assert current == VAD(0, 0, 0)
    assert {item.family for item in active} == {
        EmotionFamily.JOY,
        EmotionFamily.SADNESS,
    }
    decayed, active = derive_effective_state(
        VAD(10, -10, 5), (event,), as_of=now + timedelta(hours=3)
    )
    assert decayed == VAD(10, -10, 5)
    assert active == ()


def test_same_family_recurrence_combines_strength_and_keeps_strongest_nuance() -> None:
    now = datetime(2026, 8, 18, tzinfo=UTC)
    events = (
        StoredAffectiveEvent(
            now,
            (
                StoredEmotionComponent(
                    _component(nuance="微微期待", intensity=30), 3600
                ),
            ),
        ),
        StoredAffectiveEvent(
            now + timedelta(minutes=1),
            (
                StoredEmotionComponent(
                    _component(nuance="非常期待", intensity=80), 3600
                ),
            ),
        ),
    )
    _, active = derive_effective_state(
        VAD(0, 0, 0), events, as_of=now + timedelta(minutes=1)
    )
    assert len(active) == 1
    assert active[0].family is EmotionFamily.HOPE
    assert active[0].nuance == "非常期待"
    assert active[0].intensity == 100


def test_derivation_depends_only_on_as_of_not_poll_slices() -> None:
    started = datetime(2026, 8, 18, tzinfo=UTC)
    events = (
        StoredAffectiveEvent(
            started,
            (StoredEmotionComponent(_component(), 3600),),
        ),
    )
    target = started + timedelta(minutes=37)
    direct = derive_effective_state(VAD(0, 0, 0), events, as_of=target)
    for minute in range(1, 37):
        derive_effective_state(
            VAD(0, 0, 0), events, as_of=started + timedelta(minutes=minute)
        )
    assert derive_effective_state(VAD(0, 0, 0), events, as_of=target) == direct


def test_home_base_reflection_moves_at_most_two_points_per_axis() -> None:
    assert clamp_home_base(VAD(0, 0, 0), VAD(100, -100, 1)) == VAD(2, -2, 1)


def test_state_contract_is_v2_and_rejects_extra_fields() -> None:
    state = parse_state(
        {
            "schema_version": "armi.mood.v2",
            "dynamics_version": "exponential.v1",
            "home_base": {"valence": 0, "arousal": 0, "dominance": 0},
        }
    )
    assert state_to_wire(state)["schema_version"] == "armi.mood.v2"
    with pytest.raises(MoodViolation):
        parse_state({**state_to_wire(state), "mood": "平静"})
