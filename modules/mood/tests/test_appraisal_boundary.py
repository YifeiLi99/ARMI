"""Provider certainty, missing evidence and emotional output stay separate."""

from copy import deepcopy

import pytest
from armi_mood.api import JEV_MODEL, appraisal_questions, parse_appraisal_response


def response(**choices):
    questions = appraisal_questions(())
    answers = {}
    for name, question in questions.items():
        choice = choices.get(name, "unknown")
        options = question["criteria"]
        answers[name] = {
            "type": "choice",
            "choice": choice,
            "confidence": 0.99,
            "probabilities": {key: int(key == choice) for key in options},
        }
    return {
        "model": JEV_MODEL,
        "answers": answers,
        "usage": {"input_tokens": 100, "output_tokens": 20},
    }


def test_unknown_not_applicable_and_zero_remain_distinct():
    parsed = parse_appraisal_response(
        response(gain="level_0", control="not_applicable"),
        event_id="one",
        situations=(),
    )
    assert parsed.appraisal.gain == 0
    assert parsed.appraisal.loss is None
    assert parsed.appraisal.control is None
    assert parsed.appraisal.not_applicable == ("control",)


def test_structured_questions_keep_goal_scopes_independent_and_roundtrip():
    questions = appraisal_questions(("old-situation",), ("goal-a", "goal-b"))
    # Jev evaluates questions independently; each must carry the same object scope.
    scope = questions["gain"]["instructions"]["评价对象"]
    assert all(q["instructions"]["评价对象"] == scope for q in questions.values())
    assert "目标范围" not in questions["gain"]["instructions"]
    assert "goal-a" in questions["goal_0_gain"]["instructions"]["目标范围"]
    assert "goal-b" not in questions["goal_0_gain"]["instructions"]["目标范围"]
    assert "goal-b" in questions["goal_1_phase"]["instructions"]["目标范围"]
    raw = response()
    for name, question in questions.items():
        choice = "old-situation" if name == "situation" else "unknown"
        raw["answers"][name] = {
            "type": "choice",
            "choice": choice,
            "confidence": 1,
            "probabilities": {
                option: int(option == choice) for option in question["criteria"]
            },
        }
    parsed = parse_appraisal_response(
        raw, event_id="new", situations=("old-situation",), goals=("goal-a", "goal-b")
    )
    assert parsed.situation_id == "old-situation"
    assert [goal.reference for goal in parsed.appraisal.goals] == ["goal-a", "goal-b"]


def test_provider_confidence_does_not_change_semantic_scores():
    raw = response(gain="level_3", likelihood="level_1")
    lower = deepcopy(raw)
    for answer in lower["answers"].values():
        answer["confidence"] = 0.01
    a = parse_appraisal_response(raw, event_id="one", situations=())
    b = parse_appraisal_response(lower, event_id="one", situations=())
    assert a.appraisal == b.appraisal
    assert a.appraisal.gain == 0.75
    assert a.appraisal.likelihood == 0.25
    assert a.answers != b.answers


@pytest.mark.parametrize(
    "chosen_probability,other_probability", [(0.37, 0.38), (0, 0.75)]
)
def test_provider_choice_is_used_even_when_another_probability_is_higher(
    chosen_probability, other_probability
):
    raw = response(gain="level_0")
    raw["answers"]["gain"]["probabilities"].update(
        level_0=chosen_probability, unknown=other_probability, not_applicable=0.25
    )
    original = deepcopy(raw)
    parsed = parse_appraisal_response(raw, event_id="one", situations=())
    assert parsed.appraisal.gain == 0
    assert parsed.answers == original["answers"]
    assert raw == original


def test_float_representation_tie_preserves_provider_choice_and_probabilities():
    raw = response(self_alignment="level_4")
    raw["answers"]["self_alignment"]["probabilities"].update(
        level_4=0.22999999999999998,
        level_3=0.23,
        level_2=0.20,
        level_1=0.18,
        unknown=0.16,
    )
    original = deepcopy(raw)
    parsed = parse_appraisal_response(raw, event_id="one", situations=())
    assert parsed.appraisal.self_alignment == 1
    assert parsed.answers == original["answers"]
    assert raw == original


def test_goal_unknown_and_not_applicable_are_preserved_separately():
    raw = response()
    for name, question in appraisal_questions((), ("goal-a",)).items():
        if not name.startswith("goal_"):
            continue
        choice = "not_applicable" if name.endswith("likelihood") else "unknown"
        raw["answers"][name] = {
            "type": "choice",
            "choice": choice,
            "confidence": 0.7,
            "probabilities": {key: int(key == choice) for key in question["criteria"]},
        }
    value = parse_appraisal_response(
        raw, event_id="one", situations=(), goals=("goal-a",)
    )
    assert value.appraisal.goals[0].not_applicable == ("likelihood",)
    assert value.appraisal.goals[0].gain is None


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), -0.1, 1.1, True, "0.5"])
def test_invalid_probability_is_rejected(bad):
    raw = response()
    raw["answers"]["gain"]["probabilities"]["unknown"] = bad
    with pytest.raises(ValueError, match="MOOD-JEV-CONTRACT"):
        parse_appraisal_response(raw, event_id="one", situations=())


@pytest.mark.parametrize(
    "mutation", ["missing", "emotion", "wrong_model", "invented_choice"]
)
def test_unusable_provider_result_is_not_repaired(mutation):
    raw = response()
    if mutation == "missing":
        del raw["answers"]["gain"]
    elif mutation == "emotion":
        raw["answers"]["sadness"] = 1
    elif mutation == "wrong_model":
        raw["model"] = "another-model"
    else:
        raw["answers"]["gain"]["choice"] = "invented"
    with pytest.raises(ValueError, match="MOOD-JEV-CONTRACT"):
        parse_appraisal_response(raw, event_id="one", situations=())
