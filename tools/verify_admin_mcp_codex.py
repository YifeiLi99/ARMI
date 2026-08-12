"""Verify the locked Codex CLI against an isolated Admin MCP configuration."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import tempfile
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CODEX = ROOT / "tools/toolchain-node/node_modules/@openai/codex/bin/codex.js"
TEMPLATE = ROOT / "configs/codex/armi-admin-mcp.toml"


def _run(
    node: Path, arguments: list[str], environment: dict[str, str]
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [os.fspath(node), os.fspath(CODEX), *arguments],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tool-root", type=Path)
    args = parser.parse_args()
    configured_tool_root = args.tool_root or os.environ.get("ARMI_TOOL_ROOT")
    tool_root = (
        Path(configured_tool_root).resolve()
        if configured_tool_root is not None
        else ROOT / ".armi-tools"
    )
    node = tool_root / "installs/node/node-v24.18.0-win-x64/node.exe"
    if not node.is_file() or not CODEX.is_file():
        raise SystemExit("ADMIN-CODEX-TOOL-MISSING")
    temporary_root = ROOT / ".tmp"
    temporary_root.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="admin-codex-", dir=temporary_root) as raw:
        isolated_home = Path(raw)
        environment = dict(os.environ)
        environment["CODEX_HOME"] = os.fspath(isolated_home)

        added = _run(
            node,
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

        listed = _run(node, ["mcp", "list", "--json"], environment)
        fetched = _run(node, ["mcp", "get", "armi_admin", "--json"], environment)
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
        expected_tools = tomllib.loads(TEMPLATE.read_text(encoding="utf-8"))[
            "mcp_servers"
        ]["armi_admin"]["enabled_tools"]
        if detail["enabled_tools"] != expected_tools:
            raise SystemExit("ADMIN-CODEX-ALLOWLIST")
        if detail["startup_timeout_sec"] != 10.0 or detail["tool_timeout_sec"] != 30.0:
            raise SystemExit("ADMIN-CODEX-TIMEOUT")
    print("admin-codex-config: pass (locked Codex 0.144.4, isolated config)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
