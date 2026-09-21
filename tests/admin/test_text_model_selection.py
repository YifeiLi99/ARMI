"""Desktop selection uses the same versioned configuration transaction as CLI."""

from copy import deepcopy
from pathlib import Path
from typing import Any, cast
from unittest.mock import Mock

from armi_admin.desktop import Desktop
from armi_kernel import load_yaml_file


def test_provider_switch_is_one_versioned_patch_and_preserves_business_settings():
    current = cast(dict[str, Any], load_yaml_file(Path("configs/model-bindings.yaml")))
    before = deepcopy(current)
    desktop = object.__new__(Desktop)
    desktop.text_provider = Mock(get=Mock(return_value="deepseek"))
    desktop.text_model = Mock(get=Mock(return_value="deepseek-flash"))
    desktop.target = Mock()
    calls = []

    def admin(operation, arguments, callback=None):
        calls.append((operation, arguments))
        if arguments["action"] == "read":
            assert callback is not None
            callback(
                {
                    "status": "succeeded",
                    "result": {"version": "current-version", "values": current},
                }
            )

    desktop.admin = admin
    desktop._save_text_model()
    assert len(calls) == 2
    _, save = calls[1]
    assert save["expected_version"] == "current-version"
    assert save["target"] == "model-bindings"
    assert set(save["patch"]) == {"active_binding", "bindings"}
    assert save["patch"]["active_binding"] == "armi.model-adapter.deepseek-responses"
    row = save["patch"]["bindings"][0]
    assert row["provider"] == "deepseek" and row["model_id"] == "deepseek-flash"
    assert row["credential_locator"] == "model.deepseek_api_key"
    assert row["api_base"] == "https://api.deepseek.com"
    for key in (
        "input_token_limit",
        "output_token_limit",
        "response_contract_kind",
        "attempt_cost_limit_microyuan",
    ):
        assert row[key] == before["bindings"][0][key]
    assert current == before
