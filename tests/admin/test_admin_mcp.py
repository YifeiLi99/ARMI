from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import AbstractAsyncContextManager
from pathlib import Path
from typing import cast
from unittest.mock import patch

from armi_admin.application import (
    AdminConfig,
    AdminControlPlane,
    AdminCorrectionCoordinator,
    AdminCredentialPort,
)
from armi_admin.mcp.contracts import (
    ApplyCorrectionRequest,
    CorrectionStatusRequest,
    EnvironmentInitializeRequest,
    HealthRequest,
    InjectCreatorInputRequest,
    PreviewCorrectionRequest,
    ReplaceSubjectComponentSpec,
    RuntimeControlRequest,
    SchemaStatusRequest,
)
from armi_admin.mcp.server import create_admin_server
from armi_admin.mcp.service import AdminToolService
from armi_admin.persistence import (
    AdminCorrectionGateway,
    AdminObservationGateway,
    AdminSchemaSnapshot,
)
from armi_admin.persistence.role_session import AdminRoleBoundPool
from mcp.client import Client
from mcp.client.stdio import StdioServerParameters, stdio_client

ENVIRONMENT_ID = "018f3f4a-7b8c-7def-8abc-1234567890ab"
DIGEST = "sha256:" + "1" * 64


def _config() -> AdminConfig:
    root = Path.cwd().resolve()
    return AdminConfig.model_validate(
        {
            "schema_version": "armi.admin-config.v4",
            "environment_kind": "system_test",
            "environment_id": ENVIRONMENT_ID,
            "environment_incarnation": 1,
            "resettable": True,
            "test_controls_enabled": True,
            "environment_root": root,
            "experiment_root": root,
            "template_manifest": root / "README.md",
            "postgresql_client_root": root
            / ".armi-tools/installs/postgresql/18.4/pgsql",
            "database_locator": "env:ARMI_SECRET_ADMIN_DATABASE",
            "migrator_database_locator": "env:ARMI_SECRET_MIGRATOR_DATABASE",
            "preview_key_locator": "env:ARMI_SECRET_ADMIN_PREVIEW_KEY",
            "expected": {
                "package_digest": DIGEST,
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
    observation = cast(AdminObservationGateway, object())
    control = AdminControlPlane(config, credentials, observation)
    corrections = AdminCorrectionCoordinator(
        config, credentials, control, cast(AdminCorrectionGateway, object())
    )
    return AdminToolService(
        config=config,
        credentials=credentials,
        control=control,
        corrections=corrections,
        observation=observation,
        pool=cast(AdminRoleBoundPool, object()),
    )


def _current_snapshot() -> AdminSchemaSnapshot:
    return AdminSchemaSnapshot(
        server_version_num=180004,
        encoding="UTF8",
        timezone="UTC",
        tables=(
            "activities",
            "party_input_interactions",
            "deployment_environments",
            "maintenance_sessions",
            "runtime_instances",
            "subjects",
        ),
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

    def test_only_public_config_schema_is_packaged(self) -> None:
        resources = Path("apps/armi-admin/src/armi_admin/mcp/resources")
        self.assertEqual(
            sorted(path.name for path in resources.glob("*.json")),
            ["admin-config.schema.json"],
        )
        schema = json.loads(
            (resources / "admin-config.schema.json").read_text(encoding="utf-8")
        )
        self.assertEqual(
            schema["properties"]["schema_version"]["const"],
            "armi.admin-config.v4",
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

    def test_creator_input_uses_formal_runtime_intake(self) -> None:
        service = _service()
        request = InjectCreatorInputRequest(
            environment_id=ENVIRONMENT_ID,
            environment_incarnation=1,
            idempotency_key="automation-message-1",
            purpose="admin.inject_creator_input",
            message="你好, ARMI",
        )
        with patch(
            "armi_admin.application.control_plane.AdminControlPlane.send_control",
            return_value={
                "interaction_id": "interaction-1",
                "newly_accepted": True,
            },
        ) as send:
            result = service.mutate("inject_creator_input", request)

        self.assertEqual(result.status, "succeeded")
        send.assert_called_once_with(
            "input",
            {
                "message": "你好, ARMI",
                "idempotency_key": "automation-message-1",
            },
        )

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
        self.assertNotIn("config_digest", health.result.identity.model_dump())
        self.assertEqual(status.status, "succeeded")
        self.assertIsNotNone(status.result)
        assert status.result is not None
        self.assertEqual(status.result.status, "current")
        self.assertEqual(status.result.table_count, 6)
        self.assertEqual(status.result.missing_tables, ())
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
            tables=tuple(
                table for table in current.tables if table != "maintenance_sessions"
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
        self.assertEqual(result.error_code, "ADMIN-SCHEMA-DIRTY")


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
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config_path = root / "admin.yaml"
            config_path.write_text(
                "\n".join(
                    (
                        "schema_version: armi.admin-config.v4",
                        "environment_kind: system_test",
                        f"environment_id: {ENVIRONMENT_ID}",
                        "environment_incarnation: 1",
                        "resettable: true",
                        "test_controls_enabled: true",
                        f'environment_root: "{root.as_posix()}"',
                        f'experiment_root: "{root.as_posix()}"',
                        f'template_manifest: "{(Path.cwd() / "README.md").as_posix()}"',
                        f'postgresql_client_root: "{(Path.cwd() / ".armi-tools/installs/postgresql/18.4").as_posix()}"',
                        "database_locator: env:ARMI_SECRET_ADMIN_DATABASE",
                        "migrator_database_locator: env:ARMI_SECRET_MIGRATOR_DATABASE",
                        "preview_key_locator: env:ARMI_SECRET_ADMIN_PREVIEW_KEY",
                        "expected:",
                        f"  package_digest: {DIGEST}",
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

        mood = PreviewCorrectionRequest.model_validate(
            {
                "environment_id": ENVIRONMENT_ID,
                "environment_incarnation": 1,
                "idempotency_key": "preview-mood-1",
                "purpose": "admin.preview_correction",
                "spec": {
                    "correction_kind": "replace_subject_component",
                    "component_kind": "mood",
                    "expected_component_version": 1,
                    "replacement": {
                        "schema_version": "armi.mood.v3",
                        "dynamics_version": "recency-reappraisal.v1",
                        "derivation_version": "cpm-fuzzy.v2",
                        "home_base": {
                            "valence": 10,
                            "arousal": 0,
                            "dominance": 5,
                        },
                    },
                },
            }
        )
        assert isinstance(mood.spec, ReplaceSubjectComponentSpec)
        self.assertEqual(mood.spec.component_kind, "mood")

        correction_specs = (
            spec.model_dump(),
            {
                "correction_kind": "repair_subject_component_head",
                "component_kind": "self",
                "expected_component_version": 1,
                "target_revision_id": ENVIRONMENT_ID,
            },
            {
                "correction_kind": "delete_uncommitted_creator_input",
                "interaction_id": ENVIRONMENT_ID,
            },
            {
                "correction_kind": "requeue_stuck_work",
                "work_id": ENVIRONMENT_ID,
            },
            {
                "correction_kind": "reconcile_unknown_creator_effect",
                "effect_id": ENVIRONMENT_ID,
            },
        )
        for index, correction_spec in enumerate(correction_specs):
            with self.subTest(correction_kind=correction_spec["correction_kind"]):
                parsed = PreviewCorrectionRequest.model_validate(
                    {
                        "environment_id": ENVIRONMENT_ID,
                        "environment_incarnation": 1,
                        "idempotency_key": f"preview-contract-{index}",
                        "purpose": "admin.preview_correction",
                        "spec": correction_spec,
                    }
                )
                self.assertEqual(
                    parsed.spec.correction_kind,
                    correction_spec["correction_kind"],
                )

        for birth_mode in ("unborn", "manifest"):
            with self.subTest(birth_mode=birth_mode):
                initialized = EnvironmentInitializeRequest.model_validate(
                    {
                        "environment_id": ENVIRONMENT_ID,
                        "environment_incarnation": 1,
                        "idempotency_key": f"initialize-{birth_mode}",
                        "purpose": "admin.environment_initialize",
                        "birth_mode": birth_mode,
                    }
                )
                self.assertEqual(initialized.birth_mode, birth_mode)
        with self.assertRaises(ValueError):
            EnvironmentInitializeRequest.model_validate(
                {
                    "environment_id": ENVIRONMENT_ID,
                    "environment_incarnation": 1,
                    "idempotency_key": "initialize-invalid",
                    "purpose": "admin.environment_initialize",
                    "birth_mode": "unknown",
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
