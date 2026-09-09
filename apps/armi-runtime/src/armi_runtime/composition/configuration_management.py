"""Environment asset edits validated by their actual consuming owners."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, Literal, cast

from armi_adapter_esp32_display import load_mood_display_config
from armi_adapter_qq import load_qq_napcat_config
from armi_cognition.bootstrap import load_active_model_binding, load_voice_model_binding
from armi_context.api import load_embedding_binding
from armi_kernel import load_yaml_mapping
from armi_local_control.configuration.editing import EnvironmentConfiguration
from armi_local_control.configuration.paths import has_reparse_point
from armi_local_control.maintenance import ConfigurationInvocation
from armi_web_observation.bootstrap import validate_web_search_configuration

from armi_runtime.adapters.model.external_content import (
    load_external_recognition_binding,
)

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
        values: dict[str, Any] = (
            {} if source is None else dict(load_yaml_mapping(source.read_bytes()))
        )
        if source is not None:
            self._validate(values)
        return {
            "version": "sha256:" + hashlib.sha256(raw).hexdigest(),
            "values": values,
            "source": None if source is None else str(source),
            "activation": "not_verified",
            "configuration_state": "configured" if source is not None else "missing",
            "restart_required": True,
        }

    def preview(self, patch: dict[str, Any], expected_version: str) -> dict[str, Any]:
        current = self.read()
        if current["version"] != expected_version:
            raise ValueError("ADMIN-CONFIG-VERSION-CONFLICT")
        values = self._merge(current["values"], patch)
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
        if self.default is not None:
            self._shape(values, dict(load_yaml_mapping(self.default.read_bytes())))
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            path = root / "configuration.yaml"
            raw = json.dumps(values, ensure_ascii=False).encode("utf-8")
            path.write_bytes(raw)
            match self.target:
                case "model-bindings":
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

    @classmethod
    def _shape(cls, value: Any, example: Any) -> None:
        if type(value) is not type(example):
            raise ValueError("ADMIN-CONFIG-TYPE")
        if isinstance(example, dict):
            template = cast(dict[str, Any], example)
            if set(value) != set(template):
                raise ValueError("ADMIN-CONFIG-FIELDS")
            for key in template:
                cls._shape(value[key], template[key])
        elif isinstance(example, list) and example:
            for item in value:
                cls._shape(item, cast(list[Any], example)[0])


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
        if request.patch or request.expected_version is not None:
            raise ValueError("ADMIN-CONFIG-READ-ARGUMENTS")
        return config.read()
    if request.expected_version is None:
        raise ValueError("ADMIN-CONFIG-VERSION-REQUIRED")
    return (
        config.apply(request.patch, request.expected_version)
        if request.action == "apply"
        else config.preview(request.patch, request.expected_version)
    )


__all__ = ("execute_configuration",)
