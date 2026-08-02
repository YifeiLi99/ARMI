"""Verify the locked Codex CLI against an isolated Admin MCP configuration."""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NODE = ROOT / ".armi-tools/installs/node/node-v24.18.0-win-x64/node.exe"
CODEX = ROOT / "tools/toolchain-node/node_modules/@openai/codex/bin/codex.js"
TEMPLATE = ROOT / "tools/codex/armi-admin-mcp.toml"


def _run(
    arguments: list[str], environment: dict[str, str]
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [os.fspath(NODE), os.fspath(CODEX), *arguments],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )


def main() -> int:
    if not NODE.is_file() or not CODEX.is_file():
        raise SystemExit("ADMIN-CODEX-TOOL-MISSING")
    temporary_root = ROOT / ".tmp"
    temporary_root.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="admin-codex-", dir=temporary_root) as raw:
        isolated_home = Path(raw)
        environment = dict(os.environ)
        environment["CODEX_HOME"] = os.fspath(isolated_home)

        added = _run(
            [
                "mcp",
                "add",
                "armi_admin",
                "--env",
                "ARMI_ADMIN_CONFIG=isolated-placeholder",
                "--",
                "armi-admin-mcp",
            ],
            environment,
        )
        if added.returncode != 0:
            raise SystemExit("ADMIN-CODEX-ADD")

        config_path = isolated_home / "config.toml"
        if not config_path.is_file() or "armi_admin" not in config_path.read_text(
            encoding="utf-8"
        ):
            raise SystemExit("ADMIN-CODEX-ADD")
        config_path.write_bytes(TEMPLATE.read_bytes())

        listed = _run(["mcp", "list", "--json"], environment)
        fetched = _run(["mcp", "get", "armi_admin", "--json"], environment)
        if listed.returncode != 0 or fetched.returncode != 0:
            raise SystemExit("ADMIN-CODEX-CONFIG")
        entries = json.loads(listed.stdout)
        detail = json.loads(fetched.stdout)
        if len(entries) != 1 or entries[0]["name"] != "armi_admin":
            raise SystemExit("ADMIN-CODEX-ALLOWLIST")
        if detail["transport"] != {
            "type": "stdio",
            "command": "armi-admin-mcp",
            "args": [],
            "env": None,
            "env_vars": ["ARMI_ADMIN_CONFIG"],
            "cwd": None,
        }:
            raise SystemExit("ADMIN-CODEX-TRANSPORT")
        if detail["enabled_tools"] != ["health", "schema_status"]:
            raise SystemExit("ADMIN-CODEX-ALLOWLIST")
        if detail["startup_timeout_sec"] != 10.0 or detail["tool_timeout_sec"] != 30.0:
            raise SystemExit("ADMIN-CODEX-TIMEOUT")
    print("admin-codex-config: pass (locked Codex 0.144.4, isolated config)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
