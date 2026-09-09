"""Agent-first interaction CLI; administrative commands live in armi-admin."""

from __future__ import annotations

import argparse
import asyncio
import base64
import json
import sys
from pathlib import Path
from typing import Any

import httpx
from armi_local_control.binding import load_client_binding
from jsonschema.exceptions import ValidationError as SchemaValidationError
from pydantic import ValidationError

from .application.interaction_catalog import interaction_routes
from .interaction_client import InteractionClient, interaction_failure


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
            if "anyOf" in spec:
                variants = [
                    item for item in spec["anyOf"] if item.get("type") != "null"
                ]
                if len(variants) == 1:
                    spec = variants[0]
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
            command.add_argument(
                "--message-file",
                type=Path,
                help="UTF-8 text file, or - to read bounded text from stdin.",
            )
            command.add_argument("--wait", action="store_true")
        if op.name in {"artifact_read", "vision_preview"}:
            command.add_argument("--output", type=Path)
    wait = groups["operation"].add_parser("wait")
    wait.add_argument("--result-ref", required=True)
    wait.add_argument("--timeout-seconds", type=float, default=20)
    media = groups["upload"].add_parser("import")
    media.add_argument("--file", type=Path, required=True)
    media.add_argument(
        "--media-type", help="Override the media type inferred from the file name."
    )
    media.add_argument("--idempotency-key", required=True)
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
    if args.group == "upload" and args.action == "import":
        return await client.import_media(
            args.file, idempotency_key=args.idempotency_key, media_type=args.media_type
        )
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
        if "message" in arguments:
            raise ValueError("INTERACTION-MESSAGE-FILE")
        if str(message_file) == "-":
            content = sys.stdin.read(262145).encode("utf-8")
        else:
            with message_file.open("rb") as stream:
                content = stream.read(262145)
        if len(content) > 262144:
            raise ValueError("INTERACTION-MESSAGE-FILE")
        arguments["message"] = content.decode("utf-8")
    if args.operation == "artifact_read" and getattr(args, "output", None) is not None:
        return await client.download_artifact(arguments, args.output)
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
        result = interaction_failure(error)
        print(json.dumps(result, ensure_ascii=False))
        return 2
    print(json.dumps(result, ensure_ascii=False, allow_nan=False))
    return 0 if result.get("transport_status", 200) < 400 else 3


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ("main", "parser")
