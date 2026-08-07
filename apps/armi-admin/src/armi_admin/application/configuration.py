"""Strict private configuration for the Codex-launched Admin MCP process."""

from __future__ import annotations

import hashlib
import json
import os
import re
import tomllib
from enum import StrEnum
from pathlib import Path
from typing import Literal, Self
from uuid import UUID

from armi_kernel.application import CredentialLocator
from pydantic import BaseModel, ConfigDict, field_validator, model_validator

ADMIN_CONFIG_ENV = "ARMI_ADMIN_CONFIG"
_MAX_CONFIG_BYTES = 64 * 1024
_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$", re.ASCII)


class AdminConfigError(RuntimeError):
    """A stable, redacted Admin configuration failure."""


class AdminEnvironmentKind(StrEnum):
    DEVELOPMENT = "development"
    SYSTEM_TEST = "system_test"
    ACCEPTANCE = "acceptance"


def _validate_uuid7(value: str) -> str:
    try:
        parsed = UUID(value)
    except (ValueError, AttributeError) as exc:
        raise ValueError("ADMIN-CONFIG-ENVIRONMENT-ID") from exc
    if parsed.version != 7 or str(parsed) != value:
        raise ValueError("ADMIN-CONFIG-ENVIRONMENT-ID")
    return value


def _validate_digest(value: str) -> str:
    if _DIGEST.fullmatch(value) is None:
        raise ValueError("ADMIN-CONFIG-DIGEST")
    return value


class AdminExpectedIdentity(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    package_digest: str

    _package_digest = field_validator("package_digest")(_validate_digest)


class AdminLogSettings(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    sink: Literal["stderr"] = "stderr"
    level: Literal["warning", "error"] = "warning"


class AdminConfig(BaseModel):
    """One explicit non-production environment binding."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    schema_version: Literal["armi.admin-config.v4"]
    environment_kind: AdminEnvironmentKind
    environment_id: str
    environment_incarnation: int
    resettable: bool
    test_controls_enabled: bool
    environment_root: Path
    experiment_root: Path
    template_manifest: Path
    postgresql_client_root: Path
    postgresql_version: Literal["18.4"] = "18.4"
    database_locator: str
    migrator_database_locator: str
    preview_key_locator: str
    expected: AdminExpectedIdentity
    logging: AdminLogSettings = AdminLogSettings()

    _environment_id = field_validator("environment_id")(_validate_uuid7)

    @field_validator("environment_kind", mode="before")
    @classmethod
    def _environment_kind(cls, value: object) -> AdminEnvironmentKind:
        try:
            return AdminEnvironmentKind(value)
        except (TypeError, ValueError) as exc:
            raise ValueError("ADMIN-CONFIG-ENVIRONMENT-KIND") from exc

    @field_validator(
        "database_locator", "migrator_database_locator", "preview_key_locator"
    )
    @classmethod
    def _credential_locator(cls, value: str) -> str:
        try:
            locator = CredentialLocator.parse(value)
        except ValueError as exc:
            raise ValueError("ADMIN-CONFIG-DATABASE-LOCATOR") from exc
        if locator.scheme not in {"env", "file"}:
            raise ValueError("ADMIN-CONFIG-DATABASE-LOCATOR")
        if locator.scheme == "env" and locator.target not in {
            "ARMI_SECRET_ADMIN_DATABASE",
            "ARMI_SECRET_MIGRATOR_DATABASE",
            "ARMI_SECRET_ADMIN_PREVIEW_KEY",
        }:
            raise ValueError("ADMIN-CONFIG-DATABASE-LOCATOR")
        return value

    @field_validator("environment_incarnation")
    @classmethod
    def _incarnation(cls, value: int) -> int:
        if value < 1:
            raise ValueError("ADMIN-CONFIG-INCARNATION")
        return value

    @field_validator(
        "environment_root",
        "experiment_root",
        "template_manifest",
        "postgresql_client_root",
        mode="before",
    )
    @classmethod
    def _absolute_path(cls, value: object) -> Path:
        if not isinstance(value, (str, Path)):
            raise ValueError("ADMIN-CONFIG-PATH")
        path = Path(value)
        if not path.is_absolute() or path.is_symlink():
            raise ValueError("ADMIN-CONFIG-PATH")
        return path

    @model_validator(mode="after")
    def _not_production(self) -> Self:
        if str(self.environment_kind) not in {
            "development",
            "system_test",
            "acceptance",
        }:
            raise ValueError("ADMIN-CONFIG-ENVIRONMENT-KIND")
        if self.test_controls_enabled and self.environment_kind not in {
            AdminEnvironmentKind.SYSTEM_TEST,
            AdminEnvironmentKind.ACCEPTANCE,
        }:
            raise ValueError("ADMIN-CONFIG-TEST-CONTROLS")
        if not self.environment_root.is_relative_to(self.experiment_root):
            raise ValueError("ADMIN-CONFIG-ENVIRONMENT-ROOT")
        return self

    @property
    def expected_role(self) -> str:
        return f"armi_{self.environment_id.replace('-', '')}_admin"

    @property
    def locator(self) -> CredentialLocator:
        return CredentialLocator.parse(self.database_locator)

    @property
    def migrator_locator(self) -> CredentialLocator:
        return CredentialLocator.parse(self.migrator_database_locator)

    @property
    def preview_locator(self) -> CredentialLocator:
        return CredentialLocator.parse(self.preview_key_locator)

    def safe_digest(self) -> str:
        payload = {
            "schema_version": self.schema_version,
            "environment_kind": str(self.environment_kind),
            "environment_id": self.environment_id,
            "environment_incarnation": self.environment_incarnation,
            "resettable": self.resettable,
            "test_controls_enabled": self.test_controls_enabled,
            "environment_root_identity": _path_identity(self.environment_root),
            "experiment_root_identity": _path_identity(self.experiment_root),
            "template_manifest_identity": _path_identity(self.template_manifest),
            "postgresql_client_root_identity": _path_identity(
                self.postgresql_client_root
            ),
            "postgresql_version": self.postgresql_version,
            "database_locator_identity": self.locator.identity(),
            "migrator_locator_identity": self.migrator_locator.identity(),
            "preview_locator_identity": self.preview_locator.identity(),
            "expected": self.expected.model_dump(mode="json"),
            "logging": self.logging.model_dump(mode="json"),
        }
        encoded = json.dumps(
            payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True
        ).encode("utf-8")
        return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


def _path_identity(value: Path) -> str:
    normalized = value.resolve(strict=False).as_posix().casefold().encode("utf-8")
    return f"sha256:{hashlib.sha256(normalized).hexdigest()}"


def load_admin_config(
    environ: dict[str, str] | None = None,
) -> tuple[AdminConfig, Path]:
    """Load exactly one private TOML named by ``ARMI_ADMIN_CONFIG``."""

    source = os.environ if environ is None else environ
    raw_path = source.get(ADMIN_CONFIG_ENV, "")
    try:
        candidate = Path(raw_path)
        if not raw_path or not candidate.is_absolute():
            raise AdminConfigError("ADMIN-CONFIG-PATH")
        if candidate.is_symlink():
            raise AdminConfigError("ADMIN-CONFIG-REPARSE")
        resolved = candidate.resolve(strict=True)
        if not resolved.is_file() or resolved.stat().st_size > _MAX_CONFIG_BYTES:
            raise AdminConfigError("ADMIN-CONFIG-FILE")
        raw = resolved.read_bytes()
        if raw.startswith(b"\xef\xbb\xbf"):
            raise AdminConfigError("ADMIN-CONFIG-ENCODING")
        value = tomllib.loads(raw.decode("utf-8", errors="strict"))
        return AdminConfig.model_validate(value), resolved
    except AdminConfigError:
        raise
    except Exception as exc:
        raise AdminConfigError("ADMIN-CONFIG-INVALID") from exc


__all__ = (
    "ADMIN_CONFIG_ENV",
    "AdminConfig",
    "AdminConfigError",
    "AdminEnvironmentKind",
    "load_admin_config",
)
