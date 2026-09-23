import json

import pytest
from armi_cognition._autonomous_activity_contract import (
    autonomous_instructions_for_context,
    autonomous_schema_for_context,
)
from armi_kernel.application import ModelViolation


def compiled(capabilities, *, outlet=True, outlet_state="ready", category=None):
    return json.dumps(
        {
            "layers": [
                {
                    "items": [
                        {
                            "item_kind": "capability_catalog",
                            "content": json.dumps({"capabilities": capabilities}),
                        },
                        {
                            "item_kind": "current_life_opportunity",
                            "content": json.dumps(
                                {
                                    "autonomy": {
                                        "category": category,
                                        "outlet_bound": outlet,
                                        "outlet_state": outlet_state,
                                        "policy": {"enabled": True, "outlet": "qq"},
                                    }
                                }
                            ),
                        },
                    ]
                }
            ]
        }
    ).encode()


def test_disabled_tools_have_no_schema_entry_and_outlet_is_explicit():
    schema = autonomous_schema_for_context(compiled([], outlet=False))
    actions = schema["discriminator"]["mapping"]
    assert (
        not {
            "web_research",
            "visual_observation",
            "exact_life_query",
            "codex_delegation",
        }
        & actions.keys()
    )
    for branch in schema["oneOf"]:
        properties = schema["$defs"][branch["$ref"].split("/")[-1]]["properties"]
        assert properties["expression"] == {"type": "null", "default": None}
        assert "next_consideration_seconds" not in properties


def test_enabled_but_temporarily_unavailable_tools_remain_explicit_choices():
    schema = autonomous_schema_for_context(
        compiled(
            [
                {
                    "capability_kind": name,
                    "enabled": True,
                    "availability_status": "unavailable",
                }
                for name in ("codex.delegated-work", "vision.screen", "life.query")
            ]
        )
    )
    assert {"codex_delegation", "visual_observation", "exact_life_query"} <= schema[
        "discriminator"
    ]["mapping"].keys()
    assert schema["$defs"]["AutonomousVisualObservationDecision"]["properties"][
        "source_kind"
    ]["enum"] == ["screen"]


def test_missing_frozen_capability_context_fails_before_model_request():
    with pytest.raises(ModelViolation, match="MODEL-AUTONOMY-CONTEXT"):
        autonomous_schema_for_context(b'{"layers": []}')


@pytest.mark.parametrize("state", ["disabled", "unbound", "unavailable"])
def test_unavailable_outlet_allows_thinking_without_queued_expression(state):
    schema = autonomous_schema_for_context(compiled([], outlet_state=state))
    assert "no_activity" in schema["discriminator"]["mapping"]
    assert "wait" not in schema["discriminator"]["mapping"]
    for branch in schema["oneOf"]:
        properties = schema["$defs"][branch["$ref"].split("/")[-1]]["properties"]
        assert properties["expression"] == {"type": "null", "default": None}
        assert "next_consideration_seconds" not in properties


def test_activity_work_needs_an_actual_activity_but_concerns_do_not():
    value = json.loads(compiled([]))
    empty = autonomous_schema_for_context(json.dumps(value).encode())
    actions = empty["discriminator"]["mapping"]
    assert {
        "no_activity",
        "defer",
        "need_information",
        "start_activity",
    } <= actions.keys()
    assert not {"wait", "progress", "complete", "abandon", "no_result"} & actions.keys()
    value["layers"][0]["items"].append(
        {"item_kind": "current_activity", "content": "{}"}
    )
    active = autonomous_schema_for_context(json.dumps(value).encode())
    assert {"wait", "progress", "complete", "abandon", "no_result"} <= active[
        "discriminator"
    ]["mapping"].keys()


def test_wake_does_not_choose_an_action_or_grant_permissions():
    context = compiled([], category="wake", outlet=False)
    instructions = autonomous_instructions_for_context(context)
    assert instructions == autonomous_instructions_for_context(
        compiled([], category=None)
    )
    schema = autonomous_schema_for_context(context)
    assert "codex_delegation" not in schema["discriminator"]["mapping"]
    for branch in schema["oneOf"]:
        assert schema["$defs"][branch["$ref"].split("/")[-1]]["properties"][
            "expression"
        ] == {"type": "null", "default": None}


@pytest.mark.parametrize("category", ["wait", "unknown", "explore", "invented"])
def test_non_action_or_invalid_category_cannot_enter_full_cognition(category):
    with pytest.raises(ModelViolation, match="MODEL-AUTONOMY-CATEGORY"):
        autonomous_instructions_for_context(compiled([], category=category))
