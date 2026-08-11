"""Strict immutable models for ``armi.runtime-config.v1``."""

from __future__ import annotations

import re
from collections.abc import Mapping
from pathlib import Path
from types import MappingProxyType
from typing import Annotated, Literal, Self
from uuid import UUID

from armi_kernel.application import CredentialLocator
from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    PlainSerializer,
    WithJsonSchema,
    field_serializer,
    field_validator,
    model_validator,
)

RUNTIME_CONFIG_SCHEMA_VERSION = "armi.runtime-config.v1"
_LOCATOR_NAME = re.compile(r"^[a-z][a-z0-9._-]{0,63}$", re.ASCII)


def _parse_uuid7(value: object) -> UUID:
    if isinstance(value, UUID):
        parsed = value
    elif isinstance(value, str):
        try:
            parsed = UUID(value)
        except ValueError as error:
            raise ValueError("expected canonical UUIDv7") from error
    else:
        raise ValueError("expected canonical UUIDv7")
    if parsed.version != 7 or (isinstance(value, str) and str(parsed) != value):
        raise ValueError("expected canonical UUIDv7")
    return parsed


def _parse_absolute_path(value: object) -> Path:
    if isinstance(value, Path):
        candidate = value
    elif isinstance(value, str):
        candidate = Path(value)
    else:
        raise ValueError("expected an absolute Windows path")
    if not candidate.is_absolute():
        raise ValueError("expected an absolute Windows path")
    return candidate.resolve(strict=False)


def _parse_locator(value: object) -> CredentialLocator:
    if isinstance(value, CredentialLocator):
        return value
    if not isinstance(value, str):
        raise ValueError("expected a credential locator")
    try:
        return CredentialLocator.parse(value)
    except ValueError as error:
        raise ValueError("expected a credential locator") from error


Uuid7 = Annotated[
    UUID,
    BeforeValidator(_parse_uuid7),
    PlainSerializer(str, return_type=str),
    WithJsonSchema({"type": "string", "format": "uuid", "x-uuid-version": 7}),
]
AbsolutePath = Annotated[
    Path,
    BeforeValidator(_parse_absolute_path),
    PlainSerializer(str, return_type=str),
    WithJsonSchema({"type": "string", "format": "windows-absolute-path"}),
]
LocatorValue = Annotated[
    CredentialLocator,
    BeforeValidator(_parse_locator),
    PlainSerializer(lambda value: value.identity(), return_type=str),
    WithJsonSchema(
        {
            "type": "string",
            "pattern": "^[a-z][a-z0-9-]{1,31}:.{1,2048}$",
        }
    ),
]
PositiveInt = Annotated[int, Field(gt=0)]


class _FrozenModel(BaseModel):
    model_config = ConfigDict(
        arbitrary_types_allowed=True,
        extra="forbid",
        frozen=True,
        strict=True,
    )


class EnvironmentConfig(_FrozenModel):
    environment_id: Uuid7
    data_root: AbsolutePath


class DatabaseConfig(_FrozenModel):
    pool_min: PositiveInt = 2
    pool_max: PositiveInt = 12
    pool_acquire_timeout_seconds: PositiveInt = 5
    statement_timeout_seconds: PositiveInt = 5
    diagnostic_statement_timeout_seconds: PositiveInt = 30
    maintenance_statement_timeout_seconds: PositiveInt = 300

    @model_validator(mode="after")
    def validate_pool(self) -> Self:
        if self.pool_min > self.pool_max:
            raise ValueError("database pool_min must not exceed pool_max")
        return self


class LeaseConfig(_FrozenModel):
    lease_seconds: PositiveInt
    heartbeat_seconds: PositiveInt

    @model_validator(mode="after")
    def validate_heartbeat(self) -> Self:
        if self.heartbeat_seconds * 2 >= self.lease_seconds:
            raise ValueError("heartbeat must be less than half of lease")
        return self


class WorkConfig(LeaseConfig):
    lease_seconds: PositiveInt = 60
    heartbeat_seconds: PositiveInt = 20
    max_deadline_seconds: PositiveInt = 3600


class RuntimeLeaseConfig(LeaseConfig):
    lease_seconds: PositiveInt = 30
    heartbeat_seconds: PositiveInt = 10


class ModelConfig(_FrozenModel):
    concurrency: PositiveInt = 2
    attempt_timeout_seconds: PositiveInt = 180


class WebConfig(_FrozenModel):
    concurrency: PositiveInt = 1
    step_timeout_seconds: PositiveInt = 30
    total_timeout_seconds: PositiveInt = 90

    @model_validator(mode="after")
    def validate_timeouts(self) -> Self:
        if self.step_timeout_seconds >= self.total_timeout_seconds:
            raise ValueError("web step timeout must be less than total timeout")
        return self


class CodexConfig(_FrozenModel):
    concurrency: PositiveInt = 1
    total_timeout_seconds: PositiveInt = 1800


class CreatorConfig(_FrozenModel):
    bind_host: Literal["127.0.0.1"] = "127.0.0.1"
    port: Annotated[int, Field(ge=1024, le=65535)]
    request_body_max_bytes: PositiveInt = 262_144
    bootstrap_ttl_seconds: PositiveInt = 120
    session_ttl_seconds: PositiveInt = 28_800


class ArtifactsConfig(_FrozenModel):
    max_object_bytes: PositiveInt = 104_857_600
    orphan_grace_seconds: PositiveInt = 86_400


class DiagnosticsConfig(_FrozenModel):
    rotation_max_bytes: PositiveInt = 16_777_216
    retention_seconds: PositiveInt = 604_800


class ObservabilityConfig(_FrozenModel):
    sample_interval_seconds: PositiveInt = 10
    disk_warning_free_bytes: PositiveInt = 2_147_483_648
    disk_critical_free_bytes: PositiveInt = 1_073_741_824

    @model_validator(mode="after")
    def validate_disk_watermarks(self) -> Self:
        if self.disk_critical_free_bytes >= self.disk_warning_free_bytes:
            raise ValueError("critical disk watermark must be below warning")
        return self


class LifecycleConfig(_FrozenModel):
    graceful_shutdown_seconds: PositiveInt = 30


class SchedulerConfig(_FrozenModel):
    idle_poll_initial_seconds: PositiveInt = 1
    idle_poll_max_seconds: PositiveInt = 10

    @model_validator(mode="after")
    def validate_polling(self) -> Self:
        if self.idle_poll_initial_seconds > self.idle_poll_max_seconds:
            raise ValueError("initial poll must not exceed maximum poll")
        return self


class MaintenanceConfig(_FrozenModel):
    consideration_after_seconds: PositiveInt = 57_600
    deadline_after_seconds: PositiveInt = 86_400

    @model_validator(mode="after")
    def validate_window(self) -> Self:
        if self.consideration_after_seconds >= self.deadline_after_seconds:
            raise ValueError("maintenance consideration must precede deadline")
        return self


class RuntimeConfig(_FrozenModel):
    """The only supported effective runtime configuration shape."""

    schema_version: Literal["armi.runtime-config.v1"]
    environment: EnvironmentConfig
    database: DatabaseConfig = DatabaseConfig()
    runtime: RuntimeLeaseConfig = RuntimeLeaseConfig()
    work: WorkConfig = WorkConfig()
    model: ModelConfig = ModelConfig()
    web: WebConfig = WebConfig()
    codex: CodexConfig = CodexConfig()
    creator: CreatorConfig
    artifacts: ArtifactsConfig = ArtifactsConfig()
    diagnostics: DiagnosticsConfig = DiagnosticsConfig()
    observability: ObservabilityConfig = ObservabilityConfig()
    lifecycle: LifecycleConfig = LifecycleConfig()
    scheduler: SchedulerConfig = SchedulerConfig()
    maintenance: MaintenanceConfig = MaintenanceConfig()
    secret_locators: Mapping[str, LocatorValue] = Field(
        default_factory=dict,
        validate_default=True,
    )

    @field_validator("secret_locators")
    @classmethod
    def validate_locator_names(
        cls, value: Mapping[str, CredentialLocator]
    ) -> Mapping[str, CredentialLocator]:
        if any(_LOCATOR_NAME.fullmatch(name) is None for name in value):
            raise ValueError("secret locator name is invalid")
        return MappingProxyType(dict(value))

    @field_serializer("secret_locators")
    def serialize_locators(
        self, value: Mapping[str, CredentialLocator]
    ) -> dict[str, str]:
        return {name: locator.identity() for name, locator in value.items()}

    @model_validator(mode="after")
    def validate_deadlines(self) -> Self:
        deadline = self.work.max_deadline_seconds
        if (
            self.model.attempt_timeout_seconds >= deadline
            or self.web.total_timeout_seconds >= deadline
            or self.codex.total_timeout_seconds >= deadline
        ):
            raise ValueError("external timeout must be less than work deadline")
        return self


__all__ = (
    "RUNTIME_CONFIG_SCHEMA_VERSION",
    "AbsolutePath",
    "ArtifactsConfig",
    "CodexConfig",
    "CreatorConfig",
    "DatabaseConfig",
    "DiagnosticsConfig",
    "EnvironmentConfig",
    "LifecycleConfig",
    "LocatorValue",
    "MaintenanceConfig",
    "ModelConfig",
    "ObservabilityConfig",
    "RuntimeConfig",
    "RuntimeLeaseConfig",
    "SchedulerConfig",
    "Uuid7",
    "WebConfig",
    "WorkConfig",
)
