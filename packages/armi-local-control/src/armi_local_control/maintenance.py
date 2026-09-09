"""Closed local maintenance wire contract; no executable text or arbitrary paths."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

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
]


class MaintenanceInvocation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)
    schema_version: Literal["armi.local-maintenance.v1"] = "armi.local-maintenance.v1"
    environment_root: AbsolutePath
    environment_id: Uuid7
    action: MaintenanceAction
    apply: bool = False
    approved_official_direct: bool = False
    duration_seconds: int = Field(default=30, ge=1, le=300)


class ConfigurationInvocation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)
    schema_version: Literal["armi.local-configuration.v1"] = (
        "armi.local-configuration.v1"
    )
    environment_root: AbsolutePath
    environment_id: Uuid7
    target: Literal["model-bindings", "web-search", "qq", "mood-display"]
    action: Literal["read", "validate", "preview", "apply", "status"]
    patch: dict[str, object] = Field(default_factory=dict)
    expected_version: str | None = None


__all__ = ("ConfigurationInvocation", "MaintenanceAction", "MaintenanceInvocation")
