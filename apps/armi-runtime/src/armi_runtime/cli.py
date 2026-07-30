"""The fixed ``armi`` operational entry point for configuration and Runtime."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from armi_kernel.application import BirthViolation

from armi_runtime.composition.bootstrap import execute_birth
from armi_runtime.composition.configuration import ConfigurationViolation
from armi_runtime.composition.database import (
    DatabaseViolation,
    inspect_operator_schema,
    upgrade_operator_schema,
)
from armi_runtime.composition.environment import prepare_environment
from armi_runtime.composition.runtime import run_runtime
from armi_runtime.composition.runtime_errors import RuntimeViolation

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
    return parser


def _safe_failure(
    error: ConfigurationViolation
    | RuntimeViolation
    | DatabaseViolation
    | BirthViolation,
) -> None:
    status = error.status if isinstance(error, DatabaseViolation) else "rejected"
    message = (
        "birth operation failed" if isinstance(error, BirthViolation) else error.message
    )
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
    credential_scope: dict[str, str]
    if args.command == "config":
        credential_scope = {}
    elif args.command == "db" and args.database_command == "status":
        credential_scope = {"database.status": "database.runtime"}
    elif args.command == "db":
        credential_scope = {"database.migrator": "database.migrator"}
    elif args.command == "bootstrap":
        credential_scope = {"database.birth": "database.runtime"}
    else:
        credential_scope = {"database.runtime": "database.runtime"}
    try:
        prepared = prepare_environment(
            args.environment_root,
            credential_scope=credential_scope,
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
    return run_runtime(prepared)


__all__ = ("main",)


if __name__ == "__main__":
    raise SystemExit(main())
