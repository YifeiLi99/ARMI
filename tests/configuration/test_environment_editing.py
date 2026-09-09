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


def test_invalid_runtime_configuration_can_be_diagnosed_and_repaired(
    tmp_path: Path,
) -> None:
    config = editor(tmp_path)
    values = load_yaml_file(config.path)
    values["creator"] = {"port": "invalid-private-value"}
    config.path.write_text(json.dumps(values), encoding="utf-8")
    broken = config.read()
    assert broken["configuration_state"] == "invalid"
    assert broken["values"] is None
    assert "invalid-private-value" not in json.dumps(broken)
    config.apply({"creator": {"port": 54321}}, broken["version"])
    assert config.read()["effective_on_next_start"]["creator"]["port"] == 54321


def test_invalid_yaml_read_preserves_version_without_disclosing_content(
    tmp_path: Path,
) -> None:
    config = editor(tmp_path)
    config.path.write_text("private_key: [private-content", encoding="utf-8")
    broken = config.read()
    assert broken["configuration_state"] == "invalid"
    assert broken["version"].startswith("sha256:")
    assert "private-content" not in json.dumps(broken)


def test_complete_candidate_repairs_invalid_yaml_without_changing_bound_identity(
    tmp_path: Path,
) -> None:
    config = editor(tmp_path)
    document = config.read()["values"]
    config = EnvironmentConfiguration(
        tmp_path, DEFAULTS, environment_id=document["environment"]["environment_id"]
    )
    config.path.write_text("invalid: [", encoding="utf-8")
    version = config.read()["version"]
    foreign = {
        **document,
        "environment": {**document["environment"], "environment_id": str(uuid7())},
    }
    with pytest.raises(ConfigurationViolation, match="IDENTITY"):
        config.apply({}, version, document=foreign)
    moved = {
        **document,
        "environment": {
            **document["environment"],
            "data_root": str(tmp_path / "other"),
        },
    }
    with pytest.raises(ConfigurationViolation, match="IDENTITY"):
        config.apply({}, version, document=moved)
    preview = config.preview({}, version, document=document)
    assert preview["activation"] == "not_saved"
    config.apply({}, version, document=document)
    assert config.read()["configuration_state"] == "configured"


def test_invalid_model_configuration_can_be_repaired(tmp_path: Path) -> None:
    config = ConfigurationAsset(
        ConfigurationInvocation(
            environment_root=tmp_path,
            environment_id=uuid7(),
            target="model-bindings",
            action="read",
        )
    )
    values = config.read()["values"]
    values["voice_binding"]["timeout_seconds"] = "invalid-private-value"
    config.path.parent.mkdir(parents=True)
    config.path.write_text(json.dumps(values), encoding="utf-8")
    broken = config.read()
    assert broken["configuration_state"] == "invalid"
    assert "invalid-private-value" not in json.dumps(broken)
    config.apply({"voice_binding": {"timeout_seconds": 20}}, broken["version"])
    assert config.read()["values"]["voice_binding"]["timeout_seconds"] == 20


@pytest.mark.parametrize(
    "patch",
    [
        {"voice_binding": {"unexpected": "secret-value"}},
        {"bindings": [{"provider": "incomplete"}]},
        {"external_content_recognition": {"output_token_limit": True}},
    ],
)
def test_complete_model_manifest_rejects_invalid_sections(
    tmp_path: Path, patch: dict
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
    with pytest.raises((ValueError, RuntimeError)):
        config.apply(patch, before["version"])
    assert not config.path.exists()


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
