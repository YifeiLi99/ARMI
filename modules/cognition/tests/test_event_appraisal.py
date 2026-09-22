from datetime import UTC, datetime

import pytest
from armi_cognition.api import EventAppraisalRequest, parse_event_appraisal
from armi_mind.api import GroundedObject, MindEvaluationTarget
from armi_mood.api import JEV_MODEL, appraisal_questions

REQUEST = EventAppraisalRequest(
    "source:1:version:1",
    "event:1",
    datetime(2026, 9, 22, tzinfo=UTC),
    (),
    (),
    (MindEvaluationTarget(GroundedObject("activity", "activity:1"), ("ctx:1",)),),
)


def response(request=REQUEST):
    return {
        "model": JEV_MODEL,
        "usage": {"input_tokens": 100, "output_tokens": 20},
        "answers": {
            name: {
                "type": "choice",
                "choice": "unknown",
                "confidence": 1,
                "probabilities": {
                    option: int(option == "unknown") for option in question["criteria"]
                },
            }
            for name, question in request.questions().items()
        },
    }


def test_joint_questions_keep_mood_contract_exactly_unchanged():
    questions = REQUEST.questions()
    assert {
        key: value for key, value in questions.items() if not key.startswith("mind_")
    } == appraisal_questions(())
    result = parse_event_appraisal(response(), request=REQUEST)
    assert result.ready_for_cognition
    assert result.input_tokens == 100 and result.output_tokens == 20
    assert result.mind is not None and len(result.mind) == 1


@pytest.mark.parametrize("owner", ["mind", "mood"])
def test_one_invalid_owner_does_not_discard_valid_sibling(owner):
    raw = response()
    name = "mind_0_information_gap" if owner == "mind" else "gain"
    del raw["answers"][name]
    result = parse_event_appraisal(raw, request=REQUEST)
    assert not result.ready_for_cognition
    assert (result.mind is None) == (owner == "mind")
    assert (result.mood is None) == (owner == "mood")
    assert (result.mind_failure is not None) == (owner == "mind")
    assert (result.mood_failure is not None) == (owner == "mood")
    assert result.input_tokens == 100


def test_usage_failure_is_not_psychological_no_change():
    raw = response()
    raw["usage"]["input_tokens"] = -1
    with pytest.raises(ValueError, match="COGNITION-JEV-USAGE"):
        parse_event_appraisal(raw, request=REQUEST)


@pytest.mark.parametrize("owner", ["mind", "mood"])
def test_extra_keys_reject_only_the_responsible_owner(owner):
    raw = response()
    raw["answers"]["mind_invented" if owner == "mind" else "invented"] = raw["answers"][
        "gain"
    ]
    result = parse_event_appraisal(raw, request=REQUEST)
    assert (result.mind is None) == (owner == "mind")
    assert (result.mood is None) == (owner == "mood")


def test_empty_mind_window_is_explicit_valid_empty_result():
    request = EventAppraisalRequest("e:1", "e:1", REQUEST.at, (), (), ())
    result = parse_event_appraisal(response(request), request=request)
    assert result.mind == () and result.ready_for_cognition
