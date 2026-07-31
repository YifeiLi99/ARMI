from __future__ import annotations

import asyncio
import copy
import http.client
import io
import json
import os
import secrets
import selectors
import signal
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from collections.abc import AsyncIterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import redirect_stderr, redirect_stdout
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, LiteralString, cast
from uuid import UUID

import psycopg
import rfc8785
from armi_admin.persistence.role_session import AdminRoleBoundPool
from armi_kernel.application import (
    ArtifactPolicy,
    ArtifactPrivacyScope,
    ArtifactViolation,
    AuditQuery,
    BirthManifest,
    BirthResult,
    BirthViolation,
    CasStatus,
    LockPlan,
    LockTarget,
    LockTargetKind,
    PersonalityAnchor,
    PostCommitAction,
    RecoveryStatus,
    RuntimeAuthorityRecord,
    RuntimeAuthorityViolation,
    RuntimeInstanceId,
    SceneKey,
    SceneQueryViolation,
    SceneTimelinePage,
    SceneTimelineQuery,
    WorkDraft,
    WorkId,
    WorkOwner,
    WorkPayloadRef,
    WorkResultRef,
    WorkViolation,
    classify_cas_rows,
)
from armi_kernel.contracts import (
    Digest,
    IdempotencyKey,
    Instant,
    OpaqueCursor,
    TraceId,
)
from armi_runtime.adapters.artifacts.content_store import (
    ContentAddressedArtifactStore,
)
from armi_runtime.adapters.persistence.artifact_catalog import (
    ArtifactCatalogRepository,
)
from armi_runtime.adapters.persistence.audit_events import AuditEventRepository
from armi_runtime.adapters.persistence.birth import (
    BirthRepository,
    ContinuityState,
    probe_continuity,
)
from armi_runtime.adapters.persistence.durable_work import (
    PostgreSQLDurableWorkGateway,
)
from armi_runtime.adapters.persistence.outbox import (
    OutboxDispatcher,
    OutboxEnvelope,
    PostgreSQLOutboxGateway,
)
from armi_runtime.adapters.persistence.recovery import (
    PostgreSQLRuntimeRecovery,
)
from armi_runtime.adapters.persistence.role_policy import (
    RoleBoundConnectionPool,
    physical_role_name,
)
from armi_runtime.adapters.persistence.runtime_authority import (
    PostgreSQLRuntimeAuthority,
)
from armi_runtime.adapters.persistence.scene_timeline import (
    PostgreSQLSceneTimelineQuery,
)
from armi_runtime.adapters.persistence.schema_gateway import (
    DatabaseViolation,
    PostgreSQLSchemaGateway,
    _PackagedSchema,
)
from armi_runtime.adapters.persistence.unit_of_work import (
    PostgreSQLUnitOfWorkFactory,
)
from armi_runtime.adapters.transaction_errors import DatabaseTransactionError
from armi_runtime.cli import main
from armi_runtime.composition.artifacts import (
    ContentAddressedArtifactCoordinator,
)
from armi_runtime.composition.audit import AuditQueryGateway
from armi_runtime.composition.birth import BirthTransaction
from armi_runtime.composition.birth_manifest import packaged_birth_digests
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo

_ADMIN_DSN = os.environ.get("S009_ADMIN_DSN")
_SUMMARY_ENVIRONMENT_ID = UUID("01980f7d-7b8f-7e2a-8a11-2ab8e1234567")


def _uuid7() -> UUID:
    value = bytearray(secrets.token_bytes(16))
    value[6] = (value[6] & 0x0F) | 0x70
    value[8] = (value[8] & 0x3F) | 0x80
    return UUID(bytes=bytes(value))


async def _artifact_chunks(*values: bytes) -> AsyncIterator[bytes]:
    for value in values:
        yield value


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

    def test_empty_install_repeat_and_concurrent_upgrade_are_stable(self) -> None:
        fixture = self.create_database(environment_id=_SUMMARY_ENVIRONMENT_ID)
        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(
                executor.map(
                    lambda _: PostgreSQLSchemaGateway().upgrade(
                        fixture.migrator_dsn,
                        environment_id=fixture.environment_id,
                    ),
                    range(2),
                )
            )
        self.assertEqual({result.applied_version for result in results}, {10})
        self.assertEqual(len({result.catalog_sha256 for result in results}), 1)
        self.assertEqual(
            len({result.privilege_catalog_sha256 for result in results}), 1
        )
        with psycopg.connect(fixture.provisioner_dsn) as connection:
            first_rows = connection.execute(
                "SELECT version, applied_at FROM armi.schema_migrations ORDER BY version"
            ).fetchall()
        repeated = PostgreSQLSchemaGateway().upgrade(
            fixture.migrator_dsn,
            environment_id=fixture.environment_id,
        )
        with psycopg.connect(fixture.provisioner_dsn) as connection:
            second_rows = connection.execute(
                "SELECT version, applied_at FROM armi.schema_migrations ORDER BY version"
            ).fetchall()
        self.assertEqual(first_rows, second_rows)
        status = PostgreSQLSchemaGateway().status(
            fixture.runtime_dsn,
            environment_id=fixture.environment_id,
        )
        self.assertEqual(status.status, "current")
        self.assertEqual(status.catalog_sha256, repeated.catalog_sha256)
        summary_file = os.environ.get("S009_SUMMARY_FILE")
        if summary_file is not None:
            Path(summary_file).write_text(
                json.dumps(
                    {
                        "catalog_sha256": repeated.catalog_sha256,
                        "migration_set_sha256": repeated.migration_set_sha256,
                        "privilege_catalog_sha256": repeated.privilege_catalog_sha256,
                        "role_policy_sha256": repeated.role_policy_sha256,
                        "target_version": repeated.target_version,
                    },
                    sort_keys=True,
                    separators=(",", ":"),
                )
                + "\n",
                encoding="utf-8",
                newline="\n",
            )

    def test_existing_version_one_transfers_owner_and_upgrades(self) -> None:
        database, provisioner_dsn = self._raw_database()
        gateway = PostgreSQLSchemaGateway()
        version, name, digest, migration = gateway._packaged.migrations[0]
        with psycopg.connect(provisioner_dsn) as connection:
            connection.execute(sql.SQL(cast(LiteralString, migration.decode("utf-8"))))
            connection.execute(
                """
                INSERT INTO armi.schema_migrations
                    (version, name, sha256, application_version)
                VALUES (%s, %s, %s, '0.0.0')
                """,
                (version, name, digest),
            )
            connection.commit()
        fixture = self._bootstrap(
            database=database,
            provisioner_dsn=provisioner_dsn,
            environment_id=_uuid7(),
        )
        result = gateway.upgrade(
            fixture.migrator_dsn,
            environment_id=fixture.environment_id,
        )
        self.assertEqual(result.applied_version, 10)
        with psycopg.connect(fixture.provisioner_dsn) as connection:
            owners = connection.execute(
                """
                SELECT namespace_owner.rolname, relation_owner.rolname
                FROM pg_namespace AS namespace
                JOIN pg_roles AS namespace_owner
                  ON namespace_owner.oid = namespace.nspowner
                JOIN pg_class AS relation ON relation.relnamespace = namespace.oid
                JOIN pg_roles AS relation_owner ON relation_owner.oid = relation.relowner
                WHERE namespace.nspname = 'armi'
                  AND relation.relname = 'schema_migrations'
                """
            ).fetchone()
        self.assertEqual(owners, ("armi_owner", "armi_owner"))

    def test_existing_version_three_upgrades_only_normal_audit(self) -> None:
        database, provisioner_dsn = self._raw_database()
        fixture = self._bootstrap(
            database=database,
            provisioner_dsn=provisioner_dsn,
            environment_id=_uuid7(),
        )
        gateway = PostgreSQLSchemaGateway()
        with psycopg.connect(fixture.migrator_dsn, autocommit=True) as connection:
            for version, name, digest, migration in gateway._packaged.migrations[:3]:
                with connection.transaction():
                    connection.execute("SET LOCAL ROLE armi_owner")
                    connection.execute(
                        sql.SQL(cast(LiteralString, migration.decode("utf-8")))
                    )
                    connection.execute(
                        """
                        INSERT INTO armi.schema_migrations
                            (version, name, sha256, application_version)
                        VALUES (%s, %s, %s, '0.0.0')
                        """,
                        (version, name, digest),
                    )
        with psycopg.connect(fixture.provisioner_dsn) as connection:
            before = connection.execute(
                """
                SELECT version, applied_at
                FROM armi.schema_migrations
                ORDER BY version
                """
            ).fetchall()
            self.assertEqual([row[0] for row in before], [1, 2, 3])
            self.assertEqual(
                connection.execute(
                    """
                    SELECT to_regclass('armi.audit_events')
                    """
                ).fetchone(),
                (None,),
            )

        result = gateway.upgrade(
            fixture.migrator_dsn,
            environment_id=fixture.environment_id,
        )

        self.assertEqual(result.applied_version, 10)
        with psycopg.connect(fixture.provisioner_dsn) as connection:
            after = connection.execute(
                """
                SELECT version, applied_at
                FROM armi.schema_migrations
                ORDER BY version
                """
            ).fetchall()
            audit_table = connection.execute(
                "SELECT to_regclass('armi.audit_events')::text"
            ).fetchone()
        self.assertEqual(after[:3], before)
        self.assertEqual(audit_table, ("armi.audit_events",))

    def test_failed_migration_rolls_back_schema_and_ledger(self) -> None:
        fixture = self.create_database()
        gateway = PostgreSQLSchemaGateway()
        packaged = gateway._packaged
        version, name, digest, migration = packaged.migrations[0]
        failing = migration + b"\nSELECT armi_missing_function();\n"
        object.__setattr__(
            gateway,
            "_packaged",
            _PackagedSchema(
                packaged.manifest,
                ((version, name, digest, failing),),
                packaged.invariants,
            ),
        )
        with self.assertRaises(DatabaseViolation) as raised:
            gateway.upgrade(
                fixture.migrator_dsn,
                environment_id=fixture.environment_id,
            )
        self.assertEqual(raised.exception.code, "DB-MIGRATION-FAILED")
        with psycopg.connect(fixture.provisioner_dsn) as connection:
            exists = connection.execute(
                "SELECT EXISTS (SELECT 1 FROM pg_namespace WHERE nspname = 'armi')"
            ).fetchone()
        self.assertEqual(exists, (False,))

    def test_schema_and_role_policy_drift_are_rejected(self) -> None:
        mutations = (
            (
                "hash",
                "UPDATE armi.schema_migrations SET sha256 = "
                "'sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
                "aaaaaaaaaaaaaaaa' WHERE version = 1",
                "DB-SCHEMA-HASH",
            ),
            (
                "dirty",
                "CREATE TABLE armi.unmanifested (id bigint)",
                "DB-SCHEMA-DIRTY",
            ),
            (
                "ahead",
                "INSERT INTO armi.schema_migrations "
                "(version,name,sha256,application_version) VALUES "
                "(11,'future','sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
                "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb','0.0.0')",
                "DB-SCHEMA-AHEAD",
            ),
            (
                "gap",
                "DELETE FROM armi.schema_migrations WHERE version = 1",
                "DB-SCHEMA-GAP",
            ),
            (
                "catalog",
                "ALTER TABLE armi.schema_migrations "
                "DROP CONSTRAINT schema_migrations_name_check",
                "DB-SCHEMA-DIRTY",
            ),
            (
                "public",
                "GRANT USAGE ON SCHEMA armi TO PUBLIC",
                "DB-ROLE-PUBLIC-PRIVILEGE",
            ),
            (
                "owner",
                "ALTER TABLE armi.schema_migrations OWNER TO CURRENT_USER",
                "DB-ROLE-OWNER",
            ),
        )
        for label, mutation, expected_code in mutations:
            with self.subTest(label=label):
                fixture = self.create_database()
                gateway = PostgreSQLSchemaGateway()
                gateway.upgrade(
                    fixture.migrator_dsn,
                    environment_id=fixture.environment_id,
                )
                with psycopg.connect(
                    fixture.provisioner_dsn, autocommit=True
                ) as connection:
                    connection.execute(sql.SQL(cast(LiteralString, mutation)))
                with self.assertRaises(DatabaseViolation) as raised:
                    gateway.status(
                        fixture.runtime_dsn,
                        environment_id=fixture.environment_id,
                    )
                self.assertEqual(raised.exception.code, expected_code)

    def test_role_matrix_cross_environment_and_pool_reset(self) -> None:
        fixture_a = self.create_database()
        fixture_b = self.create_database()
        for fixture in (fixture_a, fixture_b):
            PostgreSQLSchemaGateway().upgrade(
                fixture.migrator_dsn,
                environment_id=fixture.environment_id,
            )
        for dsn in (fixture_a.runtime_dsn, fixture_a.admin_role_dsn):
            with psycopg.connect(dsn) as connection:
                self.assertEqual(
                    connection.execute(
                        "SELECT count(*) FROM armi.schema_migrations"
                    ).fetchone(),
                    (10,),
                )
                for statement in (
                    "CREATE TABLE armi.forbidden (id bigint)",
                    "UPDATE armi.schema_migrations SET application_version = 'x'",
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

        runtime_pool = RoleBoundConnectionPool(
            fixture_a.runtime_dsn,
            environment_id=fixture_a.environment_id,
            role_class="runtime",
        )
        runtime_pool.open()
        try:
            with runtime_pool.connection() as connection:
                connection.execute("SET search_path TO public")
            with runtime_pool.connection() as connection:
                self.assertEqual(
                    connection.execute(
                        "SELECT current_setting('search_path')"
                    ).fetchone(),
                    ("pg_catalog, armi",),
                )
        finally:
            runtime_pool.close()

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

    def test_identity_connection_and_runtime_authority_fail_safely(self) -> None:
        fixture = self.create_database()
        gateway = PostgreSQLSchemaGateway()
        gateway.upgrade(
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
            gateway.upgrade(
                wrong_locale.migrator_dsn,
                environment_id=wrong_locale.environment_id,
            )
        self.assertEqual(raised.exception.code, "DB-DATABASE-IDENTITY")

        altered = copy.deepcopy(gateway._packaged.manifest)
        altered["postgresql"]["server_version_num"] = 180003
        mismatched = PostgreSQLSchemaGateway()
        object.__setattr__(
            mismatched,
            "_packaged",
            _PackagedSchema(
                altered,
                mismatched._packaged.migrations,
                mismatched._packaged.invariants,
            ),
        )
        with self.assertRaises(DatabaseViolation) as raised:
            mismatched.status(
                fixture.runtime_dsn,
                environment_id=fixture.environment_id,
            )
        self.assertEqual(raised.exception.code, "DB-PG-VERSION")

    def test_artifact_registration_reuse_verified_read_and_role_grants(self) -> None:
        fixture = self.create_database()
        PostgreSQLSchemaGateway().upgrade(
            fixture.migrator_dsn,
            environment_id=fixture.environment_id,
        )

        async def reject_unexpected_lock(
            connection: psycopg.AsyncConnection[tuple[Any, ...]],
            target: LockTarget,
        ) -> None:
            del connection, target
            raise AssertionError("artifact registration must not invent lock targets")

        async def exercise(root: Path) -> dict[str, object]:
            factory = PostgreSQLUnitOfWorkFactory(
                fixture.runtime_dsn,
                environment_id=fixture.environment_id,
                lock_acquirer=reject_unexpected_lock,
                pool_min=1,
                pool_max=2,
                acquire_timeout_seconds=1,
                statement_timeout_seconds=5,
                require_runtime_fence=False,
            )
            storage = ContentAddressedArtifactStore(
                root,
                max_object_bytes=1024,
            )
            coordinator = ContentAddressedArtifactCoordinator(
                storage,
                ArtifactCatalogRepository(),
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
                self.assertEqual(duplicate, first)

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
                with self.assertRaisesRegex(
                    ArtifactViolation,
                    "ART-METADATA-CONFLICT",
                ):
                    await coordinator.put(
                        _artifact_chunks(b"authoritative-bytes"),
                        conflicting,
                    )

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
                query_result = await AuditQueryGateway(
                    AuditEventRepository(),
                    factory,
                ).query(AuditQuery(trace_id=policy.producer_trace_id, limit=100))
                self.assertFalse(query_result.truncated)
                self.assertEqual(
                    [record.draft.operation for record in query_result.records],
                    [
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
            artifact_summary = asyncio.run(
                exercise(Path(temporary).resolve() / "artifacts"),
                loop_factory=lambda: asyncio.SelectorEventLoop(
                    selectors.SelectSelector()
                ),
            )

        with psycopg.connect(fixture.runtime_dsn) as connection:
            rows = connection.execute(
                """
                SELECT artifact_id, integrity_status, retention_status, deleted_at
                FROM armi.artifacts
                """
            ).fetchall()
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0][1:], ("missing", "retained", None))
            audit_rows = connection.execute(
                """
                SELECT operation, result_status, target_ref, artifact_digest
                FROM armi.audit_events
                ORDER BY occurred_at, audit_event_id
                """
            ).fetchall()
            self.assertEqual(
                [row[0] for row in audit_rows],
                [
                    "artifact.catalog.registered",
                    "artifact.integrity.missing",
                ],
            )
            self.assertTrue(all(row[1] == "applied" for row in audit_rows))
            self.assertTrue(all(row[2] == rows[0][0] for row in audit_rows))
            self.assertTrue(
                all(row[3] == artifact_summary["content_digest"] for row in audit_rows)
            )
            with self.assertRaises(psycopg.errors.InsufficientPrivilege):
                connection.execute("DELETE FROM armi.artifacts")
            connection.rollback()
            with self.assertRaises(psycopg.errors.InsufficientPrivilege):
                connection.execute(
                    "UPDATE armi.artifacts SET logical_kind = 'forbidden'"
                )
            connection.rollback()
            for statement in (
                "UPDATE armi.audit_events SET operation = 'forbidden'",
                "DELETE FROM armi.audit_events",
                "TRUNCATE armi.audit_events",
            ):
                with self.assertRaises(psycopg.errors.InsufficientPrivilege):
                    connection.execute(cast(LiteralString, statement))
                connection.rollback()
        with (
            psycopg.connect(fixture.admin_role_dsn) as connection,
            self.assertRaises(psycopg.errors.InsufficientPrivilege),
        ):
            connection.execute("SELECT * FROM armi.artifacts").fetchall()
        for dsn in (fixture.admin_role_dsn, fixture.migrator_dsn):
            with (
                psycopg.connect(dsn) as connection,
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
        artifact_summary_file = os.environ.get("S012_ARTIFACT_SUMMARY_FILE")
        if artifact_summary_file is not None:
            Path(artifact_summary_file).write_text(
                json.dumps(
                    artifact_summary,
                    sort_keys=True,
                    separators=(",", ":"),
                )
                + "\n",
                encoding="utf-8",
                newline="\n",
            )

    def test_unique_birth_is_atomic_concurrent_and_idempotent(self) -> None:
        fixture = self.create_database()
        PostgreSQLSchemaGateway().upgrade(
            fixture.migrator_dsn,
            environment_id=fixture.environment_id,
        )
        packaged = packaged_birth_digests()
        anchor = PersonalityAnchor(
            schema_version="armi.personality-anchor.v1",
            voice_style="约 16 岁少女口吻",
            traits=("坦率", "好奇"),
        )
        anchor_digest = Digest.from_bytes(
            rfc8785.dumps(
                {
                    "schema_version": anchor.schema_version,
                    "voice_style": anchor.voice_style,
                    "traits": list(anchor.traits),
                }
            )
        )
        manifest = BirthManifest(
            schema_version="armi.birth-manifest.v1",
            environment_id=fixture.environment_id,
            birth_request_id=_uuid7(),
            creator_party_id=_uuid7(),
            idempotency_key="s015-concurrent-birth",
            personality_anchor=anchor,
            personality_anchor_digest=anchor_digest,
            composition_digest=packaged["composition_digest"],
            birth_contract_digest=packaged["birth_contract_digest"],
            schema_manifest_digest=packaged["schema_manifest_digest"],
            creator_asset_manifest_digest=packaged["creator_asset_manifest_digest"],
            request_digest=Digest.from_bytes(b"s015-birth-request"),
        )

        async def reject_unexpected_lock(
            connection: psycopg.AsyncConnection[tuple[Any, ...]],
            target: LockTarget,
        ) -> None:
            del connection, target
            raise AssertionError("birth must use only its fixed advisory lock")

        async def exercise(root: Path) -> tuple[BirthResult, BirthResult]:
            factory = PostgreSQLUnitOfWorkFactory(
                fixture.runtime_dsn,
                environment_id=fixture.environment_id,
                lock_acquirer=reject_unexpected_lock,
                pool_min=1,
                pool_max=2,
                acquire_timeout_seconds=2,
                statement_timeout_seconds=5,
            )
            transaction = BirthTransaction(
                ContentAddressedArtifactStore(root, max_object_bytes=1024 * 1024),
                ArtifactCatalogRepository(),
                BirthRepository(),
                factory,
            )
            await factory.open()
            try:
                first, replay = await asyncio.gather(
                    transaction.birth(manifest),
                    transaction.birth(manifest),
                )
                self.assertEqual(first.subject_id, replay.subject_id)
                self.assertEqual(first.life_generation_id, replay.life_generation_id)
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

        with psycopg.connect(fixture.provisioner_dsn, autocommit=True) as connection:
            connection.execute(
                """
                DROP TABLE
                    armi.opportunities,
                    armi.external_evidence,
                    armi.creator_input_interactions
                """
            )
            connection.execute(
                """
                ALTER TABLE armi.runtime_recovery_runs
                DROP COLUMN resumable_opportunity_count
                """
            )
            connection.execute(
                "DROP TABLE armi.scene_timeline_items, armi.interaction_scenes"
            )
            connection.execute(
                "DELETE FROM armi.schema_migrations WHERE version IN (9, 10)"
            )
        backfilled = PostgreSQLSchemaGateway().upgrade(
            fixture.migrator_dsn,
            environment_id=fixture.environment_id,
        )
        self.assertEqual(backfilled.applied_version, 10)

        with psycopg.connect(fixture.runtime_dsn) as connection:
            counts = connection.execute(
                """
                SELECT
                    (SELECT count(*) FROM armi.subjects),
                    (SELECT count(*) FROM armi.life_generations),
                    (SELECT count(*) FROM armi.runtime_bundle_activations),
                    (SELECT count(*) FROM armi.parties),
                    (SELECT count(*) FROM armi.prompt_documents),
                    (SELECT count(*) FROM armi.prompt_revisions),
                    (SELECT count(*) FROM armi.subject_component_heads),
                    (SELECT count(*) FROM armi.subject_component_revisions),
                    (SELECT count(*) FROM armi.interaction_scenes),
                    (SELECT count(*) FROM armi.artifacts),
                    (SELECT count(*) FROM armi.audit_events)
                """
            ).fetchone()
            self.assertEqual(counts, (1, 1, 1, 2, 3, 1, 3, 3, 1, 2, 3))
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
            identity_semantics = connection.execute(
                """
                SELECT
                    subject.singleton_key,
                    subject.subject_version,
                    subject.state_epoch,
                    subject.status,
                    generation.generation_no,
                    generation.status,
                    activation.bundle_version,
                    activation.status
                FROM armi.subjects AS subject
                JOIN armi.life_generations AS generation
                  ON generation.life_generation_id =
                     subject.current_generation_id
                JOIN armi.runtime_bundle_activations AS activation
                  ON activation.bundle_activation_id =
                     subject.current_bundle_activation_id
                """
            ).fetchone()
            component_semantics = connection.execute(
                """
                SELECT component_kind, component_version, semantic_payload
                FROM armi.subject_component_revisions
                ORDER BY component_kind
                """
            ).fetchall()
            audit_operations = connection.execute(
                """
                SELECT operation
                FROM armi.audit_events
                ORDER BY operation
                """
            ).fetchall()
            with self.assertRaises(psycopg.errors.InsufficientPrivilege):
                connection.execute("DELETE FROM armi.subjects")
            connection.rollback()

        self.assertEqual(
            probe_continuity(
                fixture.runtime_dsn,
                composition_digest=packaged["composition_digest"],
                schema_manifest_digest=packaged["schema_manifest_digest"],
                birth_contract_digest=packaged["birth_contract_digest"],
                creator_asset_digest=packaged["creator_asset_manifest_digest"],
            ),
            ContinuityState.BORN,
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
            gateway = PostgreSQLSceneTimelineQuery(
                fixture.runtime_dsn,
                environment_id=fixture.environment_id,
                creator_party_id=scene[1],
                cursor_key=b"s" * 32,
                pool_timeout_seconds=2,
            )
            await gateway.open()
            try:
                return await gateway.query(
                    SceneTimelineQuery(SceneKey(scene_key), 50, cursor)
                )
            finally:
                await gateway.close()

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
        with self.assertRaises(SceneQueryViolation) as other_scene:
            asyncio.run(
                read_page(None, "other"),
                loop_factory=lambda: asyncio.SelectorEventLoop(
                    selectors.SelectSelector()
                ),
            )
        self.assertEqual(other_scene.exception.code, "SCENE-NOT-VISIBLE")
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
        with self.assertRaises(SceneQueryViolation) as closed_scene:
            asyncio.run(
                read_page(None),
                loop_factory=lambda: asyncio.SelectorEventLoop(
                    selectors.SelectSelector()
                ),
            )
        self.assertEqual(closed_scene.exception.code, "SCENE-NOT-VISIBLE")
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
        for denied_dsn in (fixture.admin_role_dsn, fixture.migrator_dsn):
            with psycopg.connect(denied_dsn) as connection:
                with self.assertRaises(psycopg.errors.InsufficientPrivilege):
                    connection.execute("SELECT * FROM armi.subjects")
                connection.rollback()
                with self.assertRaises(psycopg.errors.InsufficientPrivilege):
                    connection.execute("SELECT * FROM armi.scene_timeline_items")
                connection.rollback()

        birth_summary_file = os.environ.get("S015_BIRTH_SUMMARY_FILE")
        if birth_summary_file is not None:
            assert identity_semantics is not None
            Path(birth_summary_file).write_text(
                json.dumps(
                    {
                        "schema_version": "armi.s015-birth-summary.v1",
                        "counts": counts,
                        "identity_semantics": identity_semantics,
                        "component_semantics": component_semantics,
                        "audit_operations": audit_operations,
                        "anchor_digest": anchor_digest.value,
                        "package_digests": {
                            name: digest.value
                            for name, digest in sorted(packaged.items())
                        },
                    },
                    ensure_ascii=True,
                    separators=(",", ":"),
                    sort_keys=True,
                )
                + "\n",
                encoding="utf-8",
                newline="\n",
            )

    def test_runtime_authority_heartbeat_takeover_and_fence(self) -> None:
        fixture = self.create_database()
        PostgreSQLSchemaGateway().upgrade(
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
            personality_anchor_digest=Digest.from_bytes(
                rfc8785.dumps(
                    {
                        "schema_version": anchor.schema_version,
                        "voice_style": anchor.voice_style,
                        "traits": list(anchor.traits),
                    }
                )
            ),
            composition_digest=packaged["composition_digest"],
            birth_contract_digest=packaged["birth_contract_digest"],
            schema_manifest_digest=packaged["schema_manifest_digest"],
            creator_asset_manifest_digest=packaged["creator_asset_manifest_digest"],
            request_digest=Digest.from_bytes(b"s016-authority-birth"),
        )

        async def reject_lock(
            connection: psycopg.AsyncConnection[tuple[Any, ...]],
            target: LockTarget,
        ) -> None:
            del connection, target
            raise AssertionError("authority conformance has no business lock target")

        async def exercise(root: Path) -> tuple[int, int, tuple[str, ...]]:
            birth_factory = PostgreSQLUnitOfWorkFactory(
                fixture.runtime_dsn,
                environment_id=fixture.environment_id,
                lock_acquirer=reject_lock,
                pool_min=1,
                pool_max=2,
                acquire_timeout_seconds=2,
                statement_timeout_seconds=5,
            )
            birth = BirthTransaction(
                ContentAddressedArtifactStore(root, max_object_bytes=1024 * 1024),
                ArtifactCatalogRepository(),
                BirthRepository(),
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
                    expected_bundle_digest=packaged["composition_digest"].to_wire(),
                    pool_timeout_seconds=2,
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
                    lock_acquirer=reject_lock,
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
                        async with uow_factory.unit_of_work(LockPlan()):
                            entered.set()
                            await asyncio.sleep(3.2)
                    except DatabaseTransactionError as error:
                        return error.code
                    raise AssertionError("expired fenced transaction committed")

                transaction_task = asyncio.create_task(expire_open_transaction())
                await entered.wait()
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
                        "REVOKE INSERT (audit_event_id) "
                        "ON armi.audit_events FROM armi_runtime"
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
                        "GRANT INSERT (audit_event_id) "
                        "ON armi.audit_events TO armi_runtime"
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
        authority_summary_file = os.environ.get("S016_AUTHORITY_SUMMARY_FILE")
        if authority_summary_file is not None:
            Path(authority_summary_file).write_text(
                json.dumps(
                    {
                        "schema_version": "armi.s016-authority-summary.v1",
                        "first_fence_token": first_token,
                        "takeover_fence_token": second_token,
                        "operations": operations,
                        "real_heartbeat_seconds": 10,
                        "stale_writer_rejected": True,
                        "expired_commit_rolled_back": True,
                        "audit_atomic": True,
                    },
                    ensure_ascii=True,
                    separators=(",", ":"),
                    sort_keys=True,
                )
                + "\n",
                encoding="utf-8",
                newline="\n",
            )

        with psycopg.connect(fixture.runtime_dsn) as connection:
            with self.assertRaises(psycopg.errors.InsufficientPrivilege):
                connection.execute("DELETE FROM armi.runtime_instances")
            connection.rollback()
            with self.assertRaises(psycopg.errors.InsufficientPrivilege):
                connection.execute("TRUNCATE armi.runtime_instances")
        for dsn in (fixture.admin_role_dsn, fixture.migrator_dsn):
            with (
                psycopg.connect(dsn) as connection,
                self.assertRaises(psycopg.errors.InsufficientPrivilege),
            ):
                connection.execute("SELECT * FROM armi.runtime_instances")

    def test_runtime_recovery_reaches_safe_without_starting_workers(self) -> None:
        fixture = self.create_database()
        PostgreSQLSchemaGateway().upgrade(
            fixture.migrator_dsn,
            environment_id=fixture.environment_id,
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
            personality_anchor_digest=Digest.from_bytes(
                rfc8785.dumps(
                    {
                        "schema_version": anchor.schema_version,
                        "voice_style": anchor.voice_style,
                        "traits": list(anchor.traits),
                    }
                )
            ),
            composition_digest=packaged["composition_digest"],
            birth_contract_digest=packaged["birth_contract_digest"],
            schema_manifest_digest=packaged["schema_manifest_digest"],
            creator_asset_manifest_digest=packaged["creator_asset_manifest_digest"],
            request_digest=Digest.from_bytes(b"s017-recovery-birth"),
        )

        async def reject_lock(
            connection: psycopg.AsyncConnection[tuple[Any, ...]],
            target: LockTarget,
        ) -> None:
            del connection, target
            raise AssertionError("recovery conformance has no business lock target")

        async def exercise(
            root: Path,
        ) -> tuple[str, int, int, int, tuple[str, ...]]:
            birth_factory = PostgreSQLUnitOfWorkFactory(
                fixture.runtime_dsn,
                environment_id=fixture.environment_id,
                lock_acquirer=reject_lock,
                pool_min=1,
                pool_max=2,
                acquire_timeout_seconds=2,
                statement_timeout_seconds=5,
            )
            birth = BirthTransaction(
                ContentAddressedArtifactStore(root, max_object_bytes=1024 * 1024),
                ArtifactCatalogRepository(),
                BirthRepository(),
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
                    expected_bundle_digest=packaged["composition_digest"].to_wire(),
                    pool_timeout_seconds=2,
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
                outbox_id = _uuid7()
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
                            %s, 'recovery_probe', 'runtime', %s,
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
                    connection.execute(
                        """
                        INSERT INTO armi.outbox_items (
                            outbox_item_id, work_id, message_kind,
                            payload_digest, status, available_at,
                            claimed_by, claim_expires_at, claim_token,
                            attempt_count, max_attempts, trace_id
                        )
                        VALUES (
                            %s, %s, 'work.available',
                            'sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb'
                            'bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb',
                            'claimed', statement_timestamp(), %s,
                            statement_timestamp() + interval '1 second',
                            9, 1, 3, %s
                        )
                        """,
                        (
                            outbox_id,
                            work_id,
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
                recovery = PostgreSQLRuntimeRecovery(
                    fixture.runtime_dsn,
                    environment_id=fixture.environment_id,
                    data_root=root.parent,
                    max_object_bytes=1024 * 1024,
                    pool_timeout_seconds=2,
                    authority_admission=lambda: record.fence,
                )
                await recovery.open()
                try:
                    summary = await recovery.recover()
                finally:
                    await recovery.close()
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
                summary.critical_artifact_count,
                summary.requeued_work_count,
                summary.requeued_outbox_count,
                operations,
            )

        with tempfile.TemporaryDirectory(dir=Path.cwd() / ".tmp") as temporary:
            environment_root = Path(temporary).resolve()
            data_root = environment_root / "data"
            secrets_root = environment_root / "secrets"
            data_root.mkdir()
            secrets_root.mkdir()
            artifact_root = data_root / "artifacts"
            status, critical_count, requeued_work, requeued_outbox, operations = (
                asyncio.run(
                    exercise(artifact_root),
                    loop_factory=lambda: asyncio.SelectorEventLoop(
                        selectors.SelectSelector()
                    ),
                )
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
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
                listener.bind(("127.0.0.1", 0))
                runtime_port = int(listener.getsockname()[1])
            (environment_root / "environment.toml").write_text(
                "\n".join(
                    (
                        "[environment]",
                        f'environment_id = "{fixture.environment_id}"',
                        f'data_root = "{data_root.as_posix()}"',
                        "",
                        "[creator]",
                        f"port = {runtime_port}",
                        "",
                        "[secret_locators]",
                        f'"database.runtime" = "file:{runtime_secret.as_posix()}"',
                        f'"creator.bearer" = "file:{creator_secret.as_posix()}"',
                        "",
                    )
                ),
                encoding="utf-8",
                newline="\n",
            )
            process = subprocess.Popen(
                (
                    str(Path(".venv/Scripts/armi.exe").resolve()),
                    "runtime",
                    "start",
                    "--environment-root",
                    str(environment_root),
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
                        self.fail("born Runtime exited before listening")
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
                    self.fail(
                        "born Runtime did not listen; "
                        f"stdout={stdout!r}; stderr={stderr!r}"
                    )
                connection = http.client.HTTPConnection(
                    "127.0.0.1",
                    runtime_port,
                    timeout=5,
                )
                try:
                    connection.request(
                        "POST",
                        "/v1/browser-bootstrap-codes",
                        body=b"",
                        headers={
                            "Authorization": f"Bearer {creator_bearer}",
                            "Content-Length": "0",
                        },
                    )
                    issued_response = connection.getresponse()
                    issued = json.loads(issued_response.read())
                    self.assertEqual(issued_response.status, 200)
                    code = issued["bootstrap_code"]
                    body = json.dumps(
                        {"bootstrap_code": code},
                        separators=(",", ":"),
                    ).encode()
                    browser_boundary_headers = {
                        "Origin": f"http://127.0.0.1:{runtime_port}",
                        "Sec-Fetch-Site": "same-origin",
                        "Sec-Fetch-Mode": "cors",
                        "Sec-Fetch-Dest": "empty",
                    }
                    connection.request(
                        "POST",
                        "/v1/browser-sessions",
                        body=body,
                        headers={
                            **browser_boundary_headers,
                            "Content-Type": "application/json",
                            "Content-Length": str(len(body)),
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
                        ("ready", "ready"),
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
                    self.assertEqual(stream_response.readline(), b"retry: 1000\n")
                    self.assertEqual(stream_response.readline(), b"\n")
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
                    connection.request(
                        "POST",
                        "/v1/scenes/default/messages",
                        body=input_body,
                        headers=input_headers,
                    )
                    replay_response = connection.getresponse()
                    replay = json.loads(replay_response.read())
                    self.assertEqual(replay_response.status, 202)
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
                    self.assertEqual(operation["details"], accepted["details"])
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
                        ),
                        (
                            "creator_input",
                            accepted["details"]["interaction_id"],
                            "accepted",
                            accepted["result_ref"],
                        ),
                    )
                    self.assertEqual(stream_response.readline(), b": keepalive\n")
                    self.assertEqual(stream_response.readline(), b"\n")
                    logout_connection = http.client.HTTPConnection(
                        "127.0.0.1",
                        runtime_port,
                        timeout=5,
                    )
                    logout_connection.request(
                        "DELETE",
                        "/v1/browser-sessions/current",
                        headers=authenticated_headers,
                    )
                    logout_response = logout_connection.getresponse()
                    logout_response.read()
                    self.assertEqual(logout_response.status, 204)
                    self.assertEqual(stream_response.readline(), b"")
                    logout_connection.close()
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
                log_events,
                [
                    "runtime.lifecycle.starting",
                    "runtime.authority.acquired",
                    "runtime.lifecycle.recovering",
                    "runtime.recovery.safe",
                    "runtime.lifecycle.ready",
                    "creator.bootstrap.issued",
                    "creator.session.established",
                    "creator.event_stream.connected",
                    "creator.input.accepted",
                    "creator.input.idempotent",
                    "runtime.authority.heartbeat",
                    "creator.event_stream.closed",
                    "creator.session.revoked",
                    "runtime.lifecycle.draining",
                    "creator.session.revoked_all",
                    "runtime.authority.released",
                    "runtime.lifecycle.stopped",
                ],
            )
            log_text = next((data_root / "logs").glob("runtime-*.jsonl")).read_text(
                encoding="utf-8"
            )
            self.assertNotIn(creator_bearer, log_text)
            self.assertNotIn(code, log_text)
            self.assertNotIn(browser_token, log_text)
            self.assertNotIn(message, log_text)
            with psycopg.connect(fixture.runtime_dsn) as database:
                fact_counts = database.execute(
                    """
                    SELECT
                        (SELECT count(*) FROM armi.creator_input_interactions),
                        (SELECT count(*) FROM armi.external_evidence),
                        (SELECT count(*) FROM armi.opportunities),
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
                artifact_identity = database.execute(
                    """
                    SELECT artifact.content_digest, artifact.storage_locator
                    FROM armi.external_evidence AS evidence
                    JOIN armi.artifacts AS artifact
                      ON artifact.artifact_id = evidence.artifact_id
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
                        INSERT INTO armi.creator_input_interactions (
                            creator_interaction_id,
                            subject_id,
                            scene_id,
                            creator_party_id,
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
                    str(Path(".venv/Scripts/armi.exe").resolve()),
                    "runtime",
                    "start",
                    "--environment-root",
                    str(environment_root),
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
                        self.fail("restarted Runtime exited before listening")
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
                recovery_count = database.execute(
                    """
                    SELECT resumable_opportunity_count
                    FROM armi.runtime_recovery_runs
                    ORDER BY started_at DESC, recovery_run_id DESC
                    LIMIT 1
                    """
                ).fetchone()
                self.assertEqual(recovery_count, (1,))
                self.assertEqual(
                    database.execute(
                        "SELECT count(*) FROM armi.durable_work"
                    ).fetchone(),
                    (1,),
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
        self.assertEqual(critical_count, 2)
        self.assertEqual((requeued_work, requeued_outbox), (1, 1))
        self.assertEqual(
            operations,
            ("runtime.recovery.started", "runtime.recovery.safe"),
        )
        recovery_summary_file = os.environ.get("S017_RECOVERY_SUMMARY_FILE")
        if recovery_summary_file is not None:
            Path(recovery_summary_file).write_text(
                json.dumps(
                    {
                        "schema_version": "armi.s017-recovery-summary.v1",
                        "status": status,
                        "critical_artifact_count": critical_count,
                        "requeued_work_count": requeued_work,
                        "requeued_outbox_count": requeued_outbox,
                        "work_lease_token_preserved": 7,
                        "outbox_claim_token_preserved": 9,
                        "audit_operations": operations,
                        "workers_started": False,
                    },
                    ensure_ascii=True,
                    separators=(",", ":"),
                    sort_keys=True,
                )
                + "\n",
                encoding="utf-8",
                newline="\n",
            )
        with psycopg.connect(fixture.runtime_dsn) as connection:
            self.assertEqual(
                connection.execute(
                    "SELECT status, blocker_count FROM armi.runtime_recovery_runs"
                ).fetchone(),
                ("safe", 0),
            )
            self.assertEqual(
                connection.execute(
                    """
                    SELECT status, lease_token, current_attempt_id, lease_owner
                    FROM armi.durable_work
                    """
                ).fetchone(),
                ("ready", 7, None, None),
            )
            self.assertEqual(
                connection.execute(
                    """
                    SELECT status, claim_token, claimed_by
                    FROM armi.outbox_items
                    """
                ).fetchone(),
                ("ready", 9, None),
            )
            with self.assertRaises(psycopg.errors.InsufficientPrivilege):
                connection.execute("DELETE FROM armi.runtime_recovery_runs")
        for dsn in (fixture.admin_role_dsn, fixture.migrator_dsn):
            with (
                psycopg.connect(dsn) as connection,
                self.assertRaises(psycopg.errors.InsufficientPrivilege),
            ):
                connection.execute("SELECT * FROM armi.runtime_recovery_runs")

    def _prepare_s011_schema(self, fixture: DatabaseFixture) -> None:
        PostgreSQLSchemaGateway().upgrade(
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
        async def acquire_subject_lock(
            connection: psycopg.AsyncConnection[tuple[Any, ...]],
            target: LockTarget,
        ) -> None:
            if target.kind is not LockTargetKind.SUBJECT:
                raise ValueError("test acquirer only owns subject locks")
            row = await (
                await connection.execute(
                    "SELECT version FROM s011_test.subjects WHERE id = %s FOR UPDATE",
                    (target.object_id,),
                )
            ).fetchone()
            if row is None:
                raise ValueError("subject lock target is missing")

        factory = PostgreSQLUnitOfWorkFactory(
            fixture.runtime_dsn,
            environment_id=fixture.environment_id,
            lock_acquirer=acquire_subject_lock,
            pool_min=1,
            pool_max=pool_max,
            acquire_timeout_seconds=1,
            statement_timeout_seconds=statement_timeout_seconds,
            require_runtime_fence=False,
        )
        await factory.open()
        return factory

    def test_uow_commit_rollback_hooks_constraints_and_session_reset(self) -> None:
        fixture = self.create_database()
        self._prepare_s011_schema(fixture)

        async def exercise() -> None:
            factory = await self._new_uow_factory(fixture)
            try:
                uow = factory.unit_of_work(LockPlan())
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

                rolled_back = factory.unit_of_work(LockPlan())
                async with rolled_back:
                    connection = rolled_back._connection_for_repository()
                    await connection.execute(
                        "INSERT INTO s011_test.entries "
                        "(id, value, unique_value) VALUES (3, 3, 'third')"
                    )
                    rolled_back.request_rollback()
                self.assertEqual(rolled_back.committed_actions, ())

                failed = factory.unit_of_work(LockPlan())
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
                    candidate = factory.unit_of_work(LockPlan())
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

                before_hook_failed = factory.unit_of_work(LockPlan())
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
                    cancelled = factory.unit_of_work(LockPlan())
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

                contaminated = factory.unit_of_work(LockPlan())
                async with contaminated:
                    connection = contaminated._connection_for_repository()
                    await connection.execute(
                        "SET LOCAL application_name = 's011-contaminated'"
                    )
                    contaminated.request_rollback()
                clean = factory.unit_of_work(LockPlan())
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
                    nested = factory.unit_of_work(LockPlan())
                    with self.assertRaises(DatabaseTransactionError) as nested_error:
                        async with nested:
                            pass
                    self.assertEqual(nested_error.exception.code, "DB-TX-NESTED")

                single = await self._new_uow_factory(fixture, pool_max=1)
                held = asyncio.Event()
                release = asyncio.Event()

                async def hold_only_connection() -> None:
                    holder = single.unit_of_work(LockPlan())
                    async with holder:
                        held.set()
                        await release.wait()

                holder_task = asyncio.create_task(hold_only_connection())
                await held.wait()
                waiting = single.unit_of_work(LockPlan())
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

                async def cas(value: str) -> CasStatus:
                    await start.wait()
                    plan = LockPlan.for_cas(
                        LockTarget(LockTargetKind.SUBJECT, subject_id, 0)
                    )
                    uow = factory.unit_of_work(plan)
                    result = CasStatus.CONFLICT
                    async with uow:
                        connection = uow._connection_for_repository()
                        cursor = await connection.execute(
                            "UPDATE s011_test.subjects "
                            "SET version = version + 1, value = %s "
                            "WHERE id = %s AND version = %s",
                            (value, subject_id, 0),
                        )
                        result = classify_cas_rows(cursor.rowcount)
                        if result is CasStatus.CONFLICT:
                            uow.request_rollback()
                    return result

                tasks = (
                    asyncio.create_task(cas("left")),
                    asyncio.create_task(cas("right")),
                )
                start.set()
                results = await asyncio.gather(*tasks)
                self.assertCountEqual(
                    results,
                    (CasStatus.APPLIED, CasStatus.CONFLICT),
                )

                timeout_uow = factory.unit_of_work(LockPlan())
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
                    uow = factory.unit_of_work(LockPlan())
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

                unknown_uow = factory.unit_of_work(LockPlan())
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
            (root / "environment.toml").write_text(
                "\n".join(
                    (
                        "[environment]",
                        f'environment_id = "{fixture.environment_id}"',
                        f'data_root = "{data.resolve().as_posix()}"',
                        "",
                        "[creator]",
                        "port = 45679",
                        "",
                        "[secret_locators]",
                        f'"database.migrator" = "file:{migrator_file.as_posix()}"',
                        f'"database.runtime" = "file:{runtime_file.as_posix()}"',
                        "",
                    )
                ),
                encoding="utf-8",
                newline="\n",
            )
            upgrade_output = io.StringIO()
            with redirect_stdout(upgrade_output):
                upgrade_exit = main(
                    ("db", "upgrade", "--environment-root", str(root.resolve()))
                )
            status_output = io.StringIO()
            with redirect_stdout(status_output):
                status_exit = main(
                    ("db", "status", "--environment-root", str(root.resolve()))
                )
            self.assertEqual(upgrade_exit, 0)
            self.assertEqual(status_exit, 0)
            output = json.loads(status_output.getvalue())
            self.assertEqual(output["status"], "current")
            self.assertIsNotNone(output["role_policy_sha256"])
            self.assertIsNotNone(output["privilege_catalog_sha256"])
            combined = upgrade_output.getvalue() + status_output.getvalue()
            self.assertNotIn(fixture.database, combined)
            self.assertNotIn(str(root), combined)
            self.assertNotIn("127.0.0.1", combined)

            error_output = io.StringIO()
            runtime_file.write_text(
                fixture.migrator_dsn, encoding="utf-8", newline="\n"
            )
            with redirect_stderr(error_output):
                exit_code = main(
                    ("db", "status", "--environment-root", str(root.resolve()))
                )
            self.assertNotEqual(exit_code, 0)
            self.assertIn("DB-ROLE-IDENTITY", error_output.getvalue())
            self.assertNotIn(fixture.database, error_output.getvalue())

    def test_durable_work_attempt_expiry_idempotency_and_outbox(self) -> None:
        fixture = self.create_database()
        PostgreSQLSchemaGateway().upgrade(
            fixture.migrator_dsn,
            environment_id=fixture.environment_id,
        )

        async def reject_unexpected_lock(
            connection: psycopg.AsyncConnection[tuple[Any, ...]],
            target: LockTarget,
        ) -> None:
            del connection, target
            raise AssertionError("durable work must not invent business lock targets")

        async def exercise() -> dict[str, object]:
            factory = PostgreSQLUnitOfWorkFactory(
                fixture.runtime_dsn,
                environment_id=fixture.environment_id,
                lock_acquirer=reject_unexpected_lock,
                pool_min=1,
                pool_max=3,
                acquire_timeout_seconds=2,
                statement_timeout_seconds=5,
                require_runtime_fence=False,
            )
            gateway = PostgreSQLDurableWorkGateway(factory)
            outbox_gateway = PostgreSQLOutboxGateway(factory)
            now = datetime.now(UTC)
            draft = WorkDraft(
                work_id=WorkId(_uuid7()),
                work_kind="work.conformance",
                owner=WorkOwner("environment", fixture.environment_id),
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
                async with factory.unit_of_work(LockPlan()) as unit_of_work:
                    first = await unit_of_work.work.enqueue(draft)
                async with factory.unit_of_work(LockPlan()) as unit_of_work:
                    duplicate = await unit_of_work.work.enqueue(
                        replace(draft, work_id=WorkId(_uuid7()))
                    )
                self.assertEqual(first, duplicate)
                with self.assertRaises(WorkViolation) as conflict:
                    async with factory.unit_of_work(LockPlan()) as unit_of_work:
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
                        lease_owner=owner_a,
                        lease_seconds=1,
                        limit=1,
                    ),
                    gateway.claim(
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

                deliveries: list[UUID] = []

                async def conformance_handler(envelope: OutboxEnvelope) -> None:
                    deliveries.append(envelope.work_id.value)

                dispatcher = OutboxDispatcher(
                    outbox_gateway,
                    {"work.available": conformance_handler},
                )
                dispatched = await dispatcher.dispatch_once(
                    claim_owner=_uuid7(),
                    lease_seconds=2,
                    limit=10,
                )
                self.assertEqual(dispatched, 1)
                self.assertEqual(deliveries, [draft.work_id.value])

                unavailable = WorkDraft(
                    work_id=WorkId(_uuid7()),
                    work_kind="work.unavailable",
                    owner=WorkOwner("environment", fixture.environment_id),
                    idempotency_key=IdempotencyKey("s014-unavailable-work"),
                    payload_digest=Digest.from_bytes(b"unavailable"),
                    priority=0,
                    not_before=Instant(datetime.now(UTC) - timedelta(seconds=1)),
                    deadline_at=Instant(datetime.now(UTC) + timedelta(seconds=30)),
                    max_attempts=1,
                    trace_id=TraceId("2" + ("4" * 31)),
                )
                async with factory.unit_of_work(LockPlan()) as unit_of_work:
                    await unit_of_work.work.enqueue(unavailable)
                unavailable_dispatcher = OutboxDispatcher(outbox_gateway, {})
                self.assertEqual(
                    await unavailable_dispatcher.dispatch_once(
                        claim_owner=_uuid7(),
                        lease_seconds=2,
                        limit=10,
                    ),
                    1,
                )
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
                async with factory.unit_of_work(LockPlan()) as unit_of_work:
                    await unit_of_work.work.enqueue(exhausted)
                exhausted_claim = (
                    await gateway.claim(
                        lease_owner=_uuid7(),
                        lease_seconds=1,
                        limit=1,
                    )
                )[0]
                self.assertEqual(exhausted_claim.attempt_count, 1)
                await asyncio.sleep(1.1)
                self.assertEqual(
                    await gateway.claim(
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
                async with factory.unit_of_work(LockPlan()) as unit_of_work:
                    await unit_of_work.work.enqueue(deadline)
                self.assertEqual(
                    await gateway.claim(
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
                            (SELECT count(*) FROM armi.outbox_items),
                            (
                                SELECT count(*)
                                FROM armi.audit_events
                                WHERE target_ref = %s
                            )
                        """,
                        (draft.work_id.value,),
                    ).fetchone()
                    unavailable_outbox = connection.execute(
                        """
                        SELECT status, last_error_code
                        FROM armi.outbox_items
                        WHERE work_id = %s
                        """,
                        (unavailable.work_id.value,),
                    ).fetchone()
                    failures = connection.execute(
                        """
                        SELECT work_id, status, last_error_code
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
                    "outbox_count": counts[1],
                    "work_audit_count": counts[2],
                    "attempt_count": reclaimed.attempt_count,
                    "lease_token": second_lease.token,
                    "deliveries": len(deliveries),
                    "unavailable_outbox": unavailable_outbox,
                    "failures": tuple((str(row[1]), str(row[2])) for row in failures),
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
                "outbox_count": 4,
                "work_audit_count": 6,
                "attempt_count": 3,
                "lease_token": 3,
                "deliveries": 1,
                "unavailable_outbox": (
                    "dead",
                    "OUTBOX-HANDLER-UNAVAILABLE",
                ),
                "failures": (
                    ("failed", "WORK-ATTEMPTS-EXHAUSTED"),
                    ("failed", "WORK-DEADLINE"),
                ),
            },
        )
        work_summary_file = os.environ.get("S014_WORK_SUMMARY_FILE")
        if work_summary_file is not None:
            Path(work_summary_file).write_text(
                json.dumps(
                    result,
                    ensure_ascii=True,
                    separators=(",", ":"),
                    sort_keys=True,
                )
                + "\n",
                encoding="utf-8",
                newline="\n",
            )

        with psycopg.connect(fixture.runtime_dsn) as connection:
            for table in ("durable_work", "outbox_items"):
                with self.assertRaises(psycopg.errors.InsufficientPrivilege):
                    connection.execute(
                        sql.SQL("DELETE FROM armi.{}").format(sql.Identifier(table))
                    )
                connection.rollback()

        for dsn in (fixture.admin_role_dsn, fixture.migrator_dsn):
            with psycopg.connect(dsn) as connection:
                for table in ("durable_work", "outbox_items"):
                    with self.assertRaises(psycopg.errors.InsufficientPrivilege):
                        connection.execute(
                            sql.SQL("SELECT * FROM armi.{}").format(
                                sql.Identifier(table)
                            )
                        )
                    connection.rollback()


if __name__ == "__main__":
    unittest.main()
