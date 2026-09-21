"""Explicit stopped-environment configuration conversion for database v30."""

from __future__ import annotations

from pathlib import Path
from typing import Any, cast

from armi_kernel import load_yaml_mapping
from armi_local_control import write_control
from armi_local_control.configuration import ModelManifest, validate_environment_values
from armi_local_control.configuration.paths import has_reparse_point

from .installation import SetupError


def prepare_configuration_upgrade(
    root: Path,
    defaults: Path,
) -> list[tuple[Path, bytes, dict[str, Any]]]:
    """Prepare both conversions before database mutation; preserve all other values."""
    changes: list[tuple[Path, bytes, dict[str, Any]]] = []
    for relative in ("environment.yaml", "configs/model-bindings.yaml"):
        path = root / relative
        if relative.startswith("configs/") and not path.exists():
            continue
        if has_reparse_point(path, root=root):
            raise SetupError("SETUP-UPGRADE-CONFIG-PATH")
        original = path.read_bytes()
        values = cast(dict[str, Any], dict(load_yaml_mapping(original)))
        changed = False
        if relative == "environment.yaml":
            # Environment files may omit the version and inherit packaged defaults.
            if values.get("schema_version") in {None, "armi.runtime-config.v4"}:
                if "schema_version" in values:
                    values["schema_version"] = "armi.runtime-config.v5"
                    changed = True
                autonomy = values.get("autonomy", {})
                for key in (
                    "daily_request_limit",
                    "minimum_consideration_seconds",
                    "maximum_consideration_seconds",
                ):
                    if key in autonomy:
                        del autonomy[key]
                        changed = True
            validate_environment_values(defaults_path=defaults, values=values)
        else:
            if values.get("schema_version") == "armi.model-bindings.v3":
                profiles = values["purpose_profiles"]
                if (
                    profiles["consider_autonomous_life"]["response_contract_version"]
                    != "armi.autonomous-activity-candidate.v10"
                ):
                    raise SetupError("SETUP-UPGRADE-MODEL-CONTRACT")
                values["schema_version"] = "armi.model-bindings.v4"
                profiles["consider_autonomous_life"]["response_contract_version"] = (
                    "armi.autonomous-activity-candidate.v11"
                )
                profiles["consider_autonomy_check"] = {
                    "profile": "autonomy_check",
                    "response_contract_version": "armi.autonomy-check-candidate.v1",
                    "output_token_limit": 64,
                }
                changed = True
            ModelManifest.model_validate(values)
        if changed:
            changes.append((path, original, values))
    return changes


def publish_configuration_upgrade(
    changes: list[tuple[Path, bytes, dict[str, Any]]],
) -> None:
    # The environment control lock spans prepare, database commit and publication.
    # A partial publication is idempotently reconciled by the next explicit apply.
    for path, original, values in changes:
        if path.read_bytes() != original:
            raise SetupError("SETUP-UPGRADE-CONFIG-CONFLICT")
        write_control(path, values)
