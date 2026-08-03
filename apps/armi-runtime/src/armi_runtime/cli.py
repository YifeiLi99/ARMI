"""The fixed ``armi`` operational entry point for configuration and Runtime."""

from __future__ import annotations

import argparse
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
)
from armi_runtime.composition.creator_session_cli import issue_browser_bootstrap
from armi_runtime.composition.database import (
    DatabaseViolation,
    inspect_operator_schema,
    upgrade_operator_schema,
)
from armi_runtime.composition.environment import prepare_environment
from armi_runtime.composition.runtime import run_runtime
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
    database = command.add_parser("db")
    database_command = database.add_subparsers(dest="database_command", required=True)
    database_status = database_command.add_parser("status")
    database_status.add_argument("--environment-root", type=Path, required=True)
    database_upgrade = database_command.add_parser("upgrade")
    database_upgrade.add_argument("--environment-root", type=Path, required=True)
    bootstrap = command.add_parser("bootstrap")
    bootstrap_command = bootstrap.add_subparsers(
        dest="bootstrap_command",
        required=True,
    )
    bootstrap_birth = bootstrap_command.add_parser("birth")
    bootstrap_birth.add_argument("--environment-root", type=Path, required=True)
    creator_session = command.add_parser("creator-session")
    creator_session_command = creator_session.add_subparsers(
        dest="creator_session_command",
        required=True,
    )
    creator_session_issue = creator_session_command.add_parser("issue")
    creator_session_issue.add_argument("--environment-root", type=Path, required=True)
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


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    environment_root = args.environment_root
    if environment_root is None:
        configured_root = os.environ.get("ARMI_ENVIRONMENT_ROOT")
        environment_root = Path(configured_root) if configured_root else Path.cwd()
    credential_scope: dict[str, str]
    if args.command == "config":
        credential_scope = {}
    elif args.command == "db" and args.database_command == "status":
        credential_scope = {"database.status": "database.runtime"}
    elif args.command == "db":
        credential_scope = {"database.migrator": "database.migrator"}
    elif args.command == "bootstrap":
        credential_scope = {"database.birth": "database.runtime"}
    elif args.command == "creator-session":
        credential_scope = {
            "creator.bootstrap.issue": CREATOR_BEARER_LOCATOR,
        }
    elif args.command in {"status", "stop"}:
        credential_scope = {}
    else:
        credential_scope = {
            "database.runtime": "database.runtime",
            "creator.bootstrap.verify": CREATOR_BEARER_LOCATOR,
            CREATOR_CURSOR_PURPOSE: CREATOR_BEARER_LOCATOR,
            "model.request": "model.ark_api_key",
            "web.search": "model.ark_api_key",
            "codex.runner.auth": "codex.auth_json",
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
            "effective_config_digest": prepared.effective.digest.to_wire(),
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
            result = (
                inspect_operator_schema(prepared)
                if args.database_command == "status"
                else upgrade_operator_schema(prepared)
            )
        except DatabaseViolation as error:
            _safe_failure(error)
            return error.exit_code
        print(
            json.dumps(
                result.safe_view(),
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
        )
        return 0
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
    if args.command == "creator-session":
        if not sys.stdout.isatty():
            _safe_failure(
                RuntimeViolation(
                    "CLI-CREATOR-TTY",
                    "bootstrap code output requires an interactive terminal",
                )
            )
            return EXIT_INVOCATION_REJECTED
        try:
            result = issue_browser_bootstrap(prepared)
        except BrowserSessionViolation as error:
            _safe_failure(error)
            return 3 if error.status_code >= 500 else EXIT_INVOCATION_REJECTED
        print(result.bootstrap_code)
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
    return run_runtime(prepared)


__all__ = ("main",)


if __name__ == "__main__":
    raise SystemExit(main())
