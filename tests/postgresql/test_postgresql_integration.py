from __future__ import annotations

import copy
import io
import json
import os
import secrets
import socket
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import redirect_stderr, redirect_stdout
from dataclasses import dataclass
from pathlib import Path
from typing import LiteralString, cast

import psycopg
from armi_runtime.adapters.persistence.schema_gateway import (
    DatabaseViolation,
    PostgreSQLSchemaGateway,
    _PackagedSchema,
)
from armi_runtime.cli import main
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo

_ADMIN_DSN = os.environ.get("S009_ADMIN_DSN")
_ENVIRONMENT_ID = "01980f7d-7b8f-7e2a-8a11-2ab8e1234567"


@dataclass(frozen=True, slots=True)
class DatabaseFixture:
    database: str
    migrator_role: str
    runtime_role: str
    migrator_dsn: str
    runtime_dsn: str
    admin_dsn: str


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
                connection.execute(
                    sql.SQL("DROP ROLE IF EXISTS {}").format(
                        sql.Identifier(fixture.runtime_role)
                    )
                )
                connection.execute(
                    sql.SQL("DROP ROLE IF EXISTS {}").format(
                        sql.Identifier(fixture.migrator_role)
                    )
                )

    def create_database(self, *, locale: str = "C.UTF-8") -> DatabaseFixture:
        assert _ADMIN_DSN is not None
        suffix = secrets.token_hex(5)
        database = f"s009_{suffix}"
        migrator = f"s009_m_{suffix}"
        runtime = f"s009_r_{suffix}"
        migrator_password = secrets.token_urlsafe(24)
        runtime_password = secrets.token_urlsafe(24)
        with psycopg.connect(_ADMIN_DSN, autocommit=True) as connection:
            connection.execute(
                sql.SQL("CREATE ROLE {} LOGIN PASSWORD {}").format(
                    sql.Identifier(migrator),
                    sql.Literal(migrator_password),
                )
            )
            connection.execute(
                sql.SQL("CREATE ROLE {} LOGIN PASSWORD {}").format(
                    sql.Identifier(runtime),
                    sql.Literal(runtime_password),
                )
            )
            connection.execute(
                sql.SQL(
                    "CREATE DATABASE {} TEMPLATE template0 ENCODING 'UTF8' "
                    "LOCALE_PROVIDER builtin BUILTIN_LOCALE {}"
                ).format(sql.Identifier(database), sql.Literal(locale))
            )
            connection.execute(
                sql.SQL("GRANT CREATE ON DATABASE {} TO {}").format(
                    sql.Identifier(database),
                    sql.Identifier(migrator),
                )
            )
        values = conninfo_to_dict(_ADMIN_DSN)
        common = {
            "host": values["host"],
            "port": values["port"],
            "dbname": database,
        }
        fixture = DatabaseFixture(
            database=database,
            migrator_role=migrator,
            runtime_role=runtime,
            migrator_dsn=make_conninfo(
                **common, user=migrator, password=migrator_password
            ),
            runtime_dsn=make_conninfo(
                **common, user=runtime, password=runtime_password
            ),
            admin_dsn=make_conninfo(
                **common,
                user=values["user"],
                password=values["password"],
            ),
        )
        type(self).databases.append(fixture)
        return fixture

    def grant_runtime_probe(self, fixture: DatabaseFixture) -> None:
        with psycopg.connect(fixture.admin_dsn, autocommit=True) as connection:
            connection.execute(
                sql.SQL("GRANT USAGE ON SCHEMA armi TO {}").format(
                    sql.Identifier(fixture.runtime_role)
                )
            )
            connection.execute(
                sql.SQL("GRANT SELECT ON armi.schema_migrations TO {}").format(
                    sql.Identifier(fixture.runtime_role)
                )
            )

    def test_empty_install_repeat_and_concurrent_upgrade_are_stable(self) -> None:
        fixture = self.create_database()
        gateway = PostgreSQLSchemaGateway()
        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(
                executor.map(
                    lambda _: PostgreSQLSchemaGateway().upgrade(fixture.migrator_dsn),
                    range(2),
                )
            )
        self.assertEqual({result.applied_version for result in results}, {1})
        first_digest = results[0].catalog_sha256
        with psycopg.connect(fixture.admin_dsn) as connection:
            first_applied_at = connection.execute(
                "SELECT applied_at FROM armi.schema_migrations WHERE version = 1"
            ).fetchone()
        repeated = gateway.upgrade(fixture.migrator_dsn)
        with psycopg.connect(fixture.admin_dsn) as connection:
            second_applied_at = connection.execute(
                "SELECT applied_at FROM armi.schema_migrations WHERE version = 1"
            ).fetchone()
        self.assertEqual(first_applied_at, second_applied_at)
        self.assertEqual(first_digest, repeated.catalog_sha256)
        summary_file = os.environ.get("S009_SUMMARY_FILE")
        if summary_file is not None:
            Path(summary_file).write_text(
                json.dumps(
                    {
                        "catalog_sha256": repeated.catalog_sha256,
                        "migration_set_sha256": repeated.migration_set_sha256,
                        "target_version": repeated.target_version,
                    },
                    sort_keys=True,
                    separators=(",", ":"),
                )
                + "\n",
                encoding="utf-8",
                newline="\n",
            )
        self.grant_runtime_probe(fixture)
        self.assertEqual(
            gateway.status(fixture.runtime_dsn).safe_view()["status"], "current"
        )

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
            gateway.upgrade(fixture.migrator_dsn)
        self.assertEqual(raised.exception.code, "DB-MIGRATION-FAILED")
        with psycopg.connect(fixture.admin_dsn) as connection:
            exists = connection.execute(
                "SELECT EXISTS (SELECT 1 FROM pg_namespace WHERE nspname = 'armi')"
            ).fetchone()
        self.assertEqual(exists, (False,))

    def test_schema_drift_gap_ahead_hash_and_catalog_damage_are_rejected(
        self,
    ) -> None:
        cases = (
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
                "(2,'future','sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
                "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb','0.0.0')",
                "DB-SCHEMA-AHEAD",
            ),
            (
                "gap",
                "DELETE FROM armi.schema_migrations WHERE version = 1; "
                "INSERT INTO armi.schema_migrations "
                "(version,name,sha256,application_version) VALUES "
                "(2,'future','sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
                "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb','0.0.0')",
                "DB-SCHEMA-GAP",
            ),
            (
                "catalog",
                "ALTER TABLE armi.schema_migrations "
                "DROP CONSTRAINT schema_migrations_name_check",
                "DB-SCHEMA-DIRTY",
            ),
        )
        for label, mutation, expected_code in cases:
            with self.subTest(label=label):
                fixture = self.create_database()
                gateway = PostgreSQLSchemaGateway()
                gateway.upgrade(fixture.migrator_dsn)
                with psycopg.connect(
                    fixture.migrator_dsn, autocommit=True
                ) as connection:
                    connection.execute(sql.SQL(cast(LiteralString, mutation)))
                with self.assertRaises(DatabaseViolation) as raised:
                    gateway.upgrade(fixture.migrator_dsn)
                self.assertEqual(raised.exception.code, expected_code)

    def test_identity_connection_and_runtime_authority_fail_safely(self) -> None:
        fixture = self.create_database()
        gateway = PostgreSQLSchemaGateway()
        gateway.upgrade(fixture.migrator_dsn)
        cases: list[tuple[str, str, str]] = []
        values = conninfo_to_dict(fixture.admin_dsn)
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            probe.bind(("127.0.0.1", 0))
            unused_port = probe.getsockname()[1]
        cases.append(
            (
                "unavailable",
                make_conninfo(
                    host="127.0.0.1",
                    port=unused_port,
                    dbname=fixture.database,
                    user=values["user"],
                    password=values["password"],
                ),
                "DB-CONNECTION-UNAVAILABLE",
            )
        )
        cases.append(("superuser", fixture.admin_dsn, "DB-RUNTIME-ROLE-UNSAFE"))
        cases.append(
            (
                "timezone",
                make_conninfo(fixture.admin_dsn, options="-c timezone=Asia/Shanghai"),
                "DB-DATABASE-IDENTITY",
            )
        )
        for label, dsn, expected_code in cases:
            with self.subTest(label=label):
                with self.assertRaises(DatabaseViolation) as raised:
                    gateway.status(dsn)
                self.assertEqual(raised.exception.code, expected_code)
                self.assertNotIn("127.0.0.1", str(raised.exception))
                self.assertNotIn(fixture.database, str(raised.exception))

        wrong_locale = self.create_database(locale="C")
        with self.assertRaises(DatabaseViolation) as raised:
            gateway.upgrade(wrong_locale.migrator_dsn)
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
            mismatched.status(fixture.admin_dsn, require_safe_runtime_role=False)
        self.assertEqual(raised.exception.code, "DB-PG-VERSION")

    def test_real_cli_uses_fixed_locators_and_safe_output(self) -> None:
        fixture = self.create_database()
        with tempfile.TemporaryDirectory() as temporary:
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
                        f'environment_id = "{_ENVIRONMENT_ID}"',
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
            self.grant_runtime_probe(fixture)
            status_output = io.StringIO()
            with redirect_stdout(status_output):
                status_exit = main(
                    ("db", "status", "--environment-root", str(root.resolve()))
                )
            self.assertEqual(upgrade_exit, 0)
            self.assertEqual(status_exit, 0)
            self.assertEqual(json.loads(status_output.getvalue())["status"], "current")
            combined = upgrade_output.getvalue() + status_output.getvalue()
            self.assertNotIn(fixture.database, combined)
            self.assertNotIn(str(root), combined)
            self.assertNotIn("127.0.0.1", combined)

        error_output = io.StringIO()
        with redirect_stderr(error_output):
            exit_code = main(
                (
                    "db",
                    "status",
                    "--environment-root",
                    str(Path(temporary).resolve()),
                )
            )
        self.assertEqual(exit_code, 2)
        self.assertNotIn(fixture.database, error_output.getvalue())


if __name__ == "__main__":
    unittest.main()
