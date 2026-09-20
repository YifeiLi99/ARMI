import pytest
from armi_cognition._autonomy_check_contract import parse_autonomy_check
from armi_kernel.application import ModelViolation


@pytest.mark.parametrize("engage", [True, False])
def test_check_accepts_only_a_boolean_decision(engage: bool) -> None:
    assert parse_autonomy_check({"engage": engage}).engage is engage


@pytest.mark.parametrize(
    "value",
    [
        {},
        {"engage": 1},
        {"engage": "false"},
        {"engage": None},
        {"engage": True, "expression": ["hello"]},
        {"engage": False, "reason": "waiting"},
        {"candidate": {"engage": True}},
    ],
)
def test_check_does_not_coerce_or_accept_subject_actions(value: object) -> None:
    with pytest.raises(ModelViolation, match="MODEL-RESPONSE-SCHEMA"):
        parse_autonomy_check(value)
