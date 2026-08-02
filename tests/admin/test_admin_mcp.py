from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import AbstractAsyncContextManager
from importlib.resources import files
from pathlib import Path
from typing import Any
from unittest.mock import patch

from armi_admin.application import AdminConfig, AdminCredentialPort
from armi_admin.mcp.contracts import (
    ApplyCorrectionRequest,
    CorrectionStatusRequest,
    HealthRequest,
    PreviewCorrectionRequest,
    ReplaceSubjectComponentSpec,
    RuntimeControlRequest,
    SchemaStatusRequest,
)
from armi_admin.mcp.server import create_admin_server
from armi_admin.mcp.service import AdminToolService
from armi_admin.persistence import AdminSchemaSnapshot
from mcp.client import Client
from mcp.client.stdio import StdioServerParameters, stdio_client

ENVIRONMENT_ID = "018f3f4a-7b8c-7def-8abc-1234567890ab"


def _resources() -> tuple[dict[str, Any], dict[str, Any]]:
    root = files("armi_admin.mcp.resources")
    governance = json.loads(root.joinpath("admin-mcp-manifest.json").read_bytes())
    schema = json.loads(root.joinpath("schema-manifest.json").read_bytes())
    return governance, schema


def _config() -> AdminConfig:
    governance, _ = _resources()
    root = Path.cwd().resolve()
    return AdminConfig.model_validate(
        {
            "schema_version": "armi.admin-config.v2",
            "environment_kind": "system_test",
            "environment_id": ENVIRONMENT_ID,
            "environment_incarnation": 1,
            "resettable": True,
            "test_controls_enabled": True,
            "environment_root": root,
            "experiment_root": root,
            "template_manifest": root / "schema/manifests/schema-manifest.json",
            "postgresql_tool_root": root / ".armi-tools/installs/postgresql/18.4/pgsql",
            "database_locator": "env:ARMI_SECRET_ADMIN_DATABASE",
            "migrator_database_locator": "env:ARMI_SECRET_MIGRATOR_DATABASE",
            "preview_key_locator": "env:ARMI_SECRET_ADMIN_PREVIEW_KEY",
            "expected": {
                "package_digest": governance["package_surface_digest"],
                "schema_manifest_digest": governance["schema_manifest_sha256"],
            },
        }
    )


def _service() -> AdminToolService:
    config = _config()
    credentials = AdminCredentialPort(
        locator=config.locator,
        config_root=Path.cwd(),
        environ={"ARMI_SECRET_ADMIN_DATABASE": "postgresql://invalid"},
    )
    return AdminToolService(config=config, credentials=credentials)


def _current_snapshot() -> AdminSchemaSnapshot:
    _, schema = _resources()
    migrations = tuple(
        (int(item["version"]), str(item["name"]), str(item["sha256"]))
        for item in schema["migrations"]
    )
    return AdminSchemaSnapshot(
        server_version_num=180004,
        encoding="UTF8",
        timezone="UTC",
        migrations=migrations,
    )


class _StdioTransport(AbstractAsyncContextManager):
    def __init__(self, parameters: StdioServerParameters) -> None:
        self._manager = stdio_client(parameters)

    async def __aenter__(self):
        return await self._manager.__aenter__()

    async def __aexit__(self, exc_type, exc, traceback):
        return await self._manager.__aexit__(exc_type, exc, traceback)


class AdminConfigurationTests(unittest.TestCase):
    def test_config_is_strict_and_safe(self) -> None:
        config = _config()
        self.assertEqual(
            config.expected_role, "armi_018f3f4a7b8c7def8abc1234567890ab_admin"
        )
        self.assertRegex(config.safe_digest(), r"^sha256:[0-9a-f]{64}$")
        with self.assertRaises(ValueError):
            AdminConfig.model_validate(
                {**config.model_dump(mode="json"), "unknown": True}
            )

    def test_generated_governance_has_exact_static_surface(self) -> None:
        governance, _ = _resources()
        self.assertEqual(governance["sdk"], {"name": "mcp", "version": "2.0.0"})
        self.assertEqual(governance["protocol"]["target_revision"], "2026-07-28")
        self.assertEqual(
            [tool["name"] for tool in governance["tools"]],
            [
                "advance_test_clock",
                "apply_correction",
                "arm_fault",
                "clear_faults",
                "correction_status",
                "environment_initialize",
                "environment_reset",
                "environment_reset_preview",
                "health",
                "inject_creator_input",
                "inspect_scope",
                "preview_correction",
                "run_test",
                "runtime_drain",
                "runtime_restart",
                "runtime_start",
                "runtime_status",
                "runtime_stop",
                "schema_status",
                "settle_correction_work",
                "subject_snapshot",
                "tail_diagnostics",
                "trace_flow",
            ],
        )
        read_only = {
            "health",
            "schema_status",
            "runtime_status",
            "subject_snapshot",
            "trace_flow",
            "inspect_scope",
            "tail_diagnostics",
            "environment_reset_preview",
            "preview_correction",
            "correction_status",
        }
        destructive = {
            "environment_reset",
            "apply_correction",
            "settle_correction_work",
        }
        for tool in governance["tools"]:
            self.assertEqual(
                tool["annotations"],
                {
                    "destructiveHint": tool["name"] in destructive,
                    "idempotentHint": True,
                    "openWorldHint": False,
                    "readOnlyHint": tool["name"] in read_only,
                },
            )

    def test_artifacts_have_no_drift(self) -> None:
        completed = subprocess.run(
            [
                os.fspath(Path(sys.executable)),
                "tools/generate_admin_mcp_artifacts.py",
            ],
            cwd=Path.cwd(),
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)

    def test_locked_codex_cli_accepts_isolated_configuration(self) -> None:
        completed = subprocess.run(
            [sys.executable, "tools/verify_admin_mcp_codex.py"],
            cwd=Path.cwd(),
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("locked Codex 0.144.4", completed.stdout)


class AdminToolServiceTests(unittest.TestCase):
    def test_control_idempotency_and_purpose_are_enforced(self) -> None:
        service = _service()
        request = RuntimeControlRequest(
            environment_id=ENVIRONMENT_ID,
            environment_incarnation=1,
            idempotency_key="same-runtime-drain",
            purpose="admin.runtime_drain",
        )
        with patch(
            "armi_admin.application.control_plane.AdminControlPlane.send_control",
            return_value={"runtime_state": "draining"},
        ) as send:
            first = service.mutate("runtime_drain", request)
            repeated = service.mutate("runtime_drain", request)
        self.assertEqual(first, repeated)
        send.assert_called_once()
        conflict = service.mutate(
            "runtime_drain",
            request.model_copy(
                update={"expected_instance_id": "0198f3f4-7b8c-7def-8abc-1234567890ab"}
            ),
        )
        self.assertEqual(conflict.error_code, "ADMIN-IDEMPOTENCY-CONFLICT")
        wrong_purpose = service.mutate(
            "runtime_drain",
            request.model_copy(update={"purpose": "admin.runtime_stop"}),
        )
        self.assertEqual(wrong_purpose.error_code, "ADMIN-PURPOSE")

    def test_health_and_current_schema_are_read_only_safe_results(self) -> None:
        service = _service()
        with patch.object(
            AdminToolService, "_read_snapshot", return_value=_current_snapshot()
        ):
            health = service.health(HealthRequest())
            status = service.schema_status(
                SchemaStatusRequest(environment_id=ENVIRONMENT_ID)
            )
        self.assertEqual(health.status, "succeeded")
        self.assertIsNotNone(health.result)
        assert health.result is not None
        self.assertTrue(health.result.database_reachable)
        self.assertEqual(health.result.role_status, "verified")
        self.assertEqual(status.status, "succeeded")
        self.assertIsNotNone(status.result)
        assert status.result is not None
        self.assertEqual(status.result.status, "current")
        self.assertEqual(status.result.applied_version, 22)
        self.assertIsNone(status.error_code)
        serialized = health.model_dump_json() + status.model_dump_json()
        self.assertNotIn("postgresql://", serialized)
        self.assertNotIn("ARMI_SECRET", serialized)

    def test_environment_mismatch_is_rejected_before_database_access(self) -> None:
        service = _service()
        with patch.object(AdminToolService, "_read_snapshot") as read_snapshot:
            result = service.schema_status(
                SchemaStatusRequest(
                    environment_id="018f3f4a-7b8c-7def-9abc-1234567890ab"
                )
            )
        read_snapshot.assert_not_called()
        self.assertEqual(result.error_code, "ADMIN-ENVIRONMENT-MISMATCH")

    def test_schema_drift_is_classified_without_row_details(self) -> None:
        service = _service()
        current = _current_snapshot()
        dirty = AdminSchemaSnapshot(
            server_version_num=current.server_version_num,
            encoding=current.encoding,
            timezone=current.timezone,
            migrations=(
                *current.migrations[:-1],
                (22, "changed", current.migrations[-1][2]),
            ),
        )
        with patch.object(AdminToolService, "_read_snapshot", return_value=dirty):
            result = service.schema_status(
                SchemaStatusRequest(environment_id=ENVIRONMENT_ID)
            )
        self.assertEqual(result.status, "failed")
        self.assertIsNotNone(result.result)
        assert result.result is not None
        self.assertEqual(result.result.status, "dirty")
        self.assertEqual(result.error_code, "ADMIN-SCHEMA-HASH")


class AdminProtocolTests(unittest.TestCase):
    def test_modern_discover_and_legacy_initialize(self) -> None:
        async def exercise() -> tuple[str, str, list[str]]:
            server = create_admin_server(_service())
            async with Client(server, mode="auto") as modern:
                names = [tool.name for tool in (await modern.list_tools()).tools]
                modern_version = modern.protocol_version
            async with Client(server, mode="legacy") as legacy:
                legacy_version = legacy.protocol_version
            return modern_version, legacy_version, names

        modern, legacy, names = asyncio.run(exercise())
        self.assertEqual(modern, "2026-07-28")
        self.assertNotEqual(legacy, "")
        self.assertEqual(len(names), 23)
        self.assertIn("environment_reset_preview", names)
        self.assertIn("preview_correction", names)
        self.assertIn("correction_status", names)

    def test_stdio_subprocess_has_clean_protocol_output(self) -> None:
        governance, _ = _resources()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config_path = root / "admin.toml"
            config_path.write_text(
                "\n".join(
                    (
                        'schema_version = "armi.admin-config.v2"',
                        'environment_kind = "system_test"',
                        f'environment_id = "{ENVIRONMENT_ID}"',
                        "environment_incarnation = 1",
                        "resettable = true",
                        "test_controls_enabled = true",
                        f'environment_root = "{root.as_posix()}"',
                        f'experiment_root = "{root.as_posix()}"',
                        f'template_manifest = "{(Path.cwd() / "schema/manifests/schema-manifest.json").as_posix()}"',
                        f'postgresql_tool_root = "{(Path.cwd() / ".armi-tools/installs/postgresql/18.4").as_posix()}"',
                        'database_locator = "env:ARMI_SECRET_ADMIN_DATABASE"',
                        'migrator_database_locator = "env:ARMI_SECRET_MIGRATOR_DATABASE"',
                        'preview_key_locator = "env:ARMI_SECRET_ADMIN_PREVIEW_KEY"',
                        "[expected]",
                        f'package_digest = "{governance["package_surface_digest"]}"',
                        f'schema_manifest_digest = "{governance["schema_manifest_sha256"]}"',
                        "",
                    )
                ),
                encoding="utf-8",
                newline="\n",
            )
            environment = dict(os.environ)
            environment["ARMI_ADMIN_CONFIG"] = os.fspath(config_path)
            environment["ARMI_SECRET_ADMIN_DATABASE"] = (
                "postgresql://127.0.0.1:1/unavailable?connect_timeout=1"
            )

            async def exercise() -> tuple[str, list[str], bool]:
                parameters = StdioServerParameters(
                    command=sys.executable,
                    args=["-m", "armi_admin.mcp.entrypoint"],
                    env=environment,
                    cwd=Path.cwd(),
                )
                async with Client(_StdioTransport(parameters), mode="auto") as client:
                    tools = await client.list_tools()
                    result = await client.call_tool(
                        "schema_status",
                        {
                            "request": {
                                "contract_version": "1.0",
                                "environment_id": "018f3f4a-7b8c-7def-9abc-1234567890ab",
                            }
                        },
                    )
                    return (
                        client.protocol_version,
                        [tool.name for tool in tools.tools],
                        bool(result.is_error),
                    )

            version, names, is_error = asyncio.run(exercise())
        self.assertEqual(version, "2026-07-28")
        self.assertEqual(len(names), 23)
        self.assertFalse(is_error)

    def test_correction_contract_is_strict_and_private_payload_is_typed(self) -> None:
        request = PreviewCorrectionRequest.model_validate_json(
            json.dumps(
                {
                    "environment_id": ENVIRONMENT_ID,
                    "environment_incarnation": 1,
                    "idempotency_key": "preview-self-1",
                    "purpose": "admin.preview_correction",
                    "spec": {
                        "correction_kind": "replace_subject_component",
                        "component_kind": "self",
                        "expected_component_version": 1,
                        "replacement": {
                            "schema_version": "armi.self.v1",
                            "identity_kind": "electronic_person",
                            "creator_role_awareness": "unique_primary_creator",
                            "name": None,
                            "self_description": None,
                            "interests": [],
                            "values": [],
                            "preferences": [],
                            "goals": [],
                            "self_narrative": None,
                            "tensions": [],
                        },
                    },
                }
            )
        )
        assert isinstance(request.spec, ReplaceSubjectComponentSpec)
        spec = request.spec
        self.assertEqual(spec.component_kind, "self")
        with self.assertRaises(ValueError):
            ApplyCorrectionRequest.model_validate(
                {
                    **request.model_dump(mode="json"),
                    "purpose": "admin.apply_correction",
                    "preview_token": "x" * 64,
                    "spec": {
                        **spec.model_dump(mode="json"),
                        "replacement": {
                            **spec.replacement.model_dump(mode="json"),
                            "identity_kind": "human",
                        },
                    },
                }
            )
        with self.assertRaises(ValueError):
            CorrectionStatusRequest.model_validate(
                {
                    "environment_id": ENVIRONMENT_ID,
                    "preview_token": "x" * 64,
                    "unknown": True,
                }
            )

    def test_unknown_input_field_is_rejected_by_sdk(self) -> None:
        async def exercise() -> bool:
            async with Client(create_admin_server(_service())) as client:
                result = await client.call_tool(
                    "health",
                    {"request": {"contract_version": "1.0", "unknown": True}},
                )
                return bool(result.is_error)

        self.assertTrue(asyncio.run(exercise()))


if __name__ == "__main__":
    unittest.main()
