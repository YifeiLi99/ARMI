"""Upgrade only obsolete autonomy fields while preserving installed choices."""

import json
from pathlib import Path
from typing import Any, cast
from uuid import uuid7

import pytest
from armi_admin.application.configuration_upgrade import (
    prepare_configuration_upgrade,
    publish_configuration_upgrade,
)
from armi_admin.application.installation import SetupError
from armi_kernel import load_yaml_file


def test_configuration_upgrade_preserves_credentials_and_model(tmp_path):
    defaults = Path("configs/runtime.yaml")
    environment = {
        "schema_version": "armi.runtime-config.v4",
        "environment": {"environment_id": str(uuid7()), "data_root": str(tmp_path)},
        "creator": {"port": 45678},
        "autonomy": {
            "enabled": False,
            "outlet": "creator_web",
            "daily_request_limit": 48,
            "minimum_consideration_seconds": 60,
            "maximum_consideration_seconds": 21600,
        },
        "secret_locators": {"model.deepseek_api_key": "env:ARMI_TEST_PRIVATE_KEY"},
    }
    path = tmp_path / "environment.yaml"
    path.write_text(json.dumps(environment), encoding="utf-8")
    manifest = cast(dict[str, Any], load_yaml_file(Path("configs/model-bindings.yaml")))
    manifest["schema_version"] = "armi.model-bindings.v3"
    del manifest["purpose_profiles"]["consider_autonomy_check"]
    manifest["purpose_profiles"]["consider_autonomous_life"][
        "response_contract_version"
    ] = "armi.autonomous-activity-candidate.v10"
    model_path = tmp_path / "configs/model-bindings.yaml"
    model_path.parent.mkdir()
    model_path.write_text(json.dumps(manifest), encoding="utf-8")
    before = path.read_bytes()
    changes = prepare_configuration_upgrade(tmp_path, defaults)
    assert path.read_bytes() == before
    assert len(changes) == 2
    publish_configuration_upgrade(changes)
    current = load_yaml_file(path)
    assert current["autonomy"] == {"enabled": False, "outlet": "creator_web"}
    assert current["secret_locators"] == environment["secret_locators"]
    model = cast(dict[str, Any], load_yaml_file(model_path))
    assert model["bindings"] == manifest["bindings"]
    assert model["active_binding"] == manifest["active_binding"]
    assert (
        model["purpose_profiles"]["consider_autonomy_check"]["output_token_limit"] == 64
    )
    assert prepare_configuration_upgrade(tmp_path, defaults) == []


def test_configuration_publication_detects_concurrent_write(tmp_path):
    path = tmp_path / "environment.yaml"
    path.write_bytes(b"new value")
    with pytest.raises(SetupError, match="CONFIG-CONFLICT"):
        publish_configuration_upgrade([(path, b"old value", {})])
    assert path.read_bytes() == b"new value"
