"""Fixed primitive inputs isolate algorithm behavior from provider judgment."""

from datetime import UTC, datetime

import pytest
from armi_mind.api import (
    Association,
    GroundedObject,
    MindChoice,
    MindEvidence,
    MindVariable,
    Opportunity,
    derive_mind,
    mind_condition_eligible,
    update_mind_object,
)


def state(**levels):
    return update_mind_object(
        MindEvidence(
            GroundedObject("event", "synthetic"),
            "e:1",
            ("synthetic",),
            datetime(2026, 9, 22, tzinfo=UTC),
            tuple(
                (v, MindChoice(f"level_{levels.get(v.value, 0)}")) for v in MindVariable
            ),
            Association.ACTIVE,
            Opportunity.AVAILABLE,
        )
    )


@pytest.mark.parametrize(
    "levels,expected",
    [
        ({"meaning": 4}, (0, 1, 0)),  # Chosen fulfilling solitude or rest.
        ({"relatedness_satisfaction": 4, "understimulation": 4}, (0, 0, 1)),
        ({"meaning": 4, "overload": 4}, (0, 0, 1)),
        (
            {
                "information_gap": 4,
                "comprehensibility": 4,
                "learning_progress": 4,
                "competence_frustration": 4,
            },
            (1, 0, 1),
        ),
        ({"novelty": 4, "information_gap": 4}, (0, 0, 1)),
        (
            {"information_gap": 4, "comprehensibility": 4, "information_value": 4},
            (1, 0, 1),
        ),
    ],
)
def test_causal_inputs_have_fixed_expected_outputs(levels, expected):
    result = derive_mind(state(**levels).variables)
    assert (
        result.exploration,
        result.engagement_fit,
        result.engagement_adjustment,
    ) == expected


def test_frustration_never_invents_contact_and_satisfaction_does_not_cancel_it():
    chosen = state(
        autonomy_satisfaction=4, autonomy_frustration=0, importance=4, meaning=4
    )
    forced = state(
        autonomy_satisfaction=0,
        autonomy_frustration=4,
        competence_satisfaction=4,
        importance=4,
        meaning=4,
    )
    rejected = state(relatedness_frustration=4, importance=4, meaning=4)
    assert not mind_condition_eligible(chosen, consumed_versions=frozenset())
    assert mind_condition_eligible(forced, consumed_versions=frozenset())
    assert derive_mind(rejected.variables).contact_need == 0
