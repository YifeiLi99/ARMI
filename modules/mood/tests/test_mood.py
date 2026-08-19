from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid7

import pytest
from armi_kernel.application import CandidateFactClass
from armi_mood._domain import (
    StoredAffectiveEvent,
    StoredEmotionComponent,
    clamp_home_base,
    derive_appraisal,
    derive_effective_snapshot,
    derive_effective_state,
    derive_semantic_appraisal,
    parse_state,
    state_to_wire,
)
from armi_mood.api import (
    VAD,
    AppraisalAdjustment,
    AppraisalAgency,
    AppraisalCausality,
    AppraisalCertainty,
    AppraisalCompatibility,
    AppraisalConcern,
    AppraisalConcernTarget,
    AppraisalCoping,
    AppraisalDemand,
    AppraisalDemandLevel,
    AppraisalDirection,
    AppraisalEvent,
    AppraisalEventPhase,
    AppraisalExpectedness,
    AppraisalIntentionality,
    AppraisalPowerBalance,
    AppraisalQuality,
    AppraisalResponseAccess,
    AppraisalSelfInvolvement,
    AppraisalSelfScope,
    AppraisalSignificance,
    AppraisalStandards,
    AppraisalTrajectory,
    AppraisalTransition,
    AppraisalUrgency,
    AppraisalVector,
    CandidateMoodDraft,
    EmotionComponent,
    EmotionFamily,
    MoodCandidateKind,
    MoodViolation,
    SemanticAppraisal,
    SemanticAppraisalEvent,
)
from armi_mood.bootstrap import bootstrap_mood_cognition


def _vector(**overrides: Any) -> AppraisalVector:
    values: dict[str, Any] = {
        "suddenness": 0,
        "predictability": 4,
        "outcome_certainty": 4,
        "self_relevance": 4,
        "relationship_relevance": 0,
        "social_order_relevance": 0,
        "urgency": 0,
        "effort": 0,
        "intentionality": 0,
        "control": 2,
        "power": 2,
        "adjustment": 2,
        "ego_involvement": 0,
        "intrinsic_pleasantness": 0,
        "goal_conduciveness": 0,
        "self_compatibility": 0,
        "norm_compatibility": 0,
        "agency": AppraisalAgency.CIRCUMSTANCE,
        "self_scope": AppraisalSelfScope.NONE,
    }
    values.update(overrides)
    return AppraisalVector(**values)


def _event(
    *,
    vector: AppraisalVector | None = None,
    transition: AppraisalTransition = AppraisalTransition.NEW,
    phase: AppraisalEventPhase = AppraisalEventPhase.REALIZED,
    gist: str = "这件事对我有意义",
) -> AppraisalEvent:
    return AppraisalEvent(
        transition,
        None if transition is AppraisalTransition.NEW else uuid7(),
        phase,
        gist,
        vector or _vector(goal_conduciveness=4),
    )


def _candidate(**overrides: Any) -> CandidateMoodDraft:
    values: dict[str, Any] = {
        "proposal_ref": "proposal:1",
        "atomic_group_ref": "group:1",
        "basis_ordinals": (1,),
        "fact_class": CandidateFactClass.SUBJECTIVE_UNDERSTANDING,
        "expected_version": 1,
        "kind": MoodCandidateKind.APPRAISAL,
        "appraisal": _event(),
    }
    values.update(overrides)
    return CandidateMoodDraft(**values)


def _semantic_event(
    *,
    concerns: tuple[AppraisalConcern, ...] | None = None,
    expectedness: AppraisalExpectedness = AppraisalExpectedness.EXPECTED,
    certainty: AppraisalCertainty = AppraisalCertainty.SETTLED,
    quality: AppraisalQuality = AppraisalQuality.PLEASANT,
    involvement: AppraisalSelfInvolvement = AppraisalSelfInvolvement.LIMITED,
    demand: AppraisalDemand | None = None,
    causality: AppraisalCausality | None = None,
    coping: AppraisalCoping | None = None,
    standards: AppraisalStandards | None = None,
    transition: AppraisalTransition = AppraisalTransition.NEW,
    phase: AppraisalEventPhase = AppraisalEventPhase.REALIZED,
) -> SemanticAppraisalEvent:
    return SemanticAppraisalEvent(
        transition,
        None if transition is AppraisalTransition.NEW else uuid7(),
        phase,
        "这件事改变了我的处境",
        SemanticAppraisal(
            concerns
            or (
                AppraisalConcern(
                    AppraisalConcernTarget.SELF_GOAL,
                    AppraisalSignificance.CORE,
                    AppraisalDirection.FULFILLED,
                ),
            ),
            expectedness,
            certainty,
            quality,
            involvement,
            demand,
            causality,
            coping,
            standards,
        ),
        None
        if transition is AppraisalTransition.NEW
        else AppraisalTrajectory.IMPROVED,
    )


def _component(
    family: EmotionFamily = EmotionFamily.HOPE,
    *,
    nuance: str = "期待",
    vad: VAD | None = None,
    intensity: int = 60,
) -> EmotionComponent:
    return EmotionComponent(family, nuance, vad or VAD(60, 40, 20), intensity)


def test_mood_candidate_round_trips_are_canonical() -> None:
    cognition = bootstrap_mood_cognition()
    for candidate in (
        _candidate(),
        _candidate(kind=MoodCandidateKind.HOME_BASE_REFLECTION, appraisal=None),
    ):
        assert (
            cognition.decode(cognition.bind(candidate).canonical_payload) == candidate
        )


def test_semantic_mood_candidate_round_trips_without_model_scores() -> None:
    cognition = bootstrap_mood_cognition()
    candidate = _candidate(appraisal=_semantic_event())
    payload = cognition.bind(candidate).canonical_payload
    assert b"armi.mood-candidate.v4" in payload
    assert b"semantic" not in payload
    assert cognition.decode(payload) == candidate


def test_unknown_semantics_do_not_invent_affect() -> None:
    event = _semantic_event(
        concerns=(
            AppraisalConcern(
                AppraisalConcernTarget.SELF_GOAL,
                AppraisalSignificance.UNKNOWN,
                AppraisalDirection.UNKNOWN,
            ),
        ),
        expectedness=AppraisalExpectedness.UNKNOWN,
        certainty=AppraisalCertainty.UNKNOWN,
        quality=AppraisalQuality.UNKNOWN,
        involvement=AppraisalSelfInvolvement.UNKNOWN,
    )
    result = derive_semantic_appraisal(event)
    assert result.components == ()
    assert result.target.dominance == 0


def test_missing_coping_is_not_interpreted_as_helplessness() -> None:
    event = _semantic_event(
        concerns=(
            AppraisalConcern(
                AppraisalConcernTarget.SELF_GOAL,
                AppraisalSignificance.CORE,
                AppraisalDirection.MAJOR_SETBACK,
            ),
        ),
        quality=AppraisalQuality.UNPLEASANT,
        coping=None,
    )
    result = derive_semantic_appraisal(event)
    assert EmotionFamily.SADNESS not in {
        item.component.family for item in result.components
    }
    assert result.target.dominance == 0


def test_mixed_concerns_keep_positive_and_negative_emotions() -> None:
    event = _semantic_event(
        concerns=(
            AppraisalConcern(
                AppraisalConcernTarget.SELF_GOAL,
                AppraisalSignificance.CORE,
                AppraisalDirection.FULFILLED,
            ),
            AppraisalConcern(
                AppraisalConcernTarget.RELATIONSHIP,
                AppraisalSignificance.CORE,
                AppraisalDirection.MAJOR_SETBACK,
            ),
        ),
        coping=AppraisalCoping(
            AppraisalResponseAccess.NONE,
            AppraisalPowerBalance.OVERMATCHED,
            AppraisalAdjustment.BLOCKED,
        ),
    )
    families = {
        item.component.family for item in derive_semantic_appraisal(event).components
    }
    assert EmotionFamily.JOY in families
    assert EmotionFamily.SADNESS in families


def test_mixed_single_concern_forms_two_weighted_poles() -> None:
    event = _semantic_event(
        concerns=(
            AppraisalConcern(
                AppraisalConcernTarget.SELF_GOAL,
                AppraisalSignificance.CORE,
                AppraisalDirection.MIXED,
            ),
        ),
        coping=AppraisalCoping(
            AppraisalResponseAccess.NONE,
            AppraisalPowerBalance.OVERMATCHED,
            AppraisalAdjustment.BLOCKED,
        ),
    )
    result = derive_semantic_appraisal(event)
    families = {item.component.family for item in result.components}
    assert EmotionFamily.JOY in families
    assert EmotionFamily.SADNESS in families


@pytest.mark.parametrize(
    ("scope", "adjustment", "expected", "excluded"),
    (
        (
            AppraisalSelfScope.ACTION,
            AppraisalAdjustment.EASY,
            EmotionFamily.GUILT,
            EmotionFamily.SHAME,
        ),
        (
            AppraisalSelfScope.GLOBAL,
            AppraisalAdjustment.BLOCKED,
            EmotionFamily.SHAME,
            EmotionFamily.GUILT,
        ),
    ),
)
def test_semantic_self_standard_scope_distinguishes_guilt_and_shame(
    scope: AppraisalSelfScope,
    adjustment: AppraisalAdjustment,
    expected: EmotionFamily,
    excluded: EmotionFamily,
) -> None:
    event = _semantic_event(
        concerns=(
            AppraisalConcern(
                AppraisalConcernTarget.SELF_GOAL,
                AppraisalSignificance.CORE,
                AppraisalDirection.MAJOR_SETBACK,
            ),
        ),
        quality=AppraisalQuality.UNPLEASANT,
        involvement=AppraisalSelfInvolvement.IDENTITY_LEVEL,
        causality=AppraisalCausality(
            AppraisalAgency.SELF, AppraisalIntentionality.DELIBERATE
        ),
        coping=AppraisalCoping(
            AppraisalResponseAccess.DIRECT,
            AppraisalPowerBalance.BALANCED,
            adjustment,
        ),
        standards=AppraisalStandards(
            AppraisalCompatibility.VIOLATION,
            AppraisalCompatibility.ALIGNED,
            scope,
        ),
    )
    families = {
        item.component.family for item in derive_semantic_appraisal(event).components
    }
    assert expected in families
    assert excluded not in families


@pytest.mark.parametrize(
    ("certainty", "expected", "excluded"),
    (
        (
            AppraisalCertainty.SETTLED,
            EmotionFamily.FEAR,
            EmotionFamily.ANXIETY,
        ),
        (
            AppraisalCertainty.UNCERTAIN,
            EmotionFamily.ANXIETY,
            EmotionFamily.FEAR,
        ),
    ),
)
def test_semantic_certainty_distinguishes_fear_and_anxiety(
    certainty: AppraisalCertainty,
    expected: EmotionFamily,
    excluded: EmotionFamily,
) -> None:
    event = _semantic_event(
        concerns=(
            AppraisalConcern(
                AppraisalConcernTarget.SELF_GOAL,
                AppraisalSignificance.CORE,
                AppraisalDirection.MAJOR_SETBACK,
            ),
        ),
        certainty=certainty,
        quality=AppraisalQuality.UNPLEASANT,
        demand=AppraisalDemand(
            AppraisalUrgency.IMMEDIATE, AppraisalDemandLevel.SUBSTANTIAL
        ),
        coping=AppraisalCoping(
            AppraisalResponseAccess.NONE,
            AppraisalPowerBalance.OVERMATCHED,
            AppraisalAdjustment.DIFFICULT,
        ),
        phase=AppraisalEventPhase.ANTICIPATED,
    )
    families = {
        item.component.family for item in derive_semantic_appraisal(event).components
    }
    assert expected in families
    assert excluded not in families


def test_semantic_agency_and_persistence_distinguish_anger_and_frustration() -> None:
    concern = (
        AppraisalConcern(
            AppraisalConcernTarget.SELF_GOAL,
            AppraisalSignificance.CORE,
            AppraisalDirection.MAJOR_SETBACK,
        ),
    )
    anger = _semantic_event(
        concerns=concern,
        quality=AppraisalQuality.UNPLEASANT,
        causality=AppraisalCausality(
            AppraisalAgency.OTHER, AppraisalIntentionality.DELIBERATE
        ),
        coping=AppraisalCoping(
            AppraisalResponseAccess.DIRECT,
            AppraisalPowerBalance.ADVANTAGED,
            AppraisalAdjustment.MANAGEABLE,
        ),
    )
    frustration = _semantic_event(
        concerns=concern,
        quality=AppraisalQuality.UNPLEASANT,
        demand=AppraisalDemand(
            AppraisalUrgency.SOON, AppraisalDemandLevel.EXTREME
        ),
        causality=AppraisalCausality(
            AppraisalAgency.CIRCUMSTANCE,
            AppraisalIntentionality.NOT_APPLICABLE,
        ),
        coping=AppraisalCoping(
            AppraisalResponseAccess.INDIRECT,
            AppraisalPowerBalance.BALANCED,
            AppraisalAdjustment.DIFFICULT,
        ),
        phase=AppraisalEventPhase.ONGOING,
    )
    anger_families = {
        item.component.family for item in derive_semantic_appraisal(anger).components
    }
    frustration_families = {
        item.component.family
        for item in derive_semantic_appraisal(frustration).components
    }
    assert EmotionFamily.ANGER in anger_families
    assert EmotionFamily.FRUSTRATION not in anger_families
    assert EmotionFamily.FRUSTRATION in frustration_families
    assert EmotionFamily.ANGER not in frustration_families


def test_semantic_resolve_can_close_a_numeric_v1_episode() -> None:
    previous = _event(
        vector=_vector(goal_conduciveness=-4),
        phase=AppraisalEventPhase.ANTICIPATED,
    )
    resolved = _semantic_event(
        concerns=(
            AppraisalConcern(
                AppraisalConcernTarget.SELF_GOAL,
                AppraisalSignificance.CORE,
                AppraisalDirection.FULFILLED,
            ),
        ),
        transition=AppraisalTransition.RESOLVE,
        phase=AppraisalEventPhase.AVERTED,
    )
    families = {
        item.component.family
        for item in derive_semantic_appraisal(resolved, previous=previous).components
    }
    assert EmotionFamily.RELIEF in families


_SIGNATURES: tuple[tuple[EmotionFamily, dict[str, Any], AppraisalEventPhase], ...] = (
    (EmotionFamily.JOY, {"goal_conduciveness": 4}, AppraisalEventPhase.REALIZED),
    (
        EmotionFamily.CONTENTMENT,
        {"goal_conduciveness": 4},
        AppraisalEventPhase.REALIZED,
    ),
    (
        EmotionFamily.INTEREST,
        {"suddenness": 4, "predictability": 0, "control": 4},
        AppraisalEventPhase.REALIZED,
    ),
    (
        EmotionFamily.HOPE,
        {"goal_conduciveness": 4, "outcome_certainty": 2},
        AppraisalEventPhase.ANTICIPATED,
    ),
    (
        EmotionFamily.AFFECTION,
        {
            "self_relevance": 0,
            "relationship_relevance": 4,
            "goal_conduciveness": 4,
            "agency": AppraisalAgency.OTHER,
        },
        AppraisalEventPhase.REALIZED,
    ),
    (
        EmotionFamily.GRATITUDE,
        {"goal_conduciveness": 4, "agency": AppraisalAgency.OTHER, "intentionality": 4},
        AppraisalEventPhase.REALIZED,
    ),
    (
        EmotionFamily.PRIDE,
        {
            "goal_conduciveness": 4,
            "agency": AppraisalAgency.SELF,
            "self_compatibility": 4,
            "ego_involvement": 4,
        },
        AppraisalEventPhase.REALIZED,
    ),
    (
        EmotionFamily.SURPRISE,
        {"suddenness": 4, "predictability": 0},
        AppraisalEventPhase.REALIZED,
    ),
    (
        EmotionFamily.SADNESS,
        {"goal_conduciveness": -4, "control": 0, "power": 0, "adjustment": 0},
        AppraisalEventPhase.REALIZED,
    ),
    (
        EmotionFamily.FEAR,
        {"goal_conduciveness": -4, "power": 0, "urgency": 4},
        AppraisalEventPhase.ANTICIPATED,
    ),
    (
        EmotionFamily.ANXIETY,
        {"goal_conduciveness": -4, "outcome_certainty": 0, "control": 0, "urgency": 4},
        AppraisalEventPhase.ANTICIPATED,
    ),
    (
        EmotionFamily.ANGER,
        {
            "goal_conduciveness": -4,
            "agency": AppraisalAgency.OTHER,
            "intentionality": 4,
            "control": 4,
        },
        AppraisalEventPhase.REALIZED,
    ),
    (
        EmotionFamily.FRUSTRATION,
        {"goal_conduciveness": -4, "effort": 4, "control": 2},
        AppraisalEventPhase.ONGOING,
    ),
    (
        EmotionFamily.DISGUST,
        {"intrinsic_pleasantness": -4, "norm_compatibility": -4, "adjustment": 0},
        AppraisalEventPhase.REALIZED,
    ),
    (
        EmotionFamily.SHAME,
        {
            "agency": AppraisalAgency.SELF,
            "self_compatibility": -4,
            "self_scope": AppraisalSelfScope.GLOBAL,
            "ego_involvement": 4,
            "adjustment": 0,
        },
        AppraisalEventPhase.REALIZED,
    ),
    (
        EmotionFamily.GUILT,
        {
            "agency": AppraisalAgency.SELF,
            "self_compatibility": -4,
            "self_scope": AppraisalSelfScope.ACTION,
            "adjustment": 4,
        },
        AppraisalEventPhase.REALIZED,
    ),
    (
        EmotionFamily.JEALOUSY,
        {
            "self_relevance": 0,
            "relationship_relevance": 4,
            "goal_conduciveness": -4,
            "agency": AppraisalAgency.OTHER,
            "ego_involvement": 4,
        },
        AppraisalEventPhase.ANTICIPATED,
    ),
    (EmotionFamily.BOREDOM, {"self_relevance": 0}, AppraisalEventPhase.ONGOING),
    (
        EmotionFamily.CONFUSION,
        {
            "suddenness": 4,
            "predictability": 0,
            "outcome_certainty": 0,
            "control": 0,
            "power": 0,
        },
        AppraisalEventPhase.REALIZED,
    ),
)


@pytest.mark.parametrize(("family", "overrides", "phase"), _SIGNATURES)
def test_each_non_relief_family_has_an_appraisal_signature(
    family: EmotionFamily,
    overrides: dict[str, Any],
    phase: AppraisalEventPhase,
) -> None:
    result = derive_appraisal(_event(vector=_vector(**overrides), phase=phase))
    assert family in {item.component.family for item in result.components}


def test_resolve_derives_relief_from_prior_negative_expectation() -> None:
    previous = _event(
        vector=_vector(goal_conduciveness=-4, outcome_certainty=2),
        phase=AppraisalEventPhase.ANTICIPATED,
    )
    resolved = _event(
        vector=_vector(goal_conduciveness=4),
        transition=AppraisalTransition.RESOLVE,
        phase=AppraisalEventPhase.AVERTED,
    )
    result = derive_appraisal(resolved, previous=previous)
    assert EmotionFamily.RELIEF in {item.component.family for item in result.components}


def test_owner_derives_vad_importance_intensity_and_bounded_half_life() -> None:
    result = derive_appraisal(_event(vector=_vector(goal_conduciveness=4, urgency=4)))
    assert result.target == VAD(55, -30, 0)
    assert result.importance == 100
    assert all(5 <= item.component.intensity <= 100 for item in result.components)
    assert all(900 <= item.half_life_seconds <= 86_400 for item in result.components)


def test_opposing_emotions_mix_then_decay_to_home_base() -> None:
    now = datetime(2026, 8, 18, tzinfo=UTC)
    event = StoredAffectiveEvent(
        now,
        (
            StoredEmotionComponent(
                _component(EmotionFamily.JOY, nuance="开心", vad=VAD(80, 40, 30)), 900
            ),
            StoredEmotionComponent(
                _component(
                    EmotionFamily.SADNESS, nuance="失落", vad=VAD(-80, -40, -30)
                ),
                900,
            ),
        ),
    )
    current, active = derive_effective_state(VAD(0, 0, 0), (event,), as_of=now)
    assert current == VAD(0, 0, 0)
    assert {item.family for item in active} == {
        EmotionFamily.JOY,
        EmotionFamily.SADNESS,
    }
    assert derive_effective_state(
        VAD(10, -10, 5), (event,), as_of=now + timedelta(hours=3)
    ) == (VAD(10, -10, 5), ())


def test_same_family_merges_and_snapshot_exposes_episode_and_top_tendencies() -> None:
    now = datetime(2026, 8, 18, tzinfo=UTC)
    episode_id = uuid7()
    events = (
        StoredAffectiveEvent(
            now,
            (
                StoredEmotionComponent(
                    _component(nuance="微微期待", intensity=30), 3600
                ),
            ),
            episode_id,
            gist="结果可能很好",
        ),
        StoredAffectiveEvent(
            now + timedelta(minutes=1),
            (
                StoredEmotionComponent(
                    _component(nuance="非常期待", intensity=80), 3600
                ),
            ),
            episode_id,
            AppraisalTransition.REINFORCE,
            AppraisalEventPhase.ANTICIPATED,
            "新的迹象强化了期待",
        ),
    )
    _, active, episodes, tendencies = derive_effective_snapshot(
        VAD(0, 0, 0), events, as_of=now + timedelta(minutes=1)
    )
    assert (active[0].family, active[0].nuance, active[0].intensity) == (
        EmotionFamily.HOPE,
        "非常期待",
        100,
    )
    assert episodes[0].episode_id == episode_id
    assert len(tendencies) <= 2


def test_same_as_of_is_independent_of_poll_slices() -> None:
    started = datetime(2026, 8, 18, tzinfo=UTC)
    events = (
        StoredAffectiveEvent(started, (StoredEmotionComponent(_component(), 3600),)),
    )
    target = started + timedelta(minutes=37)
    direct = derive_effective_state(VAD(0, 0, 0), events, as_of=target)
    for minute in range(1, 37):
        derive_effective_state(
            VAD(0, 0, 0), events, as_of=started + timedelta(minutes=minute)
        )
    assert derive_effective_state(VAD(0, 0, 0), events, as_of=target) == direct


def test_home_base_moves_at_most_two_points_per_axis() -> None:
    assert clamp_home_base(VAD(0, 0, 0), VAD(100, -100, 1)) == VAD(2, -2, 1)


def test_state_contract_is_v3_and_rejects_extra_fields() -> None:
    state = parse_state(
        {
            "schema_version": "armi.mood.v3",
            "dynamics_version": "recency-reappraisal.v1",
            "derivation_version": "cpm-fuzzy.v1",
            "home_base": {"valence": 0, "arousal": 0, "dominance": 0},
        }
    )
    assert state_to_wire(state)["schema_version"] == "armi.mood.v3"
    with pytest.raises(MoodViolation):
        parse_state({**state_to_wire(state), "mood": "平静"})
