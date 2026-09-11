"""One real stdio endpoint and fail-closed authority checks."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from unittest.mock import Mock

import pytest
from armi_admin.machine import AdminSession
from armi_app.mcp import ARMIMCPServer, MCPBinding
from mcp.client import Client
from mcp.client.stdio import StdioServerParameters, stdio_client


@pytest.mark.asyncio
async def test_real_stdio_discovers_all_groups_before_environment_preparation(
    tmp_path: Path,
) -> None:
    root = tmp_path / "environments" / "active"
    async with Client(
        stdio_client(
            StdioServerParameters(
                command=sys.executable,
                args=[
                    "-m",
                    "armi_app",
                    "mcp",
                    "--environment-root",
                    str(root),
                    "--installation-root",
                    str(tmp_path),
                ],
                cwd=Path.cwd(),
                env=dict(os.environ),
            )
        ),
        read_timeout_seconds=30,
    ) as client:
        names = {tool.name for tool in (await client.list_tools()).tools}
        assert {
            "interaction_message_send",
            "admin_environment_start",
            "admin_health",
            "setup_status",
            "setup_prepare",
        } <= names
        assert "setup_admin" not in names
        first = await client.call_tool("setup_status", {})
        second = await client.call_tool("setup_status", {})
        assert (
            first.structured_content
            == second.structured_content
            == {"status": "not_configured"}
        )
        missing = await client.call_tool("admin_health", {})
        assert missing.is_error
    assert not root.exists(), "MCP discovery must not initialize an environment"


@pytest.mark.asyncio
async def test_restricted_session_cannot_reach_setup_or_hidden_admin_operations() -> (
    None
):
    session = Mock(spec=AdminSession)
    session.permitted_operations.return_value = frozenset({"health"})
    session.invoke.return_value = {
        "status": "succeeded",
        "result": {"status": "healthy"},
    }
    server = ARMIMCPServer(admin=session, client_path=None)
    assert [tool.name for tool in await server.list_tools()] == ["admin_health"]
    for name, arguments in (
        ("setup_prepare", {"operation_id": "untrusted"}),
        ("setup_admin", {"operation": "environment_reset"}),
        ("admin_environment_reset", {}),
        ("admin_health", {"local_owner": True}),
        ("admin_health", {"environment_id": "another-environment"}),
    ):
        result = await server.call_tool(name, arguments)
        assert result.is_error
    session.invoke.assert_not_called()
    result = await server.call_tool("admin_health", {})
    assert not result.is_error
    session.invoke.assert_called_once_with("health", {})


def test_restricted_binding_cannot_declare_owner_authority() -> None:
    with pytest.raises(ValueError):
        MCPBinding.model_validate_json(
            json.dumps(
                {
                    "schema_version": "armi.mcp-binding.v1",
                    "local_owner": True,
                }
            )
        )
