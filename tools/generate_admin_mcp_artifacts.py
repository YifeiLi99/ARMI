"""Generate deterministic Admin MCP governance resources from code and root schema."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import importlib.metadata
import json
from pathlib import Path
from typing import Any

from armi_admin.mcp.server import (
    SERVER_INSTRUCTIONS,
    SERVER_NAME,
    SERVER_VERSION,
    create_admin_server,
)

ROOT = Path(__file__).resolve().parents[1]
RESOURCE_ROOT = ROOT / "apps/armi-admin/src/armi_admin/mcp/resources"
SCHEMA_SOURCE = ROOT / "schema/manifests/schema-manifest.json"


def _json_bytes(value: Any) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
        + "\n"
    ).encode("utf-8")


def _digest(value: bytes) -> str:
    return f"sha256:{hashlib.sha256(value).hexdigest()}"


class _UnusedService:
    def health(self, request: object) -> object:
        raise AssertionError(request)

    def schema_status(self, request: object) -> object:
        raise AssertionError(request)


async def _tool_entries() -> list[dict[str, Any]]:
    server = create_admin_server(_UnusedService())  # type: ignore[arg-type]
    tools = await server.list_tools()
    entries: list[dict[str, Any]] = []
    for tool in sorted(tools, key=lambda item: item.name):
        input_schema = tool.input_schema
        output_schema = tool.output_schema
        annotations = (
            {}
            if tool.annotations is None
            else tool.annotations.model_dump(
                mode="json", by_alias=True, exclude_none=True
            )
        )
        entries.append(
            {
                "name": tool.name,
                "description": tool.description,
                "input_schema_sha256": _digest(_json_bytes(input_schema)),
                "output_schema_sha256": _digest(_json_bytes(output_schema)),
                "annotations": annotations,
            }
        )
    return entries


def _config_schema() -> dict[str, Any]:
    from armi_admin.application import AdminConfig

    return AdminConfig.model_json_schema(mode="validation")


def _build() -> dict[Path, bytes]:
    schema_bytes = SCHEMA_SOURCE.read_bytes()
    config_schema_bytes = _json_bytes(_config_schema())
    tools = asyncio.run(_tool_entries())
    tool_catalog_digest = _digest(_json_bytes(tools))
    package_surface = {
        "entrypoint": "armi-admin-mcp",
        "sdk_version": importlib.metadata.version("mcp"),
        "server_name": SERVER_NAME,
        "server_version": SERVER_VERSION,
        "schema_manifest_sha256": _digest(schema_bytes),
        "tool_catalog_digest": tool_catalog_digest,
    }
    manifest = {
        "schema_version": "armi.admin-mcp.v1",
        "sdk": {"name": "mcp", "version": importlib.metadata.version("mcp")},
        "protocol": {
            "target_revision": "2026-07-28",
            "discovery_method": "server/discover",
            "legacy_initialize_compatible": True,
        },
        "transport": "stdio",
        "server": {
            "name": SERVER_NAME,
            "version": SERVER_VERSION,
            "instructions": SERVER_INSTRUCTIONS,
        },
        "capabilities": {
            "resources": False,
            "prompts": False,
            "sampling": False,
            "http": False,
            "sse": False,
            "dynamic_tools": False,
        },
        "tools": tools,
        "tool_catalog_digest": tool_catalog_digest,
        "config_schema_sha256": _digest(config_schema_bytes),
        "schema_manifest_sha256": _digest(schema_bytes),
        "package_surface_digest": _digest(_json_bytes(package_surface)),
        "codex": {
            "server_name": "armi_admin",
            "enabled_tools": ["health", "schema_status"],
            "required": True,
        },
        "activation": {
            "current_step": "M0-S035",
            "control_tools_step": "M0-S036",
            "correction_tools_step": "M0-S037",
            "user_config_and_windows_identity_step": "M0-S045",
        },
    }
    return {
        RESOURCE_ROOT / "admin-config.schema.json": config_schema_bytes,
        RESOURCE_ROOT / "admin-mcp-manifest.json": _json_bytes(manifest),
        RESOURCE_ROOT / "schema-manifest.json": schema_bytes,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()
    drift: list[str] = []
    for path, expected in _build().items():
        if args.write:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(expected)
        elif not path.is_file() or path.read_bytes() != expected:
            drift.append(path.relative_to(ROOT).as_posix())
    if drift:
        raise SystemExit("ADMIN-MANIFEST-DRIFT: " + ", ".join(drift))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
