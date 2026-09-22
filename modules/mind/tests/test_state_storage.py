import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import uuid7

import pytest
from armi_mind._state_storage import (
    apply_mind_evidence,
    correct_numeric_mind,
    initial_numeric_mind_state,
    numeric_mind_state,
)
from armi_mind.api import (
    Association,
    GroundedObject,
    MindChoice,
    MindEvaluationTarget,
    MindEvidence,
    MindVariable,
    Opportunity,
    mind_event_questions,
    parse_mind_event_answers,
)


def test_due_review_survives_question_parser_and_persistent_owner_update():
    obj = GroundedObject("cognition_focus", str(uuid7()))
    target = MindEvaluationTarget(
        obj, (obj.source_ref,), due_review_key="commit:1:time:1"
    )
    answers = {}
    for name, question in mind_event_questions((target,)).items():
        choice = (
            "active"
            if name.endswith("_association")
            else "available"
            if name.endswith("_opportunity")
            else "level_4"
        )
        answers[name] = {
            "type": "choice",
            "choice": choice,
            "confidence": 1.0,
            "probabilities": {k: float(k == choice) for k in question["criteria"]},
        }
    at = datetime.now(UTC)

    def assessed(key, review):
        return parse_mind_event_answers(
            answers,
            targets=(replace(target, due_review_key=review),),
            evidence_key=key,
            at=at,
        )

    payload = apply_mind_evidence(initial_numeric_mind_state(), assessed("e:1", None))
    payload = apply_mind_evidence(payload, assessed("e:2", target.due_review_key))
    state = numeric_mind_state(payload).objects[0]
    assert state.condition_version == 2
    assert state.condition_reason == "review_time_reached"
    payload = apply_mind_evidence(payload, assessed("e:3", target.due_review_key))
    assert numeric_mind_state(payload).objects[0].condition_version == 2


def test_persistent_objects_are_independent_unbounded_and_corrections_recompute_conditions():
    now = datetime.now(UTC)
    payload = initial_numeric_mind_state()
    events = []
    for i in range(7):
        event = MindEvidence(
            GroundedObject("event", str(uuid7())),
            str(i),
            (str(uuid7()),),
            now,
            (
                (MindVariable.CONTACT_GAP, MindChoice.FULL),
                (MindVariable.IMPORTANCE, MindChoice.FULL),
            ),
            Association.ACTIVE,
            Opportunity.AVAILABLE,
        )
        events.append(event)
        payload = apply_mind_evidence(payload, (event,))
    before = numeric_mind_state(payload)
    assert len(before.objects) == 7
    assert apply_mind_evidence(payload, (events[0],)) == payload
    changed = apply_mind_evidence(
        payload,
        (
            replace(
                events[0],
                evidence_key="new",
                at=now + timedelta(seconds=1),
                ratings=((MindVariable.CONTACT_GAP, MindChoice.NONE),),
            ),
        ),
    )
    after = numeric_mind_state(changed)
    assert after.objects[1:] == before.objects[1:]
    forged = after.model_dump(mode="json")
    forged["objects"][0]["condition_version"] = 999
    corrected = numeric_mind_state(
        correct_numeric_mind(
            payload,
            json.dumps(forged).encode(),
            correction_id=uuid7(),
            at=now + timedelta(seconds=2),
        )
    )
    assert corrected.objects[0].condition_version == before.objects[0].condition_version
    assert corrected.objects[0].armed
    with pytest.raises(ValueError, match="SOURCE"):
        correct_numeric_mind(
            payload, initial_numeric_mind_state(), correction_id=uuid7(), at=now
        )


def test_unknown_object_can_be_corrected_using_its_formal_source_without_forged_history():
    now = datetime.now(UTC)
    event = MindEvidence(
        GroundedObject("event", str(uuid7())),
        "e",
        (str(uuid7()),),
        now,
        ((MindVariable.CONTACT_GAP, MindChoice.UNKNOWN),),
        Association.UNKNOWN,
        Opportunity.UNKNOWN,
    )
    state = numeric_mind_state(
        apply_mind_evidence(initial_numeric_mind_state(), (event,))
    )
    # An unchanged unknown correction remains unknown and cannot create a signal.
    result = numeric_mind_state(
        correct_numeric_mind(
            state.model_dump_json().encode(),
            state.model_dump_json().encode(),
            correction_id=uuid7(),
            at=now + timedelta(seconds=1),
        )
    )
    assert result.objects[0].variables[0].value is None
    assert result.objects[0].condition_version == 0
