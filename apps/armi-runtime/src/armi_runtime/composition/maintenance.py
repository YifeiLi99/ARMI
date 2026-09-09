"""Local maintenance use cases, independent of CLI argument parsing."""

from __future__ import annotations

import asyncio
from dataclasses import asdict
from typing import Any

from armi_adapter_esp32_display import load_mood_display_config, probe_device
from armi_local_control.maintenance import MaintenanceInvocation
from armi_local_control.runtime_errors import RuntimeViolation
from armi_local_control.runtime_process import RuntimeProcessManager
from armi_local_control.semantic_recall_process import SemanticRecallProcessManager

from armi_runtime.adapters.vision.directshow import DirectShowUsbCamera
from armi_runtime.adapters.vision.windows_screen import WindowsScreenSource
from armi_runtime.adapters.voice.wasapi import WasapiRawAudio

from .bootstrap import execute_birth
from .database import (
    inspect_operator_schema,
    inspect_semantic_recall_storage,
    install_operator_schema,
)
from .device_binding_checks import inspect_device_bindings
from .environment import prepare_environment
from .environment_reset import reset_environment
from .napcat_process import NapCatProcessManager
from .operational_maintenance import run_artifact_retention, run_database_maintenance
from .qq_channel import (
    QQ_NAPCAT_ACCESS_TOKEN_LOCATOR,
    QQ_NAPCAT_ACCESS_TOKEN_PURPOSE,
    QQ_NAPCAT_EVENT_SECRET_LOCATOR,
    QQ_NAPCAT_EVENT_SECRET_PURPOSE,
)
from .runtime_capacity import run_runtime_capacity_baseline
from .runtime_credentials import inspect_runtime_credentials, runtime_credential_scope


def execute_maintenance(request: MaintenanceInvocation) -> dict[str, Any]:
    scopes = {
        "credential_check": runtime_credential_scope(),
        "database_install": {"database.migrator": "database.migrator"},
        "database_check": {"database.status": "database.runtime"},
        "semantic_status": {"database.status": "database.runtime"},
        "napcat_status": {
            QQ_NAPCAT_ACCESS_TOKEN_PURPOSE: QQ_NAPCAT_ACCESS_TOKEN_LOCATOR
        },
        "napcat_start": {
            QQ_NAPCAT_ACCESS_TOKEN_PURPOSE: QQ_NAPCAT_ACCESS_TOKEN_LOCATOR,
            QQ_NAPCAT_EVENT_SECRET_PURPOSE: QQ_NAPCAT_EVENT_SECRET_LOCATOR,
        },
        "database_maintain": {"database.maintenance": "database.migrator"},
        "birth": {"database.birth": "database.runtime"},
        "reset": {
            "database.migrator": "database.migrator",
            "database.birth": "database.runtime",
        },
        "artifact_cleanup": {"database.artifact-maintenance": "database.runtime"},
    }
    prepared = prepare_environment(
        request.environment_root, credential_scope=scopes.get(request.action, {})
    )
    if prepared.effective.config.environment.environment_id != request.environment_id:
        raise RuntimeViolation(
            "ADMIN-ENVIRONMENT-MISMATCH", "bound environment identity differs"
        )
    match request.action:
        case "credential_check":
            return inspect_runtime_credentials(prepared)
        case "napcat_status":
            return NapCatProcessManager(prepared).status().safe_view()
        case "napcat_start":
            return NapCatProcessManager(prepared).start().safe_view()
        case "napcat_open":
            return (
                NapCatProcessManager(prepared)
                .open_webui(auto_login=request.auto_login)
                .safe_view()
            )
        case "voice_devices":
            return {"devices": [asdict(device) for device in WasapiRawAudio.devices()]}
        case "vision_sources":
            return {
                "cameras": [asdict(source) for source in DirectShowUsbCamera.sources()],
                "screens": [asdict(source) for source in WindowsScreenSource.sources()],
            }
        case "device_bindings":
            config = prepared.effective.config
            display = load_mood_display_config(prepared.root)
            return {
                "voice": config.voice.model_dump(mode="json"),
                "vision": config.vision.model_dump(mode="json"),
                "mood_display": None if display is None else asdict(display),
                "checks": inspect_device_bindings(config),
                "mood_display_binding": "disabled"
                if display is None or not display.enabled
                else "not_verified",
                "mood_display_next_operation": "maintenance.mood_display_probe",
                "collection_performed": False,
            }
        case "mood_display_probe":
            display = load_mood_display_config(prepared.root)
            if display is None:
                raise RuntimeViolation(
                    "MOOD-DISPLAY-CONFIG-MISSING",
                    "bound display configuration is missing",
                )
            probe = probe_device(display.port)
            return {
                "probe": asdict(probe),
                "expected_device_id": display.expected_device_id,
                "binding_status": "matches"
                if probe.device_id == display.expected_device_id
                else "mismatch",
            }
        case "database_install":
            return install_operator_schema(prepared).safe_view()
        case "database_check":
            return inspect_operator_schema(prepared).safe_view()
        case "database_maintain":
            if not request.apply:
                raise RuntimeViolation(
                    "ADMIN-MAINTENANCE-APPLY-REQUIRED",
                    "database maintenance requires explicit apply",
                )
            return run_database_maintenance(prepared).safe_view()
        case "birth":
            return execute_birth(prepared).safe_view()
        case "reset":
            if not request.apply:
                raise RuntimeViolation(
                    "ADMIN-RESET-APPLY", "reset requires explicit apply"
                )
            return reset_environment(prepared, birth_after_reset=False).safe_view()
        case "artifact_cleanup":
            return asyncio.run(
                run_artifact_retention(prepared, apply=request.apply)
            ).safe_view()
        case "capacity_check":
            manager = RuntimeProcessManager(prepared.root, str(request.environment_id))
            return run_runtime_capacity_baseline(
                manager.status,
                duration_seconds=request.duration_seconds,
                sample_interval_seconds=request.sample_interval_seconds,
                max_rss_growth_bytes=request.max_rss_growth_bytes,
                max_backlog_growth=request.max_backlog_growth,
                max_open_backlog_age_seconds=request.max_open_backlog_age_seconds,
                max_log_growth_bytes=request.max_log_growth_bytes,
            ).safe_view()
        case "semantic_install" | "semantic_calibrate" | "semantic_status":
            semantic = SemanticRecallProcessManager(
                prepared.root,
                enabled=prepared.effective.config.model.semantic_recall_enabled,
            )
            if request.action == "semantic_install":
                return semantic.install(
                    approved_official_direct=request.approved_official_direct
                )
            if request.action == "semantic_calibrate":
                runtime = RuntimeProcessManager(
                    prepared.root, str(request.environment_id)
                ).status()
                if runtime["status"] != "stopped":
                    raise RuntimeViolation(
                        "SEMANTIC-RECALL-CALIBRATION-BUSY",
                        "Runtime must be stopped before semantic recall calibration",
                    )
                return semantic.calibrate()
            return {**semantic.status(), **inspect_semantic_recall_storage(prepared)}


__all__ = ("execute_maintenance",)
