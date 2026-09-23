"""Replay successful synthetic Jev recordings through the production Mind ports.

These fixtures protect consumption and state behavior, not live model accuracy.
Expected ranges were frozen before the experiments; see DESIGN's Mind validation.
"""

import json
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from armi_cognition.api import EventAppraisalRequest
from armi_mind.api import (
    GroundedObject,
    MindEvaluationTarget,
    MindVariable,
    derive_mind,
    mind_condition_eligible,
    parse_mind_event_answers,
    project_mind_object,
    update_mind_object,
)

pytestmark = pytest.mark.test_group("mind", "cognition")
FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "mind"
START = datetime(2026, 9, 22, tzinfo=UTC)


def load(name):
    return json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))


def target_for(case):
    return MindEvaluationTarget(
        GroundedObject(case["kind"], case["ref"]),
        (case["ref"],),
        tuple(
            variable
            for variable in MindVariable
            if case["kind"] != "activity" or variable != MindVariable.CONTACT_GAP
        ),
    )


@pytest.mark.parametrize("batch", ["original", "mixed", "continuous", "boundaries"])
def test_recorded_dialogues_preserve_state_and_consideration_behavior(batch):
    recording = load(batch)
    assert recording["synthetic"] is True
    assert len(recording["cases"]) == 10
    states, consumed = {}, {}
    for index, item in enumerate(recording["cases"]):
        case = item["case"]
        target = target_for(case)
        at = START + timedelta(minutes=10 * index)
        raw = item["response"]["answers"]
        # Keep actual choice, confidence and probabilities intact, including
        # disagreement between choice and probability ranking.
        (evidence,) = parse_mind_event_answers(
            raw, targets=(target,), evidence_key=f"recorded:{batch}:{index}", at=at
        )
        state = update_mind_object(evidence, previous=states.get(target.object))
        states[target.object] = state
        for variable, choices in case["choices"].items():
            assert raw[f"mind_0_{variable}"]["choice"] in choices, case["id"]
        derived = asdict(derive_mind(state.variables))
        for metric, expected in case["outputs"].items():
            actual = derived[metric]
            if expected is None:
                assert actual is None, (case["id"], metric)
            else:
                assert actual is not None, (case["id"], metric)
                assert expected[0] <= actual <= expected[1], (case["id"], metric)
        versions = consumed.setdefault(target.object, set())
        eligible = mind_condition_eligible(state, consumed_versions=frozenset(versions))
        if "eligible" in case:
            assert eligible == case["eligible"], case["id"]
        projection = project_mind_object(
            state, at=at, consumed_versions=frozenset(versions)
        )
        consideration = projection["consideration"]
        assert isinstance(consideration, dict)
        assert consideration["eligible"] == eligible
        assert update_mind_object(evidence, previous=state) is state
        assert (
            project_mind_object(state, at=at, consumed_versions=frozenset(versions))
            == projection
        )
        if eligible:
            versions.add(state.condition_version)
        assert not mind_condition_eligible(state, consumed_versions=frozenset(versions))


def test_shared_cognition_request_uses_the_live_validated_mind_questions():
    recorded = load("validated_questions")
    request = EventAppraisalRequest(
        evidence_key="validated-prompt",
        event_id="synthetic-event",
        at=START,
        situations=(),
        goals=(),
        mind_targets=(target_for(recorded["case"]),),
    )
    actual = {
        key: value
        for key, value in request.questions().items()
        if key.startswith("mind_")
    }
    # A changed prompt requires a fresh semantic experiment; copying a snapshot
    # from current production without re-evaluation would erase this safeguard.
    assert actual == recorded["questions"]
