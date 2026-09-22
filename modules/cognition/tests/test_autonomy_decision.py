import json

import pytest
from armi_cognition._autonomy_decision import should_consider_autonomy


@pytest.mark.parametrize(
    "kind,content,expected",
    [
        ("mind", {"assessed_objects": 10}, False),
        ("current_motivation", {"consideration": {"eligible": False}}, False),
        ("current_motivation", {"consideration": {"eligible": True}}, True),
        ("current_concern", {"consideration_reason": "ongoing_concern"}, False),
        ("current_concern", {"consideration_reason": "review_time_reached"}, True),
        ("current_activity", {"status": "active"}, True),
    ],
)
def test_local_check_respects_owner_conditions_and_formal_paths(
    kind, content, expected
):
    context = json.dumps(
        {"layers": [{"items": [{"item_kind": kind, "content": json.dumps(content)}]}]}
    ).encode()
    assert should_consider_autonomy(context) is expected


def test_empty_check_does_not_manufacture_a_subject_decision():
    assert not should_consider_autonomy(b'{"layers":[]}')
