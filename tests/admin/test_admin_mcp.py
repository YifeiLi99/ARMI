from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import cast
from unittest.mock import Mock, patch
from uuid import uuid7

from armi_admin.application import (
    AdminConfig,
    AdminControlPlane,
    AdminCorrectionCoordinator,
    AdminCredentialPort,
    admin_program_identity,
)
from armi_admin.application.catalog import ADMIN_OPERATIONS
from armi_admin.application.contracts import (
    ConfigurationRequest,
    CorrectionStatusRequest,
    EnvironmentInitializeRequest,
    EnvironmentLifecycleRequest,
    HealthRequest,
    InjectCreatorInputRequest,
    InvocationStatusRequest,
    MaintenanceRequest,
    PreviewCorrectionRequest,
    ReplaceSubjectComponentSpec,
    RuntimeControlRequest,
    SchemaStatusRequest,
    SubjectSnapshotRequest,
)
from armi_admin.application.invocations import InvocationEvidence, InvocationReferences
from armi_admin.application.service import AdminToolService
from armi_admin.composition import AdminComposition
from armi_admin.machine import AdminSession
from armi_admin.persistence import (
    AdminCorrectionGateway,
    AdminObservationGateway,
    AdminSchemaSnapshot,
)
from armi_admin.persistence.role_session import AdminRoleBoundPool
from armi_app.mcp import ARMIMCPServer
from armi_local_control.configuration.editing import EnvironmentConfiguration
from armi_local_control.runtime_process import RuntimeProcessManager
from mcp.client import Client

ENVIRONMENT_ID = "018f3f4a-7b8c-7def-8abc-1234567890ab"
DIGEST = "sha256:" + "1" * 64
SOURCE_ROOT = admin_program_identity()["source_root"]


def _config() -> AdminConfig:
    root = Path.cwd().resolve()
    return AdminConfig.model_validate(
        {
            "schema_version": "armi.admin-config.v10",
            "operator_id": "isolated-test-agent",
            "authorized_operations": tuple(item.name for item in ADMIN_OPERATIONS),
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
                "source_root": SOURCE_ROOT,
            },
        }
    )


def _service() -> AdminToolService:
    temporary = tempfile.TemporaryDirectory(dir=Path.cwd() / ".tmp")
    unittest.addModuleCleanup(temporary.cleanup)
    root = Path(temporary.name)
    environment_root = root / "environment"
    environment_root.mkdir()
    config = _config().model_copy(
        update={"environment_root": environment_root, "experiment_root": root}
    )
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


def test_private_snapshot_requires_separate_scope_before_owner_read() -> None:
    service = _service()
    result = service.observe(
        "subject_snapshot",
        SubjectSnapshotRequest(environment_id=ENVIRONMENT_ID, detail="private"),
    )
    assert result.status == "rejected"
    assert result.error_code == "ADMIN-PRIVATE-SCOPE-REQUIRED"


def test_cognition_read_requires_its_scope_before_owner_read() -> None:
    from armi_admin.application.contracts import CognitionReadRequest

    service = _service()
    service._config = service.config.model_copy(
        update={
            "authorized_operations": tuple(
                name
                for name in service.config.authorized_operations
                if name != "cognition_read"
            )
        }
    )
    result = service.observe(
        "cognition_read",
        CognitionReadRequest(environment_id=ENVIRONMENT_ID, episode_id=str(uuid7())),
    )
    assert result.status == "rejected"
    assert result.error_code == "ADMIN-SCOPE-REQUIRED"


def test_mcp_cognition_read_returns_text_and_pagination():
    async def exercise():
        service = _service()
        gateway = Mock(spec=AdminObservationGateway)
        artifact_id = str(uuid7())
        gateway.cognition_read.return_value = {
            "episode_id": ENVIRONMENT_ID,
            "status": "completed",
            "trace_id": "a" * 32,
            "attempts": [],
            "artifacts": [],
            "text": {
                "artifact_id": artifact_id,
                "content": "上下文",
                "offset": 0,
                "next_offset": 3,
                "total_characters": 6,
                "offset_unit": "unicode_characters",
            },
        }
        service._observation = gateway
        async with Client(_server(service)) as client:
            result = await client.call_tool(
                "admin_cognition_read",
                {
                    "episode_id": ENVIRONMENT_ID,
                    "artifact_id": artifact_id,
                    "length": 3,
                },
            )
            assert not result.is_error and result.structured_content is not None
            assert result.structured_content["result"]["text"]["content"] == "上下文"
            gateway.cognition_read.assert_called_once_with(
                episode_id=ENVIRONMENT_ID,
                artifact_id=artifact_id,
                offset=0,
                length=3,
            )

    asyncio.run(exercise())


def test_mcp_usage_preserves_optional_business_purpose() -> None:
    async def exercise() -> None:
        service = _service()
        gateway = Mock(spec=AdminObservationGateway)
        gateway.usage.return_value = {"total": 1, "items": []}
        service._observation = gateway
        async with Client(_server(service)) as client:
            tools = {tool.name: tool for tool in (await client.list_tools()).tools}
            for name in ("admin_usage_summary", "admin_usage_list"):
                assert "purpose" in tools[name].input_schema["properties"]
            assert (
                "purpose" not in tools["admin_runtime_drain"].input_schema["properties"]
            )
            for arguments, expected in (
                ({}, None),
                ({"purpose": "consider_autonomous_life"}, "consider_autonomous_life"),
            ):
                result = await client.call_tool("admin_usage_list", arguments)
                assert not result.is_error
                assert result.structured_content is not None
                assert result.structured_content["result"]["total"] == 1
                query = gateway.usage.call_args.args[0]
                assert query.filters.purpose == expected

    asyncio.run(exercise())


def test_usage_cli_exposes_purpose_filter() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "armi_admin.cli", "usage", "list", "--help"],
        capture_output=True,
        text=True,
        check=True,
    )
    assert "--purpose" in result.stdout


def _server(service: AdminToolService) -> ARMIMCPServer:
    session = AdminSession(service.config.environment_root / "admin.yaml")
    binding = patch.object(
        session,
        "_bound",
        return_value=AdminComposition(service, cast(AdminRoleBoundPool, object())),
    )
    binding.start()
    unittest.addModuleCleanup(binding.stop)
    return ARMIMCPServer(admin=session, client_path=None)


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
        revision="0000",
        baseline_identity="armi.schema-baseline.v68",
        resource_digest=DIGEST,
        catalog_digest=DIGEST,
        role_policy_digest=DIGEST,
    )


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
        resources = Path("apps/armi-admin/src/armi_admin/application/resources")
        self.assertEqual(
            sorted(path.name for path in resources.glob("*.json")),
            ["admin-config.schema.json"],
        )
        schema = json.loads(
            (resources / "admin-config.schema.json").read_text(encoding="utf-8")
        )
        self.assertEqual(
            schema["properties"]["schema_version"]["const"],
            "armi.admin-config.v10",
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
    def test_read_only_maintenance_is_fresh_without_a_write_key(self) -> None:
        service = _service()
        config = service.config.model_copy(
            update={
                "authorized_operations": ("maintenance.semantic_status",),
            }
        )
        request = MaintenanceRequest(
            environment_id=ENVIRONMENT_ID,
            environment_incarnation=1,
            purpose="admin.maintenance",
            action="semantic_status",
        )
        with (
            patch.object(service, "_config", config),
            patch.object(
                AdminControlPlane,
                "maintenance",
                side_effect=[
                    {"status": "stopped"},
                    {"status": "running"},
                ],
            ) as inspect,
        ):
            self.assertEqual(
                service.mutate("maintenance", request).result, {"status": "stopped"}
            )
            self.assertEqual(
                service.mutate("maintenance", request).result, {"status": "running"}
            )
        self.assertEqual(inspect.call_count, 2)
        self.assertFalse((config.environment_root.parent / ".armi-admin").exists())

    def test_lifecycle_receipt_survives_configuration_change_and_keeps_scope(
        self,
    ) -> None:
        service = _service()
        request = EnvironmentLifecycleRequest(
            environment_id=ENVIRONMENT_ID,
            environment_incarnation=1,
            purpose="admin.environment_start",
            idempotency_key="durable-start",
        )
        with patch(
            "armi_admin.application.service.LocalEnvironmentController.execute",
            return_value={"status": "ready"},
        ) as start:
            first = service.lifecycle("start", request)
            changed = service.config.model_copy(update={"resettable": False})
            self.assertNotEqual(service.config.safe_digest(), changed.safe_digest())
            with patch.object(service, "_config", changed):
                self.assertEqual(service.lifecycle("start", request), first)
                receipt = service.observe(
                    "invocation_get",
                    InvocationStatusRequest(
                        environment_id=ENVIRONMENT_ID,
                        operation_name="environment_start",
                        idempotency_key="durable-start",
                    ),
                )
                assert receipt.result is not None
                self.assertEqual(receipt.result["state"], "finished")
            start.assert_called_once()
        revoked = changed.model_copy(
            update={"authorized_operations": ("invocation_get",)}
        )
        with patch.object(service, "_config", revoked):
            self.assertEqual(
                service.lifecycle("start", request).error_code, "ADMIN-SCOPE-REQUIRED"
            )
            denied = service.observe(
                "invocation_get",
                InvocationStatusRequest(
                    environment_id=ENVIRONMENT_ID,
                    operation_name="environment_start",
                    idempotency_key="durable-start",
                ),
            )
            self.assertEqual(denied.error_code, "ADMIN-SCOPE-REQUIRED")

    def test_configuration_saved_and_running_values_are_distinct(self) -> None:
        service = _service()
        config = service.config.model_copy(
            update={
                "authorized_operations": ("configuration.status", "configuration.apply")
            }
        )
        (config.environment_root / "environment.yaml").write_text(
            json.dumps(
                {
                    "environment": {
                        "environment_id": config.environment_id,
                        "data_root": str(config.environment_root / "data"),
                    },
                    "creator": {"port": 43123},
                }
            ),
            encoding="utf-8",
        )
        editor = EnvironmentConfiguration(
            config.environment_root, Path.cwd() / "configs/runtime.yaml"
        )
        before = editor.read()
        status_request = ConfigurationRequest(
            environment_id=config.environment_id, action="status"
        )
        running = {
            "status": "running",
            "runtime": {"runtime_configuration_digest": before["desired_digest"]},
        }
        with (
            patch.object(service, "_config", config),
            patch.object(RuntimeProcessManager, "status", return_value=running),
        ):
            effective = service.configuration(status_request)
            assert effective.result is not None
            self.assertEqual(effective.result["activation"], "effective")
            saved = service.configuration(
                ConfigurationRequest(
                    environment_id=config.environment_id,
                    action="apply",
                    idempotency_key="save-creator-port",
                    expected_version=before["version"],
                    patch={"creator": {"port": 43124}},
                )
            )
            assert saved.result is not None
            self.assertEqual(saved.result["activation"], "saved")
            stale = service.configuration(status_request)
            assert stale.result is not None
            self.assertEqual(stale.result["activation"], "restart_required")
            running["runtime"]["runtime_configuration_digest"] = editor.read()[
                "desired_digest"
            ]
            restarted = service.configuration(status_request)
            assert restarted.result is not None
            self.assertEqual(restarted.result["activation"], "effective")
            self.assertFalse(restarted.result["restart_required"])

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

    def test_schema_identity_drift_is_rejected_without_row_details(self) -> None:
        service = _service()
        current = _current_snapshot()
        dirty = AdminSchemaSnapshot(
            server_version_num=current.server_version_num,
            encoding=current.encoding,
            timezone=current.timezone,
            tables=current.tables,
            revision=current.revision,
            baseline_identity="armi.schema-baseline.legacy",
            resource_digest=current.resource_digest,
            catalog_digest=current.catalog_digest,
            role_policy_digest=current.role_policy_digest,
        )
        with patch.object(AdminToolService, "_read_snapshot", return_value=dirty):
            result = service.schema_status(
                SchemaStatusRequest(environment_id=ENVIRONMENT_ID)
            )
        self.assertEqual(result.status, "failed")
        self.assertIsNotNone(result.result)
        assert result.result is not None
        self.assertEqual(result.result.status, "unavailable")
        self.assertEqual(result.error_code, "ADMIN-DB-IDENTITY")


class AdminProtocolTests(unittest.TestCase):
    def test_modern_discover_and_legacy_initialize(self) -> None:
        async def exercise() -> tuple[str, str, list[str]]:
            server = _server(_service())
            async with Client(server, mode="auto") as modern:
                names = [tool.name for tool in (await modern.list_tools()).tools]
                modern_version = modern.protocol_version
            async with Client(server, mode="legacy") as legacy:
                legacy_version = legacy.protocol_version
            return modern_version, legacy_version, names

        modern, legacy, names = asyncio.run(exercise())
        self.assertEqual(modern, "2026-07-28")
        self.assertNotEqual(legacy, "")
        from armi_admin.application.catalog import ADMIN_OPERATIONS

        self.assertEqual(
            set(names), {"admin_" + item.name for item in ADMIN_OPERATIONS}
        )
        self.assertIn("admin_environment_reset_preview", names)
        self.assertIn("admin_preview_correction", names)
        self.assertIn("admin_correction_status", names)

    def test_wrong_source_binding_is_rejected_before_credentials_or_pool(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config_path = root / "admin.yaml"
            config_path.write_text(
                "\n".join(
                    (
                        "schema_version: armi.admin-config.v10",
                        "operator_id: isolated-test-agent",
                        "authorized_operations: [health]",
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
                        f"  source_root: {(root / 'wrong-checkout').as_posix()}",
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
            mcp_binding = root / "mcp.yaml"
            mcp_binding.write_text(
                json.dumps(
                    {
                        "schema_version": "armi.mcp-binding.v1",
                        "admin_config": str(config_path),
                    }
                ),
                encoding="utf-8",
            )
            completed = subprocess.run(
                [sys.executable, "-m", "armi_app", "mcp", "--config", str(mcp_binding)],
                cwd=Path.cwd(),
                env=environment,
                capture_output=True,
                text=True,
                check=False,
            )
        self.assertEqual(completed.returncode, 2)
        self.assertEqual(completed.stdout, "")
        self.assertEqual(completed.stderr.strip(), "MCP-STARTUP-BINDING-INVALID")

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
        self.assertEqual(spec.replacement["identity_kind"], "electronic_person")
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
                        "schema_version": "armi.mood.v5",
                        "dynamics_version": "recency-reappraisal.v1",
                        "derivation_version": "cpm-fuzzy.v4",
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
                "conclusion": "still_unknown",
                "observed_at": "2026-08-26T00:00:00Z",
                "evidence_kind": "inconclusive",
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
            async with Client(_server(_service())) as client:
                result = await client.call_tool(
                    "admin_health",
                    {"contract_version": "1.0", "unknown": True},
                )
                return bool(result.is_error)

        self.assertTrue(asyncio.run(exercise()))


def test_mcp_scope_arrays_retain_strict_elements_and_reach_the_owner() -> None:
    async def exercise() -> None:
        service = _service()
        gateway = Mock(spec=AdminObservationGateway)
        gateway.inspect_scope.return_value = {
            "schema_version": "armi.admin-scope-graph.v2",
            "nodes": [
                {
                    "kind": "subject",
                    "id": ENVIRONMENT_ID,
                    "owner": "runtime-foundation",
                    "attributes": {},
                }
            ],
            "edges": [],
            "missing": [],
            "relations": ["current_owner"],
            "truncated": False,
            "cursor": None,
            "expansion_limit": 200,
            "expansion_truncated": False,
        }
        service._observation = gateway
        async with Client(_server(service)) as client:
            request = {
                "kind": "subject",
                "object_ids": [ENVIRONMENT_ID],
                "relations": ["current_owner"],
            }
            result = await client.call_tool("admin_inspect_scope", request)
            assert not result.is_error and result.structured_content is not None
            assert (
                result.structured_content["result"]["nodes"][0]["id"] == ENVIRONMENT_ID
            )
            gateway.inspect_scope.assert_called_once_with(
                "subject",
                (ENVIRONMENT_ID,),
                relations=("current_owner",),
                limit=100,
                cursor=None,
            )
            invalid = await client.call_tool(
                "admin_inspect_scope", {**request, "object_ids": [123]}
            )
            assert invalid.is_error
            assert gateway.inspect_scope.call_count == 1

    asyncio.run(exercise())


def test_reconcile_start_requires_preidentified_ready_runtime() -> None:
    service = _service()
    expected = "018f3f4a-7b8c-7def-8abc-1234567890ab"
    evidence = InvocationEvidence(
        operation="environment_start",
        idempotency_key="start",
        request_digest="digest",
        references=InvocationReferences(
            component="runtime", launch_instance_id=expected
        ),
    )
    current = {
        "status": "running",
        "pid": 123,
        "runtime": {
            "instance_id": expected,
            "runtime_state": "ready",
            "readiness": "ready",
        },
    }
    with (
        patch.object(AdminControlPlane, "runtime_status", return_value=current),
        patch.object(
            AdminControlPlane,
            "maintenance",
            side_effect=AssertionError("must not dispatch maintenance"),
        ),
    ):
        result, observation = service._reconcile_invocation(evidence)
    assert result is not None and result["status"] == "succeeded"
    assert observation["basis"] == "preidentified_runtime"
    changed = {
        **current,
        "runtime": {**current["runtime"], "instance_id": "different-instance"},
    }
    with (
        patch.object(AdminControlPlane, "runtime_status", return_value=changed),
        patch(
            "armi_admin.application.service.LocalEnvironmentController.execute",
            return_value=changed,
        ),
    ):
        result, observation = service._reconcile_invocation(evidence)
    assert result is None
    assert observation["basis"] == "current_process_state_only"


def test_environment_reconcile_requires_optional_process_step() -> None:
    service = _service()
    evidence = InvocationEvidence(
        operation="environment_start",
        idempotency_key="start",
        request_digest="digest",
        references=InvocationReferences(component="environment"),
        completed_steps={
            "postgresql.start": {"status": "ready"},
            "semantic.start": {"status": "disabled"},
            "runtime.readiness": {"readiness": "ready"},
        },
    )
    with patch.object(
        AdminControlPlane, "runtime_status", return_value={"status": "stopped"}
    ):
        result, _ = service._reconcile_invocation(evidence)
    assert result is None
    complete = evidence.model_copy(
        update={
            "completed_steps": {
                **evidence.completed_steps,
                "napcat.start": {"status": "not_installed"},
            }
        }
    )
    result, _ = service._reconcile_invocation(complete)
    assert result is not None and result["status"] == "succeeded"


if __name__ == "__main__":
    unittest.main()
