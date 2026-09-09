"""Closed local maintenance wire contract; no executable text or arbitrary paths."""

from __future__ import annotations

from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .configuration.models import AbsolutePath, Uuid7

type MaintenanceAction = Literal[
    "database_install",
    "database_check",
    "database_maintain",
    "birth",
    "reset",
    "artifact_cleanup",
    "capacity_check",
    "semantic_install",
    "semantic_calibrate",
    "semantic_status",
    "voice_devices",
    "vision_sources",
    "device_bindings",
    "mood_display_probe",
    "napcat_status",
    "napcat_start",
    "napcat_open",
]


class MaintenanceParameters(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)
    action: MaintenanceAction
    apply: bool = False
    approved_official_direct: bool = False
    duration_seconds: int = Field(default=30, ge=1, le=300)
    auto_login: bool = False
    sample_interval_seconds: int = Field(default=1, ge=1, le=60)
    max_rss_growth_bytes: int = Field(default=67108864, ge=0)
    max_backlog_growth: int = Field(default=0, ge=0)
    max_open_backlog_age_seconds: int = Field(default=120, ge=0)
    max_log_growth_bytes: int = Field(default=16777216, ge=0)

    @property
    def read_only(self) -> bool:
        return self.action in {
            "database_check",
            "capacity_check",
            "semantic_status",
            "voice_devices",
            "vision_sources",
            "device_bindings",
            "napcat_status",
        } or (self.action == "artifact_cleanup" and not self.apply)

    @model_validator(mode="after")
    def action_parameters(self) -> Self:
        if self.auto_login and self.action != "napcat_open":
            raise ValueError("ADMIN-MAINTENANCE-ARGUMENTS")
        if self.approved_official_direct and self.action != "semantic_install":
            raise ValueError("ADMIN-MAINTENANCE-ARGUMENTS")
        if self.apply and self.action not in {
            "database_maintain",
            "artifact_cleanup",
            "reset",
        }:
            raise ValueError("ADMIN-MAINTENANCE-ARGUMENTS")
        if (
            self.action == "capacity_check"
            and self.sample_interval_seconds > self.duration_seconds
        ):
            raise ValueError("ADMIN-CAPACITY-INTERVAL")
        return self


class MaintenanceInvocation(MaintenanceParameters):
    schema_version: Literal["armi.local-maintenance.v1"] = "armi.local-maintenance.v1"
    environment_root: AbsolutePath
    environment_id: Uuid7


class ConfigurationInvocation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)
    schema_version: Literal["armi.local-configuration.v2"] = (
        "armi.local-configuration.v2"
    )
    environment_root: AbsolutePath
    environment_id: Uuid7
    target: Literal["model-bindings", "web-search", "qq", "mood-display"]
    action: Literal["read", "validate", "preview", "apply", "status"]
    patch: dict[str, object] = Field(default_factory=dict)
    document: dict[str, object] | None = None
    expected_version: str | None = None


__all__ = (
    "ConfigurationInvocation",
    "MaintenanceAction",
    "MaintenanceInvocation",
    "MaintenanceParameters",
)
