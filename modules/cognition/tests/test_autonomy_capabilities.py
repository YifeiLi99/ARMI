import json

import pytest
from armi_cognition._autonomous_activity_contract import autonomous_schema_for_context
from armi_kernel.application import ModelViolation


def compiled(capabilities, *, outlet=True, outlet_state="ready"):
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
                                        "outlet_bound": outlet,
                                        "outlet_state": outlet_state,
                                        "policy": {
                                            "minimum_consideration_seconds": 120,
                                            "maximum_consideration_seconds": 3600,
                                        },
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
        assert properties["next_consideration_seconds"]["minimum"] == 120
        assert properties["next_consideration_seconds"]["maximum"] == 3600


def test_enabled_but_temporarily_unavailable_tools_remain_explicit_choices():
    schema = autonomous_schema_for_context(
        compiled(
            [
                {
                    "capability_kind": name,
                    "enabled": True,
                    "availability_status": "unavailable",
                }
                for name in ("web.search", "vision.screen", "life.query")
            ]
        )
    )
    assert {"web_research", "visual_observation", "exact_life_query"} <= schema[
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
    assert "no_result" in schema["discriminator"]["mapping"]
    for branch in schema["oneOf"]:
        properties = schema["$defs"][branch["$ref"].split("/")[-1]]["properties"]
        assert properties["expression"] == {"type": "null", "default": None}
        assert "next_consideration_seconds" in properties
