"""Static MCPServer composition root for the local Admin stdio process."""

from __future__ import annotations

from mcp.server import MCPServer
from mcp.types import ToolAnnotations

from .contracts import (
    HealthRequest,
    HealthResult,
    SchemaStatusRequest,
    SchemaStatusResult,
)
from .service import AdminToolService

SERVER_NAME = "armi_admin"
SERVER_VERSION = "0.0.0"
SERVER_INSTRUCTIONS = (
    "Read-only administration for one explicitly bound non-production ARMI "
    "environment. Never infer another environment or request credentials."
)
READ_ONLY_ANNOTATIONS = ToolAnnotations(
    read_only_hint=True,
    destructive_hint=False,
    idempotent_hint=True,
    open_world_hint=False,
)


def create_admin_server(service: AdminToolService) -> MCPServer:
    """Register exactly the two S035 tools; no dynamic discovery is used."""

    server = MCPServer(
        name=SERVER_NAME,
        title="ARMI Admin",
        description="Read-only local administration for one ARMI environment.",
        instructions=SERVER_INSTRUCTIONS,
        version=SERVER_VERSION,
        tools=[],
        resources=[],
        extensions=[],
        log_level="ERROR",
    )

    @server.tool(
        name="health",
        description="Verify the bound package, configuration, database, and Admin role.",
        annotations=READ_ONLY_ANNOTATIONS,
        structured_output=True,
    )
    def health(  # pyright: ignore[reportUnusedFunction]
        request: HealthRequest,
    ) -> HealthResult:
        return service.health(request)

    @server.tool(
        name="schema_status",
        description="Read and verify the packaged migration ledger for the bound environment.",
        annotations=READ_ONLY_ANNOTATIONS,
        structured_output=True,
    )
    def schema_status(  # pyright: ignore[reportUnusedFunction]
        request: SchemaStatusRequest,
    ) -> SchemaStatusResult:
        return service.schema_status(request)

    return server


__all__ = (
    "READ_ONLY_ANNOTATIONS",
    "SERVER_INSTRUCTIONS",
    "SERVER_NAME",
    "SERVER_VERSION",
    "create_admin_server",
)
