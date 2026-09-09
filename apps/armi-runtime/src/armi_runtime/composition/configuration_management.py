"""Environment asset edits validated by their actual consuming owners."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, Literal, cast

from armi_adapter_esp32_display import MoodDisplayViolation, load_mood_display_config
from armi_adapter_qq import load_qq_napcat_config
from armi_cognition.bootstrap import load_active_model_binding, load_voice_model_binding
from armi_context.api import load_embedding_binding
from armi_kernel import load_yaml_mapping
from armi_kernel.application import ModelViolation
from armi_local_control.configuration.editing import EnvironmentConfiguration
from armi_local_control.configuration.paths import has_reparse_point
from armi_local_control.maintenance import ConfigurationInvocation
from armi_web_observation.api import WebObservationViolation
from armi_web_observation.bootstrap import validate_web_search_configuration

from armi_runtime.adapters.model.external_content import (
    load_external_recognition_binding,
)
from armi_runtime.application.model_manifest import ModelManifest

from .config_assets import runtime_config_path


class ConfigurationAsset(EnvironmentConfiguration):
    def __init__(self, request: ConfigurationInvocation) -> None:
        super().__init__(request.environment_root, runtime_config_path("runtime.yaml"))
        self.target: Literal["model-bindings", "web-search", "qq", "mood-display"] = (
            request.target
        )
        relative = {
            "model-bindings": "configs/model-bindings.yaml",
            "web-search": "configs/web-search.yaml",
            "qq": "channels/qq-napcat.yaml",
            "mood-display": "devices/mood-display.yaml",
        }[self.target]
        self.path = self.root / relative
        self.default = (
            runtime_config_path(self.target + ".yaml")
            if self.target in {"model-bindings", "web-search"}
            else None
        )

    def read(self) -> dict[str, Any]:
        if has_reparse_point(self.path, root=self.root):
            raise ValueError("ADMIN-CONFIG-PATH")
        exists = self.path.exists()
        raw = self.path.read_bytes() if exists else b""
        if len(raw) > 1024 * 1024:
            raise ValueError("ADMIN-CONFIG-SIZE")
        source = self.path if exists else self.default
        source_raw = raw if exists else b"" if source is None else source.read_bytes()
        try:
            values: dict[str, Any] = (
                {} if source is None else dict(load_yaml_mapping(source_raw))
            )
            if source is not None:
                self._validate(values)
        except (
            ValueError,
            ModelViolation,
            WebObservationViolation,
            MoodDisplayViolation,
        ):
            result = self._invalid(raw, "ADMIN-CONFIG-INVALID")
            result["sources"] = [] if source is None else [str(source)]
            return result
        return {
            "version": "sha256:" + hashlib.sha256(raw).hexdigest(),
            "values": values,
            "source": None if source is None else str(source),
            "desired_source_version": None
            if source is None
            else "sha256:" + hashlib.sha256(source_raw).hexdigest(),
            "activation": "not_verified",
            "configuration_state": "configured" if source is not None else "missing",
            "restart_required": True,
        }

    def preview(
        self,
        patch: dict[str, Any],
        expected_version: str,
        *,
        document: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        current = self.read()
        if current["version"] != expected_version:
            raise ValueError("ADMIN-CONFIG-VERSION-CONFLICT")
        if document is not None:
            if patch:
                raise ValueError("ADMIN-CONFIG-EDIT-CONFLICT")
            base = {}
        elif current["configuration_state"] == "invalid":
            # Parse the source again privately so a patch can repair a valid YAML
            # document whose values fail the consumer contract.
            source = self.path if self.path.exists() else self.default
            base = (
                {} if source is None else dict(load_yaml_mapping(source.read_bytes()))
            )
        else:
            base = current["values"]
        values = document if document is not None else self._merge(base, patch)
        self._validate(values)
        return {
            "expected_version": expected_version,
            "values": values,
            "activation": "not_saved",
            "restart_required": True,
        }

    def _validate(self, values: dict[str, Any]) -> None:
        # Parsing consumes no credentials, network or devices. The same owner
        # validators are used by Runtime composition after a restart.
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            path = root / "configuration.yaml"
            raw = json.dumps(values, ensure_ascii=False).encode("utf-8")
            path.write_bytes(raw)
            match self.target:
                case "model-bindings":
                    ModelManifest.model_validate(values)
                    load_active_model_binding(path)
                    load_voice_model_binding(path)
                    load_embedding_binding(path)
                    load_external_recognition_binding(path)
                case "web-search":
                    validate_web_search_configuration(raw)
                case "qq":
                    load_qq_napcat_config(path)
                case "mood-display":
                    devices = root / "devices"
                    devices.mkdir()
                    path.replace(devices / "mood-display.yaml")
                    load_mood_display_config(root)


def execute_configuration(request: ConfigurationInvocation) -> dict[str, Any]:
    environment = load_yaml_mapping(
        (request.environment_root / "environment.yaml").read_bytes()
    )
    identity = cast(dict[str, Any], environment.get("environment", {})).get(
        "environment_id"
    )
    if identity != str(request.environment_id):
        raise ValueError("ADMIN-ENVIRONMENT-MISMATCH")
    config = ConfigurationAsset(request)
    if request.action in {"read", "status"}:
        if (
            request.patch
            or request.document is not None
            or request.expected_version is not None
        ):
            raise ValueError("ADMIN-CONFIG-READ-ARGUMENTS")
        return config.read()
    if request.expected_version is None:
        raise ValueError("ADMIN-CONFIG-VERSION-REQUIRED")
    return (
        config.apply(request.patch, request.expected_version, document=request.document)
        if request.action == "apply"
        else config.preview(
            request.patch, request.expected_version, document=request.document
        )
    )


__all__ = ("execute_configuration",)
