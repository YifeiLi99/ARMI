"""Interaction tool adapter for the unified product MCP server."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx
from armi_runtime.machine import (
    InteractionClient,
    interaction_failure,
    interaction_routes,
)
from jsonschema.exceptions import ValidationError
from mcp.server.mcpserver import Context
from mcp.types import CallToolResult, TextContent, Tool, ToolAnnotations


class InteractionTools:
    def __init__(self, client: Callable[[], InteractionClient]) -> None:
        self._client = client

    async def list_tools(self) -> list[Tool]:
        tools = [
            Tool(
                name=route.operation.name,
                description=f"{route.operation.group}: {route.operation.action}. Uses the bound Creator delegate and the formal owner boundary.",
                input_schema=dict(route.operation.input_schema),
                output_schema=dict(route.operation.output_schema),
                annotations=ToolAnnotations(
                    read_only_hint=not route.operation.mutating,
                    destructive_hint=route.operation.name
                    in {"data_rights_request", "data_rights_retry"},
                    idempotent_hint=not route.operation.mutating,
                    open_world_hint=route.operation.mutating,
                ),
            )
            for route in interaction_routes()
        ]
        tools.append(
            Tool(
                name="capabilities",
                description="Read the bound environment and authorized operation catalog.",
                input_schema={
                    "type": "object",
                    "properties": {},
                    "additionalProperties": False,
                },
            )
        )
        tools.append(
            Tool(
                name="operation_wait",
                description="Wait up to 25 seconds without resending input; returns state and a resumable reference.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "result_ref": {"type": "string", "format": "uuid"},
                        "timeout_seconds": {
                            "type": "number",
                            "exclusiveMinimum": 0,
                            "maximum": 25,
                            "default": 20,
                        },
                    },
                    "required": ["result_ref"],
                    "additionalProperties": False,
                },
            )
        )
        tools.append(
            Tool(
                name="upload_import",
                description="Import a local file with bounded resumable chunks. Does not send a message or trigger cognition.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "file": {"type": "string", "minLength": 1},
                        "media_type": {"type": "string"},
                        "idempotency_key": {
                            "type": "string",
                            "minLength": 1,
                            "maxLength": 128,
                        },
                    },
                    "required": ["file", "idempotency_key"],
                    "additionalProperties": False,
                },
            )
        )
        return tools

    async def call_tool(
        self,
        name: str,
        arguments: dict[str, Any],
        context: Context[Any, Any] | None = None,
    ) -> CallToolResult:
        del context
        result: dict[str, Any]
        try:
            client = self._client()
            if name == "upload_import":
                from jsonschema import Draft202012Validator

                tool = next(
                    tool for tool in await self.list_tools() if tool.name == name
                )
                if not Draft202012Validator(tool.input_schema).is_valid(arguments):  # pyright: ignore[reportUnknownMemberType] -- upstream deprecated overload
                    raise ValueError("UPLOAD-ARGUMENTS")
                result = await client.import_media(
                    Path(arguments["file"]),
                    idempotency_key=arguments["idempotency_key"],
                    media_type=arguments.get("media_type"),
                )
            elif name == "operation_wait":
                from jsonschema import Draft202012Validator

                tool = next(
                    tool for tool in await self.list_tools() if tool.name == name
                )
                if not Draft202012Validator(tool.input_schema).is_valid(arguments):  # pyright: ignore[reportUnknownMemberType] -- upstream deprecated overload
                    raise ValueError("INTERACTION-ARGUMENTS")
                result = await client.wait(
                    arguments["result_ref"],
                    timeout_seconds=arguments.get("timeout_seconds", 20),
                )
            else:
                result = await client.invoke(name, arguments)
        except (ValueError, OSError, ValidationError, httpx.HTTPError) as error:
            result = interaction_failure(error)
        return CallToolResult(
            content=[
                TextContent(type="text", text=json.dumps(result, ensure_ascii=False))
            ],
            structured_content=result,
            is_error=result.get("transport_status", 200) >= 400,
        )


__all__ = ("InteractionTools",)
