"""Strict structured input and output models for the S035 tool surface."""

from __future__ import annotations

import re
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, field_validator

_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$", re.ASCII)


def _uuid7(value: str) -> str:
    try:
        parsed = UUID(value)
    except (ValueError, AttributeError) as exc:
        raise ValueError("ADMIN-INPUT-ENVIRONMENT-ID") from exc
    if parsed.version != 7 or str(parsed) != value:
        raise ValueError("ADMIN-INPUT-ENVIRONMENT-ID")
    return value


def _digest(value: str) -> str:
    if _DIGEST.fullmatch(value) is None:
        raise ValueError("ADMIN-OUTPUT-DIGEST")
    return value


def _optional_digest(value: str | None) -> str | None:
    return None if value is None else _digest(value)


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class HealthRequest(_StrictModel):
    contract_version: Literal["1.0"] = "1.0"


class SchemaStatusRequest(_StrictModel):
    contract_version: Literal["1.0"] = "1.0"
    environment_id: str

    _environment_id = field_validator("environment_id")(_uuid7)


class AdminIdentity(_StrictModel):
    package_digest: str
    config_digest: str
    tool_catalog_digest: str
    schema_manifest_digest: str

    _package = field_validator("package_digest")(_digest)
    _config = field_validator("config_digest")(_digest)
    _catalog = field_validator("tool_catalog_digest")(_digest)
    _schema = field_validator("schema_manifest_digest")(_digest)


class HealthResult(_StrictModel):
    contract_version: Literal["1.0"] = "1.0"
    status: Literal["healthy", "unavailable", "misconfigured"]
    environment_kind: Literal["development", "system_test", "acceptance"]
    environment_id: str
    identity: AdminIdentity
    database_reachable: bool
    role_status: Literal["verified", "unavailable", "rejected"]
    error_code: str | None = None

    _environment_id = field_validator("environment_id")(_uuid7)


class SchemaStatusResult(_StrictModel):
    contract_version: Literal["1.0"] = "1.0"
    status: Literal["current", "behind", "ahead", "dirty", "unavailable"]
    environment_id: str
    target_version: int
    applied_version: int | None
    applied_migration_count: int
    expected_migration_set_digest: str
    observed_migration_set_digest: str | None
    error_code: str | None = None

    _environment_id = field_validator("environment_id")(_uuid7)
    _expected = field_validator("expected_migration_set_digest")(_digest)
    _observed = field_validator("observed_migration_set_digest")(_optional_digest)


__all__ = (
    "AdminIdentity",
    "HealthRequest",
    "HealthResult",
    "SchemaStatusRequest",
    "SchemaStatusResult",
)
