import json
import logging

import pytest
from armi_cognition._autonomy_decision import parse_autonomy_check
from armi_kernel.application import ModelViolation


def response(choice):
    return {
        "answers": {
            "engage": {
                "type": "choice",
                "choice": choice,
                "confidence": 0.6,
                "probabilities": {"engage": 0.3, "wait": 0.6, "unknown": 0.1},
            }
        }
    }


@pytest.mark.parametrize("choice,expected", [("engage", True), ("wait", False)])
def test_consumes_jev_choice_without_probability_veto(caplog, choice, expected):
    with caplog.at_level(logging.INFO):
        assert parse_autonomy_check(json.dumps(response(choice)).encode()) is expected
    record = next(
        record
        for record in caplog.records
        if record.armi_event == "autonomy.check.evaluated"
    )
    assert record.armi_details["reason"] == "jev_" + choice


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
