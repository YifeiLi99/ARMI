"""Local stdio interaction MCP, sharing its client and contract with armi CLI."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import httpx
from armi_local_control.binding import load_client_binding
from jsonschema.exceptions import ValidationError
from mcp.server import MCPServer
from mcp.server.mcpserver import Context
from mcp.types import CallToolResult, TextContent, Tool, ToolAnnotations

from .interaction_client import InteractionClient
from .interfaces.interaction_catalog import interaction_routes


class InteractionMCPServer(MCPServer[Any]):
    def __init__(self, client: InteractionClient) -> None:
        super().__init__(
            name="armi",
            instructions="Act as the explicitly bound Creator delegate. Use capabilities, send with a stable idempotency key, then operation_wait/get and artifact_read. Acceptance is not completion. Administration is a separate armi_admin server.",
            tools=[],
            resources=[],
            extensions=[],
        )
        self.client = client

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
            if name == "operation_wait":
                from jsonschema import Draft202012Validator

                tool = next(
                    tool for tool in await self.list_tools() if tool.name == name
                )
                if not Draft202012Validator(tool.input_schema).is_valid(arguments):  # pyright: ignore[reportUnknownMemberType] -- upstream deprecated overload
                    raise ValueError("INTERACTION-ARGUMENTS")
                result = await self.client.wait(
                    arguments["result_ref"],
                    timeout_seconds=arguments.get("timeout_seconds", 20),
                )
            else:
                result = await self.client.invoke(name, arguments)
        except ValueError as error:
            code = str(error)
            result = {
                "status": "rejected",
                "error_code": code
                if code
                in {
                    "INTERACTION-ARGUMENTS",
                    "INTERACTION-OPERATION-UNKNOWN",
                    "INTERACTION-WAIT-TIMEOUT",
                }
                else "INTERACTION-RESPONSE-CONTRACT",
                "transport_status": 400,
            }
        except OSError, ValidationError, httpx.HTTPError:
            result = {
                "status": "unavailable",
                "error_code": "INTERACTION-CALL-FAILED",
                "transport_status": 503,
            }
        return CallToolResult(
            content=[
                TextContent(type="text", text=json.dumps(result, ensure_ascii=False))
            ],
            structured_content=result,
            is_error=result.get("transport_status", 200) >= 400,
        )


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="armi-mcp", description="Creator-delegated local stdio interaction."
    )
    parser.add_argument("--config", type=Path)
    args = parser.parse_args(argv)
    try:
        InteractionMCPServer(InteractionClient(load_client_binding(args.config))).run(
            "stdio"
        )
    except ValueError, OSError:
        print("INTERACTION-MCP-CONFIG", file=sys.stderr)
        raise SystemExit(2) from None


if __name__ == "__main__":
    main()


__all__ = ("InteractionMCPServer", "main")
