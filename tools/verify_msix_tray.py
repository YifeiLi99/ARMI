"""Exercise the real tray against the disposable MSIX acceptance environment."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import subprocess
import time
from pathlib import Path
from typing import Any
from uuid import uuid7

import win32gui
from armi_admin.windows_tray import stop_desktop
from armi_local_control import ManagedProcessIdentity, ManagedProcessState
from mcp.client import Client
from mcp.client.stdio import StdioServerParameters, stdio_client


async def main() -> None:
    local = Path(os.environ["LOCALAPPDATA"])
    alias = local / "Microsoft/WindowsApps/ARMI.MsixAcceptance.exe"
    environment = local / "ARMI.MsixAcceptance/environments/active"
    parameters = StdioServerParameters(command=str(alias), args=["mcp"])
    async with Client(stdio_client(parameters), read_timeout_seconds=300) as client:

        async def call(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
            response = await client.call_tool(name, arguments)
            result = response.structured_content
            assert not response.is_error and result is not None, (name, result)
            assert result["status"] in {"succeeded", "ready", "not_configured"}, (
                name,
                result,
            )
            return result

        state = await call("setup_status", {})
        update = await client.call_tool(
            "setup_update", {"update": {"action": "automatic", "enabled": False}}
        )
        assert not update.is_error
        if state["status"] == "not_configured":
            await call("setup_prepare", {"operation_id": str(uuid7())})
        if not (environment / "bootstrap/birth-manifest.json").exists():
            await call(
                "setup_birth",
                {
                    "personality_anchor": {
                        "schema_version": "armi.personality-anchor.v1",
                        "traits": ["isolated lifecycle test"],
                        "voice_style": "约 16 岁少女口吻",
                    }
                },
            )
        # Never install real credentials or send inputs in this fixture.
        started = await call(
            "admin_environment_start", {"idempotency_key": str(uuid7())}
        )
        pid = started["result"]["runtime"]["pid"]
        assert pid is not None, started
        record = environment / ".setup/desktop.json"
        window_class = (
            "ARMI.Tray."
            + hashlib.sha256(str(environment).casefold().encode()).hexdigest()
        )
        try:
            for _ in range(2):
                subprocess.Popen([str(alias), "--background"])
                deadline = time.monotonic() + 60
                while True:
                    if record.exists():
                        identity = ManagedProcessIdentity.from_wire(
                            json.loads(record.read_bytes())
                        )
                        if (
                            identity.inspect() == ManagedProcessState.MATCHES
                            and win32gui.FindWindow(window_class, "ARMI")
                        ):
                            break
                    assert time.monotonic() < deadline, "Desktop did not start"
                    await asyncio.sleep(0.2)
                # Give the normal-start callback time to finish before requesting exit.
                await asyncio.sleep(20)
                await asyncio.to_thread(stop_desktop, environment)
                assert not record.exists(), "Desktop record survived clean exit"
                status = await call("admin_environment_status", {})
                assert status["result"]["runtime"]["pid"] == pid, status
                assert status["result"]["postgresql"]["status"] == "ready", status
        finally:
            await call("admin_environment_stop", {"idempotency_key": str(uuid7())})
            await asyncio.to_thread(stop_desktop, environment)
        status = await call("admin_environment_status", {})
        assert status["result"]["runtime"]["status"] == "stopped", status
        print(
            json.dumps(
                {
                    "tray_close_and_reopen_cycles": 2,
                    "same_runtime_pid": pid,
                    "normal_stop": True,
                }
            )
        )


if __name__ == "__main__":
    asyncio.run(main())
