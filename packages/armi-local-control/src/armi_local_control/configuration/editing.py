"""Version-checked environment configuration edits, without runtime effects."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any, cast
from uuid import uuid7

from armi_kernel import load_yaml_mapping

from armi_local_control.runtime_process import LocalProcessLock

from .errors import ConfigurationViolation
from .loader import validate_environment_values
from .paths import has_reparse_point


def _digest(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


def configuration_digest(values: dict[str, Any]) -> str:
    """Compare validated desired values with the values held by a live Runtime."""
    return _digest(
        json.dumps(
            values,
            sort_keys=True,
            ensure_ascii=False,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    )


class EnvironmentConfiguration:
    def __init__(
        self, root: Path, defaults: Path, *, environment_id: str | None = None
    ) -> None:
        self.root = root.resolve()
        self.defaults = defaults
        self.path = self.root / "environment.yaml"
        self.environment_id = environment_id

    def _check_identity(self, values: dict[str, Any]) -> None:
        if self.environment_id is None:
            return
        identity = values.get("environment", {})
        if not isinstance(identity, dict):
            raise ConfigurationViolation(
                "CFG-ENVIRONMENT-IDENTITY", "bound environment identity differs"
            )
        bound_identity = cast(dict[str, Any], identity)
        if (
            bound_identity.get("environment_id") != self.environment_id
            or Path(str(bound_identity.get("data_root", ""))).resolve()
            != self.root / "data"
        ):
            raise ConfigurationViolation(
                "CFG-ENVIRONMENT-IDENTITY", "bound environment identity differs"
            )

    def _content(self) -> bytes:
        if has_reparse_point(self.path, root=self.root):
            raise ValueError("ADMIN-CONFIG-PATH")
        content = self.path.read_bytes()
        if len(content) > 1024 * 1024:
            raise ValueError("ADMIN-CONFIG-SIZE")
        return content

    def read(self) -> dict[str, Any]:
        content = self._content()
        try:
            values = dict(load_yaml_mapping(content))
            self._check_identity(values)
            effective = validate_environment_values(
                defaults_path=self.defaults, values=values
            )
        except ConfigurationViolation as error:
            return self._invalid(content, error.code)
        except ValueError:
            return self._invalid(content, "ADMIN-CONFIG-YAML")
        return {
            "version": _digest(content),
            "configuration_state": "configured",
            "values": values,
            "effective_on_next_start": effective.model_dump(mode="json"),
            "desired_digest": configuration_digest(effective.model_dump(mode="json")),
            "sources": [str(self.defaults), str(self.path)],
            "activation": "not_verified",
            "restart_required": True,
        }

    def _invalid(self, content: bytes, code: str) -> dict[str, Any]:
        # Unvalidated values can contain credentials or arbitrary error text.
        # Return only the file version and a stable diagnosis, never that text.
        return {
            "version": _digest(content),
            "configuration_state": "invalid",
            "error_code": code,
            "values": None,
            "sources": [str(self.defaults), str(self.path)],
            "activation": "invalid",
            "restart_required": False,
        }

    def preview(
        self,
        patch: dict[str, Any],
        expected_version: str,
        *,
        document: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        content = self._content()
        if _digest(content) != expected_version:
            raise ValueError("ADMIN-CONFIG-VERSION-CONFLICT")
        if any(key in patch for key in ("environment", "schema_version")):
            raise ValueError("ADMIN-CONFIG-IMMUTABLE")
        if document is not None:
            if patch:
                raise ValueError("ADMIN-CONFIG-EDIT-CONFLICT")
            if self.environment_id is None:
                raise ValueError("ADMIN-CONFIG-BOUND-IDENTITY-REQUIRED")
            values = document
        else:
            values = self._merge(dict(load_yaml_mapping(content)), patch)
        self._check_identity(values)
        effective = validate_environment_values(
            defaults_path=self.defaults, values=values
        )
        return {
            "expected_version": expected_version,
            "values": values,
            "effective_on_next_start": effective.model_dump(mode="json"),
            "restart_required": True,
            "activation": "not_saved",
        }

    def apply(
        self,
        patch: dict[str, Any],
        expected_version: str,
        *,
        document: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        import yaml

        lock_path = self.root / ".configuration-edit.lock"
        temporary = self.root / f".configuration-{uuid7()}.yaml"
        try:
            with LocalProcessLock(lock_path):
                candidate = self.preview(patch, expected_version, document=document)
                if has_reparse_point(self.path.parent, root=self.root):
                    raise ValueError("ADMIN-CONFIG-PATH")
                self.path.parent.mkdir(parents=True, exist_ok=True)
                content = yaml.safe_dump(
                    candidate["values"], allow_unicode=True, sort_keys=False
                ).encode("utf-8")
                with temporary.open("xb") as stream:
                    stream.write(content)
                    stream.flush()
                    os.fsync(stream.fileno())
                if (
                    _digest(self.path.read_bytes() if self.path.exists() else b"")
                    != expected_version
                ):
                    raise ValueError("ADMIN-CONFIG-VERSION-CONFLICT")
                os.replace(temporary, self.path)
                return {
                    "version": _digest(content),
                    "activation": "saved",
                    "restart_required": True,
                }
        finally:
            temporary.unlink(missing_ok=True)

    @classmethod
    def _merge(cls, base: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
        result = dict(base)
        for key, value in patch.items():
            result[key] = (
                cls._merge(result[key], cast(dict[str, Any], value))
                if isinstance(value, dict) and isinstance(result.get(key), dict)
                else value
            )
        return result


__all__ = ("EnvironmentConfiguration", "configuration_digest")
