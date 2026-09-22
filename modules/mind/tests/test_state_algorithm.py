from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any, cast

import pytest
from armi_mind.api import (
    MIND_PARAMETERS,
    Association,
    GroundedObject,
    MindChoice,
    MindEvidence,
    MindVariable,
    Opportunity,
    derive_mind,
    mind_attention_weight,
    mind_condition_eligible,
    project_mind_object,
    update_mind_object,
)

NOW = datetime(2026, 9, 22, tzinfo=UTC)
OBJECT = GroundedObject("activity", "test-activity")


def test_projection_keeps_domains_evidence_quality_and_read_only_time():
    state = update_mind_object(evidence(contact_gap="level_3", importance="level_4"))
    view = cast(
        dict[str, Any],
        project_mind_object(state, at=NOW, consumed_versions=frozenset()),
    )
    assert view["object"] == {"source_kind": "activity", "source_ref": "test-activity"}
    assert view["domains"]["relatedness"]["contact_need"] == 75
    uncertain = update_mind_object(
        evidence(key="2", contact_gap="unknown"), previous=state
    )
    view = cast(
        dict[str, Any],
        project_mind_object(uncertain, at=NOW, consumed_versions=frozenset()),
    )
    relatedness = view["domains"]["relatedness"]
    assert relatedness["contact_need"] is None
    assert relatedness["contact_gap"]["value"] == 75
    assert relatedness["contact_gap"]["quality"] == "unknown"
    assert relatedness["contact_gap"]["basis_refs"] == ["ctx:1"]
    assert not view["consideration"]["eligible"]


def evidence(*, key="event:1", minutes=0, opportunity=Opportunity.AVAILABLE, **values):
    return MindEvidence(
        OBJECT,
        key,
        ("ctx:1",),
        NOW + timedelta(minutes=minutes),
        tuple((MindVariable(k), MindChoice(v)) for k, v in values.items()),
        Association.ACTIVE,
        opportunity,
    )


def test_satisfaction_and_frustration_coexist_without_time_creating_needs():
    state = update_mind_object(
        evidence(
            autonomy_satisfaction="level_4",
            autonomy_frustration="level_3",
            importance="level_4",
        )
    )
    values = {v.variable: v.value for v in state.variables}
    assert values[MindVariable.AUTONOMY_SATISFACTION] == 1
    assert values[MindVariable.AUTONOMY_FRUSTRATION] == 0.75
    initial = derive_mind(state.variables)
    assert mind_attention_weight(
        state, at=NOW + timedelta(minutes=30)
    ) == pytest.approx(0.375)
    for minute in range(60):
        mind_attention_weight(state, at=NOW + timedelta(minutes=minute))
    assert derive_mind(state.variables) == initial


def test_repetition_does_not_recharge_or_trigger_again():
    first = evidence(autonomy_frustration="level_4", importance="level_4")
    state = update_mind_object(first)
    assert update_mind_object(first, previous=state) is state
    assert mind_condition_eligible(state, consumed_versions=frozenset())
    for minute in range(1, 120):
        state = update_mind_object(
            replace(
                first,
                evidence_key=f"event:{minute + 1}",
                at=NOW + timedelta(minutes=minute),
            ),
            previous=state,
        )
        assert not mind_condition_eligible(state, consumed_versions=frozenset({1}))
    assert state.condition_version == 1
    assert state.salient_at == NOW


def test_unknown_preserves_evidence_but_cannot_trigger():
    state = update_mind_object(evidence(contact_gap="level_4", importance="level_4"))
    uncertain = update_mind_object(
        evidence(
            key="event:2",
            minutes=1,
            contact_gap="unknown",
            importance="level_4",
        ),
        previous=state,
    )
    contact = next(
        v for v in uncertain.variables if v.variable == MindVariable.CONTACT_GAP
    )
    assert contact.value == 1 and contact.known_at == NOW
    assert contact.quality == MindChoice.UNKNOWN
    assert derive_mind(uncertain.variables).contact_need is None
    assert not mind_condition_eligible(uncertain, consumed_versions=frozenset())
    empty = update_mind_object(evidence(contact_gap="unknown", importance="unknown"))
    assert derive_mind(empty.variables).priority is None


def test_unknown_inputs_remain_unknown_when_known_evidence_determines_formula():
    noise = update_mind_object(
        evidence(
            comprehensibility="level_0", information_gap="unknown", novelty="level_4"
        )
    )
    assert derive_mind(noise.variables).exploration == 0
    assert (
        next(
            v for v in noise.variables if v.variable == MindVariable.INFORMATION_GAP
        ).value
        is None
    )
    meaningless = update_mind_object(
        evidence(meaning="level_0", overload="unknown", importance="level_4")
    )
    assert derive_mind(meaningless.variables).engagement_adjustment == 1
    assert derive_mind(meaningless.variables).engagement_fit == 0
    assert mind_condition_eligible(meaningless, consumed_versions=frozenset())
    # Partial known overload does not determine the result of max(U, O).
    partial = update_mind_object(
        evidence(meaning="level_3", overload="level_3", understimulation="unknown")
    )
    assert derive_mind(partial.variables).engagement_adjustment is None


def test_rearm_material_change_and_opportunity_restoration():
    state = update_mind_object(evidence(contact_gap="level_3", importance="level_4"))
    state = update_mind_object(evidence(key="2", contact_gap="level_4"), previous=state)
    assert state.condition_version == 2
    state = update_mind_object(evidence(key="3", contact_gap="level_1"), previous=state)
    assert state.armed
    state = update_mind_object(evidence(key="4", contact_gap="level_3"), previous=state)
    assert state.condition_version == 3
    waiting = update_mind_object(
        evidence(key="5", opportunity=Opportunity.LATER), previous=state
    )
    assert not mind_condition_eligible(waiting, consumed_versions=frozenset())
    restored = update_mind_object(evidence(key="6"), previous=waiting)
    assert restored.condition_version == 4
    assert restored.condition_reason == "opportunity_restored"


def test_due_review_is_explicit_and_one_time():
    state = update_mind_object(evidence(contact_gap="level_4", importance="level_4"))
    state = update_mind_object(
        evidence(key="2"), previous=state, due_review_key="review:1"
    )
    assert state.condition_version == 2
    state = update_mind_object(
        evidence(key="3"), previous=state, due_review_key="review:1"
    )
    assert state.condition_version == 2


@pytest.mark.parametrize(
    "values,expected",
    [
        (
            {
                "information_gap": "level_3",
                "comprehensibility": "level_4",
                "information_value": "level_4",
                "learning_progress": "unknown",
                "novelty": "unknown",
            },
            0.75,
        ),
        (
            {
                "information_gap": "level_4",
                "comprehensibility": "level_4",
                "information_value": "level_0",
                "learning_progress": "level_2",
                "novelty": "unknown",
            },
            0.5,
        ),
        (
            {
                "information_gap": "unknown",
                "comprehensibility": "unknown",
                "information_value": "level_0",
                "learning_progress": "level_0",
                "novelty": "level_0",
            },
            0.0,
        ),
        (
            {
                "information_gap": "level_4",
                "comprehensibility": "level_4",
                "information_value": "unknown",
                "learning_progress": "level_2",
                "novelty": "level_0",
            },
            None,
        ),
    ],
)
def test_exploration_uses_only_mathematically_determined_unknown_completions(
    values, expected
):
    state = update_mind_object(evidence(**values))
    assert derive_mind(state.variables).exploration == expected
    for variable in state.variables:
        if values[variable.variable.value] == "unknown":
            assert variable.quality == MindChoice.UNKNOWN
            assert variable.value is None


def test_material_change_after_unknown_uses_last_trigger_evidence():
    first = update_mind_object(evidence(contact_gap="level_4", importance="level_4"))
    uncertain = update_mind_object(
        evidence(key="2", contact_gap="unknown"), previous=first
    )
    changed = update_mind_object(
        evidence(key="3", contact_gap="level_3"), previous=uncertain
    )
    assert changed.condition_version == 2
    assert changed.condition_reason == "material_change"
    assert mind_condition_eligible(changed, consumed_versions=frozenset({1}))


def test_rearm_requires_strictly_below_threshold():
    parameters = replace(MIND_PARAMETERS, rearm_threshold=0.375)
    first = update_mind_object(
        evidence(contact_gap="level_4", importance="level_3"), parameters=parameters
    )
    equal = update_mind_object(
        evidence(key="2", contact_gap="level_2"), previous=first, parameters=parameters
    )
    assert not equal.armed
    lower = update_mind_object(
        evidence(key="3", contact_gap="level_1"), previous=equal, parameters=parameters
    )
    assert lower.armed


def test_unknown_high_motive_cannot_rearm_from_an_unrelated_known_zero():
    state = update_mind_object(
        evidence(
            contact_gap="level_4",
            importance="level_4",
            autonomy_frustration="level_0",
        )
    )
    uncertain = update_mind_object(
        evidence(key="2", contact_gap="unknown"), previous=state
    )
    assert not uncertain.armed
    recovered = update_mind_object(
        evidence(key="3", contact_gap="level_4"), previous=uncertain
    )
    assert recovered.condition_version == 1
    assert not mind_condition_eligible(recovered, consumed_versions=frozenset({1}))


def test_unknown_cannot_block_rearm_when_its_formula_is_determined():
    first = update_mind_object(
        evidence(
            contact_gap="level_4",
            importance="level_4",
            information_gap="level_0",
            comprehensibility="unknown",
            information_value="unknown",
            learning_progress="unknown",
            novelty="unknown",
        )
    )
    lower = update_mind_object(evidence(key="2", contact_gap="level_1"), previous=first)
    assert derive_mind(lower.variables).exploration == 0
    assert lower.armed
    restored = update_mind_object(
        evidence(key="3", contact_gap="level_4"), previous=lower
    )
    assert restored.condition_version == 2


def test_object_isolation_stale_evidence_and_source_invalidation():
    state = update_mind_object(evidence(contact_gap="level_4", importance="level_4"))
    with pytest.raises(ValueError, match="another object"):
        update_mind_object(
            replace(evidence(key="2"), object=GroundedObject("party", "other")),
            previous=state,
        )
    with pytest.raises(ValueError, match="stale"):
        update_mind_object(evidence(key="2", minutes=-1), previous=state)
    invalid = update_mind_object(
        replace(evidence(key="2"), association=Association.INVALID), previous=state
    )
    assert not mind_condition_eligible(invalid, consumed_versions=frozenset())
    assert mind_attention_weight(invalid, at=NOW) == 0


@pytest.mark.parametrize(
    "values,exploration,fit,adjustment,contact",
    [
        # Chosen, meaningful solitude does not create a contact need or boredom.
        (
            {
                "meaning": "level_4",
                "understimulation": "level_0",
                "overload": "level_0",
                "contact_gap": "level_0",
            },
            None,
            1,
            0,
            0,
        ),
        # Company does not prevent an activity from lacking engagement.
        (
            {
                "relatedness_satisfaction": "level_4",
                "meaning": "level_1",
                "understimulation": "level_4",
                "overload": "level_0",
            },
            None,
            0,
            1,
            None,
        ),
        # Meaning and overload are independent.
        (
            {
                "meaning": "level_4",
                "understimulation": "level_0",
                "overload": "level_3",
            },
            None,
            0.25,
            0.75,
            None,
        ),
        # A failed attempt may still support exploration through learning progress.
        (
            {
                "competence_frustration": "level_3",
                "information_gap": "level_4",
                "comprehensibility": "level_4",
                "information_value": "level_1",
                "learning_progress": "level_4",
                "novelty": "level_0",
            },
            1,
            None,
            None,
            None,
        ),
        # Unintelligible novelty alone cannot create exploration motivation.
        (
            {
                "information_gap": "level_4",
                "comprehensibility": "level_0",
                "information_value": "level_0",
                "learning_progress": "level_0",
                "novelty": "level_4",
            },
            0,
            None,
            None,
            None,
        ),
        # Understood new question with value is an exploration candidate.
        (
            {
                "information_gap": "level_4",
                "comprehensibility": "level_3",
                "information_value": "level_4",
                "learning_progress": "level_0",
                "novelty": "level_4",
            },
            0.75,
            None,
            None,
            None,
        ),
    ],
)
def test_frozen_causal_cases(values, exploration, fit, adjustment, contact):
    result = derive_mind(update_mind_object(evidence(**values)).variables)
    assert result.exploration == exploration
    assert result.engagement_fit == fit
    assert result.engagement_adjustment == adjustment
    assert result.contact_need == contact


def test_partial_resolution_then_end_does_not_accumulate_motivation():
    state = update_mind_object(
        evidence(
            importance="level_4",
            information_gap="level_4",
            comprehensibility="level_4",
            information_value="level_4",
            learning_progress="level_4",
            novelty="level_3",
        )
    )
    assert derive_mind(state.variables).exploration == 1
    state = update_mind_object(
        evidence(key="2", information_gap="level_2"), previous=state
    )
    assert derive_mind(state.variables).exploration == 0.5
    state = update_mind_object(
        replace(
            evidence(key="3", information_gap="level_0"),
            association=Association.SATISFIED,
        ),
        previous=state,
    )
    assert derive_mind(state.variables).exploration == 0
    assert not mind_condition_eligible(state, consumed_versions=frozenset())
