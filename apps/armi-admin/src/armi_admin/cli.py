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
    parser = argparse.ArgumentParser(prog="ARMI cli admin")
    parser.add_argument(
        "--config",
        type=Path,
        help="Bound Admin configuration; defaults to ARMI_ADMIN_CONFIG.",
    )
    commands = parser.add_subparsers(dest="operation", required=True)
    commands.add_parser("schema")
    commands.add_parser("identity")
    groups: dict[str, Any] = {}
    for operation in ADMIN_OPERATIONS:
        name = (
            operation.name.removeprefix("environment_")
            if operation.mode == "lifecycle"
            else operation.name.replace("_", "-")
        )
        parent = commands
        if operation.name.startswith(("authorization_", "invocation_")):
            group, name = operation.name.split("_", 1)
            if group not in groups:
                groups[group] = commands.add_parser(group).add_subparsers(required=True)
            parent = groups[group]
        command = parent.add_parser(
            name, help=operation.description, description=operation.description
        )
        command.set_defaults(operation_name=operation.name)
        command.add_argument("--json", type=json.loads, default={})
        command.add_argument("--idempotency-key")
        request_schema = operation.request.model_json_schema()
        fields = request_schema.get("properties", {})
        editable: list[str] = []
        for field, schema in fields.items():
            if field in {
                "environment_id",
                "environment_incarnation",
                "purpose",
                "idempotency_key",
            } or (field == "component" and operation.mode == "lifecycle"):
                continue
            if "$ref" in schema:
                schema = request_schema["$defs"][schema["$ref"].rsplit("/", 1)[1]]
            kind = schema.get("type")
            variants = schema.get("anyOf", [])
            if variants:
                non_null = [item for item in variants if item.get("type") != "null"]
                if len(non_null) == 1:
                    schema = non_null[0]
                    if "$ref" in schema:
                        schema = request_schema["$defs"][
                            schema["$ref"].rsplit("/", 1)[1]
                        ]
                    kind = schema.get("type")
            conversion = (
                int
                if kind == "integer"
                else float
                if kind == "number"
                else str
                if kind == "string"
                else json.loads
            )
            command.add_argument(
                "--" + field.replace("_", "-"),
                dest="input_" + field,
                type=conversion,
                default=argparse.SUPPRESS,
                help=schema.get("description", schema.get("title", field)),
            )
            editable.append(field)
        command.set_defaults(argument_fields=editable)
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
        authorization_locator=config.authorization_signing_key_locator,
        config_root=path.parent,
    )
    selected = next(
        item for item in ADMIN_OPERATIONS if item.name == args.operation_name
    )
    arguments: dict[str, Any] = dict(args.json)
    for field in args.argument_fields:
        if hasattr(args, "input_" + field):
            if field in arguments:
                print(
                    json.dumps(
                        {"status": "rejected", "error_code": "ADMIN-INPUT-DUPLICATE"}
                    )
                )
                return 2
            arguments[field] = getattr(args, "input_" + field)
    if args.idempotency_key is not None:
        arguments["idempotency_key"] = args.idempotency_key
    if selected.mode not in {"health", "capabilities"}:
        arguments.setdefault("environment_id", config.environment_id)
    if selected.mode in {"mutate", "lifecycle"}:
        arguments.setdefault("environment_incarnation", config.environment_incarnation)
        arguments.setdefault("purpose", f"admin.{selected.name}")
    if selected.mode == "lifecycle":
        arguments.setdefault("component", args.component)
        if selected.name != "environment_status":
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
