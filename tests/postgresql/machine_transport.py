"""Real installed CLI/MCP calls shared by isolated business journeys."""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, cast

from armi_admin.application.catalog import ADMIN_OPERATIONS
from mcp.client import Client
from mcp.client.stdio import StdioServerParameters, stdio_client


async def admin_stdio(
    binding: Path, environment: dict[str, str], name: str, request: dict[str, Any]
) -> dict[str, Any]:
    async with Client(
        stdio_client(
            StdioServerParameters(
                command=os.environ.get(
                    "ARMI_CREATOR_SYSTEM_ENTRY_POINT", sys.executable
                ),
                args=["-m", "armi_admin.mcp.entrypoint"],
                cwd=Path.cwd(),
                env={**environment, "ARMI_ADMIN_CONFIG": str(binding)},
            )
        ),
        read_timeout_seconds=60,
    ) as client:
        result = await client.call_tool(name, {"request": request})
        assert not result.is_error, (name, result)
        assert result.structured_content is not None, name
        return cast(dict[str, Any], result.structured_content)


def verify_admin_replay(
    binding: Path,
    environment: dict[str, str],
    arguments: tuple[str, ...],
    receipt: dict[str, Any],
) -> None:
    """Verify writes through a second process/transport using their durable key."""
    if "--idempotency-key" not in arguments:
        return
    command = arguments[0].replace("-", "_")
    if command in {"start", "stop", "restart"}:
        command = "environment_" + command
    elif command in {"authorization", "invocation"}:
        command += "_" + arguments[1]
    operation = next(item for item in ADMIN_OPERATIONS if item.name == command)
    config = json.loads(binding.read_text(encoding="utf-8"))
    request: dict[str, Any] = {}
    offset = 2 if arguments[0] in {"authorization", "invocation"} else 1
    for index in range(offset, len(arguments), 2):
        field, value = (
            arguments[index].removeprefix("--").replace("-", "_"),
            arguments[index + 1],
        )
        try:
            request[field] = json.loads(value)
        except ValueError:
            request[field] = value
    if operation.mode not in {"health", "capabilities"}:
        request["environment_id"] = config["environment_id"]
    if operation.mode in {"mutate", "lifecycle"}:
        request.update(
            environment_incarnation=config["environment_incarnation"],
            purpose="admin." + command,
        )
    if operation.mode == "lifecycle":
        request.setdefault("component", "environment")
    validated = operation.request.model_validate_json(json.dumps(request))
    result = asyncio.run(
        admin_stdio(binding, environment, command, validated.model_dump(mode="json"))
    )
    assert result == receipt, (
        command,
        "CLI/MCP did not return the same durable receipt",
    )


def verify_admin_observation_scenarios(
    binding: Path, environment: dict[str, str], subject_id: str
) -> None:
    config = json.loads(binding.read_text(encoding="utf-8"))
    cases: tuple[tuple[str, dict[str, Any], dict[str, Any]], ...] = (
        ("health", {}, {"status": "healthy", "database_reachable": True}),
        ("schema_status", {}, {"status": "current"}),
        ("runtime_status", {}, {"status": "running"}),
        (
            "configuration",
            {"action": "status"},
            {"activation": "effective", "restart_required": False},
        ),
        ("maintenance", {"action": "database_check"}, {"status": "current"}),
        ("maintenance", {"action": "device_bindings"}, {"collection_performed": False}),
        ("subject_snapshot", {}, {}),
        (
            "inspect_scope",
            {
                "kind": "subject",
                "object_ids": [subject_id],
                "relations": ["direct_dependents"],
            },
            {},
        ),
        (
            "doctor",
            {},
            {"collection_performed": False, "external_effects_dispatched": False},
        ),
        *[
            (
                name,
                {"operation_name": "maintenance", "idempotency_key": "birth"},
                {"state": "finished"},
            )
            for name in ("invocation_get", "invocation_wait", "invocation_reconcile")
        ],
    )
    for name, values, expected in cases:
        operation = next(item for item in ADMIN_OPERATIONS if item.name == name)
        request = dict(values)
        if operation.mode not in {"health", "capabilities"}:
            request["environment_id"] = config["environment_id"]
        if operation.mode in {"mutate", "lifecycle"}:
            request.update(
                environment_incarnation=config["environment_incarnation"],
                purpose="admin." + name,
            )
        payload = operation.request.model_validate_json(json.dumps(request)).model_dump(
            mode="json"
        )
        command = (
            name.split("_", 1)
            if name.startswith("invocation_")
            else [name.replace("_", "-")]
        )
        cli = subprocess.run(
            [
                sys.executable,
                "-m",
                "armi_admin.cli",
                "--config",
                str(binding),
                *command,
                "--json",
                json.dumps(payload),
            ],
            cwd=Path.cwd(),
            env=environment,
            capture_output=True,
            encoding="utf-8",
            timeout=60,
            check=False,
        )
        assert cli.returncode == 0, (name, cli.stdout, cli.stderr)
        replies = [
            json.loads(cli.stdout),
            asyncio.run(admin_stdio(binding, environment, name, payload)),
        ]
        for reply in replies:
            assert reply["status"] == "succeeded", (name, reply)
            result = reply["result"]
            assert all(result[key] == value for key, value in expected.items()), (
                name,
                result,
            )
            if name == "subject_snapshot":
                assert result["subject"]["subject_id"] == subject_id
                assert result["components"]
            elif name == "inspect_scope":
                assert any(
                    edge["target"]["id"] == subject_id
                    and edge["source"]["kind"] == "scene"
                    for edge in result["edges"]
                )
            elif name == "doctor":
                checks = {item["component"]: item for item in result["checks"]}
                assert checks["schema_and_acl"]["status"] == "succeeded"
                assert checks["credential.database.admin"]["status"] == "observed"
                credentials = checks["credential_check"]["evidence"]["checks"]
                assert any(
                    item["name"] == "database.runtime"
                    and item["status"] == "resolvable"
                    for item in credentials
                )
            elif name.startswith("invocation_"):
                assert result["result"]["result"]["subject_id"] == subject_id


__all__ = ("admin_stdio", "verify_admin_observation_scenarios", "verify_admin_replay")
