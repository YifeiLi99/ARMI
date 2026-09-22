from datetime import UTC, datetime

import pytest
from armi_mind.api import (
    GroundedObject,
    MindChoice,
    MindEvaluationTarget,
    MindVariable,
    mind_event_questions,
    parse_mind_event_answers,
)

NOW = datetime(2026, 9, 22, tzinfo=UTC)
TARGET = MindEvaluationTarget(GroundedObject("activity", "activity:1"), ("ctx:1",))


def answers_for(targets, *, selected="level_3", confidence=0.5):
    answers = {}
    for name, question in mind_event_questions(targets).items():
        choice = (
            "active"
            if name.endswith("_association")
            else "available"
            if name.endswith("_opportunity")
            else selected
        )
        answers[name] = {
            "type": "choice",
            "choice": choice,
            "confidence": confidence,
            "probabilities": {key: int(key == choice) for key in question["criteria"]},
        }
    return answers


def test_four_objects_share_bounded_questions_without_lifetime_cap():
    objects = tuple(
        MindEvaluationTarget(GroundedObject("activity", str(i)), (f"ctx:{i + 1}",))
        for i in range(5)
    )
    assert len(mind_event_questions(objects[:4])) == 72
    with pytest.raises(ValueError, match="window"):
        mind_event_questions(objects)
    assert len(mind_event_questions(objects[4:])) == 18
    assert mind_event_questions(()) == {}
    with pytest.raises(ValueError, match="window"):
        mind_event_questions((TARGET, TARGET))


def test_object_type_can_omit_inapplicable_questions():
    target = MindEvaluationTarget(
        TARGET.object,
        TARGET.basis_refs,
        (MindVariable.CONTACT_GAP, MindVariable.IMPORTANCE),
    )
    assert len(mind_event_questions((target,))) == 4
    (result,) = parse_mind_event_answers(
        answers_for((target,)), targets=(target,), evidence_key="e:1", at=NOW
    )
    assert result.object == TARGET.object
    assert result.basis_refs == ("ctx:1",)
    assert len(result.ratings) == 2


def test_probability_and_confidence_do_not_supply_intensity():
    (first,) = parse_mind_event_answers(
        answers_for((TARGET,), confidence=0.01),
        targets=(TARGET,),
        evidence_key="e:1",
        at=NOW,
    )
    (second,) = parse_mind_event_answers(
        answers_for((TARGET,), confidence=0.99),
        targets=(TARGET,),
        evidence_key="e:1",
        at=NOW,
    )
    assert first == second
    assert all(choice == MindChoice.HIGH for _, choice in first.ratings)


@pytest.mark.parametrize("choice", ["unknown", "not_applicable"])
def test_unknown_is_distinct_from_zero_and_inapplicable(choice):
    (result,) = parse_mind_event_answers(
        answers_for((TARGET,), selected=choice),
        targets=(TARGET,),
        evidence_key="e:1",
        at=NOW,
    )
    assert all(value == MindChoice(choice) for _, value in result.ratings)


@pytest.mark.parametrize(
    "corruption",
    ["missing", "extra", "nan", "bool", "wrong_winner", "wrong_type", "bad_sum"],
)
def test_malformed_answers_rejected(corruption):
    answers = answers_for((TARGET,))
    key = next(iter(answers))
    if corruption == "missing":
        answers.pop(key)
    elif corruption == "extra":
        answers["invented"] = answers[key]
    elif corruption == "nan":
        answers[key]["confidence"] = float("nan")
    elif corruption == "bool":
        answers[key]["confidence"] = True
    elif corruption == "wrong_winner":
        answers[key]["choice"] = "level_0"
    elif corruption == "wrong_type":
        answers[key]["type"] = "score"
    else:
        answers[key]["probabilities"]["level_3"] = 0.2
    with pytest.raises(ValueError, match="MIND-JEV-CONTRACT"):
        parse_mind_event_answers(answers, targets=(TARGET,), evidence_key="e:1", at=NOW)
