"""Source-independent probes executed by an installed S045 candidate."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import http.client
import json
import os
from contextlib import AbstractAsyncContextManager
from importlib.resources import as_file, files
from pathlib import Path
from typing import Any, LiteralString, cast
from uuid import uuid7

import psycopg
import rfc8785
from psycopg import sql


def _digest(value: bytes) -> str:
    return f"sha256:{hashlib.sha256(value).hexdigest()}"


def _environment(root: Path) -> dict[str, Any]:
    import tomllib

    return tomllib.loads((root / "environment.toml").read_text(encoding="utf-8"))


def birth_manifest(root: Path) -> dict[str, Any]:
    environment_id = _environment(root)["environment"]["environment_id"]
    runtime = files("armi_runtime.composition.runtime_resources")
    creator = files("armi_runtime.interfaces.creator_web_resources")
    anchor = {
        "schema_version": "armi.personality-anchor.v1",
        "voice_style": "S045 隔离验收中性表达",
        "traits": ["审慎"],
    }
    value = {
        "schema_version": "armi.birth-manifest.v1",
        "environment_id": environment_id,
        "birth_request_id": str(uuid7()),
        "creator_party_id": str(uuid7()),
        "idempotency_key": f"s045-birth-{environment_id}",
        "personality_anchor": anchor,
        "personality_anchor_digest": _digest(rfc8785.dumps(anchor)),
        "expected_package": {
            "composition_digest": _digest(
                runtime.joinpath("runtime-composition.manifest.json").read_bytes()
            ),
            "birth_contract_digest": _digest(
                runtime.joinpath("birth-contract.manifest.json").read_bytes()
            ),
            "schema_manifest_digest": _digest(
                runtime.joinpath("schema/manifests/schema-manifest.json").read_bytes()
            ),
            "creator_asset_manifest_digest": _digest(
                creator.joinpath("manifest.json").read_bytes()
            ),
        },
    }
    target = root / "bootstrap/birth-manifest.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(rfc8785.dumps(value))
    return {
        "status": "prepared",
        "request_digest": _digest(rfc8785.dumps(value)),
    }


def admin_config(root: Path, postgresql_tool_root: Path) -> dict[str, Any]:
    governance_root = files("armi_admin.mcp.resources")
    governance = json.loads(
        governance_root.joinpath("admin-mcp-manifest.json").read_bytes()
    )
    schema_resource = files("armi_runtime.composition.runtime_resources").joinpath(
        "schema/manifests/schema-manifest.json"
    )
    with as_file(schema_resource) as schema_path:
        lines = (
            'schema_version = "armi.admin-config.v2"',
            'environment_kind = "acceptance"',
            f'environment_id = "{_environment(root)["environment"]["environment_id"]}"',
            "environment_incarnation = 1",
            "resettable = false",
            "test_controls_enabled = false",
            f'environment_root = "{root.as_posix()}"',
            f'experiment_root = "{root.parent.as_posix()}"',
            f'template_manifest = "{Path(schema_path).as_posix()}"',
            f'postgresql_tool_root = "{postgresql_tool_root.as_posix()}"',
            f'database_locator = "file:{(root / "secrets/admin").as_posix()}"',
            f'migrator_database_locator = "file:{(root / "secrets/migrator").as_posix()}"',
            f'preview_key_locator = "file:{(root / "secrets/preview").as_posix()}"',
            "[expected]",
            f'package_digest = "{governance["package_surface_digest"]}"',
            f'schema_manifest_digest = "{governance["schema_manifest_sha256"]}"',
            "",
        )
        target = root / "admin.toml"
        target.write_text("\n".join(lines), encoding="utf-8", newline="\n")
    return {"status": "prepared", "config_digest": _digest(target.read_bytes())}


class _StdioTransport(AbstractAsyncContextManager):
    def __init__(self, parameters: Any) -> None:
        from mcp.client.stdio import stdio_client

        self._manager = stdio_client(parameters)

    async def __aenter__(self) -> Any:
        return await self._manager.__aenter__()

    async def __aexit__(self, exc_type: Any, exc: Any, traceback: Any) -> Any:
        return await self._manager.__aexit__(exc_type, exc, traceback)


def admin_smoke(root: Path) -> dict[str, Any]:
    from mcp.client import Client
    from mcp.client.stdio import StdioServerParameters

    environment_id = _environment(root)["environment"]["environment_id"]

    async def exercise() -> dict[str, Any]:
        environment = dict(os.environ)
        environment["ARMI_ADMIN_CONFIG"] = os.fspath(root / "admin.toml")
        parameters = StdioServerParameters(
            command=os.fspath(Path(sys.executable).with_name("armi-admin-mcp.exe")),
            env=environment,
            cwd=root,
        )
        async with Client(_StdioTransport(parameters), mode="auto") as client:
            tools = await client.list_tools()
            health = await client.call_tool(
                "health", {"request": {"contract_version": "1.0"}}
            )
            schema = await client.call_tool(
                "schema_status",
                {
                    "request": {
                        "contract_version": "1.0",
                        "environment_id": environment_id,
                    }
                },
            )
            return {
                "protocol_version": client.protocol_version,
                "tool_count": len(tools.tools),
                "health_error": bool(health.is_error),
                "schema_error": bool(schema.is_error),
            }

    import sys

    result = asyncio.run(exercise())
    if (
        result["protocol_version"] != "2026-07-28"
        or result["tool_count"] != 23
        or result["health_error"]
        or result["schema_error"]
    ):
        raise RuntimeError("S045-ADMIN-SMOKE")
    return {"status": "pass", **result}


def creator_input(root: Path) -> dict[str, Any]:
    configuration = _environment(root)
    port = int(configuration["creator"]["port"])
    bearer = (root / "secrets/creator").read_text(encoding="utf-8").strip()
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    connection.request(
        "POST",
        "/v1/browser-bootstrap-codes",
        body=b"",
        headers={"Authorization": f"Bearer {bearer}", "Content-Length": "0"},
    )
    response = connection.getresponse()
    issued = json.loads(response.read())
    if response.status != 200:
        raise RuntimeError("S045-CREATOR-BOOTSTRAP")
    body = json.dumps(
        {"bootstrap_code": issued["bootstrap_code"]}, separators=(",", ":")
    ).encode()
    boundary = {
        "Origin": f"http://127.0.0.1:{port}",
        "Sec-Fetch-Site": "same-origin",
        "Sec-Fetch-Mode": "cors",
        "Sec-Fetch-Dest": "empty",
    }
    connection.request(
        "POST",
        "/v1/browser-sessions",
        body=body,
        headers={
            **boundary,
            "Content-Type": "application/json",
            "Content-Length": str(len(body)),
        },
    )
    response = connection.getresponse()
    session = json.loads(response.read())
    if response.status != 200:
        raise RuntimeError("S045-CREATOR-SESSION")
    message = json.dumps(
        {"contract_version": "1.0", "message": "S045 隔离恢复演练输入"},
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode()
    connection.request(
        "POST",
        "/v1/scenes/default/messages",
        body=message,
        headers={
            **boundary,
            "Authorization": f"Bearer {session['browser_session_token']}",
            "Content-Type": "application/json",
            "Content-Length": str(len(message)),
            "Idempotency-Key": "s045-recovery-input",
        },
    )
    response = connection.getresponse()
    accepted = json.loads(response.read())
    if response.status != 202 or accepted.get("status") != "accepted":
        raise RuntimeError("S045-CREATOR-INPUT")
    return {
        "status": "accepted",
        "result_ref_digest": _digest(str(accepted["result_ref"]).encode()),
    }


def snapshot(conninfo_file: Path) -> dict[str, Any]:
    conninfo = conninfo_file.read_text(encoding="utf-8").strip()
    queries = {
        "schema": "SELECT version, name, sha256, application_version FROM armi.schema_migrations ORDER BY version",
        "subjects": "SELECT subject_id::text, current_generation_id::text, current_bundle_activation_id::text, subject_version, state_epoch FROM armi.subjects ORDER BY subject_id",
        "generations": "SELECT life_generation_id::text, subject_id::text, generation_no, status FROM armi.life_generations ORDER BY life_generation_id",
        "activations": "SELECT bundle_activation_id::text, subject_id::text, bundle_version, bundle_digest, status FROM armi.runtime_bundle_activations ORDER BY bundle_activation_id",
        "inputs": "SELECT creator_interaction_id::text, request_digest, content_digest FROM armi.creator_input_interactions ORDER BY creator_interaction_id",
        "work": "SELECT work_id::text, work_kind, status, attempt_count FROM armi.durable_work ORDER BY work_id",
        "effects": "SELECT effect_id::text, effect_kind, status, payload_digest, registration_digest FROM armi.effects ORDER BY effect_id",
        "recovery": "SELECT status, blocker_count, resumable_work_count, resumable_opportunity_count FROM armi.runtime_recovery_runs ORDER BY started_at, recovery_run_id",
    }
    projections: dict[str, list[list[Any]]] = {}
    with psycopg.connect(conninfo) as connection:
        for name, query in queries.items():
            projections[name] = [
                list(row)
                for row in connection.execute(sql.SQL(cast(LiteralString, query)))
            ]
    fact_names = (
        "schema",
        "subjects",
        "generations",
        "activations",
        "inputs",
        "effects",
    )
    facts = {name: projections[name] for name in fact_names}
    encoded = rfc8785.dumps(projections)
    return {
        "status": "pass",
        "authority_sha256": _digest(encoded),
        "facts_sha256": _digest(rfc8785.dumps(facts)),
        "counts": {name: len(rows) for name, rows in projections.items()},
        "latest_recovery": projections["recovery"][-1]
        if projections["recovery"]
        else None,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("birth-manifest", "admin-smoke", "creator-input"):
        command = commands.add_parser(name)
        command.add_argument("--environment-root", type=Path, required=True)
    admin = commands.add_parser("admin-config")
    admin.add_argument("--environment-root", type=Path, required=True)
    admin.add_argument("--postgresql-tool-root", type=Path, required=True)
    state = commands.add_parser("snapshot")
    state.add_argument("--conninfo-file", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "birth-manifest":
        result = birth_manifest(args.environment_root.resolve())
    elif args.command == "admin-config":
        result = admin_config(
            args.environment_root.resolve(), args.postgresql_tool_root.resolve()
        )
    elif args.command == "admin-smoke":
        result = admin_smoke(args.environment_root.resolve())
    elif args.command == "creator-input":
        result = creator_input(args.environment_root.resolve())
    else:
        result = snapshot(args.conninfo_file.resolve())
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
