from __future__ import annotations

import copy
import io
import json
import os
import secrets
import socket
import subprocess
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import redirect_stderr, redirect_stdout
from dataclasses import dataclass
from pathlib import Path
from typing import LiteralString, cast
from uuid import UUID

import psycopg
from armi_admin.persistence.role_session import AdminRoleBoundPool
from armi_runtime.adapters.persistence.role_policy import (
    RoleBoundConnectionPool,
    physical_role_name,
)
from armi_runtime.adapters.persistence.schema_gateway import (
    DatabaseViolation,
    PostgreSQLSchemaGateway,
    _PackagedSchema,
)
from armi_runtime.cli import main
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo

_ADMIN_DSN = os.environ.get("S009_ADMIN_DSN")
_SUMMARY_ENVIRONMENT_ID = UUID("01980f7d-7b8f-7e2a-8a11-2ab8e1234567")


def _uuid7() -> UUID:
    value = bytearray(secrets.token_bytes(16))
    value[6] = (value[6] & 0x0F) | 0x70
    value[8] = (value[8] & 0x3F) | 0x80
    return UUID(bytes=bytes(value))


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
        self.assertEqual({result.applied_version for result in results}, {2})
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
        self.assertEqual(result.applied_version, 2)
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
                "(3,'future','sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
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
                    (2,),
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


if __name__ == "__main__":
    unittest.main()
