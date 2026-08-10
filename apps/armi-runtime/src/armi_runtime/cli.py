"""The fixed ``armi`` operational entry point for configuration and Runtime."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from collections.abc import Sequence
from pathlib import Path

from armi_kernel.application import BirthViolation

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
    install_operator_schema,
    migrate_operator_schema,
)
from armi_runtime.composition.environment import prepare_environment
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
    for lifecycle_command in ("start", "status", "stop"):
        lifecycle = command.add_parser(lifecycle_command)
        lifecycle.add_argument("--environment-root", type=Path)
    creator = command.add_parser("creator")
    creator_command = creator.add_subparsers(dest="creator_command", required=True)
    creator_send = creator_command.add_parser("send")
    creator_send.add_argument("--environment-root", type=Path)
    creator_source = creator_send.add_mutually_exclusive_group(required=True)
    creator_source.add_argument("--message")
    creator_source.add_argument("--message-file")
    creator_send.add_argument("--idempotency-key")
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
    if args.command == "config":
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
    elif args.command in {"status", "stop", "capacity", "creator"}:
        credential_scope = {}
    else:
        credential_scope = {
            "database.runtime": "database.runtime",
            CREATOR_VERIFY_PURPOSE: CREATOR_BEARER_LOCATOR,
            CREATOR_CURSOR_PURPOSE: CREATOR_BEARER_LOCATOR,
            "model.request": "model.ark_api_key",
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
            "composition_digest": prepared.composition.digest,
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
    if args.command in {"start", "status", "stop"}:
        process = RuntimeProcessManager(
            prepared.root,
            str(prepared.effective.config.environment.environment_id),
        )
        try:
            result = getattr(process, args.command)()
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
    return run_runtime(prepared)


__all__ = ("main",)


if __name__ == "__main__":
    raise SystemExit(main())
