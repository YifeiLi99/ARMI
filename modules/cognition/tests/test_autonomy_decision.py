import json
import logging

import pytest
from armi_cognition._autonomy_decision import parse_autonomy_check
from armi_kernel.application import AutonomyCategory, ModelViolation


def response(choice):
    return {
        "answers": {
            "category": {
                "type": "choice",
                "choice": choice,
                "confidence": 0.6,
                "probabilities": {
                    "wake": 0.4,
                    "wait": 0.5,
                    "unknown": 0.1,
                },
            }
        }
    }


@pytest.mark.parametrize("choice", list(AutonomyCategory))
def test_consumes_jev_choice_without_probability_veto(caplog, choice):
    with caplog.at_level(logging.INFO):
        assert parse_autonomy_check(json.dumps(response(choice)).encode()) is choice
    record = next(
        record
        for record in caplog.records
        if record.armi_event == "autonomy.check.evaluated"
    )
    assert record.armi_details["reason"] == "jev_" + choice
    assert record.armi_details["category"] == choice


def test_unknown_is_not_a_decision_to_wait():
    with pytest.raises(ModelViolation, match="MODEL-JEV-CHECK-UNDETERMINED"):
        parse_autonomy_check(json.dumps(response("unknown")).encode())


@pytest.mark.parametrize(
    "raw",
    [
        b"broken",
        b"{}",
        b"null",
        b'{"answers":[]}',
        json.dumps(response("invented")).encode(),
    ],
)
def test_invalid_response_does_not_become_silence(raw):
    with pytest.raises(ModelViolation, match="MODEL-JEV-CHECK-CONTRACT"):
        parse_autonomy_check(raw)
