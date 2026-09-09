import json
from pathlib import Path
from typing import cast
from uuid import uuid7

import pytest
from armi_kernel import load_yaml_file
from armi_local_control import ConfigurationViolation
from armi_local_control.configuration import load_effective_config
from armi_local_control.configuration.editing import EnvironmentConfiguration
from armi_local_control.maintenance import ConfigurationInvocation
from armi_runtime.composition.config_assets import runtime_config_path
from armi_runtime.composition.configuration_management import ConfigurationAsset

DEFAULTS = Path(__file__).resolve().parents[2] / "configs/runtime.yaml"


def editor(root: Path) -> EnvironmentConfiguration:
    (root / "environment.yaml").write_text(
        json.dumps(
            {
                "creator": {"port": 43123},
                "environment": {
                    "environment_id": str(uuid7()),
                    "data_root": str(root / "data"),
                },
            }
        ),
        encoding="utf-8",
    )
    return EnvironmentConfiguration(root, DEFAULTS)


def test_configuration_preview_apply_and_concurrent_version(tmp_path: Path) -> None:
    config = editor(tmp_path)
    before = config.read()
    preview = config.preview({"creator": {"port": 54321}}, before["version"])
    assert preview["activation"] == "not_saved"
    assert config.read()["version"] == before["version"]
    result = config.apply({"creator": {"port": 54321}}, before["version"])
    assert result["activation"] == "saved"
    assert result["restart_required"] is True
    assert (
        load_effective_config(
            defaults_path=DEFAULTS, environment_path=tmp_path / "environment.yaml"
        ).config.creator.port
        == 54321
    )
    with pytest.raises(ValueError, match="VERSION-CONFLICT"):
        config.apply({"creator": {"port": 54322}}, before["version"])


@pytest.mark.parametrize(
    "patch",
    [
        {"creator": {"port": -1}},
        {"unregistered": True},
        {"secret_locators": {"model": "plaintext-secret"}},
    ],
)
def test_invalid_configuration_never_saved(tmp_path: Path, patch: dict) -> None:
    config = editor(tmp_path)
    before = config.read()
    with pytest.raises(ConfigurationViolation):
        config.apply(patch, before["version"])
    assert config.read()["version"] == before["version"]


def test_environment_identity_cannot_be_patched(tmp_path: Path) -> None:
    config = editor(tmp_path)
    with pytest.raises(ValueError, match="IMMUTABLE"):
        config.preview(
            {"environment": {"environment_id": str(uuid7())}}, config.read()["version"]
        )


def test_model_override_is_consumed_and_conflict_does_not_overwrite(
    tmp_path: Path,
) -> None:
    config = ConfigurationAsset(
        ConfigurationInvocation(
            environment_root=tmp_path,
            environment_id=uuid7(),
            target="model-bindings",
            action="read",
        )
    )
    before = config.read()
    config.apply({"voice_binding": {"timeout_seconds": 20}}, before["version"])
    path = runtime_config_path("model-bindings.yaml", environment_root=tmp_path)
    assert path == tmp_path / "configs/model-bindings.yaml"
    assert (
        cast(dict[str, object], load_yaml_file(path)["voice_binding"])[
            "timeout_seconds"
        ]
        == 20
    )
    with pytest.raises(ValueError, match="VERSION-CONFLICT"):
        config.apply({"voice_binding": {"timeout_seconds": 25}}, before["version"])
    assert (
        cast(dict[str, object], load_yaml_file(path)["voice_binding"])[
            "timeout_seconds"
        ]
        == 20
    )


def test_new_device_configuration_uses_owner_validation(tmp_path: Path) -> None:
    config = ConfigurationAsset(
        ConfigurationInvocation(
            environment_root=tmp_path,
            environment_id=uuid7(),
            target="mood-display",
            action="read",
        )
    )
    before = config.read()
    assert before["configuration_state"] == "missing"
    config.apply(
        {
            "schema_version": "armi.mood-display-config.v1",
            "enabled": False,
            "port": "COM7",
            "expected_device_id": "test-display",
        },
        before["version"],
    )
    assert config.read()["values"]["expected_device_id"] == "test-display"
    with pytest.raises(ValueError):
        config.apply({"secret": "must-never-be-saved"}, config.read()["version"])
    assert "secret" not in config.read()["values"]
