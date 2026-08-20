"""The fixed ``armi`` operational entry point for configuration and Runtime."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from collections.abc import Sequence
from dataclasses import replace
from pathlib import Path

from armi_adapter_esp32_display import MoodDisplayViolation, probe_device
from armi_kernel.application import BirthViolation

from armi_runtime.adapters.vision.directshow import DirectShowUsbCamera
from armi_runtime.adapters.voice.wasapi import WasapiRawAudio
from armi_runtime.composition.bootstrap import execute_birth
from armi_runtime.composition.configuration import ConfigurationViolation
from armi_runtime.composition.creator_session import (
    CREATOR_BEARER_LOCATOR,
    CREATOR_CURSOR_PURPOSE,
    CREATOR_VERIFY_PURPOSE,
)
from armi_runtime.composition.database import (
    DatabaseViolation,
    inspect_operator_schema,
    inspect_semantic_recall_storage,
    install_operator_schema,
    migrate_operator_schema,
)
from armi_runtime.composition.environment import prepare_environment
from armi_runtime.composition.napcat_process import NapCatProcessManager
from armi_runtime.composition.operational_maintenance import (
    run_artifact_retention,
    run_database_maintenance,
)
from armi_runtime.composition.qq_channel import (
    QQ_NAPCAT_ACCESS_TOKEN_LOCATOR,
    QQ_NAPCAT_ACCESS_TOKEN_PURPOSE,
    QQ_NAPCAT_EVENT_SECRET_LOCATOR,
    QQ_NAPCAT_EVENT_SECRET_PURPOSE,
)
from armi_runtime.composition.recovery import (
    create_recovery_backup,
    drill_recovery_backup,
    verify_recovery_backup,
)
from armi_runtime.composition.runtime import run_runtime
from armi_runtime.composition.runtime_capacity import run_runtime_capacity_baseline
from armi_runtime.composition.runtime_errors import RuntimeViolation
from armi_runtime.composition.runtime_process import RuntimeProcessManager
from armi_runtime.composition.semantic_recall_process import (
    SemanticRecallProcessManager,
)
from armi_runtime.interfaces.browser_sessions import BrowserSessionViolation

EXIT_INVOCATION_REJECTED = 2


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="armi")
    command = parser.add_subparsers(dest="command", required=True)
    config = command.add_parser("config")
    config_command = config.add_subparsers(dest="config_command", required=True)
    config_check = config_command.add_parser("check")
    config_check.add_argument("--environment-root", type=Path, required=True)
    runtime = command.add_parser("runtime")
    runtime_command = runtime.add_subparsers(dest="runtime_command", required=True)
    runtime_start = runtime_command.add_parser("start")
    runtime_start.add_argument("--environment-root", type=Path, required=True)
    runtime_start.add_argument("--creator-web-resources", type=Path)
    for lifecycle_command in ("start", "status", "stop"):
        lifecycle = command.add_parser(lifecycle_command)
        lifecycle.add_argument("--environment-root", type=Path)
        if lifecycle_command == "start":
            lifecycle.add_argument("--creator-web-resources", type=Path)
    creator = command.add_parser("creator")
    creator_command = creator.add_subparsers(dest="creator_command", required=True)
    creator_send = creator_command.add_parser("send")
    creator_send.add_argument("--environment-root", type=Path)
    creator_source = creator_send.add_mutually_exclusive_group(required=True)
    creator_source.add_argument("--message")
    creator_source.add_argument("--message-file")
    creator_send.add_argument("--idempotency-key")
    other_human = command.add_parser("other-human")
    other_human_command = other_human.add_subparsers(
        dest="other_human_command", required=True
    )
    other_human_party = other_human_command.add_parser("party")
    other_human_party_command = other_human_party.add_subparsers(
        dest="other_human_party_command", required=True
    )
    other_human_party_register = other_human_party_command.add_parser("register")
    other_human_party_register.add_argument("--environment-root", type=Path)
    other_human_party_register.add_argument("--party-key", required=True)
    other_human_party_register.add_argument("--display-label", required=True)
    other_human_scene = other_human_command.add_parser("scene")
    other_human_scene_command = other_human_scene.add_subparsers(
        dest="other_human_scene_command", required=True
    )
    other_human_scene_set = other_human_scene_command.add_parser("set")
    other_human_scene_set.add_argument("--environment-root", type=Path)
    other_human_scene_set.add_argument("--party-key", required=True)
    other_human_scene_set.add_argument("--scene-key", required=True)
    other_human_scene_set.add_argument(
        "--status", choices=("open", "closed"), required=True
    )
    other_human_send = other_human_command.add_parser("send")
    other_human_send.add_argument("--environment-root", type=Path)
    other_human_send.add_argument("--party-key", required=True)
    other_human_send.add_argument("--scene-key", default="default")
    other_human_source = other_human_send.add_mutually_exclusive_group(required=True)
    other_human_source.add_argument("--message")
    other_human_source.add_argument("--message-file")
    other_human_send.add_argument("--idempotency-key")
    other_human_rights = other_human_command.add_parser("data-rights")
    other_human_rights_command = other_human_rights.add_subparsers(
        dest="other_human_rights_command", required=True
    )
    other_human_rights_request = other_human_rights_command.add_parser("request")
    other_human_rights_request.add_argument("--environment-root", type=Path)
    other_human_rights_request.add_argument("--party-key", required=True)
    other_human_rights_request.add_argument(
        "--order-kind",
        choices=("stop_contact", "stop_use", "delete_related"),
        required=True,
    )
    other_human_rights_request.add_argument("--idempotency-key")
    other_human_rights_list = other_human_rights_command.add_parser("list")
    other_human_rights_list.add_argument("--environment-root", type=Path)
    other_human_rights_list.add_argument("--party-key", required=True)
    other_human_rights_get = other_human_rights_command.add_parser("get")
    other_human_rights_get.add_argument("--environment-root", type=Path)
    other_human_rights_get.add_argument("--party-key", required=True)
    other_human_rights_get.add_argument("--order-id", required=True)
    channel = command.add_parser("channel")
    channel_command = channel.add_subparsers(dest="channel_command", required=True)
    channel_qq = channel_command.add_parser("qq")
    channel_qq_command = channel_qq.add_subparsers(
        dest="channel_qq_command",
        required=True,
    )
    for channel_lifecycle_command in ("open", "start", "status"):
        channel_lifecycle = channel_qq_command.add_parser(channel_lifecycle_command)
        channel_lifecycle.add_argument("--environment-root", type=Path)
        if channel_lifecycle_command == "open":
            channel_lifecycle.add_argument(
                "--auto-login",
                action="store_true",
                help=(
                    "put the NapCat WebUI token in the browser URL query to log in "
                    "automatically; this can expose it in browser or process history"
                ),
            )
    voice = command.add_parser("voice")
    voice_command = voice.add_subparsers(dest="voice_command", required=True)
    for voice_action in ("devices", "status", "start", "stop"):
        voice_action_parser = voice_command.add_parser(voice_action)
        voice_action_parser.add_argument("--environment-root", type=Path)
    vision = command.add_parser("vision")
    vision_command = vision.add_subparsers(dest="vision_command", required=True)
    for vision_action in ("devices", "status", "start", "stop", "observe"):
        vision_action_parser = vision_command.add_parser(vision_action)
        vision_action_parser.add_argument("--environment-root", type=Path)
    device = command.add_parser("device")
    device_command = device.add_subparsers(dest="device_command", required=True)
    mood_display = device_command.add_parser("mood-display")
    mood_display_command = mood_display.add_subparsers(
        dest="mood_display_command", required=True
    )
    mood_display_probe = mood_display_command.add_parser("probe")
    mood_display_probe.add_argument("--port", required=True)
    database = command.add_parser("db")
    database_command = database.add_subparsers(dest="database_command", required=True)
    database_status = database_command.add_parser("status")
    database_status.add_argument("--environment-root", type=Path, required=True)
    database_install = database_command.add_parser("install")
    database_install.add_argument("--environment-root", type=Path, required=True)
    database_migrate = database_command.add_parser("migrate")
    database_migrate.add_argument("--environment-root", type=Path, required=True)
    database_migrate.add_argument("--apply", action="store_true", required=True)
    database_maintain = database_command.add_parser("maintain")
    database_maintain.add_argument("--environment-root", type=Path, required=True)
    database_maintain.add_argument("--apply", action="store_true", required=True)
    artifacts = command.add_parser("artifacts")
    artifacts_command = artifacts.add_subparsers(
        dest="artifacts_command",
        required=True,
    )
    artifacts_cleanup = artifacts_command.add_parser("cleanup")
    artifacts_cleanup.add_argument("--environment-root", type=Path, required=True)
    artifacts_cleanup.add_argument("--apply", action="store_true")
    recovery = command.add_parser("recovery")
    recovery_command = recovery.add_subparsers(
        dest="recovery_command",
        required=True,
    )
    recovery_create = recovery_command.add_parser("create")
    recovery_create.add_argument("--environment-root", type=Path, required=True)
    recovery_create.add_argument("--postgresql-client-root", type=Path, required=True)
    recovery_create.add_argument("--destination", type=Path, required=True)
    recovery_verify = recovery_command.add_parser("verify")
    recovery_verify.add_argument("--bundle", type=Path, required=True)
    recovery_drill = recovery_command.add_parser("drill")
    recovery_drill.add_argument("--bundle", type=Path, required=True)
    recovery_drill.add_argument("--quarantine-root", type=Path, required=True)
    recovery_drill.add_argument("--target-conninfo-file", type=Path, required=True)
    recovery_drill.add_argument("--postgresql-client-root", type=Path, required=True)
    recovery_drill.add_argument("--apply", action="store_true", required=True)
    capacity = command.add_parser("capacity")
    capacity_command = capacity.add_subparsers(
        dest="capacity_command",
        required=True,
    )
    capacity_baseline = capacity_command.add_parser("baseline")
    capacity_baseline.add_argument("--environment-root", type=Path, required=True)
    capacity_baseline.add_argument("--duration-seconds", type=int, default=60)
    capacity_baseline.add_argument("--sample-interval-seconds", type=int, default=5)
    capacity_baseline.add_argument(
        "--max-rss-growth-bytes",
        type=int,
        default=67_108_864,
    )
    capacity_baseline.add_argument("--max-backlog-growth", type=int, default=0)
    capacity_baseline.add_argument(
        "--max-open-backlog-age-seconds",
        type=int,
        default=120,
    )
    capacity_baseline.add_argument(
        "--max-log-growth-bytes",
        type=int,
        default=16_777_216,
    )
    bootstrap = command.add_parser("bootstrap")
    bootstrap_command = bootstrap.add_subparsers(
        dest="bootstrap_command",
        required=True,
    )
    bootstrap_birth = bootstrap_command.add_parser("birth")
    bootstrap_birth.add_argument("--environment-root", type=Path, required=True)
    semantic_recall = command.add_parser("semantic-recall")
    semantic_recall_command = semantic_recall.add_subparsers(
        dest="semantic_recall_command", required=True
    )
    semantic_install = semantic_recall_command.add_parser("install")
    semantic_install.add_argument("--environment-root", type=Path, required=True)
    semantic_install.add_argument("--approved-official-direct", action="store_true")
    semantic_calibrate = semantic_recall_command.add_parser("calibrate")
    semantic_calibrate.add_argument("--environment-root", type=Path, required=True)
    semantic_status = semantic_recall_command.add_parser("status")
    semantic_status.add_argument("--environment-root", type=Path, required=True)
    return parser


def _safe_failure(
    error: ConfigurationViolation
    | RuntimeViolation
    | DatabaseViolation
    | BirthViolation
    | BrowserSessionViolation,
) -> None:
    status = error.status if isinstance(error, DatabaseViolation) else "rejected"
    if isinstance(error, BirthViolation):
        message = "birth operation failed"
    elif isinstance(error, BrowserSessionViolation):
        message = "creator session operation failed"
    else:
        message = error.message
    print(
        json.dumps(
            {"status": status, "code": error.code, "message": message},
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ),
        file=sys.stderr,
    )


def _creator_message(args: argparse.Namespace) -> str:
    if args.message is not None:
        return str(args.message)
    source = str(args.message_file)
    try:
        if source == "-":
            return sys.stdin.read()
        path = Path(source)
        if not path.is_file() or path.is_symlink():
            raise OSError
        return path.read_text(encoding="utf-8", errors="strict")
    except (OSError, UnicodeError) as exc:
        raise RuntimeViolation(
            "CLI-CREATOR-MESSAGE-FILE",
            "creator message file is unavailable",
        ) from exc


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.command == "voice" and args.voice_command == "devices":
        try:
            devices = WasapiRawAudio.devices()
            result = {
                "status": "available",
                "devices": [
                    {
                        "host_api": item.host_api,
                        "name": item.name,
                        "input_channels": item.input_channels,
                        "output_channels": item.output_channels,
                        "default_sample_rate": item.default_sample_rate,
                    }
                    for item in devices
                ],
            }
        except Exception as error:
            result = {
                "status": "unavailable",
                "reason_code": getattr(error, "code", "VOICE-AUDIO-UNAVAILABLE"),
            }
        print(
            json.dumps(
                result, ensure_ascii=False, sort_keys=True, separators=(",", ":")
            )
        )
        return 0 if result["status"] == "available" else 3
    if args.command == "vision" and args.vision_command == "devices":
        try:
            devices = DirectShowUsbCamera.devices()
            result = {
                "status": "available",
                "devices": [
                    {
                        "name": item.name,
                        "device_path": item.device_path,
                        "usb_location_id": item.usb_location_id,
                        "yaml": {
                            "device": {
                                "name": item.name,
                                "device_path": item.device_path,
                                "usb_location_id": item.usb_location_id,
                            }
                        },
                    }
                    for item in devices
                ],
            }
        except Exception as error:
            result = {
                "status": "unavailable",
                "reason_code": getattr(error, "code", "VISION-ENUMERATION-FAILED"),
            }
        print(
            json.dumps(
                result, ensure_ascii=False, sort_keys=True, separators=(",", ":")
            )
        )
        return 0 if result["status"] == "available" else 3
    if args.command == "device":
        try:
            result = probe_device(str(args.port))
        except (MoodDisplayViolation, OSError) as error:
            code = getattr(error, "code", "MOOD-DISPLAY-UNAVAILABLE")
            print(
                json.dumps(
                    {"status": "unavailable", "code": code},
                    sort_keys=True,
                    separators=(",", ":"),
                ),
                file=sys.stderr,
            )
            return 3
        print(
            json.dumps(
                {
                    "status": "available",
                    "device_id": result.device_id,
                    "firmware_version": result.firmware_version,
                    "protocol_version": result.protocol_version,
                    "boot_id": result.boot_id,
                },
                sort_keys=True,
                separators=(",", ":"),
            )
        )
        return 0
    if args.command == "recovery" and args.recovery_command in {"verify", "drill"}:
        try:
            if args.recovery_command == "verify":
                recovery_result = verify_recovery_backup(args.bundle)
            else:
                recovery_result = drill_recovery_backup(
                    args.bundle,
                    quarantine_root=args.quarantine_root,
                    target_conninfo_file=args.target_conninfo_file,
                    postgresql_client_root=args.postgresql_client_root,
                )
        except RuntimeViolation as error:
            _safe_failure(error)
            return 4
        print(
            json.dumps(
                recovery_result.safe_view(),
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
        )
        return 0
    environment_root = args.environment_root
    if environment_root is None:
        configured_root = os.environ.get("ARMI_ENVIRONMENT_ROOT")
        environment_root = Path(configured_root) if configured_root else Path.cwd()
    credential_scope: dict[str, str]
    if args.command == "semantic-recall":
        credential_scope = (
            {"database.status": "database.runtime"}
            if args.semantic_recall_command == "status"
            else {}
        )
    elif args.command == "config":
        credential_scope = {}
    elif args.command == "db" and args.database_command == "status":
        credential_scope = {"database.status": "database.runtime"}
    elif args.command == "db" and args.database_command == "maintain":
        credential_scope = {"database.maintenance": "database.migrator"}
    elif args.command == "db" and args.database_command == "migrate":
        credential_scope = {"database.migrate": "database.migrator"}
    elif args.command == "db":
        credential_scope = {"database.migrator": "database.migrator"}
    elif args.command == "artifacts":
        credential_scope = {
            "database.artifact-maintenance": "database.runtime",
        }
    elif args.command == "recovery":
        credential_scope = {"database.recovery": "database.migrator"}
    elif args.command == "bootstrap":
        credential_scope = {"database.birth": "database.runtime"}
    elif args.command == "channel":
        credential_scope = (
            {}
            if args.channel_qq_command == "open"
            else {
                QQ_NAPCAT_ACCESS_TOKEN_PURPOSE: QQ_NAPCAT_ACCESS_TOKEN_LOCATOR,
                **(
                    {QQ_NAPCAT_EVENT_SECRET_PURPOSE: (QQ_NAPCAT_EVENT_SECRET_LOCATOR)}
                    if args.channel_qq_command == "start"
                    else {}
                ),
            }
        )
    elif args.command == "status":
        credential_scope = {
            QQ_NAPCAT_ACCESS_TOKEN_PURPOSE: QQ_NAPCAT_ACCESS_TOKEN_LOCATOR,
        }
    elif args.command in {
        "stop",
        "capacity",
        "creator",
        "other-human",
        "voice",
        "vision",
    }:
        credential_scope = {}
    else:
        credential_scope = {
            "database.runtime": "database.runtime",
            CREATOR_VERIFY_PURPOSE: CREATOR_BEARER_LOCATOR,
            CREATOR_CURSOR_PURPOSE: CREATOR_BEARER_LOCATOR,
            "model.request": "model.ark_api_key",
            "speech.recognition": "speech.volc_credentials",
            "web.search": "model.ark_api_key",
            "codex.runner.auth": "codex.auth_json",
            QQ_NAPCAT_ACCESS_TOKEN_PURPOSE: QQ_NAPCAT_ACCESS_TOKEN_LOCATOR,
            QQ_NAPCAT_EVENT_SECRET_PURPOSE: QQ_NAPCAT_EVENT_SECRET_LOCATOR,
        }
    try:
        configuration_environment = dict(os.environ)
        configuration_environment.pop("ARMI_ENVIRONMENT_ROOT", None)
        prepared = prepare_environment(
            environment_root,
            credential_scope=credential_scope,
            environment=configuration_environment,
        )
    except (ConfigurationViolation, RuntimeViolation) as error:
        _safe_failure(error)
        return EXIT_INVOCATION_REJECTED
    if args.command == "config":
        result = {
            "status": "pass",
            "schema_version": prepared.effective.config.schema_version,
            "config": prepared.effective.redacted_view(),
        }
        print(
            json.dumps(
                result,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
        )
        return 0
    if args.command == "semantic-recall":
        manager = SemanticRecallProcessManager(
            prepared.root,
            enabled=prepared.effective.config.model.semantic_recall_enabled,
        )
        try:
            if args.semantic_recall_command == "install":
                result = manager.install(
                    approved_official_direct=bool(args.approved_official_direct)
                )
            elif args.semantic_recall_command == "calibrate":
                runtime_status = RuntimeProcessManager(
                    prepared.root,
                    str(prepared.effective.config.environment.environment_id),
                ).status()
                if runtime_status["status"] != "stopped":
                    raise RuntimeViolation(
                        "SEMANTIC-RECALL-CALIBRATION-BUSY",
                        "Runtime must be stopped before semantic recall calibration",
                    )
                result = manager.calibrate()
            else:
                result = {
                    **manager.status(),
                    **inspect_semantic_recall_storage(prepared),
                }
        except RuntimeViolation as error:
            _safe_failure(error)
            return 3
        print(
            json.dumps(
                result,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
        )
        return 0
    if args.command == "db":
        try:
            if args.database_command == "status":
                result = inspect_operator_schema(prepared)
            elif args.database_command == "install":
                result = install_operator_schema(prepared)
            elif args.database_command == "migrate":
                result = migrate_operator_schema(prepared)
            else:
                result = run_database_maintenance(prepared)
        except (DatabaseViolation, RuntimeViolation) as error:
            _safe_failure(error)
            return error.exit_code if isinstance(error, DatabaseViolation) else 4
        print(
            json.dumps(
                result.safe_view(),
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
        )
        return 0
    if args.command == "artifacts":
        try:
            result = asyncio.run(
                run_artifact_retention(prepared, apply=bool(args.apply))
            )
        except RuntimeViolation as error:
            _safe_failure(error)
            return 4 if args.apply else 3
        print(
            json.dumps(
                result.safe_view(),
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
        )
        return 0
    if args.command == "recovery":
        try:
            result = create_recovery_backup(
                prepared,
                postgresql_client_root=args.postgresql_client_root,
                destination=args.destination,
            )
        except RuntimeViolation as error:
            _safe_failure(error)
            return 4
        print(
            json.dumps(
                result.safe_view(),
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
        )
        return 0
    if args.command == "capacity":
        manager = RuntimeProcessManager(
            prepared.root,
            str(prepared.effective.config.environment.environment_id),
        )
        try:
            result = run_runtime_capacity_baseline(
                manager.status,
                duration_seconds=args.duration_seconds,
                sample_interval_seconds=args.sample_interval_seconds,
                max_rss_growth_bytes=args.max_rss_growth_bytes,
                max_backlog_growth=args.max_backlog_growth,
                max_open_backlog_age_seconds=args.max_open_backlog_age_seconds,
                max_log_growth_bytes=args.max_log_growth_bytes,
            )
        except RuntimeViolation as error:
            _safe_failure(error)
            return 3
        print(
            json.dumps(
                result.safe_view(),
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
        )
        return 0 if result.status == "pass" else 4
    if args.command == "bootstrap":
        try:
            result = execute_birth(prepared)
        except BirthViolation as error:
            _safe_failure(error)
            return EXIT_INVOCATION_REJECTED
        print(
            json.dumps(
                result.safe_view(),
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
        )
        return 0
    if args.command == "channel":
        manager = NapCatProcessManager(prepared)
        try:
            if args.channel_qq_command == "start":
                result = manager.start().safe_view()
            elif args.channel_qq_command == "open":
                result = manager.open_webui(auto_login=args.auto_login).safe_view()
            else:
                result = manager.status().safe_view()
        except RuntimeViolation as error:
            _safe_failure(error)
            return 3
        print(
            json.dumps(
                result,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
        )
        return 0
    if args.command == "voice":
        process = RuntimeProcessManager(
            prepared.root,
            str(prepared.effective.config.environment.environment_id),
        )
        try:
            result = process.voice(args.voice_command)
        except RuntimeViolation as error:
            _safe_failure(error)
            return 3
        print(
            json.dumps(
                result,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
        )
        return 0 if result.get("state") not in {"unavailable", "failed"} else 3
    if args.command == "vision":
        process = RuntimeProcessManager(
            prepared.root,
            str(prepared.effective.config.environment.environment_id),
        )
        try:
            result = process.vision(args.vision_command)
        except RuntimeViolation as error:
            _safe_failure(error)
            return 3
        print(
            json.dumps(
                result, ensure_ascii=False, sort_keys=True, separators=(",", ":")
            )
        )
        return 0 if result.get("state") not in {"unavailable", "failed"} else 3
    if args.command in {"start", "status", "stop"}:
        process = RuntimeProcessManager(
            prepared.root,
            str(prepared.effective.config.environment.environment_id),
        )
        semantic_recall = SemanticRecallProcessManager(
            prepared.root,
            enabled=prepared.effective.config.model.semantic_recall_enabled,
        )
        try:
            if args.command == "start":
                try:
                    semantic_status = semantic_recall.start()
                except RuntimeViolation as error:
                    semantic_status = {
                        "status": "unavailable",
                        "reason_code": error.code,
                    }
                try:
                    result = (
                        process.start()
                        if args.creator_web_resources is None
                        else process.start(
                            creator_web_resources=args.creator_web_resources,
                        )
                    )
                except Exception:
                    semantic_recall.stop()
                    raise
                channel_start_status = "attention"
                try:
                    channel_result = NapCatProcessManager(prepared).start()
                    channel_health = channel_result.health.safe_view()
                    channel_start_status = channel_result.status
                except RuntimeViolation as error:
                    failed_health = NapCatProcessManager(prepared).status()
                    channel_health = replace(
                        failed_health,
                        reason_codes=tuple(
                            dict.fromkeys(
                                (
                                    *failed_health.reason_codes,
                                    error.code.replace("-", "_"),
                                )
                            )
                        ),
                    ).safe_view()
                result = {
                    **result,
                    "channels": {"qq": channel_health},
                    "channel_start": {"qq": channel_start_status},
                    "semantic_recall": semantic_status,
                }
            elif args.command == "status":
                result = {
                    **process.status(),
                    "channels": {
                        "qq": NapCatProcessManager(prepared).status().safe_view()
                    },
                    "semantic_recall": semantic_recall.status(),
                }
            else:
                result = process.stop()
                result = {**result, "semantic_recall": semantic_recall.stop()}
        except RuntimeViolation as error:
            _safe_failure(error)
            return 3
        print(
            json.dumps(
                result,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
        )
        return 0
    if args.command == "creator":
        process = RuntimeProcessManager(
            prepared.root,
            str(prepared.effective.config.environment.environment_id),
        )
        try:
            result = process.send_creator_input(
                _creator_message(args),
                idempotency_key=args.idempotency_key,
            )
        except RuntimeViolation as error:
            _safe_failure(error)
            return 3
        print(
            json.dumps(
                result,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
        )
        return 0
    if args.command == "other-human":
        process = RuntimeProcessManager(
            prepared.root,
            str(prepared.effective.config.environment.environment_id),
        )
        action: str
        payload: dict[str, object]
        if args.other_human_command == "party":
            action = "party_register"
            payload = {
                "party_key": args.party_key,
                "display_label": args.display_label,
            }
        elif args.other_human_command == "scene":
            action = "scene_set"
            payload = {
                "party_key": args.party_key,
                "scene_key": args.scene_key,
                "status": args.status,
            }
        elif args.other_human_command == "send":
            action = "message_send"
            payload = {
                "party_key": args.party_key,
                "scene_key": args.scene_key,
                "message": _creator_message(args),
                "idempotency_key": args.idempotency_key or f"cli-{os.urandom(16).hex()}",
            }
        elif args.other_human_rights_command == "request":
            action = "data_rights_request"
            payload = {
                "party_key": args.party_key,
                "order_kind": args.order_kind,
                "idempotency_key": args.idempotency_key or f"cli-{os.urandom(16).hex()}",
            }
        elif args.other_human_rights_command == "list":
            action = "data_rights_list"
            payload = {"party_key": args.party_key}
        else:
            action = "data_rights_get"
            payload = {"party_key": args.party_key, "order_id": args.order_id}
        try:
            result = process.other_human(action, payload)
        except RuntimeViolation as error:
            _safe_failure(error)
            return 3
        print(
            json.dumps(
                result,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
        )
        return 0
    return run_runtime(
        prepared,
        creator_web_resources=args.creator_web_resources,
    )


__all__ = ("main",)


if __name__ == "__main__":
    raise SystemExit(main())
