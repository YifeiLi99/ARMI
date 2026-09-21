from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid7

import pytest
import rfc8785
from armi_kernel.application import CandidateFactClass
from armi_mood._domain import (
    StoredAffectiveEvent,
    StoredCoreAffect,
    StoredEmotionComponent,
    clamp_home_base,
    consideration_signals,
    derive_effective_snapshot,
    derive_effective_state,
    derive_semantic_appraisal,
    parse_semantic_appraisal,
    parse_state,
    semantic_appraisal_to_wire,
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
    CandidateMoodDraft,
    EmotionComponent,
    EmotionFamily,
    MoodCandidateKind,
    MoodViolation,
    SemanticAppraisal,
    SemanticAppraisalEvent,
    active_mood_episodes,
    active_mood_gists,
)
from armi_mood.bootstrap import bootstrap_mood_cognition


def _candidate(**overrides: Any) -> CandidateMoodDraft:
    values: dict[str, Any] = {
        "proposal_ref": "proposal:1",
        "atomic_group_ref": "group:1",
        "basis_ordinals": (1,),
        "fact_class": CandidateFactClass.SUBJECTIVE_UNDERSTANDING,
        "expected_version": 1,
        "kind": MoodCandidateKind.APPRAISAL,
        "appraisal": _semantic_event(),
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
        None if transition is AppraisalTransition.NEW else AppraisalTrajectory.IMPROVED,
    )


@pytest.mark.parametrize(
    "engagement", ["satisfying", "not_applicable", "unknown", "understimulated"]
)
def test_quiet_waiting_only_becomes_boredom_with_grounded_understimulation(engagement):
    event = _semantic_event(
        phase=AppraisalEventPhase.ONGOING,
        concerns=(
            AppraisalConcern(
                AppraisalConcernTarget.RELATIONSHIP,
                AppraisalSignificance.DIRECT,
                AppraisalDirection.UNCHANGED,
            ),
        ),
        quality=AppraisalQuality.NEUTRAL,
        certainty=AppraisalCertainty.OPEN,
        demand=AppraisalDemand(AppraisalUrgency.NONE, AppraisalDemandLevel.NONE),
        coping=AppraisalCoping(
            AppraisalResponseAccess.INDIRECT,
            AppraisalPowerBalance.BALANCED,
            AppraisalAdjustment.EASY,
        ),
    )
    event = replace(event, appraisal=replace(event.appraisal, engagement=engagement))
    result = derive_semantic_appraisal(event)
    boredom = [
        c for c in result.components if c.component.family is EmotionFamily.BOREDOM
    ]
    assert bool(boredom) == (engagement == "understimulated")


@pytest.mark.parametrize(
    "quality,norm,expected",
    [
        (AppraisalQuality.UNPLEASANT, AppraisalCompatibility.NOT_APPLICABLE, False),
        (
            AppraisalQuality.STRONGLY_AVERSIVE,
            AppraisalCompatibility.NOT_APPLICABLE,
            True,
        ),
        (AppraisalQuality.UNPLEASANT, AppraisalCompatibility.VIOLATION, False),
    ],
)
def test_disgust_requires_repulsion_not_loss_or_norm_conflict_alone(
    quality, norm, expected
):
    event = _semantic_event(
        concerns=(
            AppraisalConcern(
                AppraisalConcernTarget.SELF_GOAL,
                AppraisalSignificance.CORE,
                AppraisalDirection.MAJOR_SETBACK,
            ),
        ),
        quality=quality,
        coping=AppraisalCoping(
            AppraisalResponseAccess.NONE,
            AppraisalPowerBalance.OVERMATCHED,
            AppraisalAdjustment.BLOCKED,
        ),
        standards=AppraisalStandards(
            AppraisalCompatibility.NOT_APPLICABLE, norm, AppraisalSelfScope.NONE
        ),
    )
    families = {c.component.family for c in derive_semantic_appraisal(event).components}
    assert (EmotionFamily.DISGUST in families) is expected
    assert EmotionFamily.SADNESS in families


@pytest.mark.parametrize(
    "intent,expected",
    [
        (AppraisalIntentionality.UNCLEAR, False),
        (AppraisalIntentionality.UNKNOWN, False),
        (AppraisalIntentionality.ACCIDENTAL, False),
        (AppraisalIntentionality.DELIBERATE, True),
    ],
)
def test_anger_does_not_treat_uncertain_intent_as_deliberate_harm(intent, expected):
    event = _semantic_event(
        concerns=(
            AppraisalConcern(
                AppraisalConcernTarget.SELF_GOAL,
                AppraisalSignificance.CORE,
                AppraisalDirection.MAJOR_SETBACK,
            ),
        ),
        quality=AppraisalQuality.UNPLEASANT,
        causality=AppraisalCausality(AppraisalAgency.OTHER, intent),
        coping=AppraisalCoping(
            AppraisalResponseAccess.DIRECT,
            AppraisalPowerBalance.ADVANTAGED,
            AppraisalAdjustment.MANAGEABLE,
        ),
    )
    families = {c.component.family for c in derive_semantic_appraisal(event).components}
    assert (EmotionFamily.ANGER in families) is expected


def _component(
    family: EmotionFamily = EmotionFamily.HOPE,
    *,
    nuance: str = "期待",
    vad: VAD | None = None,
    intensity: int = 60,
) -> EmotionComponent:
    return EmotionComponent(family, nuance, vad or VAD(60, 40, 20), intensity)


def test_resolved_episode_leaves_context_while_residual_emotion_decays() -> None:
    now = datetime(2026, 9, 19, tzinfo=UTC)
    episode_id = uuid7()
    opened = StoredAffectiveEvent(
        now,
        (StoredEmotionComponent(_component(intensity=80), 3600),),
        episode_id,
        gist="等待回应",
        core=StoredCoreAffect(VAD(0, 20, 0), 80, 3600),
    )
    closed = StoredAffectiveEvent(
        now + timedelta(seconds=1),
        (),
        episode_id,
        AppraisalTransition.RESOLVE,
        AppraisalEventPhase.REALIZED,
        "已经结束",
        core=StoredCoreAffect(VAD(0, 0, 0), 0, 3600),
    )
    _, emotions, episodes, _ = derive_effective_snapshot(
        VAD(0, 0, 0), (opened, closed), as_of=now + timedelta(seconds=2)
    )
    assert emotions
    assert episodes == ()
    assert derive_effective_snapshot(VAD(0, 0, 0), (opened, closed), as_of=now)[2]


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
    assert b"armi.mood-candidate.v5" in payload
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
    assert result.core.intensity == 0


def test_missing_coping_allows_sadness_without_inventing_helplessness() -> None:
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
    assert EmotionFamily.SADNESS in {
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
    strengths = {
        item.component.family: item.component.intensity
        for item in derive_semantic_appraisal(event).components
    }
    # Graded matching allows mixed fear/anxiety; certainty changes which leads.
    assert strengths[expected] > strengths.get(excluded, 0)


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
        demand=AppraisalDemand(AppraisalUrgency.SOON, AppraisalDemandLevel.EXTREME),
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


def test_semantic_resolve_can_close_a_negative_episode() -> None:
    previous = _semantic_event(
        concerns=(
            AppraisalConcern(
                AppraisalConcernTarget.SELF_GOAL,
                AppraisalSignificance.CORE,
                AppraisalDirection.MAJOR_SETBACK,
            ),
        ),
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
        core=StoredCoreAffect(VAD(0, 0, 0), 60, 900),
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
            core=StoredCoreAffect(VAD(0, 20, 0), 30, 3600),
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
            core=StoredCoreAffect(VAD(0, 20, 0), 80, 3600),
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


@pytest.mark.parametrize(
    "family,attracts",
    [
        (EmotionFamily.CONFUSION, True),
        (EmotionFamily.INTEREST, True),
        (EmotionFamily.AFFECTION, True),
        (EmotionFamily.GUILT, True),
        (EmotionFamily.CONTENTMENT, False),
    ],
)
def test_new_affect_can_attract_attention_without_ordering_expression(
    family: EmotionFamily, attracts: bool
) -> None:
    now = datetime(2026, 9, 16, tzinfo=UTC)
    event = StoredAffectiveEvent(
        now,
        (
            StoredEmotionComponent(
                EmotionComponent(family, "牵挂的事情", VAD(0, 20, 0), 60), 3600
            ),
        ),
        uuid7(),
        phase=AppraisalEventPhase.ONGOING,
        core=StoredCoreAffect(VAD(0, 20, 0), 60, 3600),
    )
    event = replace(event, event_id=uuid7())
    signals = consideration_signals((event,), minimum_delay_seconds=60, as_of=now)
    assert bool(signals) is attracts
    if attracts:
        assert signals[0].eligible_at == now + timedelta(seconds=60)
        assert signals[0].object_ref == event.episode_id
        assert (
            consideration_signals((event,), minimum_delay_seconds=60, as_of=now)
            == signals
        )
    assert (
        consideration_signals(
            (event,), minimum_delay_seconds=60, as_of=now + timedelta(days=2)
        )
        == ()
    )


@pytest.mark.parametrize(
    "transition", [AppraisalTransition.RESOLVE, AppraisalTransition.REAPPRAISE]
)
def test_resolved_or_reappraised_concern_does_not_reuse_old_action_tendency(
    transition: AppraisalTransition,
) -> None:
    now = datetime(2026, 9, 16, tzinfo=UTC)
    episode = uuid7()
    event = StoredAffectiveEvent(
        now,
        (
            StoredEmotionComponent(
                EmotionComponent(EmotionFamily.CONFUSION, "不明白", VAD(0, 20, 0), 60),
                3600,
            ),
        ),
        episode,
        core=StoredCoreAffect(VAD(0, 20, 0), 60, 3600),
    )
    later = StoredAffectiveEvent(
        now + timedelta(minutes=1),
        (),
        episode,
        transition,
        AppraisalEventPhase.AVERTED,
        core=StoredCoreAffect(VAD(0, 0, 0), 0, 3600),
    )
    assert (
        consideration_signals(
            (event, later), minimum_delay_seconds=60, as_of=later.occurred_at
        )
        == ()
    )


def test_same_as_of_is_independent_of_poll_slices() -> None:
    started = datetime(2026, 8, 18, tzinfo=UTC)
    events = (
        StoredAffectiveEvent(
            started,
            (StoredEmotionComponent(_component(), 3600),),
            core=StoredCoreAffect(VAD(0, 20, 0), 60, 3600),
        ),
    )
    target = started + timedelta(minutes=37)
    direct = derive_effective_state(VAD(0, 0, 0), events, as_of=target)
    for minute in range(1, 37):
        derive_effective_state(
            VAD(0, 0, 0), events, as_of=started + timedelta(minutes=minute)
        )
    assert derive_effective_state(VAD(0, 0, 0), events, as_of=target) == direct


@pytest.mark.parametrize("minutes", [10, 60, 360, 1440])
def test_unchanged_reappraisal_preserves_decay_even_when_repeated(minutes: int) -> None:
    now = datetime(2026, 9, 21, tzinfo=UTC)
    event = StoredAffectiveEvent(
        now,
        (
            StoredEmotionComponent(
                _component(EmotionFamily.SADNESS, intensity=85), 21600
            ),
        ),
        uuid7(),
        core=StoredCoreAffect(VAD(-70, 20, -85), 85, 21600),
    )
    reappraisals = tuple(
        replace(
            event,
            occurred_at=now + timedelta(minutes=minute),
            transition=AppraisalTransition.REAPPRAISE,
        )
        for minute in [10, 20, 30]
    )
    at = now + timedelta(minutes=minutes)
    assert derive_effective_snapshot(
        VAD(0, 0, 0), (event, *reappraisals), as_of=at
    ) == (derive_effective_snapshot(VAD(0, 0, 0), (event,), as_of=at))


def test_coping_reappraisal_changes_control_without_adding_sadness() -> None:
    loss = _semantic_event(
        concerns=(
            AppraisalConcern(
                AppraisalConcernTarget.SELF_GOAL,
                AppraisalSignificance.CORE,
                AppraisalDirection.MAJOR_SETBACK,
            ),
        ),
        quality=AppraisalQuality.UNPLEASANT,
        coping=AppraisalCoping(
            AppraisalResponseAccess.NONE,
            AppraisalPowerBalance.OVERMATCHED,
            AppraisalAdjustment.DIFFICULT,
        ),
    )
    _, stored, _ = _event_snapshot(loss)
    changed = replace(
        loss,
        transition=AppraisalTransition.REAPPRAISE,
        previous_episode_id=stored.episode_id,
        change_from_previous=AppraisalTrajectory.UNCHANGED,
        appraisal=replace(
            loss.appraisal,
            coping=AppraisalCoping(
                AppraisalResponseAccess.DIRECT,
                AppraisalPowerBalance.BALANCED,
                AppraisalAdjustment.EASY,
            ),
        ),
    )
    derived = derive_semantic_appraisal(changed, previous=loss)
    later = replace(
        stored,
        occurred_at=stored.occurred_at + timedelta(minutes=10),
        transition=changed.transition,
        core=derived.core,
        components=derived.components,
    )
    before = derive_effective_snapshot(VAD(0, 0, 0), (stored,), as_of=later.occurred_at)
    after = derive_effective_snapshot(
        VAD(0, 0, 0), (stored, later), as_of=later.occurred_at
    )
    assert after[0].dominance > before[0].dominance
    assert after[0].valence == before[0].valence
    assert after[1] == before[1]
    assert after[2] == before[2]


@pytest.mark.parametrize("separate_episode", [False, True])
def test_new_stimulus_can_still_increase_affect(separate_episode: bool) -> None:
    now = datetime(2026, 9, 21, tzinfo=UTC)
    event = StoredAffectiveEvent(
        now,
        (StoredEmotionComponent(_component(intensity=30), 3600),),
        uuid7(),
        core=StoredCoreAffect(VAD(60, 20, 0), 30, 3600),
    )
    later = replace(
        event,
        occurred_at=now + timedelta(minutes=10),
        episode_id=uuid7() if separate_episode else event.episode_id,
        transition=AppraisalTransition.NEW
        if separate_episode
        else AppraisalTransition.REINFORCE,
    )
    baseline = derive_effective_snapshot(
        VAD(0, 0, 0), (event,), as_of=later.occurred_at
    )
    actual = derive_effective_snapshot(
        VAD(0, 0, 0), (event, later), as_of=later.occurred_at
    )
    assert actual[0].valence > baseline[0].valence
    assert actual[1][0].intensity > baseline[1][0].intensity
    assert len(actual[2]) == (2 if separate_episode else 1)


def test_reappraisal_leaves_fading_anger_without_duplicating_unchanged_sadness() -> (
    None
):
    now = datetime(2026, 9, 21, tzinfo=UTC)
    sadness = StoredEmotionComponent(
        _component(EmotionFamily.SADNESS, intensity=50), 3600
    )
    anger = StoredEmotionComponent(_component(EmotionFamily.ANGER, intensity=40), 3600)
    event = StoredAffectiveEvent(
        now, (sadness, anger), uuid7(), core=StoredCoreAffect(VAD(-60, 20, 0), 60, 3600)
    )
    clarified = replace(
        event,
        occurred_at=now + timedelta(minutes=10),
        components=(sadness,),
        transition=AppraisalTransition.REAPPRAISE,
    )
    at = clarified.occurred_at
    baseline = derive_effective_state(VAD(0, 0, 0), (event,), as_of=at)
    assert (
        derive_effective_state(VAD(0, 0, 0), (event, clarified), as_of=at) == baseline
    )
    at += timedelta(minutes=30)
    before = {
        e.family: e.intensity
        for e in derive_effective_state(VAD(0, 0, 0), (event,), as_of=at)[1]
    }
    after = {
        e.family: e.intensity
        for e in derive_effective_state(VAD(0, 0, 0), (event, clarified), as_of=at)[1]
    }
    assert after[EmotionFamily.SADNESS] == before[EmotionFamily.SADNESS]
    assert 0 < after[EmotionFamily.ANGER] < before[EmotionFamily.ANGER]


def test_returning_emotion_replaces_its_residual_and_leaves_other_episode_alone() -> (
    None
):
    now = datetime(2026, 9, 21, tzinfo=UTC)
    anger = StoredEmotionComponent(_component(EmotionFamily.ANGER, intensity=40), 3600)
    event = StoredAffectiveEvent(
        now, (anger,), uuid7(), core=StoredCoreAffect(VAD(-60, 20, 0), 60, 3600)
    )
    other = replace(
        event,
        episode_id=uuid7(),
        components=(
            StoredEmotionComponent(_component(EmotionFamily.JOY, intensity=25), 3600),
        ),
    )
    cleared = replace(
        event,
        occurred_at=now + timedelta(minutes=10),
        components=(),
        transition=AppraisalTransition.REAPPRAISE,
        core=StoredCoreAffect(VAD(0, 0, 0), 0, 3600),
    )
    returned = replace(
        event,
        occurred_at=now + timedelta(minutes=20),
        transition=AppraisalTransition.REAPPRAISE,
    )
    history = (event, other, cleared, returned)
    actual = derive_effective_snapshot(
        VAD(0, 0, 0), history, as_of=returned.occurred_at
    )
    fresh = derive_effective_snapshot(
        VAD(0, 0, 0), (other, returned), as_of=returned.occurred_at
    )
    assert actual == fresh
    assert {e.family: e.intensity for e in actual[1]}[EmotionFamily.ANGER] == 40


@pytest.mark.parametrize("revised_strength,expected", [(30, 15), (90, 45)])
def test_reappraisal_changes_existing_strength_without_refreshing_elapsed_time(
    revised_strength: int, expected: int
) -> None:
    now = datetime(2026, 9, 21, tzinfo=UTC)
    original = StoredAffectiveEvent(
        now,
        (StoredEmotionComponent(_component(intensity=60), 3600),),
        uuid7(),
        core=StoredCoreAffect(VAD(60, 20, 0), 60, 3600),
    )
    revised = replace(
        original,
        occurred_at=now + timedelta(hours=1),
        transition=AppraisalTransition.REAPPRAISE,
        core=replace(original.core, intensity=revised_strength),
        components=(
            StoredEmotionComponent(_component(intensity=revised_strength), 3600),
        ),
    )
    result = derive_effective_snapshot(
        VAD(0, 0, 0), (original, revised), as_of=revised.occurred_at
    )
    assert result[1][0].intensity == expected
    assert result[2][0].intensity == expected


def _event_snapshot(event: SemanticAppraisalEvent):
    derived = derive_semantic_appraisal(event)
    now = datetime(2026, 9, 21, tzinfo=UTC)
    stored = StoredAffectiveEvent(now, derived.components, uuid7(), core=derived.core)
    return (
        derived,
        stored,
        derive_effective_snapshot(VAD(0, 0, 0), (stored,), as_of=now),
    )


@pytest.mark.parametrize(
    "direction,quality,sign",
    [
        (AppraisalDirection.FULFILLED, AppraisalQuality.PLEASANT, 1),
        (AppraisalDirection.SETBACK, AppraisalQuality.UNPLEASANT, -1),
    ],
)
def test_small_events_have_weaker_but_nonzero_affect(direction, quality, sign):
    strengths = []
    for significance in (
        AppraisalSignificance.PERIPHERAL,
        AppraisalSignificance.DIRECT,
        AppraisalSignificance.CORE,
    ):
        derived, _, snapshot = _event_snapshot(
            _semantic_event(
                concerns=(
                    AppraisalConcern(
                        AppraisalConcernTarget.SELF_GOAL, significance, direction
                    ),
                ),
                quality=quality,
            )
        )
        assert derived.components
        assert sign * snapshot[0].valence > 0
        strengths.append(derived.core.intensity)
    assert 0 < strengths[0] < strengths[1] < strengths[2]


def test_coping_changes_control_not_whether_loss_can_hurt():
    values = []
    for coping in (
        AppraisalCoping(
            AppraisalResponseAccess.NONE,
            AppraisalPowerBalance.OVERMATCHED,
            AppraisalAdjustment.DIFFICULT,
        ),
        AppraisalCoping(
            AppraisalResponseAccess.DIRECT,
            AppraisalPowerBalance.BALANCED,
            AppraisalAdjustment.EASY,
        ),
    ):
        derived, _, snapshot = _event_snapshot(
            _semantic_event(
                concerns=(
                    AppraisalConcern(
                        AppraisalConcernTarget.SELF_GOAL,
                        AppraisalSignificance.CORE,
                        AppraisalDirection.MAJOR_SETBACK,
                    ),
                ),
                quality=AppraisalQuality.UNPLEASANT,
                coping=coping,
            )
        )
        assert EmotionFamily.SADNESS in {x.component.family for x in derived.components}
        assert snapshot[0].valence < 0
        values.append(snapshot[0])
    assert values[0].valence == values[1].valence
    assert values[0].dominance < 0 < values[1].dominance


def test_event_affect_and_episode_do_not_depend_on_number_of_emotion_labels():
    _, stored, snapshot = _event_snapshot(_semantic_event())
    for components in ((), stored.components[:1], stored.components * 2):
        changed = derive_effective_snapshot(
            VAD(0, 0, 0),
            (replace(stored, components=components),),
            as_of=stored.occurred_at,
        )
        assert changed[0] == snapshot[0]
        assert changed[2] == snapshot[2]


def test_unclassified_experience_still_affects_mood_and_fades():
    derived, stored, snapshot = _event_snapshot(
        _semantic_event(
            concerns=(
                AppraisalConcern(
                    AppraisalConcernTarget.SELF_GOAL,
                    AppraisalSignificance.DIRECT,
                    AppraisalDirection.UNCHANGED,
                ),
            ),
            quality=AppraisalQuality.UNPLEASANT,
        )
    )
    assert derived.components == ()
    assert snapshot[0].valence < 0
    later = derive_effective_snapshot(
        VAD(0, 0, 0),
        (stored,),
        as_of=stored.occurred_at + timedelta(seconds=derived.core.half_life_seconds),
    )
    assert snapshot[0].valence < later[0].valence <= 0


def test_quiet_neutral_wait_does_not_invent_core_affect():
    derived, _, snapshot = _event_snapshot(
        _semantic_event(
            concerns=(
                AppraisalConcern(
                    AppraisalConcernTarget.SELF_GOAL,
                    AppraisalSignificance.DIRECT,
                    AppraisalDirection.UNCHANGED,
                ),
            ),
            quality=AppraisalQuality.NEUTRAL,
            phase=AppraisalEventPhase.ONGOING,
        )
    )
    assert derived.core.intensity == 0
    assert snapshot[0] == VAD(0, 0, 0)
    assert snapshot[1:] == ((), (), ())


def test_home_base_moves_at_most_two_points_per_axis() -> None:
    assert clamp_home_base(VAD(0, 0, 0), VAD(100, -100, 1)) == VAD(2, -2, 1)


def test_state_contract_is_current_and_rejects_extra_fields() -> None:
    state = parse_state(
        {
            "schema_version": "armi.mood.v5",
            "dynamics_version": "recency-reappraisal.v1",
            "derivation_version": "cpm-fuzzy.v4",
            "home_base": {"valence": 0, "arousal": 0, "dominance": 0},
        }
    )
    assert state_to_wire(state)["schema_version"] == "armi.mood.v5"
    with pytest.raises(MoodViolation):
        parse_state({**state_to_wire(state), "mood": "平静"})


def test_mood_projection_exposes_referenceable_episodes_and_bounded_recall_bias() -> (
    None
):
    source_id = uuid7()
    episode_ids = (uuid7(), uuid7(), uuid7())
    mood = rfc8785.dumps(
        {
            "schema_version": "armi.mood-snapshot.v2",
            "home_base": {"valence": 0, "arousal": 0, "dominance": 0},
            "current": {"valence": 10, "arousal": 20, "dominance": 0},
            "active_emotions": [],
            "active_episodes": [
                {
                    "episode_id": str(episode_id),
                    "gist": gist,
                    "event_phase": "ongoing",
                    "intensity": intensity,
                }
                for episode_id, gist, intensity in zip(
                    episode_ids,
                    ("甲" * 64, "乙" * 64, "低强度事件"),
                    (80, 60, 19),
                    strict=True,
                )
            ],
            "action_tendencies": [{"tendency": "explore", "intensity": 70}],
        }
    )
    payloads = (("mood", source_id, 3, mood),)
    episodes = active_mood_episodes(payloads)
    gists = active_mood_gists(payloads)
    assert tuple(item[0] for item in episodes) == episode_ids
    assert len(gists) == 2
    assert sum(map(len, gists)) == 128


def test_old_appraisal_contract_is_rejected_without_filling_fields() -> None:
    current = semantic_appraisal_to_wire(_semantic_event())
    previous = {**current, "schema_version": "armi.mood-appraisal.v2"}
    appraisal = current["appraisal"]
    assert isinstance(appraisal, dict)
    previous["appraisal"] = {
        key: value for key, value in appraisal.items() if key != "engagement"
    }
    with pytest.raises(MoodViolation):
        parse_semantic_appraisal(previous)
