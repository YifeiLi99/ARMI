"""Exercise the shipped native entry point, including actual stdio MCP clients."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import subprocess
import time
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid7

import psutil
from armi_admin.application.distribution import ProgramBundle
from mcp.client import Client
from mcp.client.stdio import StdioServerParameters, stdio_client
from verify_machine_wheel import verify


async def check(program: Path, *, installed: bool = False) -> None:
    executable = program / "ARMI.exe"
    expected_entries = {"ARMI.exe"}
    assert {p.name for p in program.glob("*.exe")} == expected_entries
    if installed:
        assert (program / "AppxManifest.xml").is_file()
        assert (program / "armi_windows.dll").is_file()
        ProgramBundle.read(program).verify(program)
    environment = {k: v for k, v in os.environ.items() if not k.startswith("ARMI_")}
    environment["PATH"] = str(Path(os.environ["SYSTEMROOT"]) / "System32")
    for arguments in (
        ["cli", "interaction"],
        ["cli", "admin"],
        ["cli", "setup"],
        ["mcp"],
    ):
        result = subprocess.run(
            [str(executable), *arguments, "--help"],
            capture_output=True,
            env=environment,
            timeout=30,
            check=False,
        )
        assert result.returncode == 0 and b"usage:" in result.stdout, result.stderr
    result = subprocess.run(
        [str(executable), "cli", "setup"],
        input=b'{"action":"status"}',
        capture_output=True,
        env=environment,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0
    status = json.loads(result.stdout)["status"]
    assert status in {
        "not_configured",
        "claimed",
        "configured",
        "roles_ready",
        "installing",
        "ready",
    }
    if not installed:
        assert status == "not_configured"
    scratch = Path(__file__).resolve().parents[1] / ".tmp"
    scratch.mkdir(exist_ok=True)
    with TemporaryDirectory(prefix="entrypoint-", dir=scratch) as raw:
        root = Path(raw)
        await verify(root, executable)
        binding = root / "client.yaml"
        binding.write_text(
            json.dumps(
                {
                    "schema_version": "armi.interaction-client.v1",
                    "environment_id": str(uuid7()),
                    "environment_root": str(root),
                    "delegate_id": str(uuid7()),
                    "creator_party_id": str(uuid7()),
                    "credential_locator": "env:ARMI_SECRET_TEST_DELEGATE",
                    "scopes": ["interaction.read"],
                    "endpoint": "http://127.0.0.1:1",
                }
            ),
            encoding="utf-8",
        )
        mcp_binding = root / "interaction-mcp.yaml"
        mcp_binding.write_text(
            json.dumps(
                {
                    "schema_version": "armi.mcp-binding.v1",
                    "interaction_config": str(binding),
                }
            ),
            encoding="utf-8",
        )
        owner_arguments = [
            "--environment-root",
            str(root / "environments" / "active"),
            "--installation-root",
            str(root),
        ]
        for scope, extra in (
            ("interaction", ["--config", str(mcp_binding)]),
            ("owner", owner_arguments),
        ):
            async with Client(
                stdio_client(
                    StdioServerParameters(
                        command=str(executable),
                        args=["mcp", *extra],
                        env=environment,
                    )
                ),
                read_timeout_seconds=30,
            ) as client:
                listed = await client.list_tools()
                names = {tool.name for tool in listed.tools}
                assert names
                if scope == "interaction":
                    assert all(name.startswith("interaction_") for name in names)
                else:
                    assert {
                        "setup_status",
                        "admin_health",
                        "interaction_message_send",
                    } <= names
        process = subprocess.Popen(
            [str(executable), "mcp", *owner_arguments],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=environment,
        )
        try:
            deadline = time.monotonic() + 15
            children = []
            while time.monotonic() < deadline:
                children = psutil.Process(process.pid).children()
                if children:
                    break
                time.sleep(0.1)
            assert children
            time.sleep(3)
            process.terminate()
            process.wait(timeout=10)
            for child in children:
                child.wait(timeout=10)
        finally:
            if process.poll() is None:
                process.terminate()
            process.communicate(timeout=10)
    print(
        "windows-entrypoint: unified MCP, native pipes, restricted bindings, EOF and cancellation passed"
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("program", type=Path)
    parser.add_argument("--installed", action="store_true")
    arguments = parser.parse_args()
    asyncio.run(check(arguments.program.resolve(), installed=arguments.installed))
