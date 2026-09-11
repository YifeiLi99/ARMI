"""Before/after checks for an explicitly isolated v16 -> current MSIX upgrade."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
from pathlib import Path
from typing import Any
from uuid import uuid7

from armi_postgresql_contract import BASELINE_IDENTITY
from armi_postgresql_contract.upgrades import upgrade_plan
from mcp.client import Client
from mcp.client.stdio import StdioServerParameters, stdio_client


async def verify(phase: str, evidence: Path) -> None:
    data = Path(os.environ["LOCALAPPDATA"]) / "ARMI.MsixAcceptance"
    root = data / "environments/active"
    executable = (
        Path(os.environ["LOCALAPPDATA"])
        / "Microsoft/WindowsApps/ARMI.MsixAcceptance.exe"
    )
    state = json.loads((root / ".setup/operation.json").read_text(encoding="utf-8"))
    args = (
        ["mcp"]
        if phase == "after"
        else ["mcp", "admin", "--config", str(root / "admin.yaml")]
    )
    async with Client(
        stdio_client(StdioServerParameters(command=str(executable), args=args)),
        read_timeout_seconds=120,
    ) as client:
        names = {tool.name for tool in (await client.list_tools()).tools}
        if phase == "after":
            assert {
                "admin_content_write",
                "admin_database_batch",
                "setup_status",
                "interaction_message_send",
            } <= names

        async def call(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
            if phase == "after":
                name = "admin_" + name
            else:
                arguments = {
                    "request": {"environment_id": state["environment_id"], **arguments}
                }
            response = await client.call_tool(name, arguments)
            result = response.structured_content
            assert not response.is_error and result is not None, (name, result)
            assert result["status"] == "succeeded", (name, result)
            return result["result"]

        schema = await call("schema_status", {})
        assert schema["status"] == "current", schema
        receipt = await call(
            "invocation_get",
            {
                "operation_name": "maintenance",
                "idempotency_key": state["birth_request_id"],
            },
        )
        assert receipt["state"] == "finished", receipt
        assert receipt["result"]["status"] == "succeeded", receipt
        birth = receipt["result"]["result"]
        subject = {
            "subject_id": birth["subject_id"],
            "current_generation_id": birth["life_generation_id"],
        }
        if phase == "after":
            snapshot = await call("subject_snapshot", {})
            assert snapshot["subject"]["subject_version"] == 0
            assert all(
                component["component_version"] == 1
                for component in snapshot["components"]
            )
            subject = {key: snapshot["subject"][key] for key in subject}
        files = [
            root / ".setup/operation.json",
            *root.glob("*.yaml"),
            *root.joinpath("secrets").rglob("*"),
        ]
        hashes = {
            str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in files
            if path.is_file()
        }
        if phase == "before":
            assert (
                schema["baseline_identity"] == upgrade_plan()["source"]["baseline"]
            ), schema
            evidence.write_text(
                json.dumps(
                    {"subject": subject, "receipt": receipt, "hashes": hashes},
                    ensure_ascii=False,
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )
        else:
            before = json.loads(evidence.read_text(encoding="utf-8"))
            assert schema["baseline_identity"] == BASELINE_IDENTITY, schema
            assert before["subject"] == subject, (
                "Subject identity or version changed during deployment"
            )
            assert before["receipt"] == receipt, (
                "Birth receipt changed during deployment"
            )
            assert before["hashes"] == hashes, (
                "Retained configuration or credentials changed"
            )
            setup = await client.call_tool("setup_status", {})
            assert not setup.is_error, setup.structured_content
        print(
            json.dumps(
                {
                    "phase": phase,
                    "baseline": schema["baseline_identity"],
                    "subject_id": subject["subject_id"],
                    "configuration_and_secret_files": len(hashes),
                    "birth_receipt_preserved": True,
                }
            )
        )


async def exercise_online() -> None:
    executable = (
        Path(os.environ["LOCALAPPDATA"])
        / "Microsoft/WindowsApps/ARMI.MsixAcceptance.exe"
    )
    parameters = StdioServerParameters(command=str(executable), args=["mcp"])
    async with Client(stdio_client(parameters), read_timeout_seconds=120) as client:

        async def call(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
            response = await client.call_tool("admin_" + name, arguments)
            result = response.structured_content
            assert not response.is_error and result is not None, (name, result)
            assert result["status"] == "succeeded", (name, result)
            return result["result"]

        started = await call("environment_start", {"idempotency_key": str(uuid7())})
        assert started["status"] == "ready", started
        assert started["runtime"]["status"] in {"started", "already_running"}, started
        pid = started["runtime"]["pid"]
        snapshot = await call("subject_snapshot", {})
        generation = snapshot["subject"]["current_generation_id"]
        memory = str(uuid7())
        for action, version in (("create", 0), ("update", 1), ("delete", 2)):
            payload = (
                {"summary": "Isolated administrator memory", "uncertainty": None}
                if action != "delete"
                else None
            )
            written = await call(
                "content_write",
                {
                    "idempotency_key": str(uuid7()),
                    "reason": "isolated installed online acceptance",
                    "expected_generation_id": generation,
                    "change": {
                        "owner": "memory",
                        "action": action,
                        "object_id": memory,
                        "expected_version": version,
                        "data": payload,
                    },
                },
            )
            assert written["execution_mode"] == "online", written
            assert written["change"]["new_version"] == version + 1, written
        running = await call("environment_status", {})
        assert running["runtime"]["pid"] == pid, running
    # Closing the first stdio connection must not own the environment lifetime.
    async with Client(stdio_client(parameters), read_timeout_seconds=120) as client:
        response = await client.call_tool("admin_environment_status", {})
        result = response.structured_content
        assert result is not None and result["status"] == "succeeded", result
        assert result["result"]["runtime"]["pid"] == pid, result
        stopped = await client.call_tool(
            "admin_environment_stop", {"idempotency_key": str(uuid7())}
        )
        assert not stopped.is_error, stopped.structured_content
    print(
        json.dumps(
            {
                "online_writes": 3,
                "runtime_pid_preserved_across_mcp_close": pid,
                "stopped": True,
            }
        )
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("phase", choices=("before", "after", "online"))
    parser.add_argument("evidence", type=Path)
    options = parser.parse_args()
    asyncio.run(
        exercise_online()
        if options.phase == "online"
        else verify(options.phase, options.evidence.resolve())
    )
