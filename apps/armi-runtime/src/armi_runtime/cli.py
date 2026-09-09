"""Agent-first interaction CLI; administrative commands live in armi-admin."""

from __future__ import annotations

import argparse
import asyncio
import base64
import json
from pathlib import Path
from typing import Any

import httpx
from armi_local_control.binding import load_client_binding
from jsonschema.exceptions import ValidationError as SchemaValidationError
from pydantic import ValidationError

from .interaction_client import InteractionClient
from .interfaces.interaction_catalog import interaction_routes


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(
        prog="armi",
        description="Creator-delegated interaction. Administrative operations: armi-admin.",
    )
    result.add_argument(
        "--config",
        type=Path,
        help="Private client binding; defaults to ARMI_CLIENT_CONFIG.",
    )
    commands = result.add_subparsers(dest="group", required=True)
    commands.add_parser(
        "capabilities",
        help="Discover the bound Runtime's authorized interaction operations.",
    )
    commands.add_parser(
        "schema", help="Print all local interaction request schemas without connecting."
    )
    groups: dict[str, Any] = {}
    for route in interaction_routes():
        op = route.operation
        if op.group not in groups:
            groups[op.group] = commands.add_parser(op.group).add_subparsers(
                dest="action", required=True
            )
        command = groups[op.group].add_parser(op.action)
        command.set_defaults(operation=op.name)
        command.add_argument(
            "--json",
            type=json.loads,
            help="Complete structured arguments; do not combine with individual arguments.",
        )
        properties = dict(op.input_schema)["properties"]
        for name, spec in properties.items():
            kind = spec.get("type")
            conversion = (
                int
                if kind == "integer"
                else float
                if kind == "number"
                else json.loads
                if kind in {"object", "array", "boolean"} or "anyOf" in spec
                else str
            )
            command.add_argument(
                "--" + name.replace("_", "-"),
                type=conversion,
                default=argparse.SUPPRESS,
            )
        if op.name == "message_send":
            command.add_argument("--message-file", type=Path)
            command.add_argument("--wait", action="store_true")
        if op.name in {"artifact_read", "vision_preview"}:
            command.add_argument("--output", type=Path)
    wait = groups["operation"].add_parser("wait")
    wait.add_argument("--result-ref", required=True)
    wait.add_argument("--timeout-seconds", type=float, default=20)
    return result


async def _execute(args: argparse.Namespace) -> dict[str, Any]:
    routes = interaction_routes()
    if args.group == "schema":
        return {
            "operations": [
                {
                    "name": route.operation.name,
                    "input_schema": dict(route.operation.input_schema),
                }
                for route in routes
            ]
        }
    client = InteractionClient(load_client_binding(args.config))
    if args.group == "capabilities":
        return await client.invoke("capabilities", {})
    if args.group == "operation" and args.action == "wait":
        return await client.wait(args.result_ref, timeout_seconds=args.timeout_seconds)
    route = next(route for route in routes if route.operation.name == args.operation)
    arguments = {
        name: getattr(args, name)
        for name in route.operation.input_schema["properties"]
        if hasattr(args, name)
    }
    if args.json is not None:
        if arguments or getattr(args, "message_file", None) is not None:
            raise ValueError("INTERACTION-ARGUMENT-SOURCES")
        arguments = args.json
    message_file = getattr(args, "message_file", None)
    if message_file is not None:
        if "message" in arguments or message_file.stat().st_size > 262144:
            raise ValueError("INTERACTION-MESSAGE-FILE")
        arguments["message"] = message_file.read_text(encoding="utf-8")
    outcome = await client.invoke(args.operation, arguments)
    if (
        getattr(args, "wait", False)
        and outcome.get("result", {}).get("status") == "accepted"
    ):
        outcome = await client.wait(outcome["result"]["result_ref"])
    output = getattr(args, "output", None)
    if output is not None and "artifact" in outcome:
        content = base64.b64decode(outcome["artifact"]["content"], validate=True)
        with output.open("xb") as stream:
            stream.write(content)
        outcome["artifact"] = {
            "path": str(output.resolve()),
            "size_bytes": len(content),
            "media_type": outcome["artifact"]["media_type"],
        }
    return outcome


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        result = asyncio.run(_execute(args))
    except (
        ValueError,
        OSError,
        ValidationError,
        SchemaValidationError,
        httpx.HTTPError,
    ) as error:
        result = {
            "status": "unavailable"
            if isinstance(error, httpx.HTTPError)
            else "rejected",
            "error_code": "INTERACTION-DEPENDENCY"
            if isinstance(error, httpx.HTTPError)
            else "INTERACTION-INPUT",
        }
        print(json.dumps(result, ensure_ascii=False))
        return 2
    print(json.dumps(result, ensure_ascii=False, allow_nan=False))
    return 0 if result.get("transport_status", 200) < 400 else 3


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ("main", "parser")
