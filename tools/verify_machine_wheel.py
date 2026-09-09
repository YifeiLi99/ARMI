"""Exercise installed CLI and real stdio MCP discovery with no running database."""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid7

from armi_admin.application import AdminConfig, admin_package_set_digest
from armi_admin.application.catalog import ADMIN_OPERATIONS
from mcp.client import Client
from mcp.client.stdio import StdioServerParameters, stdio_client


async def verify(root: Path) -> None:
    environment_id = str(uuid7())
    config = root / "admin.yaml"
    config.write_text(
        json.dumps(
            {
                "schema_version": "armi.admin-config.v6",
                "operator_id": "wheel-verifier",
                "authorized_operations": ["capabilities", "environment_status"],
                "environment_kind": "active",
                "environment_id": environment_id,
                "environment_incarnation": 1,
                "resettable": False,
                "test_controls_enabled": False,
                "environment_root": str(root),
                "database_locator": "env:ARMI_SECRET_ADMIN_DATABASE",
                "migrator_database_locator": "env:ARMI_SECRET_MIGRATOR_DATABASE",
                "preview_key_locator": "env:ARMI_SECRET_ADMIN_PREVIEW_KEY",
                "expected": {"package_set_digest": admin_package_set_digest()},
            }
        ),
        encoding="utf-8",
        newline="\n",
    )
    environment = {
        key: value for key, value in os.environ.items() if not key.startswith("ARMI_")
    }
    environment["ARMI_ADMIN_CONFIG"] = str(config)
    AdminConfig.model_validate(json.loads(config.read_text(encoding="utf-8")))
    scripts = Path(sys.executable).parent
    command = subprocess.run(
        [str(scripts / "armi-admin.exe"), "capabilities"],
        env=environment,
        cwd=root,
        capture_output=True,
        timeout=20,
        text=True,
        encoding="utf-8",
        check=False,
    )
    assert command.returncode == 0, command.stdout + command.stderr
    cli = json.loads(command.stdout)
    assert cli["status"] == "succeeded"
    async with Client(
        stdio_client(
            StdioServerParameters(
                command=str(scripts / "armi-admin-mcp.exe"),
                cwd=root,
                env=environment,
            )
        ),
        read_timeout_seconds=20,
    ) as client:
        listed = await client.list_tools()
        assert {tool.name for tool in listed.tools} == {
            item.name for item in ADMIN_OPERATIONS
        }
        called = await client.call_tool("capabilities", {"request": {}})
        assert not called.is_error and called.structured_content is not None
        assert called.structured_content["result"] == cli["result"]
        denied = await client.call_tool(
            "arm_fault",
            {
                "request": {
                    "environment_id": environment_id,
                    "environment_incarnation": 1,
                    "idempotency_key": "denied-live-fault",
                    "purpose": "admin.arm_fault",
                    "fault": "subject_before_cas",
                    "duration_seconds": 1,
                }
            },
        )
        assert denied.structured_content is not None
        assert denied.structured_content["status"] == "rejected"
        assert denied.structured_content["error_code"] == "ADMIN-SCOPE-REQUIRED"
    print("machine-wheel: CLI/MCP capability parity and cold active discovery passed")


def main() -> None:
    with TemporaryDirectory(prefix="armi-machine-wheel-", dir=Path.cwd()) as temporary:
        asyncio.run(verify(Path(temporary).resolve()))


if __name__ == "__main__":
    main()
