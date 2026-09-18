"""Real installed CLI/MCP calls shared by isolated business journeys."""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any, cast

from armi_admin.application.catalog import ADMIN_OPERATIONS
from mcp.client import Client
from mcp.client.stdio import StdioServerParameters, stdio_client


async def admin_stdio(
    binding: Path, environment: dict[str, str], name: str, request: dict[str, Any]
) -> dict[str, Any]:
    mcp_binding = binding.parent / "mcp-admin.yaml"
    mcp_binding.write_text(
        json.dumps(
            {
                "schema_version": "armi.mcp-binding.v1",
                "admin_config": str(binding),
            }
        ),
        encoding="utf-8",
    )
    async with Client(
        stdio_client(
            StdioServerParameters(
                command=os.environ.get(
                    "ARMI_CREATOR_SYSTEM_ENTRY_POINT", sys.executable
                ),
                args=["-m", "armi_app", "mcp", "--config", str(mcp_binding)],
                cwd=Path.cwd(),
                env={**environment, "ARMI_ADMIN_CONFIG": str(binding)},
            )
        ),
        read_timeout_seconds=60,
    ) as client:
        result = await client.call_tool(
            "admin_" + name,
            {
                key: value
                for key, value in request.items()
                if key not in {"environment_id", "environment_incarnation", "purpose"}
            },
        )
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


__all__ = ("admin_stdio", "verify_admin_replay")
