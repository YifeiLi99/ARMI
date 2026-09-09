"""Admin stdio registration from the shared, explicit application catalog."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from mcp.server import MCPServer
from mcp.types import ToolAnnotations
from pydantic import BaseModel

from armi_admin.application.catalog import ADMIN_OPERATIONS, AdminOperation
from armi_admin.application.contracts import AdminToolResult
from armi_admin.application.service import AdminToolService

SERVER_NAME = "armi_admin"
SERVER_VERSION = "0.0.0"
SERVER_INSTRUCTIONS = (
    "Observe and control one explicitly authorized ARMI environment. "
    "Never infer another environment, path, command, or credential."
)
READ_ONLY_ANNOTATIONS = ToolAnnotations(
    read_only_hint=True,
    destructive_hint=False,
    idempotent_hint=True,
    open_world_hint=False,
)
CONTROL_ANNOTATIONS = ToolAnnotations(
    read_only_hint=False,
    destructive_hint=False,
    idempotent_hint=True,
    open_world_hint=False,
)
RESET_ANNOTATIONS = ToolAnnotations(
    read_only_hint=False,
    destructive_hint=True,
    idempotent_hint=True,
    open_world_hint=False,
)


def _tool(
    operation: AdminOperation,
    service: AdminToolService,
) -> Callable[[BaseModel], AdminToolResult[Any]]:
    def invoke(request: BaseModel) -> AdminToolResult[Any]:
        return operation.invoke(service, request)

    # SDK schema generation and argument validation consume these exact model
    # classes. There is no secondary parser or dynamically evaluated code.
    invoke.__annotations__ = {"request": operation.request, "return": operation.result}
    return invoke


def create_admin_server(service: AdminToolService) -> MCPServer:
    server = MCPServer(
        name=SERVER_NAME,
        title="ARMI Admin",
        description="Local administration for one bound ARMI environment.",
        instructions=SERVER_INSTRUCTIONS,
        version=SERVER_VERSION,
        tools=[],
        resources=[],
        extensions=[],
        log_level="ERROR",
    )
    for operation in ADMIN_OPERATIONS:
        server.add_tool(
            _tool(operation, service),
            name=operation.name,
            description=operation.description,
            annotations=READ_ONLY_ANNOTATIONS
            if operation.read_only
            else RESET_ANNOTATIONS
            if operation.destructive
            else CONTROL_ANNOTATIONS,
            structured_output=True,
        )
    return server


__all__ = (
    "CONTROL_ANNOTATIONS",
    "READ_ONLY_ANNOTATIONS",
    "RESET_ANNOTATIONS",
    "SERVER_INSTRUCTIONS",
    "SERVER_NAME",
    "SERVER_VERSION",
    "create_admin_server",
)
