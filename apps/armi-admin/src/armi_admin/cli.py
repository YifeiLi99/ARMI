"""Structured administrative CLI over the same application service as MCP."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any
from uuid import uuid7

from pydantic import ValidationError

from armi_admin.application import (
    AdminConfigError,
    AdminCredentialPort,
    AdminPackageIdentityError,
    AdminSecretError,
    admin_package_set_digest,
    load_admin_config,
    verify_admin_package_set,
)
from armi_admin.application.catalog import ADMIN_OPERATIONS
from armi_admin.composition import bootstrap_admin


def _run(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="armi-admin")
    parser.add_argument(
        "--config",
        type=Path,
        help="Bound Admin configuration; defaults to ARMI_ADMIN_CONFIG.",
    )
    commands = parser.add_subparsers(dest="operation", required=True)
    commands.add_parser("schema")
    commands.add_parser("identity")
    for operation in ADMIN_OPERATIONS:
        name = (
            operation.name.removeprefix("environment_")
            if operation.mode == "lifecycle"
            else operation.name.replace("_", "-")
        )
        command = commands.add_parser(
            name, help=operation.description, description=operation.description
        )
        command.set_defaults(operation_name=operation.name)
        command.add_argument("--json", type=json.loads, default={})
        command.add_argument("--idempotency-key")
        if operation.mode == "lifecycle":
            command.add_argument(
                "--component",
                choices=("environment", "runtime", "postgresql", "semantic-recall"),
                default="environment",
            )
    args = parser.parse_args(argv)
    if args.operation == "identity":
        print(json.dumps({"package_set_digest": admin_package_set_digest()}))
        return 0
    if args.operation == "schema":
        print(
            json.dumps(
                {
                    item.name: item.request.model_json_schema()
                    for item in ADMIN_OPERATIONS
                },
                ensure_ascii=False,
            )
        )
        return 0
    environment = dict(os.environ)
    if args.config is not None:
        environment["ARMI_ADMIN_CONFIG"] = str(args.config.resolve())
    config, path = load_admin_config(environment)
    verify_admin_package_set(config.expected.package_set_digest)
    credentials = AdminCredentialPort(
        locator=config.locator,
        migrator_locator=config.migrator_locator,
        preview_locator=config.preview_locator,
        config_root=path.parent,
    )
    selected = next(
        item for item in ADMIN_OPERATIONS if item.name == args.operation_name
    )
    arguments: dict[str, Any] = dict(args.json)
    if selected.mode not in {"health", "capabilities"}:
        arguments.setdefault("environment_id", config.environment_id)
    if selected.mode in {"mutate", "lifecycle"}:
        arguments.setdefault("environment_incarnation", config.environment_incarnation)
        arguments.setdefault("purpose", f"admin.{selected.name}")
        if args.idempotency_key is not None:
            arguments["idempotency_key"] = args.idempotency_key
    if selected.mode == "lifecycle":
        arguments.setdefault("component", args.component)
        arguments.setdefault("idempotency_key", f"cli-{uuid7()}")
    try:
        request = selected.request.model_validate_json(json.dumps(arguments))
    except ValidationError:
        print(json.dumps({"status": "rejected", "error_code": "ADMIN-INPUT"}))
        return 2
    composition = bootstrap_admin(config, credentials)
    try:
        result = selected.invoke(composition.service, request)
        print(result.model_dump_json())
        return 0 if result.status == "succeeded" else 3
    finally:
        composition.close()


def main(argv: list[str] | None = None) -> int:
    try:
        return _run(argv)
    except (AdminConfigError, AdminPackageIdentityError, AdminSecretError) as error:
        print(json.dumps({"status": "rejected", "error_code": str(error)}))
        return 2
    except OSError, ValueError, TypeError:
        print(json.dumps({"status": "rejected", "error_code": "ADMIN-INPUT"}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ("main",)
