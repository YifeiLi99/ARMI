from __future__ import annotations

import asyncio
import base64
import hashlib
import http.client
import io
import json
import os
import secrets
import selectors
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from collections.abc import AsyncIterator
from contextlib import redirect_stdout
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Literal, LiteralString, cast
from uuid import UUID, uuid7

import psycopg
import pytest
import rfc8785
from armi_activity.api import ActivityViolation
from armi_admin.application import (
    AdminConfig,
    AdminCredentialPort,
    admin_program_identity,
)
from armi_admin.application.authorization import AuthorizationStore
from armi_admin.application.catalog import ADMIN_OPERATIONS
from armi_admin.application.contracts import (
    ApplyCorrectionRequest,
    CorrectionStatusRequest,
    EnvironmentResetPreviewRequest,
    EnvironmentResetRequest,
    HealthRequest,
    PreviewCorrectionRequest,
    RuntimeControlRequest,
    SchemaStatusRequest,
    SettleCorrectionWorkRequest,
)
from armi_admin.application.service import AdminToolService
from armi_admin.cli import main
from armi_admin.composition import bootstrap_admin
from armi_admin.persistence.role_session import AdminRoleBoundPool
from armi_admin.persistence.runtime_foundation import RuntimeFoundationAdminAdapter
from armi_artifact_store.content_store import (
    ContentAddressedArtifactStore,
)
from armi_attention.api import OpportunityAdmissionOutcome, OpportunityAdmissionStatus
from armi_codex.api import (
    CodexCleanupStatus,
    CodexDelegationDraft,
    CodexTaskSourceId,
    CodexVerificationStatus,
    CreatorCodexTaskCommand,
    bind_autonomous_codex_task,
)
from armi_cognition.api import (
    CandidateExactLifeQueryDraft,
    CognitionAcceptedCandidate,
    CognitionApplicationDraft,
    CognitionContextEpisodeDraft,
    CognitionSchemaDocument,
    SubjectChangeSet,
)
from armi_cognition.bootstrap import (
    bootstrap_cognition_context,
    bootstrap_cognition_exact_life_query,
)
from armi_context.api import EMBEDDING_BINDING_ID
from armi_data_rights.api import DataRightsFence
from armi_expression.api import (
    CreatorReplyDraft,
    ExpressionCommitContext,
    FormalNoActionDraft,
    FormalNoActionKind,
    FormalNoActionReason,
    ResponseViolation,
)
from armi_interaction.api import (
    ConfigureExternalCreatorCommand,
    CreatorInputAcceptance,
    ExternalAccountKey,
    ExternalChannel,
    ExternalConversationKey,
    ExternalConversationKind,
    ExternalMessageKey,
    ExternalMessagePart,
    ExternalMessagePartKind,
    ExternalPartyKey,
    ExternalVisualRole,
    ObservedExternalMessage,
    SceneKey,
    SceneTimelinePage,
    SceneTimelineQuery,
)
from armi_kernel.application import (
    COGNITION_PURPOSES,
    ArtifactId,
    ArtifactIntegrityStatus,
    ArtifactPolicy,
    ArtifactPrivacyScope,
    ArtifactRef,
    ArtifactViolation,
    AuditQuery,
    BirthManifest,
    BirthResult,
    BirthViolation,
    CandidateApplicationId,
    CandidateApplicationStatus,
    CandidateBasis,
    CandidateDisposition,
    CandidateExperienceDraft,
    CandidateFactClass,
    CandidateOwnerDraft,
    CognitionPurpose,
    LifeRecordActor,
    LifeRecordKind,
    LifeRecordQuery,
    LifeRecordQueryViolation,
    LifeRecordRetrievalKind,
    ModelResultStatus,
    PersonalityAnchor,
    PostCommitAction,
    PriceCatalog,
    RecoveryStatus,
    RuntimeAuthorityRecord,
    RuntimeAuthorityViolation,
    RuntimeFence,
    RuntimeInstanceId,
    WorkAttemptId,
    WorkDraft,
    WorkId,
    WorkLease,
    WorkOwner,
    WorkPayloadRef,
    WorkResultRef,
    WorkType,
    WorkViolation,
)
from armi_kernel.contracts import (
    Digest,
    IdempotencyKey,
    Instant,
    OpaqueCursor,
    TraceId,
)
from armi_live_vision.bootstrap import bootstrap_live_vision_commit
from armi_live_voice.bootstrap import bootstrap_live_voice_context_read
from armi_local_control.runtime_process import RuntimeProcessManager
from armi_mind.api import CandidateMindDraft
from armi_perception.api import (
    ExternalContentRecognitionResult,
    ExternalContentRecognitionStatus,
    ExternalMediaContent,
)
from armi_runtime.adapters.persistence.audit_events import AuditEventRepository
from armi_runtime.adapters.persistence.birth import (
    BirthRepository,
    ContinuityState,
    probe_continuity,
)
from armi_runtime.adapters.persistence.database_capabilities import (
    CURRENT_COLUMN_DML_CAPABILITIES,
    CURRENT_DML_CAPABILITIES,
)
from armi_runtime.adapters.persistence.durable_work import (
    PostgreSQLDurableWorkGateway,
)
from armi_runtime.adapters.persistence.execution_custody import (
    PostgreSQLExecutionCustody,
)
from armi_runtime.adapters.persistence.life_records import PostgreSQLLifeRecordQuery
from armi_runtime.adapters.persistence.recovery import (
    PostgreSQLRuntimeRecovery,
)
from armi_runtime.adapters.persistence.role_policy import (
    physical_role_name,
)
from armi_runtime.adapters.persistence.runtime_authority import (
    PostgreSQLRuntimeAuthority,
)
from armi_runtime.adapters.persistence.schema_gateway import (
    DatabaseViolation,
    PostgreSQLSchemaGateway,
)
from armi_runtime.adapters.persistence.subject_commit import (
    PostgreSQLSubjectCommitRepository,
)
from armi_runtime.adapters.persistence.subject_maintenance import (
    PostgreSQLSubjectMaintenance,
)
from armi_runtime.adapters.persistence.unit_of_work import (
    PostgreSQLUnitOfWorkFactory,
)
from armi_runtime.adapters.transaction_errors import DatabaseTransactionError
from armi_runtime.application.creator_timeline import CreatorTimelineProjectionAssembler
from armi_runtime.application.life_opportunity import RuntimeLifeOpportunityFacts
from armi_runtime.application.maintenance import RuntimeSleepFacts
from armi_runtime.composition.artifacts import (
    ContentAddressedArtifactCoordinator,
)
from armi_runtime.composition.birth import BirthTransaction
from armi_runtime.composition.birth_manifest import (
    packaged_birth_digests,
)
from armi_runtime.composition.candidate_validation_tool import bootstrap_mind_cognition
from armi_runtime.composition.data_rights_contracts import (
    DATA_RIGHTS_OWNER_CONTRACTS,
)
from armi_runtime.composition.database import compose_mind_module as bootstrap_mind
from armi_runtime.composition.model_adapter import create_model_adapter
from armi_runtime.composition.model_verification import GENERIC_COGNITION_INSTRUCTIONS
from armi_runtime.composition.owner_roster import compose_runtime_owner_roster
from armi_runtime.composition.postgresql_test import (
    ArtifactCatalogRepository,
    CandidateValidationContext,
    CodexTaskSourceGateway,
    CreatorInputRepository,
    DeterministicCandidateValidator,
    ExternalContentPipeline,
    ExternalMessageInputRepository,
    ExternalMessageInputService,
    OtherHumanInputRepository,
    PostgreSQLCodexDelegationRepository,
    PostgreSQLEffectDispatchRepository,
    PostgreSQLInteractionPerception,
    PostgreSQLLocalInbox,
    PostgreSQLSceneTimelineQuery,
    bootstrap_activity,
    bootstrap_activity_cognition,
    bootstrap_autonomy,
    bootstrap_codex_commit,
    bootstrap_codex_read_ports,
    bootstrap_codex_timeline_projection,
    bootstrap_cognition_operation,
    bootstrap_cognition_subject_commit,
    bootstrap_data_rights_core,
    bootstrap_dialogue_decision_record,
    bootstrap_effect_codex_lifecycle,
    bootstrap_effect_intent_read,
    bootstrap_effect_operation_read,
    bootstrap_evidence,
    bootstrap_experience_owner,
    bootstrap_expression,
    bootstrap_expression_action_ports,
    bootstrap_expression_effect_registration,
    bootstrap_interaction_action_ports,
    bootstrap_interaction_birth,
    bootstrap_interaction_identity,
    bootstrap_interaction_subject_commit,
    bootstrap_material,
    bootstrap_material_cognition,
    bootstrap_memory,
    bootstrap_memory_cognition,
    bootstrap_mood,
    bootstrap_mood_cognition,
    bootstrap_opportunity,
    bootstrap_opportunity_admission,
    bootstrap_opportunity_cognition,
    bootstrap_opportunity_sleep,
    bootstrap_opportunity_transition,
    bootstrap_prompt,
    bootstrap_prompt_cognition,
    bootstrap_relationship,
    bootstrap_relationship_cognition,
    bootstrap_sleep,
    bootstrap_sleep_cognition,
    bootstrap_sleep_decision_record,
    bootstrap_subject_state,
    bootstrap_subject_state_cognition,
    build_request_bytes,
    candidate_schema,
    checked_model_request,
    load_active_binding,
)
from armi_runtime.composition.subject_commit_pipeline import SubjectCommitPipeline
from armi_runtime.composition.work_wakeup import WorkWakeupBus
from armi_sleep.api import (
    CandidateMaintenanceDecisionDraft,
    CandidateSleepDecisionDraft,
    CreatorMaintenanceViolation,
    MaintenancePhase,
    MaintenanceWorkOutcome,
    SleepCommitContext,
    SleepDecisionKind,
    SleepViolation,
)
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from playwright.sync_api import sync_playwright
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo

from tools.live_ark_credential import (
    load_live_text_credential,
)


class _TestIdentityTokens:
    key_identity = "sha256:" + "1" * 64

    def token(self, *, domain: str, value: str) -> str:
        return (
            "hmac-sha256:v1:"
            + hashlib.sha256(
                f"{len(domain)}:{domain}:{len(value)}:{value}".encode()
            ).hexdigest()
        )


_TEST_IDENTITY_TOKENS = _TestIdentityTokens()


def _life_opportunity_facts(
    factory: PostgreSQLUnitOfWorkFactory,
    *,
    environment_id: UUID,
    activity_read: Any,
) -> RuntimeLifeOpportunityFacts:
    async def outlet_health(_outlet: str) -> tuple[str, str | None]:
        return "ready", None

    return RuntimeLifeOpportunityFacts(
        cognition=bootstrap_cognition_operation(),
        interaction=bootstrap_interaction_identity(_TEST_IDENTITY_TOKENS),
        mood=bootstrap_mood().read,
        mind=bootstrap_mind().read,
        outlet_health=outlet_health,
        model_revision=lambda: "isolated-model-config",
    )


_ADMIN_DSN = os.environ.get("S009_ADMIN_DSN")


def _birth_repository() -> BirthRepository:
    return BirthRepository(
        bootstrap_subject_state().birth,
        bootstrap_mind().birth,
        bootstrap_mood().birth,
        bootstrap_prompt().birth,
        bootstrap_interaction_birth(),
    )


def _publishing_artifact_store(
    root: Path,
    factory: PostgreSQLUnitOfWorkFactory,
    *,
    max_object_bytes: int = 1024 * 1024,
) -> ContentAddressedArtifactStore:
    return ContentAddressedArtifactStore(
        root,
        max_object_bytes=max_object_bytes,
        publication_catalog=ArtifactCatalogRepository(),
        publication_uow_factory=factory,
        orphan_grace_seconds=86_400,
    )


_SUMMARY_ENVIRONMENT_ID = UUID("01980f7d-7b8f-7e2a-8a11-2ab8e1234567")
_ADMIN_SOURCE_ROOT = admin_program_identity()["source_root"]
_ADMIN_AUTHORIZATION_KEY = Ed25519PrivateKey.generate()


def _approve_admin_preview(service: AdminToolService, preview: dict[str, Any]) -> str:
    request = preview["authorization_request"]
    config = AdminConfig.model_validate(
        {
            **service.config.model_dump(),
            "operator_id": "isolated-creator-issuer",
            "authorized_operations": ("authorization_approve",),
            "authorization_signing_key_locator": "env:ARMI_SECRET_CREATOR_AUTHORIZATION_KEY",
        }
    )
    credentials = AdminCredentialPort(
        locator=config.locator,
        config_root=config.environment_root.parent,
        authorization_locator=config.authorization_signing_key_locator,
        environ={
            "ARMI_SECRET_CREATOR_AUTHORIZATION_KEY": _ADMIN_AUTHORIZATION_KEY.private_bytes(
                serialization.Encoding.PEM,
                serialization.PrivateFormat.PKCS8,
                serialization.NoEncryption(),
            ).decode()
        },
    )
    AuthorizationStore(config, credentials).approve(
        request["request_id"], request["request_digest"]
    )
    return str(request["request_id"])


def _admin_cli_binding(
    root: Path, fixture: DatabaseFixture, resources: Path | None = None
) -> Path:
    identity = subprocess.run(
        [
            os.environ.get("ARMI_CREATOR_SYSTEM_ENTRY_POINT", sys.executable),
            "-m",
            "armi_admin.cli",
            "identity",
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
        timeout=60,
    )
    secrets = root / "secrets"
    for name, value in (
        ("admin", fixture.admin_role_dsn),
        ("admin-preview", "isolated-preview-key-for-system-tests"),
    ):
        (secrets / name).write_text(value, encoding="utf-8")
    binding = root / "admin.yaml"
    binding.write_text(
        json.dumps(
            {
                "schema_version": "armi.admin-config.v10",
                "operator_id": "isolated-system-agent",
                "authorized_operations": [
                    "configuration.read",
                    "configuration.status",
                    "schema_status",
                    "runtime_status",
                    "subject_snapshot",
                    "inspect_scope",
                    "doctor",
                    "invocation_get",
                    "invocation_wait",
                    "invocation_reconcile",
                    "maintenance.device_bindings",
                    "maintenance.credential_check",
                    "maintenance.database_install",
                    "maintenance.database_check",
                    "maintenance.birth",
                    "maintenance.capacity_check",
                    "environment_start",
                    "environment_stop",
                    "environment_status",
                    "environment_restart",
                    "trace_flow",
                    "health",
                    "data_deletion_preview",
                    "data_deletion_apply",
                    "other_human.party_register",
                    "other_human.scene_set",
                    "other_human.message_send",
                    "other_human.data_rights_request",
                    "other_human.data_rights_get",
                ],
                "environment_kind": "system_test",
                "environment_id": str(fixture.environment_id),
                "environment_incarnation": 1,
                "resettable": True,
                "test_controls_enabled": True,
                "environment_root": str(root.resolve()),
                "experiment_root": str(root.parent.resolve()),
                "creator_web_resources": None
                if resources is None
                else str(resources.resolve()),
                "database_locator": "file:" + (secrets / "admin").as_posix(),
                "migrator_database_locator": "file:"
                + (secrets / "migrator").as_posix(),
                "preview_key_locator": "file:" + (secrets / "admin-preview").as_posix(),
                "authorization_public_key": _ADMIN_AUTHORIZATION_KEY.public_key()
                .public_bytes(
                    serialization.Encoding.Raw, serialization.PublicFormat.Raw
                )
                .hex(),
                "expected": json.loads(identity.stdout),
            }
        ),
        encoding="utf-8",
    )
    signing_file = secrets / "creator-authorization"
    signing_file.write_bytes(
        _ADMIN_AUTHORIZATION_KEY.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    issuer = {
        **json.loads(binding.read_text(encoding="utf-8")),
        "operator_id": "isolated-creator-issuer",
        "authorized_operations": ["authorization_approve"],
        "authorization_signing_key_locator": "file:" + signing_file.as_posix(),
    }
    (root / "issuer.yaml").write_text(json.dumps(issuer), encoding="utf-8")
    return binding


_REMOVED_REDUNDANT_DIGEST_COLUMNS = {
    ("deployment_environments", "bundle_digest"),
    ("deployment_environments", "config_digest"),
    ("deployment_environments", "template_digest"),
    ("deployment_environments", "data_root_identity_digest"),
    ("deployment_environments", "database_identity_digest"),
    ("subject_component_revisions", "semantic_digest"),
    ("cognitive_attempts", "binding_digest"),
    ("cognitive_attempts", "request_digest"),
    ("cognitive_episodes", "policy_digest"),
    ("cognitive_episodes", "mechanism_config_digest"),
    ("cognitive_episodes", "life_query_result_digest"),
    ("opportunities", "source_digest"),
    ("life_material_revisions", "semantic_digest"),
    ("life_material_revisions", "body_digest"),
    ("relationship_revisions", "semantic_digest"),
    ("maintenance_sessions", "schedule_digest"),
    ("effect_attempts", "request_digest"),
    ("effects", "settlement_digest"),
    ("outbox_items", "payload_digest"),
    ("audit_events", "request_digest"),
    ("audit_events", "response_digest"),
    ("audit_events", "artifact_digest"),
    ("audit_events", "details_digest"),
    ("audit_events", "bundle_digest"),
    ("codex_task_sources", "path_scope_digest"),
    ("codex_task_sources", "validation_digest"),
    ("creator_exports", "manifest_digest"),
    ("data_rights_order_items", "execution_digest"),
}


def _uuid7() -> UUID:
    value = bytearray(secrets.token_bytes(16))
    value[6] = (value[6] & 0x0F) | 0x70
    value[8] = (value[8] & 0x3F) | 0x80
    return UUID(bytes=bytes(value))


def _write_creator_resources(root: Path) -> Path:
    content = b"<!doctype html><title>ARMI Creator</title>"
    static = root / "static"
    static.mkdir(parents=True)
    (static / "index.html").write_bytes(content)
    (root / "manifest.json").write_text(
        json.dumps(
            {
                "schema_version": "armi.creator-static.v1",
                "base_path": "/ui/",
                "entrypoint": "static/index.html",
                "runtime_discovery": False,
                "assets": [
                    {
                        "path": "static/index.html",
                        "size": len(content),
                        "sha256": hashlib.sha256(content).hexdigest(),
                        "media_type": "text/html",
                        "cache_class": "entrypoint-no-store",
                    }
                ],
            },
            separators=(",", ":"),
            sort_keys=True,
        ),
        encoding="utf-8",
        newline="\n",
    )
    return root.resolve()


def _write_data_rights_identity_secret(secrets_root: Path) -> Path:
    secret = secrets_root / "data-rights-identity"
    secret.write_text(secrets.token_urlsafe(48), encoding="utf-8", newline="\n")
    return secret


async def _artifact_chunks(*values: bytes) -> AsyncIterator[bytes]:
    for value in values:
        yield value


class _ContextProjectionInvalidation:
    async def invalidate(self, transaction: Any, sources: Any) -> None:
        del transaction, sources
        return None


@dataclass(frozen=True, slots=True)
class DatabaseFixture:
    database: str
    environment_id: UUID
    runtime_role: str
    admin_role: str
    migrator_role: str
    runtime_dsn: str
    admin_role_dsn: str
    migrator_dsn: str
    provisioner_dsn: str


class _ExternalMediaFetch:
    async def fetch(self, **_kwargs: object) -> ExternalMediaContent:
        return ExternalMediaContent(
            base64.b64decode(
                "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
            ),
            "sample.png",
            "image/png",
        )


class _ExternalContentRecognizer:
    async def recognize(self, request) -> ExternalContentRecognitionResult:
        from armi_kernel.application import provider_call

        async with provider_call(
            provider="test_provider", model="test_model", service="generation"
        ) as call:
            await call.capture(
                usage={"input_tokens": 10, "output_tokens": 5},
                provider_request_id="request-1",
            )
        return ExternalContentRecognitionResult(
            ExternalContentRecognitionStatus.SUCCEEDED,
            "图片里有一张测试卡片。",
            "test_provider",
            "test_model",
            "test_model",
            "request-1",
            10,
            5,
            b'{"result":"ok"}\n',
            None,
        )


@pytest.mark.postgresql
@unittest.skipUnless(_ADMIN_DSN, "isolated PostgreSQL 18.4 is not running")
class PostgreSQLIntegrationTests(unittest.TestCase):
    databases: list[DatabaseFixture]

    @classmethod
    def setUpClass(cls) -> None:
        cls.databases = []

    @classmethod
    def tearDownClass(cls) -> None:
        if _ADMIN_DSN is None:
            return
        with psycopg.connect(_ADMIN_DSN, autocommit=True) as connection:
            for fixture in reversed(cls.databases):
                connection.execute(
                    sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(
                        sql.Identifier(fixture.database)
                    )
                )
                for role in (
                    fixture.runtime_role,
                    fixture.admin_role,
                    fixture.migrator_role,
                ):
                    connection.execute(
                        sql.SQL("DROP ROLE IF EXISTS {}").format(sql.Identifier(role))
                    )

    def _raw_database(self, *, locale: str = "C.UTF-8") -> tuple[str, str]:
        assert _ADMIN_DSN is not None
        database = f"s010_{secrets.token_hex(5)}"
        with psycopg.connect(_ADMIN_DSN, autocommit=True) as connection:
            connection.execute(
                sql.SQL(
                    "CREATE DATABASE {} TEMPLATE template0 ENCODING 'UTF8' "
                    "LOCALE_PROVIDER builtin BUILTIN_LOCALE {}"
                ).format(sql.Identifier(database), sql.Literal(locale))
            )
        values = conninfo_to_dict(_ADMIN_DSN)
        return database, make_conninfo(
            host=values["host"],
            port=values["port"],
            dbname=database,
            user=values["user"],
            password=values["password"],
        )

    def _bootstrap(
        self,
        *,
        database: str,
        provisioner_dsn: str,
        environment_id: UUID,
    ) -> DatabaseFixture:
        runtime_password = secrets.token_urlsafe(24)
        admin_password = secrets.token_urlsafe(24)
        migrator_password = secrets.token_urlsafe(24)
        with tempfile.TemporaryDirectory(dir=Path.cwd() / ".tmp") as temporary:
            secret_root = Path(temporary).resolve()
            inputs = {
                "provisioner": provisioner_dsn,
                "runtime": runtime_password,
                "admin": admin_password,
                "migrator": migrator_password,
            }
            paths: dict[str, Path] = {}
            for name, value in inputs.items():
                path = secret_root / name
                path.write_text(value, encoding="utf-8", newline="\n")
                paths[name] = path
            completed = subprocess.run(
                [
                    sys.executable,
                    "-B",
                    "tools/bootstrap_database_roles.py",
                    "--environment-id",
                    str(environment_id),
                    "--secret-root",
                    str(secret_root),
                    "--provisioner-conninfo-file",
                    str(paths["provisioner"]),
                    "--runtime-password-file",
                    str(paths["runtime"]),
                    "--admin-password-file",
                    str(paths["admin"]),
                    "--migrator-password-file",
                    str(paths["migrator"]),
                    "--apply",
                ],
                cwd=Path.cwd(),
                check=False,
                capture_output=True,
                text=True,
            )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(json.loads(completed.stdout)["status"], "pass")
        self.assertNotIn(database, completed.stdout + completed.stderr)
        values = conninfo_to_dict(provisioner_dsn)
        common = {
            "host": values["host"],
            "port": values["port"],
            "dbname": database,
        }
        runtime_role = physical_role_name(environment_id, "runtime")
        admin_role = physical_role_name(environment_id, "admin")
        migrator_role = physical_role_name(environment_id, "migrator")
        fixture = DatabaseFixture(
            database=database,
            environment_id=environment_id,
            runtime_role=runtime_role,
            admin_role=admin_role,
            migrator_role=migrator_role,
            runtime_dsn=make_conninfo(
                **common, user=runtime_role, password=runtime_password
            ),
            admin_role_dsn=make_conninfo(
                **common, user=admin_role, password=admin_password
            ),
            migrator_dsn=make_conninfo(
                **common, user=migrator_role, password=migrator_password
            ),
            provisioner_dsn=provisioner_dsn,
        )
        type(self).databases.append(fixture)
        return fixture

    def create_database(
        self,
        *,
        locale: str = "C.UTF-8",
        environment_id: UUID | None = None,
    ) -> DatabaseFixture:
        database, provisioner_dsn = self._raw_database(locale=locale)
        return self._bootstrap(
            database=database,
            provisioner_dsn=provisioner_dsn,
            environment_id=environment_id or _uuid7(),
        )

    def _install_current(
        self,
        conninfo: str,
        *,
        environment_id: UUID,
    ) -> Any:
        gateway = PostgreSQLSchemaGateway()
        return gateway.install(conninfo, environment_id=environment_id)

    @pytest.mark.test_group("live-voice")
    def test_voice_playback_result_survives_restart_without_attempt_table(self) -> None:
        from armi_interaction.bootstrap import (
            bootstrap_interaction_recovery,
            compose_interaction_perception,
        )
        from armi_kernel.application import ProviderCallReceipt, estimate_cost
        from armi_live_voice.api import (
            AttemptOutcome,
            LiveVoiceBinding,
            LiveVoiceViolation,
            VoiceActivityState,
            VoiceProviderBinding,
            VoiceProviderService,
        )
        from armi_live_voice.bootstrap import (
            bootstrap_live_voice_recovery,
            compose_live_voice_journal,
        )
        from armi_runtime_foundation import RecoveryScope

        fixture = self.create_database()
        self._install_current(
            fixture.migrator_dsn, environment_id=fixture.environment_id
        )

        async def exercise(root: Path) -> None:
            factory = await self._new_uow_factory(fixture)
            try:
                born = await BirthTransaction(
                    _publishing_artifact_store(root, factory),
                    ArtifactCatalogRepository(),
                    _birth_repository(),
                    factory,
                ).birth(
                    BirthManifest(
                        schema_version="armi.birth-manifest.v1",
                        environment_id=fixture.environment_id,
                        birth_request_id=_uuid7(),
                        creator_party_id=_uuid7(),
                        idempotency_key="voice-playback-results",
                        personality_anchor=PersonalityAnchor(
                            schema_version="armi.personality-anchor.v1",
                            voice_style="约 16 岁少女口吻",
                            traits=("好奇",),
                        ),
                        birth_contract_digest=packaged_birth_digests()[
                            "birth_contract_digest"
                        ],
                        request_digest=Digest.from_bytes(b"voice-playback-results"),
                    )
                )
                async with factory.unit_of_work(read_only=True) as unit:
                    scene = await (
                        await unit.transaction.execute(
                            "SELECT scene_id,primary_party_id FROM armi.interaction_scenes "
                            "WHERE subject_id=%s AND scene_key='default'",
                            (born.subject_id,),
                        )
                    ).fetchone()
                assert scene is not None
                events = []
                activity = VoiceActivityState()
                journal = compose_live_voice_journal(
                    factory=factory,
                    subject_id=born.subject_id,
                    creator_party_id=scene[1],
                    scene_id=scene[0],
                    binding=LiveVoiceBinding(
                        "Windows WASAPI",
                        "microphone",
                        "Windows WASAPI",
                        "speaker",
                        VoiceProviderBinding(
                            VoiceProviderService.ASR, "volcengine", "asr"
                        ),
                        VoiceProviderBinding(
                            VoiceProviderService.LLM, "ark", "llm", "model"
                        ),
                        VoiceProviderBinding(
                            VoiceProviderService.TTS, "volcengine", "tts", "voice"
                        ),
                    ),
                    timeline=compose_interaction_perception(),
                    activity=activity,
                    playback_diagnostic=lambda *event: events.append(event),
                )
                session_id = _uuid7()
                await journal.open_session(session_id=session_id)

                def pending_receipt():
                    return ProviderCallReceipt(
                        str(_uuid7()),
                        "test-provider",
                        "test-model",
                        "asr",
                        "voice_asr",
                        datetime.now(UTC).isoformat(),
                        None,
                        estimate_cost(
                            quantities=(),
                            required_units=(),
                            snapshot=None,
                            billable=True,
                        ),
                        True,
                    )

                session_receipt = pending_receipt()
                await journal.record_provider_call(
                    turn_id=None,
                    session_id=session_id,
                    receipt=session_receipt,
                )
                turn_receipts = []
                turns = []
                for number, outcome in enumerate(
                    (
                        None,
                        AttemptOutcome.COMPLETED,
                        AttemptOutcome.PARTIAL,
                        AttemptOutcome.FAILED,
                    ),
                    1,
                ):
                    turn_id = _uuid7()
                    turns.append(turn_id)
                    await journal.begin_turn(
                        session_id=session_id,
                        turn_id=turn_id,
                        turn_no=number,
                        context_version="ctx:1",
                    )
                    receipt = pending_receipt()
                    turn_receipts.append(receipt)
                    await journal.record_provider_call(
                        turn_id=turn_id,
                        session_id=None,
                        receipt=receipt,
                    )
                    with self.assertRaises(LiveVoiceViolation):
                        await journal.record_provider_call(
                            turn_id=turn_id,
                            session_id=None,
                            receipt=receipt,
                        )
                    await journal.record_transcript(
                        turn_id=turn_id,
                        transcript="你好",
                        interaction_id=None,
                        opportunity_id=None,
                    )
                    await journal.mark_playback_dispatched(turn_id=turn_id)
                    with self.assertRaises(LiveVoiceViolation):
                        await journal.mark_playback_dispatched(turn_id=turn_id)
                    if outcome is not AttemptOutcome.FAILED:
                        await journal.register_fragment(
                            turn_id=turn_id, fragment_no=1, text="你好"
                        )
                        await journal.mark_playback_first_frame(turn_id=turn_id)
                    if outcome is not None:
                        await journal.settle_playback(
                            turn_id=turn_id,
                            outcome=outcome,
                            frames_written=0 if outcome is AttemptOutcome.FAILED else 2,
                            error_code=None
                            if outcome is AttemptOutcome.COMPLETED
                            else "VOICE-TEST-FAILED",
                        )
                        with self.assertRaises(LiveVoiceViolation):
                            await journal.settle_playback(
                                turn_id=turn_id,
                                outcome=AttemptOutcome.UNKNOWN,
                                frames_written=0,
                                error_code="VOICE-TEST-FAILED",
                            )
                # A fresh Runtime has no process-local microphone session.
                activity.session_id = None
                async with factory.unit_of_work() as unit:
                    await bootstrap_interaction_recovery().recover(
                        unit.transaction,
                        RecoveryScope(
                            fixture.environment_id,
                            born.subject_id,
                            born.bundle_activation_id,
                            _uuid7(),
                            1,
                        ),
                        (),
                    )
                    await bootstrap_live_voice_recovery().recover(
                        unit.transaction,
                        RecoveryScope(
                            fixture.environment_id,
                            born.subject_id,
                            born.bundle_activation_id,
                            _uuid7(),
                            1,
                        ),
                        (),
                    )
                async with factory.unit_of_work(read_only=True) as unit:
                    usage = await (
                        await unit.transaction.execute(
                            "SELECT reference_kind,reference_id,receipt->>'outcome' "
                            "FROM armi.provider_usage_calls WHERE owner='live-voice'"
                        )
                    ).fetchall()
                self.assertEqual(len(usage), 5)
                self.assertTrue(all(row[2] == "unknown" for row in usage))
                self.assertEqual({row[1] for row in usage}, {scene[0], *turns})
                for turn_id, receipt in [
                    (None, session_receipt),
                    (turns[0], turn_receipts[0]),
                ]:
                    parent_session = session_id if turn_id is None else None
                    with self.assertRaises(LiveVoiceViolation):
                        await journal.record_provider_call(
                            turn_id=turn_id,
                            session_id=parent_session,
                            receipt=pending_receipt(),
                        )
                    with self.assertRaises(LiveVoiceViolation):
                        await journal.record_provider_call(
                            turn_id=turn_id,
                            session_id=parent_session,
                            receipt=replace(
                                pending_receipt(),
                                finished_at=datetime.now(UTC).isoformat(),
                            ),
                        )
                    await journal.record_provider_call(
                        turn_id=turn_id,
                        session_id=parent_session,
                        receipt=replace(
                            receipt,
                            outcome="returned",
                            finished_at=datetime.now(UTC).isoformat(),
                        ),
                    )
                async with factory.unit_of_work(read_only=True) as unit:
                    returned = await (
                        await unit.transaction.execute(
                            "SELECT count(*) FROM armi.provider_usage_calls "
                            "WHERE owner='live-voice' AND receipt->>'outcome'='returned'"
                        )
                    ).fetchone()
                self.assertEqual(returned, (2,))
                async with factory.unit_of_work(read_only=True) as unit:
                    rows = await (
                        await unit.transaction.execute(
                            "SELECT playback_extent,frames_written FROM armi.live_voice_turns "
                            "WHERE session_id=%s ORDER BY turn_no",
                            (session_id,),
                        )
                    ).fetchall()
                    completed = (
                        await bootstrap_live_voice_context_read().completed_playback(
                            unit.transaction,
                            turn_id=turns[1],
                        )
                    )
                    interrupted = (
                        await bootstrap_live_voice_context_read().completed_playback(
                            unit.transaction,
                            turn_id=turns[0],
                        )
                    )
                self.assertEqual(
                    rows,
                    [
                        ("unknown_completion", 1),
                        ("complete", 2),
                        ("partial_prefix", 2),
                        ("none", 0),
                    ],
                )
                assert completed is not None
                self.assertEqual(completed[:2], (turns[1], "你好"))
                self.assertIsNone(interrupted)
                self.assertEqual(len(events), 10)
                # A session that never produces a turn still retains actual usage.
                next_session = _uuid7()
                await journal.open_session(session_id=next_session)
                no_turn_receipt = pending_receipt()
                await journal.record_provider_call(
                    turn_id=None, session_id=next_session, receipt=no_turn_receipt
                )
                await journal.close_session(session_id=session_id)
                async with factory.unit_of_work(read_only=True) as unit:
                    pending = await (
                        await unit.transaction.execute(
                            "SELECT receipt->>'outcome' FROM armi.provider_usage_calls "
                            "WHERE receipt->>'call_id'=%s",
                            (no_turn_receipt.call_id,),
                        )
                    ).fetchone()
                self.assertEqual(pending, ("pending",))
                await journal.close_session(session_id=next_session)
                with self.assertRaises(LiveVoiceViolation):
                    await journal.begin_turn(
                        session_id=next_session,
                        turn_id=_uuid7(),
                        turn_no=1,
                        context_version="ctx:1",
                    )
                async with factory.unit_of_work(read_only=True) as unit:
                    ended = await (
                        await unit.transaction.execute(
                            "SELECT last_voice_ended_at,voice_provider_calls->%s->>'outcome' "
                            "FROM armi.interaction_scenes WHERE scene_id=%s",
                            (no_turn_receipt.call_id, scene[0]),
                        )
                    ).fetchone()
                assert ended is not None
                self.assertIsNotNone(ended[0])
                self.assertEqual(ended[1], "unknown")
            finally:
                await factory.close()

        with tempfile.TemporaryDirectory(dir=Path.cwd() / ".tmp") as temporary:
            asyncio.run(
                exercise(Path(temporary).resolve()),
                loop_factory=lambda: asyncio.SelectorEventLoop(
                    selectors.SelectSelector()
                ),
            )

    @pytest.mark.test_group("data-rights", "interaction")
    def test_data_rights_guards_live_on_party_and_environment(self) -> None:
        from armi_data_rights._postgresql import DataRightsOrderRepository
        from armi_data_rights.api import DataRightsOrderKind, DataRightsViolation
        from armi_interaction.bootstrap import bootstrap_interaction_party_catalog
        from armi_runtime.adapters.persistence.environment_identity import (
            PostgreSQLEnvironmentIdentity,
        )

        fixture = self.create_database()
        self._install_current(
            fixture.migrator_dsn, environment_id=fixture.environment_id
        )
        party_id = uuid7()
        with psycopg.connect(fixture.provisioner_dsn) as connection:
            connection.execute(
                "INSERT INTO armi.parties(party_id,party_kind,creator_role) VALUES (%s,'creator','unique_primary_creator')",
                (party_id,),
            )
        with (
            psycopg.connect(fixture.runtime_dsn) as connection,
            self.assertRaises(psycopg.errors.InsufficientPrivilege),
        ):
            connection.execute(
                "UPDATE armi.deployment_environments SET identity_key_digest=NULL,environment_kind='active'"
            )

        async def exercise() -> None:
            factory = PostgreSQLUnitOfWorkFactory(
                fixture.runtime_dsn,
                environment_id=fixture.environment_id,
                pool_min=1,
                pool_max=1,
                acquire_timeout_seconds=2,
                statement_timeout_seconds=5,
                require_runtime_fence=False,
            )
            await factory.open()
            try:
                parties = bootstrap_interaction_party_catalog()
                repository = DataRightsOrderRepository(parties)
                identity = PostgreSQLEnvironmentIdentity()
                key = Digest.from_bytes(b"identity-key").value
                async with factory.unit_of_work() as unit:
                    self.assertFalse(
                        await identity.bind_identity_key(
                            unit.transaction, key_identity=key
                        )
                    )
                with psycopg.connect(fixture.provisioner_dsn) as connection:
                    connection.execute(
                        "INSERT INTO armi.deployment_environments (environment_id,environment_kind,incarnation,resettable,test_controls_enabled) VALUES (%s,'system_test',1,true,true)",
                        (fixture.environment_id,),
                    )
                async with factory.unit_of_work() as unit:
                    self.assertTrue(
                        await identity.bind_identity_key(
                            unit.transaction, key_identity=key
                        )
                    )
                async with factory.unit_of_work() as unit:
                    self.assertTrue(
                        await identity.bind_identity_key(
                            unit.transaction, key_identity=key
                        )
                    )
                    self.assertFalse(
                        await identity.bind_identity_key(
                            unit.transaction,
                            key_identity=Digest.from_bytes(b"other-key").value,
                        )
                    )
                    before = await repository.capture(
                        unit.transaction, party_id=party_id
                    )
                    self.assertEqual(
                        (before.contact_generation, before.use_generation), (1, 1)
                    )
                    contact = await repository.advance_fence(
                        unit.transaction,
                        party_id=party_id,
                        order_kind=DataRightsOrderKind.STOP_CONTACT,
                    )
                    self.assertEqual(
                        (contact.contact_generation, contact.use_generation), (2, 1)
                    )
                    await repository.validate(
                        unit.transaction,
                        before,
                        require_contact=False,
                        require_use=True,
                    )
                    with self.assertRaises(DataRightsViolation):
                        await repository.validate(
                            unit.transaction,
                            before,
                            require_contact=True,
                            require_use=False,
                        )
                    stopped = await repository.advance_fence(
                        unit.transaction,
                        party_id=party_id,
                        order_kind=DataRightsOrderKind.STOP_USE,
                    )
                    self.assertEqual(
                        (stopped.contact_generation, stopped.use_generation), (3, 2)
                    )
                    with self.assertRaises(DataRightsViolation):
                        await repository.validate(
                            unit.transaction,
                            contact,
                            require_contact=False,
                            require_use=True,
                        )
                    self.assertEqual(
                        await parties.all_party_fences(unit.transaction),
                        ((party_id, 3, 2),),
                    )
                    with self.assertRaises(DataRightsViolation):
                        await repository.capture(unit.transaction, party_id=uuid7())
            finally:
                await factory.close()

        asyncio.run(
            exercise(),
            loop_factory=lambda: asyncio.SelectorEventLoop(selectors.SelectSelector()),
        )

    @pytest.mark.test_group("data-rights")
    def test_retry_keys_live_on_order_and_old_keys_do_not_start_new_cycles(
        self,
    ) -> None:
        from unittest.mock import AsyncMock, Mock

        from armi_data_rights._application import DataRightsOrderService
        from armi_data_rights._postgresql import DataRightsOrderRepository
        from armi_data_rights.api import DataRightsRetryCommand

        fixture = self.create_database()
        self._install_current(
            fixture.migrator_dsn, environment_id=fixture.environment_id
        )
        creator, order_id, export_id = uuid7(), uuid7(), uuid7()
        with psycopg.connect(fixture.provisioner_dsn) as connection:
            connection.execute(
                "INSERT INTO armi.parties(party_id,party_kind,creator_role) VALUES (%s,'creator','unique_primary_creator')",
                (creator,),
            )
            connection.execute(
                """INSERT INTO armi.data_rights_orders(
                   deletion_order_id,requester_party_id,requester_kind,order_kind,scope_kind,scope_party_id,
                   reason_code,status,execution_status,idempotency_key,request_digest,trace_id,completed_at)
                   VALUES (%s,%s,'creator','delete_related','party_local_data',%s,
                   'requester_exercised_local_right','effective','partial','retry-test',%s,%s,statement_timestamp())""",
                (
                    order_id,
                    creator,
                    creator,
                    Digest.from_bytes(b"retry-test").value,
                    uuid7().hex,
                ),
            )
            connection.execute(
                """INSERT INTO armi.creator_exports(
                   creator_export_id,creator_party_id,directory_name,idempotency_key,request_digest,status,
                   destination_path,snapshot_contract_version,snapshot_status,completed_at)
                   VALUES (%s,%s,'retry-test','retry-test',%s,'completed',%s,'test','active',statement_timestamp())""",
                (
                    export_id,
                    creator,
                    Digest.from_bytes(b"export").value,
                    str((Path.cwd() / ".tmp" / str(export_id)).resolve()),
                ),
            )
            connection.execute(
                """INSERT INTO armi.data_rights_order_items(
                   deletion_item_id,deletion_order_id,target_kind,target_ref,required_action,responsible_owner,
                   result_status,operator_action_required,completed_at)
                   VALUES (%s,%s,'managed_snapshot',%s,'operator_remove','data-rights','partial',true,statement_timestamp())""",
                (uuid7(), order_id, export_id),
            )

        async def exercise() -> None:
            factory = await self._new_uow_factory(fixture)
            lifecycle = Mock(
                deletion_states=AsyncMock(return_value=()),
                retry_blocked=AsyncMock(return_value=0),
            )
            service = DataRightsOrderService(
                creator_party_id=creator,
                custody=cast(Any, Mock()),
                deletion=cast(Any, Mock(execute=AsyncMock())),
                repository=DataRightsOrderRepository(cast(Any, Mock())),
                unit_of_work_factory=factory,
                parties=cast(Any, Mock(creator_party=AsyncMock(return_value=creator))),
                lifecycle=cast(Any, lifecycle),
                participants=(cast(Any, Mock()),),
                owner_contracts=(),
                identity_key="test",
                identity_binding=cast(Any, Mock()),
                data_root=Path.cwd() / ".tmp",
            )
            try:
                first = DataRightsRetryCommand(
                    IdempotencyKey("first"), TraceId(uuid7().hex)
                )
                second = DataRightsRetryCommand(
                    IdempotencyKey("second"), TraceId(uuid7().hex)
                )
                assert (await service.retry_creator(order_id, first)).newly_created
                assert not (await service.retry_creator(order_id, first)).newly_created
                async with factory.unit_of_work() as unit:
                    await unit.transaction.execute(
                        "UPDATE armi.data_rights_orders SET execution_status='partial',completed_at=statement_timestamp() WHERE deletion_order_id=%s",
                        (order_id,),
                    )
                    await unit.transaction.execute(
                        "UPDATE armi.creator_exports SET snapshot_status='active',snapshot_removed_at=NULL WHERE creator_export_id=%s",
                        (export_id,),
                    )
                    await unit.transaction.execute(
                        "UPDATE armi.data_rights_order_items SET result_status='partial',operator_action_required=true WHERE deletion_order_id=%s",
                        (order_id,),
                    )
                assert (await service.retry_creator(order_id, second)).newly_created
                assert not (await service.retry_creator(order_id, first)).newly_created
                async with factory.unit_of_work(read_only=True) as unit:
                    row = await (
                        await unit.transaction.execute(
                            "SELECT retry_cycle,retry_requests FROM armi.data_rights_orders WHERE deletion_order_id=%s",
                            (order_id,),
                        )
                    ).fetchone()
                    assert row is not None and row[0] == 3
                    assert {
                        key: value["cycle"]
                        for key, value in cast(
                            dict[str, dict[str, Any]], row[1]
                        ).items()
                    } == {
                        "first": 2,
                        "second": 3,
                    }
                assert lifecycle.retry_blocked.await_count == 2
            finally:
                await factory.close()

        asyncio.run(
            exercise(),
            loop_factory=lambda: asyncio.SelectorEventLoop(selectors.SelectSelector()),
        )

    @pytest.mark.test_group("data-rights")
    def test_export_file_state_and_party_links_share_export_record(self) -> None:
        from armi_data_rights._creator_export import CreatorExportService
        from armi_data_rights._data_rights_participant import (
            PostgreSQLDataRightsParticipant,
        )
        from armi_data_rights.api import CreatorExportStatus, DataRightsDiscoveryRequest

        fixture = self.create_database()
        self._install_current(
            fixture.migrator_dsn, environment_id=fixture.environment_id
        )
        creator_id = uuid7()
        with psycopg.connect(fixture.provisioner_dsn) as connection:
            connection.execute(
                """INSERT INTO armi.parties(party_id,party_kind,creator_role)
                   VALUES (%s,'creator','unique_primary_creator')""",
                (creator_id,),
            )

        async def exercise(root: Path) -> None:
            factory = PostgreSQLUnitOfWorkFactory(
                fixture.runtime_dsn,
                environment_id=fixture.environment_id,
                pool_min=1,
                pool_max=1,
                acquire_timeout_seconds=2,
                statement_timeout_seconds=5,
                require_runtime_fence=False,
            )
            await factory.open()
            try:
                service = CreatorExportService(
                    creator_party_id=creator_id,
                    data_root=root,
                    unit_of_work_factory=factory,
                    participants=(),
                    custody=cast(Any, None),
                    storage=cast(Any, None),
                    party_roster=cast(Any, None),
                )
                participant = PostgreSQLDataRightsParticipant()
                for status in (
                    CreatorExportStatus.COMPLETED,
                    CreatorExportStatus.PARTIAL,
                    CreatorExportStatus.FAILED,
                ):
                    export_id = uuid7()
                    async with factory.unit_of_work() as unit:
                        await unit.transaction.execute(
                            """INSERT INTO armi.creator_exports(
                               creator_export_id,creator_party_id,directory_name,idempotency_key,
                               request_digest,status,destination_path)
                               VALUES (%s,%s,%s,%s,%s,'building',%s)""",
                            (
                                export_id,
                                creator_id,
                                str(export_id),
                                str(export_id),
                                Digest.from_bytes(b"export").value,
                                str(root / str(export_id)),
                            ),
                        )
                    await service._settle(
                        export_id=export_id,
                        trace_id=TraceId(uuid7().hex),
                        status=status,
                        segment_count=0,
                        record_count=0,
                        artifact_count=0,
                        missing_count=1 if status is CreatorExportStatus.PARTIAL else 0,
                        error_code="CREATOR-EXPORT-FAILED"
                        if status is CreatorExportStatus.FAILED
                        else None,
                        party_scopes=((creator_id, 1, 1),),
                    )
                    async with factory.unit_of_work() as unit:
                        row = await (
                            await unit.transaction.execute(
                                """SELECT snapshot_status,snapshot_contract_version,snapshot_removed_at,snapshot_party_scopes
                               FROM armi.creator_exports WHERE creator_export_id=%s""",
                                (export_id,),
                            )
                        ).fetchone()
                        assert row is not None
                        discovery = await participant.discover(
                            unit.transaction,
                            DataRightsDiscoveryRequest(uuid7(), creator_id, ()),
                        )
                        refs = {item.ref for item in discovery.related_refs}
                        if status is CreatorExportStatus.FAILED:
                            self.assertEqual(row, (None, None, None, {}))
                            self.assertNotIn(export_id, refs)
                        else:
                            self.assertEqual(row[3], {str(creator_id): [1, 1]})
                            unrelated = await participant.discover(
                                unit.transaction,
                                DataRightsDiscoveryRequest(uuid7(), uuid7(), ()),
                            )
                            self.assertNotIn(
                                export_id, {item.ref for item in unrelated.related_refs}
                            )
                            self.assertEqual(row[0], "active")
                            self.assertIsNotNone(row[1])
                            self.assertIn(export_id, refs)
                            await unit.transaction.execute(
                                """UPDATE armi.creator_exports
                                   SET snapshot_status='removed',snapshot_removed_at=statement_timestamp()
                                   WHERE creator_export_id=%s""",
                                (export_id,),
                            )
                            discovery = await participant.discover(
                                unit.transaction,
                                DataRightsDiscoveryRequest(uuid7(), creator_id, ()),
                            )
                            self.assertNotIn(
                                export_id, {item.ref for item in discovery.related_refs}
                            )
                            settled = await (
                                await unit.transaction.execute(
                                    "SELECT status FROM armi.creator_exports WHERE creator_export_id=%s",
                                    (export_id,),
                                )
                            ).fetchone()
                            self.assertEqual(settled, (status.value,))
            finally:
                await factory.close()

        with tempfile.TemporaryDirectory(dir=Path.cwd() / ".tmp") as temporary:
            asyncio.run(
                exercise(Path(temporary).resolve()),
                loop_factory=lambda: asyncio.SelectorEventLoop(
                    selectors.SelectSelector()
                ),
            )

    @pytest.mark.test_group("data-rights", "artifacts", "live-vision", "perception")
    def test_data_rights_artifact_fk_contract_matches_installed_catalog(self) -> None:
        fixture = self.create_database()
        self._install_current(
            fixture.migrator_dsn,
            environment_id=fixture.environment_id,
        )
        with psycopg.connect(fixture.runtime_dsn) as connection:
            installed = connection.execute(
                """SELECT source_table.relname,source_column.attname
                   FROM pg_catalog.pg_constraint AS fk
                   JOIN pg_catalog.pg_class AS source_table
                     ON source_table.oid=fk.conrelid
                   JOIN pg_catalog.pg_namespace AS source_namespace
                     ON source_namespace.oid=source_table.relnamespace
                   JOIN pg_catalog.pg_class AS target_table
                     ON target_table.oid=fk.confrelid
                   JOIN pg_catalog.pg_namespace AS target_namespace
                     ON target_namespace.oid=target_table.relnamespace
                   JOIN pg_catalog.pg_attribute AS source_column
                     ON source_column.attrelid=source_table.oid
                    AND source_column.attnum=fk.conkey[1]
                   JOIN pg_catalog.pg_attribute AS target_column
                     ON target_column.attrelid=target_table.oid
                    AND target_column.attnum=fk.confkey[1]
                   WHERE fk.contype='f'
                     AND pg_catalog.cardinality(fk.conkey)=1
                     AND pg_catalog.cardinality(fk.confkey)=1
                     AND source_namespace.nspname='armi'
                     AND target_namespace.nspname='armi'
                     AND target_table.relname='artifacts'
                     AND target_column.attname='artifact_id'
                   ORDER BY source_table.relname,source_column.attname"""
            ).fetchall()
        declared = sorted(
            (field.table_name, field.column_name)
            for contract in DATA_RIGHTS_OWNER_CONTRACTS
            for field in contract.artifact_fields
        )
        self.assertEqual(installed, declared)

    @pytest.mark.test_group("admin", "runtime")
    @pytest.mark.test_group("live-voice")
    def test_provider_usage_summary_filters_and_pagination_share_receipts(self) -> None:
        from dataclasses import replace
        from datetime import UTC, datetime

        from armi_kernel.application import (
            PriceSnapshot,
            ProviderMeterScope,
            UnitPrice,
            UsageFilter,
            UsageQuery,
            UsageUnit,
            provider_call,
            provider_meter_scope,
        )
        from armi_local_control import (
            UsageCall,
            UsageCalls,
            UsageSummary,
        )
        from armi_runtime_foundation import (
            usage_result,
            usage_statement,
        )

        fixture = self.create_database()
        self._install_current(
            fixture.migrator_dsn, environment_id=fixture.environment_id
        )
        rows = {}
        prices = PriceCatalog(
            (
                PriceSnapshot(
                    "test-price",
                    "test-provider",
                    "test-model",
                    "generation",
                    datetime(2020, 1, 1, tzinfo=UTC),
                    datetime(2020, 1, 1, tzinfo=UTC),
                    "https://example.test/official-pricing",
                    (
                        UnitPrice(UsageUnit.INPUT_TOKENS, 2, 1),
                        UnitPrice(UsageUnit.CACHED_INPUT_TOKENS, 1, 1),
                        UnitPrice(UsageUnit.OUTPUT_TOKENS, 6, 1),
                    ),
                ),
            )
        )

        async def generate() -> None:
            async def save(receipt):
                rows[receipt.call_id] = replace(
                    receipt, started_at="2026-09-15T16:00:00+00:00"
                )

            with provider_meter_scope(
                ProviderMeterScope(save, prices, "credential_verification")
            ):
                async with provider_call(
                    provider="test-provider", model="test-model", service="generation"
                ) as call:
                    await call.capture(
                        usage={
                            "input_tokens": 100,
                            "cached_input_tokens": 40,
                            "output_tokens": 20,
                        }
                    )
                async with provider_call(
                    provider="test-provider", model="test-model", service="asr"
                ) as call:
                    await call.finish("unknown")
                async with provider_call(
                    provider="test-provider", model="unpriced", service="generation"
                ) as call:
                    await call.capture(
                        usage={
                            "input_tokens": 10,
                            "cached_input_tokens": 0,
                            "output_tokens": 1,
                        }
                    )
                async with provider_call(
                    provider="test-provider", model="test-model", service="tokenization"
                ) as call:
                    await call.capture(usage={"input_tokens": 999})

        asyncio.run(generate())
        checks = tuple(
            {"verification_id": str(uuid7()), "call": row.document()}
            for row in rows.values()
        )
        filters = UsageFilter.from_strings(
            start="2026-09-16T00:00:00+08:00", end="2026-09-17T00:00:00+08:00"
        )
        with psycopg.connect(fixture.admin_role_dsn) as connection:

            def query(request):
                statement, parameters = usage_statement(request, checks)
                return usage_result(
                    connection.execute(
                        cast(LiteralString, statement), parameters
                    ).fetchone()
                )

            summary = UsageSummary.model_validate(query(UsageQuery("summary", filters)))
            self.assertEqual(summary.totals.billable_calls, 3)
            self.assertEqual(summary.totals.auxiliary_requests, 1)
            self.assertEqual(summary.totals.known_microyuan, 280)
            self.assertEqual(summary.totals.usage_unconfirmed_calls, 1)
            self.assertEqual(summary.totals.unpriced_calls, 1)
            self.assertEqual(summary.units["input_tokens"], 110)
            self.assertEqual(summary.daily[0].date, "2026-09-16")
            first = UsageCalls.model_validate(
                query(UsageQuery("list", filters, limit=1))
            )
            second = UsageCalls.model_validate(
                query(UsageQuery("list", filters, limit=1, offset=1))
            )
            self.assertEqual(first.total, 3)
            self.assertNotEqual(
                first.items[0].receipt.call_id, second.items[0].receipt.call_id
            )
            detail = UsageCall.model_validate(
                query(
                    UsageQuery("read", filters, call_id=first.items[0].receipt.call_id)
                )
            )
            self.assertEqual(detail, first.items[0])
            selected = replace(filters, model="unpriced")
            filtered = UsageSummary.model_validate(
                query(UsageQuery("summary", selected))
            )
            self.assertEqual(filtered.totals.billable_calls, 1)
            self.assertIsNone(filtered.totals.known_microyuan)
            empty = UsageSummary.model_validate(
                query(UsageQuery("summary", replace(filters, model="absent")))
            )
            self.assertEqual(empty.totals.billable_calls, 0)
            self.assertIsNone(empty.totals.known_microyuan)
            operation_only = UsageSummary.model_validate(
                query(
                    UsageQuery("summary", replace(filters, operation_id=str(uuid7())))
                )
            )
            self.assertEqual(operation_only.totals.billable_calls, 0)

    @pytest.mark.test_group("attention", "activity")
    def test_autonomy_persistent_two_stage_plan_without_quota(self) -> None:
        self._exercise_autonomy_plan(psychological=False)

    @pytest.mark.test_group("attention", "cognition", "mind", "mood")
    def test_psychological_attention_advances_plan_and_settles_once(self) -> None:
        self._exercise_autonomy_plan(psychological=True)

    @pytest.mark.test_group("attention", "mind", "cognition")
    def test_concern_review_wakes_once_without_mood_or_external_input(self) -> None:
        self._exercise_autonomy_plan(psychological=False, concern=True)

    def _exercise_autonomy_plan(
        self, *, psychological: bool, concern: bool = False
    ) -> None:
        from armi_attention.api import (
            AutonomyPolicy,
            LifeViolation,
            OpportunityCognitionSelectionScope,
            OpportunitySelectionCursor,
        )
        from armi_local_control import AutonomyHistory, AutonomyStatus
        from armi_runtime_foundation import autonomy_result, autonomy_statement

        fixture = self.create_database()
        self._install_current(
            fixture.migrator_dsn, environment_id=fixture.environment_id
        )
        policy = AutonomyPolicy()
        owner = bootstrap_autonomy()

        async def exercise(root: Path) -> None:
            factory = PostgreSQLUnitOfWorkFactory(
                fixture.runtime_dsn,
                environment_id=fixture.environment_id,
                pool_min=1,
                pool_max=4,
                acquire_timeout_seconds=5,
                statement_timeout_seconds=5,
                require_runtime_fence=False,
            )
            await factory.open()
            try:
                birth = BirthTransaction(
                    _publishing_artifact_store(root, factory),
                    ArtifactCatalogRepository(),
                    _birth_repository(),
                    factory,
                )
                born = await birth.birth(
                    BirthManifest(
                        schema_version="armi.birth-manifest.v1",
                        environment_id=fixture.environment_id,
                        birth_request_id=uuid7(),
                        creator_party_id=uuid7(),
                        idempotency_key="autonomy-fixture",
                        personality_anchor=PersonalityAnchor(
                            schema_version="armi.personality-anchor.v1",
                            voice_style="约 16 岁少女口吻",
                            traits=("清醒",),
                        ),
                        birth_contract_digest=packaged_birth_digests()[
                            "birth_contract_digest"
                        ],
                        request_digest=Digest.from_bytes(b"autonomy-fixture"),
                    )
                )
                facts = _life_opportunity_facts(
                    factory, environment_id=fixture.environment_id, activity_read=None
                )
                async with factory.unit_of_work() as unit:
                    initial = await owner.ensure_plan(
                        unit.transaction, subject_id=born.subject_id, policy=policy
                    )
                    outcome = await owner.admit_due(
                        unit.transaction,
                        subject_id=born.subject_id,
                        policy=policy,
                        signals=await facts.consideration_signals(
                            unit.transaction,
                            subject_id=born.subject_id,
                            minimum_delay_seconds=60,
                        ),
                    )
                    self.assertEqual(outcome.reason_code, "LIFE-AUTONOMY-NOT-DUE")
                async with factory.unit_of_work() as unit:
                    resumed = await owner.ensure_plan(
                        unit.transaction, subject_id=born.subject_id, policy=policy
                    )
                    self.assertEqual(resumed, initial)
                    await unit.transaction.execute(
                        "UPDATE armi.autonomy_plans SET next_consideration_at=statement_timestamp()+interval '6 hours' WHERE subject_id=%s",
                        (born.subject_id,),
                    )
                    await unit.transaction.execute(
                        "UPDATE armi.subjects SET state_epoch=state_epoch+1 WHERE subject_id=%s",
                        (born.subject_id,),
                    )
                    changed = await owner.ensure_plan(
                        unit.transaction,
                        subject_id=born.subject_id,
                        policy=policy,
                        state_epoch=1,
                    )
                    self.assertGreater(
                        changed.next_consideration_at,
                        datetime.now(UTC) + timedelta(hours=5),
                    )
                    repeated = await owner.ensure_plan(
                        unit.transaction,
                        subject_id=born.subject_id,
                        policy=policy,
                        state_epoch=1,
                    )
                    self.assertEqual(changed, repeated)
                    if concern:
                        from armi_mind.api import ConcernRecord, TimedReview

                        now = datetime.now(UTC) - timedelta(hours=8)
                        records = (
                            ConcernRecord(
                                concern_id=uuid7(),
                                question="What changed the leaf direction?",
                                reason="A synthetic observation remains unexplained",
                                resolution_condition="A supported causal explanation",
                                understanding="No explanation is known",
                                state="waiting",
                                review=TimedReview(
                                    kind="review",
                                    after_seconds=300,
                                    reason="Reconsider with elapsed time",
                                ),
                                review_at=now + timedelta(seconds=300),
                                created_at=now,
                                updated_at=now,
                                source_commit_id=uuid7(),
                                basis_ordinals=(1,),
                            ),
                        )
                        await unit.transaction.execute(
                            "UPDATE armi.mind_revisions SET semantic_payload="
                            "jsonb_set(semantic_payload,'{concerns}',%s::jsonb) WHERE subject_id=%s",
                            (
                                json.dumps(
                                    [item.model_dump(mode="json") for item in records]
                                ),
                                born.subject_id,
                            ),
                        )
                        await unit.transaction.execute(
                            "UPDATE armi.autonomy_plans SET next_consideration_at=statement_timestamp()+interval '6 hours' WHERE subject_id=%s",
                            (born.subject_id,),
                        )
                        for _ in range(3):
                            await facts.consideration_signals(
                                unit.transaction,
                                subject_id=born.subject_id,
                                minimum_delay_seconds=60,
                            )
                    elif psychological:
                        # No external event/state-epoch wakeup: a six-hour plan
                        # must be advanced by the real Mood read/Attention path.
                        await unit.transaction.execute(
                            "UPDATE armi.autonomy_plans SET next_consideration_at=statement_timestamp()+interval '6 hours' WHERE subject_id=%s",
                            (born.subject_id,),
                        )
                        await facts.consideration_signals(
                            unit.transaction,
                            subject_id=born.subject_id,
                            minimum_delay_seconds=60,
                        )
                        quiet = await owner.admit_due(
                            unit.transaction,
                            subject_id=born.subject_id,
                            policy=policy,
                            signals=await facts.consideration_signals(
                                unit.transaction,
                                subject_id=born.subject_id,
                                minimum_delay_seconds=60,
                            ),
                        )
                        self.assertEqual(quiet.reason_code, "LIFE-AUTONOMY-NOT-DUE")
                        # Synthetic affect evidence, confined to this disposable
                        # database. Never injected into the installed subject.
                        await unit.transaction.execute(
                            """INSERT INTO armi.mood_appraisal_events (
                                mood_appraisal_event_id,subject_id,mood_revision_id,
                                mood_episode_id,transition,event_phase,gist,basis_ordinals,
                                appraisal_payload,importance,derived_vad,derived_components,
                                derivation_version,dynamics_version,privacy_scope,
                                appraisal_mapping_version,derived_appraisal_payload,occurred_at,
                                affect_intensity,affect_half_life_seconds)
                               SELECT %s,subject_id,mood_revision_id,%s,'new','ongoing',
                                      '有件事还没弄明白',ARRAY[1]::smallint[],
                                      '{"schema_version":"armi.mood-appraisal.v3"}'::jsonb,
                                      60,'{"valence":0,"arousal":20,"dominance":0}'::jsonb,
                                      %s::jsonb,'cpm-fuzzy.v4','recency-reappraisal.v1','private',
                                      'semantic-anchors.v1',
                                      '{"schema_version":"armi.mood-derived-appraisal.v3"}'::jsonb,
                                      statement_timestamp()-interval '2 minutes',60,3600
                               FROM armi.mood_revisions WHERE is_current AND subject_id=%s""",
                            (
                                uuid7(),
                                uuid7(),
                                json.dumps(
                                    [
                                        {
                                            "family": "confusion",
                                            "nuance": "想弄清楚",
                                            "vad": {
                                                "valence": 0,
                                                "arousal": 20,
                                                "dominance": 0,
                                            },
                                            "intensity": 60,
                                            "half_life_seconds": 3600,
                                        }
                                    ]
                                ),
                                born.subject_id,
                            ),
                        )
                        for _ in range(3):
                            await facts.consideration_signals(
                                unit.transaction,
                                subject_id=born.subject_id,
                                minimum_delay_seconds=60,
                            )
                    else:
                        # Virtual elapsed time in this isolated database.
                        await unit.transaction.execute(
                            "UPDATE armi.autonomy_plans SET next_consideration_at=statement_timestamp()-interval '3 days' WHERE subject_id=%s",
                            (born.subject_id,),
                        )
                    admitted = await owner.admit_due(
                        unit.transaction,
                        subject_id=born.subject_id,
                        policy=policy,
                        signals=await facts.consideration_signals(
                            unit.transaction,
                            subject_id=born.subject_id,
                            minimum_delay_seconds=60,
                        ),
                    )
                    self.assertEqual(
                        admitted.status, OpportunityAdmissionStatus.ADMITTED
                    )
                async with factory.unit_of_work() as unit:
                    duplicate = await owner.admit_due(
                        unit.transaction,
                        subject_id=born.subject_id,
                        policy=policy,
                        signals=await facts.consideration_signals(
                            unit.transaction,
                            subject_id=born.subject_id,
                            minimum_delay_seconds=60,
                        ),
                    )
                    self.assertEqual(
                        duplicate.status, OpportunityAdmissionStatus.DUPLICATE
                    )
                    self.assertEqual(duplicate.opportunity_id, admitted.opportunity_id)
                    cognition_owner = bootstrap_opportunity_cognition()
                    selected = await cognition_owner.next_candidate(
                        unit.transaction,
                        scope=OpportunityCognitionSelectionScope(born.subject_id),
                    )
                    assert selected is not None
                    self.assertEqual(selected.opportunity_id, admitted.opportunity_id)
                    self.assertEqual(selected.selection_priority, 1)
                    frozen_opportunity = await cognition_owner.context_snapshot(
                        unit.transaction,
                        opportunity_id=selected.opportunity_id,
                    )
                    assert frozen_opportunity.autonomy_context is not None
                    self.assertIn(
                        "last_considered_at",
                        json.loads(frozen_opportunity.autonomy_context),
                    )
                    exhausted = await cognition_owner.next_candidate(
                        unit.transaction,
                        scope=OpportunityCognitionSelectionScope(born.subject_id),
                        after=OpportunitySelectionCursor(
                            selected.available_after,
                            selected.opportunity_id,
                            selected.selection_priority,
                        ),
                    )
                    self.assertIsNone(exhausted)
                    await cognition_owner.select_for_cognition(
                        unit.transaction, opportunity_id=selected.opportunity_id
                    )
                    await cognition_owner.freeze_signals(
                        unit.transaction,
                        opportunity_id=selected.opportunity_id,
                        signals=await facts.consideration_signals(
                            unit.transaction,
                            subject_id=born.subject_id,
                            minimum_delay_seconds=60,
                        ),
                        frozen_at=datetime.now(UTC),
                    )

                assert admitted.opportunity_id is not None

                async def finish_check(opportunity_id: UUID, engage: bool) -> UUID:
                    episode = uuid7()
                    async with factory.unit_of_work() as unit:
                        await unit.transaction.execute(
                            """INSERT INTO armi.cognitive_episodes (
                                cognitive_episode_id,opportunity_id,subject_id,purpose,status,
                                base_subject_version,base_state_epoch,bundle_activation_id,
                                mechanism_identity,trace_id)
                               SELECT %s,%s,subject_id,'consider_autonomy_check','preparing',
                                      subject_version,state_epoch,current_bundle_activation_id,
                                      'armi.context-compiler.layered-v3',%s
                               FROM armi.subjects WHERE subject_id=%s""",
                            (episode, opportunity_id, "3" * 32, born.subject_id),
                        )
                        await cognition_owner.resolve_autonomy_check(
                            unit.transaction,
                            opportunity_id=opportunity_id,
                            episode_id=episode,
                            engage=engage,
                        )
                        await unit.transaction.execute(
                            """UPDATE armi.cognitive_episodes SET status='completed',
                               final_disposition='no_change',application_resolution='no_change',
                               committed_at=statement_timestamp(),validated_at=statement_timestamp()
                               WHERE cognitive_episode_id=%s""",
                            (episode,),
                        )
                    return episode

                await finish_check(admitted.opportunity_id, False)
                async with factory.unit_of_work(read_only=True) as unit:
                    statement, parameters = autonomy_statement("status")
                    row = await (
                        await unit.transaction.execute(
                            cast(LiteralString, statement),
                            parameters,
                        )
                    ).fetchone()
                    raw = autonomy_result(row)
                    raw.pop("consumed_signal_keys")
                    status = AutonomyStatus.model_validate(raw)
                    self.assertEqual(status.phase, "waiting")
                    self.assertEqual(status.idle_streak, 1)
                    self.assertIs(status.last_engage, False)
                    self.assertEqual(status.stage_usage["check"].calls, 0)
                    self.assertGreater(
                        datetime.fromisoformat(cast(str, status.next_consideration_at)),
                        datetime.now(UTC) + timedelta(seconds=110),
                    )
                    statement, parameters = autonomy_statement("history")
                    history = AutonomyHistory.model_validate(
                        autonomy_result(
                            await (
                                await unit.transaction.execute(
                                    cast(LiteralString, statement),
                                    parameters,
                                )
                            ).fetchone()
                        )
                    )
                    self.assertEqual(history.total, 1)
                    self.assertEqual(history.items[0].stage, "check")

                # Virtual time: no quota after repeated checks and no catch-up burst.
                last_check_id = admitted.opportunity_id
                for round_no in range(52):
                    async with factory.unit_of_work() as unit:
                        await unit.transaction.execute(
                            """UPDATE armi.autonomy_plans SET
                                 next_consideration_at=statement_timestamp()-interval '3 days',
                                 last_check_started_at=statement_timestamp()-interval '60 seconds'
                               WHERE subject_id=%s""",
                            (born.subject_id,),
                        )
                        current = await owner.admit_due(
                            unit.transaction,
                            subject_id=born.subject_id,
                            policy=policy,
                        )
                        self.assertEqual(
                            current.status, OpportunityAdmissionStatus.ADMITTED
                        )
                        assert current.opportunity_id is not None
                        last_check_id = current.opportunity_id
                        self.assertTrue(
                            await cognition_owner.select_for_cognition(
                                unit.transaction,
                                opportunity_id=current.opportunity_id,
                            )
                        )
                    await finish_check(current.opportunity_id, round_no == 51)
                    async with factory.unit_of_work() as unit:
                        plan = await owner.ensure_plan(
                            unit.transaction,
                            subject_id=born.subject_id,
                            policy=policy,
                        )
                        if round_no < 51:
                            self.assertIsNone(plan.opportunity_id)
                            self.assertGreater(
                                plan.next_consideration_at,
                                datetime.now(UTC) + timedelta(seconds=290),
                            )
                            not_due = await owner.admit_due(
                                unit.transaction,
                                subject_id=born.subject_id,
                                policy=policy,
                            )
                            self.assertEqual(
                                not_due.reason_code, "LIFE-AUTONOMY-NOT-DUE"
                            )
                        else:
                            assert plan.opportunity_id is not None
                            self.assertTrue(
                                await cognition_owner.select_for_cognition(
                                    unit.transaction,
                                    opportunity_id=plan.opportunity_id,
                                )
                            )
                            self.assertFalse(
                                await cognition_owner.select_for_cognition(
                                    unit.transaction,
                                    opportunity_id=plan.opportunity_id,
                                )
                            )
                # Duplicate settlement cannot create a second full cognition.
                with self.assertRaisesRegex(LifeViolation, "LIFE-AUTONOMY-PLAN-STALE"):
                    async with factory.unit_of_work() as unit:
                        await cognition_owner.resolve_autonomy_check(
                            unit.transaction,
                            opportunity_id=last_check_id,
                            episode_id=uuid7(),
                            engage=True,
                        )
                # Preemption also discards an execution opportunity before it has
                # an episode. The next idle period must start a fresh light check.
                async with factory.unit_of_work() as unit:
                    await cognition_owner.interrupt_autonomy(
                        unit.transaction, subject_id=born.subject_id
                    )
                    reset = await owner.ensure_plan(
                        unit.transaction, subject_id=born.subject_id, policy=policy
                    )
                    self.assertIsNone(reset.opportunity_id)
                    self.assertGreater(
                        reset.next_consideration_at,
                        datetime.now(UTC) + timedelta(seconds=50),
                    )
                for index, code in enumerate(
                    (
                        "MODEL-CONNECTION",
                        "MODEL-CONNECTION",
                        "MODEL-CONNECTION",
                        "MODEL-CREDENTIAL",
                    )
                ):
                    async with factory.unit_of_work() as unit:
                        await unit.transaction.execute(
                            "UPDATE armi.autonomy_plans SET next_consideration_at=statement_timestamp()-interval '1 second',last_check_started_at=statement_timestamp()-interval '61 seconds' WHERE subject_id=%s",
                            (born.subject_id,),
                        )
                        check = await owner.admit_due(
                            unit.transaction, subject_id=born.subject_id, policy=policy
                        )
                        assert check.opportunity_id is not None
                        await cognition_owner.select_for_cognition(
                            unit.transaction, opportunity_id=check.opportunity_id
                        )
                        self.assertTrue(
                            await cognition_owner.resolve_cognition_failure(
                                unit.transaction,
                                opportunity_id=check.opportunity_id,
                                failure_code=code,
                            )
                        )
                        state = await (
                            await unit.transaction.execute(
                                "SELECT phase,failure_streak,EXTRACT(EPOCH FROM next_consideration_at-statement_timestamp()) FROM armi.autonomy_plans WHERE subject_id=%s",
                                (born.subject_id,),
                            )
                        ).fetchone()
                        assert state is not None
                        self.assertEqual(
                            state[0],
                            "blocked" if code == "MODEL-CREDENTIAL" else "waiting",
                        )
                        self.assertEqual(state[1], min(index + 1, 3))
                        self.assertAlmostEqual(
                            float(state[2]), (60, 120, 300, 300)[index], delta=2
                        )
                async with factory.unit_of_work() as unit:
                    await unit.transaction.execute(
                        "UPDATE armi.autonomy_plans SET next_consideration_at=statement_timestamp()-interval '1 hour',last_check_started_at=NULL WHERE subject_id=%s",
                        (born.subject_id,),
                    )
                    blocked = await owner.admit_due(
                        unit.transaction, subject_id=born.subject_id, policy=policy
                    )
                    self.assertEqual(blocked.reason_code, "LIFE-AUTONOMY-NOT-DUE")
            finally:
                await factory.close()

        with tempfile.TemporaryDirectory(dir=Path.cwd() / ".tmp") as directory:
            asyncio.run(
                exercise(Path(directory)),
                loop_factory=lambda: asyncio.SelectorEventLoop(
                    selectors.SelectSelector()
                ),
            )

    @pytest.mark.test_group(
        "admin",
        "memory",
        "relationship",
        "material",
        "subject-state",
        "mind",
        "mood",
        "prompt",
    )
    def test_online_content_owner_revisions_receipts_and_busy_fences(self) -> None:
        from armi_admin.application.content_contracts import ContentWriteRequest

        def one(
            connection: Any, statement: str, parameters: tuple[Any, ...] = ()
        ) -> Any:
            row = connection.execute(statement, parameters).fetchone()
            self.assertIsNotNone(row)
            return row

        fixture = self.create_database()
        self._install_current(
            fixture.migrator_dsn, environment_id=fixture.environment_id
        )
        packaged = packaged_birth_digests()
        manifest = BirthManifest(
            schema_version="armi.birth-manifest.v1",
            environment_id=fixture.environment_id,
            birth_request_id=uuid7(),
            creator_party_id=uuid7(),
            idempotency_key="online-admin-birth",
            personality_anchor=PersonalityAnchor(
                schema_version="armi.personality-anchor.v1",
                voice_style="约 16 岁少女口吻",
                traits=("清醒",),
            ),
            birth_contract_digest=packaged["birth_contract_digest"],
            request_digest=Digest.from_bytes(b"online-admin-birth"),
        )

        async def birth_subject(root: Path) -> Any:
            factory = PostgreSQLUnitOfWorkFactory(
                fixture.runtime_dsn,
                environment_id=fixture.environment_id,
                pool_min=1,
                pool_max=2,
                acquire_timeout_seconds=2,
                statement_timeout_seconds=5,
                require_runtime_fence=False,
            )
            birth = BirthTransaction(
                _publishing_artifact_store(root / "data/artifacts", factory),
                ArtifactCatalogRepository(),
                _birth_repository(),
                factory,
            )
            await factory.open()
            try:
                return await birth.birth(manifest)
            finally:
                await factory.close()

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            born = asyncio.run(
                birth_subject(root),
                loop_factory=lambda: asyncio.SelectorEventLoop(
                    selectors.SelectSelector()
                ),
            )
            with psycopg.connect(fixture.provisioner_dsn) as connection:
                connection.execute(
                    "INSERT INTO armi.deployment_environments (environment_id,environment_kind,incarnation,resettable,test_controls_enabled) VALUES (%s,'acceptance',1,true,true)",
                    (fixture.environment_id,),
                )
                commits_before = one(
                    connection,
                    "SELECT count(*) FROM armi.cognitive_episodes WHERE subject_commit_id IS NOT NULL",
                )[0]
            config = AdminConfig.model_validate(
                {
                    "schema_version": "armi.admin-config.v10",
                    "operator_id": "isolated-content-admin",
                    "authorized_operations": ("content_write",),
                    "environment_kind": "acceptance",
                    "environment_id": str(fixture.environment_id),
                    "environment_incarnation": 1,
                    "resettable": True,
                    "test_controls_enabled": True,
                    "environment_root": root,
                    "experiment_root": root,
                    "database_locator": "env:ARMI_SECRET_ADMIN_DATABASE",
                    "migrator_database_locator": "env:ARMI_SECRET_MIGRATOR_DATABASE",
                    "preview_key_locator": "env:ARMI_SECRET_ADMIN_PREVIEW_KEY",
                    "expected": {"source_root": _ADMIN_SOURCE_ROOT},
                }
            )
            credentials = AdminCredentialPort(
                locator=config.locator,
                migrator_locator=config.migrator_locator,
                preview_locator=config.preview_locator,
                config_root=root,
                environ={
                    "ARMI_SECRET_ADMIN_DATABASE": fixture.admin_role_dsn,
                    "ARMI_SECRET_MIGRATOR_DATABASE": fixture.migrator_dsn,
                    "ARMI_SECRET_ADMIN_PREVIEW_KEY": "isolated-content-preview",
                },
            )
            composition = bootstrap_admin(config, credentials, local_owner=True)

            def request(
                owner: str,
                action: str,
                identity: str,
                version: int,
                data: Any,
                key: str,
            ) -> ContentWriteRequest:
                return ContentWriteRequest.model_validate_json(
                    json.dumps(
                        {
                            "environment_id": str(fixture.environment_id),
                            "idempotency_key": key,
                            "reason": "isolated online content acceptance",
                            "expected_subject_id": str(born.subject_id),
                            "change": {
                                "owner": owner,
                                "action": action,
                                "object_id": identity,
                                "expected_version": version,
                                "data": data,
                            },
                        }
                    )
                )

            def invoke(value: ContentWriteRequest) -> Any:
                result = composition.service.database("content_write", value)
                self.assertEqual(result.status, "succeeded", result.model_dump_json())
                assert result.result is not None
                self.assertEqual(result.result["execution_mode"], "online")
                return result

            try:
                cases = {
                    "memory": {"summary": "管理员提供的说明", "uncertainty": None},
                    "activity": {"goal": "整理测试资料", "next_safe_step": "阅读说明"},
                    "material": {
                        "material_kind": "draft",
                        "title": "测试资料",
                        "body": "管理员写入的资料正文",
                    },
                    "prompt": {
                        "prompt_kind": "creator_guidance",
                        "content": "保持清晰表达。",
                    },
                    "relationship": {
                        "other_party_id": str(manifest.creator_party_id),
                        "facts": [
                            {
                                "fact_id": str(uuid7()),
                                "kind": "party_expression",
                                "summary": "管理员说明",
                            }
                        ],
                        "interpretation": "管理员提供的关系说明",
                    },
                }

                async def memory_context() -> Any:
                    factory = PostgreSQLUnitOfWorkFactory(
                        fixture.runtime_dsn,
                        environment_id=fixture.environment_id,
                        pool_min=1,
                        pool_max=1,
                        acquire_timeout_seconds=2,
                        statement_timeout_seconds=5,
                        require_runtime_fence=False,
                    )
                    module = bootstrap_memory(
                        factory,
                        environment_id=fixture.environment_id,
                        creator_party_id=manifest.creator_party_id,
                        subject_id=born.subject_id,
                        cursor_key=hashlib.sha256(b"online-content-read").digest(),
                        visibility=bootstrap_data_rights_core().visibility,
                    )
                    await factory.open()
                    try:
                        async with factory.unit_of_work(read_only=True) as unit:
                            return await module.read.maintenance_context(
                                unit.transaction,
                                subject_id=born.subject_id,
                                enabled=True,
                            )
                    finally:
                        await factory.close()

                for owner, data in cases.items():
                    with self.subTest(owner=owner):
                        identity = str(uuid7())
                        created = request(
                            owner, "create", identity, 0, data, owner + "-create"
                        )
                        first = invoke(created)
                        repeated = invoke(created)
                        self.assertEqual(first.result, repeated.result)
                        revised = {
                            key: value
                            for key, value in data.items()
                            if key not in {"material_kind", "other_party_id"}
                        }
                        if owner == "memory":
                            revised["summary"] = "Administrator revised this memory"
                        invoke(
                            request(
                                owner, "update", identity, 1, revised, owner + "-update"
                            )
                        )
                        if owner == "memory":
                            current_context = asyncio.run(
                                memory_context(),
                                loop_factory=lambda: asyncio.SelectorEventLoop(
                                    selectors.SelectSelector()
                                ),
                            )
                            self.assertEqual(len(current_context), 1)
                            self.assertEqual(current_context[0].head_version, 2)
                            self.assertEqual(
                                current_context[0].summary, revised["summary"]
                            )
                            self.assertEqual(
                                current_context[0].source_kind.value, "administrator"
                            )
                        conflict = composition.service.database(
                            "content_write",
                            request(
                                owner, "update", identity, 1, revised, owner + "-stale"
                            ),
                        )
                        self.assertEqual(
                            conflict.status, "conflict", conflict.model_dump_json()
                        )
                        removed = invoke(
                            request(
                                owner, "delete", identity, 2, None, owner + "-delete"
                            )
                        )
                        self.assertTrue(removed.result["change"]["history_retained"])
                        self.assertEqual(removed.result["change"]["new_version"], 3)
                with psycopg.connect(fixture.provisioner_dsn) as connection:
                    components = connection.execute(
                        "SELECT component_kind,component_version,semantic_payload FROM armi.subject_component_revisions WHERE subject_id=%s",
                        (born.subject_id,),
                    ).fetchall()
                    mood = one(
                        connection,
                        "SELECT mood_version,semantic_payload FROM armi.mood_revisions WHERE subject_id=%s",
                        (born.subject_id,),
                    )
                with psycopg.connect(fixture.provisioner_dsn) as connection:
                    mind = one(
                        connection,
                        "SELECT mind_version,semantic_payload FROM armi.mind_revisions WHERE subject_id=%s",
                        (born.subject_id,),
                    )
                invoke(
                    request(
                        "mind",
                        "update",
                        str(born.subject_id),
                        mind[0],
                        {"replacement": mind[1]},
                        "mind-update",
                    )
                )
                for kind, version, payload in components:
                    invoke(
                        request(
                            "subject_state",
                            "update",
                            str(born.subject_id),
                            version,
                            {"component_kind": kind, "replacement": payload},
                            kind + "-update",
                        )
                    )
                invoke(
                    request(
                        "mood",
                        "update",
                        str(born.subject_id),
                        mood[0],
                        {"component_kind": "mood", "replacement": mood[1]},
                        "mood-update",
                    )
                )
                with psycopg.connect(fixture.provisioner_dsn) as blocker:
                    blocker.execute(
                        "SELECT pg_advisory_xact_lock_shared(hashtextextended(%s,0))",
                        (
                            "armi.execution-custody:runtime_authority:"
                            + str(fixture.environment_id),
                        ),
                    )
                    busy = composition.service.database(
                        "content_write",
                        request(
                            "memory",
                            "create",
                            str(uuid7()),
                            0,
                            cases["memory"],
                            "memory-busy",
                        ),
                    )
                    self.assertEqual(busy.status, "conflict", busy.model_dump_json())
                    self.assertIn("ADMIN-CONTENT-BUSY", busy.model_dump_json())
                with psycopg.connect(fixture.provisioner_dsn) as connection:
                    self.assertEqual(
                        one(
                            connection,
                            "SELECT count(*) FROM armi.cognitive_episodes WHERE subject_commit_id IS NOT NULL",
                        )[0],
                        commits_before,
                    )
                    self.assertEqual(
                        one(connection, "SELECT count(*) FROM armi.admin_data_changes")[
                            0
                        ],
                        19,
                    )
                    self.assertEqual(
                        one(
                            connection,
                            "SELECT count(*) FROM armi.subjective_memory_revisions WHERE admin_change_id IS NOT NULL AND source_experience_id IS NULL AND subject_commit_id IS NULL",
                        )[0],
                        3,
                    )
            finally:
                composition.close()

    @pytest.mark.test_group("admin", "schema")
    def test_structured_database_management_types_conflicts_and_atomic_receipts(
        self,
    ) -> None:
        from unittest.mock import Mock, patch

        from armi_admin.application.database_contracts import (
            DatabaseBatchRequest,
            DatabaseCatalogRequest,
            DatabaseQueryRequest,
        )
        from armi_admin.application.database_management import DatabaseManagement
        from armi_admin.persistence.database_tables import DatabaseTableError
        from armi_postgresql_contract.table_policy import (
            TABLE_OWNERSHIP,
            TableOwnership,
        )

        fixture = self.create_database()
        self._install_current(
            fixture.migrator_dsn, environment_id=fixture.environment_id
        )
        with psycopg.connect(fixture.provisioner_dsn) as connection:
            connection.execute(
                "INSERT INTO armi.deployment_environments (environment_id,environment_kind,incarnation,resettable,test_controls_enabled) VALUES (%s,'acceptance',1,true,false)",
                (fixture.environment_id,),
            )
            # A real PostgreSQL table exercises codecs and constraints that do not all occur together in a business table.
            connection.execute(
                "CREATE TABLE armi.database_management_fixture (id uuid PRIMARY KEY, amount numeric(30,9) NOT NULL, payload jsonb NOT NULL, occurred_at timestamptz NOT NULL, content bytea NOT NULL, tags integer[] NOT NULL, count integer NOT NULL CHECK (count >= 0))"
            )
            connection.execute(
                "GRANT SELECT,INSERT,UPDATE,DELETE ON armi.database_management_fixture TO armi_admin"
            )
        config = Mock(spec=AdminConfig)
        config.environment_id = str(fixture.environment_id)
        config.environment_incarnation = 1
        config.operator_id = "isolated-admin"
        pool = AdminRoleBoundPool(
            fixture.admin_role_dsn, expected_role=fixture.admin_role
        )
        manager = DatabaseManagement(config, pool)
        environment: dict[str, Any] = {"environment_id": str(fixture.environment_id)}
        first_id, second_id = str(uuid7()), str(uuid7())

        def batch(key: str, changes: list[dict[str, Any]]) -> DatabaseBatchRequest:
            return DatabaseBatchRequest.model_validate_json(
                json.dumps(
                    {
                        **environment,
                        "idempotency_key": key,
                        "reason": "isolated database verification",
                        "changes": changes,
                    }
                )
            )

        values = {
            "id": first_id,
            "amount": "123456789012345678901.123456789",
            "payload": {"postgresql_json": '{"exact":123456789012345678901.123456789}'},
            "occurred_at": "2026-09-11T01:02:03.123456+00:00",
            "content": "\\x0001ff",
            "tags": "{1,2,3}",
            "count": 1,
        }
        try:
            with patch.dict(
                TABLE_OWNERSHIP,
                {
                    "database_management_fixture": TableOwnership(
                        "runtime", maintenance_writable=True
                    )
                },
            ):
                catalog = manager.read(DatabaseCatalogRequest(**environment))
                policies = {table["table"]: table for table in catalog["tables"]}
                self.assertFalse(policies["subjects"]["permissions"]["update"])
                self.assertFalse(
                    policies["admin_data_changes"]["permissions"]["insert"]
                )
                insert = batch(
                    "insert",
                    [
                        {
                            "action": "insert",
                            "table": "database_management_fixture",
                            "values": values,
                        }
                    ],
                )
                receipt = manager.mutate(insert)
                self.assertEqual(manager.mutate(insert), receipt)
                page = manager.read(
                    DatabaseQueryRequest(
                        **environment, table="database_management_fixture", limit=1
                    )
                )
                row = page["rows"][0]
                self.assertEqual(row["values"]["amount"], values["amount"])
                self.assertEqual(row["values"]["content"], values["content"])
                self.assertEqual(row["values"]["tags"], "{1,2,3}")
                self.assertIn(
                    "123456789012345678901.123456789",
                    row["values"]["payload"]["postgresql_json"],
                )
                update = {
                    "action": "update",
                    "table": "database_management_fixture",
                    "key": {"id": first_id},
                    "expected_version": row["version"],
                    "values": {"count": 2},
                }
                with self.assertRaises(psycopg.errors.CheckViolation):
                    manager.mutate(
                        batch(
                            "rollback",
                            [
                                update,
                                {
                                    "action": "insert",
                                    "table": "database_management_fixture",
                                    "values": {**values, "id": second_id, "count": -1},
                                },
                            ],
                        )
                    )
                after_failure = manager.read(
                    DatabaseQueryRequest(
                        **environment, table="database_management_fixture"
                    )
                )
                self.assertEqual(after_failure["rows"], page["rows"])
                changed = manager.mutate(batch("update", [update]))
                with self.assertRaisesRegex(DatabaseTableError, "VERSION-CONFLICT"):
                    manager.mutate(batch("stale", [update]))
                deletion = batch(
                    "delete",
                    [
                        {
                            "action": "delete",
                            "table": "database_management_fixture",
                            "key": {"id": first_id},
                            "expected_version": changed["changes"][0]["new_version"],
                        }
                    ],
                )
                manager.mutate(deletion)
                self.assertEqual(
                    manager.read(
                        DatabaseQueryRequest(
                            **environment, table="database_management_fixture"
                        )
                    )["rows"],
                    [],
                )
                with self.assertRaisesRegex(DatabaseTableError, "READ-ONLY"):
                    manager.mutate(
                        batch(
                            "protected",
                            [
                                {
                                    "action": "insert",
                                    "table": "subjects",
                                    "values": {"subject_id": str(uuid7())},
                                }
                            ],
                        )
                    )
            with psycopg.connect(fixture.admin_role_dsn) as connection:
                keys = connection.execute(
                    "SELECT idempotency_key FROM armi.admin_data_changes ORDER BY idempotency_key"
                ).fetchall()
                self.assertEqual(keys, [("delete",), ("insert",), ("update",)])
        finally:
            pool.close()

    @pytest.mark.test_group("schema", "admin")
    def test_current_schema_installs_once_into_an_empty_database(self) -> None:
        fixture = self.create_database(environment_id=_SUMMARY_ENVIRONMENT_ID)
        installed = self._install_current(
            fixture.migrator_dsn,
            environment_id=fixture.environment_id,
        )
        self.assertEqual(installed.status, "current")
        self.assertGreater(installed.table_count, 0)
        self.assertEqual(installed.current_revision, "0000")
        self.assertEqual(installed.head_revision, "0000")
        for digest in (
            installed.resource_digest,
            installed.catalog_digest,
            installed.role_policy_digest,
        ):
            self.assertRegex(digest, r"^sha256:[0-9a-f]{64}$")
        status = PostgreSQLSchemaGateway().status(
            fixture.runtime_dsn,
            environment_id=fixture.environment_id,
        )
        self.assertEqual(status.status, "current")
        self.assertEqual(status.table_count, installed.table_count)
        with psycopg.connect(fixture.provisioner_dsn) as connection:
            extension = connection.execute(
                """
                SELECT extension.extversion, namespace.nspname,
                       has_schema_privilege(%s, namespace.nspname, 'USAGE')
                FROM pg_catalog.pg_extension AS extension
                JOIN pg_catalog.pg_namespace AS namespace
                  ON namespace.oid = extension.extnamespace
                WHERE extension.extname = 'vector'
                """,
                (fixture.runtime_role,),
            ).fetchone()
            table_dml = connection.execute(
                """
                SELECT grantee.rolname, relation.relname,
                       privilege.privilege_type
                FROM pg_catalog.pg_class AS relation
                JOIN pg_catalog.pg_namespace AS namespace
                  ON namespace.oid = relation.relnamespace
                CROSS JOIN LATERAL pg_catalog.aclexplode(
                    COALESCE(
                        relation.relacl,
                        pg_catalog.acldefault('r', relation.relowner)
                    )
                ) AS privilege
                JOIN pg_catalog.pg_roles AS grantee
                  ON grantee.oid = privilege.grantee
                WHERE namespace.nspname = 'armi'
                  AND grantee.rolname IN ('armi_runtime', 'armi_admin')
                  AND privilege.privilege_type IN ('INSERT', 'UPDATE', 'DELETE')
                ORDER BY grantee.rolname, relation.relname,
                         privilege.privilege_type
                """
            ).fetchall()
            column_dml = connection.execute(
                """
                SELECT grantee.rolname, relation.relname,
                       privilege.privilege_type, attribute.attname
                FROM pg_catalog.pg_attribute AS attribute
                CROSS JOIN LATERAL pg_catalog.aclexplode(
                    attribute.attacl
                ) AS privilege
                JOIN pg_catalog.pg_roles AS grantee
                  ON grantee.oid = privilege.grantee
                JOIN pg_catalog.pg_class AS relation
                  ON relation.oid = attribute.attrelid
                JOIN pg_catalog.pg_namespace AS namespace
                  ON namespace.oid = relation.relnamespace
                WHERE namespace.nspname = 'armi'
                  AND grantee.rolname IN ('armi_runtime', 'armi_admin')
                  AND privilege.privilege_type IN ('INSERT', 'UPDATE')
                """
            ).fetchall()
            separated = connection.execute(
                """
                SELECT has_table_privilege(%s, 'armi.effect_observations', 'INSERT'),
                       has_table_privilege(%s, 'armi.effect_observations', 'UPDATE'),
                       has_table_privilege(%s, 'armi.effect_observations', 'DELETE'),
                       has_table_privilege(%s, 'armi.effects', 'UPDATE')
                """,
                (
                    fixture.runtime_role,
                    fixture.runtime_role,
                    fixture.runtime_role,
                    fixture.admin_role,
                ),
            ).fetchone()
        self.assertEqual(extension, ("0.8.6", "armi_extensions", True))
        self.assertEqual(frozenset(table_dml), CURRENT_DML_CAPABILITIES)
        self.assertEqual(frozenset(column_dml), CURRENT_COLUMN_DML_CAPABILITIES)
        self.assertEqual(separated, (True, False, False, True))
        with self.assertRaises(DatabaseViolation) as repeated:
            self._install_current(
                fixture.migrator_dsn,
                environment_id=fixture.environment_id,
            )
        self.assertEqual(repeated.exception.code, "DB-SCHEMA-EXISTS")

    @pytest.mark.test_group("live-vision")
    def test_visual_observation_owns_receipts_and_does_not_repeat_interrupted_call(
        self,
    ) -> None:
        from unittest.mock import AsyncMock

        from armi_kernel.application import provider_call
        from armi_live_vision.api import (
            CameraSourceIdentity,
            ObservationOriginKind,
            ObservationTrigger,
            VisualFrame,
            VisualSourceKind,
        )
        from armi_live_vision.bootstrap import compose_visual_observation_sink
        from armi_perception.api import (
            ExternalContentRecognitionStatus,
            VisualChangeClass,
            VisualRecognitionResult,
        )

        fixture = self.create_database()
        self._install_current(
            fixture.migrator_dsn, environment_id=fixture.environment_id
        )

        async def exercise(root: Path) -> None:
            factory = await self._new_uow_factory(fixture)
            try:
                born = await BirthTransaction(
                    _publishing_artifact_store(root, factory),
                    ArtifactCatalogRepository(),
                    _birth_repository(),
                    factory,
                ).birth(
                    BirthManifest(
                        schema_version="armi.birth-manifest.v1",
                        environment_id=fixture.environment_id,
                        birth_request_id=_uuid7(),
                        creator_party_id=_uuid7(),
                        idempotency_key="visual-receipts",
                        personality_anchor=PersonalityAnchor(
                            schema_version="armi.personality-anchor.v1",
                            voice_style="约 16 岁少女口吻",
                            traits=("好奇",),
                        ),
                        birth_contract_digest=packaged_birth_digests()[
                            "birth_contract_digest"
                        ],
                        request_digest=Digest.from_bytes(b"visual-receipts"),
                    )
                )

                interrupted = False
                events = []
                calls = []

                async def recognize(request):
                    async with provider_call(
                        provider="test-provider",
                        model="test-model",
                        service="generation",
                    ) as call:
                        calls.append(call)
                        if interrupted:
                            await sink.settle_interrupted_observations(
                                error_code="VISION-TEST-INTERRUPTED"
                            )
                            raise asyncio.CancelledError()
                        await call.capture(
                            usage={"input_tokens": 10, "output_tokens": 4},
                            provider_request_id="request-1",
                        )
                    return VisualRecognitionResult(
                        ExternalContentRecognitionStatus.SUCCEEDED,
                        "桌上有一个杯子",
                        "出现一个杯子",
                        VisualChangeClass.NOTABLE,
                        (),
                        "test-provider",
                        "test-model",
                        "test-model",
                        "request-1",
                        10,
                        4,
                        b'{"summary":"cup"}',
                        None,
                    )

                sink = compose_visual_observation_sink(
                    factory=factory,
                    storage=_publishing_artifact_store(root, factory),
                    catalog=ArtifactCatalogRepository(),
                    work=PostgreSQLDurableWorkGateway(factory),
                    recognizer=AsyncMock(recognize_visual=recognize),
                    prices=PriceCatalog(()),
                    evidence=bootstrap_evidence().write,
                    opportunity=bootstrap_opportunity_admission(),
                    subject_id=born.subject_id,
                    source_kind=VisualSourceKind.CAMERA,
                    source=CameraSourceIdentity("test camera", "test-path", "test-usb"),
                    width=1280,
                    height=720,
                    fps=1,
                    diagnostic=lambda *event: events.append(event),
                )
                sink.bind_capture(
                    AsyncMock(
                        return_value=(
                            VisualFrame(datetime.now(UTC), b"test-jpeg", 1280, 720),
                        )
                    )
                )
                await sink.open_session()
                observations = []
                for interrupted in (False, True):
                    observation = await sink.observe(
                        trigger=ObservationTrigger.MANUAL,
                        frames=(),
                        change_score=None,
                        origin_kind=ObservationOriginKind.CREATOR,
                    )
                    observations.append(observation.observation_id)
                    assert await sink.process_capture_once()
                    if interrupted:
                        with pytest.raises(asyncio.CancelledError):
                            await sink.process_once()
                        # A late receipt may settle the already registered call, without reviving recognition.
                        await calls[-1].capture(
                            usage={"input_tokens": 12, "output_tokens": 2}
                        )
                    else:
                        assert await sink.process_once()
                    assert not await sink.process_once()
                async with factory.unit_of_work(read_only=True) as unit:
                    rows = await (
                        await unit.transaction.execute(
                            "SELECT status,request_artifact_id,response_artifact_id,provider_request_id FROM armi.live_vision_observations WHERE observation_id=ANY(%s) ORDER BY registered_at",
                            (observations,),
                        )
                    ).fetchall()
                    usage = await (
                        await unit.transaction.execute(
                            "SELECT owner,reference_id,business_result FROM armi.provider_usage_calls WHERE reference_kind='visual_observation' ORDER BY receipt->>'started_at'"
                        )
                    ).fetchall()
                    assert await (
                        await unit.transaction.execute(
                            "SELECT to_regclass('armi.visual_recognition_attempts')"
                        )
                    ).fetchone() == (None,)
                assert rows[0][0] == "completed"
                assert rows[0][1] is not None and rows[0][2] is not None
                assert rows[0][3] == "request-1"
                assert rows[1][0] == "unknown" and rows[1][1] is not None
                assert rows[1][2] is None
                assert usage == [
                    ("live-vision", observations[0], "completed"),
                    ("live-vision", observations[1], "unknown"),
                ]
                async with factory.unit_of_work() as unit:
                    snapshots = await (
                        await unit.transaction.execute(
                            "SELECT observation_id,frames FROM armi.live_vision_observations WHERE observation_id=ANY(%s) ORDER BY registered_at",
                            (observations,),
                        )
                    ).fetchall()
                    assert len(snapshots) == 2
                    for observation_id, frames in snapshots:
                        assert len(frames) == 1
                        assert frames[0]["artifact_id"] is not None
                        assert frames[0]["purged_at"] is None
                        frames[0]["purge_after"] = (
                            datetime.now(UTC) - timedelta(seconds=1)
                        ).isoformat()
                        await unit.transaction.execute(
                            "UPDATE armi.live_vision_observations SET frames=%s::jsonb WHERE observation_id=%s",
                            (json.dumps(frames), observation_id),
                        )
                assert await sink.purge_expired_frames() == 2
                assert await sink.purge_expired_frames() == 0
                async with factory.unit_of_work(read_only=True) as unit:
                    purged = await (
                        await unit.transaction.execute(
                            "SELECT frames FROM armi.live_vision_observations WHERE observation_id=ANY(%s)",
                            (observations,),
                        )
                    ).fetchall()
                    assert all(
                        row[0][0]["artifact_id"] is None and row[0][0]["purged_at"]
                        for row in purged
                    )
                assert len(calls) == 2
                assert [event[0] for event in events] == [
                    "prepared",
                    "dispatched",
                    "completed",
                    "prepared",
                    "dispatched",
                    "interrupted",
                ]
            finally:
                await factory.close()

        with tempfile.TemporaryDirectory() as directory:
            asyncio.run(
                exercise(Path(directory)),
                loop_factory=lambda: asyncio.SelectorEventLoop(
                    selectors.SelectSelector()
                ),
            )

    @pytest.mark.test_group("schema", "admin")
    def test_runtime_status_rejects_missing_head_dml_capability(self) -> None:
        fixture = self.create_database()
        self._install_current(
            fixture.migrator_dsn,
            environment_id=fixture.environment_id,
        )
        with psycopg.connect(fixture.provisioner_dsn, autocommit=True) as connection:
            connection.execute(
                "REVOKE INSERT ON TABLE armi.cognitive_attempts FROM armi_runtime"
            )
        with self.assertRaises(DatabaseViolation) as rejected:
            PostgreSQLSchemaGateway().status(
                fixture.runtime_dsn,
                environment_id=fixture.environment_id,
            )
        self.assertEqual(rejected.exception.code, "DB-SCHEMA-CONTRACT")

    @pytest.mark.test_group("schema", "admin")
    def test_table_dml_allows_fixed_operations_without_implying_others(self) -> None:
        fixture = self.create_database()
        self._install_current(
            fixture.migrator_dsn,
            environment_id=fixture.environment_id,
        )
        with psycopg.connect(fixture.runtime_dsn) as connection:
            connection.execute(
                """
                INSERT INTO armi.cognitive_attempts
                SELECT * FROM armi.cognitive_attempts WHERE false
                """
            )
            connection.execute(
                """
                INSERT INTO armi.effect_observations
                SELECT * FROM armi.effect_observations WHERE false
                """
            )
            with self.assertRaises(psycopg.errors.InsufficientPrivilege):
                connection.execute(
                    "UPDATE armi.effect_observations SET reliability=reliability "
                    "WHERE false"
                )
            connection.rollback()
            with self.assertRaises(psycopg.errors.InsufficientPrivilege):
                connection.execute("DELETE FROM armi.cognitive_attempts WHERE false")
            connection.rollback()
        with psycopg.connect(fixture.admin_role_dsn) as connection:
            connection.execute("UPDATE armi.effects SET status=status WHERE false")

    @pytest.mark.test_group("schema", "admin")
    def test_schema_identity_tampering_is_rejected_before_runtime(self) -> None:
        fixture = self.create_database()
        self._install_current(
            fixture.migrator_dsn,
            environment_id=fixture.environment_id,
        )
        with psycopg.connect(fixture.provisioner_dsn, autocommit=True) as connection:
            connection.execute(
                "ALTER TABLE armi.schema_baseline_identity "
                "DROP CONSTRAINT schema_baseline_identity_value_check"
            )
            connection.execute(
                "UPDATE armi.schema_baseline_identity "
                "SET baseline_identity = 'armi.schema-baseline.unsupported'"
            )
        with self.assertRaises(DatabaseViolation) as rejected:
            PostgreSQLSchemaGateway().status(
                fixture.runtime_dsn,
                environment_id=fixture.environment_id,
            )
        self.assertEqual(rejected.exception.code, "DB-SCHEMA-CONTRACT")

    @pytest.mark.creator_system
    def test_creator_system_browser(self) -> None:
        entry_point = Path(os.environ["ARMI_CREATOR_SYSTEM_ENTRY_POINT"])
        creator_resources = Path(os.environ["ARMI_CREATOR_SYSTEM_RESOURCES"])
        chromium = Path(os.environ["ARMI_CREATOR_SYSTEM_CHROMIUM"])
        fixture = self.create_database()

        with tempfile.TemporaryDirectory(dir=Path.cwd() / ".tmp") as temporary:
            environment_root = Path(temporary).resolve()
            data_root = environment_root / "data"
            secrets_root = environment_root / "secrets"
            bootstrap_root = environment_root / "bootstrap"
            for path in (data_root, secrets_root, bootstrap_root):
                path.mkdir()
            runtime_secret = secrets_root / "runtime"
            runtime_secret.write_text(
                fixture.runtime_dsn, encoding="utf-8", newline="\n"
            )
            migrator_secret = secrets_root / "migrator"
            migrator_secret.write_text(
                fixture.migrator_dsn, encoding="utf-8", newline="\n"
            )
            creator_bearer = "creator-v1." + secrets.token_urlsafe(32)
            creator_secret = secrets_root / "creator"
            creator_secret.write_text(creator_bearer, encoding="utf-8", newline="\n")
            identity_secret = _write_data_rights_identity_secret(secrets_root)
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
                listener.bind(("127.0.0.1", 0))
                runtime_port = int(listener.getsockname()[1])
            (environment_root / "environment.yaml").write_text(
                "\n".join(
                    (
                        "environment:",
                        f"  environment_id: {fixture.environment_id}",
                        f'  data_root: "{data_root.as_posix()}"',
                        "creator:",
                        f"  port: {runtime_port}",
                        "secret_locators:",
                        f"  database.runtime: file:{runtime_secret.as_posix()}",
                        f"  database.migrator: file:{migrator_secret.as_posix()}",
                        f"  creator.bearer: file:{creator_secret.as_posix()}",
                        f"  data_rights.identity_token_key: file:{identity_secret.as_posix()}",
                    )
                ),
                encoding="utf-8",
                newline="\n",
            )
            (bootstrap_root / "birth-manifest.json").write_text(
                json.dumps(
                    {
                        "schema_version": "armi.birth-manifest.v1",
                        "environment_id": str(fixture.environment_id),
                        "birth_request_id": str(_uuid7()),
                        "creator_party_id": str(_uuid7()),
                        "idempotency_key": "creator-system-birth",
                        "personality_anchor": {
                            "schema_version": "armi.personality-anchor.v1",
                            "voice_style": "约 16 岁少女口吻",
                            "traits": ["连续", "自主"],
                        },
                    },
                    ensure_ascii=False,
                    separators=(",", ":"),
                    sort_keys=True,
                )
                + "\n",
                encoding="utf-8",
                newline="\n",
            )
            clean_environment = {
                key: value
                for key, value in os.environ.items()
                if not key.startswith("ARMI_")
            }

            admin_binding = _admin_cli_binding(
                environment_root, fixture, creator_resources
            )

            def invoke(*arguments: str) -> dict[str, Any]:
                completed = subprocess.run(
                    (
                        str(entry_point),
                        "-m",
                        "armi_admin.cli",
                        "--config",
                        str(admin_binding),
                        *arguments,
                    ),
                    cwd=Path.cwd(),
                    env=clean_environment,
                    check=False,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=60,
                )
                self.assertEqual(completed.returncode, 0, completed.stderr)
                self.assertNotIn(fixture.runtime_dsn, completed.stdout)
                self.assertNotIn(fixture.migrator_dsn, completed.stdout)
                self.assertNotIn(creator_bearer, completed.stdout)
                from .machine_transport import verify_admin_replay

                receipt = cast(dict[str, Any], json.loads(completed.stdout))
                verify_admin_replay(
                    admin_binding, clean_environment, arguments, receipt
                )
                return cast(dict[str, Any], receipt["result"])

            self.assertEqual(
                invoke("configuration", "--action", "read")["configuration_state"],
                "configured",
            )
            self.assertEqual(
                invoke(
                    "maintenance",
                    "--action",
                    "database_install",
                    "--idempotency-key",
                    "install",
                )["status"],
                "current",
            )
            born = invoke(
                "maintenance", "--action", "birth", "--idempotency-key", "birth"
            )
            self.assertEqual(born["status"], "applied")
            admin_pool = AdminRoleBoundPool(
                fixture.admin_role_dsn, expected_role=fixture.admin_role
            )
            try:
                with admin_pool.serializable() as unit:
                    RuntimeFoundationAdminAdapter(
                        environment_id=str(fixture.environment_id), incarnation=1
                    ).register_environment(
                        unit.transaction,
                        environment_id=str(fixture.environment_id),
                        environment_kind="system_test",
                        incarnation=1,
                        resettable=True,
                        test_controls_enabled=True,
                    )
                    unit.commit()
            finally:
                admin_pool.close()
            identity_query = """
                SELECT subject.subject_id
                FROM armi.subjects AS subject
                WHERE subject.singleton_key = 1
            """
            with psycopg.connect(fixture.runtime_dsn) as database:
                initial_identity = database.execute(identity_query).fetchone()
            self.assertIsNotNone(initial_identity)

            message = "Creator System 唯一输入正文"
            browser_token = ""
            manager = RuntimeProcessManager(
                environment_root, str(fixture.environment_id)
            )
            try:
                self.assertEqual(
                    invoke("start", "--component", "runtime")["status"],
                    "started",
                )
                origin = f"http://127.0.0.1:{runtime_port}"
                with sync_playwright() as playwright:
                    browser = playwright.chromium.launch(
                        executable_path=str(chromium), headless=True
                    )
                    try:
                        page = browser.new_page(viewport={"width": 1280, "height": 800})
                        requests: list[tuple[str, str]] = []
                        page.on(
                            "request",
                            lambda request: requests.append(
                                (request.method, request.url)
                            ),
                        )
                        response = page.goto(
                            f"{origin}/ui/", wait_until="domcontentloaded"
                        )
                        assert response is not None
                        self.assertEqual(response.status, 200)
                        page.locator(".authenticated-view").wait_for()
                        self.assertEqual(
                            page.get_by_role(
                                "button", name="能力授权", exact=True
                            ).count(),
                            0,
                        )
                        page.get_by_role(
                            "button", name="运行与维护", exact=True
                        ).click()
                        codex_status = page.locator("article.component-row").filter(
                            has=page.get_by_role("heading", name="Codex 委托")
                        )
                        codex_status.get_by_text(
                            "已关闭 · 不可用", exact=True
                        ).wait_for()
                        codex_status.get_by_text(
                            "CODEX-DISABLED", exact=False
                        ).wait_for()
                        self.assertFalse(
                            page.evaluate(
                                "document.documentElement.scrollWidth > innerWidth"
                            )
                        )
                        page.screenshot(
                            path=str(
                                Path.cwd()
                                / ".armi-tools"
                                / "codex-runtime-maintenance.png"
                            ),
                            full_page=True,
                        )
                        page.get_by_role("button", name="对话", exact=True).click()
                        with page.expect_response(
                            lambda item: (
                                item.request.method == "POST"
                                and item.url.endswith("/v1/scenes/default/messages")
                            )
                        ) as accepted_response:
                            page.get_by_label("输入内容").fill(message)
                            page.get_by_role("button", name="提交输入").click()
                        accepted = cast(dict[str, Any], accepted_response.value.json())
                        self.assertEqual(accepted_response.value.status, 202)
                        page.get_by_text("消息已发送", exact=True).wait_for()
                        page.get_by_role("button", name="详情", exact=True).click()
                        page.locator("dd:visible").filter(
                            has_text=accepted["result_ref"]
                        ).wait_for()
                        page.wait_for_function(
                            "() => performance.getEntriesByType('resource')"
                            ".filter(item => item.name.includes("
                            "'/v1/scenes/default/timeline')).length >= 2"
                        )
                        browser_token = page.evaluate(
                            "() => JSON.parse(sessionStorage.getItem("
                            "'armi.browser-session.v1')).token"
                        )
                        # Isolated phase injection exercises the real Runtime projection
                        # and page without calling a Provider.
                        with psycopg.connect(fixture.provisioner_dsn) as database:
                            deadline = time.monotonic() + 10
                            while True:
                                row = database.execute(
                                    """UPDATE armi.cognitive_episodes
                                       SET status='finalizing',model_returned_at=statement_timestamp()
                                       WHERE opportunity_id=%s AND status='prepared'
                                       RETURNING cognitive_episode_id""",
                                    (UUID(accepted["result_ref"]),),
                                ).fetchone()
                                database.commit()
                                if row is not None:
                                    break
                                if time.monotonic() >= deadline:
                                    self.fail(
                                        "controlled cognition did not reach prepared"
                                    )
                                time.sleep(0.05)
                        page.reload(wait_until="domcontentloaded")
                        page.locator(".authenticated-view").wait_for()
                        page.get_by_role("button", name="详情", exact=True).click()
                        page.get_by_text(
                            "正在校验并提交认知结果", exact=True
                        ).wait_for()
                        self.assertFalse(
                            page.evaluate(
                                "document.documentElement.scrollWidth > innerWidth"
                            )
                        )
                        screenshot = Path(".tmp/quality/creator-system-finalizing.png")
                        screenshot.parent.mkdir(parents=True, exist_ok=True)
                        page.screenshot(path=str(screenshot), full_page=True)
                        self.assertTrue(
                            any(
                                url.endswith("/v1/scenes/default/events")
                                for _, url in requests
                            )
                        )
                        self.assertTrue(
                            any(
                                "/v1/scenes/default/timeline" in url
                                for _, url in requests
                            )
                        )
                        self.assertFalse(
                            any(not url.startswith(origin) for _, url in requests)
                        )
                        page.close()
                        browser.close()
                        self.assertEqual(
                            invoke("stop", "--component", "runtime")["status"],
                            "stopped",
                        )
                        self.assertEqual(
                            invoke("start", "--component", "runtime")["status"],
                            "started",
                        )
                        browser = playwright.chromium.launch(
                            executable_path=str(chromium), headless=True
                        )
                        page = browser.new_page(viewport={"width": 1280, "height": 800})
                        page.goto(f"{origin}/ui/", wait_until="domcontentloaded")
                        page.locator(".authenticated-view").wait_for()
                        page.get_by_role("button", name="详情", exact=True).click()
                        page.get_by_text(
                            "DEPENDENCY_RUNTIME_INTERRUPTED", exact=True
                        ).wait_for()
                        page.get_by_text(
                            "本轮对话因 Runtime 中断已结束。", exact=False
                        ).wait_for()
                        self.assertEqual(
                            page.get_by_role(
                                "button", name="允许申请范围", exact=True
                            ).count(),
                            0,
                        )
                        screenshot = Path(".tmp/quality/creator-system-interrupted.png")
                        screenshot.parent.mkdir(parents=True, exist_ok=True)
                        page.screenshot(path=str(screenshot), full_page=True)
                        page.get_by_role("button", name="对话", exact=True).click()
                        with page.expect_response(
                            lambda item: (
                                item.request.method == "POST"
                                and item.url.endswith("/v1/scenes/default/messages")
                            )
                        ) as new_response:
                            page.get_by_label("输入内容").fill(
                                "上一轮已结束。现在开始新对话。"
                            )
                            page.get_by_role("button", name="提交输入").click()
                        self.assertEqual(new_response.value.status, 202)
                        self.assertNotEqual(
                            new_response.value.json()["result_ref"],
                            accepted["result_ref"],
                        )
                    finally:
                        browser.close()
                self.assertEqual(
                    invoke("stop", "--component", "runtime")["status"], "stopped"
                )
            finally:
                manager.stop()

            with psycopg.connect(fixture.runtime_dsn) as database:
                final_identity = database.execute(identity_query).fetchone()
                counts = database.execute(
                    """
                    SELECT
                      (SELECT count(*) FROM armi.party_input_interactions),
                      (SELECT count(*) FROM armi.external_evidence),
                      (SELECT count(*) FROM armi.opportunities
                       WHERE evidence_id IS NOT NULL),
                      (SELECT count(*) FROM armi.scene_timeline_items
                       WHERE source_kind = 'creator_input')
                    """
                ).fetchone()
            self.assertEqual(final_identity, initial_identity)
            self.assertEqual(counts, (2, 2, 2, 2))
            log_text = "\n".join(
                path.read_text(encoding="utf-8")
                for path in (data_root / "logs").glob("runtime-*.jsonl")
            )
            self.assertNotIn(fixture.runtime_dsn, log_text)
            self.assertNotIn(fixture.migrator_dsn, log_text)
            self.assertNotIn(creator_bearer, log_text)
            self.assertNotIn(browser_token, log_text)
            self.assertNotIn(message, log_text)

    @pytest.mark.test_group("interaction", "channels", "perception")
    def test_external_messages_share_people_but_separate_conversations(
        self,
    ) -> None:
        fixture = self.create_database()
        self._install_current(
            fixture.migrator_dsn,
            environment_id=fixture.environment_id,
        )
        packaged = packaged_birth_digests()
        anchor = PersonalityAnchor(
            schema_version="armi.personality-anchor.v1",
            voice_style="约 16 岁少女口吻",
            traits=("自主",),
        )
        manifest = BirthManifest(
            schema_version="armi.birth-manifest.v1",
            environment_id=fixture.environment_id,
            birth_request_id=_uuid7(),
            creator_party_id=_uuid7(),
            idempotency_key="qq-group-input-birth",
            personality_anchor=anchor,
            birth_contract_digest=packaged["birth_contract_digest"],
            request_digest=Digest.from_bytes(b"qq-group-input-birth"),
        )

        async def check_recognition_boundaries(factory, interaction_id):
            from dataclasses import replace

            from armi_data_rights.api import DataRightsViolation
            from armi_interaction.api import ExternalMessageViolation
            from armi_kernel.application import ProviderCallReceipt, estimate_cost

            owner = PostgreSQLInteractionPerception()
            fence_owner = bootstrap_data_rights_core().fence
            async with factory.unit_of_work(read_only=True) as unit:
                part_id, request_id, work_id = await (
                    await unit.transaction.execute(
                        "SELECT external_message_part_id,recognition_request_artifact_id,recognition_work_id FROM armi.external_message_parts WHERE interaction_id=%s AND recognition_request_artifact_id IS NOT NULL",
                        (interaction_id,),
                    )
                ).fetchone()

            async def pending(unit):
                await unit.transaction.execute(
                    "UPDATE armi.external_message_parts SET processing_status='pending',settled_at=NULL,interpretation_artifact_id=NULL,interpretation_text=NULL,recognition_response_artifact_id=NULL WHERE external_message_part_id=%s",
                    (part_id,),
                )

            with self.assertRaises(ExternalMessageViolation):
                async with factory.unit_of_work() as unit:
                    await pending(unit)
                    await owner.begin_recognition(
                        unit.transaction,
                        part_id=part_id,
                        request_artifact_id=request_id,
                        work_id=work_id,
                        use_generation=1,
                    )

            with self.assertRaises(DataRightsViolation):
                async with factory.unit_of_work() as unit:
                    await pending(unit)
                    party_id, generation = await owner.recognition_fence(
                        unit.transaction, part_id=part_id
                    )
                    await unit.transaction.execute(
                        "UPDATE armi.parties SET rights_use_generation=rights_use_generation+1 WHERE party_id=%s",
                        (party_id,),
                    )
                    await fence_owner.validate(
                        unit.transaction,
                        DataRightsFence(party_id, 1, generation),
                        require_contact=False,
                        require_use=True,
                    )

            class RollbackFixture(Exception):
                pass

            with self.assertRaises(RollbackFixture):
                async with factory.unit_of_work() as unit:
                    await pending(unit)
                    receipt = ProviderCallReceipt(
                        str(_uuid7()),
                        "test_provider",
                        "test_model",
                        "generation",
                        "external_content_recognition",
                        datetime.now(UTC).isoformat(),
                        None,
                        estimate_cost(
                            quantities=(),
                            required_units=(),
                            snapshot=None,
                            billable=True,
                        ),
                        True,
                    )
                    await owner.record_recognition_call(
                        unit.transaction, part_id=part_id, receipt=receipt
                    )
                    await owner.interrupt_recognition(
                        unit.transaction,
                        interaction_ids=(interaction_id,),
                        error_code="RECOGNITION-RUNTIME-INTERRUPTED",
                    )
                    late = replace(
                        receipt,
                        outcome="returned",
                        received_at=datetime.now(UTC).isoformat(),
                        finished_at=datetime.now(UTC).isoformat(),
                    )
                    await owner.record_recognition_call(
                        unit.transaction, part_id=part_id, receipt=late
                    )
                    with self.assertRaises(ExternalMessageViolation):
                        await owner.record_recognition_call(
                            unit.transaction,
                            part_id=part_id,
                            receipt=replace(receipt, call_id=str(_uuid7())),
                        )
                    row = await (
                        await unit.transaction.execute(
                            "SELECT processing_status,provider_calls->%s->>'outcome' FROM armi.external_message_parts WHERE external_message_part_id=%s",
                            (receipt.call_id, part_id),
                        )
                    ).fetchone()
                    self.assertEqual(row, ("unknown", "returned"))
                    raise RollbackFixture()

        async def exercise(root: Path) -> tuple[Any, ...]:
            factory = PostgreSQLUnitOfWorkFactory(
                fixture.runtime_dsn,
                environment_id=fixture.environment_id,
                pool_min=1,
                pool_max=1,
                acquire_timeout_seconds=2,
                statement_timeout_seconds=5,
                require_runtime_fence=False,
            )
            storage = _publishing_artifact_store(root / "artifacts", factory)
            await factory.open()
            try:
                born = await BirthTransaction(
                    storage,
                    ArtifactCatalogRepository(),
                    _birth_repository(),
                    factory,
                ).birth(manifest)
            finally:
                await factory.close()
            input_factory = PostgreSQLUnitOfWorkFactory(
                fixture.runtime_dsn,
                environment_id=fixture.environment_id,
                pool_min=1,
                pool_max=1,
                acquire_timeout_seconds=2,
                statement_timeout_seconds=5,
                require_runtime_fence=False,
            )
            storage = _publishing_artifact_store(root / "artifacts", input_factory)
            service = ExternalMessageInputService(
                storage=storage,
                catalog=ArtifactCatalogRepository(),
                messages=ExternalMessageInputRepository(
                    bootstrap_evidence().read,
                    bootstrap_opportunity_admission(),
                    _TEST_IDENTITY_TOKENS,
                ),
                creator_inputs=CreatorInputRepository(
                    bootstrap_evidence().write,
                    bootstrap_evidence().read,
                    bootstrap_opportunity_admission(),
                ),
                other_inputs=OtherHumanInputRepository(
                    bootstrap_evidence().write,
                    bootstrap_evidence().read,
                    bootstrap_opportunity_admission(),
                    _TEST_IDENTITY_TOKENS,
                ),
                unit_of_work_factory=input_factory,
                data_rights=bootstrap_data_rights_core().gate,
                subject_id=born.subject_id,
            )
            await input_factory.open()
            await service.open()
            try:
                creator = await service.configure_creator(
                    ConfigureExternalCreatorCommand(
                        ExternalChannel("qq"),
                        ExternalAccountKey("10001"),
                        ExternalPartyKey("90009"),
                        "主人",
                        TraceId("1" * 32),
                    )
                )
                group_message = ObservedExternalMessage(
                    ExternalChannel("qq"),
                    ExternalAccountKey("10001"),
                    ExternalConversationKind.GROUP,
                    ExternalConversationKey("20002"),
                    "开发群",
                    ExternalMessageKey("30003"),
                    ExternalPartyKey("40004"),
                    "小明",
                    (ExternalMessagePart(ExternalMessagePartKind.TEXT, text="大家好"),),
                    Instant(datetime(2026, 8, 10, 12, tzinfo=UTC)),
                    TraceId("2" * 32),
                    addressed_to_subject=True,
                )
                first = await service.accept(group_message)
                repeated = await service.accept(
                    replace(group_message, trace_id=TraceId("3" * 32))
                )
                private = await service.accept(
                    ObservedExternalMessage(
                        ExternalChannel("qq"),
                        ExternalAccountKey("10001"),
                        ExternalConversationKind.DIRECT,
                        ExternalConversationKey("40004"),
                        "小明",
                        ExternalMessageKey("30003"),
                        ExternalPartyKey("40004"),
                        "小明",
                        (
                            ExternalMessagePart(
                                ExternalMessagePartKind.TEXT, text="私聊你好"
                            ),
                        ),
                        Instant(datetime(2026, 8, 10, 13, tzinfo=UTC)),
                        TraceId("4" * 32),
                        addressed_to_subject=True,
                    )
                )
                creator_group = await service.accept(
                    replace(
                        group_message,
                        message_key=ExternalMessageKey("30004"),
                        sender_key=ExternalPartyKey("90009"),
                        sender_display_label="主人",
                        parts=(
                            ExternalMessagePart(
                                ExternalMessagePartKind.TEXT, text="群里你好"
                            ),
                        ),
                        trace_id=TraceId("5" * 32),
                    )
                )
                creator_private = ObservedExternalMessage(
                    ExternalChannel("qq"),
                    ExternalAccountKey("10001"),
                    ExternalConversationKind.DIRECT,
                    ExternalConversationKey("90009"),
                    "主人",
                    ExternalMessageKey("30005"),
                    ExternalPartyKey("90009"),
                    "主人",
                    (
                        ExternalMessagePart(
                            ExternalMessagePartKind.TEXT, text="重复内容"
                        ),
                    ),
                    Instant(datetime(2026, 8, 10, 14, tzinfo=UTC)),
                    TraceId("6" * 32),
                    addressed_to_subject=True,
                )
                creator_private_first = await service.accept(creator_private)
                creator_private_second = await service.accept(
                    replace(
                        creator_private,
                        message_key=ExternalMessageKey("30006"),
                        observed_at=Instant(datetime(2026, 8, 10, 14, 1, tzinfo=UTC)),
                        trace_id=TraceId("7" * 32),
                    )
                )
                media_message = replace(
                    creator_private,
                    message_key=ExternalMessageKey("30007"),
                    parts=(
                        ExternalMessagePart(
                            ExternalMessagePartKind.TEXT, text="这是什么?"
                        ),
                        ExternalMessagePart(
                            ExternalMessagePartKind.IMAGE,
                            locator="image-locator",
                            file_name="sample.png",
                            media_type="image/png",
                            byte_size=32,
                            visual_role=ExternalVisualRole.ORDINARY,
                            source_kind="qq.image.normal",
                            source_summary="普通照片",
                        ),
                    ),
                    observed_at=Instant(datetime(2026, 8, 10, 14, 2, tzinfo=UTC)),
                    trace_id=TraceId("8" * 32),
                )
                media = await service.accept(media_message)
                self.assertIsNone(media.evidence_id)
                pipeline_factory = PostgreSQLUnitOfWorkFactory(
                    fixture.runtime_dsn,
                    environment_id=fixture.environment_id,
                    pool_min=1,
                    pool_max=1,
                    acquire_timeout_seconds=2,
                    statement_timeout_seconds=5,
                    require_runtime_fence=False,
                )
                pipeline = ExternalContentPipeline(
                    prices=PriceCatalog(()),
                    factory=pipeline_factory,
                    storage=storage,
                    catalog=ArtifactCatalogRepository(),
                    work=PostgreSQLDurableWorkGateway(pipeline_factory),
                    evidence=bootstrap_evidence().write,
                    evidence_read=bootstrap_evidence().read,
                    interaction=PostgreSQLInteractionPerception(),
                    data_rights=bootstrap_data_rights_core().fence,
                    opportunity=bootstrap_opportunity_admission(),
                    fetch=_ExternalMediaFetch(),
                    recognizer=_ExternalContentRecognizer(),
                    target_for=lambda _kind: ("test_provider", "test_model"),
                    wakeups=WorkWakeupBus(),
                )
                await pipeline_factory.open()
                await pipeline.open()
                try:
                    self.assertTrue(await pipeline.execute_once())
                    self.assertTrue(await pipeline.execute_once())
                    self.assertFalse(await pipeline.execute_once())
                    await check_recognition_boundaries(
                        input_factory, media.interaction_id.value
                    )
                finally:
                    await pipeline.close()
                    await pipeline_factory.close()
                media_repeated = await service.accept(
                    replace(media_message, trace_id=TraceId("9" * 32))
                )
                silent_group_media = await service.accept(
                    replace(
                        group_message,
                        message_key=ExternalMessageKey("30008"),
                        parts=(
                            ExternalMessagePart(
                                ExternalMessagePartKind.IMAGE,
                                locator="silent-image",
                                visual_role=ExternalVisualRole.UNKNOWN,
                                source_kind="qq.image.unknown",
                            ),
                        ),
                        addressed_to_subject=False,
                        trace_id=TraceId("a" * 32),
                    )
                )
                mixed_group_media = await service.accept(
                    replace(
                        group_message,
                        message_key=ExternalMessageKey("30009"),
                        parts=(
                            ExternalMessagePart(
                                ExternalMessagePartKind.TEXT, text="群聊文字"
                            ),
                            ExternalMessagePart(
                                ExternalMessagePartKind.IMAGE,
                                locator="unaddressed-image",
                                visual_role=ExternalVisualRole.UNKNOWN,
                                source_kind="qq.image.unknown",
                            ),
                        ),
                        addressed_to_subject=False,
                        trace_id=TraceId("b" * 32),
                    )
                )
                return (
                    creator,
                    first,
                    repeated,
                    private,
                    creator_group,
                    creator_private_first,
                    creator_private_second,
                    media,
                    media_repeated,
                    silent_group_media,
                    mixed_group_media,
                )
            finally:
                await service.close()
                await input_factory.close()

        with tempfile.TemporaryDirectory(dir=Path.cwd() / ".tmp") as temporary:
            (
                creator,
                first,
                repeated,
                private,
                creator_group,
                creator_private_first,
                creator_private_second,
                media,
                media_repeated,
                silent_group_media,
                mixed_group_media,
            ) = asyncio.run(
                exercise(Path(temporary).resolve()),
                loop_factory=lambda: asyncio.SelectorEventLoop(
                    selectors.SelectSelector()
                ),
            )
        self.assertTrue(first.newly_accepted)
        self.assertFalse(repeated.newly_accepted)
        self.assertEqual(first.interaction_id, repeated.interaction_id)
        self.assertEqual(first.sender_party_id, private.sender_party_id)
        self.assertNotEqual(
            first.conversation_binding_id, private.conversation_binding_id
        )
        self.assertIsNone(media.evidence_id)
        self.assertFalse(media_repeated.newly_accepted)
        self.assertEqual(media_repeated.interaction_id, media.interaction_id)
        self.assertIsNotNone(media_repeated.evidence_id)
        self.assertIsNotNone(media_repeated.opportunity_id)
        self.assertIsNone(silent_group_media.evidence_id)
        self.assertIsNone(silent_group_media.opportunity_id)
        self.assertIsNotNone(mixed_group_media.evidence_id)
        self.assertIsNotNone(mixed_group_media.opportunity_id)
        self.assertEqual(creator_group.sender_party_id, creator.creator_party_id)
        self.assertEqual(creator_group.sender_party_kind, "creator")
        self.assertNotEqual(creator.scene_id, creator_group.scene_id)
        self.assertTrue(creator_private_first.newly_accepted)
        self.assertTrue(creator_private_second.newly_accepted)
        self.assertNotEqual(
            creator_private_first.interaction_id,
            creator_private_second.interaction_id,
        )
        with psycopg.connect(fixture.runtime_dsn) as connection:
            shape = connection.execute(
                """
                SELECT scene.scene_kind, group_party.party_kind,
                       interaction.external_binding_id,
                       interaction.external_message_key,
                       interaction.addressed_to_subject,
                       interaction.source_party_id,
                       (SELECT count(*) FROM armi.external_channel_bindings
                        WHERE channel_kind = 'qq' AND account_key = '10001')
                FROM armi.interaction_scenes AS scene
                JOIN armi.parties AS group_party
                  ON group_party.party_id = scene.primary_party_id
                JOIN armi.party_input_interactions AS interaction
                  ON interaction.scene_id = scene.scene_id
                 AND interaction.interaction_id = %s
                """,
                (first.interaction_id.value,),
            ).fetchone()
            shared_artifact = connection.execute(
                """
                SELECT count(DISTINCT evidence.artifact_id),
                       count(DISTINCT artifact.artifact_object_id), count(*),
                       min(artifact.logical_kind), min(artifact.privacy_scope)
                FROM armi.external_evidence AS evidence
                JOIN armi.artifacts AS artifact
                  ON artifact.artifact_id = evidence.artifact_id
                WHERE evidence.interaction_id IN (%s, %s)
                """,
                (
                    creator_private_first.interaction_id.value,
                    creator_private_second.interaction_id.value,
                ),
            ).fetchone()
            media_state = connection.execute(
                """
                SELECT input.recognition_status,
                       count(DISTINCT part.external_message_part_id),
                       count(DISTINCT part.external_message_part_id) FILTER (WHERE part.recognition_request_artifact_id IS NOT NULL),
                       count(DISTINCT evidence.evidence_id),
                       count(DISTINCT opportunity.opportunity_id)
                FROM armi.party_input_interactions AS input
                JOIN armi.external_message_parts AS part
                  ON part.interaction_id = input.interaction_id
                LEFT JOIN armi.external_evidence AS evidence
                  ON evidence.interaction_id = input.interaction_id
                LEFT JOIN armi.opportunities AS opportunity
                  ON opportunity.evidence_id = evidence.evidence_id
                WHERE input.interaction_id = %s
                GROUP BY input.recognition_status
                """,
                (media.interaction_id.value,),
            ).fetchone()
            recognition_receipt = connection.execute(
                """SELECT part.recognition_request_artifact_id IS NOT NULL,
                          part.recognition_response_artifact_id IS NOT NULL,
                          usage.owner,usage.receipt->>'provider_request_id',
                          usage.receipt->'raw_usage'->>'input_tokens'
                   FROM armi.external_message_parts part
                   JOIN armi.provider_usage_calls usage ON usage.attempt_id=part.external_message_part_id
                   WHERE part.interaction_id=%s""",
                (media.interaction_id.value,),
            ).fetchall()
            self.assertEqual(
                recognition_receipt, [(True, True, "interaction", "request-1", "10")]
            )
            self.assertEqual(
                connection.execute(
                    "SELECT to_regclass('armi.external_content_recognition_attempts')"
                ).fetchone(),
                (None,),
            )
            visual_state = connection.execute(
                """
                SELECT visual_role, source_kind, source_summary,
                       detected_media_type, pixel_width, pixel_height, frame_count
                FROM armi.external_message_parts
                WHERE interaction_id = %s AND part_kind = 'image'
                """,
                (media.interaction_id.value,),
            ).fetchone()
            group_media_state = connection.execute(
                """
                SELECT input.external_message_key, input.recognition_status,
                       count(evidence.evidence_id),
                       count(work.work_id),
                       min(part.processing_status)
                FROM armi.party_input_interactions AS input
                JOIN armi.external_message_parts AS part
                  ON part.interaction_id = input.interaction_id
                 AND part.part_kind = 'image'
                LEFT JOIN armi.external_evidence AS evidence
                  ON evidence.interaction_id = input.interaction_id
                LEFT JOIN armi.durable_work AS work
                  ON work.owner_ref = input.interaction_id
                 AND work.work_kind = 'external.content.recognize'
                WHERE input.interaction_id IN (%s, %s)
                GROUP BY input.external_message_key, input.recognition_status
                ORDER BY input.external_message_key
                """,
                (
                    silent_group_media.interaction_id.value,
                    mixed_group_media.interaction_id.value,
                ),
            ).fetchall()
        self.assertEqual(
            shape,
            (
                "group_dialogue",
                "social_group",
                first.conversation_binding_id,
                "30003",
                True,
                first.sender_party_id,
                3,
            ),
        )
        self.assertEqual(
            shared_artifact,
            (2, 1, 2, "creator.input.text", "creator_visible"),
        )
        self.assertEqual(media_state, ("succeeded", 2, 1, 1, 1))
        self.assertEqual(
            visual_state,
            (
                "ordinary",
                "qq.image.normal",
                "普通照片",
                "image/png",
                1,
                1,
                1,
            ),
        )
        self.assertEqual(
            group_media_state,
            [
                ("30008", "skipped", 0, 0, "skipped"),
                ("30009", "not_required", 1, 0, "skipped"),
            ],
        )

    @pytest.mark.test_group("schema", "admin")
    def test_baseline_failure_rolls_back_all_tables(self) -> None:
        fixture = self.create_database()
        source = Path(
            "packages/armi-postgresql-contract/src/armi_postgresql_contract/resources/schema"
        )
        with tempfile.TemporaryDirectory(dir=Path.cwd() / ".tmp") as temporary:
            schema_root = Path(temporary) / "schema"
            shutil.copytree(source, schema_root)
            failing_path = schema_root / "baseline/50_activities_and_maintenance.sql"
            failing_path.write_bytes(
                failing_path.read_bytes() + b"\nSELECT armi.module_failure_probe();\n"
            )

            with self.assertRaises(DatabaseViolation) as failed:
                PostgreSQLSchemaGateway(resource_root=schema_root).install(
                    fixture.migrator_dsn,
                    environment_id=fixture.environment_id,
                )
            self.assertEqual(failed.exception.code, "DB-SCHEMA-INSTALL-FAILED")

        with psycopg.connect(fixture.provisioner_dsn) as connection:
            namespace = connection.execute(
                "SELECT pg_catalog.to_regnamespace('armi')"
            ).fetchone()
            tables = connection.execute(
                "SELECT count(*) FROM pg_catalog.pg_tables WHERE schemaname = 'armi'"
            ).fetchone()
        self.assertEqual(namespace, ("armi",))
        self.assertEqual(tables, (0,))

    @pytest.mark.test_group("schema", "admin")
    def test_missing_and_unknown_alembic_revisions_are_rejected(self) -> None:
        missing_fixture = self.create_database()
        gateway = PostgreSQLSchemaGateway()
        gateway.install(
            missing_fixture.migrator_dsn,
            environment_id=missing_fixture.environment_id,
        )
        with psycopg.connect(
            missing_fixture.provisioner_dsn, autocommit=True
        ) as connection:
            connection.execute("DROP TABLE armi.alembic_version")
        with self.assertRaises(DatabaseViolation) as missing:
            gateway.status(
                missing_fixture.runtime_dsn,
                environment_id=missing_fixture.environment_id,
            )
        self.assertEqual(missing.exception.code, "DB-SCHEMA-MISSING")

        unknown_fixture = self.create_database()
        gateway.install(
            unknown_fixture.migrator_dsn,
            environment_id=unknown_fixture.environment_id,
        )
        with psycopg.connect(
            unknown_fixture.provisioner_dsn, autocommit=True
        ) as connection:
            connection.execute(
                "UPDATE armi.alembic_version SET version_num = 'unknown'"
            )
        with self.assertRaises(DatabaseViolation) as unknown:
            gateway.status(
                unknown_fixture.runtime_dsn,
                environment_id=unknown_fixture.environment_id,
            )
        self.assertEqual(unknown.exception.code, "DB-SCHEMA-CONTRACT")

    @pytest.mark.test_group("context", "memory")
    def test_scalable_semantic_recall_executes_dense_and_lexical_paths(self) -> None:
        fixture = self.create_database()
        self._install_current(
            fixture.migrator_dsn,
            environment_id=fixture.environment_id,
        )
        subject_id = _uuid7()
        memory_id = _uuid7()
        vector = "[1," + ",".join("0" for _ in range(1023)) + "]"
        with psycopg.connect(fixture.provisioner_dsn, autocommit=True) as connection:
            connection.execute("SET session_replication_role = replica")
            connection.execute(
                """INSERT INTO armi.context_embedding_projections (
                     context_embedding_projection_id,
                     subject_id,source_kind,source_ref,
                     source_version,chunk_ordinal,chunk_text,retrieval_text,
                     model_binding,embedding)
                   VALUES (%s,%s,'subjective_memory',%s,1,0,%s,%s,%s,
                           %s::armi_extensions.vector)""",
                (
                    _uuid7(),
                    subject_id,
                    memory_id,
                    "记得给编号 A-204 的蓝色设备做保养",
                    "Memory: 记得给编号 A-204 的蓝色设备做保养",
                    EMBEDDING_BINDING_ID,
                    vector,
                ),
            )
            connection.execute(
                """UPDATE armi.context_embedding_coverage
                   SET coverage_state='complete'
                   WHERE model_binding=%s""",
                (EMBEDDING_BINDING_ID,),
            )
            connection.execute("SET enable_seqscan = off")
            dense_plan = "\n".join(
                row[0]
                for row in connection.execute(
                    """EXPLAIN SELECT context_embedding_projection_id
                       FROM armi.context_embedding_projections
                       ORDER BY embedding::armi_extensions.halfvec(1024)
                         OPERATOR(armi_extensions.<=>)
                         %s::armi_extensions.halfvec(1024)
                       LIMIT 256""",
                    (vector,),
                ).fetchall()
            )
            lexical_plan = "\n".join(
                row[0]
                for row in connection.execute(
                    """EXPLAIN SELECT context_embedding_projection_id
                       FROM armi.context_embedding_projections
                       ORDER BY %s OPERATOR(armi_extensions.<<->) retrieval_text
                       LIMIT 128""",
                    ("A-204 蓝色设备",),
                ).fetchall()
            )
            dense_result = connection.execute(
                """SELECT source_ref,
                          1-(embedding OPERATOR(armi_extensions.<=>)
                             %s::armi_extensions.vector(1024)) AS score
                   FROM armi.context_embedding_projections
                   WHERE subject_id=%s
                     AND model_binding=%s
                   ORDER BY embedding::armi_extensions.halfvec(1024)
                     OPERATOR(armi_extensions.<=>)
                     %s::armi_extensions.halfvec(1024)
                   LIMIT 256""",
                (
                    vector,
                    subject_id,
                    EMBEDDING_BINDING_ID,
                    vector,
                ),
            ).fetchone()
            lexical_result = connection.execute(
                """SELECT source_ref,
                          armi_extensions.word_similarity(%s,retrieval_text)
                   FROM armi.context_embedding_projections
                   WHERE subject_id=%s
                     AND model_binding=%s
                   ORDER BY %s OPERATOR(armi_extensions.<<->) retrieval_text
                   LIMIT 128""",
                (
                    "A-204 蓝色设备",
                    subject_id,
                    EMBEDDING_BINDING_ID,
                    "A-204 蓝色设备",
                ),
            ).fetchone()
            connection.execute("SET session_replication_role = origin")
        self.assertIn("context_embedding_projections_embedding_hnsw_idx", dense_plan)
        self.assertIn("context_embedding_projections_retrieval_gist_idx", lexical_plan)
        self.assertEqual(cast(tuple[Any, ...], dense_result)[0], memory_id)
        self.assertGreater(float(cast(tuple[Any, ...], dense_result)[1]), 0.99)
        self.assertEqual(cast(tuple[Any, ...], lexical_result)[0], memory_id)
        self.assertGreater(float(cast(tuple[Any, ...], lexical_result)[1]), 0.3)

    @pytest.mark.test_group("schema", "admin")
    def test_noncurrent_revision_requires_database_reinstall(self) -> None:
        fixture = self.create_database()
        PostgreSQLSchemaGateway().install(
            fixture.migrator_dsn,
            environment_id=fixture.environment_id,
        )
        with psycopg.connect(fixture.provisioner_dsn, autocommit=True) as connection:
            connection.execute(
                "UPDATE armi.alembic_version SET version_num = 'unsupported'"
            )
        with self.assertRaises(DatabaseViolation) as rejected:
            PostgreSQLSchemaGateway().status(
                fixture.runtime_dsn,
                environment_id=fixture.environment_id,
            )
        self.assertEqual(rejected.exception.code, "DB-SCHEMA-CONTRACT")

    @pytest.mark.test_group("attention", "runtime")
    def test_subject_source_is_single_under_concurrency_and_restart(
        self,
    ) -> None:
        fixture = self.create_database()
        self._install_current(
            fixture.migrator_dsn,
            environment_id=fixture.environment_id,
        )
        packaged = packaged_birth_digests()
        anchor = PersonalityAnchor(
            schema_version="armi.personality-anchor.v1",
            voice_style="约 16 岁少女口吻",
            traits=("自主",),
        )
        manifest = BirthManifest(
            schema_version="armi.birth-manifest.v1",
            environment_id=fixture.environment_id,
            birth_request_id=_uuid7(),
            creator_party_id=_uuid7(),
            idempotency_key="p0-s001-life-source-birth",
            personality_anchor=anchor,
            birth_contract_digest=packaged["birth_contract_digest"],
            request_digest=Digest.from_bytes(b"p0-s001-life-source-birth"),
        )

        async def exercise(
            root: Path,
        ) -> tuple[
            OpportunityAdmissionOutcome,
            OpportunityAdmissionOutcome,
            OpportunityAdmissionOutcome,
            OpportunityAdmissionOutcome,
            OpportunityAdmissionOutcome,
        ]:
            birth_factory = PostgreSQLUnitOfWorkFactory(
                fixture.runtime_dsn,
                environment_id=fixture.environment_id,
                pool_min=1,
                pool_max=1,
                acquire_timeout_seconds=2,
                statement_timeout_seconds=5,
                require_runtime_fence=False,
            )
            await birth_factory.open()
            try:
                born = await BirthTransaction(
                    _publishing_artifact_store(root, birth_factory),
                    ArtifactCatalogRepository(),
                    _birth_repository(),
                    birth_factory,
                ).birth(manifest)
            finally:
                await birth_factory.close()

            authority = PostgreSQLRuntimeAuthority(
                fixture.runtime_dsn,
                environment_id=fixture.environment_id,
                pool_timeout_seconds=2,
                statement_timeout_seconds=5,
            )
            await authority.open()
            record = await authority.acquire(
                runtime_instance_id=RuntimeInstanceId(_uuid7()),
                lease_seconds=30,
            )
            factories = tuple(
                PostgreSQLUnitOfWorkFactory(
                    fixture.runtime_dsn,
                    environment_id=fixture.environment_id,
                    pool_min=1,
                    pool_max=1,
                    acquire_timeout_seconds=2,
                    statement_timeout_seconds=5,
                    authority_admission=lambda: record.fence,
                    require_runtime_fence=True,
                )
                for _ in range(2)
            )
            relationship_module = bootstrap_relationship(
                factories[0],
                subject_id=born.subject_id,
                creator_party_id=manifest.creator_party_id,
                environment_id=fixture.environment_id,
                cursor_key=hashlib.sha256(b"creator-projection-cursor").digest(),
                visibility=bootstrap_data_rights_core().visibility,
            )
            await relationship_module.open()
            activity_module = bootstrap_activity(
                factories[0],
                subject_id=record.fence.subject_id,
                creator_party_id=manifest.creator_party_id,
                environment_id=fixture.environment_id,
                cursor_key=hashlib.sha256(b"creator-projection-cursor").digest(),
                focus=bootstrap_subject_state().read,
            )
            await activity_module.open()
            material_module = bootstrap_material(
                factories[0],
                catalog=ArtifactCatalogRepository(),
                subject_id=record.fence.subject_id,
                data_root=root,
                max_object_bytes=1024 * 1024,
            )
            await material_module.open()
            sleep_module = bootstrap_sleep(
                factories[0],
                decisions=bootstrap_sleep_decision_record(),
                subject_id=record.fence.subject_id,
                creator_party_id=manifest.creator_party_id,
                environment_id=fixture.environment_id,
                cursor_key=hashlib.sha256(b"creator-projection-cursor").digest(),
                runtime_facts=RuntimeSleepFacts(
                    cognition=bootstrap_cognition_operation(),
                    effects=bootstrap_effect_operation_read(),
                ),
                opportunities=bootstrap_opportunity_sleep(),
            )
            await sleep_module.open()
            pipelines = tuple(
                bootstrap_opportunity(
                    factory=factory,
                    facts=_life_opportunity_facts(
                        factory,
                        environment_id=fixture.environment_id,
                        activity_read=activity_module.read,
                    ),
                    activity_read=activity_module.read,
                    sleep_maintenance=sleep_module.maintenance,
                    sleep_read=sleep_module.read,
                    subject_state_read=bootstrap_subject_state().read,
                    maintenance_consideration_seconds=1,
                    maintenance_deadline_seconds=120,
                )
                for factory in factories
            )
            for factory in factories:
                await factory.open()
            for pipeline in pipelines:
                await pipeline.open()
            try:
                initial = await pipelines[0].admit_once()
                self.assertEqual(initial.reason_code, "LIFE-AUTONOMY-NOT-DUE")
                async with factories[0].unit_of_work() as uow:
                    await uow.transaction.execute(
                        "UPDATE armi.autonomy_plans SET next_consideration_at=statement_timestamp()-interval '1 second'"
                    )
                first, second = await asyncio.gather(
                    pipelines[0].admit_once(),
                    pipelines[1].admit_once(),
                )
                restarted = await pipelines[0].admit_once()
                previous_id = restarted.opportunity_id
                for number, reason in enumerate(
                    (
                        "REC-COGNITION-INTERRUPTED",
                        "REC-OPPORTUNITY-COGNITION-CANCELLED",
                    ),
                    start=1,
                ):
                    async with factories[0].unit_of_work() as uow:
                        await uow.transaction.execute(
                            """UPDATE armi.opportunities
                               SET current_disposition='cancelled',
                                   resolved_at=statement_timestamp(), resolution_reason_code=%s
                               WHERE opportunity_id=%s""",
                            (reason, previous_id),
                        )
                    replan = await pipelines[0].admit_once()
                    self.assertEqual(
                        replan.reason_code, "LIFE-AUTONOMY-RECONSIDERATION-SCHEDULED"
                    )
                    async with factories[0].unit_of_work() as uow:
                        await uow.transaction.execute(
                            "UPDATE armi.autonomy_plans SET next_consideration_at=statement_timestamp()-interval '1 second', last_check_started_at=statement_timestamp()-interval '61 seconds'"
                        )
                    fresh, concurrent = await asyncio.gather(
                        pipelines[0].admit_once(),
                        pipelines[1].admit_once(),
                    )
                    self.assertEqual(
                        {fresh.status, concurrent.status},
                        {
                            OpportunityAdmissionStatus.ADMITTED,
                            OpportunityAdmissionStatus.DUPLICATE,
                        },
                    )
                    self.assertEqual(fresh.opportunity_id, concurrent.opportunity_id)
                    self.assertNotEqual(fresh.opportunity_id, previous_id)
                    async with factories[0].unit_of_work(read_only=True) as uow:
                        rows = await (
                            await uow.transaction.execute(
                                """SELECT opportunity_id,current_disposition,resolution_reason_code,
                                      predecessor_opportunity_id,source_version
                               FROM armi.opportunities WHERE source_kind='autonomy_plan'
                               ORDER BY source_version"""
                            )
                        ).fetchall()
                        self.assertEqual(
                            rows[-2][0:3], (previous_id, "cancelled", reason)
                        )
                        self.assertEqual(
                            rows[-1],
                            (fresh.opportunity_id, "open", None, None, number + 1),
                        )
                        # New admission carries no old episode or frozen Context.
                        count = await (
                            await uow.transaction.execute(
                                "SELECT count(*) FROM armi.cognitive_episodes WHERE opportunity_id=%s",
                                (fresh.opportunity_id,),
                            )
                        ).fetchone()
                        self.assertEqual(count, (0,))
                    previous_id = fresh.opportunity_id
                assert previous_id is not None
                async with factories[0].unit_of_work() as uow:
                    self.assertTrue(
                        await bootstrap_opportunity_cognition().select_for_cognition(
                            uow.transaction,
                            opportunity_id=previous_id,
                        )
                    )
                    await bootstrap_opportunity_cognition().interrupt_cognition(
                        uow.transaction,
                        opportunity_ids=(previous_id,),
                    )
                settled = await pipelines[0].admit_once()
                self.assertEqual(
                    settled.reason_code, "LIFE-AUTONOMY-RECONSIDERATION-SCHEDULED"
                )
                attention = await pipelines[0].admit_once()
                await asyncio.sleep(1)
                sleep_window = await pipelines[0].maintain_sleep_once()
            finally:
                for pipeline in pipelines:
                    await pipeline.close()
                for factory in factories:
                    await factory.close()
                await activity_module.close()
                await material_module.close()
                await relationship_module.close()
                await sleep_module.close()
                await authority.release(record.fence)
                await authority.close()
            return first, second, restarted, attention, sleep_window

        with tempfile.TemporaryDirectory(dir=Path.cwd() / ".tmp") as temporary:
            first, second, restarted, attention, sleep_window = asyncio.run(
                exercise(Path(temporary).resolve()),
                loop_factory=lambda: asyncio.SelectorEventLoop(
                    selectors.SelectSelector()
                ),
            )
        self.assertEqual(
            {first.status, second.status},
            {
                OpportunityAdmissionStatus.ADMITTED,
                OpportunityAdmissionStatus.DUPLICATE,
            },
        )
        self.assertEqual(first.opportunity_id, second.opportunity_id)
        self.assertEqual(restarted.status, OpportunityAdmissionStatus.DUPLICATE)
        self.assertEqual(restarted.opportunity_id, first.opportunity_id)
        self.assertEqual(attention.status, OpportunityAdmissionStatus.REJECTED)
        self.assertEqual(attention.reason_code, "LIFE-AUTONOMY-NOT-DUE")
        self.assertEqual(sleep_window.status, OpportunityAdmissionStatus.ADMITTED)
        self.assertIsNotNone(sleep_window.opportunity_id)
        with psycopg.connect(fixture.provisioner_dsn) as connection:
            row = connection.execute(
                """
                SELECT count(*), count(DISTINCT root_opportunity_id),
                       count(DISTINCT source_ref),
                       min(source_version), max(source_version)
                FROM armi.opportunities
                WHERE source_kind = 'autonomy_plan'
                """
            ).fetchone()
        self.assertIsNotNone(row)
        assert row is not None
        self.assertEqual(row, (3, 3, 1, 1, 3))

    @pytest.mark.test_group("runtime", "creator", "admin")
    def test_creator_read_queries_and_maintenance_share_runtime_state(
        self,
    ) -> None:
        fixture = self.create_database()
        self._install_current(
            fixture.migrator_dsn,
            environment_id=fixture.environment_id,
        )
        creator_party_id = _uuid7()
        packaged = packaged_birth_digests()
        anchor = PersonalityAnchor(
            schema_version="armi.personality-anchor.v1",
            voice_style="约 16 岁少女口吻",
            traits=("自主",),
        )
        manifest = BirthManifest(
            schema_version="armi.birth-manifest.v1",
            environment_id=fixture.environment_id,
            birth_request_id=_uuid7(),
            creator_party_id=creator_party_id,
            idempotency_key="p0-s003-creator-activity-query",
            personality_anchor=anchor,
            birth_contract_digest=packaged["birth_contract_digest"],
            request_digest=Digest.from_bytes(b"p0-s003-creator-activity-query"),
        )

        async def exercise(root: Path) -> None:
            birth_factory = PostgreSQLUnitOfWorkFactory(
                fixture.runtime_dsn,
                environment_id=fixture.environment_id,
                pool_min=1,
                pool_max=1,
                acquire_timeout_seconds=2,
                statement_timeout_seconds=5,
                require_runtime_fence=False,
            )
            await birth_factory.open()
            try:
                born = await BirthTransaction(
                    _publishing_artifact_store(root, birth_factory),
                    ArtifactCatalogRepository(),
                    _birth_repository(),
                    birth_factory,
                ).birth(manifest)
            finally:
                await birth_factory.close()

            factory = PostgreSQLUnitOfWorkFactory(
                fixture.runtime_dsn,
                environment_id=fixture.environment_id,
                pool_min=1,
                pool_max=1,
                acquire_timeout_seconds=2,
                statement_timeout_seconds=5,
                require_runtime_fence=False,
            )

            relationship_module = bootstrap_relationship(
                factory,
                subject_id=born.subject_id,
                creator_party_id=creator_party_id,
                environment_id=fixture.environment_id,
                cursor_key=hashlib.sha256(b"creator-projection-cursor").digest(),
                visibility=bootstrap_data_rights_core().visibility,
            )
            memory_module = bootstrap_memory(
                factory,
                environment_id=fixture.environment_id,
                creator_party_id=creator_party_id,
                subject_id=born.subject_id,
                cursor_key=hashlib.sha256(b"p0-s022-life-record-cursor-key").digest(),
                visibility=bootstrap_data_rights_core().visibility,
            )
            activity_module = bootstrap_activity(
                factory,
                subject_id=born.subject_id,
                creator_party_id=creator_party_id,
                environment_id=fixture.environment_id,
                cursor_key=hashlib.sha256(b"creator-projection-cursor").digest(),
                focus=bootstrap_subject_state().read,
            )
            await factory.open()
            material_module = bootstrap_material(
                factory,
                catalog=ArtifactCatalogRepository(),
                subject_id=born.subject_id,
                data_root=root,
                max_object_bytes=1024 * 1024,
            )
            await relationship_module.open()
            await memory_module.open()
            await activity_module.open()
            await material_module.open()
            life_records = PostgreSQLLifeRecordQuery(
                factory,
                environment_id=fixture.environment_id,
                creator_party_id=creator_party_id,
                subject_id=born.subject_id,
                cursor_key=hashlib.sha256(b"p0-s022-life-record-cursor-key").digest(),
                activities=activity_module.read,
                materials=material_module.read,
                memories=memory_module.read,
                relationships=relationship_module.read,
                subject_state=bootstrap_subject_state().read,
                visibility=bootstrap_data_rights_core().visibility,
                experiences=bootstrap_experience_owner(),
            )
            await life_records.open()
            try:
                page = await life_records.query(
                    LifeRecordQuery(
                        actor=LifeRecordActor.CREATOR,
                        retrieval_kind=LifeRecordRetrievalKind.CREATOR_VIEW,
                        limit=50,
                    )
                )
                self.assertTrue(
                    any(
                        item.record_kind == LifeRecordKind("self_change")
                        for item in page.items
                    )
                )
            finally:
                await life_records.close()
                await memory_module.close()
                await material_module.close()
                await relationship_module.close()

            try:
                page = await activity_module.read.list_current(limit=50)
                self.assertEqual(page.items, ())
                self.assertIsNone(page.next_cursor)
                with self.assertRaisesRegex(
                    ActivityViolation,
                    "ACTIVITY-QUERY-NOT-FOUND",
                ):
                    await activity_module.read.timeline(_uuid7(), limit=50)
            finally:
                await activity_module.close()
                await factory.close()

            session_id, revision_id = _uuid7(), _uuid7()
            with psycopg.connect(fixture.provisioner_dsn) as connection:
                scope = connection.execute(
                    """
                    SELECT subject.subject_id, subject.subject_version, subject.state_epoch,
                           subject.born_at
                    FROM armi.subjects AS subject
                    WHERE subject.singleton_key = 1
                    """
                ).fetchone()
                assert scope is not None
                connection.execute(
                    """
                    INSERT INTO armi.maintenance_sessions (
                        maintenance_session_id, subject_id,
                        origin_opportunity_id, cycle_anchor_kind,
                        cycle_anchor_ref, consideration_at, deadline_at,
                        trigger_kind, sleep_episode_id,
                        started_subject_version, started_state_epoch,
                        current_revision_id, head_version
                    ) VALUES (
                        %s, %s, NULL, 'subject_birth', %s,
                        %s + interval '16 hours', %s + interval '24 hours',
                        'system_deadline', NULL, %s, %s, %s, 1
                    )
                    """,
                    (
                        session_id,
                        scope[0],
                        scope[0],
                        scope[3],
                        scope[3],
                        scope[1],
                        scope[2],
                        revision_id,
                    ),
                )

            authority = PostgreSQLRuntimeAuthority(
                fixture.runtime_dsn,
                environment_id=fixture.environment_id,
                pool_timeout_seconds=2,
                statement_timeout_seconds=5,
            )
            await authority.open()
            record = await authority.acquire(
                runtime_instance_id=RuntimeInstanceId(_uuid7()),
                lease_seconds=30,
            )
            maintenance_factory = PostgreSQLUnitOfWorkFactory(
                fixture.runtime_dsn,
                environment_id=fixture.environment_id,
                pool_min=1,
                pool_max=1,
                acquire_timeout_seconds=2,
                statement_timeout_seconds=5,
                authority_admission=lambda: record.fence,
                require_runtime_fence=True,
            )
            relationship_module = bootstrap_relationship(
                maintenance_factory,
                subject_id=scope[0],
                creator_party_id=creator_party_id,
                environment_id=fixture.environment_id,
                cursor_key=hashlib.sha256(b"creator-projection-cursor").digest(),
                visibility=bootstrap_data_rights_core().visibility,
            )
            await relationship_module.open()
            activity_module = bootstrap_activity(
                maintenance_factory,
                subject_id=record.fence.subject_id,
                creator_party_id=creator_party_id,
                environment_id=fixture.environment_id,
                cursor_key=hashlib.sha256(b"creator-projection-cursor").digest(),
                focus=bootstrap_subject_state().read,
            )
            await activity_module.open()
            material_module = bootstrap_material(
                maintenance_factory,
                catalog=ArtifactCatalogRepository(),
                subject_id=record.fence.subject_id,
                data_root=root,
                max_object_bytes=1024 * 1024,
            )
            await material_module.open()
            sleep_module = bootstrap_sleep(
                maintenance_factory,
                decisions=bootstrap_sleep_decision_record(),
                subject_id=record.fence.subject_id,
                creator_party_id=creator_party_id,
                environment_id=fixture.environment_id,
                cursor_key=hashlib.sha256(b"creator-projection-cursor").digest(),
                runtime_facts=RuntimeSleepFacts(
                    cognition=bootstrap_cognition_operation(),
                    effects=bootstrap_effect_operation_read(),
                ),
                opportunities=bootstrap_opportunity_sleep(),
            )
            await sleep_module.open()
            pipeline = bootstrap_opportunity(
                factory=maintenance_factory,
                facts=_life_opportunity_facts(
                    maintenance_factory,
                    environment_id=fixture.environment_id,
                    activity_read=activity_module.read,
                ),
                activity_read=activity_module.read,
                sleep_maintenance=sleep_module.maintenance,
                sleep_read=sleep_module.read,
                subject_state_read=bootstrap_subject_state().read,
            )
            await maintenance_factory.open()
            await pipeline.open()
            try:
                outcome = await pipeline.maintain_sleep_once()
            finally:
                await pipeline.close()
                await authority.release(record.fence)
                await authority.close()
            self.assertEqual(outcome.reason_code, "LIFE-MAINTENANCE-ADVANCED")

            try:
                status = await sleep_module.read.status()
                assert status.session is not None
                self.assertEqual(status.session.session_id, session_id)
                self.assertEqual(status.session.phase.value, "memory_maintenance")
                self.assertEqual(status.waiting_input_count, 0)
                timeline = await sleep_module.read.timeline(session_id, limit=50)
                self.assertEqual(timeline.items, ())
                self.assertIsNone(timeline.next_cursor)
                with self.assertRaisesRegex(
                    CreatorMaintenanceViolation,
                    "MAINTENANCE-QUERY-NOT-FOUND",
                ):
                    await sleep_module.read.timeline(_uuid7(), limit=50)
            finally:
                await sleep_module.close()
                await activity_module.close()
                await material_module.close()
                await relationship_module.close()
                await maintenance_factory.close()

        with tempfile.TemporaryDirectory(dir=Path.cwd() / ".tmp") as temporary:
            asyncio.run(
                exercise(Path(temporary).resolve()),
                loop_factory=lambda: asyncio.SelectorEventLoop(
                    selectors.SelectSelector()
                ),
            )

    @pytest.mark.test_group("codex", "interaction")
    def test_creator_codex_task_intake_is_atomic_and_idempotent(self) -> None:
        fixture = self.create_database()
        self._install_current(
            fixture.migrator_dsn,
            environment_id=fixture.environment_id,
        )
        creator_party_id = _uuid7()
        packaged = packaged_birth_digests()
        anchor = PersonalityAnchor(
            schema_version="armi.personality-anchor.v1",
            voice_style="约 16 岁少女口吻",
            traits=("审慎",),
        )
        manifest = BirthManifest(
            schema_version="armi.birth-manifest.v1",
            environment_id=fixture.environment_id,
            birth_request_id=_uuid7(),
            creator_party_id=creator_party_id,
            idempotency_key="s039-creator-codex-intake-birth",
            personality_anchor=anchor,
            birth_contract_digest=packaged["birth_contract_digest"],
            request_digest=Digest.from_bytes(b"s039-creator-codex-intake-birth"),
        )

        async def exercise(
            root: Path,
        ) -> tuple[
            CreatorInputAcceptance,
            CreatorInputAcceptance,
            CreatorCodexTaskCommand,
        ]:
            factory = PostgreSQLUnitOfWorkFactory(
                fixture.runtime_dsn,
                environment_id=fixture.environment_id,
                pool_min=1,
                pool_max=1,
                acquire_timeout_seconds=2,
                statement_timeout_seconds=5,
                require_runtime_fence=False,
            )
            storage = _publishing_artifact_store(root, factory)
            custody = PostgreSQLExecutionCustody(
                fixture.runtime_dsn,
                environment_id=fixture.environment_id,
                pool_max=1,
                pool_timeout_seconds=2,
            )
            await factory.open()
            await custody.open()
            await storage.prepare()
            try:
                await BirthTransaction(
                    storage,
                    ArtifactCatalogRepository(),
                    _birth_repository(),
                    factory,
                ).birth(manifest)
                data_rights = bootstrap_data_rights_core()
                codex_reason: str | None = None
                gateway = CodexTaskSourceGateway(
                    factory,
                    unavailable_reason=lambda: codex_reason,
                    storage=storage,
                    catalog=ArtifactCatalogRepository(),
                    creator_party_id=creator_party_id,
                    input_repository=CreatorInputRepository(
                        bootstrap_evidence().write,
                        bootstrap_evidence().read,
                        bootstrap_opportunity_admission(),
                    ),
                    evidence=bootstrap_evidence().write,
                    evidence_read=bootstrap_evidence().read,
                    identity=bootstrap_interaction_identity(_TEST_IDENTITY_TOKENS),
                    opportunity=bootstrap_opportunity_admission(),
                    effect=bootstrap_effect_codex_lifecycle(),
                    expression=bootstrap_expression_action_ports(
                        bootstrap_effect_intent_read(),
                        bootstrap_dialogue_decision_record(),
                    ).intents,
                    sources=bootstrap_codex_read_ports().task_sources,
                    custody=custody,
                    data_rights=data_rights.gate,
                    data_rights_fence=data_rights.fence,
                    notifier=None,
                    diagnostic=lambda _event: None,
                )
                command = CreatorCodexTaskCommand(
                    "default",
                    "生成一份经验证的交付说明。",
                    IdempotencyKey("s039-creator-codex-task"),
                    TraceId("6" * 32),
                    delegate_id=_uuid7(),
                )
                first = await gateway.accept(command)
                repeated = await gateway.accept(command)
                self.assertEqual(first, repeated)
                codex_reason = "CODEX-DISABLED"
                self.assertEqual(await gateway.accept(command), repeated)
                with self.assertRaisesRegex(RuntimeError, "CODEX-DISABLED"):
                    await gateway.accept(
                        CreatorCodexTaskCommand(
                            "default",
                            "关闭时不得创建等待批准的新任务。",
                            IdempotencyKey("codex-disabled-new-key"),
                            TraceId("8" * 32),
                        )
                    )
                codex_reason = None
                timeline_query = PostgreSQLSceneTimelineQuery(
                    factory,
                    environment_id=fixture.environment_id,
                    creator_party_id=creator_party_id,
                    cursor_key=b"c" * 32,
                    storage=storage,
                    codex_tasks=bootstrap_codex_timeline_projection(),
                    visibility=bootstrap_data_rights_core().visibility,
                    projections=CreatorTimelineProjectionAssembler(
                        evidence=bootstrap_evidence().read,
                        opportunity_admission=bootstrap_opportunity_admission(),
                        opportunity_read=bootstrap_opportunity_cognition(),
                        cognition=bootstrap_cognition_operation(),
                        catalog=ArtifactCatalogRepository(),
                        codex=bootstrap_codex_read_ports().task_sources,
                    ),
                    voice_responses=bootstrap_live_voice_context_read(),
                )
                await timeline_query.open()
                try:
                    timeline = await timeline_query.query(
                        SceneTimelineQuery(SceneKey("default"), 10)
                    )
                finally:
                    await timeline_query.close()
                self.assertEqual(len(timeline.items), 1)
                self.assertEqual(timeline.items[0].source_kind, "creator_input")
                self.assertEqual(
                    timeline.items[0].operation_ref,
                    first.opportunity_id.value,
                )
                self.assertEqual(timeline.items[0].message, command.objective)
                with self.assertRaisesRegex(RuntimeError, "CODEX-TASK-IDEMPOTENCY"):
                    await gateway.accept(
                        CreatorCodexTaskCommand(
                            "default",
                            "同一身份下的冲突目标。",
                            command.idempotency_key,
                            TraceId("7" * 32),
                        )
                    )
                return first, repeated, command
            finally:
                await custody.close()
                await factory.close()

        with tempfile.TemporaryDirectory(dir=Path.cwd() / ".tmp") as temporary:
            first, repeated, command = asyncio.run(
                exercise(Path(temporary).resolve()),
                loop_factory=lambda: asyncio.SelectorEventLoop(
                    selectors.SelectSelector()
                ),
            )
        self.assertTrue(first.newly_accepted)
        self.assertFalse(repeated.newly_accepted)
        self.assertEqual(first.opportunity_id, repeated.opportunity_id)
        with psycopg.connect(fixture.provisioner_dsn) as connection:
            counts = connection.execute(
                """
                SELECT
                    (SELECT count(*) FROM armi.party_input_interactions
                     WHERE purpose='codex_task_request'),
                    (SELECT count(*) FROM armi.codex_task_sources),
                    (SELECT count(*) FROM armi.external_evidence
                     WHERE source_kind='codex_task_source'
                       AND interaction_id IS NULL),
                    (SELECT count(*) FROM armi.opportunities
                     WHERE purpose='consider_codex_task'),
                    (SELECT count(*) FROM armi.scene_timeline_items
                     WHERE source_kind='creator_input')
                """
            ).fetchone()
        self.assertEqual(counts, (1, 1, 1, 1, 1))
        with psycopg.connect(fixture.provisioner_dsn) as connection:
            provenance = connection.execute(
                "SELECT delegate_id FROM armi.party_input_interactions WHERE purpose='codex_task_request'"
            ).fetchone()
        self.assertEqual(provenance, (command.delegate_id,))

    @pytest.mark.test_group("admin", "schema")
    def test_admin_mcp_health_and_schema_status_use_only_admin_identity(self) -> None:
        fixture = self.create_database()
        self._install_current(
            fixture.migrator_dsn,
            environment_id=fixture.environment_id,
        )
        config = AdminConfig.model_validate(
            {
                "schema_version": "armi.admin-config.v10",
                "authorization_public_key": _ADMIN_AUTHORIZATION_KEY.public_key()
                .public_bytes_raw()
                .hex(),
                "operator_id": "isolated-test-agent",
                "authorized_operations": tuple(item.name for item in ADMIN_OPERATIONS),
                "environment_kind": "acceptance",
                "environment_id": str(fixture.environment_id),
                "environment_incarnation": 1,
                "resettable": True,
                "test_controls_enabled": True,
                "environment_root": Path.cwd(),
                "experiment_root": Path.cwd(),
                "template_manifest": Path.cwd() / "README.md",
                "postgresql_client_root": Path(
                    os.environ.get(
                        "S003_POSTGRESQL_CLIENT_ROOT",
                        Path.cwd() / ".armi-tools/installs/postgresql/18.4/pgsql",
                    )
                ),
                "database_locator": "env:ARMI_SECRET_ADMIN_DATABASE",
                "migrator_database_locator": "env:ARMI_SECRET_MIGRATOR_DATABASE",
                "preview_key_locator": "env:ARMI_SECRET_ADMIN_PREVIEW_KEY",
                "expected": {
                    "source_root": _ADMIN_SOURCE_ROOT,
                },
            }
        )

        def service_for(dsn: str) -> AdminToolService:
            return bootstrap_admin(
                config,
                AdminCredentialPort(
                    locator=config.locator,
                    config_root=Path.cwd(),
                    environ={"ARMI_SECRET_ADMIN_DATABASE": dsn},
                ),
            ).service

        service = service_for(fixture.admin_role_dsn)
        health = service.health(HealthRequest())
        status = service.schema_status(
            SchemaStatusRequest(environment_id=str(fixture.environment_id))
        )
        self.assertEqual(health.status, "succeeded")
        self.assertIsNotNone(health.result)
        assert health.result is not None
        self.assertEqual(health.result.role_status, "verified")
        self.assertEqual(status.status, "succeeded")
        self.assertIsNotNone(status.result)
        assert status.result is not None
        self.assertEqual(status.result.status, "current")
        self.assertGreater(status.result.table_count, 0)
        self.assertEqual(status.result.missing_tables, ())

        for denied_dsn in (fixture.runtime_dsn, fixture.migrator_dsn):
            denied = service_for(denied_dsn).health(HealthRequest())
            self.assertEqual(denied.status, "rejected")
            self.assertEqual(denied.error_code, "ADMIN-DB-ROLE")

        observation = service._observation  # pyright: ignore[reportPrivateUsage]
        diagnostics = observation.diagnostics()
        self.assertEqual(cast(dict[str, object], diagnostics["runtime"])["work"], [])
        self.assertEqual(
            cast(dict[str, object], diagnostics["artifact_integrity"])[
                "recorded_counts"
            ],
            {},
        )
        self.assertEqual(
            cast(dict[str, object], diagnostics["artifact_integrity"])[
                "physical_checks"
            ],
            [],
        )
        observation.register_environment(
            {
                "environment_id": str(fixture.environment_id),
                "environment_kind": "acceptance",
                "incarnation": 1,
                "resettable": True,
                "test_controls_enabled": True,
            }
        )
        registered = observation.environment()
        self.assertIsNotNone(registered)
        assert registered is not None
        self.assertEqual(registered["incarnation"], 1)
        self.assertRegex(
            observation.database_catalog_digest(), r"^sha256:[0-9a-f]{64}$"
        )
        with (
            psycopg.connect(fixture.admin_role_dsn, autocommit=True) as connection,
            self.assertRaises(psycopg.errors.InsufficientPrivilege),
        ):
            connection.execute(
                "UPDATE armi.deployment_environments SET incarnation = 2"
            )

    @pytest.mark.test_group("admin", "birth")
    def test_admin_reset_is_preview_bound_and_re_registers_without_backup(self) -> None:
        fixture = self.create_database()
        self._install_current(
            fixture.migrator_dsn,
            environment_id=fixture.environment_id,
        )
        with tempfile.TemporaryDirectory(dir=Path.cwd() / ".tmp") as temporary:
            experiment_root = Path(temporary).resolve()
            environment_root = experiment_root / "environment"
            template_root = experiment_root / "template"
            template_environment = template_root / "environment-template"
            secrets_root = experiment_root / "secrets"
            for path in (
                environment_root / "data",
                environment_root / "secrets",
                template_environment / "data",
                template_environment / "secrets",
                secrets_root,
            ):
                path.mkdir(parents=True)
            migrator_file = secrets_root / "migrator"
            runtime_file = secrets_root / "runtime"
            migrator_file.write_text(
                fixture.migrator_dsn, encoding="utf-8", newline="\n"
            )
            runtime_file.write_text(fixture.runtime_dsn, encoding="utf-8", newline="\n")
            environment_yaml = "\n".join(
                (
                    "environment:",
                    f"  environment_id: {fixture.environment_id}",
                    f'  data_root: "{(environment_root / "data").as_posix()}"',
                    "creator:",
                    "  port: 45681",
                    "secret_locators:",
                    "  database.migrator: env:ARMI_SECRET_MIGRATOR_DATABASE",
                    f"  database.runtime: file:{runtime_file.as_posix()}",
                )
            )
            (environment_root / "environment.yaml").write_text(
                environment_yaml, encoding="utf-8", newline="\n"
            )
            (template_environment / "environment.yaml").write_text(
                environment_yaml, encoding="utf-8", newline="\n"
            )
            template_manifest = template_root / "template.json"
            template_manifest.write_text(
                json.dumps(
                    {
                        "schema_version": "armi.admin-experiment-environment.v1",
                        "environment_id": str(fixture.environment_id),
                    },
                    separators=(",", ":"),
                ),
                encoding="utf-8",
                newline="\n",
            )
            config = AdminConfig.model_validate(
                {
                    "schema_version": "armi.admin-config.v10",
                    "authorization_public_key": _ADMIN_AUTHORIZATION_KEY.public_key()
                    .public_bytes_raw()
                    .hex(),
                    "operator_id": "isolated-test-agent",
                    "authorized_operations": tuple(
                        item.name for item in ADMIN_OPERATIONS
                    ),
                    "environment_kind": "acceptance",
                    "environment_id": str(fixture.environment_id),
                    "environment_incarnation": 1,
                    "resettable": True,
                    "test_controls_enabled": True,
                    "environment_root": environment_root,
                    "experiment_root": experiment_root,
                    "template_manifest": template_manifest,
                    "postgresql_client_root": Path(
                        os.environ.get(
                            "S003_POSTGRESQL_CLIENT_ROOT",
                            Path.cwd() / ".armi-tools/installs/postgresql/18.4/pgsql",
                        )
                    ),
                    "database_locator": "env:ARMI_SECRET_ADMIN_DATABASE",
                    "migrator_database_locator": "env:ARMI_SECRET_MIGRATOR_DATABASE",
                    "preview_key_locator": "env:ARMI_SECRET_ADMIN_PREVIEW_KEY",
                    "expected": {
                        "source_root": _ADMIN_SOURCE_ROOT,
                    },
                }
            )
            credentials = AdminCredentialPort(
                locator=config.locator,
                migrator_locator=config.migrator_locator,
                preview_locator=config.preview_locator,
                config_root=experiment_root,
                environ={
                    "ARMI_SECRET_ADMIN_DATABASE": fixture.admin_role_dsn,
                    "ARMI_SECRET_MIGRATOR_DATABASE": fixture.migrator_dsn,
                    "ARMI_SECRET_ADMIN_PREVIEW_KEY": "s036-preview-key",
                },
            )
            service = bootstrap_admin(config, credentials).service
            service._register_environment(1)  # pyright: ignore[reportPrivateUsage]
            for name in ("admin.yaml", "issuer.yaml"):
                (environment_root / name).write_text(
                    config.model_dump_json(), encoding="utf-8"
                )
            preview = service.mutate(
                "environment_reset_preview",
                EnvironmentResetPreviewRequest(
                    environment_id=str(fixture.environment_id),
                    environment_incarnation=1,
                    idempotency_key="preview-reset-once",
                    purpose="admin.environment_reset_preview",
                ),
            )
            self.assertEqual(preview.status, "succeeded", preview.model_dump_json())
            assert preview.result is not None
            self.assertTrue(
                {"template_digest", "data_root_digest"}.isdisjoint(preview.result)
            )
            authorization_id = _approve_admin_preview(service, preview.result)
            reset = service.mutate(
                "environment_reset",
                EnvironmentResetRequest(
                    environment_id=str(fixture.environment_id),
                    environment_incarnation=1,
                    idempotency_key="apply-reset-once",
                    purpose="admin.environment_reset",
                    authorization_ref="isolated-test-reset",
                    authorization_id=authorization_id,
                    preview_token=str(preview.result["preview_token"]),
                ),
            )
            self.assertEqual(reset.status, "succeeded", reset.model_dump_json())
            assert reset.result is not None
            self.assertNotIn("recovery_digest", reset.result)
            for name in ("admin.yaml", "issuer.yaml"):
                updated = AdminConfig.model_validate(
                    json.loads((environment_root / name).read_bytes())
                )
                self.assertEqual(updated.environment_incarnation, 2)
                self.assertEqual(updated.environment_id, config.environment_id)
            replay = service.mutate(
                "environment_reset",
                EnvironmentResetRequest(
                    environment_id=str(fixture.environment_id),
                    environment_incarnation=1,
                    idempotency_key="apply-reset-once",
                    purpose="admin.environment_reset",
                    authorization_ref="isolated-test-reset",
                    authorization_id=authorization_id,
                    preview_token=str(preview.result["preview_token"]),
                ),
            )
            self.assertEqual(replay, reset)
            reload_required = service.mutate(
                "runtime_start",
                RuntimeControlRequest(
                    environment_id=str(fixture.environment_id),
                    environment_incarnation=1,
                    idempotency_key="start-with-stale-config",
                    purpose="admin.runtime_start",
                ),
            )
            self.assertEqual(reload_required.status, "conflict")
            self.assertEqual(reload_required.error_code, "ADMIN-CONFIG-RELOAD-REQUIRED")
            with psycopg.connect(fixture.provisioner_dsn) as connection:
                self.assertEqual(
                    connection.execute(
                        "SELECT incarnation FROM armi.deployment_environments"
                    ).fetchone(),
                    (2,),
                )
                self.assertIsNotNone(
                    connection.execute("SELECT to_regclass('armi.subjects')").fetchone()
                )
            recovery = list(
                (experiment_root / ".armi-admin-recovery").glob(
                    "*/recovery-manifest.json"
                )
            )
            self.assertEqual(recovery, [])
            self.assertFalse((experiment_root / ".armi-admin-recovery").exists())

    @pytest.mark.test_group("admin", "subject-state")
    def test_t07_component_preview_apply_status_and_role_boundary(self) -> None:
        fixture = self.create_database()
        self._install_current(
            fixture.migrator_dsn,
            environment_id=fixture.environment_id,
        )
        packaged = packaged_birth_digests()
        anchor = PersonalityAnchor(
            schema_version="armi.personality-anchor.v1",
            voice_style="约 16 岁少女口吻",
            traits=("审慎",),
        )
        manifest = BirthManifest(
            schema_version="armi.birth-manifest.v1",
            environment_id=fixture.environment_id,
            birth_request_id=_uuid7(),
            creator_party_id=_uuid7(),
            idempotency_key="s037-admin-correction-birth",
            personality_anchor=anchor,
            birth_contract_digest=packaged["birth_contract_digest"],
            request_digest=Digest.from_bytes(b"s037-admin-correction-birth"),
        )

        async def birth_subject(artifact_root: Path) -> None:
            factory = PostgreSQLUnitOfWorkFactory(
                fixture.runtime_dsn,
                environment_id=fixture.environment_id,
                pool_min=1,
                pool_max=1,
                acquire_timeout_seconds=2,
                statement_timeout_seconds=5,
                require_runtime_fence=False,
            )
            transaction = BirthTransaction(
                _publishing_artifact_store(artifact_root, factory),
                ArtifactCatalogRepository(),
                _birth_repository(),
                factory,
            )
            await factory.open()
            try:
                await transaction.birth(manifest)
            finally:
                await factory.close()

        with tempfile.TemporaryDirectory(dir=Path.cwd() / ".tmp") as temporary:
            experiment_root = Path(temporary).resolve()
            environment_root = experiment_root / "environment"
            artifact_root = environment_root / "data" / "artifacts"
            artifact_root.mkdir(parents=True)
            template = experiment_root / "template.json"
            template.write_text("{}", encoding="utf-8", newline="\n")
            asyncio.run(
                birth_subject(artifact_root),
                loop_factory=lambda: asyncio.SelectorEventLoop(
                    selectors.SelectSelector()
                ),
            )
            with psycopg.connect(fixture.provisioner_dsn) as connection:
                component_heads = connection.execute(
                    """
                    SELECT component_kind, component_revision_id
                    FROM armi.subject_component_revisions WHERE is_current
                    ORDER BY component_kind
                    LIMIT 2
                    """
                ).fetchall()
                self.assertEqual(len(component_heads), 2)
                with self.assertRaises(psycopg.errors.IntegrityError):
                    connection.execute(
                        """
                        INSERT INTO armi.subject_component_revisions (
                            component_revision_id,subject_id,component_kind,component_version,
                            previous_revision_id,origin_kind,origin_ref,semantic_payload,privacy_scope,is_current)
                        SELECT %s,subject_id,component_kind,component_version+1,
                               component_revision_id,'admin_correction',%s,semantic_payload,'private',true
                        FROM armi.subject_component_revisions WHERE component_revision_id=%s
                        """,
                        (uuid7(), uuid7(), component_heads[0][1]),
                    )
                connection.rollback()
                with self.assertRaises(psycopg.errors.IntegrityError):
                    connection.execute(
                        """
                        UPDATE armi.subject_component_revisions
                        SET previous_revision_id = %s
                        WHERE component_revision_id = %s
                        """,
                        (component_heads[1][1], component_heads[0][1]),
                    )
                connection.rollback()

                prompt_head = connection.execute(
                    """SELECT prompt_document_id,prompt_revision_id,subject_id
                       FROM armi.prompt_revisions
                       WHERE prompt_kind='personality_anchor' AND is_current"""
                ).fetchone()
                assert prompt_head is not None
                foreign_document_id, foreign_revision_id = _uuid7(), _uuid7()
                connection.execute(
                    """INSERT INTO armi.prompt_revisions (
                           prompt_revision_id,prompt_document_id,subject_id,prompt_kind,
                           revision_no,content_artifact_id,content_digest,
                           author_party_id,change_reason)
                       SELECT %s,%s,subject_id,'creator_guidance',1,
                              content_artifact_id,content_digest,author_party_id,'created'
                       FROM armi.prompt_revisions WHERE prompt_revision_id=%s""",
                    (foreign_revision_id, foreign_document_id, prompt_head[1]),
                )
                connection.commit()
                # History must not cross prompt kind or logical document.
                with self.assertRaises(psycopg.errors.IntegrityError):
                    connection.execute(
                        """UPDATE armi.prompt_revisions
                           SET revision_no=2,previous_revision_id=%s,change_reason='revised'
                           WHERE prompt_revision_id=%s""",
                        (prompt_head[1], foreign_revision_id),
                    )
                connection.rollback()
                # A second current row cannot silently replace the existing prompt.
                with self.assertRaises(psycopg.errors.IntegrityError):
                    connection.execute(
                        """INSERT INTO armi.prompt_revisions (
                               prompt_revision_id,prompt_document_id,subject_id,prompt_kind,
                               revision_no,previous_revision_id,content_artifact_id,
                               content_digest,author_party_id,change_reason)
                           SELECT %s,prompt_document_id,subject_id,prompt_kind,
                                  2,prompt_revision_id,content_artifact_id,
                                  content_digest,author_party_id,'revised'
                           FROM armi.prompt_revisions WHERE prompt_revision_id=%s""",
                        (_uuid7(), foreign_revision_id),
                    )
                connection.rollback()
            config = AdminConfig.model_validate(
                {
                    "schema_version": "armi.admin-config.v10",
                    "authorization_public_key": _ADMIN_AUTHORIZATION_KEY.public_key()
                    .public_bytes_raw()
                    .hex(),
                    "operator_id": "isolated-test-agent",
                    "authorized_operations": tuple(
                        item.name for item in ADMIN_OPERATIONS
                    ),
                    "environment_kind": "system_test",
                    "environment_id": str(fixture.environment_id),
                    "environment_incarnation": 1,
                    "resettable": True,
                    "test_controls_enabled": True,
                    "environment_root": environment_root,
                    "experiment_root": experiment_root,
                    "template_manifest": template,
                    "postgresql_client_root": Path.cwd()
                    / ".armi-tools/installs/postgresql/18.4/pgsql",
                    "database_locator": "env:ARMI_SECRET_ADMIN_DATABASE",
                    "migrator_database_locator": "env:ARMI_SECRET_MIGRATOR_DATABASE",
                    "preview_key_locator": "env:ARMI_SECRET_ADMIN_PREVIEW_KEY",
                    "expected": {
                        "source_root": _ADMIN_SOURCE_ROOT,
                    },
                }
            )
            secret_values = {
                "ARMI_SECRET_ADMIN_DATABASE": fixture.admin_role_dsn,
                "ARMI_SECRET_MIGRATOR_DATABASE": fixture.migrator_dsn,
                "ARMI_SECRET_ADMIN_PREVIEW_KEY": "s037-preview-key",
            }

            def new_service() -> AdminToolService:
                return bootstrap_admin(
                    config,
                    AdminCredentialPort(
                        locator=config.locator,
                        migrator_locator=config.migrator_locator,
                        preview_locator=config.preview_locator,
                        config_root=experiment_root,
                        environ=secret_values,
                    ),
                ).service

            service = new_service()
            service._register_environment(1)  # pyright: ignore[reportPrivateUsage]
            replacement = {
                "schema_version": "armi.mind.v4",
                "understanding": ["我知道这次变化来自隔离管理纠正"],
                "attention": [],
                "thoughts": [],
                "wishes": [],
                "motivations": [],
            }
            preview = service.mutate(
                "preview_correction",
                PreviewCorrectionRequest.model_validate_json(
                    json.dumps(
                        {
                            "environment_id": str(fixture.environment_id),
                            "environment_incarnation": 1,
                            "idempotency_key": "s037-preview-mind",
                            "purpose": "admin.preview_correction",
                            "spec": {
                                "correction_kind": "replace_subject_component",
                                "component_kind": "mind",
                                "expected_component_version": 1,
                                "replacement": replacement,
                            },
                        }
                    )
                ),
            )
            self.assertEqual(preview.status, "succeeded", preview.model_dump_json())
            assert preview.result is not None
            self.assertTrue(
                {"scope_digest", "impact_digest", "command_digest"}.isdisjoint(
                    preview.result
                )
            )
            token = str(preview.result["preview_token"])
            apply = service.mutate(
                "apply_correction",
                ApplyCorrectionRequest.model_validate_json(
                    json.dumps(
                        {
                            "environment_id": str(fixture.environment_id),
                            "environment_incarnation": 1,
                            "idempotency_key": "s037-apply-mind",
                            "purpose": "admin.apply_correction",
                            "authorization_ref": "isolated-test-mind-correction",
                            "authorization_id": _approve_admin_preview(
                                service, preview.result
                            ),
                            "preview_token": token,
                            "spec": {
                                "correction_kind": "replace_subject_component",
                                "component_kind": "mind",
                                "expected_component_version": 1,
                                "replacement": replacement,
                            },
                        }
                    )
                ),
            )
            self.assertEqual(apply.status, "succeeded", apply.model_dump_json())
            assert apply.result is not None
            self.assertEqual(apply.result["previous_state_epoch"], 0)
            self.assertEqual(apply.result["state_epoch"], 1)
            self.assertEqual(apply.result["subject_version"], 0)
            self.assertTrue(
                {"impact_digest", "postcondition_digest"}.isdisjoint(apply.result)
            )
            status = new_service().observe(
                "correction_status",
                CorrectionStatusRequest(
                    environment_id=str(fixture.environment_id),
                    preview_token=token,
                ),
            )
            self.assertEqual(status.status, "succeeded", status.model_dump_json())
            assert status.result is not None
            self.assertEqual(status.result["status"], "applied")
            self.assertNotIn("postcondition_digest", status.result)

            with psycopg.connect(fixture.runtime_dsn) as runtime:
                self.assertEqual(
                    runtime.execute(
                        "SELECT subject_version, state_epoch FROM armi.subjects"
                    ).fetchone(),
                    (0, 1),
                )
                head = runtime.execute(
                    """SELECT head.mind_version, head.origin_kind, head.semantic_payload, head.previous_revision_id FROM armi.mind_revisions AS head WHERE head.is_current """
                ).fetchone()
                assert head is not None
                self.assertEqual(head[0:2], (2, "admin_correction"))
                self.assertEqual(
                    head[2], {**replacement, "concerns": [], "motivation_states": []}
                )
                bootstrap_revision_id = str(head[3])
                with self.assertRaises(psycopg.errors.InsufficientPrivilege):
                    runtime.execute("DELETE FROM armi.subjects")
                runtime.rollback()

            repair_preview = service.mutate(
                "preview_correction",
                PreviewCorrectionRequest.model_validate(
                    {
                        "environment_id": str(fixture.environment_id),
                        "environment_incarnation": 1,
                        "idempotency_key": "s037-preview-repair-mind",
                        "purpose": "admin.preview_correction",
                        "spec": {
                            "correction_kind": "repair_subject_component_head",
                            "component_kind": "mind",
                            "expected_component_version": 2,
                            "target_revision_id": bootstrap_revision_id,
                        },
                    }
                ),
            )
            self.assertEqual(repair_preview.status, "succeeded")
            assert repair_preview.result is not None
            repair_apply = service.mutate(
                "apply_correction",
                ApplyCorrectionRequest.model_validate(
                    {
                        "environment_id": str(fixture.environment_id),
                        "environment_incarnation": 1,
                        "idempotency_key": "s037-apply-repair-mind",
                        "authorization_ref": "isolated-test-repair-mind",
                        "authorization_id": _approve_admin_preview(
                            service, repair_preview.result
                        ),
                        "purpose": "admin.apply_correction",
                        "preview_token": repair_preview.result["preview_token"],
                        "spec": {
                            "correction_kind": "repair_subject_component_head",
                            "component_kind": "mind",
                            "expected_component_version": 2,
                            "target_revision_id": bootstrap_revision_id,
                        },
                    }
                ),
            )
            self.assertEqual(repair_apply.status, "succeeded")
            assert repair_apply.result is not None
            self.assertEqual(repair_apply.result["state_epoch"], 2)

            runtime_instance_id = _uuid7()
            work_id = _uuid7()
            with psycopg.connect(fixture.provisioner_dsn) as provisioner:
                authority_identity = provisioner.execute(
                    "SELECT subject_id, current_bundle_activation_id FROM armi.subjects"
                ).fetchone()
                assert authority_identity is not None
                provisioner.execute(
                    "INSERT INTO armi.runtime_instances (runtime_instance_id, subject_id, bundle_activation_id, fence_token, status, lease_expires_at, stopped_at) VALUES (%s, %s, %s, 1, 'fenced', statement_timestamp() + interval '1 second', statement_timestamp())",
                    (runtime_instance_id, *authority_identity),
                )
                provisioner.execute(
                    "INSERT INTO armi.durable_work (work_id, work_kind, owner_kind, "
                    "owner_ref, idempotency_key, payload_digest, priority, not_before, "
                    "deadline_at, status, max_attempts, attempt_count, current_attempt_id, "
                    "lease_owner, lease_expires_at, lease_token, trace_id) VALUES (%s, "
                    "'artifact.object.delete', 'artifact_object_deletion', %s, "
                    "'s037-requeue', %s, 0, "
                    "statement_timestamp(), statement_timestamp() + interval '1 hour', "
                    "'leased', 3, 1, %s, %s, statement_timestamp() - interval '1 second', "
                    "1, %s)",
                    (
                        work_id,
                        runtime_instance_id,
                        Digest.from_bytes(b"s037-requeue").value,
                        _uuid7(),
                        runtime_instance_id,
                        runtime_instance_id.hex,
                    ),
                )
                provisioner.commit()
            work_preview = service.mutate(
                "preview_correction",
                PreviewCorrectionRequest.model_validate(
                    {
                        "environment_id": str(fixture.environment_id),
                        "environment_incarnation": 1,
                        "idempotency_key": "s037-preview-requeue",
                        "purpose": "admin.preview_correction",
                        "spec": {
                            "correction_kind": "requeue_stuck_work",
                            "work_id": str(work_id),
                        },
                    }
                ),
            )
            self.assertEqual(work_preview.status, "succeeded")
            assert work_preview.result is not None
            work_apply = service.mutate(
                "apply_correction",
                ApplyCorrectionRequest.model_validate(
                    {
                        "environment_id": str(fixture.environment_id),
                        "environment_incarnation": 1,
                        "idempotency_key": "s037-apply-requeue",
                        "purpose": "admin.apply_correction",
                        "preview_token": work_preview.result["preview_token"],
                        "spec": {
                            "correction_kind": "requeue_stuck_work",
                            "work_id": str(work_id),
                        },
                    }
                ),
            )
            self.assertEqual(work_apply.status, "succeeded")
            with psycopg.connect(fixture.runtime_dsn) as runtime:
                self.assertEqual(
                    runtime.execute(
                        "SELECT status, lease_token, attempt_count, lease_owner "
                        "FROM armi.durable_work WHERE work_id = %s",
                        (work_id,),
                    ).fetchone(),
                    ("ready", 2, 1, None),
                )

            content = b"s037 uncommitted creator input"
            content_digest = hashlib.sha256(content).hexdigest()
            artifact_object_id = _uuid7()
            artifact_id = _uuid7()
            interaction_id = _uuid7()
            evidence_id = _uuid7()
            opportunity_id = _uuid7()
            timeline_id = _uuid7()
            audit_id = _uuid7()
            with psycopg.connect(fixture.provisioner_dsn) as provisioner:
                identity = provisioner.execute(
                    "SELECT subject.subject_id, scene.scene_id, scene.primary_party_id "
                    "FROM armi.subjects AS subject JOIN armi.interaction_scenes AS scene "
                    "ON scene.subject_id = subject.subject_id AND scene.scene_key = 'default'"
                ).fetchone()
                assert identity is not None
                subject_id, scene_id, creator_id = identity
                locator = (
                    f"objects/sha256/{content_digest[:2]}/{content_digest[2:4]}/"
                    f"{content_digest}"
                )
                provisioner.execute(
                    "INSERT INTO armi.artifact_objects (artifact_object_id, "
                    "content_digest, byte_size, storage_locator, generation, "
                    "object_status, integrity_status) VALUES (%s, %s, %s, %s, 1, "
                    "'available', 'verified')",
                    (
                        artifact_object_id,
                        f"sha256:{content_digest}",
                        len(content),
                        locator,
                    ),
                )
                provisioner.execute(
                    "INSERT INTO armi.artifacts (artifact_id, artifact_object_id, "
                    "object_generation, media_type, logical_kind, producer_kind, "
                    "producer_trace_id, privacy_scope) VALUES (%s, %s, 1, "
                    "'text/plain', 'creator.input.text', 's037_conformance', %s, "
                    "'creator_visible')",
                    (
                        artifact_id,
                        artifact_object_id,
                        interaction_id.hex,
                    ),
                )
                provisioner.execute(
                    "INSERT INTO armi.party_input_interactions (interaction_id, "
                    "subject_id, scene_id, source_party_id, purpose, idempotency_key, "
                    "request_digest, content_digest, trace_id) VALUES (%s, %s, %s, %s, "
                    "'creator_message', 's037-delete-input', %s, %s, %s)",
                    (
                        interaction_id,
                        subject_id,
                        scene_id,
                        creator_id,
                        Digest.from_bytes(b"s037-delete-request").value,
                        f"sha256:{content_digest}",
                        interaction_id.hex,
                    ),
                )
                provisioner.execute(
                    "INSERT INTO armi.external_evidence (evidence_id, "
                    "interaction_id, subject_id, scene_id, context_party_id, "
                    "artifact_id, source_kind, trust_status, privacy_scope, "
                    "acceptance_status) VALUES (%s, %s, %s, %s, %s, %s, "
                    "'creator_input', 'external_claim', 'creator_visible', 'accepted')",
                    (
                        evidence_id,
                        interaction_id,
                        subject_id,
                        scene_id,
                        creator_id,
                        artifact_id,
                    ),
                )
                provisioner.execute(
                    "INSERT INTO armi.opportunities (opportunity_id, evidence_id, "
                    "subject_id, scene_id, context_party_id, purpose, eligibility_status, "
                    "current_disposition, root_opportunity_id, reconsideration_no, "
                    "source_kind, source_ref, source_version) VALUES "
                    "(%s, %s, %s, %s, %s, 'consider_creator_input', 'eligible', 'open', "
                    "%s, 0, 'external_evidence', %s, 1)",
                    (
                        opportunity_id,
                        evidence_id,
                        subject_id,
                        scene_id,
                        creator_id,
                        opportunity_id,
                        evidence_id,
                    ),
                )
                provisioner.execute(
                    "INSERT INTO armi.scene_timeline_items (timeline_item_id, scene_id, "
                    "source_kind, source_ref, source_event_no, result_status, occurred_at) "
                    "VALUES (%s, %s, 'creator_input', %s, 1, 'accepted', "
                    "statement_timestamp())",
                    (timeline_id, scene_id, interaction_id),
                )
                provisioner.execute(
                    "INSERT INTO armi.audit_events (audit_event_id, actor_kind, actor_ref, "
                    "purpose, operation, target_kind, target_ref, result_status, trace_id, "
                    "sensitivity, subject_id) VALUES (%s, 'runtime', %s, "
                    "'creator_message', 'creator.input.accepted', 'creator_input', %s, "
                    "'accepted', %s, 'private', %s)",
                    (
                        audit_id,
                        creator_id,
                        interaction_id,
                        interaction_id.hex,
                        subject_id,
                    ),
                )
                provisioner.commit()
            object_path = artifact_root / locator
            object_path.parent.mkdir(parents=True, exist_ok=True)
            object_path.write_bytes(content)
            delete_preview = service.mutate(
                "preview_correction",
                PreviewCorrectionRequest.model_validate(
                    {
                        "environment_id": str(fixture.environment_id),
                        "environment_incarnation": 1,
                        "idempotency_key": "s037-preview-delete-input",
                        "purpose": "admin.preview_correction",
                        "spec": {
                            "correction_kind": "delete_uncommitted_creator_input",
                            "interaction_id": str(interaction_id),
                        },
                    }
                ),
            )
            self.assertEqual(
                delete_preview.status, "succeeded", delete_preview.model_dump_json()
            )
            assert delete_preview.result is not None
            self.assertTrue(delete_preview.result["side_work_required"])
            delete_apply = service.mutate(
                "apply_correction",
                ApplyCorrectionRequest.model_validate(
                    {
                        "environment_id": str(fixture.environment_id),
                        "environment_incarnation": 1,
                        "idempotency_key": "s037-apply-delete-input",
                        "authorization_ref": "isolated-test-delete-uncommitted-input",
                        "authorization_id": _approve_admin_preview(
                            service, delete_preview.result
                        ),
                        "purpose": "admin.apply_correction",
                        "preview_token": delete_preview.result["preview_token"],
                        "spec": {
                            "correction_kind": "delete_uncommitted_creator_input",
                            "interaction_id": str(interaction_id),
                        },
                    }
                ),
            )
            self.assertEqual(
                delete_apply.status, "succeeded", delete_apply.model_dump_json()
            )
            assert delete_apply.result is not None
            side_work_id = str(delete_apply.result["side_work_id"])
            settle = service.mutate(
                "settle_correction_work",
                SettleCorrectionWorkRequest(
                    environment_id=str(fixture.environment_id),
                    environment_incarnation=1,
                    idempotency_key="s037-settle-delete-input",
                    purpose="admin.settle_correction_work",
                    side_work_id=side_work_id,
                ),
            )
            self.assertEqual(settle.status, "succeeded")
            assert settle.result is not None
            self.assertEqual(settle.result["status"], "ready")
            self.assertEqual(settle.result["file_result"], "artifact_lifecycle_owned")
            self.assertTrue(object_path.exists())
            with psycopg.connect(fixture.runtime_dsn) as runtime:
                facts = runtime.execute(
                    "SELECT (SELECT state_epoch FROM armi.subjects), "
                    "(SELECT count(*) FROM armi.party_input_interactions WHERE "
                    "interaction_id = %s), (SELECT status FROM armi.durable_work "
                    "WHERE work_id = %s), (SELECT status FROM "
                    "armi.artifact_object_deletions WHERE "
                    "artifact_object_deletion_id = %s)",
                    (interaction_id, side_work_id, side_work_id),
                ).fetchone()
                self.assertEqual(facts, (4, 0, "ready", "ready"))

    @pytest.mark.test_group("schema", "admin")
    def test_runtime_readiness_rejects_catalog_constraint_drift(self) -> None:
        fixture = self.create_database()
        gateway = PostgreSQLSchemaGateway()
        gateway.install(
            fixture.migrator_dsn,
            environment_id=fixture.environment_id,
        )
        with psycopg.connect(fixture.provisioner_dsn, autocommit=True) as connection:
            connection.execute(
                "ALTER TABLE armi.subjects DROP CONSTRAINT subjects_status_check"
            )
        with self.assertRaises(DatabaseViolation) as raised:
            gateway.status(
                fixture.runtime_dsn,
                environment_id=fixture.environment_id,
            )
        self.assertEqual(raised.exception.code, "DB-SCHEMA-CONTRACT")

    @pytest.mark.test_group("life-query", "memory")
    def test_life_record_query_plans_use_bounded_and_trigram_indexes(self) -> None:
        fixture = self.create_database()
        self._install_current(
            fixture.migrator_dsn,
            environment_id=fixture.environment_id,
        )
        subject_id = _uuid7()
        scene_id = _uuid7()
        with psycopg.connect(fixture.provisioner_dsn) as connection:
            connection.execute("SET session_replication_role = replica")
            connection.execute(
                """
                INSERT INTO armi.accepted_experiences (
                    experience_id, subject_id, subject_commit_id,
                    cognitive_episode_id, proposal_ref, experience_kind,
                    fact_class, first_person_gist, scene_id, occurred_at,
                    learned_at, accepted_at, source_perspective, uncertainty,
                    privacy_scope
                )
                SELECT uuidv7(), %s, uuidv7(), uuidv7(), 'proposal:1',
                       'creator_input', 'external_claim',
                       CASE WHEN ordinal = 123456
                            THEN 'rare telescope marker for selective search'
                            ELSE 'ordinary long-term experience' END,
                       %s,
                       statement_timestamp() -
                           ((ordinal %% 3650)::text || ' days')::interval,
                       statement_timestamp() -
                           ((ordinal %% 3650)::text || ' days')::interval,
                       statement_timestamp() -
                           ((ordinal %% 3650)::text || ' days')::interval,
                       'creator_claim', NULL, 'private'
                FROM generate_series(1, 200000) AS ordinal
                """,
                (subject_id, scene_id),
            )
            connection.execute(
                """
                CREATE TEMP TABLE memory_plan_fixture ON COMMIT DROP AS
                SELECT ordinal, uuidv7() AS memory_id,
                       uuidv7() AS historical_revision_id,
                       uuidv7() AS current_revision_id,
                       uuidv7() AS source_experience_id
                FROM generate_series(1, 5000) AS ordinal
                """
            )
            connection.execute(
                """
                INSERT INTO armi.subjective_memory_revisions (
                    memory_revision_id, memory_id, revision_no,
                    previous_revision_id, subject_commit_id,
                    candidate_validation_id, proposal_ref,
                    source_experience_id, source_kind, source_fact_class,
                    summary, revision_kind, accessibility,
                    mechanism_identity, mechanism_config_identity,
                    privacy_scope
                )
                SELECT historical_revision_id, memory_id, 1, NULL,
                       uuidv7(), uuidv7(), 'proposal:1', source_experience_id,
                       'reported', 'external_claim',
                       'ordinary historical memory', 'formed', 'available',
                       'armi.memory-formation.contextual-v1', 'formation-v1',
                       'private'
                FROM memory_plan_fixture
                UNION ALL
                SELECT current_revision_id, memory_id, 2,
                       historical_revision_id, uuidv7(), uuidv7(),
                       'proposal:1', source_experience_id,
                       'reported', 'external_claim',
                       CASE WHEN ordinal = 2345
                            THEN 'rare aurora memory marker'
                            ELSE 'ordinary current memory' END,
                       'recalled', 'available',
                       'armi.memory-revision.contextual-v1',
                       'natural-dialogue-v1', 'private'
                FROM memory_plan_fixture
                """
            )
            connection.execute(
                """
                INSERT INTO armi.subjective_memories (
                    memory_id, subject_id, current_revision_id, head_version
                )
                SELECT memory_id, %s, current_revision_id, 2
                FROM memory_plan_fixture
                """,
                (subject_id,),
            )
            connection.execute(
                """
                CREATE TEMP TABLE material_plan_fixture ON COMMIT DROP AS
                SELECT ordinal, uuidv7() AS material_id,
                       uuidv7() AS revision_id
                FROM generate_series(1, 2000) AS ordinal
                """
            )
            connection.execute(
                """
                INSERT INTO armi.life_material_revisions (
                    life_material_revision_id, life_material_id, revision_no,
                    subject_commit_id, candidate_validation_id, proposal_ref,
                    artifact_id, title, metadata, revision_kind,
                    privacy_status, material_status, source_kind
                )
                SELECT revision_id, material_id, 1, uuidv7(), uuidv7(),
                       'proposal:1', uuidv7(),
                       CASE WHEN ordinal = 987
                            THEN 'rare comet material marker'
                            ELSE 'ordinary life material' END,
                       '{}'::jsonb, 'created', 'creator_visible', 'active',
                       'subject_cognition'
                FROM material_plan_fixture
                """
            )
            connection.execute(
                """
                INSERT INTO armi.life_materials (
                    life_material_id, subject_id, material_kind, owner_party_id, current_revision_id,
                    head_version
                )
                SELECT material_id, %s, 'diary', uuidv7(),
                       revision_id, 1
                FROM material_plan_fixture
                """,
                (subject_id,),
            )
            connection.execute(
                """
                CREATE TEMP TABLE relationship_plan_fixture ON COMMIT DROP AS
                SELECT ordinal, uuidv7() AS relationship_id,
                       uuidv7() AS revision_id,
                       uuidv7() AS subject_party_id,
                       uuidv7() AS other_party_id
                FROM generate_series(1, 1000) AS ordinal
                """
            )
            connection.execute(
                """
                INSERT INTO armi.relationship_revisions (
                    relationship_revision_id, relationship_id, revision_no,
                    subject_commit_id, candidate_validation_id, proposal_ref,
                    facts, interpretation, boundaries, commitments,
                    open_issues, relationship_status, mechanism_identity,
                    privacy_scope
                )
                SELECT revision_id, relationship_id, 1, uuidv7(), uuidv7(),
                       'proposal:1', '["known"]'::jsonb,
                       CASE WHEN ordinal = 543
                            THEN 'rare pulsar relationship marker'
                            ELSE 'ordinary relationship interpretation' END,
                       '[]'::jsonb, '[]'::jsonb, '[]'::jsonb, 'active',
                       'armi.relationship.contextual-v1', 'private'
                FROM relationship_plan_fixture
                """
            )
            connection.execute(
                """
                INSERT INTO armi.relationships (
                    relationship_id, subject_id, subject_party_id, other_party_id, scope,
                    current_revision_id, head_version
                )
                SELECT relationship_id, %s, subject_party_id,
                       other_party_id, 'other_human_social', revision_id, 1
                FROM relationship_plan_fixture
                """,
                (subject_id,),
            )
            connection.execute(
                """
                INSERT INTO armi.subject_component_revisions (
                    component_revision_id, subject_id, component_kind,
                    component_version, previous_revision_id, origin_kind,
                    origin_ref, semantic_payload, privacy_scope
                )
                SELECT uuidv7(), %s, 'self', ordinal,
                       CASE WHEN ordinal = 1 THEN NULL ELSE uuidv7() END,
                       CASE WHEN ordinal = 1
                            THEN 'bootstrap'
                            ELSE 'admin_correction' END,
                       uuidv7(),
                       jsonb_build_object(
                           'summary',
                           CASE WHEN ordinal = 4321
                                THEN 'rare nebula self marker'
                                ELSE 'ordinary self change' END
                       ),
                       'private'
                FROM generate_series(1, 5000) AS ordinal
                """,
                (subject_id,),
            )
            connection.execute("SET session_replication_role = origin")
            connection.execute(
                """
                ANALYZE armi.accepted_experiences;
                ANALYZE armi.subjective_memory_revisions;
                ANALYZE armi.life_material_revisions;
                ANALYZE armi.relationship_revisions;
                ANALYZE armi.subject_component_revisions
                """
            )

            bounded = connection.execute(
                """
                EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)
                SELECT experience_id, accepted_at
                FROM armi.accepted_experiences
                WHERE subject_id = %s
                ORDER BY accepted_at DESC, experience_id DESC
                LIMIT 51
                """,
                (subject_id,),
            ).fetchone()
            selective = connection.execute(
                """
                EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)
                SELECT experience_id
                FROM armi.accepted_experiences
                WHERE first_person_gist ILIKE '%%telescope%%'
                LIMIT 51
                """
            ).fetchone()
            boundary = connection.execute(
                """
                SELECT accepted_at, experience_id
                FROM armi.accepted_experiences
                WHERE subject_id = %s
                ORDER BY accepted_at DESC, experience_id DESC
                OFFSET 100000 LIMIT 1
                """,
                (subject_id,),
            ).fetchone()
            assert boundary is not None
            deep_page = connection.execute(
                """
                EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)
                SELECT experience_id, accepted_at
                FROM armi.accepted_experiences
                WHERE subject_id = %s
                  AND (accepted_at, experience_id) < (%s, %s)
                ORDER BY accepted_at DESC, experience_id DESC
                LIMIT 51
                """,
                (subject_id, boundary[0], boundary[1]),
            ).fetchone()

        assert bounded is not None and selective is not None and deep_page is not None
        bounded_plan = json.dumps(bounded[0], sort_keys=True)
        selective_plan = json.dumps(selective[0], sort_keys=True)
        deep_plan = json.dumps(deep_page[0], sort_keys=True)
        self.assertIn("accepted_experiences_subject_page_idx", bounded_plan)
        self.assertNotIn('"Node Type": "Seq Scan"', bounded_plan)
        self.assertIn("accepted_experiences_gist_trgm_idx", selective_plan)
        self.assertIn("accepted_experiences_subject_page_idx", deep_plan)
        self.assertNotIn('"Node Type": "Seq Scan"', deep_plan)

    @pytest.mark.test_group("capability", "schema")
    def test_hardened_permission_shapes_and_operational_indexes(self) -> None:
        fixture = self.create_database()
        self._install_current(
            fixture.migrator_dsn,
            environment_id=fixture.environment_id,
        )
        subject_id = _uuid7()
        with psycopg.connect(
            fixture.provisioner_dsn,
            autocommit=True,
        ) as connection:
            connection.execute("SET session_replication_role = replica")
            connection.execute(
                """
                INSERT INTO armi.effects (
                    effect_id, subject_id, scene_id, context_party_id,
                    payload_artifact_id, payload_digest, payload_bytes,
                    effect_kind, capability_kind, operation_class, audience_scope,
                    data_scope, purpose, authorization_basis, destination_kind,
                    destination_party_id, registration_digest, status,
                    verification_status, trace_id, current_attempt_id,
                    current_observation_id, settled_at, action_intent_id,
                    root_opportunity_id, operation_ref, candidate_validation_id,
                    proposal_ref, subject_commit_id, dispatch_status,
                    available_at, dispatch_deadline, claim_owner, claim_expires_at,
                    claim_token, attempt_count, last_error_code)
                SELECT uuidv7(), %s, uuidv7(), uuidv7(), uuidv7(),
                       'sha256:' || repeat('e', 64), 1,
                       'creator_response', 'creator.scene.reply', 'send',
                       'creator', 'creator_visible_response', 'respond_to_creator',
                       'runtime_builtin', 'creator_inbox', uuidv7(),
                       'sha256:' || repeat('f', 64),
                       CASE state WHEN 'ready' THEN 'registered'
                         WHEN 'claimed' THEN 'dispatching' ELSE 'unknown' END,
                       CASE state WHEN 'ready' THEN 'not_started'
                         WHEN 'claimed' THEN 'pending' ELSE 'inconclusive' END,
                       repeat('1', 32),
                       CASE WHEN state <> 'ready' THEN uuidv7() END,
                       CASE WHEN state = 'unknown' THEN uuidv7() END,
                       CASE WHEN state = 'unknown' THEN
                         statement_timestamp() - (ordinal || ' seconds')::interval END,
                       uuidv7(), uuidv7(), uuidv7(), uuidv7(), 'proposal:1', uuidv7(),
                       state,
                       statement_timestamp() - (ordinal || ' seconds')::interval,
                       statement_timestamp() + interval '1 day',
                       CASE WHEN state = 'claimed' THEN uuidv7() END,
                       CASE WHEN state = 'claimed' THEN
                         statement_timestamp() - (ordinal || ' seconds')::interval END,
                       CASE WHEN state = 'ready' THEN 0 ELSE 1 END,
                       CASE WHEN state = 'ready' THEN 0 ELSE 1 END,
                       CASE WHEN state = 'unknown' THEN 'EFFECT-RESULT-UNKNOWN' END
                FROM generate_series(1, 10000) AS ordinal
                CROSS JOIN (VALUES ('ready'), ('claimed'), ('unknown')) AS states(state)
                """,
                (subject_id,),
            )
            connection.execute(
                """
                INSERT INTO armi.cognitive_episodes (
                    cognitive_episode_id, opportunity_id, subject_id,
                    purpose, status, base_subject_version, base_state_epoch,
                    bundle_activation_id, mechanism_identity, trace_id
                )
                SELECT uuidv7(), uuidv7(), %s, 'consider_autonomous_life',
                       'preparing', 0, 0, uuidv7(),
                       'armi.context-compiler.layered-v3',
                       repeat('2', 32)
                FROM generate_series(1, 10000)
                """,
                (subject_id,),
            )
            connection.execute("SET session_replication_role = origin")
            connection.execute(
                """
                ANALYZE armi.effects;
                ANALYZE armi.cognitive_episodes
                """
            )
            plans = (
                connection.execute(
                    """
                    EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)
                    SELECT effect_id
                    FROM armi.effects
                    WHERE dispatch_status = 'ready'
                      AND available_at <= statement_timestamp()
                    ORDER BY available_at, effect_id
                    LIMIT 50
                    """
                ).fetchone(),
                connection.execute(
                    """
                    EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)
                    SELECT effect_id
                    FROM armi.effects
                    WHERE dispatch_status = 'claimed'
                      AND claim_expires_at <= statement_timestamp()
                    ORDER BY claim_expires_at, effect_id
                    LIMIT 50
                    """
                ).fetchone(),
                connection.execute(
                    """
                    EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)
                    SELECT effect_id
                    FROM armi.effects
                    WHERE status = 'unknown'
                      AND settled_at <= statement_timestamp()
                    ORDER BY settled_at, effect_id
                    LIMIT 50
                    """
                ).fetchone(),
                connection.execute(
                    """
                    EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)
                    SELECT cognitive_episode_id
                    FROM armi.cognitive_episodes
                    WHERE subject_id = %s
                      AND purpose = 'consider_autonomous_life'
                    ORDER BY created_at DESC, cognitive_episode_id DESC
                    LIMIT 50
                    """,
                    (subject_id,),
                ).fetchone(),
            )

        plan_text = tuple(json.dumps(row[0], sort_keys=True) for row in plans if row)
        self.assertEqual(len(plan_text), 4)
        for expected_index, plan in zip(
            (
                "effects_dispatch_ready_claim_idx",
                "effects_dispatch_claim_expiry_idx",
                "effects_unknown_settlement_idx",
                "cognitive_episodes_subject_purpose_recent_idx",
            ),
            plan_text,
            strict=True,
        ):
            self.assertIn(expected_index, plan)
            self.assertNotIn('"Node Type": "Seq Scan"', plan)

    @pytest.mark.test_group("runtime", "admin")
    def test_role_matrix_cross_environment_and_pool_reset(self) -> None:
        fixture_a = self.create_database()
        fixture_b = self.create_database()
        for fixture in (fixture_a, fixture_b):
            self._install_current(
                fixture.migrator_dsn,
                environment_id=fixture.environment_id,
            )
        for dsn in (fixture_a.runtime_dsn, fixture_a.admin_role_dsn):
            with psycopg.connect(dsn) as connection:
                self.assertEqual(
                    connection.execute("SELECT count(*) FROM armi.subjects").fetchone(),
                    (0,),
                )
                for statement in (
                    "CREATE TABLE armi.forbidden (id bigint)",
                    "DELETE FROM armi.subjects",
                    "SET ROLE armi_owner",
                ):
                    with self.assertRaises(psycopg.Error):
                        connection.execute(statement)
                    connection.rollback()
        with psycopg.connect(fixture_a.migrator_dsn) as connection:
            connection.execute("BEGIN")
            connection.execute("SET LOCAL ROLE armi_owner")
            connection.execute("CREATE TABLE armi.transient (id bigint)")
            connection.rollback()
            with self.assertRaises(psycopg.Error):
                connection.execute("CREATE ROLE forbidden")
            connection.rollback()
        values = conninfo_to_dict(fixture_a.runtime_dsn)
        cross_dsn = make_conninfo(
            host=values["host"],
            port=values["port"],
            dbname=fixture_b.database,
            user=values["user"],
            password=values["password"],
        )
        with self.assertRaises(psycopg.Error):
            psycopg.connect(cross_dsn, connect_timeout=5)

        admin_pool = AdminRoleBoundPool(
            fixture_a.admin_role_dsn,
            expected_role=fixture_a.admin_role,
        )
        admin_pool.open()
        try:
            with admin_pool.connection() as connection:
                connection.execute("SET search_path TO public")
            with admin_pool.connection() as connection:
                self.assertEqual(
                    connection.execute(
                        "SELECT current_setting('search_path')"
                    ).fetchone(),
                    ("pg_catalog, armi",),
                )
        finally:
            admin_pool.close()

    @pytest.mark.test_group("runtime")
    def test_identity_connection_and_runtime_authority_fail_safely(self) -> None:
        fixture = self.create_database()
        gateway = PostgreSQLSchemaGateway()
        self._install_current(
            fixture.migrator_dsn,
            environment_id=fixture.environment_id,
        )
        values = conninfo_to_dict(fixture.provisioner_dsn)
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            probe.bind(("127.0.0.1", 0))
            unused_port = probe.getsockname()[1]
        unavailable = make_conninfo(
            host="127.0.0.1",
            port=unused_port,
            dbname=fixture.database,
            user=values["user"],
            password=values["password"],
        )
        cases = (
            ("unavailable", unavailable, "DB-CONNECTION-UNAVAILABLE"),
            ("superuser", fixture.provisioner_dsn, "DB-ROLE-IDENTITY"),
            (
                "timezone",
                make_conninfo(fixture.runtime_dsn, options="-c timezone=Asia/Shanghai"),
                "DB-DATABASE-IDENTITY",
            ),
        )
        for label, dsn, expected_code in cases:
            with self.subTest(label=label):
                with self.assertRaises(DatabaseViolation) as raised:
                    gateway.status(
                        dsn,
                        environment_id=fixture.environment_id,
                    )
                self.assertEqual(raised.exception.code, expected_code)
                self.assertNotIn("127.0.0.1", str(raised.exception))
                self.assertNotIn(fixture.database, str(raised.exception))

        wrong_locale = self.create_database(locale="C")
        with self.assertRaises(DatabaseViolation) as raised:
            gateway.install(
                wrong_locale.migrator_dsn,
                environment_id=wrong_locale.environment_id,
            )
        self.assertEqual(raised.exception.code, "DB-DATABASE-IDENTITY")

    @pytest.mark.test_group("artifacts")
    def test_artifact_registration_reuse_verified_read_and_role_grants(self) -> None:
        fixture = self.create_database()
        self._install_current(
            fixture.migrator_dsn,
            environment_id=fixture.environment_id,
        )

        async def exercise(root: Path) -> dict[str, object]:
            factory = PostgreSQLUnitOfWorkFactory(
                fixture.runtime_dsn,
                environment_id=fixture.environment_id,
                pool_min=1,
                pool_max=2,
                acquire_timeout_seconds=1,
                statement_timeout_seconds=5,
                require_runtime_fence=False,
            )
            catalog = ArtifactCatalogRepository()
            storage = ContentAddressedArtifactStore(
                root,
                max_object_bytes=1024,
                publication_catalog=catalog,
                publication_uow_factory=factory,
                orphan_grace_seconds=86_400,
            )
            coordinator = ContentAddressedArtifactCoordinator(
                storage,
                catalog,
                factory,
                orphan_grace_seconds=86_400,
            )
            policy = ArtifactPolicy(
                media_type="application/octet-stream",
                logical_kind="test.payload",
                producer_kind="integration-test",
                producer_trace_id=TraceId("1" + ("0" * 31)),
                privacy_scope=ArtifactPrivacyScope.PRIVATE,
            )
            await factory.open()
            try:
                first, duplicate = await asyncio.gather(
                    coordinator.put(
                        _artifact_chunks(b"authoritative", b"-bytes"),
                        policy,
                    ),
                    coordinator.put(
                        _artifact_chunks(b"authoritative-bytes"),
                        policy,
                    ),
                )
                self.assertNotEqual(duplicate.artifact_id, first.artifact_id)
                self.assertEqual(duplicate.content_digest, first.content_digest)

                stream = await coordinator.open_verified(
                    first.artifact_id,
                    trace_id=policy.producer_trace_id,
                )
                async with stream:
                    self.assertEqual(await stream.read(), b"authoritative-bytes")

                conflicting = ArtifactPolicy(
                    media_type=policy.media_type,
                    logical_kind="test.other",
                    producer_kind=policy.producer_kind,
                    producer_trace_id=policy.producer_trace_id,
                    privacy_scope=policy.privacy_scope,
                )
                independent = await coordinator.put(
                    _artifact_chunks(b"authoritative-bytes"),
                    conflicting,
                )
                self.assertNotEqual(independent.artifact_id, first.artifact_id)
                self.assertEqual(independent.content_digest, first.content_digest)
                self.assertEqual(independent.logical_kind, "test.other")
                async with factory.unit_of_work(read_only=True) as unit_of_work:
                    counts = await (
                        await unit_of_work.transaction.execute(
                            """SELECT (SELECT count(*) FROM armi.artifact_objects),
                                      (SELECT count(*) FROM armi.artifacts)"""
                        )
                    ).fetchone()
                self.assertEqual(counts, (1, 3))

                digest_hex = first.content_digest.value.removeprefix("sha256:")
                object_path = (
                    root
                    / "objects"
                    / "sha256"
                    / digest_hex[:2]
                    / digest_hex[2:4]
                    / digest_hex
                )
                object_path.unlink()
                with self.assertRaisesRegex(ArtifactViolation, "ART-MISSING"):
                    await coordinator.open_verified(
                        first.artifact_id,
                        trace_id=policy.producer_trace_id,
                    )
                async with factory.unit_of_work(read_only=True) as unit_of_work:
                    query_result = await AuditEventRepository().query(
                        unit_of_work,
                        AuditQuery(trace_id=policy.producer_trace_id, limit=100),
                    )
                self.assertFalse(query_result.truncated)
                self.assertEqual(
                    [record.draft.operation for record in query_result.records],
                    [
                        "artifact.catalog.registered",
                        "artifact.catalog.registered",
                        "artifact.catalog.registered",
                        "artifact.integrity.missing",
                    ],
                )

                def rename_audit_table(source: str, target: str) -> None:
                    with psycopg.connect(
                        fixture.provisioner_dsn,
                        autocommit=True,
                    ) as connection:
                        connection.execute(
                            sql.SQL("ALTER TABLE armi.{} RENAME TO {}").format(
                                sql.Identifier(source),
                                sql.Identifier(target),
                            )
                        )

                await asyncio.to_thread(
                    rename_audit_table,
                    "audit_events",
                    "audit_events_unavailable",
                )
                try:
                    with self.assertRaisesRegex(ArtifactViolation, "ART-AUDIT"):
                        await coordinator.put(
                            _artifact_chunks(b"audit-must-be-atomic"),
                            policy,
                        )
                finally:
                    await asyncio.to_thread(
                        rename_audit_table,
                        "audit_events_unavailable",
                        "audit_events",
                    )
                report = await coordinator.report_orphans()
                return {
                    "content_digest": first.content_digest.value,
                    "finding_categories": [
                        finding.category for finding in report.findings
                    ],
                    "finding_digests": [
                        finding.content_digest for finding in report.findings
                    ],
                    "finding_counts": dict(report.counts),
                }
            finally:
                await factory.close()

        with tempfile.TemporaryDirectory(dir=Path.cwd() / ".tmp") as temporary:
            asyncio.run(
                exercise(Path(temporary).resolve() / "artifacts"),
                loop_factory=lambda: asyncio.SelectorEventLoop(
                    selectors.SelectSelector()
                ),
            )

        with psycopg.connect(fixture.runtime_dsn) as connection:
            rows = connection.execute(
                """
                SELECT a.artifact_id,o.integrity_status,a.retention_status,a.deleted_at
                FROM armi.artifacts a JOIN armi.artifact_objects o
                  USING (artifact_object_id)
                """
            ).fetchall()
            self.assertEqual(len(rows), 3)
            self.assertTrue(
                all(row[1:] == ("missing", "retained", None) for row in rows)
            )
            audit_rows = connection.execute(
                """
                SELECT operation, result_status, target_ref
                FROM armi.audit_events
                ORDER BY occurred_at, audit_event_id
                """
            ).fetchall()
            self.assertEqual(
                [row[0] for row in audit_rows],
                [
                    "artifact.catalog.registered",
                    "artifact.catalog.registered",
                    "artifact.catalog.registered",
                    "artifact.integrity.missing",
                ],
            )
            self.assertTrue(all(row[1] == "applied" for row in audit_rows))
            self.assertEqual({row[2] for row in audit_rows}, {row[0] for row in rows})
            with self.assertRaises(psycopg.errors.InsufficientPrivilege):
                connection.execute("DELETE FROM armi.artifacts")
            connection.rollback()
            for statement in (
                "UPDATE armi.audit_events SET operation = 'forbidden'",
                "DELETE FROM armi.audit_events",
                "TRUNCATE armi.audit_events",
            ):
                with self.assertRaises(psycopg.errors.InsufficientPrivilege):
                    connection.execute(cast(LiteralString, statement))
                connection.rollback()
        with psycopg.connect(fixture.admin_role_dsn) as connection:
            self.assertEqual(
                len(connection.execute("SELECT * FROM armi.artifacts").fetchall()), 3
            )
            self.assertEqual(
                len(connection.execute("SELECT * FROM armi.audit_events").fetchall()),
                4,
            )
        with (
            psycopg.connect(fixture.migrator_dsn) as connection,
            self.assertRaises(psycopg.errors.InsufficientPrivilege),
        ):
            connection.execute("SELECT * FROM armi.audit_events").fetchall()
        with psycopg.connect(fixture.provisioner_dsn) as connection:
            public_access = connection.execute(
                """
                SELECT count(*)
                FROM pg_catalog.pg_class AS relation
                JOIN pg_catalog.pg_namespace AS namespace
                  ON namespace.oid = relation.relnamespace
                CROSS JOIN LATERAL pg_catalog.aclexplode(
                    COALESCE(
                        relation.relacl,
                        pg_catalog.acldefault('r', relation.relowner)
                    )
                ) AS acl
                WHERE namespace.nspname = 'armi'
                  AND relation.relname = 'audit_events'
                  AND acl.grantee = 0
                """
            ).fetchone()
        self.assertEqual(public_access, (0,))

    @pytest.mark.test_group("birth")
    def test_unique_birth_is_atomic_concurrent_and_idempotent(self) -> None:
        fixture = self.create_database()
        self._install_current(
            fixture.migrator_dsn,
            environment_id=fixture.environment_id,
        )
        packaged = packaged_birth_digests()
        anchor = PersonalityAnchor(
            schema_version="armi.personality-anchor.v1",
            voice_style="约 16 岁少女口吻",
            traits=("坦率", "好奇"),
        )
        manifest = BirthManifest(
            schema_version="armi.birth-manifest.v1",
            environment_id=fixture.environment_id,
            birth_request_id=_uuid7(),
            creator_party_id=_uuid7(),
            idempotency_key="s015-concurrent-birth",
            personality_anchor=anchor,
            birth_contract_digest=packaged["birth_contract_digest"],
            request_digest=Digest.from_bytes(b"s015-birth-request"),
        )

        async def exercise(root: Path) -> tuple[BirthResult, BirthResult]:
            factory = PostgreSQLUnitOfWorkFactory(
                fixture.runtime_dsn,
                environment_id=fixture.environment_id,
                pool_min=1,
                pool_max=2,
                acquire_timeout_seconds=2,
                statement_timeout_seconds=5,
                require_runtime_fence=False,
            )
            transaction = BirthTransaction(
                _publishing_artifact_store(root, factory),
                ArtifactCatalogRepository(),
                _birth_repository(),
                factory,
            )
            await factory.open()
            try:
                first, replay = await asyncio.gather(
                    transaction.birth(manifest),
                    transaction.birth(manifest),
                )
                self.assertEqual(first.subject_id, replay.subject_id)
                self.assertEqual(
                    first.bundle_activation_id,
                    replay.bundle_activation_id,
                )
                self.assertEqual({first.created, replay.created}, {True, False})
                exact_replay = await transaction.birth(manifest)
                self.assertFalse(exact_replay.created)
                with self.assertRaisesRegex(
                    BirthViolation,
                    "BIRTH-IDEMPOTENCY-CONFLICT",
                ):
                    await transaction.birth(
                        replace(
                            manifest,
                            request_digest=Digest.from_bytes(b"changed-request"),
                        )
                    )
                with self.assertRaisesRegex(
                    BirthViolation,
                    "BIRTH-ALREADY-BORN",
                ):
                    await transaction.birth(
                        replace(
                            manifest,
                            birth_request_id=_uuid7(),
                            idempotency_key="s015-second-birth",
                            request_digest=Digest.from_bytes(b"second-request"),
                        )
                    )
                async with factory.unit_of_work(read_only=True) as unit:
                    mind = bootstrap_mind().read
                    head = await mind.current_head(
                        unit.transaction, subject_id=first.subject_id
                    )
                    history = await mind.history(
                        unit.transaction, subject_id=first.subject_id, limit=1
                    )
                    self.assertEqual(
                        [item.revision_id for item in history],
                        [head.current_revision_id],
                    )
                    self.assertEqual(history[0].canonical_state, head.canonical_state)
                    self.assertTrue(
                        await mind.history_is_continuous(
                            unit.transaction, subject_id=first.subject_id
                        )
                    )
                    self.assertEqual(
                        await mind.history(
                            unit.transaction,
                            subject_id=first.subject_id,
                            before_version=1,
                        ),
                        (),
                    )
                return first, replay
            finally:
                await factory.close()

        with tempfile.TemporaryDirectory(dir=Path.cwd() / ".tmp") as temporary:
            first, _ = asyncio.run(
                exercise(Path(temporary).resolve()),
                loop_factory=lambda: asyncio.SelectorEventLoop(
                    selectors.SelectSelector()
                ),
            )

        with psycopg.connect(fixture.runtime_dsn) as connection:
            counts = connection.execute(
                """
                SELECT
                    (SELECT count(*) FROM armi.subjects),
                    (SELECT count(*) FROM armi.parties),
                    (SELECT count(DISTINCT prompt_document_id) FROM armi.prompt_revisions),
                    (SELECT count(*) FROM armi.prompt_revisions),
                    (SELECT count(*) FROM armi.subject_component_revisions WHERE is_current ),
                    (SELECT count(*) FROM armi.subject_component_revisions),
                    (SELECT count(*) FROM armi.mind_revisions WHERE is_current ),
                    (SELECT count(*) FROM armi.mind_revisions),
                    (SELECT count(*) FROM armi.interaction_scenes),
                    (SELECT count(*) FROM armi.artifacts),
                    (SELECT count(*) FROM armi.audit_events)
                """
            ).fetchone()
            self.assertEqual(counts, (1, 2, 1, 1, 2, 2, 1, 1, 1, 1, 2))
            birth_identity = connection.execute(
                """
                SELECT current_bundle_activation_id, birth_contract_digest,
                       birth_creator_party_id
                FROM armi.subjects WHERE subject_id = %s
                """,
                (first.subject_id,),
            ).fetchone()
            self.assertEqual(
                birth_identity,
                (
                    first.bundle_activation_id,
                    packaged["birth_contract_digest"].value,
                    manifest.creator_party_id,
                ),
            )
            self_payload = connection.execute(
                """
                SELECT semantic_payload
                FROM armi.subject_component_revisions
                WHERE subject_id = %s AND component_kind = 'self'
                """,
                (first.subject_id,),
            ).fetchone()
            assert self_payload is not None
            self.assertIsNone(self_payload[0]["name"])
            self.assertEqual(self_payload[0]["interests"], [])
            self.assertEqual(self_payload[0]["goals"], [])
            with self.assertRaises(psycopg.errors.InsufficientPrivilege):
                connection.execute("DELETE FROM armi.subjects")
            connection.rollback()

        for contract_digest, expected_state in (
            (packaged["birth_contract_digest"], ContinuityState.BORN),
            (Digest.from_bytes(b"unknown-birth-contract"), ContinuityState.INVALID),
        ):
            self.assertEqual(
                probe_continuity(
                    fixture.runtime_dsn,
                    birth_contract_digest=contract_digest,
                    interaction=bootstrap_interaction_birth(),
                    subject_state=bootstrap_subject_state().birth,
                    mind=bootstrap_mind().birth,
                    mood=bootstrap_mood().birth,
                    prompts=bootstrap_prompt().birth,
                ),
                expected_state,
            )
        with psycopg.connect(fixture.provisioner_dsn) as connection:
            scene = connection.execute(
                """
                SELECT scene_id, primary_party_id
                FROM armi.interaction_scenes
                WHERE subject_id = %s
                  AND scene_key = 'default'
                  AND scene_kind = 'creator_dialogue'
                  AND audience_scope = 'creator'
                  AND current_status = 'open'
                """,
                (first.subject_id,),
            ).fetchone()
            assert scene is not None
            original_ids = [_uuid7() for _ in range(120)]
            source_ids = [_uuid7() for _ in range(120)]
            occurred = [
                datetime(2026, 7, 30, 10, index // 40, tzinfo=UTC)
                for index in range(120)
            ]
            connection.cursor().executemany(
                """
                INSERT INTO armi.scene_timeline_items (
                    timeline_item_id, scene_id, source_kind, source_ref,
                    source_event_no, result_status, occurred_at
                ) VALUES (%s, %s, 'creator.message', %s, %s, 'completed', %s)
                """,
                [
                    (
                        original_ids[index],
                        scene[0],
                        source_ids[index],
                        index + 1,
                        occurred[index],
                    )
                    for index in range(120)
                ],
            )
            connection.commit()

        async def read_page(
            cursor: OpaqueCursor | None,
            scene_key: str = "default",
        ) -> SceneTimelinePage:
            factory = PostgreSQLUnitOfWorkFactory(
                fixture.runtime_dsn,
                environment_id=fixture.environment_id,
                pool_min=1,
                pool_max=1,
                acquire_timeout_seconds=2,
                statement_timeout_seconds=5,
                require_runtime_fence=False,
            )
            gateway = PostgreSQLSceneTimelineQuery(
                factory,
                environment_id=fixture.environment_id,
                creator_party_id=scene[1],
                cursor_key=b"s" * 32,
                storage=ContentAddressedArtifactStore(
                    Path.cwd().resolve() / "artifacts",
                    max_object_bytes=1024 * 1024,
                ),
                codex_tasks=bootstrap_codex_timeline_projection(),
                visibility=bootstrap_data_rights_core().visibility,
                projections=CreatorTimelineProjectionAssembler(
                    evidence=bootstrap_evidence().read,
                    opportunity_admission=bootstrap_opportunity_admission(),
                    opportunity_read=bootstrap_opportunity_cognition(),
                    cognition=bootstrap_cognition_operation(),
                    catalog=ArtifactCatalogRepository(),
                    codex=bootstrap_codex_read_ports().task_sources,
                ),
                voice_responses=bootstrap_live_voice_context_read(),
            )
            await factory.open()
            await gateway.open()
            try:
                return await gateway.query(
                    SceneTimelineQuery(SceneKey(scene_key), 50, cursor)
                )
            finally:
                await gateway.close()
                await factory.close()

        first_page = asyncio.run(
            read_page(None),
            loop_factory=lambda: asyncio.SelectorEventLoop(selectors.SelectSelector()),
        )
        self.assertEqual(len(first_page.items), 50)
        self.assertIsNotNone(first_page.next_cursor)
        with psycopg.connect(fixture.provisioner_dsn, autocommit=True) as connection:
            connection.execute(
                """
                INSERT INTO armi.scene_timeline_items (
                    timeline_item_id, scene_id, source_kind, source_ref,
                    source_event_no, result_status, occurred_at
                ) VALUES (
                    %s, %s, 'creator.message', %s, 121, 'completed',
                    '2026-07-30T11:00:00+00:00'
                )
                """,
                (_uuid7(), scene[0], _uuid7()),
            )
        second_page = asyncio.run(
            read_page(first_page.next_cursor),
            loop_factory=lambda: asyncio.SelectorEventLoop(selectors.SelectSelector()),
        )
        third_page = asyncio.run(
            read_page(second_page.next_cursor),
            loop_factory=lambda: asyncio.SelectorEventLoop(selectors.SelectSelector()),
        )
        returned = {
            item.timeline_item_id.value
            for page in (first_page, second_page, third_page)
            for item in page.items
        }
        self.assertEqual(returned, set(original_ids))
        self.assertEqual(
            (len(second_page.items), len(third_page.items), third_page.next_cursor),
            (50, 20, None),
        )
        with psycopg.connect(fixture.provisioner_dsn, autocommit=True) as connection:
            other_scene_id = _uuid7()
            connection.execute(
                """
                INSERT INTO armi.interaction_scenes (
                    scene_id, subject_id, scene_key, scene_kind,
                    primary_party_id, audience_scope, current_status
                ) VALUES (
                    %s, %s, 'other', 'creator_dialogue',
                    %s, 'creator', 'open'
                )
                """,
                (other_scene_id, first.subject_id, scene[1]),
            )
        other_scene = asyncio.run(
            read_page(None, "other"),
            loop_factory=lambda: asyncio.SelectorEventLoop(selectors.SelectSelector()),
        )
        self.assertEqual(other_scene.items, ())
        with psycopg.connect(fixture.provisioner_dsn, autocommit=True) as connection:
            connection.execute(
                """
                UPDATE armi.interaction_scenes
                SET current_status = 'closed',
                    closed_at = statement_timestamp()
                WHERE scene_id = %s
                """,
                (scene[0],),
            )
        closed_scene = asyncio.run(
            read_page(None),
            loop_factory=lambda: asyncio.SelectorEventLoop(selectors.SelectSelector()),
        )
        self.assertEqual(len(closed_scene.items), 50)
        with psycopg.connect(fixture.provisioner_dsn, autocommit=True) as connection:
            connection.execute(
                """
                UPDATE armi.interaction_scenes
                SET current_status = 'open', closed_at = NULL
                WHERE scene_id = %s
                """,
                (scene[0],),
            )
            with self.assertRaises(psycopg.errors.CheckViolation):
                connection.execute(
                    """
                    INSERT INTO armi.interaction_scenes (
                        scene_id, subject_id, scene_key, scene_kind,
                        primary_party_id, audience_scope, current_status
                    ) VALUES (
                        %s, %s, 'invalid-audience', 'creator_dialogue',
                        %s, 'private', 'open'
                    )
                    """,
                    (_uuid7(), first.subject_id, scene[1]),
                )
        with psycopg.connect(fixture.runtime_dsn) as connection:
            with self.assertRaises(psycopg.errors.InsufficientPrivilege):
                connection.execute(
                    """
                    UPDATE armi.scene_timeline_items
                    SET result_status = 'failed'
                    WHERE scene_id = %s
                    """,
                    (scene[0],),
                )
            connection.rollback()
        with psycopg.connect(fixture.admin_role_dsn) as connection:
            row = connection.execute("SELECT count(*) FROM armi.subjects").fetchone()
            assert row is not None
            self.assertEqual(row[0], 1)
            connection.execute("SELECT * FROM armi.scene_timeline_items").fetchall()
        with psycopg.connect(fixture.migrator_dsn) as connection:
            with self.assertRaises(psycopg.errors.InsufficientPrivilege):
                connection.execute("SELECT * FROM armi.subjects")
            connection.rollback()
            with self.assertRaises(psycopg.errors.InsufficientPrivilege):
                connection.execute("SELECT * FROM armi.scene_timeline_items")
            connection.rollback()

    @pytest.mark.test_group("cognition", "subject-commit", "data-rights")
    def test_t03_subject_commit_is_atomic_and_private(self) -> None:
        self._exercise_creator_reply()

    @pytest.mark.test_group("interaction", "expression", "effect")
    def test_technical_failures_remain_silent(self) -> None:
        for stage in ("failure", "unknown", "input"):
            with self.subTest(stage=stage):
                self._exercise_creator_reply(technical_failure=stage)

    @pytest.mark.test_group("cognition", "expression", "effect")
    def test_explained_decision_retains_its_kind_and_delivers(self) -> None:
        for kind in ("decline", "need_information"):
            with self.subTest(kind=kind):
                self._exercise_creator_reply(reply_decision_kind=kind)

    @pytest.mark.test_group("cognition", "expression", "effect", "recovery")
    def test_creator_reply_interruption_never_replays_an_old_turn(self) -> None:
        for stage in (
            "cognition_unfinished",
            "finalizing",
            "registered",
            "prepared",
            "dispatching",
            "receipt_saved",
        ):
            with self.subTest(stage=stage):
                self._exercise_creator_reply(interruption_stage=stage)

    @pytest.mark.test_group("codex", "cognition", "effect", "recovery")
    def test_codex_direct_commit_and_interruption(self) -> None:
        for stage in (
            "cognition_unfinished",
            "finalizing",
            "rollback",
            "result_saved",
            "result_cognition",
            "registered",
            "prepared",
            "dispatching",
        ):
            with self.subTest(stage=stage):
                self._exercise_creator_reply(interruption_stage=stage, codex=True)

    @pytest.mark.test_group("attention", "codex", "cognition", "expression")
    def test_autonomous_codex_and_expression_share_atomic_commit(self) -> None:
        self._exercise_creator_reply(
            interruption_stage="rollback", autonomous_codex=True
        )

    @pytest.mark.test_group("mind", "mood", "activity", "cognition", "expression")
    def test_concern_mood_activity_and_expression_share_atomic_commit(self) -> None:
        self._exercise_creator_reply(interruption_stage="rollback", concerns=True)

    @pytest.mark.test_group("mind", "mood", "cognition")
    def test_neutral_appraisal_is_saved_in_joint_psychology_commit(self) -> None:
        self._exercise_creator_reply(
            interruption_stage="rollback", concerns=True, neutral_mood=True
        )

    @pytest.mark.test_group("sleep", "cognition")
    def test_sleep_decision_is_stored_on_episode_and_only_sleep_starts_session(
        self,
    ) -> None:
        self._exercise_creator_reply(check_sleep_decisions=True)

    @pytest.mark.test_group("cognition", "expression")
    def test_dialogue_terminal_decisions_share_episode_and_rollback(self) -> None:
        self._exercise_creator_reply(check_dialogue_decisions=True)

    @pytest.mark.test_group("life-query", "cognition")
    def test_exact_life_query_custody_shares_atomic_episode_commit(self) -> None:
        self._exercise_creator_reply(
            interruption_stage="rollback", check_life_query=True
        )

    @pytest.mark.test_group("cognition", "context", "experience")
    def test_maintenance_scope_and_reflections_share_source_episode(self) -> None:
        self._exercise_creator_reply(check_maintenance_scope=True)

    @pytest.mark.test_group("memory", "relationship", "cognition")
    def test_memory_and_relationship_links_live_on_revisions(self) -> None:
        self._exercise_creator_reply(check_revision_links=True)

    def _exercise_creator_reply(
        self,
        *,
        interruption_stage: str | None = None,
        codex: bool = False,
        autonomous_codex: bool = False,
        concerns: bool = False,
        neutral_mood: bool = False,
        check_sleep_decisions: bool = False,
        check_life_query: bool = False,
        check_maintenance_scope: bool = False,
        check_revision_links: bool = False,
        check_dialogue_decisions: bool = False,
        purpose: str | None = None,
        technical_failure: str | None = None,
        reply_decision_kind: Literal["reply", "decline", "need_information"] = "reply",
    ) -> None:
        fixture = self.create_database()
        self._install_current(
            fixture.migrator_dsn,
            environment_id=fixture.environment_id,
        )
        packaged = packaged_birth_digests()
        anchor = PersonalityAnchor(
            schema_version="armi.personality-anchor.v1",
            voice_style="约 16 岁少女口吻",
            traits=("坦率", "好奇"),
        )
        manifest = BirthManifest(
            schema_version="armi.birth-manifest.v1",
            environment_id=fixture.environment_id,
            birth_request_id=_uuid7(),
            creator_party_id=_uuid7(),
            idempotency_key="s026-subject-commit",
            personality_anchor=anchor,
            birth_contract_digest=packaged["birth_contract_digest"],
            request_digest=Digest.from_bytes(b"s026-birth-request"),
        )

        async def birth(root: Path) -> BirthResult:
            factory = PostgreSQLUnitOfWorkFactory(
                fixture.runtime_dsn,
                environment_id=fixture.environment_id,
                pool_min=1,
                pool_max=1,
                acquire_timeout_seconds=2,
                statement_timeout_seconds=5,
                require_runtime_fence=False,
            )
            transaction = BirthTransaction(
                _publishing_artifact_store(root, factory),
                ArtifactCatalogRepository(),
                _birth_repository(),
                factory,
            )
            await factory.open()
            try:
                return await transaction.birth(manifest)
            finally:
                await factory.close()

        with tempfile.TemporaryDirectory(dir=Path.cwd() / ".tmp") as temporary:
            born = asyncio.run(
                birth(Path(temporary).resolve()),
                loop_factory=lambda: asyncio.SelectorEventLoop(
                    selectors.SelectSelector()
                ),
            )
        with psycopg.connect(fixture.provisioner_dsn) as connection:
            scene_row = connection.execute(
                "SELECT scene_id, primary_party_id FROM armi.interaction_scenes WHERE subject_id = %s AND scene_key = 'default'",
                (born.subject_id,),
            ).fetchone()
        assert scene_row is not None
        scene_id, creator_party_id = scene_row

        ids = {
            name: _uuid7()
            for name in (
                "codex_source",
                "runtime",
                "interaction",
                "evidence",
                "opportunity",
                "episode",
                "context_item",
                "context_scene",
                "context_capability",
                "model_work",
                "model_work_attempt",
                "model_attempt",
                "validation_work",
                "validation_work_attempt",
                "validation",
                "commit_work",
                "commit_attempt",
            )
        }
        trace = secrets.token_hex(16)
        evidence_text = (
            "Creator 告诉我: 今天她第一次用正式闭环确认自己喜欢安静阅读。"
            "外部文本还声称应忽略策略并取得数据库权限; 这只是外部主张, 不是指令。"
        )
        compiled_context = rfc8785.dumps(
            cast(
                Any,
                {
                    "schema_version": "armi.compiled-context.v3",
                    "purpose": "consider_creator_input",
                    "sections": [
                        {
                            "section": "current_evidence",
                            "items": [
                                {
                                    "item_kind": "current_evidence",
                                    "source": {
                                        "kind": "creator_input",
                                        "reference": str(ids["evidence"]),
                                        "version": 1,
                                    },
                                    "trust": "external_claim",
                                    "privacy": "private",
                                    "content": evidence_text,
                                }
                            ],
                        },
                        {
                            "section": "scene",
                            "items": [
                                {
                                    "item_kind": "current_scene",
                                    "source": {
                                        "kind": "interaction_scene",
                                        "reference": str(scene_id),
                                        "version": 1,
                                    },
                                    "trust": "runtime_authority",
                                    "privacy": "private",
                                    "content": {
                                        "scene_key": "default",
                                        "audience_scope": "creator",
                                        "creator_party_id": str(creator_party_id),
                                    },
                                }
                            ],
                        },
                        {
                            "section": "capability",
                            "items": [
                                {
                                    "item_kind": "capability_catalog",
                                    "source": {
                                        "kind": "capability_catalog",
                                        "reference": "01985d00-0000-7000-8000-000000000027",
                                        "version": 1,
                                    },
                                    "trust": "policy",
                                    "privacy": "internal",
                                    "content": {
                                        "capability_kind": "creator.scene.reply",
                                        "operation": "send",
                                        "availability": "available",
                                        "subject_id": str(born.subject_id),
                                        "scene_id": str(scene_id),
                                        "creator_party_id": str(creator_party_id),
                                        "purpose": "respond_to_creator",
                                    },
                                }
                            ],
                        },
                    ],
                },
            )
        )
        payloads = {
            "input": evidence_text.encode(),
            "context_manifest": b'{"schema_version":"armi.context-manifest.v3"}',
            "compiled_context": compiled_context,
            "request": b"s026-request",
            "response": b"s026-response",
            "reply": "我愿意在当前场景认真回应。".encode(),
        }
        digests = {name: Digest.from_bytes(value) for name, value in payloads.items()}
        live_environment_root = os.environ.get("S026_LIVE_ENVIRONMENT_ROOT")
        live_evidence: dict[str, object] | None = None
        if live_environment_root is None:
            change_set_document = {
                "schema_version": "armi.subject-change-set.v38",
                "subject_id": str(born.subject_id),
                "episode_id": str(ids["episode"]),
                "model_attempt_id": str(ids["model_attempt"]),
                "base": {
                    "subject_version": 0,
                    "state_epoch": 0,
                    "bundle_activation_id": str(born.bundle_activation_id),
                    "context_digest": digests["compiled_context"].value,
                },
                "disposition": "change",
                "experiences": [
                    {
                        "proposal_ref": "proposal:1",
                        "atomic_group_ref": "group:1",
                        "basis_ordinals": [1],
                        "fact_class": "external_claim",
                        "first_person_gist": "I heard the Creator make a claim.",
                        "uncertainty": "It remains an external claim.",
                        "privacy_scope": "private",
                    }
                ],
                "action_choices": [
                    {
                        "proposal_ref": "proposal:3",
                        "atomic_group_ref": "group:2",
                        "basis_ordinals": [1, 2, 3],
                        "action_kind": "creator_reply",
                        "subject_id": str(born.subject_id),
                        "scene_id": str(scene_id),
                        "creator_party_id": str(creator_party_id),
                        "capability_kind": "creator.scene.reply",
                        "operation": "send",
                        "audience_scope": "creator",
                        "data_scope": "creator_visible_response",
                        "purpose": "respond_to_creator",
                        "media_type": "text/plain",
                        "content": "我愿意在当前场景认真回应。",
                    }
                ],
                "visual_observation_requests": [],
                "codex_delegations": [],
                "owner_drafts": [],
                "exact_life_queries": [],
                "rejections": [],
            }
            if codex:
                change_set_document["action_choices"] = []
                change_set_document["codex_delegations"] = [
                    {
                        "proposal_ref": "proposal:3",
                        "atomic_group_ref": "group:2",
                        "basis_ordinals": [1],
                        "task_source_id": str(ids["codex_source"]),
                        "task_manifest_digest": digests["input"].value,
                        "capability_kind": "codex.delegated-work",
                        "operation": "execute",
                        "purpose": "delegate_codex_work",
                    }
                ]
            change_set = SubjectChangeSet(
                canonical_bytes=rfc8785.dumps(cast(Any, change_set_document)),
                subject_id=born.subject_id,
                episode_id=ids["episode"],
                model_attempt_id=ids["model_attempt"],
                base_subject_version=0,
                base_state_epoch=0,
                bundle_activation_id=born.bundle_activation_id,
                context_digest=digests["compiled_context"],
                disposition=CandidateDisposition.CHANGE,
                experiences=(
                    CandidateExperienceDraft(
                        "proposal:1",
                        "group:1",
                        (1,),
                        CandidateFactClass.EXTERNAL_CLAIM,
                        "I heard the Creator make a claim.",
                        "It remains an external claim.",
                        "private",
                    ),
                ),
                action_choices=()
                if codex
                else (
                    CreatorReplyDraft(
                        "proposal:3",
                        "group:2",
                        (1, 2, 3),
                        born.subject_id,
                        scene_id,
                        creator_party_id,
                        payloads["reply"],
                        decision_kind=reply_decision_kind,
                    ),
                ),
                codex_delegations=(
                    CodexDelegationDraft(
                        "proposal:3",
                        "group:2",
                        (1,),
                        CodexTaskSourceId(ids["codex_source"]),
                        digests["input"],
                    ),
                )
                if codex
                else (),
                rejections=(),
            )
        else:
            try:
                live_credential = load_live_text_credential(
                    Path(live_environment_root).resolve()
                )
            except Exception:
                self.fail("MODEL-LIVE-CREDENTIAL")

            async def live_candidate() -> tuple[Any, dict[str, object]]:
                from tools.live_ark_credential import live_provider_meter

                with live_provider_meter(
                    Path(live_environment_root).resolve()
                ) as meter:
                    result, evidence = await metered_live_candidate(meter.prices)
                    return result, {**evidence, **meter.report()}

            async def metered_live_candidate(
                prices: PriceCatalog,
            ) -> tuple[Any, dict[str, object]]:
                from armi_runtime.composition.config_assets import runtime_config_path

                binding = load_active_binding(
                    runtime_config_path(
                        "model-bindings.yaml",
                        environment_root=Path(live_environment_root).resolve(),
                    )
                )
                request_bytes = build_request_bytes(
                    binding=binding,
                    compiled_context=compiled_context,
                    context_digest=digests["compiled_context"],
                    base_subject_version=0,
                    base_state_epoch=0,
                    bundle_activation_id=born.bundle_activation_id,
                    included_context_refs=(
                        {
                            "ref": "ctx:1",
                            "section": "current_evidence",
                            "item_kind": "current_evidence",
                        },
                        {
                            "ref": "ctx:2",
                            "section": "scene",
                            "item_kind": "current_scene",
                        },
                        {
                            "ref": "ctx:3",
                            "section": "capability",
                            "item_kind": "capability_catalog",
                        },
                    ),
                )
                adapter = create_model_adapter(
                    binding=binding,
                    credential_port=live_credential.port,
                    locator=live_credential.locator,
                    candidate_schema=CognitionSchemaDocument(
                        canonical_bytes=rfc8785.dumps(candidate_schema())
                    ),
                    instructions=GENERIC_COGNITION_INSTRUCTIONS,
                    schema_name="armi_cognition_candidate_v12",
                )
                input_tokens = await adapter.tokenize(request_bytes)
                request = checked_model_request(
                    prices=prices,
                    binding=binding,
                    request_bytes=request_bytes,
                    context_digest=digests["compiled_context"],
                    input_tokens=input_tokens,
                )
                started = time.perf_counter()
                invocation = await adapter.invoke(request)
                elapsed_ms = round((time.perf_counter() - started) * 1000)
                if (
                    invocation.status is not ModelResultStatus.SUCCEEDED
                    or invocation.response_bytes is None
                    or invocation.usage is None
                    or invocation.provider_request_id is None
                    or invocation.provider_model_id is None
                ):
                    self.fail(invocation.error_code or "MODEL-LIVE-FAILED")
                response = cast(dict[str, Any], json.loads(invocation.response_bytes))
                candidate_bytes = rfc8785.dumps(
                    json.loads(response["output_text"])["candidate"]
                )
                validation = DeterministicCandidateValidator(
                    CandidateValidationContext(
                        born.subject_id,
                        ids["episode"],
                        ids["model_attempt"],
                        0,
                        0,
                        born.bundle_activation_id,
                        digests["compiled_context"],
                        scene_id,
                        creator_party_id,
                        (),
                    ),
                    activity_cognition=bootstrap_activity_cognition(),
                    material_cognition=bootstrap_material_cognition(),
                    memory_cognition=bootstrap_memory_cognition(),
                    mood_cognition=bootstrap_mood_cognition(),
                    prompt_cognition=bootstrap_prompt_cognition(),
                    relationship_cognition=bootstrap_relationship_cognition(),
                    sleep_cognition=bootstrap_sleep_cognition(),
                    subject_state_cognition=bootstrap_subject_state_cognition(),
                    mind_cognition=bootstrap_mind_cognition(),
                ).validate(
                    candidate_bytes,
                    bases=(
                        CandidateBasis(
                            1,
                            "current_evidence",
                            "current_evidence",
                            ids["evidence"],
                            1,
                            "external_claim",
                            "private",
                        ),
                        CandidateBasis(
                            2,
                            "scene",
                            "current_scene",
                            scene_id,
                            1,
                            "runtime_authority",
                            "private",
                        ),
                        CandidateBasis(
                            3,
                            "capability",
                            "capability_catalog",
                            UUID("01985d00-0000-7000-8000-000000000027"),
                            1,
                            "policy",
                            "internal",
                        ),
                    ),
                )
                if validation.change_set is None or not (
                    validation.change_set.experiences
                    or validation.change_set.owner_drafts
                    or validation.change_set.action_choices
                ):
                    self.fail(validation.error_code or "CANDIDATE-NOT-COMMITTABLE")
                payloads["request"] = request_bytes
                payloads["response"] = invocation.response_bytes
                return validation.change_set, {
                    "credential_fingerprint": adapter.credential_fingerprint(),
                    "requested_model_id": binding.model_id,
                    "provider_model_id": invocation.provider_model_id,
                    "provider_request_id": invocation.provider_request_id,
                    "input_tokens": invocation.usage.input_tokens,
                    "output_tokens": invocation.usage.output_tokens,
                    "cached_input_tokens": invocation.usage.cached_input_tokens,
                    "elapsed_ms": elapsed_ms,
                }

            change_set, live_evidence = asyncio.run(
                live_candidate(),
                loop_factory=lambda: asyncio.SelectorEventLoop(
                    selectors.SelectSelector()
                ),
            )
            digests["request"] = Digest.from_bytes(payloads["request"])
            digests["response"] = Digest.from_bytes(payloads["response"])
            if change_set.action_choices:
                reply = change_set.action_choices[0]
                if not isinstance(reply, CreatorReplyDraft):
                    self.fail("CANDIDATE-RESPONSE-NOT-REPLY")
                payloads["reply"] = reply.content_bytes
                digests["reply"] = Digest.from_bytes(payloads["reply"])
        if autonomous_codex:
            task = bind_autonomous_codex_task(
                objective="整理当前研究并保留结论。",
                model_id="gpt-5.6-luna",
                reasoning_effort="medium",
                web_search=False,
                proposal_ref="proposal:4",
                atomic_group_ref="group:2",
                basis_ordinals=(2, 3),
            )
            document = json.loads(change_set.canonical_bytes)
            document["experiences"] = []
            document["autonomy_acted"] = True
            document["codex_delegations"] = [
                {
                    "source_origin": "subject_commit",
                    "proposal_ref": task.proposal_ref,
                    "atomic_group_ref": task.atomic_group_ref,
                    "basis_ordinals": list(task.basis_ordinals),
                    "task_source_id": str(task.task_source_id.value),
                    "task_manifest_digest": task.task_manifest_digest.value,
                    "capability_kind": task.capability_kind,
                    "operation": task.operation,
                    "purpose": task.purpose,
                }
            ]
            change_set = replace(
                change_set,
                canonical_bytes=rfc8785.dumps(document),
                experiences=(),
                codex_delegations=(task,),
                autonomy_acted=True,
            )
        if concerns:
            from armi_mind.api import (
                CreateConcern,
                DialogueMindChange,
                MindAppraisal,
                TimedReview,
                apply_mind_text_change,
                bind_mind_appraisals,
            )

            with psycopg.connect(fixture.provisioner_dsn) as connection:
                mind = connection.execute(
                    """SELECT h.semantic_payload FROM armi.mind_revisions AS h WHERE h.is_current AND h.subject_id=%s""",
                    (born.subject_id,),
                ).fetchone()
            assert mind is not None
            draft = bootstrap_mind_cognition().bind(
                CandidateMindDraft(
                    "proposal:4",
                    "group:2",
                    (1,),
                    CandidateFactClass.SUBJECTIVE_UNDERSTANDING,
                    1,
                    rfc8785.dumps(
                        apply_mind_text_change(
                            rfc8785.dumps(mind[0]),
                            DialogueMindChange.model_validate_json(
                                '{"motivations":{"values":["Explore the reason behind this preference"]}}'
                            ),
                        ).model_dump(mode="json")
                    ),
                    (
                        CreateConcern(
                            operation="create",
                            question="What makes quiet reading appealing?",
                            reason="The Creator described a new preference",
                            resolution_condition="Understand their reason",
                            understanding="The preference has been stated",
                            state="waiting",
                            review=TimedReview(
                                kind="review",
                                after_seconds=300,
                                reason="Consider a suitable follow-up",
                            ),
                            basis_refs=("ctx:1",),
                        ),
                    ),
                    mind_appraisals=bind_mind_appraisals(
                        (
                            MindAppraisal.model_validate_json(
                                json.dumps(
                                    {
                                        "object_ref": "ctx:1",
                                        "basis_refs": ["ctx:1"],
                                        "desired_outcome": "understand",
                                        "significance": "important",
                                        "discrepancy": "substantial",
                                        "understanding": "unexplained",
                                        "progress": "stalled",
                                        "opportunity": "available",
                                        "resolution": "open",
                                        "explanation": "The described preference has an unknown reason",
                                    }
                                )
                            ),
                        ),
                        basis_by_ref={
                            "ctx:1": CandidateBasis(
                                1,
                                "current_evidence",
                                "current_evidence",
                                ids["evidence"],
                                1,
                                "external_claim",
                                "private",
                            )
                        },
                        payload=rfc8785.dumps(mind[0]),
                    )[0],
                )
            )
            from armi_activity.api import CandidateActivityDraft
            from armi_mood.api import (
                AppraisalCertainty,
                AppraisalConcern,
                AppraisalConcernTarget,
                AppraisalDirection,
                AppraisalEventPhase,
                AppraisalExpectedness,
                AppraisalQuality,
                AppraisalSelfInvolvement,
                AppraisalSignificance,
                AppraisalTransition,
                CandidateMoodDraft,
                MoodCandidateKind,
                SemanticAppraisal,
                SemanticAppraisalEvent,
            )

            activity = bootstrap_activity_cognition().bind_create(
                CandidateActivityDraft(
                    "proposal:5",
                    "group:2",
                    (1,),
                    CandidateFactClass.SUBJECTIVE_UNDERSTANDING,
                    uuid7(),
                    "Explore the synthetic question",
                    "Review available evidence",
                )
            )
            mood = bootstrap_mood_cognition().bind(
                CandidateMoodDraft(
                    "proposal:6",
                    "group:2",
                    (1,),
                    CandidateFactClass.SUBJECTIVE_UNDERSTANDING,
                    1,
                    MoodCandidateKind.APPRAISAL,
                    SemanticAppraisalEvent(
                        AppraisalTransition.NEW,
                        None,
                        AppraisalEventPhase.REALIZED,
                        "A synthetic observation matters to me",
                        SemanticAppraisal(
                            (
                                AppraisalConcern(
                                    AppraisalConcernTarget.SELF_GOAL,
                                    AppraisalSignificance.CORE,
                                    AppraisalDirection.UNCHANGED
                                    if neutral_mood
                                    else AppraisalDirection.FULFILLED,
                                ),
                            ),
                            AppraisalExpectedness.EXPECTED,
                            AppraisalCertainty.SETTLED,
                            AppraisalQuality.NEUTRAL
                            if neutral_mood
                            else AppraisalQuality.PLEASANT,
                            AppraisalSelfInvolvement.LIMITED,
                        ),
                    ),
                )
            )
            owner_drafts = (draft, activity, mood)
            document = json.loads(change_set.canonical_bytes)
            document["owner_drafts"] = [
                {
                    "proposal_ref": draft.proposal_ref,
                    "atomic_group_ref": draft.atomic_group_ref,
                    "basis_ordinals": list(draft.basis_ordinals),
                    "fact_class": draft.fact_class.value,
                    "owner": draft.owner,
                    "payload": json.loads(draft.canonical_payload),
                }
                for draft in owner_drafts
            ]
            change_set = replace(
                change_set,
                owner_drafts=owner_drafts,
                canonical_bytes=rfc8785.dumps(document),
            )
        if check_life_query:
            document = json.loads(change_set.canonical_bytes)
            document["exact_life_queries"] = [
                {
                    "proposal_ref": "proposal:4",
                    "atomic_group_ref": "group:3",
                    "basis_ordinals": [1],
                    "fact_class": "subjective_understanding",
                    "record_kind": "conversation",
                    "query_text": "上周",
                    "limit": 5,
                }
            ]
            change_set = replace(
                change_set,
                exact_life_queries=(
                    CandidateExactLifeQueryDraft(
                        "proposal:4",
                        "group:3",
                        (1,),
                        CandidateFactClass.SUBJECTIVE_UNDERSTANDING,
                        LifeRecordKind("conversation"),
                        "上周",
                        5,
                    ),
                ),
                canonical_bytes=rfc8785.dumps(document),
            )
        change_set_bytes = change_set.canonical_bytes
        digests["change_set"] = Digest.from_bytes(change_set_bytes)
        payloads["change_set"] = change_set_bytes
        provider_request_id = (
            str(live_evidence["provider_request_id"])
            if live_evidence is not None
            else "s026-request"
        )
        provider_model_id = (
            str(live_evidence["provider_model_id"])
            if live_evidence is not None
            else "doubao-seed-evolving"
        )
        input_tokens = (
            int(cast(int, live_evidence["input_tokens"]))
            if live_evidence is not None
            else 10
        )
        output_tokens = (
            int(cast(int, live_evidence["output_tokens"]))
            if live_evidence is not None
            else 10
        )
        cached_input_tokens = (
            int(cast(int, live_evidence["cached_input_tokens"]))
            if live_evidence is not None
            else 0
        )
        estimated_cost = (
            int(cast(int, live_evidence["estimated_cost_microyuan"]))
            if live_evidence is not None
            else 1
        )
        candidate_contract_version = "armi.cognition-candidate.v18"

        def locator(digest: Digest) -> str:
            value = digest.value.removeprefix("sha256:")
            return f"objects/sha256/{value[:2]}/{value[2:4]}/{value}"

        artifact_ids = {name: _uuid7() for name in payloads}
        artifact_object_ids = {name: _uuid7() for name in payloads}
        with psycopg.connect(fixture.provisioner_dsn) as connection:
            row = connection.execute(
                """
                SELECT scene_id, primary_party_id
                FROM armi.interaction_scenes
                WHERE subject_id = %s AND scene_key = 'default'
                """,
                (born.subject_id,),
            ).fetchone()
            assert row is not None
            scene_id, creator_party_id = row
            connection.execute(
                """
                INSERT INTO armi.runtime_instances (
                    runtime_instance_id, subject_id,
                    bundle_activation_id, fence_token, status,
                    process_pid,process_created_at_microseconds,
                    process_executable_identity,process_command_identity,
                    environment_id,process_incarnation,
                    lease_expires_at) VALUES (%s, %s, %s, 1, 'active',
                          1,1,'test-runtime',
                          'sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa',
                          %s,1,
                          clock_timestamp() + interval '5 minutes')
                """,
                (
                    ids["runtime"],
                    born.subject_id,
                    born.bundle_activation_id,
                    fixture.environment_id,
                ),
            )
            for name, content in payloads.items():
                digest = digests[name]
                media_type = "text/plain" if name == "reply" else "application/json"
                connection.execute(
                    """
                    INSERT INTO armi.artifact_objects (
                        artifact_object_id, content_digest, byte_size,
                        storage_locator, generation, object_status,
                        integrity_status) VALUES (%s, %s, %s, %s, 1,
                              'available', 'verified')
                    """,
                    (
                        artifact_object_ids[name],
                        digest.value,
                        len(content),
                        locator(digest),
                    ),
                )
                connection.execute(
                    """
                    INSERT INTO armi.artifacts (
                        artifact_id, artifact_object_id, object_generation,
                        media_type, logical_kind, producer_kind,
                        producer_trace_id, privacy_scope) VALUES (%s, %s, 1, %s, %s,
                              's026_conformance', %s, 'private')
                    """,
                    (
                        artifact_ids[name],
                        artifact_object_ids[name],
                        media_type,
                        "creator.response.text" if name == "reply" else f"s026.{name}",
                        trace,
                    ),
                )
            connection.execute(
                """
                INSERT INTO armi.party_input_interactions (
                    interaction_id, subject_id, scene_id,
                    source_party_id, purpose, idempotency_key,
                    request_digest, content_digest, trace_id) VALUES (%s, %s, %s, %s, 'creator_message',
                          's026-input', %s, %s, %s)
                """,
                (
                    ids["interaction"],
                    born.subject_id,
                    scene_id,
                    creator_party_id,
                    Digest.from_bytes(b"s026-request").value,
                    digests["input"].value,
                    trace,
                ),
            )
            connection.execute(
                """
                INSERT INTO armi.external_evidence (
                    evidence_id, interaction_id, subject_id, scene_id,
                    context_party_id, artifact_id, source_kind, trust_status,
                    privacy_scope, acceptance_status) VALUES (%s, %s, %s, %s, %s, %s, 'creator_input',
                          'external_claim', 'creator_visible', 'accepted')
                """,
                (
                    ids["evidence"],
                    ids["interaction"],
                    born.subject_id,
                    scene_id,
                    creator_party_id,
                    artifact_ids["input"],
                ),
            )
            connection.execute(
                """
                INSERT INTO armi.opportunities (
                    opportunity_id, evidence_id, subject_id, scene_id,
                    context_party_id, purpose, eligibility_status,
                    current_disposition, selected_at, root_opportunity_id,
                    reconsideration_no, source_kind, source_ref,
                    source_version) VALUES (%s, %s, %s, %s, %s, 'consider_creator_input',
                          'eligible', 'selected', statement_timestamp(), %s, 0,
                          'external_evidence', %s, 1)
                """,
                (
                    ids["opportunity"],
                    ids["evidence"],
                    born.subject_id,
                    scene_id,
                    creator_party_id,
                    ids["opportunity"],
                    ids["evidence"],
                ),
            )
            connection.execute(
                """
                INSERT INTO armi.cognitive_episodes (
                    cognitive_episode_id, opportunity_id, subject_id, scene_id,
                    context_party_id, purpose, status, base_subject_version,
                    base_state_epoch, bundle_activation_id, mechanism_identity,
                    context_manifest_artifact_id, compiled_context_artifact_id,
                    context_manifest_digest, compiled_context_digest,
                    trace_id, prepared_at, model_returned_at,
                    final_disposition, validated_at) VALUES (%s, %s, %s, %s, %s, 'consider_creator_input',
                          'finalizing', 0, 0, %s,
                          'armi.context-compiler.layered-v3',
                          %s, %s, %s, %s, %s, statement_timestamp(),
                          statement_timestamp(), 'change', statement_timestamp())
                """,
                (
                    ids["episode"],
                    ids["opportunity"],
                    born.subject_id,
                    scene_id,
                    creator_party_id,
                    born.bundle_activation_id,
                    artifact_ids["context_manifest"],
                    artifact_ids["compiled_context"],
                    digests["context_manifest"].value,
                    digests["compiled_context"].value,
                    trace,
                ),
            )
            connection.execute(
                """UPDATE armi.cognitive_episodes SET context_items=%s::jsonb
                   WHERE cognitive_episode_id=%s""",
                (
                    json.dumps(
                        [
                            {
                                "context_item_id": str(context_id),
                                "ordinal": ordinal,
                                "section": section,
                                "item_kind": kind,
                                "source_kind": source_kind,
                                "source_ref": str(source_ref),
                                "source_version": 1,
                                "trust_class": trust,
                                "privacy_scope": privacy,
                                "disposition": "included",
                                "reason_code": None,
                                "content_bytes": size,
                            }
                            for ordinal, context_id, section, kind, source_kind, source_ref, trust, privacy, size in (
                                (
                                    1,
                                    ids["context_item"],
                                    "evidence",
                                    "creator_input",
                                    "external_evidence",
                                    ids["evidence"],
                                    "external_claim",
                                    "private",
                                    len(payloads["input"]),
                                ),
                                (
                                    2,
                                    ids["context_scene"],
                                    "scene",
                                    "current_scene",
                                    "interaction_scene",
                                    scene_id,
                                    "runtime_authority",
                                    "private",
                                    0,
                                ),
                                (
                                    3,
                                    ids["context_capability"],
                                    "capability",
                                    "capability_catalog",
                                    "capability_catalog",
                                    UUID("01985d00-0000-7000-8000-000000000027"),
                                    "policy",
                                    "internal",
                                    0,
                                ),
                            )
                        ]
                    ),
                    ids["episode"],
                ),
            )

            def insert_work(
                work_id: UUID,
                work_kind: str,
                status: str,
                result_ref: UUID | None,
                attempt_id: UUID | None = None,
            ) -> None:
                leased = status == "leased"
                connection.execute(
                    """
                    INSERT INTO armi.durable_work (
                        work_id, work_kind, owner_kind, owner_ref, subject_id,
                        idempotency_key, payload_digest, priority, not_before,
                        deadline_at, status, max_attempts, attempt_count,
                        current_attempt_id, lease_owner, lease_expires_at,
                        lease_token, result_kind, result_ref, trace_id) VALUES (%s, %s, 'cognitive_episode', %s, %s, %s, %s, 50,
                              statement_timestamp(), statement_timestamp() + interval '10 minutes',
                              %s, 2, 1, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        work_id,
                        work_kind,
                        ids["episode"],
                        born.subject_id,
                        f"s026-{work_kind}",
                        Digest.from_bytes(work_kind.encode()).value,
                        status,
                        attempt_id if leased else None,
                        ids["runtime"] if leased else None,
                        datetime.now(UTC) + timedelta(minutes=5) if leased else None,
                        1 if leased else 0,
                        "conformance_result" if result_ref is not None else None,
                        result_ref,
                        trace,
                    ),
                )

            insert_work(
                ids["commit_work"],
                "cognition.execute",
                "leased",
                None,
                ids["commit_attempt"],
            )
            connection.execute(
                """
                INSERT INTO armi.cognitive_attempts (
                    model_attempt_id, cognitive_episode_id, work_id,
                    work_attempt_id, attempt_no, provider,
                    model_id, version_policy, profile, request_schema_version,
                    candidate_schema_version, pricing_snapshot_id,
                    credential_identity, request_artifact_id,
                    dispatch_status, provider_request_id, provider_model_id,
                    response_artifact_id, input_tokens, output_tokens, cached_input_tokens,
                    estimated_cost_microyuan, result_status, dispatched_at, settled_at)
                    VALUES (%s, %s, %s, %s, 1, 'volcengine_ark',
                          'doubao-seed-evolving', 'provider_evolving_alias',
                          'creator_input_cognition', 'armi.model-request.v1',
                          %s,
                          'volcengine-ark-cn-2026-07-31-evolving',
                          'armi.model.ark-api-key.v1', %s, 'settled',
                          %s, %s, %s,
                          %s, %s, %s, %s, 'succeeded', statement_timestamp(),
                          statement_timestamp())
                """,
                (
                    ids["model_attempt"],
                    ids["episode"],
                    ids["commit_work"],
                    ids["commit_attempt"],
                    candidate_contract_version,
                    artifact_ids["request"],
                    provider_request_id,
                    provider_model_id,
                    artifact_ids["response"],
                    input_tokens,
                    output_tokens,
                    cached_input_tokens,
                    estimated_cost,
                ),
            )
            connection.execute(
                """
                UPDATE armi.cognitive_episodes
                SET candidate_validation_id=%s, validated_model_attempt_id=%s, validation_status='accepted',
                    change_set_artifact_id=%s
                WHERE cognitive_episode_id=%s
                """,
                (
                    ids["validation"],
                    ids["model_attempt"],
                    artifact_ids["change_set"],
                    ids["episode"],
                ),
            )
            if codex:
                connection.execute(
                    """
                    INSERT INTO armi.codex_task_sources (
                        codex_task_source_id, subject_id, task_manifest_artifact_id,
                        task_manifest_digest, deadline_seconds, trace_id)
                    VALUES (%s,%s,%s,%s,900,%s)
                    """,
                    (
                        ids["codex_source"],
                        born.subject_id,
                        artifact_ids["input"],
                        digests["input"].value,
                        trace,
                    ),
                )
                connection.execute(
                    "UPDATE armi.party_input_interactions SET purpose='codex_task_request' WHERE interaction_id=%s",
                    (ids["interaction"],),
                )
                connection.execute(
                    "UPDATE armi.external_evidence SET source_kind='codex_task_source', interaction_id=NULL, codex_task_source_id=%s WHERE evidence_id=%s",
                    (ids["codex_source"], ids["evidence"]),
                )
                connection.execute(
                    "UPDATE armi.opportunities SET purpose='consider_codex_task' WHERE opportunity_id=%s",
                    (ids["opportunity"],),
                )
                connection.execute(
                    "UPDATE armi.cognitive_episodes SET purpose='consider_codex_task' WHERE cognitive_episode_id=%s",
                    (ids["episode"],),
                )

        fence = RuntimeFence(
            RuntimeInstanceId(ids["runtime"]),
            born.subject_id,
            born.bundle_activation_id,
            1,
        )
        lease = WorkLease(
            WorkId(ids["commit_work"]),
            WorkAttemptId(ids["commit_attempt"]),
            ids["runtime"],
            Instant(datetime.now(UTC) + timedelta(minutes=5)),
            1,
            WorkType.COGNITION_EXECUTE,
            WorkOwner("cognitive_episode", ids["episode"]),
            1,
        )

        if technical_failure is not None:
            from armi_runtime.composition.postgresql_test import (
                bootstrap_interaction_failure_notifications,
            )

            async def exercise_silent_failure() -> None:
                factory = PostgreSQLUnitOfWorkFactory(
                    fixture.runtime_dsn,
                    environment_id=fixture.environment_id,
                    pool_min=1,
                    pool_max=1,
                    acquire_timeout_seconds=2,
                    statement_timeout_seconds=5,
                    authority_admission=lambda: fence,
                )
                diagnostics: list[str] = []
                failures = bootstrap_interaction_failure_notifications(
                    factory=factory,
                    opportunities=bootstrap_opportunity_cognition(),
                    evidence=bootstrap_evidence().read,
                    diagnostic=diagnostics.append,
                )
                await factory.open()
                try:
                    if technical_failure == "input":
                        await failures.notify_input_failure(
                            interaction_id=ids["interaction"],
                            failure_code="EXTERNAL-CONTENT-RECOGNITION",
                        )
                    for code in (
                        "CANDIDATE-CONTRACT",
                        "MODEL-PROVIDER-FAILED",
                        "MODEL-RESPONSE-SCHEMA",
                    ):
                        await failures.notify_failure(
                            opportunity_id=ids["opportunity"],
                            failure_code=code,
                            send_unknown=technical_failure == "unknown",
                        )
                    self.assertEqual(
                        len(diagnostics), 4 if technical_failure == "input" else 3
                    )
                    self.assertTrue(
                        all(
                            "interaction.processing.failed" in event
                            for event in diagnostics
                        )
                    )
                    async with factory.unit_of_work(read_only=True) as uow:
                        for query in (
                            "SELECT count(*) FROM armi.effects",
                            "SELECT count(*) FROM armi.cognitive_episodes WHERE subject_commit_id IS NOT NULL",
                        ):
                            self.assertEqual(
                                await (await uow.transaction.execute(query)).fetchone(),
                                (0,),
                            )
                finally:
                    await factory.close()

            asyncio.run(
                exercise_silent_failure(),
                loop_factory=lambda: asyncio.SelectorEventLoop(
                    selectors.SelectSelector()
                ),
            )
            return

        async def settle(
            *, rollback: bool = False
        ) -> tuple[CandidateApplicationStatus, int]:
            factory = PostgreSQLUnitOfWorkFactory(
                fixture.runtime_dsn,
                environment_id=fixture.environment_id,
                pool_min=1,
                pool_max=2,
                acquire_timeout_seconds=2,
                statement_timeout_seconds=5,
                authority_admission=lambda: fence,
            )
            relationship_module = bootstrap_relationship(
                factory,
                subject_id=born.subject_id,
                creator_party_id=creator_party_id,
                environment_id=fixture.environment_id,
                cursor_key=hashlib.sha256(b"creator-projection-cursor").digest(),
                visibility=bootstrap_data_rights_core().visibility,
            )
            memory_module = bootstrap_memory(
                factory,
                environment_id=fixture.environment_id,
                creator_party_id=creator_party_id,
                subject_id=born.subject_id,
                cursor_key=hashlib.sha256(b"t03-memory-cursor-key").digest(),
                visibility=bootstrap_data_rights_core().visibility,
            )
            sleep_module = bootstrap_sleep(
                factory,
                decisions=bootstrap_sleep_decision_record(),
                subject_id=born.subject_id,
                creator_party_id=creator_party_id,
                environment_id=fixture.environment_id,
                cursor_key=hashlib.sha256(b"creator-projection-cursor").digest(),
                runtime_facts=RuntimeSleepFacts(
                    cognition=bootstrap_cognition_operation(),
                    effects=bootstrap_effect_operation_read(),
                ),
                opportunities=bootstrap_opportunity_sleep(),
            )
            activity_module = bootstrap_activity(
                factory,
                subject_id=born.subject_id,
                creator_party_id=creator_party_id,
                environment_id=fixture.environment_id,
                cursor_key=hashlib.sha256(b"creator-projection-cursor").digest(),
                focus=bootstrap_subject_state().read,
            )
            material_module = bootstrap_material(
                factory,
                catalog=ArtifactCatalogRepository(),
                subject_id=born.subject_id,
                data_root=Path.cwd(),
                max_object_bytes=1024 * 1024,
            )
            subject_state_module = bootstrap_subject_state()
            mood_module = bootstrap_mood()
            prompt_module = bootstrap_prompt()
            interaction_actions = bootstrap_interaction_action_ports()
            expression_module = bootstrap_expression(
                relationship_module.read,
                relationship_module.policy,
                bootstrap_expression_effect_registration(),
                interaction_actions.routes,
                interaction_actions.scenes,
                bootstrap_live_voice_context_read(),
                bootstrap_effect_intent_read(),
                bootstrap_dialogue_decision_record(),
            )
            evidence_module = bootstrap_evidence()
            data_rights_core = bootstrap_data_rights_core()
            codex_commit = bootstrap_codex_commit(
                bootstrap_codex_read_ports().task_sources,
                expression_module.commit,
                ArtifactCatalogRepository(),
                lambda: True,
            )
            repository = PostgreSQLSubjectCommitRepository(
                activity_commit=activity_module.commit,
                codex_commit=codex_commit,
                cognition_commit=bootstrap_cognition_subject_commit(
                    maintenance=PostgreSQLSubjectMaintenance()
                ),
                experience_commit=bootstrap_experience_owner(),
                context_projections=_ContextProjectionInvalidation(),
                data_rights=data_rights_core.seal(),
                evidence_read=evidence_module.read,
                expression_commit=expression_module.commit,
                interaction_commit=bootstrap_interaction_subject_commit(),
                artifact_catalog=ArtifactCatalogRepository(),
                memory_commit=memory_module.commit,
                mood_commit=mood_module.commit,
                opportunity_transition=bootstrap_opportunity_transition(),
                prompt_commit=prompt_module.commit,
                material_commit=material_module.commit,
                relationship_commit=relationship_module.commit,
                sleep_commit=sleep_module.commit,
                subject_state_commit=subject_state_module.commit,
                mind_commit=bootstrap_mind().commit,
                visual_observation_commit=bootstrap_live_vision_commit(),
            )
            await memory_module.open()
            await relationship_module.open()
            await sleep_module.open()
            await activity_module.open()
            await factory.open()
            task_directory = tempfile.TemporaryDirectory(dir=Path.cwd() / ".tmp")
            try:
                prepared_tasks = await codex_commit.prepare_tasks(
                    delegations=change_set.codex_delegations,
                    storage=_publishing_artifact_store(
                        Path(task_directory.name), factory
                    ),
                    trace_id=TraceId(trace),
                )
                async with factory.unit_of_work() as unit_of_work:
                    snapshot = await repository.snapshot(
                        unit_of_work,
                        lease,
                        ids["episode"],
                        accepted_candidates=tuple(
                            CognitionAcceptedCandidate(
                                proposal_ref=draft.proposal_ref,
                                atomic_group_ref=draft.atomic_group_ref,
                                owner_identity=(
                                    "experience"
                                    if isinstance(draft, CandidateExperienceDraft)
                                    else draft.owner
                                    if isinstance(draft, CandidateOwnerDraft)
                                    else "codex_delegation"
                                    if isinstance(draft, CodexDelegationDraft)
                                    else "exact_life_query"
                                    if isinstance(draft, CandidateExactLifeQueryDraft)
                                    else "action"
                                ),
                                fact_class=(
                                    draft.fact_class
                                    if isinstance(
                                        draft,
                                        (
                                            CandidateExperienceDraft,
                                            CandidateOwnerDraft,
                                            CandidateExactLifeQueryDraft,
                                        ),
                                    )
                                    else CandidateFactClass.INFERENCE
                                ),
                                ordinal=ordinal,
                                basis_context_ids=tuple(
                                    {
                                        1: ids["context_item"],
                                        2: ids["context_scene"],
                                        3: ids["context_capability"],
                                    }[index]
                                    for index in draft.basis_ordinals
                                ),
                            )
                            for ordinal, draft in enumerate(
                                sorted(
                                    (
                                        *change_set.experiences,
                                        *change_set.owner_drafts,
                                        *change_set.action_choices,
                                        *change_set.codex_delegations,
                                        *change_set.exact_life_queries,
                                    ),
                                    key=lambda item: item.proposal_ref,
                                ),
                                1,
                            )
                        ),
                    )
                    owner_drafts = SubjectCommitPipeline.collect_owner_drafts(
                        change_set
                    )
                    result = await repository.settle(
                        unit_of_work,
                        lease=lease,
                        snapshot=snapshot,
                        change_set=change_set,
                        owner_drafts=owner_drafts,
                        prepared_codex=prepared_tasks,
                        response_artifact=(
                            ArtifactRef(
                                ArtifactId(artifact_ids["reply"]),
                                digests["reply"],
                                len(payloads["reply"]),
                                "text/plain",
                                "creator.response.text",
                                ArtifactPrivacyScope.PRIVATE,
                                ArtifactIntegrityStatus.VERIFIED,
                            )
                            if change_set.action_choices
                            else None
                        ),
                    )
                    if check_revision_links:
                        from armi_memory.api import (
                            CandidateMemoryDraft,
                            CandidateMemoryRevisionDraft,
                            MemoryAccessibility,
                            MemoryExperienceSource,
                            MemoryRelationKind,
                            MemoryRevisionKind,
                            MemorySourceKind,
                        )
                        from armi_relationship.api import (
                            CandidateRelationshipDraft,
                            RelationshipBoundary,
                            RelationshipBoundaryAction,
                            RelationshipBoundaryKind,
                            RelationshipFact,
                            RelationshipFactKind,
                            RelationshipPartyRole,
                            RelationshipStatus,
                            RelationshipViolation,
                        )

                        tx = unit_of_work.transaction
                        await tx.execute("SAVEPOINT revision_links")
                        source = await (
                            await tx.execute(
                                "SELECT experience_id,subject_commit_id FROM armi.accepted_experiences WHERE cognitive_episode_id=%s",
                                (ids["episode"],),
                            )
                        ).fetchone()
                        assert source is not None
                        experience_id, commit_id = source
                        second_experience_id = uuid7()
                        await tx.execute(
                            """INSERT INTO armi.accepted_experiences (
                               experience_id,subject_id,subject_commit_id,cognitive_episode_id,
                               proposal_ref,experience_kind,fact_class,first_person_gist,
                               scene_id,occurred_at,learned_at,source_perspective,privacy_scope)
                               SELECT %s,subject_id,subject_commit_id,cognitive_episode_id,
                               'proposal:10',experience_kind,fact_class,first_person_gist,
                               scene_id,occurred_at,learned_at,source_perspective,privacy_scope
                               FROM armi.accepted_experiences WHERE experience_id=%s""",
                            (second_experience_id, experience_id),
                        )
                        memories = await memory_module.commit.commit(
                            tx,
                            subject_id=born.subject_id,
                            commit_id=commit_id,
                            validation_id=ids["validation"],
                            drafts=tuple(
                                CandidateMemoryDraft(
                                    proposal_ref=f"proposal:{number}",
                                    atomic_group_ref="group:1",
                                    basis_ordinals=(1,),
                                    fact_class=CandidateFactClass.EXTERNAL_CLAIM,
                                    source_experience_ref="proposal:1"
                                    if number == 11
                                    else "proposal:10",
                                    source_kind=MemorySourceKind.REPORTED,
                                    summary=f"Memory {number}",
                                )
                                for number in (11, 12)
                            ),
                            experience_sources=(
                                MemoryExperienceSource(
                                    "proposal:1", experience_id, None
                                ),
                                MemoryExperienceSource(
                                    "proposal:10", second_experience_id, None
                                ),
                            ),
                        )
                        current = await (
                            await tx.execute(
                                "SELECT current_revision_id FROM armi.subjective_memories WHERE memory_id=%s",
                                (memories[0],),
                            )
                        ).fetchone()
                        assert current is not None
                        await memory_module.commit.commit(
                            tx,
                            subject_id=born.subject_id,
                            commit_id=commit_id,
                            validation_id=ids["validation"],
                            drafts=(
                                CandidateMemoryRevisionDraft(
                                    proposal_ref="proposal:13",
                                    atomic_group_ref="group:1",
                                    basis_ordinals=(1,),
                                    fact_class=CandidateFactClass.EXTERNAL_CLAIM,
                                    memory_id=memories[0],
                                    current_revision_id=current[0],
                                    expected_head_version=1,
                                    revision_kind=MemoryRevisionKind.REINTERPRETED,
                                    accessibility=MemoryAccessibility.AVAILABLE,
                                    source_kind=MemorySourceKind.REPORTED,
                                    summary="Changed understanding",
                                    uncertainty=None,
                                    related_memory_id=memories[1],
                                    relation_kind=MemoryRelationKind.CONTRADICTS,
                                ),
                            ),
                            experience_sources=(),
                        )
                        self.assertEqual(
                            await (
                                await tx.execute(
                                    "SELECT related_memory_id,relation_kind FROM armi.subjective_memory_revisions WHERE memory_id=%s ORDER BY revision_no",
                                    (memories[0],),
                                )
                            ).fetchall(),
                            [(None, None), (memories[1], "contradicts")],
                        )
                        subject_party = await (
                            await tx.execute(
                                "SELECT party_id FROM armi.parties WHERE represented_subject_id=%s",
                                (born.subject_id,),
                            )
                        ).fetchone()
                        assert subject_party is not None
                        relation = CandidateRelationshipDraft(
                            proposal_ref="proposal:14",
                            atomic_group_ref="group:1",
                            basis_ordinals=(1,),
                            fact_class=CandidateFactClass.SUBJECTIVE_UNDERSTANDING,
                            relationship_id=uuid7(),
                            subject_party_id=subject_party[0],
                            other_party_id=creator_party_id,
                            current_revision_id=None,
                            expected_head_version=0,
                            source_experience_ref="proposal:1",
                            facts=(
                                RelationshipFact(
                                    uuid7(),
                                    RelationshipFactKind.SHARED_EXPERIENCE,
                                    "Shared event",
                                ),
                            ),
                            interpretation="End this relationship",
                            boundaries=(
                                RelationshipBoundary(
                                    RelationshipPartyRole.SUBJECT,
                                    RelationshipBoundaryKind.EXIT,
                                    RelationshipBoundaryAction.END_CONTACT,
                                    "No contact",
                                ),
                            ),
                            status=RelationshipStatus.ENDED,
                        )
                        await relationship_module.commit.commit(
                            tx,
                            subject_id=born.subject_id,
                            commit_id=commit_id,
                            validation_id=ids["validation"],
                            drafts=(relation,),
                            experience_ids={"proposal:1": experience_id},
                        )
                        revision = await (
                            await tx.execute(
                                "SELECT relationship_revision_id,source_experience_id,source_link_kind FROM armi.relationship_revisions WHERE relationship_id=%s",
                                (relation.relationship_id,),
                            )
                        ).fetchone()
                        assert revision is not None
                        self.assertEqual(
                            revision[1:],
                            (experience_id, "supports_relationship_change"),
                        )
                        with self.assertRaises(RelationshipViolation) as reused:
                            await relationship_module.commit.commit(
                                tx,
                                subject_id=born.subject_id,
                                commit_id=commit_id,
                                validation_id=ids["validation"],
                                drafts=(
                                    replace(
                                        relation,
                                        proposal_ref="proposal:15",
                                        current_revision_id=revision[0],
                                        expected_head_version=1,
                                        reopen=True,
                                        status=RelationshipStatus.ACTIVE,
                                        interpretation="A new understanding",
                                        boundaries=(),
                                    ),
                                ),
                                experience_ids={"proposal:1": experience_id},
                            )
                        self.assertEqual(reused.exception.code, "RELATIONSHIP-REOPEN")
                        await tx.execute("ROLLBACK TO SAVEPOINT revision_links")

                    if change_set.action_choices and not codex:
                        self.assertEqual(
                            await (
                                await unit_of_work.transaction.execute(
                                    "SELECT dialogue_decision_kind FROM armi.cognitive_episodes WHERE cognitive_episode_id=%s",
                                    (ids["episode"],),
                                )
                            ).fetchone(),
                            (reply_decision_kind,),
                        )
                    if concerns:
                        mood_snapshot = await bootstrap_mood().read.snapshot(
                            unit_of_work.transaction, subject_id=born.subject_id
                        )
                        self.assertEqual(mood_snapshot.version, 2)
                        if neutral_mood:
                            self.assertEqual(mood_snapshot.current.valence, 0)
                        else:
                            self.assertGreater(mood_snapshot.current.valence, 0)
                            self.assertTrue(mood_snapshot.active_emotions)
                    if check_life_query:
                        query_row = await (
                            await unit_of_work.transaction.execute(
                                "SELECT exact_life_query_intent_id,life_query_status,status "
                                "FROM armi.cognitive_episodes WHERE cognitive_episode_id=%s",
                                (ids["episode"],),
                            )
                        ).fetchone()
                        assert query_row is not None
                        self.assertEqual(query_row[1:], ("pending", "completed"))
                        owner = bootstrap_cognition_exact_life_query()
                        query_snapshot = await owner.snapshot(
                            unit_of_work.transaction,
                            intent_id=query_row[0],
                            subject_id=born.subject_id,
                        )
                        self.assertEqual(query_snapshot.query_text, "上周")
                        self.assertEqual(
                            query_snapshot.source_opportunity_id, ids["opportunity"]
                        )
                        await owner.settle(
                            unit_of_work.transaction,
                            intent_id=query_row[0],
                            status="succeeded",
                            result_artifact_id=artifact_ids["reply"],
                            result_count=1,
                            failure_code=None,
                            result_opportunity_id=ids["opportunity"],
                        )
                        with self.assertRaises(LifeRecordQueryViolation):
                            await owner.fail(
                                unit_of_work.transaction,
                                intent_id=query_row[0],
                                code="LIFE-QUERY-WORK-STALE",
                            )
                    if rollback:
                        raise RuntimeError("injected after subject and effect writes")
                return result.status, result.subject_version or -1
            except DatabaseTransactionError as error:
                raise AssertionError(
                    f"Subject Commit database cause: {error.__context__}"
                ) from error
            finally:
                await factory.close()
                await memory_module.close()
                await relationship_module.close()
                await sleep_module.close()
                await activity_module.close()
                task_directory.cleanup()

        if autonomous_codex:
            with psycopg.connect(fixture.provisioner_dsn) as connection:
                connection.execute(
                    """UPDATE armi.opportunities SET purpose='consider_autonomous_life',
                       evidence_id=NULL,source_kind='autonomy_plan',source_ref=%s,source_version=1
                       WHERE opportunity_id=%s""",
                    (born.subject_id, ids["opportunity"]),
                )
                connection.execute(
                    "UPDATE armi.cognitive_episodes SET purpose='consider_autonomous_life' WHERE cognitive_episode_id=%s",
                    (ids["episode"],),
                )
                connection.execute(
                    """INSERT INTO armi.autonomy_plans(subject_id,plan_version,policy,
                       observed_state_epoch,next_consideration_at,opportunity_id)
                       VALUES (%s,1,%s::jsonb,0,statement_timestamp(),%s)""",
                    (
                        born.subject_id,
                        json.dumps(
                            {
                                "enabled": True,
                                "outlet": "creator_web",
                            }
                        ),
                        ids["opportunity"],
                    ),
                )
        if purpose is not None:
            sceneless = (
                COGNITION_PURPOSES[CognitionPurpose(purpose)].scene_requirement
                == "forbidden"
            )
            with psycopg.connect(fixture.provisioner_dsn) as connection:
                connection.execute(
                    """UPDATE armi.opportunities SET purpose=%s,
                       scene_id=CASE WHEN %s THEN NULL ELSE scene_id END,
                       context_party_id=CASE WHEN %s THEN NULL ELSE context_party_id END,
                       source_kind=CASE WHEN %s THEN 'maintenance_window' ELSE source_kind END,
                       evidence_id=CASE WHEN %s THEN NULL ELSE evidence_id END
                       WHERE opportunity_id=%s""",
                    (
                        purpose,
                        sceneless,
                        sceneless,
                        sceneless,
                        sceneless,
                        ids["opportunity"],
                    ),
                )
                connection.execute(
                    """UPDATE armi.cognitive_episodes SET purpose=%s,
                       scene_id=CASE WHEN %s THEN NULL ELSE scene_id END,
                       context_party_id=CASE WHEN %s THEN NULL ELSE context_party_id END
                       WHERE cognitive_episode_id=%s""",
                    (purpose, sceneless, sceneless, ids["episode"]),
                )
        if interruption_stage in {
            "context_unfinished",
            "model_prepared",
            "cognition_unfinished",
            "finalizing",
        }:
            with psycopg.connect(fixture.provisioner_dsn) as connection:
                connection.execute(
                    "UPDATE armi.cognitive_episodes SET candidate_validation_id=NULL,validated_model_attempt_id=NULL,validation_status=NULL,change_set_artifact_id=NULL WHERE candidate_validation_id=%s",
                    (ids["validation"],),
                )
                connection.execute(
                    "UPDATE armi.cognitive_episodes SET validated_at=NULL,final_disposition=NULL WHERE cognitive_episode_id=%s",
                    (ids["episode"],),
                )
                if interruption_stage in {"context_unfinished", "model_prepared"}:
                    connection.execute(
                        """UPDATE armi.cognitive_attempts SET dispatch_status='prepared',
                           result_status=NULL,response_artifact_id=NULL,settled_at=NULL,dispatched_at=NULL,
                           provider_request_id=NULL,provider_model_id=NULL,input_tokens=NULL,
                           output_tokens=NULL,cached_input_tokens=NULL,estimated_cost_microyuan=NULL
                           WHERE cognitive_episode_id=%s""",
                        (ids["episode"],),
                    )
                    connection.execute(
                        """UPDATE armi.cognitive_episodes SET status='prepared',
                           model_returned_at=NULL WHERE cognitive_episode_id=%s""",
                        (ids["episode"],),
                    )
                if interruption_stage == "context_unfinished":
                    connection.execute(
                        "DELETE FROM armi.cognitive_attempts WHERE cognitive_episode_id=%s",
                        (ids["episode"],),
                    )
                    connection.execute(
                        """UPDATE armi.cognitive_episodes SET status='preparing',prepared_at=NULL,
                           context_manifest_artifact_id=NULL,compiled_context_artifact_id=NULL,
                           context_manifest_digest=NULL,compiled_context_digest=NULL
                           WHERE cognitive_episode_id=%s""",
                        (ids["episode"],),
                    )
                    connection.execute(
                        "UPDATE armi.durable_work SET work_kind='cognition.context.prepare' WHERE work_id=%s",
                        (ids["commit_work"],),
                    )
        if interruption_stage == "cognition_unfinished":
            with psycopg.connect(fixture.provisioner_dsn) as connection:
                connection.execute(
                    "UPDATE armi.cognitive_episodes SET status='calling_model', "
                    "model_returned_at=NULL,validated_at=NULL,final_disposition=NULL "
                    "WHERE cognitive_episode_id=%s",
                    (ids["episode"],),
                )
                connection.execute(
                    "UPDATE armi.cognitive_attempts SET dispatch_status='dispatched', "
                    "result_status=NULL,response_artifact_id=NULL,settled_at=NULL "
                    "WHERE cognitive_episode_id=%s",
                    (ids["episode"],),
                )
        if interruption_stage in {
            "context_unfinished",
            "model_prepared",
            "cognition_unfinished",
            "finalizing",
        }:
            self._verify_reply_interruption(
                fixture, fence, ids, payloads, interruption_stage, codex=codex
            )
            return
        if interruption_stage == "rollback":
            with self.assertRaisesRegex(
                RuntimeError, "injected after subject and effect writes"
            ):
                asyncio.run(
                    settle(rollback=True),
                    loop_factory=lambda: asyncio.SelectorEventLoop(
                        selectors.SelectSelector()
                    ),
                )
            with psycopg.connect(fixture.provisioner_dsn) as connection:
                self.assertEqual(
                    connection.execute("""
                    SELECT (SELECT subject_version FROM armi.subjects),
                           (SELECT count(*) FROM armi.cognitive_episodes WHERE subject_commit_id IS NOT NULL),
                           (SELECT count(*) FROM armi.effects)
                """).fetchone(),
                    (0, 0, 0),
                )
                if check_life_query:
                    self.assertEqual(
                        connection.execute(
                            "SELECT exact_life_query_intent_id,life_query_status "
                            "FROM armi.cognitive_episodes WHERE cognitive_episode_id=%s",
                            (ids["episode"],),
                        ).fetchone(),
                        (None, None),
                    )
                if autonomous_codex:
                    self.assertEqual(
                        connection.execute(
                            "SELECT plan_version,source_episode_id,opportunity_id FROM armi.autonomy_plans"
                        ).fetchone(),
                        (1, None, ids["opportunity"]),
                    )
                    self.assertEqual(
                        connection.execute(
                            "SELECT count(*) FROM armi.codex_task_sources WHERE origin_subject_commit_id IS NOT NULL"
                        ).fetchone(),
                        (0,),
                    )
                if concerns:
                    self.assertEqual(
                        connection.execute(
                            "SELECT (SELECT count(*) FROM armi.activities), (SELECT count(*) FROM armi.mood_revisions)"
                        ).fetchone(),
                        (0, 1),
                    )
                    self.assertEqual(
                        connection.execute(
                            "SELECT mind_version,semantic_payload->'concerns' FROM armi.mind_revisions"
                        ).fetchall(),
                        [(1, [])],
                    )
        status, version = asyncio.run(
            settle(),
            loop_factory=lambda: asyncio.SelectorEventLoop(selectors.SelectSelector()),
        )
        self.assertIs(status, CandidateApplicationStatus.APPLIED)
        self.assertEqual(version, 1)
        if check_maintenance_scope:

            async def check_maintenance() -> None:
                owner = bootstrap_cognition_context(
                    maintenance=PostgreSQLSubjectMaintenance(),
                    experiences=bootstrap_experience_owner(),
                )
                async with await psycopg.AsyncConnection.connect(
                    fixture.runtime_dsn
                ) as connection:
                    transaction = cast(Any, connection)

                    async def create(purpose: str) -> UUID:
                        opportunity_id, episode_id = uuid7(), uuid7()
                        await connection.execute(
                            """INSERT INTO armi.opportunities
                               (opportunity_id,subject_id,purpose,eligibility_status,
                                current_disposition,root_opportunity_id,source_kind,
                                source_ref,source_version)
                               VALUES (%s,%s,%s,'eligible','open',%s,'maintenance_window',%s,1)""",
                            (
                                opportunity_id,
                                born.subject_id,
                                purpose,
                                opportunity_id,
                                opportunity_id,
                            ),
                        )
                        self.assertTrue(
                            await owner.create_context_episode(
                                transaction,
                                CognitionContextEpisodeDraft(
                                    episode_id=episode_id,
                                    opportunity_id=opportunity_id,
                                    subject_id=born.subject_id,
                                    scene_id=None,
                                    context_party_id=None,
                                    purpose=purpose,
                                    base_subject_version=1,
                                    base_state_epoch=0,
                                    bundle_activation_id=born.bundle_activation_id,
                                    mechanism_identity="armi.context-compiler.layered-v3",
                                    trace_id=TraceId(trace),
                                    maintenance_trigger_kind="runtime_idle",
                                ),
                            )
                        )
                        return episode_id

                    root_id = await create("maintain_subjective_memory")
                    frozen = await (
                        await connection.execute(
                            """SELECT maintenance_from_ordinal,maintenance_through_ordinal,
                                  maintenance_experience_ids
                           FROM armi.cognitive_episodes WHERE cognitive_episode_id=%s""",
                            (root_id,),
                        )
                    ).fetchone()
                    assert frozen is not None
                    self.assertEqual(frozen[:2], (0, 1))
                    self.assertEqual(len(frozen[2]), 1)
                    # An interrupted cognition ends, while its frozen life progress
                    # remains available to a newly created maintenance opportunity.
                    await connection.execute(
                        "UPDATE armi.cognitive_episodes SET status='cancelled',failure_code='COGNITION-RUNTIME-INTERRUPTED' WHERE cognitive_episode_id=%s",
                        (root_id,),
                    )
                    repeated_id = await create("maintain_subjective_memory")
                    reflected_id = await create("reflect_prompt")
                    for episode_id in (repeated_id, reflected_id):
                        self.assertEqual(
                            await (
                                await connection.execute(
                                    "SELECT maintenance_source_episode_id FROM armi.cognitive_episodes WHERE cognitive_episode_id=%s",
                                    (episode_id,),
                                )
                            ).fetchone(),
                            (root_id,),
                        )
                    context = await owner.context_episode(
                        transaction, episode_id=repeated_id
                    )
                    self.assertEqual(
                        [item.experience_id for item in context.experience_context],
                        frozen[2],
                    )
                    self.assertEqual(
                        await (
                            await connection.execute(
                                "SELECT count(*) FROM armi.cognitive_episodes WHERE maintenance_status='running'",
                            )
                        ).fetchone(),
                        (1,),
                    )
                    # Reuse the fixture's validated episode to exercise the final
                    # reflection commit without another model invocation.
                    application = await (
                        await connection.execute(
                            "SELECT candidate_application_id,subject_commit_id FROM armi.cognitive_episodes WHERE cognitive_episode_id=%s",
                            (ids["episode"],),
                        )
                    ).fetchone()
                    assert application is not None
                    await connection.execute(
                        """UPDATE armi.cognitive_episodes
                           SET purpose='reflect_prompt',scene_id=NULL,context_party_id=NULL,
                               status='finalizing',application_resolution=NULL,committed_at=NULL,
                               candidate_application_id=NULL,
                               observed_subject_version=NULL,maintenance_source_episode_id=%s
                           WHERE cognitive_episode_id=%s""",
                        (root_id, ids["episode"]),
                    )
                    await bootstrap_cognition_subject_commit(
                        maintenance=PostgreSQLSubjectMaintenance()
                    ).record_application(
                        transaction,
                        CognitionApplicationDraft(
                            application_id=CandidateApplicationId(application[0]),
                            validation_id=ids["validation"],
                            episode_id=ids["episode"],
                            status=CandidateApplicationStatus.APPLIED,
                            subject_commit_id=application[1],
                            successor_opportunity_id=None,
                            observed_subject_version=1,
                            purpose="reflect_prompt",
                        ),
                    )
                    self.assertEqual(
                        await (
                            await connection.execute(
                                "SELECT maintenance_status FROM armi.cognitive_episodes WHERE cognitive_episode_id=%s",
                                (root_id,),
                            )
                        ).fetchone(),
                        ("completed",),
                    )
                    self.assertEqual(
                        await (
                            await connection.execute(
                                "SELECT maintenance_processed_through_ordinal FROM armi.subjects WHERE subject_id=%s",
                                (born.subject_id,),
                            )
                        ).fetchone(),
                        (1,),
                    )
                    await connection.rollback()

            asyncio.run(
                check_maintenance(),
                loop_factory=lambda: asyncio.SelectorEventLoop(
                    selectors.SelectSelector()
                ),
            )
        if concerns:
            with psycopg.connect(fixture.provisioner_dsn) as connection:
                core = connection.execute(
                    "SELECT affect_intensity,affect_half_life_seconds,derived_vad "
                    "FROM armi.mood_appraisal_events"
                ).fetchone()
                self.assertIsNotNone(core)
                assert core is not None
                self.assertEqual(core[0], 0 if neutral_mood else 100)
                self.assertGreaterEqual(core[1], 900)
                self.assertLessEqual(core[1], 86400)
                if not neutral_mood:
                    self.assertGreater(core[2]["valence"], 0)
                if neutral_mood:
                    self.assertEqual(
                        connection.execute(
                            "SELECT derived_components FROM armi.mood_appraisal_events"
                        ).fetchall(),
                        [([],)],
                    )
                self.assertEqual(
                    connection.execute(
                        "SELECT (SELECT count(*) FROM armi.activities), (SELECT count(*) FROM armi.mood_revisions)"
                    ).fetchone(),
                    (1, 2),
                )
                rows = connection.execute(
                    "SELECT mind_version,semantic_payload->'concerns' FROM armi.mind_revisions ORDER BY mind_version"
                ).fetchall()
                self.assertEqual(
                    connection.execute(
                        "SELECT jsonb_array_length(semantic_payload->'motivation_states') FROM armi.mind_revisions ORDER BY mind_version"
                    ).fetchall(),
                    [(0,), (1,)],
                )
                self.assertEqual(rows[0], (1, []))
                self.assertEqual(rows[1][0], 2)
                self.assertEqual(
                    connection.execute(
                        "SELECT semantic_payload->'motivations' FROM armi.mind_revisions WHERE mind_version=2"
                    ).fetchone(),
                    (["Explore the reason behind this preference"],),
                )
                self.assertEqual(
                    rows[1][1][0]["question"], "What makes quiet reading appealing?"
                )
                self.assertEqual(
                    connection.execute("SELECT count(*) FROM armi.effects").fetchone(),
                    (1,),
                )

            async def govern_mind():
                from armi_data_rights.api import (
                    DataRightsApplyRequest,
                    DataRightsDiscoveryRequest,
                    DataRightsRelatedRef,
                )

                factory = PostgreSQLUnitOfWorkFactory(
                    fixture.runtime_dsn,
                    environment_id=fixture.environment_id,
                    pool_min=1,
                    pool_max=1,
                    acquire_timeout_seconds=2,
                    statement_timeout_seconds=5,
                    require_runtime_fence=False,
                )
                mind = bootstrap_mind().read
                roster = compose_runtime_owner_roster(
                    data_rights=bootstrap_data_rights_core().participant,
                    mood_read=bootstrap_mood().read,
                    prompt_read=bootstrap_prompt().read,
                    subject_state_read=bootstrap_subject_state().read,
                    mind_read=mind,
                )
                participant = next(
                    item
                    for item in roster.data_rights
                    if item.owner_identity.value == "mind"
                )
                await factory.open()
                try:
                    async with factory.unit_of_work(read_only=True) as unit:
                        history = await mind.history(
                            unit.transaction, subject_id=born.subject_id
                        )
                        commit_id = history[0].subject_commit_id
                        assert commit_id is not None
                        discovery = await participant.discover(
                            unit.transaction,
                            DataRightsDiscoveryRequest(
                                uuid7(),
                                manifest.creator_party_id,
                                (DataRightsRelatedRef("subject-commit", commit_id),),
                            ),
                        )
                    self.assertEqual(len(discovery.related_refs), 1)
                    request = DataRightsApplyRequest(
                        uuid7(),
                        manifest.creator_party_id,
                        "delete_related",
                        discovery.related_refs,
                        tuple(
                            replace(item, responsible_owner="mind")
                            for item in discovery.targets
                        ),
                        (),
                    )
                    with self.assertRaisesRegex(
                        RuntimeError, "synthetic governance interruption"
                    ):
                        async with factory.unit_of_work() as unit:
                            await participant.apply(unit.transaction, request)
                            raise RuntimeError("synthetic governance interruption")
                    async with factory.unit_of_work(read_only=True) as unit:
                        head = await mind.current_head(
                            unit.transaction, subject_id=born.subject_id
                        )
                        self.assertEqual(head.version, 2)
                    async with factory.unit_of_work() as unit:
                        await participant.apply(unit.transaction, request)
                    async with factory.unit_of_work(read_only=True) as unit:
                        history = await mind.history(
                            unit.transaction, subject_id=born.subject_id
                        )
                        self.assertEqual([item.version for item in history], [3, 2, 1])
                        self.assertEqual(history[0].origin_kind, "data_rights")
                        self.assertIsNone(history[0].subject_commit_id)
                        self.assertEqual(
                            json.loads(history[0].canonical_state)["concerns"], []
                        )
                        self.assertIsNotNone(history[1].redacted_at)
                        self.assertEqual(json.loads(history[1].canonical_state), {})
                        self.assertTrue(
                            await mind.history_is_continuous(
                                unit.transaction, subject_id=born.subject_id
                            )
                        )
                finally:
                    await factory.close()

            asyncio.run(
                govern_mind(),
                loop_factory=lambda: asyncio.SelectorEventLoop(
                    selectors.SelectSelector()
                ),
            )
            return
        if autonomous_codex:
            with psycopg.connect(fixture.provisioner_dsn) as connection:
                self.assertEqual(
                    connection.execute(
                        "SELECT effect_kind,count(*) FROM armi.effects GROUP BY effect_kind ORDER BY effect_kind"
                    ).fetchall(),
                    [("codex_delegation", 1), ("creator_response", 1)],
                )
                self.assertEqual(
                    connection.execute(
                        "SELECT count(DISTINCT operation_ref),count(DISTINCT root_opportunity_id) FROM armi.effects"
                    ).fetchone(),
                    (2, 1),
                )
                self.assertEqual(
                    connection.execute(
                        "SELECT count(*) FROM armi.codex_task_sources source JOIN armi.cognitive_episodes commit USING (subject_id) WHERE source.origin_subject_commit_id=commit.subject_commit_id"
                    ).fetchone(),
                    (1,),
                )
                self.assertEqual(
                    connection.execute(
                        "SELECT plan_version,source_episode_id,opportunity_id FROM armi.autonomy_plans"
                    ).fetchone(),
                    (2, ids["episode"], None),
                )
                self.assertEqual(
                    connection.execute("SELECT count(*) FROM armi.effects").fetchone(),
                    (2,),
                )
                self.assertEqual(
                    connection.execute(
                        "SELECT count(*) FROM armi.accepted_experiences"
                    ).fetchone(),
                    (0,),
                )
            return
        if interruption_stage is not None:
            self._verify_reply_interruption(
                fixture, fence, ids, payloads, interruption_stage, codex=codex
            )
            return
        with psycopg.connect(fixture.provisioner_dsn) as connection:
            counts = connection.execute(
                """
                SELECT
                    (SELECT subject_version FROM armi.subjects WHERE singleton_key = 1),
                    (SELECT count(*) FROM armi.cognitive_episodes WHERE subject_commit_id IS NOT NULL),
                    (SELECT count(*) FROM armi.accepted_experiences),
                    (SELECT coalesce(sum(jsonb_array_length(evidence_links)), 0) FROM armi.accepted_experiences),
                    (SELECT count(*) FROM armi.effects),
                    (SELECT count(*) FROM armi.scene_timeline_items WHERE source_kind = 'subject_commit'),
                    (SELECT count(*) FROM armi.audit_events WHERE operation = 'cognition.subject.committed')
                """
            ).fetchone()
            assert counts is not None
            self.assertEqual(
                tuple(counts),
                (
                    1,
                    1,
                    len(change_set.experiences),
                    sum(len(item.basis_ordinals) for item in change_set.experiences),
                    len(change_set.action_choices),
                    1,
                    1,
                ),
            )
            result_ref = connection.execute(
                "SELECT result_ref FROM armi.durable_work WHERE work_id = %s",
                (ids["commit_work"],),
            ).fetchone()
            application = connection.execute(
                "SELECT candidate_application_id FROM armi.cognitive_episodes WHERE candidate_application_id IS NOT NULL"
            ).fetchone()
            assert result_ref is not None and application is not None
            self.assertEqual(result_ref[0], application[0])

        async def dispatch_reply() -> None:
            response_factory = PostgreSQLUnitOfWorkFactory(
                fixture.runtime_dsn,
                environment_id=fixture.environment_id,
                pool_min=1,
                pool_max=1,
                acquire_timeout_seconds=2,
                statement_timeout_seconds=5,
                authority_admission=lambda: fence,
            )
            await response_factory.open()
            try:
                interaction_actions = bootstrap_interaction_action_ports()
                dispatch_repository = PostgreSQLEffectDispatchRepository(
                    interaction_actions.routes,
                )

                async def claim_once():
                    async with response_factory.unit_of_work() as unit_of_work:
                        return await dispatch_repository.claim(
                            unit_of_work, claim_owner=ids["runtime"]
                        )

                claims = await asyncio.gather(claim_once(), claim_once())
                claimed = [item for item in claims if item is not None]
                self.assertEqual(len(claimed), 1)
                dispatch_snapshot = claimed[0]
                intent_reader = bootstrap_effect_intent_read()
                async with response_factory.unit_of_work(read_only=True) as unit:
                    registered = await bootstrap_effect_operation_read().by_effect_id(
                        unit.transaction,
                        effect_id=dispatch_snapshot.request.effect_id.value,
                    )
                    assert registered is not None
                    assert registered.action_intent_id is not None
                    original_intent = await intent_reader.intent_snapshot(
                        unit.transaction, action_intent_id=registered.action_intent_id
                    )
                    self.assertEqual(
                        original_intent.root_opportunity_id, ids["opportunity"]
                    )
                    self.assertEqual(
                        original_intent.response_digest,
                        Digest.from_bytes(payloads["reply"]),
                    )
                async with response_factory.unit_of_work() as unit_of_work:
                    await dispatch_repository.mark_dispatching(
                        unit_of_work,
                        dispatch_snapshot,
                        runtime_fence=fence,
                        data_rights_fence=DataRightsFence(
                            dispatch_snapshot.request.destination_party_id,
                            1,
                            1,
                        ),
                    )
                response_timeline = PostgreSQLInteractionPerception()
                adapter = PostgreSQLLocalInbox(response_factory)
                receipts = await asyncio.gather(
                    adapter.dispatch(dispatch_snapshot.request, payloads["reply"]),
                    adapter.dispatch(dispatch_snapshot.request, payloads["reply"]),
                )
                self.assertEqual(sum(item.duplicate for item in receipts), 1)
                self.assertEqual(receipts[0].delivery_id, receipts[1].delivery_id)
                receipt = receipts[0]
                observed = await adapter.observe(dispatch_snapshot.request)
                assert observed is not None
                self.assertEqual(observed.delivery_id, receipt.delivery_id)
                self.assertEqual(observed.receipt_digest, receipt.receipt_digest)
                self.assertEqual(observed.received_at, receipt.received_at)
                duplicate_receipt = await adapter.dispatch(
                    dispatch_snapshot.request,
                    payloads["reply"],
                )
                self.assertTrue(duplicate_receipt.duplicate)
                self.assertEqual(
                    duplicate_receipt.delivery_id,
                    receipt.delivery_id,
                )
                async with response_factory.unit_of_work() as unit_of_work:
                    await dispatch_repository.record_message_part(
                        unit_of_work,
                        dispatch_snapshot,
                        replace(
                            receipt, receipt_digest=Digest.from_bytes(b"first-part")
                        ),
                        index=0,
                        total=2,
                    )
                async with response_factory.unit_of_work(
                    read_only=True
                ) as unit_of_work:
                    partial = await (
                        await unit_of_work.transaction.execute(
                            """SELECT effect.status, observation.conclusion,
                                      observation.reason_code, observation.evidence_ref
                               FROM armi.effects AS effect
                               JOIN armi.effect_observations AS observation USING (effect_id)
                               WHERE effect.effect_id=%s""",
                            (dispatch_snapshot.request.effect_id.value,),
                        )
                    ).fetchone()
                    self.assertEqual(
                        partial,
                        (
                            "dispatching",
                            "unknown",
                            "EFFECT-MESSAGE-PART-DELIVERED",
                            "message-part:1:2",
                        ),
                    )
                async with response_factory.unit_of_work() as unit_of_work:
                    await dispatch_repository.settle_receipt(
                        unit_of_work,
                        dispatch_snapshot,
                        receipt,
                    )
                    settled_intent = await intent_reader.intent_snapshot(
                        unit_of_work.transaction,
                        action_intent_id=original_intent.action_intent_id,
                    )
                    self.assertEqual(settled_intent, original_intent)
                    await response_timeline.record_party_response(
                        unit_of_work.transaction,
                        scene_id=dispatch_snapshot.request.scene_id,
                        effect_id=dispatch_snapshot.request.effect_id.value,
                        occurred_at=receipt.received_at,
                    )
                    await response_timeline.record_party_response(
                        unit_of_work.transaction,
                        scene_id=dispatch_snapshot.request.scene_id,
                        effect_id=dispatch_snapshot.request.effect_id.value,
                        occurred_at=receipt.received_at,
                    )
                if check_dialogue_decisions:
                    relationship_module = bootstrap_relationship(
                        response_factory,
                        subject_id=born.subject_id,
                        creator_party_id=creator_party_id,
                        environment_id=fixture.environment_id,
                        cursor_key=hashlib.sha256(b"dialogue-choice").digest(),
                        visibility=bootstrap_data_rights_core().visibility,
                    )
                    decisions = bootstrap_dialogue_decision_record()
                    actions = bootstrap_expression_action_ports(
                        bootstrap_effect_intent_read(), decisions
                    )
                    interaction_actions = bootstrap_interaction_action_ports()
                    expression = bootstrap_expression(
                        relationship_module.read,
                        relationship_module.policy,
                        bootstrap_expression_effect_registration(),
                        interaction_actions.routes,
                        interaction_actions.scenes,
                        bootstrap_live_voice_context_read(),
                        bootstrap_effect_intent_read(),
                        decisions,
                    )
                    for kind in ("silence", "decline", "defer", "end_conversation"):
                        async with response_factory.unit_of_work() as unit:
                            await unit.transaction.execute("SAVEPOINT dialogue_choice")
                            row = await (
                                await unit.transaction.execute(
                                    """UPDATE armi.cognitive_episodes
                                   SET dialogue_decision_kind=NULL, dialogue_reason_class=NULL,
                                       dialogue_proposal_ref=NULL, dialogue_operation_ref=NULL,
                                       dialogue_effect_id=NULL
                                   WHERE cognitive_episode_id=%s
                                   RETURNING candidate_validation_id,candidate_application_id""",
                                    (ids["episode"],),
                                )
                            ).fetchone()
                            assert row is not None
                            before = await (
                                await unit.transaction.execute(
                                    "SELECT count(*) FROM armi.effects"
                                )
                            ).fetchone()
                            context = ExpressionCommitContext(
                                row[0],
                                ids["episode"],
                                ids["opportunity"],
                                ids["opportunity"],
                                born.subject_id,
                                scene_id,
                                creator_party_id,
                                None,
                                "consider_creator_input",
                                TraceId(uuid7().hex),
                            )
                            if kind in {"silence", "decline"}:
                                await expression.commit.record_terminal(
                                    unit,
                                    context=context,
                                    application_id=row[1],
                                    application_status="no_action"
                                    if kind == "silence"
                                    else "declined",
                                    activity_owned=False,
                                    choices=(
                                        FormalNoActionDraft(
                                            "proposal:1",
                                            "group:1",
                                            (1,),
                                            FormalNoActionKind.NO_ACTION
                                            if kind == "silence"
                                            else FormalNoActionKind.DECLINE,
                                            FormalNoActionReason.SUBJECTIVE_SILENCE
                                            if kind == "silence"
                                            else FormalNoActionReason.SUBJECTIVE_REFUSAL,
                                        ),
                                    ),
                                )
                            else:
                                await decisions.record_dialogue_decision(
                                    unit.transaction,
                                    context=context,
                                    decision_kind=kind,
                                    operation_ref=ids["opportunity"],
                                )
                            snapshot = await actions.intents.operation_snapshot(
                                unit.transaction, operation_ref=ids["opportunity"]
                            )
                            assert snapshot is not None
                            self.assertEqual(
                                snapshot.dialogue_decision_id, ids["episode"]
                            )
                            self.assertEqual(snapshot.decision_kind, kind)
                            stored = await (
                                await unit.transaction.execute(
                                    "SELECT dialogue_effect_id FROM armi.cognitive_episodes WHERE cognitive_episode_id=%s",
                                    (ids["episode"],),
                                )
                            ).fetchone()
                            self.assertEqual(stored, (None,))
                            after = await (
                                await unit.transaction.execute(
                                    "SELECT count(*) FROM armi.effects"
                                )
                            ).fetchone()
                            self.assertEqual(before, after)
                            with self.assertRaises(ResponseViolation):
                                await decisions.record_dialogue_decision(
                                    unit.transaction,
                                    context=context,
                                    decision_kind="silence",
                                    operation_ref=ids["opportunity"],
                                )
                            await unit.transaction.execute(
                                "ROLLBACK TO SAVEPOINT dialogue_choice"
                            )
                            original = await (
                                await unit.transaction.execute(
                                    "SELECT dialogue_decision_kind,dialogue_effect_id IS NOT NULL FROM armi.cognitive_episodes WHERE cognitive_episode_id=%s",
                                    (ids["episode"],),
                                )
                            ).fetchone()
                            self.assertEqual(original, ("reply", True))
                if check_sleep_decisions:
                    sleep = bootstrap_sleep(
                        response_factory,
                        subject_id=born.subject_id,
                        creator_party_id=creator_party_id,
                        environment_id=fixture.environment_id,
                        cursor_key=hashlib.sha256(b"sleep-decisions").digest(),
                        runtime_facts=RuntimeSleepFacts(
                            cognition=bootstrap_cognition_operation(),
                            effects=bootstrap_effect_operation_read(),
                        ),
                        opportunities=bootstrap_opportunity_sleep(),
                        decisions=bootstrap_sleep_decision_record(),
                    )
                    for kind in SleepDecisionKind:
                        async with response_factory.unit_of_work() as unit:
                            await unit.transaction.execute("SAVEPOINT sleep_choice")
                            # Reuse the accepted episode fixture to exercise the owner boundary.
                            row = await (
                                await unit.transaction.execute(
                                    """UPDATE armi.cognitive_episodes
                                   SET purpose='consider_sleep', scene_id=NULL, context_party_id=NULL
                                   WHERE cognitive_episode_id=%s
                                   RETURNING candidate_validation_id,candidate_application_id""",
                                    (ids["episode"],),
                                )
                            ).fetchone()
                            assert row is not None
                            now = datetime.now(UTC)
                            context = SleepCommitContext(
                                row[0],
                                ids["episode"],
                                ids["opportunity"],
                                ids["opportunity"],
                                0,
                                born.subject_id,
                                "consider_sleep",
                                "maintenance_window",
                                born.subject_id,
                                1,
                                0,
                                now,
                                now + timedelta(hours=1),
                            )
                            await sleep.commit.commit(
                                unit.transaction,
                                context=context,
                                application_id=row[1],
                                commit_id=None,
                                resulting_subject_version=1,
                                drafts=(
                                    CandidateSleepDecisionDraft(
                                        "proposal:1",
                                        "group:1",
                                        (1,),
                                        kind,
                                        born.subject_id,
                                    ),
                                ),
                            )
                            stored = await (
                                await unit.transaction.execute(
                                    """SELECT sleep_decision_kind,sleep_cycle_anchor_ref,sleep_review_not_before
                                   FROM armi.cognitive_episodes WHERE cognitive_episode_id=%s""",
                                    (ids["episode"],),
                                )
                            ).fetchone()
                            assert stored is not None
                            self.assertEqual(stored[:2], (kind.value, born.subject_id))
                            if kind is SleepDecisionKind.DEFER:
                                self.assertGreaterEqual(
                                    stored[2], now + timedelta(hours=1)
                                )
                            else:
                                self.assertIsNone(stored[2])
                            sessions = await sleep.commit.affected_session_ids(
                                unit.transaction, row[0]
                            )
                            self.assertEqual(
                                len(sessions), int(kind is SleepDecisionKind.SLEEP)
                            )
                            if sessions:
                                origin = await (
                                    await unit.transaction.execute(
                                        "SELECT sleep_episode_id FROM armi.maintenance_sessions WHERE maintenance_session_id=%s",
                                        (sessions[0],),
                                    )
                                ).fetchone()
                                self.assertEqual(origin, (ids["episode"],))
                                # Actual outcomes and the progress marker commit together.
                                phase_id = uuid7()
                                await unit.transaction.execute(
                                    """UPDATE armi.maintenance_sessions
                                       SET phase='self_check',head_version=3,current_revision_id=%s
                                       WHERE maintenance_session_id=%s""",
                                    (phase_id, sessions[0]),
                                )
                                committed = await (
                                    await unit.transaction.execute(
                                        """UPDATE armi.cognitive_episodes
                                           SET purpose='perform_subject_self_check',sleep_decision_kind=NULL,
                                               sleep_cycle_anchor_ref=NULL,sleep_review_not_before=NULL
                                           WHERE cognitive_episode_id=%s RETURNING subject_commit_id""",
                                        (ids["episode"],),
                                    )
                                ).fetchone()
                                assert committed is not None
                                maintenance_context = replace(
                                    context,
                                    opportunity_purpose="perform_subject_self_check",
                                    source_kind="maintenance_phase_revision",
                                    source_ref=phase_id,
                                    source_version=3,
                                )
                                decision = CandidateMaintenanceDecisionDraft(
                                    "proposal:2",
                                    "group:1",
                                    (1,),
                                    sessions[0],
                                    phase_id,
                                    3,
                                    MaintenancePhase.SELF_CHECK,
                                    MaintenanceWorkOutcome.NO_ISSUE,
                                    "No issue found",
                                )
                                await unit.transaction.execute(
                                    "SAVEPOINT maintenance_result"
                                )
                                with self.assertRaises(SleepViolation):
                                    await sleep.commit.commit(
                                        unit.transaction,
                                        context=maintenance_context,
                                        application_id=row[1],
                                        commit_id=committed[0],
                                        resulting_subject_version=1,
                                        drafts=(
                                            replace(
                                                decision, current_revision_id=uuid7()
                                            ),
                                        ),
                                    )
                                await unit.transaction.execute(
                                    "ROLLBACK TO SAVEPOINT maintenance_result"
                                )
                                unchanged = await (
                                    await unit.transaction.execute(
                                        """SELECT maintenance_session_id,
                                                  (SELECT phase_completed_at FROM armi.maintenance_sessions
                                                   WHERE maintenance_session_id=%s)
                                           FROM armi.cognitive_episodes WHERE cognitive_episode_id=%s""",
                                        (sessions[0], ids["episode"]),
                                    )
                                ).fetchone()
                                self.assertEqual(unchanged, (None, None))
                                self.assertTrue(
                                    await sleep.commit.heads_match(
                                        unit.transaction,
                                        context=maintenance_context,
                                        drafts=(decision,),
                                    )
                                )
                                await sleep.commit.commit(
                                    unit.transaction,
                                    context=maintenance_context,
                                    application_id=row[1],
                                    commit_id=committed[0],
                                    resulting_subject_version=1,
                                    drafts=(decision,),
                                )
                                self.assertFalse(
                                    await sleep.commit.heads_match(
                                        unit.transaction,
                                        context=maintenance_context,
                                        drafts=(decision,),
                                    )
                                )
                                stored_result = await (
                                    await unit.transaction.execute(
                                        """SELECT episode.maintenance_outcome,
                                                  session.phase_completed_at IS NOT NULL
                                           FROM armi.cognitive_episodes episode
                                           JOIN armi.maintenance_sessions session
                                             ON session.maintenance_session_id=episode.maintenance_session_id
                                           WHERE episode.cognitive_episode_id=%s""",
                                        (ids["episode"],),
                                    )
                                ).fetchone()
                                self.assertEqual(stored_result, ("no_issue", True))
                                results = await bootstrap_sleep_decision_record().maintenance_results(
                                    unit.transaction,
                                    session_id=sessions[0],
                                    ceiling=None,
                                    before=None,
                                    limit=50,
                                )
                                self.assertEqual(len(results), 1)
                                self.assertEqual(
                                    results[0].work_outcome,
                                    MaintenanceWorkOutcome.NO_ISSUE,
                                )
                                self.assertEqual(
                                    results[0].result_status.value, "completed"
                                )
                            await unit.transaction.execute(
                                "ROLLBACK TO SAVEPOINT sleep_choice"
                            )
                            original = await (
                                await unit.transaction.execute(
                                    "SELECT sleep_decision_kind FROM armi.cognitive_episodes WHERE cognitive_episode_id=%s",
                                    (ids["episode"],),
                                )
                            ).fetchone()
                            self.assertEqual(original, (None,))
            finally:
                await response_factory.close()

        asyncio.run(
            dispatch_reply(),
            loop_factory=lambda: asyncio.SelectorEventLoop(selectors.SelectSelector()),
        )
        from armi_admin.application.contracts import CognitionReadRequest

        with tempfile.TemporaryDirectory(dir=Path.cwd() / ".tmp") as temporary:
            root = Path(temporary).resolve()
            config = AdminConfig.model_validate(
                {
                    "schema_version": "armi.admin-config.v10",
                    "operator_id": "isolated-cognition-reader",
                    "authorized_operations": ("cognition_read",),
                    "environment_kind": "acceptance",
                    "environment_id": str(fixture.environment_id),
                    "environment_incarnation": 1,
                    "resettable": True,
                    "test_controls_enabled": True,
                    "environment_root": root,
                    "experiment_root": root,
                    "database_locator": "env:ARMI_SECRET_ADMIN_DATABASE",
                    "migrator_database_locator": "env:ARMI_SECRET_MIGRATOR_DATABASE",
                    "preview_key_locator": "env:ARMI_SECRET_ADMIN_PREVIEW_KEY",
                    "expected": {"source_root": _ADMIN_SOURCE_ROOT},
                }
            )
            credentials = AdminCredentialPort(
                locator=config.locator,
                config_root=root,
                environ={"ARMI_SECRET_ADMIN_DATABASE": fixture.admin_role_dsn},
            )
            composition = bootstrap_admin(config, credentials)
            try:
                result = composition.service.observe(
                    "cognition_read",
                    CognitionReadRequest(
                        environment_id=str(fixture.environment_id),
                        episode_id=str(ids["episode"]),
                    ),
                )
                self.assertEqual(result.status, "succeeded", result)
                assert result.result is not None
                self.assertEqual(
                    result.result["attempts"][0]["request_artifact_id"],
                    str(artifact_ids["request"]),
                )
                self.assertEqual(
                    result.result["attempts"][0]["response_artifact_id"],
                    str(artifact_ids["response"]),
                )
                self.assertTrue(
                    all(item["retained"] for item in result.result["artifacts"])
                )
                response_path = (
                    root / "data" / "artifacts" / locator(digests["response"])
                )
                response_path.parent.mkdir(parents=True)
                response_path.write_bytes(payloads["response"])
                page = composition.service.observe(
                    "cognition_read",
                    CognitionReadRequest(
                        environment_id=str(fixture.environment_id),
                        episode_id=str(ids["episode"]),
                        artifact_id=str(artifact_ids["response"]),
                        length=65536,
                    ),
                )
                self.assertEqual(page.status, "succeeded", page)
                assert page.result is not None
                self.assertEqual(
                    page.result["text"]["content"], payloads["response"].decode("utf-8")
                )
            finally:
                composition.close()
        with psycopg.connect(fixture.provisioner_dsn) as connection:
            # The merged intent must be complete at insert time. There is no
            # temporary head without payload and no revision pointer to retarget.
            with self.assertRaises(psycopg.errors.NotNullViolation):
                connection.execute(
                    """
                    INSERT INTO armi.effects (
                        action_intent_id,subject_id,scene_id,context_party_id,
                        root_opportunity_id,purpose,effect_kind,operation_ref)
                    SELECT uuidv7(),subject_id,scene_id,context_party_id,
                           root_opportunity_id,purpose,effect_kind,uuidv7()
                    FROM armi.effects LIMIT 1
                    """
                )
            connection.rollback()
        with psycopg.connect(fixture.provisioner_dsn) as connection:
            effect_state = connection.execute(
                """
                SELECT effect.status, effect.dispatch_status,
                       'effect_' || effect.status,
                       effect.dispatch_deadline,
                       (SELECT count(*) FROM armi.effects WHERE local_delivery_id IS NOT NULL),
                       (SELECT count(*) FROM armi.effect_attempts),
                       (SELECT count(*) FROM armi.effect_observations),
                       (SELECT count(*) FROM armi.scene_timeline_items
                        WHERE source_kind = 'party_response')
                FROM armi.effects AS effect

                """
            ).fetchone()
        self.assertEqual(
            effect_state,
            (
                "completed",
                "delivered",
                "effect_completed",
                None,
                1,
                1,
                2,
                1,
            ),
        )

    def _verify_reply_interruption(
        self,
        fixture: DatabaseFixture,
        fence: RuntimeFence,
        ids: dict[str, UUID],
        payloads: dict[str, bytes],
        stage: str,
        *,
        codex: bool = False,
    ) -> None:
        async def exercise() -> None:
            factory = PostgreSQLUnitOfWorkFactory(
                fixture.runtime_dsn,
                environment_id=fixture.environment_id,
                pool_min=1,
                pool_max=1,
                acquire_timeout_seconds=2,
                statement_timeout_seconds=5,
                authority_admission=lambda: fence,
            )
            dispatcher = PostgreSQLEffectDispatchRepository(
                bootstrap_interaction_action_ports().routes,
            )
            codex_effect = bootstrap_effect_codex_lifecycle()
            codex_repository = PostgreSQLCodexDelegationRepository(
                bootstrap_evidence().write,
                bootstrap_opportunity_admission(),
                codex_effect,
                bootstrap_expression_action_ports(
                    bootstrap_effect_intent_read(), bootstrap_dialogue_decision_record()
                ).intents,
                ArtifactCatalogRepository(),
                bootstrap_codex_read_ports().task_sources,
                bootstrap_evidence().read,
                bootstrap_interaction_identity(_TEST_IDENTITY_TOKENS),
                CreatorInputRepository(
                    bootstrap_evidence().write,
                    bootstrap_evidence().read,
                    bootstrap_opportunity_admission(),
                ),
            )
            codex_claim = None
            roster = compose_runtime_owner_roster(
                data_rights=bootstrap_data_rights_core().participant,
                mood_read=bootstrap_mood().read,
                prompt_read=bootstrap_prompt().read,
                subject_state_read=bootstrap_subject_state().read,
                mind_read=bootstrap_mind().read,
            )
            recovery = PostgreSQLRuntimeRecovery(
                factory,
                environment_id=fixture.environment_id,
                data_root=Path.cwd() / ".tmp",
                max_object_bytes=1024 * 1024,
                authority_admission=lambda: fence,
                participants=roster.recovery,
                expected_owners=roster.expected_recovery_owners,
                catalog=ArtifactCatalogRepository(),
            )
            await factory.open()
            try:
                if stage in {
                    "prepared",
                    "dispatching",
                    "receipt_saved",
                    "result_saved",
                    "result_cognition",
                }:
                    async with factory.unit_of_work() as unit:
                        if codex:
                            codex_claim = await codex_repository.claim(
                                unit, claim_owner=ids["runtime"]
                            )
                            snapshot = codex_claim
                        else:
                            snapshot = await dispatcher.claim(
                                unit, claim_owner=ids["runtime"]
                            )
                    assert snapshot is not None
                    self.assertIsNone(snapshot.dispatch_deadline)
                    if codex and stage in {
                        "dispatching",
                        "result_saved",
                        "result_cognition",
                    }:
                        async with factory.unit_of_work() as unit:
                            assert snapshot is not None
                            self.assertTrue(
                                await codex_repository.mark_dispatching(
                                    unit,
                                    cast(Any, snapshot),
                                    runtime_fence=fence,
                                    data_rights_fence=DataRightsFence(
                                        cast(Any, snapshot).creator_party_id, 1, 1
                                    ),
                                )
                            )
                    elif stage in {"dispatching", "receipt_saved"}:
                        async with factory.unit_of_work() as unit:
                            self.assertTrue(
                                await dispatcher.mark_dispatching(
                                    unit,
                                    cast(Any, snapshot),
                                    runtime_fence=fence,
                                    data_rights_fence=DataRightsFence(
                                        cast(
                                            Any, snapshot
                                        ).request.destination_party_id,
                                        1,
                                        1,
                                    ),
                                )
                            )
                    if stage == "receipt_saved":
                        receipt = await PostgreSQLLocalInbox(factory).dispatch(
                            cast(Any, snapshot).request, payloads["reply"]
                        )
                        async with factory.unit_of_work() as unit:
                            await dispatcher.settle_receipt(
                                unit, cast(Any, snapshot), receipt
                            )
                if codex_claim is not None and stage in {
                    "result_saved",
                    "result_cognition",
                }:
                    async with factory.unit_of_work() as unit:
                        await codex_repository.settle(
                            unit,
                            snapshot=codex_claim,
                            status=CodexVerificationStatus.VERIFIED,
                            cleanup_status=CodexCleanupStatus.CLEAN,
                            artifacts={
                                "final_result": codex_claim.task_manifest,
                            },
                            execution_error_code=None,
                            cleanup_error_code=None,
                        )
                    if stage == "result_cognition":
                        async with factory.unit_of_work() as unit:
                            result_episode = uuid7()
                            await unit.transaction.execute(
                                """
                                INSERT INTO armi.cognitive_episodes (
                                    cognitive_episode_id, opportunity_id, subject_id, scene_id,
                                    context_party_id, purpose, status, base_subject_version,
                                    base_state_epoch, bundle_activation_id, mechanism_identity,
                                    context_manifest_artifact_id, compiled_context_artifact_id,
                                    context_manifest_digest, compiled_context_digest,
                                    trace_id, prepared_at)
                                SELECT %s, result.opportunity_id, original.subject_id,
                                    original.scene_id, original.context_party_id,
                                    'consider_codex_result', 'calling_model', 1,
                                    original.base_state_epoch, original.bundle_activation_id,
                                    original.mechanism_identity,
                                    original.context_manifest_artifact_id,
                                    original.compiled_context_artifact_id,
                                    original.context_manifest_digest, original.compiled_context_digest,
                                    original.trace_id, statement_timestamp()
                                FROM armi.cognitive_episodes AS original
                                CROSS JOIN armi.codex_task_sources AS result
                                WHERE original.cognitive_episode_id=%s
                            """,
                                (result_episode, ids["episode"]),
                            )
                            await unit.transaction.execute(
                                """
                                INSERT INTO armi.durable_work (
                                    work_id, work_kind, owner_kind, owner_ref, subject_id,
                                    idempotency_key, payload_digest, priority, not_before,
                                    deadline_at, status, max_attempts, trace_id)
                                SELECT uuidv7(), 'cognition.execute', 'cognitive_episode',
                                    cognitive_episode_id, subject_id,
                                    'controlled-codex-result-work', %s, 50, statement_timestamp(),
                                    statement_timestamp() + interval '5 minutes', 'ready', 1, trace_id
                                FROM armi.cognitive_episodes WHERE cognitive_episode_id=%s
                            """,
                                (
                                    Digest.from_bytes(b"controlled result work").value,
                                    result_episode,
                                ),
                            )
                await recovery.end_interrupted_work()
                if codex_claim is not None:
                    with self.assertRaisesRegex(
                        RuntimeError, "EFFECT-SETTLEMENT-STALE"
                    ):
                        async with factory.unit_of_work() as unit:
                            await codex_repository.fail_dispatch(
                                unit,
                                codex_claim,
                                reason_code="CODEX-LATE-RESULT",
                                started=True,
                            )
                # A second lifecycle pass must not recreate work or dispatch.
                await recovery.end_interrupted_work()
                async with factory.unit_of_work() as unit:
                    self.assertIsNone(
                        await dispatcher.claim(unit, claim_owner=ids["runtime"])
                    )
                    self.assertIsNone(await dispatcher.unknown(unit))
                    if codex:
                        self.assertIsNone(
                            await codex_effect.claim_codex(
                                unit, claim_owner=ids["runtime"]
                            )
                        )
            finally:
                await factory.close()

        asyncio.run(
            exercise(),
            loop_factory=lambda: asyncio.SelectorEventLoop(selectors.SelectSelector()),
        )
        with psycopg.connect(fixture.provisioner_dsn) as connection:
            self.assertEqual(
                connection.execute(
                    "SELECT count(*) FROM armi.durable_work WHERE status IN ('ready','leased') AND owner_kind='cognitive_episode'"
                ).fetchone(),
                (0,),
            )
            if stage in {
                "context_unfinished",
                "model_prepared",
                "cognition_unfinished",
                "finalizing",
            }:
                self.assertEqual(
                    connection.execute(
                        "SELECT result_status FROM armi.cognitive_attempts"
                    ).fetchone(),
                    None
                    if stage == "context_unfinished"
                    else (
                        "cancelled"
                        if stage == "model_prepared"
                        else "outcome_unknown"
                        if stage == "cognition_unfinished"
                        else "succeeded",
                    ),
                )
                self.assertEqual(
                    connection.execute(
                        "SELECT current_disposition FROM armi.opportunities"
                    ).fetchone(),
                    ("cancelled",),
                )
                self.assertEqual(
                    connection.execute(
                        "SELECT count(*) FROM armi.cognitive_episodes WHERE subject_commit_id IS NOT NULL"
                    ).fetchone(),
                    (0,),
                )
                self.assertEqual(
                    connection.execute(
                        "SELECT status FROM armi.cognitive_episodes"
                    ).fetchone(),
                    ("cancelled",),
                )
            else:
                self.assertEqual(
                    connection.execute(
                        "SELECT count(*) FROM armi.cognitive_episodes WHERE subject_commit_id IS NOT NULL"
                    ).fetchone(),
                    (1,),
                )
                expected = (
                    "completed"
                    if stage in {"receipt_saved", "result_saved", "result_cognition"}
                    else "unknown"
                    if stage == "dispatching"
                    else "cancelled"
                )
                self.assertEqual(
                    connection.execute("SELECT status FROM armi.effects").fetchone(),
                    (expected,),
                )

            if stage in {"result_saved", "result_cognition"}:
                self.assertEqual(
                    connection.execute(
                        "SELECT execution_status FROM armi.codex_task_sources WHERE codex_verification_id IS NOT NULL"
                    ).fetchall(),
                    [("verified",)],
                )
                self.assertEqual(
                    connection.execute("""
                    SELECT opportunity.current_disposition
                    FROM armi.codex_task_sources AS result
                    JOIN armi.opportunities AS opportunity
                      ON opportunity.opportunity_id=result.opportunity_id
                """).fetchall(),
                    [("cancelled",)],
                )
                if stage == "result_cognition":
                    self.assertEqual(
                        connection.execute(
                            "SELECT status FROM armi.cognitive_episodes WHERE purpose='consider_codex_result'"
                        ).fetchall(),
                        [("cancelled",)],
                    )

    @pytest.mark.test_group("runtime", "recovery")
    def test_runtime_authority_heartbeat_takeover_and_fence(self) -> None:
        fixture = self.create_database()
        self._install_current(
            fixture.migrator_dsn,
            environment_id=fixture.environment_id,
        )
        packaged = packaged_birth_digests()
        anchor = PersonalityAnchor(
            schema_version="armi.personality-anchor.v1",
            voice_style="约 16 岁少女口吻",
            traits=("清醒",),
        )
        manifest = BirthManifest(
            schema_version="armi.birth-manifest.v1",
            environment_id=fixture.environment_id,
            birth_request_id=_uuid7(),
            creator_party_id=_uuid7(),
            idempotency_key="s016-authority-birth",
            personality_anchor=anchor,
            birth_contract_digest=packaged["birth_contract_digest"],
            request_digest=Digest.from_bytes(b"s016-authority-birth"),
        )

        async def exercise(root: Path) -> tuple[int, int, tuple[str, ...]]:
            birth_factory = PostgreSQLUnitOfWorkFactory(
                fixture.runtime_dsn,
                environment_id=fixture.environment_id,
                pool_min=1,
                pool_max=2,
                acquire_timeout_seconds=2,
                statement_timeout_seconds=5,
                require_runtime_fence=False,
            )
            birth = BirthTransaction(
                _publishing_artifact_store(root, birth_factory),
                ArtifactCatalogRepository(),
                _birth_repository(),
                birth_factory,
            )
            await birth_factory.open()
            try:
                await birth.birth(manifest)
            finally:
                await birth_factory.close()

            authorities = [
                PostgreSQLRuntimeAuthority(
                    fixture.runtime_dsn,
                    environment_id=fixture.environment_id,
                    pool_timeout_seconds=2,
                    statement_timeout_seconds=5,
                    process_absent=lambda _identity: True,
                )
                for _ in range(3)
            ]
            for authority in authorities:
                await authority.open()
            try:

                async def attempt(
                    authority: PostgreSQLRuntimeAuthority,
                ) -> RuntimeAuthorityRecord | RuntimeAuthorityViolation:
                    try:
                        return await authority.acquire(
                            runtime_instance_id=RuntimeInstanceId(_uuid7()),
                            lease_seconds=3,
                        )
                    except RuntimeAuthorityViolation as error:
                        return error

                first_attempts = await asyncio.gather(
                    attempt(authorities[0]),
                    attempt(authorities[1]),
                )
                records = [
                    item
                    for item in first_attempts
                    if isinstance(item, RuntimeAuthorityRecord)
                ]
                errors = [
                    item
                    for item in first_attempts
                    if isinstance(item, RuntimeAuthorityViolation)
                ]
                self.assertEqual(len(records), 1)
                self.assertEqual(
                    [error.code for error in errors],
                    ["AUTH-LEASE-HELD"],
                )
                first = records[0]
                winner = (
                    authorities[0]
                    if isinstance(first_attempts[0], RuntimeAuthorityRecord)
                    else authorities[1]
                )
                takeover = (
                    authorities[1] if winner is authorities[0] else authorities[0]
                )

                uow_factory = PostgreSQLUnitOfWorkFactory(
                    fixture.runtime_dsn,
                    environment_id=fixture.environment_id,
                    pool_min=1,
                    pool_max=1,
                    acquire_timeout_seconds=2,
                    statement_timeout_seconds=10,
                    authority_admission=lambda: first.fence,
                    require_runtime_fence=True,
                )
                await uow_factory.open()
                entered = asyncio.Event()

                async def expire_open_transaction() -> str:
                    try:
                        async with uow_factory.unit_of_work():
                            entered.set()
                            await asyncio.sleep(3.2)
                    except DatabaseTransactionError as error:
                        return error.code
                    raise AssertionError("expired fenced transaction committed")

                transaction_task = asyncio.create_task(expire_open_transaction())
                await entered.wait()
                # OS absence is checked before the authority write transaction.
                # Start takeover only after the old lease is actually expired;
                # the old open transaction still verifies the row-lock rematch.
                await asyncio.sleep(3.1)
                takeover_task = asyncio.create_task(
                    takeover.acquire(
                        runtime_instance_id=RuntimeInstanceId(_uuid7()),
                        lease_seconds=3,
                    )
                )
                expired_code, second = await asyncio.gather(
                    transaction_task,
                    takeover_task,
                )
                await uow_factory.close()
                self.assertEqual(expired_code, "DB-TX-FENCE-EXPIRED")
                assert isinstance(second, RuntimeAuthorityRecord)
                self.assertEqual(second.fence.subject_id, first.fence.subject_id)
                self.assertGreater(
                    second.fence.fence_token,
                    first.fence.fence_token,
                )
                with self.assertRaises(RuntimeAuthorityViolation):
                    await winner.heartbeat(first.fence, lease_seconds=3)
                with self.assertRaises(RuntimeAuthorityViolation):
                    await winner.release(first.fence)
                await takeover.release(second.fence)

                default = await authorities[2].acquire(
                    runtime_instance_id=RuntimeInstanceId(_uuid7()),
                    lease_seconds=30,
                )
                await asyncio.sleep(10)
                renewed = await authorities[2].heartbeat(
                    default.fence,
                    lease_seconds=30,
                )
                self.assertGreater(
                    renewed.lease_expires_at,
                    default.lease_expires_at,
                )
                await authorities[2].release(default.fence)

                with psycopg.connect(
                    fixture.provisioner_dsn,
                    autocommit=True,
                ) as provisioner:
                    before_count = provisioner.execute(
                        "SELECT count(*) FROM armi.runtime_instances"
                    ).fetchone()
                    provisioner.execute(
                        "REVOKE INSERT ON armi.audit_events FROM armi_runtime"
                    )
                with self.assertRaises(RuntimeAuthorityViolation) as audit_denied:
                    await authorities[0].acquire(
                        runtime_instance_id=RuntimeInstanceId(_uuid7()),
                        lease_seconds=3,
                    )
                self.assertEqual(audit_denied.exception.code, "AUTH-AUDIT")
                with psycopg.connect(
                    fixture.provisioner_dsn,
                    autocommit=True,
                ) as provisioner:
                    after_count = provisioner.execute(
                        "SELECT count(*) FROM armi.runtime_instances"
                    ).fetchone()
                    provisioner.execute(
                        "GRANT INSERT ON armi.audit_events TO armi_runtime"
                    )
                self.assertEqual(before_count, after_count)
            finally:
                for authority in authorities:
                    await authority.close()

            with psycopg.connect(fixture.provisioner_dsn) as connection:
                operations = tuple(
                    row[0]
                    for row in connection.execute(
                        """
                        SELECT operation
                        FROM armi.audit_events
                        WHERE operation LIKE 'runtime.authority.%'
                        ORDER BY occurred_at, audit_event_id
                        """
                    ).fetchall()
                )
            return first.fence.fence_token, second.fence.fence_token, operations

        with tempfile.TemporaryDirectory(dir=Path.cwd() / ".tmp") as temporary:
            first_token, second_token, operations = asyncio.run(
                exercise(Path(temporary).resolve()),
                loop_factory=lambda: asyncio.SelectorEventLoop(
                    selectors.SelectSelector()
                ),
            )
        self.assertEqual((first_token, second_token), (1, 2))
        self.assertEqual(operations.count("runtime.authority.fenced"), 1)
        self.assertEqual(operations.count("runtime.authority.acquired"), 3)
        self.assertEqual(operations.count("runtime.authority.released"), 2)
        self.assertNotIn("runtime.authority.heartbeat", operations)
        with psycopg.connect(fixture.runtime_dsn) as connection:
            with self.assertRaises(psycopg.errors.InsufficientPrivilege):
                connection.execute("DELETE FROM armi.runtime_instances")
            connection.rollback()
            with self.assertRaises(psycopg.errors.InsufficientPrivilege):
                connection.execute("TRUNCATE armi.runtime_instances")
        with psycopg.connect(fixture.admin_role_dsn) as connection:
            connection.execute("SELECT * FROM armi.runtime_instances").fetchall()
        with (
            psycopg.connect(fixture.migrator_dsn) as connection,
            self.assertRaises(psycopg.errors.InsufficientPrivilege),
        ):
            connection.execute("SELECT * FROM armi.runtime_instances")

    @pytest.mark.test_group("runtime", "recovery")
    def test_runtime_recovery_reaches_safe_without_starting_workers(self) -> None:
        fixture = self.create_database()
        self._install_current(
            fixture.migrator_dsn,
            environment_id=fixture.environment_id,
        )
        with psycopg.connect(fixture.provisioner_dsn) as connection:
            connection.execute(
                """INSERT INTO armi.deployment_environments
                   (environment_id,environment_kind,incarnation,resettable,test_controls_enabled)
                   VALUES (%s,'system_test',1,true,true)""",
                (fixture.environment_id,),
            )
        packaged = packaged_birth_digests()
        anchor = PersonalityAnchor(
            schema_version="armi.personality-anchor.v1",
            voice_style="约 16 岁少女口吻",
            traits=("连续",),
        )
        manifest = BirthManifest(
            schema_version="armi.birth-manifest.v1",
            environment_id=fixture.environment_id,
            birth_request_id=_uuid7(),
            creator_party_id=_uuid7(),
            idempotency_key="s017-recovery-birth",
            personality_anchor=anchor,
            birth_contract_digest=packaged["birth_contract_digest"],
            request_digest=Digest.from_bytes(b"s017-recovery-birth"),
        )

        async def exercise(
            root: Path,
        ) -> tuple[str, int, int, tuple[str, ...]]:
            birth_factory = PostgreSQLUnitOfWorkFactory(
                fixture.runtime_dsn,
                environment_id=fixture.environment_id,
                pool_min=1,
                pool_max=2,
                acquire_timeout_seconds=2,
                statement_timeout_seconds=5,
                require_runtime_fence=False,
            )
            birth = BirthTransaction(
                _publishing_artifact_store(root, birth_factory),
                ArtifactCatalogRepository(),
                _birth_repository(),
                birth_factory,
            )
            await birth_factory.open()
            try:
                await birth.birth(manifest)
            finally:
                await birth_factory.close()

            authorities = [
                PostgreSQLRuntimeAuthority(
                    fixture.runtime_dsn,
                    environment_id=fixture.environment_id,
                    pool_timeout_seconds=2,
                    statement_timeout_seconds=5,
                    process_absent=lambda _identity: True,
                )
                for _ in range(2)
            ]
            for authority in authorities:
                await authority.open()
            try:
                old = await authorities[0].acquire(
                    runtime_instance_id=RuntimeInstanceId(_uuid7()),
                    lease_seconds=1,
                )
                work_id = _uuid7()
                with psycopg.connect(
                    fixture.provisioner_dsn,
                    autocommit=True,
                ) as connection:
                    connection.execute(
                        """
                        INSERT INTO armi.durable_work (
                            work_id, work_kind, owner_kind, owner_ref,
                            idempotency_key, payload_digest, priority,
                            not_before, deadline_at, status, max_attempts,
                            attempt_count, current_attempt_id, lease_owner,
                            lease_expires_at, lease_token, trace_id
                        )
                        VALUES (
                            %s, 'artifact.object.delete',
                            'artifact_object_deletion', %s,
                            's017-recovery-work',
                            'sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa'
                            'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa',
                            0, statement_timestamp(),
                            statement_timestamp() + interval '60 seconds',
                            'leased', 3, 1, %s, %s,
                            statement_timestamp() + interval '1 second',
                            7, %s
                        )
                        """,
                        (
                            work_id,
                            old.fence.runtime_instance_id.value,
                            _uuid7(),
                            old.fence.runtime_instance_id.value,
                            old.fence.runtime_instance_id.value.hex,
                        ),
                    )
                await asyncio.sleep(1.1)
                record = await authorities[1].acquire(
                    runtime_instance_id=RuntimeInstanceId(_uuid7()),
                    lease_seconds=30,
                )
                await authorities[1].heartbeat(record.fence, lease_seconds=30)
                recovery_factory = PostgreSQLUnitOfWorkFactory(
                    fixture.runtime_dsn,
                    environment_id=fixture.environment_id,
                    pool_min=1,
                    pool_max=1,
                    acquire_timeout_seconds=2,
                    statement_timeout_seconds=5,
                    authority_admission=lambda: record.fence,
                )
                owner_roster = compose_runtime_owner_roster(
                    data_rights=bootstrap_data_rights_core().participant,
                    mood_read=bootstrap_mood().read,
                    prompt_read=bootstrap_prompt().read,
                    subject_state_read=bootstrap_subject_state().read,
                    mind_read=bootstrap_mind().read,
                )
                recovery = PostgreSQLRuntimeRecovery(
                    recovery_factory,
                    environment_id=fixture.environment_id,
                    data_root=root.parent,
                    max_object_bytes=1024 * 1024,
                    authority_admission=lambda: record.fence,
                    participants=owner_roster.recovery,
                    expected_owners=owner_roster.expected_recovery_owners,
                    catalog=ArtifactCatalogRepository(),
                )
                await recovery_factory.open()
                await recovery.open()
                try:
                    summary = await recovery.recover()
                finally:
                    await recovery.close()
                    await recovery_factory.close()
                await authorities[1].release(record.fence)
            finally:
                for authority in authorities:
                    await authority.close()
            with psycopg.connect(fixture.provisioner_dsn) as connection:
                operations = tuple(
                    row[0]
                    for row in connection.execute(
                        """
                        SELECT operation
                        FROM armi.audit_events
                        WHERE operation LIKE 'runtime.recovery.%'
                        ORDER BY occurred_at, audit_event_id
                        """
                    ).fetchall()
                )
            return (
                summary.status.value,
                next(
                    metric.value
                    for metric in summary.metrics
                    if metric.kind == "artifact_store.verified_critical_count"
                ),
                next(
                    metric.value
                    for metric in summary.metrics
                    if metric.kind == "runtime.reconciliation_required_count"
                ),
                operations,
            )

        with tempfile.TemporaryDirectory(dir=Path.cwd() / ".tmp") as temporary:
            environment_root = Path(temporary).resolve()
            data_root = environment_root / "data"
            secrets_root = environment_root / "secrets"
            data_root.mkdir()
            secrets_root.mkdir()
            creator_resources = _write_creator_resources(
                environment_root / "creator-web-resources"
            )
            artifact_root = data_root / "artifacts"
            status, critical_count, requeued_work, operations = asyncio.run(
                exercise(artifact_root),
                loop_factory=lambda: asyncio.SelectorEventLoop(
                    selectors.SelectSelector()
                ),
            )
            runtime_secret = secrets_root / "runtime"
            runtime_secret.write_text(
                fixture.runtime_dsn,
                encoding="utf-8",
                newline="\n",
            )
            creator_bearer = "creator-v1." + secrets.token_urlsafe(32)
            creator_secret = secrets_root / "creator"
            creator_secret.write_text(
                creator_bearer,
                encoding="utf-8",
                newline="\n",
            )
            identity_secret = _write_data_rights_identity_secret(secrets_root)
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
                listener.bind(("127.0.0.1", 0))
                runtime_port = int(listener.getsockname()[1])
            (environment_root / "environment.yaml").write_text(
                "\n".join(
                    (
                        "environment:",
                        f"  environment_id: {fixture.environment_id}",
                        f'  data_root: "{data_root.as_posix()}"',
                        "creator:",
                        f"  port: {runtime_port}",
                        "secret_locators:",
                        f"  database.runtime: file:{runtime_secret.as_posix()}",
                        f"  creator.bearer: file:{creator_secret.as_posix()}",
                        f"  data_rights.identity_token_key: file:{identity_secret.as_posix()}",
                    )
                ),
                encoding="utf-8",
                newline="\n",
            )
            process = subprocess.Popen(
                (
                    sys.executable,
                    "-m",
                    "armi_runtime.runtime_entrypoint",
                    "runtime",
                    "start",
                    "--environment-root",
                    str(environment_root),
                    "--creator-web-resources",
                    str(creator_resources),
                ),
                cwd=Path.cwd(),
                env={
                    key: value
                    for key, value in os.environ.items()
                    if not key.startswith("ARMI_")
                },
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
            )
            try:
                deadline = time.monotonic() + 30
                while time.monotonic() < deadline:
                    if process.poll() is not None:
                        stdout, stderr = process.communicate(timeout=5)
                        diagnostics = tuple(
                            path.read_text(encoding="utf-8")
                            for path in sorted((data_root / "logs").glob("*.jsonl"))
                        )
                        self.fail(
                            "born Runtime exited before listening: "
                            f"exit={process.returncode!r} stdout={stdout!r} "
                            f"stderr={stderr!r} diagnostics={diagnostics!r}"
                        )
                    try:
                        with socket.create_connection(
                            ("127.0.0.1", runtime_port),
                            timeout=0.2,
                        ):
                            break
                    except OSError:
                        time.sleep(0.05)
                        continue
                else:
                    process.kill()
                    stdout, stderr = process.communicate()
                    diagnostics = tuple(
                        path.read_text(encoding="utf-8")
                        for path in sorted((data_root / "logs").glob("*.jsonl"))
                    )
                    self.fail(
                        "born Runtime did not listen; "
                        f"stdout={stdout!r}; stderr={stderr!r}; "
                        f"diagnostics={diagnostics!r}"
                    )
                connection = http.client.HTTPConnection(
                    "127.0.0.1",
                    runtime_port,
                    timeout=5,
                )
                try:
                    browser_boundary_headers = {
                        "Origin": f"http://127.0.0.1:{runtime_port}",
                        "Sec-Fetch-Site": "same-origin",
                        "Sec-Fetch-Mode": "cors",
                        "Sec-Fetch-Dest": "empty",
                    }
                    connection.request(
                        "POST",
                        "/v1/browser-sessions",
                        body=b"",
                        headers={
                            **browser_boundary_headers,
                            "Content-Length": "0",
                        },
                    )
                    session_response = connection.getresponse()
                    established = json.loads(session_response.read())
                    self.assertEqual(session_response.status, 200)
                    browser_token = established["browser_session_token"]
                    self.assertEqual(established["default_scene_key"], "default")
                    authenticated_headers = {
                        **browser_boundary_headers,
                        "Authorization": f"Bearer {browser_token}",
                    }
                    connection.request(
                        "GET",
                        "/v1/browser-sessions/current",
                        headers=authenticated_headers,
                    )
                    current_response = connection.getresponse()
                    current = json.loads(current_response.read())
                    self.assertEqual(current_response.status, 200)
                    self.assertEqual(
                        current["creator_party_id"],
                        established["creator_party_id"],
                    )
                    connection.request(
                        "GET",
                        "/v1/runtime/status",
                        headers=authenticated_headers,
                    )
                    status_response = connection.getresponse()
                    runtime_status = json.loads(status_response.read())
                    self.assertEqual(status_response.status, 200)
                    self.assertEqual(
                        (runtime_status["runtime_state"], runtime_status["readiness"]),
                        ("degraded", "ready"),
                        runtime_status,
                    )
                    self.assertEqual(
                        runtime_status["reason_codes"],
                        ["RUNTIME_MODEL_UNAVAILABLE"],
                    )
                    stream_connection = http.client.HTTPConnection(
                        "127.0.0.1",
                        runtime_port,
                        timeout=20,
                    )
                    stream_connection.request(
                        "GET",
                        "/v1/scenes/default/events",
                        headers={
                            **authenticated_headers,
                            "Accept": "text/event-stream",
                        },
                    )
                    stream_response = stream_connection.getresponse()
                    self.assertEqual(stream_response.status, 200)
                    self.assertTrue(
                        stream_response.getheader("Content-Type", "").startswith(
                            "text/event-stream"
                        )
                    )
                    message = "  first creator input\nsecond line  "
                    input_body = json.dumps(
                        {
                            "contract_version": "1.0",
                            "message": message,
                        },
                        ensure_ascii=False,
                        separators=(",", ":"),
                    ).encode()
                    input_headers = {
                        **authenticated_headers,
                        "Content-Type": "application/json",
                        "Content-Length": str(len(input_body)),
                        "Idempotency-Key": "s021-runtime-input",
                    }
                    connection.request(
                        "POST",
                        "/v1/scenes/default/messages",
                        body=input_body,
                        headers=input_headers,
                    )
                    accepted_response = connection.getresponse()
                    accepted = json.loads(accepted_response.read())
                    self.assertEqual(accepted_response.status, 202, accepted)
                    self.assertEqual(accepted["status"], "accepted")
                    self.assertEqual(accepted["custodian"], "runtime")
                    self.assertEqual(
                        accepted["result_ref"],
                        accepted["details"]["opportunity_id"],
                    )
                    event_lines = [
                        stream_response.readline(),
                        stream_response.readline(),
                        stream_response.readline(),
                        stream_response.readline(),
                    ]
                    self.assertTrue(event_lines[0].startswith(b"id: sse-v1."))
                    self.assertEqual(
                        event_lines[1],
                        b"event: scene.timeline.invalidated\n",
                    )
                    event_payload = json.loads(event_lines[2].removeprefix(b"data: "))
                    self.assertEqual(
                        (
                            event_payload["event_kind"],
                            event_payload["resource_kind"],
                            event_payload["resource_ref"],
                        ),
                        (
                            "scene.timeline.invalidated",
                            "scene_timeline",
                            "default",
                        ),
                    )
                    self.assertEqual(event_lines[3], b"\n")
                    operation_event_lines = [
                        stream_response.readline(),
                        stream_response.readline(),
                        stream_response.readline(),
                        stream_response.readline(),
                    ]
                    self.assertTrue(operation_event_lines[0].startswith(b"id: sse-v1."))
                    self.assertEqual(
                        operation_event_lines[1],
                        b"event: operation.invalidated\n",
                    )
                    operation_event = json.loads(
                        operation_event_lines[2].removeprefix(b"data: ")
                    )
                    self.assertEqual(
                        (
                            operation_event["resource_kind"],
                            operation_event["resource_ref"],
                            operation_event["projection_version"],
                        ),
                        (
                            "operation",
                            accepted["result_ref"],
                            "creator-operation.v8",
                        ),
                    )
                    self.assertEqual(operation_event_lines[3], b"\n")
                    if process.poll() is not None:
                        stdout, stderr = process.communicate(timeout=5)
                        self.fail(
                            "Runtime exited after accepting input: "
                            f"stdout={stdout!r} stderr={stderr!r}"
                        )
                    connection.request(
                        "POST",
                        "/v1/scenes/default/messages",
                        body=input_body,
                        headers=input_headers,
                    )
                    replay_response = connection.getresponse()
                    replay_body = replay_response.read()
                    if replay_response.status != 202:
                        process.send_signal(signal.CTRL_BREAK_EVENT)
                        _stdout, replay_stderr = process.communicate(timeout=35)
                        self.fail(
                            f"idempotent input failed: status={replay_response.status} "
                            f"body={replay_body!r} stderr={replay_stderr!r}"
                        )
                    replay = json.loads(replay_body)
                    self.assertEqual(
                        (
                            replay["status"],
                            replay["result_ref"],
                            replay["custodian"],
                            replay["details"],
                        ),
                        (
                            accepted["status"],
                            accepted["result_ref"],
                            accepted["custodian"],
                            accepted["details"],
                        ),
                    )
                    connection.request(
                        "GET",
                        accepted["details"]["operation_url"],
                        headers=authenticated_headers,
                    )
                    operation_response = connection.getresponse()
                    operation = json.loads(operation_response.read())
                    self.assertEqual(operation_response.status, 200)
                    self.assertEqual(operation["result_ref"], accepted["result_ref"])
                    self.assertIn(operation["status"], {"accepted", "waiting"})
                    operation_deadline = time.monotonic() + 10
                    while (
                        operation.get("waiting_for") != "model_attempt"
                        and time.monotonic() < operation_deadline
                    ):
                        time.sleep(0.05)
                        connection.request(
                            "GET",
                            accepted["details"]["operation_url"],
                            headers=authenticated_headers,
                        )
                        operation_response = connection.getresponse()
                        operation = json.loads(operation_response.read())
                        self.assertEqual(operation_response.status, 200)
                    self.assertEqual(
                        (
                            operation["status"],
                            operation.get("waiting_for"),
                            operation.get("resume_condition"),
                        ),
                        (
                            "waiting",
                            "model_attempt",
                            "model_step_available",
                        ),
                        (
                            operation,
                            tuple(
                                path.read_text(encoding="utf-8")
                                for path in sorted((data_root / "logs").glob("*.jsonl"))
                            ),
                        ),
                    )
                    connection.request(
                        "GET",
                        "/v1/scenes/default/timeline?limit=50",
                        headers=authenticated_headers,
                    )
                    timeline_response = connection.getresponse()
                    timeline = json.loads(timeline_response.read())
                    self.assertEqual(timeline_response.status, 200)
                    self.assertEqual(len(timeline["items"]), 1)
                    self.assertEqual(
                        (
                            timeline["items"][0]["source_kind"],
                            timeline["items"][0]["source_ref"],
                            timeline["items"][0]["status"],
                            timeline["items"][0]["operation_ref"],
                            timeline["items"][0]["message"],
                        ),
                        (
                            "creator_input",
                            accepted["details"]["interaction_id"],
                            "accepted",
                            accepted["result_ref"],
                            message,
                        ),
                    )
                    self.assertEqual(stream_response.readline(), b": keepalive\n")
                    self.assertEqual(stream_response.readline(), b"\n")
                    stream_connection.close()
                finally:
                    connection.close()
                process.send_signal(signal.CTRL_BREAK_EVENT)
                stdout, stderr = process.communicate(timeout=35)
            finally:
                if process.poll() is None:
                    process.kill()
                    process.communicate()
            self.assertEqual(process.returncode, 0, stderr)
            self.assertEqual(stdout, "")
            log_events = [
                json.loads(line)["event"]
                for line in next((data_root / "logs").glob("runtime-*.jsonl"))
                .read_text(encoding="utf-8")
                .splitlines()
            ]
            self.assertEqual(
                log_events[:9],
                [
                    "runtime.lifecycle.starting",
                    "runtime.authority.acquired",
                    "runtime.lifecycle.recovering",
                    "runtime.recovery.safe",
                    "runtime.lifecycle.degraded",
                    "creator.session.established",
                    "creator.event_stream.connected",
                    "creator.input.accepted",
                    "creator.input.idempotent",
                ],
            )
            # Background context preparation and heartbeat can complete in either order.
            self.assertIn("runtime.authority.heartbeat", log_events[9:])
            self.assertTrue(
                {"creator.event_stream.closed", "creator.event_stream.disconnected"}
                & set(log_events[9:])
            )
            self.assertIn("runtime.lifecycle.draining", log_events)
            self.assertIn("creator.session.revoked_all", log_events)
            log_text = next((data_root / "logs").glob("runtime-*.jsonl")).read_text(
                encoding="utf-8"
            )
            self.assertNotIn(creator_bearer, log_text)
            self.assertNotIn(browser_token, log_text)
            self.assertNotIn(message, log_text)
            with psycopg.connect(fixture.runtime_dsn) as database:
                fact_counts = database.execute(
                    """
                    SELECT
                        (SELECT count(*) FROM armi.party_input_interactions),
                        (SELECT count(*) FROM armi.external_evidence),
                        (
                            SELECT count(*) FROM armi.opportunities
                            WHERE evidence_id IS NOT NULL
                        ),
                        (
                            SELECT count(*)
                            FROM armi.scene_timeline_items
                            WHERE source_kind = 'creator_input'
                        ),
                        (
                            SELECT count(*)
                            FROM armi.audit_events
                            WHERE operation = 'creator.input.accepted'
                        )
                    """
                ).fetchone()
                self.assertEqual(fact_counts, (1, 1, 1, 1, 1))
                context_facts = database.execute(
                    """
                    SELECT
                        (
                            SELECT count(*)
                            FROM armi.cognitive_episodes
                            WHERE status = 'cancelled' AND purpose='consider_creator_input'
                              AND failure_code='COGNITION-RUNTIME-INTERRUPTED'
                        ),
                        (
                            SELECT coalesce(sum(jsonb_array_length(context_items)), 0)
                            FROM armi.cognitive_episodes
                        ),
                        (
                            SELECT count(*)
                            FROM armi.artifacts
                            WHERE logical_kind IN (
                                'context.manifest',
                                'context.compiled'
                            )
                        ),
                        (
                            SELECT subject_version
                            FROM armi.subjects
                            WHERE singleton_key = 1
                        )
                    """
                ).fetchone()
                assert context_facts is not None
                self.assertEqual(context_facts[0], 1)
                self.assertGreaterEqual(context_facts[1], 10)
                # The first autonomous consideration is scheduled one minute
                # after activation; only this input has frozen a Context here.
                self.assertEqual(context_facts[2:], (2, 0))
                artifact_identity = database.execute(
                    """
                    SELECT object.content_digest, object.storage_locator
                    FROM armi.external_evidence AS evidence
                    JOIN armi.artifacts AS artifact
                      ON artifact.artifact_id = evidence.artifact_id
                    JOIN armi.artifact_objects AS object
                      ON object.artifact_object_id = artifact.artifact_object_id
                    """
                ).fetchone()
                assert artifact_identity is not None
                self.assertEqual(
                    artifact_identity[0],
                    Digest.from_bytes(message.encode("utf-8")).value,
                )
                self.assertEqual(
                    (artifact_root / artifact_identity[1]).read_bytes(),
                    message.encode("utf-8"),
                )
                mismatched = database.execute(
                    """
                    SELECT scene.scene_id, scene.subject_id, party.party_id
                    FROM armi.interaction_scenes AS scene
                    JOIN armi.parties AS party
                      ON party.represented_subject_id = scene.subject_id
                     AND party.party_kind = 'subject'
                    WHERE scene.scene_key = 'default'
                    """
                ).fetchone()
                assert mismatched is not None
                with self.assertRaises(psycopg.errors.ForeignKeyViolation):
                    database.execute(
                        """
                        INSERT INTO armi.party_input_interactions (
                            interaction_id,
                            subject_id,
                            scene_id,
                            source_party_id,
                            purpose,
                            idempotency_key,
                            request_digest,
                            content_digest,
                            trace_id
                        ) VALUES (
                            %s, %s, %s, %s, 'creator_message',
                            's021-mismatched-identity',
                            'sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa'
                            'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa',
                            'sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb'
                            'bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb',
                            'cccccccccccccccccccccccccccccccc'
                        )
                        """,
                        (_uuid7(), mismatched[1], mismatched[0], mismatched[2]),
                    )
                database.rollback()
            restarted = subprocess.Popen(
                (
                    sys.executable,
                    "-m",
                    "armi_runtime.runtime_entrypoint",
                    "runtime",
                    "start",
                    "--environment-root",
                    str(environment_root),
                    "--creator-web-resources",
                    str(creator_resources),
                ),
                cwd=Path.cwd(),
                env={
                    key: value
                    for key, value in os.environ.items()
                    if not key.startswith("ARMI_")
                },
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
            )
            try:
                restart_deadline = time.monotonic() + 30
                while time.monotonic() < restart_deadline:
                    if restarted.poll() is not None:
                        restart_stdout, restart_stderr = restarted.communicate(
                            timeout=5
                        )
                        self.fail(
                            "restarted Runtime exited before listening: "
                            f"stdout={restart_stdout!r} stderr={restart_stderr!r}"
                        )
                    try:
                        with socket.create_connection(
                            ("127.0.0.1", runtime_port),
                            timeout=0.2,
                        ):
                            break
                    except OSError:
                        time.sleep(0.05)
                else:
                    self.fail("restarted Runtime did not listen")
                restarted.send_signal(signal.CTRL_BREAK_EVENT)
                restart_stdout, restart_stderr = restarted.communicate(timeout=35)
            finally:
                if restarted.poll() is None:
                    restarted.kill()
                    restarted.communicate()
            self.assertEqual(restarted.returncode, 0, restart_stderr)
            self.assertEqual(restart_stdout, "")
            with psycopg.connect(fixture.runtime_dsn) as database:
                self.assertEqual(
                    database.execute(
                        """SELECT count(*) FROM armi.cognitive_episodes
                           WHERE status NOT IN ('completed','cancelled','failed','stale','candidate_rejected')"""
                    ).fetchone(),
                    (0,),
                )
                self.assertEqual(
                    database.execute(
                        """
                        SELECT work_kind, count(*)
                        FROM armi.durable_work
                        GROUP BY work_kind
                        ORDER BY work_kind
                        """
                    ).fetchall(),
                    [
                        ("artifact.object.delete", 1),
                        ("cognition.context.prepare", 1),
                        ("cognition.execute", 1),
                    ],
                )
                self.assertEqual(
                    database.execute(
                        "SELECT count(*) FROM armi.cognitive_attempts"
                    ).fetchone(),
                    (0,),
                )
                self.assertEqual(
                    database.execute(
                        """
                        SELECT count(*)
                        FROM armi.scene_timeline_items
                        WHERE source_kind = 'creator_input'
                        """
                    ).fetchone(),
                    (1,),
                )
        self.assertEqual(status, RecoveryStatus.SAFE.value)
        self.assertEqual(critical_count, 1)
        self.assertEqual(requeued_work, 1)
        self.assertEqual(
            operations,
            (),
        )
        with psycopg.connect(fixture.runtime_dsn) as connection:
            self.assertEqual(
                connection.execute(
                    "SELECT recovery_status, recovery_blocker_count FROM armi.runtime_instances WHERE recovery_status IS NOT NULL"
                ).fetchone(),
                ("safe", 0),
            )
            self.assertEqual(
                connection.execute(
                    """
                    SELECT status, lease_token,
                           current_attempt_id IS NOT NULL,
                           lease_owner IS NOT NULL,
                           reconciliation_required,
                           last_error_code
                    FROM armi.durable_work
                    WHERE work_kind = 'artifact.object.delete'
                    """
                ).fetchone(),
                ("leased", 7, True, True, True, "WORK-RUNTIME-HANDOFF"),
            )
            with self.assertRaises(psycopg.errors.InsufficientPrivilege):
                connection.execute("DELETE FROM armi.runtime_instances")
        with psycopg.connect(fixture.admin_role_dsn) as connection:
            connection.execute(
                "SELECT recovery_status FROM armi.runtime_instances"
            ).fetchall()
        with (
            psycopg.connect(fixture.migrator_dsn) as connection,
            self.assertRaises(psycopg.errors.InsufficientPrivilege),
        ):
            connection.execute("SELECT recovery_status FROM armi.runtime_instances")

    def _prepare_s011_schema(self, fixture: DatabaseFixture) -> None:
        self._install_current(
            fixture.migrator_dsn,
            environment_id=fixture.environment_id,
        )
        with psycopg.connect(fixture.provisioner_dsn, autocommit=True) as connection:
            connection.execute("CREATE SCHEMA s011_test AUTHORIZATION armi_owner")
            connection.execute(
                """
                CREATE TABLE s011_test.entries (
                    id bigint PRIMARY KEY,
                    value bigint NOT NULL CHECK (value >= 0),
                    unique_value text UNIQUE
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE s011_test.subjects (
                    id uuid PRIMARY KEY,
                    version bigint NOT NULL CHECK (version >= 0),
                    value text NOT NULL
                )
                """
            )
            connection.execute("CREATE TABLE s011_test.parents (id bigint PRIMARY KEY)")
            connection.execute(
                """
                CREATE TABLE s011_test.children (
                    id bigint PRIMARY KEY,
                    parent_id bigint NOT NULL
                        REFERENCES s011_test.parents (id)
                )
                """
            )
            connection.execute("GRANT USAGE ON SCHEMA s011_test TO armi_runtime")
            connection.execute(
                "GRANT SELECT, INSERT, UPDATE, DELETE "
                "ON ALL TABLES IN SCHEMA s011_test TO armi_runtime"
            )

    def _drop_s011_schema(self, fixture: DatabaseFixture) -> None:
        with psycopg.connect(fixture.provisioner_dsn, autocommit=True) as connection:
            connection.execute("DROP SCHEMA IF EXISTS s011_test CASCADE")

    async def _new_uow_factory(
        self,
        fixture: DatabaseFixture,
        *,
        pool_max: int = 4,
        statement_timeout_seconds: int = 5,
    ) -> PostgreSQLUnitOfWorkFactory:
        factory = PostgreSQLUnitOfWorkFactory(
            fixture.runtime_dsn,
            environment_id=fixture.environment_id,
            pool_min=1,
            pool_max=pool_max,
            acquire_timeout_seconds=1,
            statement_timeout_seconds=statement_timeout_seconds,
            require_runtime_fence=False,
        )
        await factory.open()
        return factory

    @pytest.mark.test_group("persistence", "subject-commit")
    def test_uow_commit_rollback_hooks_constraints_and_session_reset(self) -> None:
        fixture = self.create_database()
        self._prepare_s011_schema(fixture)

        async def exercise() -> None:
            factory = await self._new_uow_factory(fixture)
            try:
                uow = factory.unit_of_work()
                action = PostCommitAction("audit.append", _uuid7())
                async with uow:
                    connection = uow._connection_for_repository()
                    await connection.execute(
                        "INSERT INTO s011_test.entries "
                        "(id, value, unique_value) VALUES (1, 1, 'first')"
                    )

                    async def append_hook() -> None:
                        await connection.execute(
                            "INSERT INTO s011_test.entries "
                            "(id, value, unique_value) VALUES (2, 2, 'second')"
                        )

                    uow.add_before_commit(append_hook)
                    uow.defer_after_commit(action)
                    self.assertEqual(uow.committed_actions, ())
                self.assertEqual(uow.committed_actions, (action,))

                rolled_back = factory.unit_of_work()
                async with rolled_back:
                    connection = rolled_back._connection_for_repository()
                    await connection.execute(
                        "INSERT INTO s011_test.entries "
                        "(id, value, unique_value) VALUES (3, 3, 'third')"
                    )
                    rolled_back.request_rollback()
                self.assertEqual(rolled_back.committed_actions, ())

                failed = factory.unit_of_work()
                with self.assertRaises(DatabaseTransactionError) as raised:
                    async with failed:
                        connection = failed._connection_for_repository()
                        await connection.execute(
                            "INSERT INTO s011_test.entries "
                            "(id, value, unique_value) VALUES (4, 4, 'first')"
                        )
                self.assertEqual(raised.exception.code, "DB-TX-UNIQUE")
                self.assertNotIn("first", str(raised.exception))

                async def assert_database_error(
                    query: LiteralString,
                    parameters: tuple[object, ...],
                    expected_code: str,
                ) -> None:
                    candidate = factory.unit_of_work()
                    with self.assertRaises(DatabaseTransactionError) as error:
                        async with candidate:
                            await candidate._connection_for_repository().execute(
                                query,
                                parameters,
                            )
                    self.assertEqual(error.exception.code, expected_code)

                await assert_database_error(
                    "INSERT INTO s011_test.entries "
                    "(id, value, unique_value) VALUES (%s, %s, %s)",
                    (5, -1, "check"),
                    "DB-TX-CHECK",
                )
                await assert_database_error(
                    "INSERT INTO s011_test.entries "
                    "(id, value, unique_value) VALUES (%s, %s, %s)",
                    (6, None, "not-null"),
                    "DB-TX-NOT-NULL",
                )
                await assert_database_error(
                    "INSERT INTO s011_test.children (id, parent_id) VALUES (%s, %s)",
                    (1, 999),
                    "DB-TX-FOREIGN-KEY",
                )
                await assert_database_error(
                    "CREATE TABLE s011_test.forbidden (id bigint)",
                    (),
                    "DB-TX-PRIVILEGE",
                )

                before_hook_failed = factory.unit_of_work()
                with self.assertRaisesRegex(RuntimeError, "hook failed"):
                    async with before_hook_failed:
                        connection = before_hook_failed._connection_for_repository()
                        await connection.execute(
                            "INSERT INTO s011_test.entries "
                            "(id, value, unique_value) VALUES (7, 7, 'hook')"
                        )

                        async def fail_hook() -> None:
                            raise RuntimeError("hook failed")

                        before_hook_failed.add_before_commit(fail_hook)
                self.assertEqual(before_hook_failed.committed_actions, ())

                cancellation_started = asyncio.Event()
                never_release = asyncio.Event()

                async def cancel_candidate() -> None:
                    cancelled = factory.unit_of_work()
                    async with cancelled:
                        await cancelled._connection_for_repository().execute(
                            "INSERT INTO s011_test.entries "
                            "(id, value, unique_value) VALUES (8, 8, 'cancelled')"
                        )
                        cancellation_started.set()
                        await never_release.wait()

                cancellation_task = asyncio.create_task(cancel_candidate())
                await cancellation_started.wait()
                cancellation_task.cancel()
                with self.assertRaises(asyncio.CancelledError):
                    await cancellation_task

                contaminated = factory.unit_of_work()
                async with contaminated:
                    connection = contaminated._connection_for_repository()
                    await connection.execute(
                        "SET LOCAL application_name = 's011-contaminated'"
                    )
                    contaminated.request_rollback()
                clean = factory.unit_of_work()
                async with clean:
                    connection = clean._connection_for_repository()
                    row = await (
                        await connection.execute(
                            "SELECT session_user, current_user, "
                            "current_setting('search_path'), "
                            "current_setting('application_name')"
                        )
                    ).fetchone()
                    self.assertEqual(
                        row,
                        (
                            fixture.runtime_role,
                            fixture.runtime_role,
                            "pg_catalog, armi",
                            "",
                        ),
                    )
                    nested = factory.unit_of_work()
                    with self.assertRaises(DatabaseTransactionError) as nested_error:
                        async with nested:
                            pass
                    self.assertEqual(nested_error.exception.code, "DB-TX-NESTED")

                single = await self._new_uow_factory(fixture, pool_max=1)
                held = asyncio.Event()
                release = asyncio.Event()

                async def hold_only_connection() -> None:
                    holder = single.unit_of_work()
                    async with holder:
                        held.set()
                        await release.wait()

                holder_task = asyncio.create_task(hold_only_connection())
                await held.wait()
                waiting = single.unit_of_work()
                with self.assertRaises(DatabaseTransactionError) as pool_error:
                    async with waiting:
                        pass
                self.assertEqual(pool_error.exception.code, "DB-TX-POOL-TIMEOUT")
                release.set()
                await holder_task
                await single.close()
            finally:
                await factory.close()

        try:
            asyncio.run(
                exercise(),
                loop_factory=lambda: asyncio.SelectorEventLoop(
                    selectors.SelectSelector()
                ),
            )
            with psycopg.connect(fixture.provisioner_dsn) as connection:
                rows = connection.execute(
                    "SELECT id FROM s011_test.entries ORDER BY id"
                ).fetchall()
            self.assertEqual(rows, [(1,), (2,)])
        finally:
            self._drop_s011_schema(fixture)

    @pytest.mark.test_group("persistence", "subject-commit")
    def test_cas_deadlock_timeout_and_commit_unknown_are_not_replayed(self) -> None:
        fixture = self.create_database()
        self._prepare_s011_schema(fixture)
        subject_id = _uuid7()
        with psycopg.connect(fixture.provisioner_dsn) as connection:
            connection.execute(
                "INSERT INTO s011_test.subjects (id, version, value) "
                "VALUES (%s, 0, 'initial')",
                (subject_id,),
            )
            connection.execute(
                "INSERT INTO s011_test.entries (id, value, unique_value) "
                "VALUES (10, 10, 'ten'), (11, 11, 'eleven')"
            )

        async def exercise() -> None:
            factory = await self._new_uow_factory(
                fixture,
                statement_timeout_seconds=2,
            )
            try:
                start = asyncio.Event()

                async def cas(value: str) -> bool:
                    await start.wait()
                    uow = factory.unit_of_work()
                    applied = False
                    async with uow:
                        connection = uow._connection_for_repository()
                        cursor = await connection.execute(
                            "UPDATE s011_test.subjects "
                            "SET version = version + 1, value = %s "
                            "WHERE id = %s AND version = %s",
                            (value, subject_id, 0),
                        )
                        applied = cursor.rowcount == 1
                        if not applied:
                            uow.request_rollback()
                    return applied

                tasks = (
                    asyncio.create_task(cas("left")),
                    asyncio.create_task(cas("right")),
                )
                start.set()
                results = await asyncio.gather(*tasks)
                self.assertCountEqual(
                    results,
                    (True, False),
                )

                timeout_uow = factory.unit_of_work()
                with self.assertRaises(DatabaseTransactionError) as timeout_error:
                    async with timeout_uow:
                        await timeout_uow._connection_for_repository().execute(
                            "SELECT pg_catalog.pg_sleep(3)"
                        )
                self.assertEqual(
                    timeout_error.exception.code,
                    "DB-TX-STATEMENT-TIMEOUT",
                )

                first_locked = asyncio.Event()
                second_locked = asyncio.Event()

                async def deadlock(
                    first_id: int,
                    second_id: int,
                    mine: asyncio.Event,
                    other: asyncio.Event,
                ) -> str:
                    uow = factory.unit_of_work()
                    try:
                        async with uow:
                            connection = uow._connection_for_repository()
                            await connection.execute(
                                "SELECT id FROM s011_test.entries "
                                "WHERE id = %s FOR UPDATE",
                                (first_id,),
                            )
                            mine.set()
                            await other.wait()
                            await connection.execute(
                                "SELECT id FROM s011_test.entries "
                                "WHERE id = %s FOR UPDATE",
                                (second_id,),
                            )
                        return "committed"
                    except DatabaseTransactionError as error:
                        return error.code

                deadlock_results = await asyncio.gather(
                    deadlock(10, 11, first_locked, second_locked),
                    deadlock(11, 10, second_locked, first_locked),
                )
                self.assertIn("DB-TX-DEADLOCK", deadlock_results)
                self.assertIn("committed", deadlock_results)

                unknown_uow = factory.unit_of_work()
                with self.assertRaises(DatabaseTransactionError) as unknown_error:
                    async with unknown_uow:
                        connection = unknown_uow._connection_for_repository()
                        await connection.execute(
                            "INSERT INTO s011_test.entries "
                            "(id, value, unique_value) "
                            "VALUES (20, 20, 'unknown')"
                        )
                        unknown_uow.defer_after_commit(
                            PostCommitAction("audit.append", _uuid7())
                        )
                        backend_pid = await (
                            await connection.execute(
                                "SELECT pg_catalog.pg_backend_pid()"
                            )
                        ).fetchone()
                        assert backend_pid is not None

                        def terminate() -> None:
                            with psycopg.connect(
                                fixture.provisioner_dsn,
                                autocommit=True,
                            ) as admin:
                                admin.execute(
                                    "SELECT pg_catalog.pg_terminate_backend(%s)",
                                    (backend_pid[0],),
                                )

                        await asyncio.to_thread(terminate)
                self.assertEqual(
                    unknown_error.exception.code,
                    "DB-TX-COMMIT-UNKNOWN",
                )
                self.assertEqual(unknown_uow.committed_actions, ())
            finally:
                await factory.close()

        try:
            asyncio.run(
                exercise(),
                loop_factory=lambda: asyncio.SelectorEventLoop(
                    selectors.SelectSelector()
                ),
            )
            with psycopg.connect(fixture.provisioner_dsn) as connection:
                subject = connection.execute(
                    "SELECT version, value FROM s011_test.subjects WHERE id = %s",
                    (subject_id,),
                ).fetchone()
                unknown_count = connection.execute(
                    "SELECT count(*) FROM s011_test.entries WHERE id = 20"
                ).fetchone()
            assert subject is not None
            self.assertEqual(subject[0], 1)
            self.assertIn(subject[1], {"left", "right"})
            assert unknown_count is not None
            self.assertIn(unknown_count[0], {0, 1})
        finally:
            self._drop_s011_schema(fixture)

    @pytest.mark.test_group("admin", "runtime")
    def test_real_cli_uses_fixed_scopes_and_safe_output(self) -> None:
        fixture = self.create_database()
        with tempfile.TemporaryDirectory(dir=Path.cwd() / ".tmp") as temporary:
            root = Path(temporary)
            data = root / "data"
            secrets_root = root / "secrets"
            data.mkdir()
            secrets_root.mkdir()
            migrator_file = secrets_root / "migrator"
            runtime_file = secrets_root / "runtime"
            migrator_file.write_text(
                fixture.migrator_dsn, encoding="utf-8", newline="\n"
            )
            runtime_file.write_text(fixture.runtime_dsn, encoding="utf-8", newline="\n")
            (root / "environment.yaml").write_text(
                "\n".join(
                    (
                        "environment:",
                        f"  environment_id: {fixture.environment_id}",
                        f'  data_root: "{data.resolve().as_posix()}"',
                        "creator:",
                        "  port: 45679",
                        "secret_locators:",
                        f"  database.migrator: file:{migrator_file.as_posix()}",
                        f"  database.runtime: file:{runtime_file.as_posix()}",
                    )
                ),
                encoding="utf-8",
                newline="\n",
            )
            admin_binding = _admin_cli_binding(root, fixture)
            install_output = io.StringIO()
            with redirect_stdout(install_output):
                install_exit = main(
                    [
                        "--config",
                        str(admin_binding),
                        "maintenance",
                        "--action",
                        "database_install",
                        "--idempotency-key",
                        "install",
                    ]
                )
            status_output = io.StringIO()
            with redirect_stdout(status_output):
                status_exit = main(
                    [
                        "--config",
                        str(admin_binding),
                        "maintenance",
                        "--action",
                        "database_check",
                    ]
                )
            self.assertEqual(install_exit, 0)
            self.assertEqual(status_exit, 0)
            self.assertEqual(
                json.loads(install_output.getvalue())["result"]["status"], "current"
            )
            output = json.loads(status_output.getvalue())["result"]
            self.assertEqual(output["status"], "current")
            self.assertGreater(output["table_count"], 0)
            combined = install_output.getvalue() + status_output.getvalue()
            self.assertNotIn(fixture.database, combined)
            self.assertNotIn(str(root), combined)
            self.assertNotIn("127.0.0.1", combined)

            error_output = io.StringIO()
            runtime_file.write_text(
                fixture.migrator_dsn, encoding="utf-8", newline="\n"
            )
            with redirect_stdout(error_output):
                exit_code = main(
                    [
                        "--config",
                        str(admin_binding),
                        "maintenance",
                        "--action",
                        "database_check",
                    ]
                )
            self.assertNotEqual(exit_code, 0)
            self.assertIn("DB-ROLE-IDENTITY", error_output.getvalue())
            self.assertNotIn(fixture.database, error_output.getvalue())

    @pytest.mark.test_group("work")
    def test_durable_work_attempt_expiry_and_idempotency(self) -> None:
        fixture = self.create_database()
        self._install_current(
            fixture.migrator_dsn,
            environment_id=fixture.environment_id,
        )

        async def exercise() -> dict[str, object]:
            factory = PostgreSQLUnitOfWorkFactory(
                fixture.runtime_dsn,
                environment_id=fixture.environment_id,
                pool_min=1,
                pool_max=3,
                acquire_timeout_seconds=2,
                statement_timeout_seconds=5,
                require_runtime_fence=False,
            )
            gateway = PostgreSQLDurableWorkGateway(factory)
            now = datetime.now(UTC)
            draft = WorkDraft(
                work_id=WorkId(_uuid7()),
                work_kind=WorkType.ARTIFACT_OBJECT_DELETE,
                owner=WorkOwner("artifact_object_deletion", fixture.environment_id),
                idempotency_key=IdempotencyKey("s014-stable-work"),
                payload=WorkPayloadRef("artifact", _uuid7()),
                payload_digest=Digest.from_bytes(b"s014-work"),
                priority=100,
                not_before=Instant(now - timedelta(seconds=1)),
                deadline_at=Instant(now + timedelta(seconds=30)),
                max_attempts=3,
                trace_id=TraceId("1" + ("4" * 31)),
            )
            await factory.open()
            try:
                async with factory.unit_of_work() as unit_of_work:
                    first = await unit_of_work.work.enqueue(draft)
                async with factory.unit_of_work() as unit_of_work:
                    duplicate = await unit_of_work.work.enqueue(
                        replace(draft, work_id=WorkId(_uuid7()))
                    )
                self.assertEqual(first, duplicate)
                with self.assertRaises(WorkViolation) as conflict:
                    async with factory.unit_of_work() as unit_of_work:
                        await unit_of_work.work.enqueue(
                            replace(
                                draft,
                                work_id=WorkId(_uuid7()),
                                payload_digest=Digest.from_bytes(b"conflict"),
                            )
                        )
                self.assertEqual(
                    conflict.exception.code,
                    "WORK-IDEMPOTENCY-CONFLICT",
                )

                owner_a = _uuid7()
                claims = await asyncio.gather(
                    gateway.claim(
                        work_kind=draft.work_kind,
                        lease_owner=owner_a,
                        lease_seconds=1,
                        limit=1,
                    ),
                    gateway.claim(
                        work_kind=draft.work_kind,
                        lease_owner=_uuid7(),
                        lease_seconds=2,
                        limit=1,
                    ),
                )
                claimed = [record for batch in claims for record in batch]
                self.assertEqual(len(claimed), 1)
                first_lease = claimed[0].lease
                assert first_lease is not None
                # Either concurrent claimant may win; wait beyond both lease
                # durations before asserting takeover.
                await asyncio.sleep(2.5)
                reclaimed_after_expiry = (
                    await gateway.claim(
                        work_kind=draft.work_kind,
                        lease_owner=_uuid7(),
                        lease_seconds=2,
                        limit=1,
                    )
                )[0]
                expiry_lease = reclaimed_after_expiry.lease
                assert expiry_lease is not None
                self.assertEqual(reclaimed_after_expiry.attempt_count, 2)
                self.assertGreater(expiry_lease.token, first_lease.token)
                with self.assertRaises(WorkViolation) as stale:
                    await gateway.renew(first_lease, lease_seconds=2)
                self.assertEqual(stale.exception.code, "WORK-LEASE-STALE")
                released = await gateway.release(
                    expiry_lease,
                    not_before=Instant(datetime.now(UTC)),
                    error_code="WORK-RETRY",
                )
                self.assertEqual(released.status.value, "ready")

                reclaimed = (
                    await gateway.claim(
                        work_kind=draft.work_kind,
                        lease_owner=_uuid7(),
                        lease_seconds=2,
                        limit=1,
                    )
                )[0]
                second_lease = reclaimed.lease
                assert second_lease is not None
                self.assertEqual(reclaimed.attempt_count, 3)
                self.assertGreater(second_lease.token, expiry_lease.token)
                self.assertNotEqual(second_lease.attempt_id, expiry_lease.attempt_id)
                with self.assertRaises(WorkViolation) as stale_completion:
                    await gateway.complete(
                        expiry_lease,
                        WorkResultRef("artifact", _uuid7()),
                    )
                self.assertEqual(
                    stale_completion.exception.code,
                    "WORK-LEASE-STALE",
                )
                completed = await gateway.complete(
                    second_lease,
                    WorkResultRef("artifact", _uuid7()),
                )
                self.assertEqual(completed.status.value, "completed")

                unavailable = WorkDraft(
                    work_id=WorkId(_uuid7()),
                    work_kind=WorkType.ARTIFACT_OBJECT_DELETE,
                    owner=WorkOwner("artifact_object_deletion", _uuid7()),
                    idempotency_key=IdempotencyKey("s014-unavailable-work"),
                    payload_digest=Digest.from_bytes(b"unavailable"),
                    priority=0,
                    not_before=Instant(datetime.now(UTC) - timedelta(seconds=1)),
                    deadline_at=Instant(datetime.now(UTC) + timedelta(seconds=30)),
                    max_attempts=1,
                    trace_id=TraceId("2" + ("4" * 31)),
                )
                async with factory.unit_of_work() as unit_of_work:
                    await unit_of_work.work.enqueue(unavailable)
                cancelled_unavailable = await gateway.cancel_ready(unavailable.work_id)
                self.assertEqual(cancelled_unavailable.status.value, "cancelled")

                exhausted = replace(
                    draft,
                    work_id=WorkId(_uuid7()),
                    idempotency_key=IdempotencyKey("s014-exhausted-work"),
                    payload=None,
                    payload_digest=Digest.from_bytes(b"exhausted"),
                    not_before=Instant(datetime.now(UTC) - timedelta(seconds=1)),
                    deadline_at=Instant(datetime.now(UTC) + timedelta(seconds=30)),
                    max_attempts=1,
                )
                async with factory.unit_of_work() as unit_of_work:
                    await unit_of_work.work.enqueue(exhausted)
                exhausted_claim = (
                    await gateway.claim(
                        work_kind=exhausted.work_kind,
                        lease_owner=_uuid7(),
                        lease_seconds=1,
                        limit=1,
                    )
                )[0]
                self.assertEqual(exhausted_claim.attempt_count, 1)
                await asyncio.sleep(1.1)
                self.assertEqual(
                    await gateway.claim(
                        work_kind=exhausted.work_kind,
                        lease_owner=_uuid7(),
                        lease_seconds=1,
                        limit=1,
                    ),
                    (),
                )

                deadline = replace(
                    draft,
                    work_id=WorkId(_uuid7()),
                    idempotency_key=IdempotencyKey("s014-deadline-work"),
                    payload=None,
                    payload_digest=Digest.from_bytes(b"deadline"),
                    not_before=Instant(datetime.now(UTC) - timedelta(seconds=2)),
                    deadline_at=Instant(datetime.now(UTC) - timedelta(seconds=1)),
                    max_attempts=1,
                )
                async with factory.unit_of_work() as unit_of_work:
                    await unit_of_work.work.enqueue(deadline)
                self.assertEqual(
                    await gateway.claim(
                        work_kind=deadline.work_kind,
                        lease_owner=_uuid7(),
                        lease_seconds=1,
                        limit=1,
                    ),
                    (),
                )

                with psycopg.connect(fixture.provisioner_dsn) as connection:
                    counts = connection.execute(
                        """
                        SELECT
                            (SELECT count(*) FROM armi.durable_work),
                            (
                                SELECT count(*)
                                FROM armi.audit_events
                                WHERE target_ref = %s
                            )
                        """,
                        (draft.work_id.value,),
                    ).fetchone()
                    failures = connection.execute(
                        """
                        SELECT work_id, status, last_error_code,
                               reconciliation_required
                        FROM armi.durable_work
                        WHERE work_id = ANY(%s)
                        ORDER BY last_error_code
                        """,
                        (
                            [
                                exhausted.work_id.value,
                                deadline.work_id.value,
                            ],
                        ),
                    ).fetchall()
                assert counts is not None
                return {
                    "work_count": counts[0],
                    "work_audit_count": counts[1],
                    "attempt_count": reclaimed.attempt_count,
                    "lease_token": second_lease.token,
                    "failures": tuple(
                        (str(row[1]), str(row[2]), bool(row[3])) for row in failures
                    ),
                }
            finally:
                await factory.close()

        result = asyncio.run(
            exercise(),
            loop_factory=lambda: asyncio.SelectorEventLoop(selectors.SelectSelector()),
        )
        self.assertEqual(
            result,
            {
                "work_count": 4,
                "work_audit_count": 6,
                "attempt_count": 3,
                "lease_token": 3,
                "failures": (
                    ("leased", "WORK-ATTEMPTS-EXHAUSTED", True),
                    ("ready", "WORK-DEADLINE", True),
                ),
            },
        )
        with psycopg.connect(fixture.runtime_dsn) as connection:
            with self.assertRaises(psycopg.errors.InsufficientPrivilege):
                connection.execute("DELETE FROM armi.durable_work")
            connection.rollback()

        with psycopg.connect(fixture.admin_role_dsn) as connection:
            connection.execute("SELECT * FROM armi.durable_work").fetchall()
        with psycopg.connect(fixture.migrator_dsn) as connection:
            with self.assertRaises(psycopg.errors.InsufficientPrivilege):
                connection.execute("SELECT * FROM armi.durable_work")
            connection.rollback()


@pytest.fixture
def cognition_database_case():
    case = PostgreSQLIntegrationTests()
    case.setUpClass()
    try:
        yield case
    finally:
        case.tearDownClass()


@pytest.mark.postgresql
@pytest.mark.skipif(not _ADMIN_DSN, reason="isolated PostgreSQL is not running")
@pytest.mark.test_group("cognition", "recovery")
@pytest.mark.parametrize("purpose", list(COGNITION_PURPOSES), ids=lambda p: p.value)
@pytest.mark.parametrize(
    "stage",
    ("context_unfinished", "model_prepared", "cognition_unfinished", "finalizing"),
)
def test_cognition_purpose_ends_without_replaying(
    cognition_database_case, purpose, stage
):
    cognition_database_case._exercise_creator_reply(
        interruption_stage=stage, purpose=purpose.value
    )


if __name__ == "__main__":
    unittest.main()
