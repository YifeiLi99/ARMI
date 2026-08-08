"""Install, baseline, inspect, and migrate the authoritative PostgreSQL schema."""

from __future__ import annotations

import hashlib
import json
import re
from contextlib import suppress
from dataclasses import dataclass
from importlib.resources import files
from importlib.resources.abc import Traversable
from typing import Any, Final, LiteralString, cast
from uuid import UUID

import psycopg
from psycopg import sql

from armi_runtime.adapters.database_errors import DatabaseViolation

from .role_policy import PostgreSQLRolePolicyGateway

_RESOURCE_PACKAGE = "armi_runtime.composition.runtime_resources"
_SCHEMA_RESOURCE = "schema"
_BASELINE_MANIFEST = "baseline/manifest.json"
_MIGRATIONS_MANIFEST = "migrations/manifest.json"
_HISTORY_TABLE = "schema_migrations"
_ADVISORY_LOCK: Final = 4_701_932_009
_EXPECTED_POSTGRESQL: Final = 180004
_EXPECTED_PGVECTOR: Final = "0.8.6"
_EXPECTED_PGVECTOR_SCHEMA: Final = "armi_extensions"
_EXPECTED_ENCODING: Final = "UTF8"
_EXPECTED_TIMEZONE: Final = "UTC"
_EXPECTED_LOCALE: Final = "C.UTF-8"
_IDENTIFIER = re.compile(r"^[0-9]{4}_[a-z0-9_]+$", re.ASCII)
_BASELINE_ID: Final = "baseline"
_BASELINE_PATH: Final = "baseline.sql"
_TABLE = re.compile(r"^[a-z][a-z0-9_]*$", re.ASCII)
_TABLE_PATTERN = re.compile(rb"\bCREATE TABLE armi\.([a-z][a-z0-9_]*)\s*\(")


@dataclass(frozen=True, slots=True)
class SchemaStatus:
    status: str
    table_count: int
    baseline_id: str
    migration_count: int
    target_id: str

    def safe_view(self) -> dict[str, object]:
        return {
            "status": self.status,
            "table_count": self.table_count,
            "baseline_id": self.baseline_id,
            "migration_count": self.migration_count,
            "target_id": self.target_id,
        }


@dataclass(frozen=True, slots=True)
class _Migration:
    migration_id: str
    checksum: str
    definition: bytes
    creates_tables: frozenset[str]
    drops_tables: frozenset[str]


@dataclass(frozen=True, slots=True)
class _SchemaPlan:
    baseline_id: str
    baseline_checksum: str
    baseline_definition: bytes
    baseline_tables: frozenset[str]
    migrations: tuple[_Migration, ...]

    @property
    def expected_history(self) -> tuple[tuple[str, str, str], ...]:
        return (
            (self.baseline_id, "baseline", self.baseline_checksum),
            *tuple(
                (migration.migration_id, "migration", migration.checksum)
                for migration in self.migrations
            ),
        )

    @property
    def target_id(self) -> str:
        return self.migrations[-1].migration_id if self.migrations else self.baseline_id

    def tables_after(self, history_count: int) -> frozenset[str]:
        tables = set(self.baseline_tables)
        for migration in self.migrations[: max(0, history_count - 1)]:
            tables.difference_update(migration.drops_tables)
            tables.update(migration.creates_tables)
        return frozenset(tables)


def _digest(value: bytes) -> str:
    return f"sha256:{hashlib.sha256(value).hexdigest()}"


def _strict_json(raw: bytes, *, code: str) -> dict[str, object]:
    def pairs(items: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in items:
            if key in result:
                raise ValueError
            result[key] = value
        return result

    try:
        value = json.loads(raw.decode("utf-8", "strict"), object_pairs_hook=pairs)
    except UnicodeDecodeError, json.JSONDecodeError, ValueError:
        raise DatabaseViolation(
            code, "the packaged schema manifest is invalid"
        ) from None
    if type(value) is not dict:
        raise DatabaseViolation(code, "the packaged schema manifest is invalid")
    return cast(dict[str, object], value)


def _text_list(value: object) -> list[str]:
    if type(value) is not list:
        raise ValueError
    items = cast(list[object], value)
    if any(type(item) is not str for item in items):
        raise ValueError
    return cast(list[str], items)


def _load_schema_plan(resource_root: Traversable | None = None) -> _SchemaPlan:
    root = resource_root or files(_RESOURCE_PACKAGE).joinpath(_SCHEMA_RESOURCE)
    baseline_root = root.joinpath("baseline")
    migrations_root = root.joinpath("migrations")
    try:
        baseline_raw = root.joinpath(_BASELINE_MANIFEST).read_bytes()
        migrations_raw = root.joinpath(_MIGRATIONS_MANIFEST).read_bytes()
    except OSError:
        raise DatabaseViolation(
            "DB-SCHEMA-RESOURCE", "the packaged schema manifests are unavailable"
        ) from None
    baseline = _strict_json(baseline_raw, code="DB-SCHEMA-RESOURCE")
    migrations_value = _strict_json(migrations_raw, code="DB-SCHEMA-RESOURCE")
    try:
        if set(baseline) != {
            "schema_version",
            "baseline_id",
            "path",
            "sha256",
            "tables",
        }:
            raise ValueError
        baseline_id = baseline["baseline_id"]
        if (
            baseline["schema_version"] != "armi.schema-baseline.v1"
            or type(baseline_id) is not str
            or baseline_id != _BASELINE_ID
            or baseline["path"] != _BASELINE_PATH
            or type(baseline["sha256"]) is not str
        ):
            raise ValueError
        declared_tables = _text_list(baseline["tables"])
        if declared_tables != sorted(set(declared_tables)) or any(
            _TABLE.fullmatch(name) is None for name in declared_tables
        ):
            raise ValueError
        baseline_definition = baseline_root.joinpath(_BASELINE_PATH).read_bytes()
        if (
            not baseline_definition.strip()
            or _digest(baseline_definition) != baseline["sha256"]
        ):
            raise ValueError
        discovered_tables = {
            match.group(1).decode("ascii")
            for match in _TABLE_PATTERN.finditer(baseline_definition)
        }
        actual_paths = sorted(
            entry.name
            for entry in baseline_root.iterdir()
            if entry.name.endswith(".sql")
        )
        if actual_paths != [_BASELINE_PATH]:
            raise ValueError
        if (
            discovered_tables != set(declared_tables)
            or _HISTORY_TABLE not in discovered_tables
        ):
            raise ValueError

        if set(migrations_value) != {"schema_version", "baseline_id", "migrations"}:
            raise ValueError
        migration_values = migrations_value["migrations"]
        if (
            migrations_value["schema_version"] != "armi.schema-migrations.v1"
            or migrations_value["baseline_id"] != baseline_id
            or type(migration_values) is not list
        ):
            raise ValueError
        migration_paths: list[str] = []
        migrations: list[_Migration] = []
        target_tables = set(declared_tables)
        previous_id: str | None = None
        for item in cast(list[object], migration_values):
            if type(item) is not dict:
                raise ValueError
            entry = cast(dict[str, object], item)
            if set(entry) != {
                "migration_id",
                "path",
                "sha256",
                "creates_tables",
                "drops_tables",
            }:
                raise ValueError
            migration_id = entry["migration_id"]
            path = entry["path"]
            checksum = entry["sha256"]
            creates = _text_list(entry["creates_tables"])
            drops = _text_list(entry["drops_tables"])
            if (
                type(migration_id) is not str
                or _IDENTIFIER.fullmatch(migration_id) is None
                or (previous_id is not None and migration_id <= previous_id)
                or type(path) is not str
                or path != f"{migration_id}.sql"
                or type(checksum) is not str
                or creates != sorted(set(creates))
                or drops != sorted(set(drops))
                or any(_TABLE.fullmatch(name) is None for name in (*creates, *drops))
            ):
                raise ValueError
            migration_definition = migrations_root.joinpath(path).read_bytes()
            if (
                not migration_definition.strip()
                or _digest(migration_definition) != checksum
            ):
                raise ValueError
            if set(creates).intersection(target_tables) or not set(drops).issubset(
                target_tables
            ):
                raise ValueError
            target_tables.difference_update(drops)
            target_tables.update(creates)
            migrations.append(
                _Migration(
                    migration_id,
                    checksum,
                    migration_definition,
                    frozenset(creates),
                    frozenset(drops),
                )
            )
            migration_paths.append(path)
            previous_id = migration_id
        actual_migration_paths = sorted(
            entry.name
            for entry in migrations_root.iterdir()
            if entry.name.endswith(".sql")
        )
        if migration_paths != actual_migration_paths:
            raise ValueError
    except OSError, TypeError, ValueError:
        raise DatabaseViolation(
            "DB-SCHEMA-RESOURCE", "the packaged schema plan is invalid"
        ) from None
    return _SchemaPlan(
        baseline_id=baseline_id,
        baseline_checksum=_digest(baseline_definition),
        baseline_definition=baseline_definition,
        baseline_tables=frozenset(declared_tables),
        migrations=tuple(migrations),
    )


class PostgreSQLSchemaGateway:
    """Govern one authoritative schema from baseline through ordered migrations."""

    __slots__ = ("_plan",)

    def __init__(self, *, resource_root: Traversable | None = None) -> None:
        self._plan = _load_schema_plan(resource_root)

    def status(
        self,
        conninfo: str,
        *,
        environment_id: UUID,
        role_class: str = "runtime",
    ) -> SchemaStatus:
        with self._connect(conninfo) as connection:
            self._verify_database_identity(connection)
            state = self._inspect_schema(connection)
            PostgreSQLRolePolicyGateway().verify(
                connection,
                environment_id=environment_id,
                role_class=role_class,
            )
            return state

    def install(self, conninfo: str, *, environment_id: UUID) -> SchemaStatus:
        with self._connect(conninfo, autocommit=True) as connection:
            self._verify_database_identity(connection)
            role_gateway = PostgreSQLRolePolicyGateway()
            role_gateway.verify(
                connection,
                environment_id=environment_id,
                role_class="migrator",
                require_objects=False,
            )
            self._acquire_lock(connection)
            try:
                if self._catalog_tables(connection):
                    raise DatabaseViolation(
                        "DB-SCHEMA-EXISTS",
                        "the authoritative database must be empty before baseline install",
                    )
                try:
                    with connection.transaction():
                        connection.execute("SET LOCAL ROLE armi_owner")
                        self._execute(connection, self._plan.baseline_definition)
                        self._record(
                            connection,
                            self._plan.baseline_id,
                            "baseline",
                            self._plan.baseline_checksum,
                        )
                        connection.execute("RESET ALL")
                except psycopg.Error, UnicodeDecodeError:
                    raise DatabaseViolation(
                        "DB-SCHEMA-INSTALL-FAILED",
                        "the schema baseline install failed and was rolled back",
                    ) from None
                role_gateway.verify(
                    connection,
                    environment_id=environment_id,
                    role_class="migrator",
                )
                return self._inspect_schema(connection)
            finally:
                self._release_lock(connection)

    def migrate(self, conninfo: str, *, environment_id: UUID) -> SchemaStatus:
        with self._connect(conninfo, autocommit=True) as connection:
            self._verify_database_identity(connection)
            role_gateway = PostgreSQLRolePolicyGateway()
            role_gateway.verify(
                connection,
                environment_id=environment_id,
                role_class="migrator",
            )
            self._acquire_lock(connection)
            try:
                state = self._inspect_schema(connection, allow_pending=True)
                if state.status == "current":
                    return state
                self._reject_active_runtime(connection)
                applied = len(self._history(connection)) - 1
                for migration in self._plan.migrations[applied:]:
                    try:
                        with connection.transaction():
                            connection.execute("SET LOCAL ROLE armi_owner")
                            self._execute(connection, migration.definition)
                            self._record(
                                connection,
                                migration.migration_id,
                                "migration",
                                migration.checksum,
                            )
                    except psycopg.Error, UnicodeDecodeError:
                        raise DatabaseViolation(
                            "DB-SCHEMA-MIGRATION-FAILED",
                            "a schema migration failed and was rolled back",
                        ) from None
                role_gateway.verify(
                    connection,
                    environment_id=environment_id,
                    role_class="migrator",
                )
                return self._inspect_schema(connection)
            finally:
                self._release_lock(connection)

    @staticmethod
    def _connect(
        conninfo: str,
        *,
        autocommit: bool = False,
    ) -> psycopg.Connection[tuple[Any, ...]]:
        try:
            return psycopg.connect(
                conninfo,
                autocommit=autocommit,
                connect_timeout=5,
                application_name="armi-schema-governance",
            )
        except psycopg.Error, UnicodeError, ValueError:
            raise DatabaseViolation(
                "DB-CONNECTION-UNAVAILABLE",
                "the configured PostgreSQL connection is unavailable",
                status="unavailable",
                exit_code=3,
            ) from None

    @staticmethod
    def _verify_database_identity(
        connection: psycopg.Connection[tuple[Any, ...]],
    ) -> None:
        try:
            version_row = connection.execute("SHOW server_version_num").fetchone()
            encoding_row = connection.execute("SHOW server_encoding").fetchone()
            timezone_row = connection.execute("SHOW TimeZone").fetchone()
            locale_row = connection.execute(
                """
                SELECT datlocprovider, datlocale
                FROM pg_catalog.pg_database
                WHERE datname = current_database()
                """
            ).fetchone()
            vector_row = connection.execute(
                """
                SELECT extension.extversion, namespace.nspname
                FROM pg_catalog.pg_extension AS extension
                JOIN pg_catalog.pg_namespace AS namespace
                  ON namespace.oid = extension.extnamespace
                WHERE extension.extname = 'vector'
                """
            ).fetchone()
            if None in (
                version_row,
                encoding_row,
                timezone_row,
                locale_row,
                vector_row,
            ):
                raise ValueError
            version = int(str(cast(tuple[object, ...], version_row)[0]))
            encoding = str(cast(tuple[object, ...], encoding_row)[0])
            timezone = str(cast(tuple[object, ...], timezone_row)[0])
            provider, locale = cast(tuple[object, object], locale_row)
            vector_version, vector_schema = cast(tuple[object, object], vector_row)
        except psycopg.Error, TypeError, ValueError:
            raise DatabaseViolation(
                "DB-DATABASE-IDENTITY",
                "database identity properties could not be verified",
            ) from None
        if version != _EXPECTED_POSTGRESQL:
            raise DatabaseViolation(
                "DB-PG-VERSION", "PostgreSQL must be exactly version 18.4"
            )
        if (
            vector_version != _EXPECTED_PGVECTOR
            or vector_schema != _EXPECTED_PGVECTOR_SCHEMA
        ):
            raise DatabaseViolation(
                "DB-PGVECTOR-IDENTITY",
                "pgvector must be exactly version 0.8.6 in armi_extensions",
            )
        if (
            encoding != _EXPECTED_ENCODING
            or timezone != _EXPECTED_TIMEZONE
            or provider != "b"
            or locale != _EXPECTED_LOCALE
        ):
            raise DatabaseViolation(
                "DB-DATABASE-IDENTITY",
                "database encoding, timezone, or locale is not the baseline",
            )

    def _inspect_schema(
        self,
        connection: psycopg.Connection[tuple[Any, ...]],
        *,
        allow_pending: bool = False,
    ) -> SchemaStatus:
        actual = self._catalog_tables(connection)
        if not actual:
            raise DatabaseViolation(
                "DB-SCHEMA-MISSING", "the authoritative schema is not installed"
            )
        if _HISTORY_TABLE not in actual:
            if actual == self._plan.baseline_tables - {_HISTORY_TABLE}:
                raise DatabaseViolation(
                    "DB-SCHEMA-UNBASELINED",
                    "the pre-baseline development database must be rebuilt",
                )
            raise DatabaseViolation("DB-SCHEMA-DIRTY", "the schema tables have drifted")
        history = self._history(connection)
        expected = self._plan.expected_history
        if (
            not history
            or len(history) > len(expected)
            or history != expected[: len(history)]
        ):
            raise DatabaseViolation(
                "DB-SCHEMA-HISTORY", "the schema migration history has drifted"
            )
        expected_tables = self._plan.tables_after(len(history))
        if actual != expected_tables:
            raise DatabaseViolation("DB-SCHEMA-DIRTY", "the schema tables have drifted")
        migration_count = len(history) - 1
        if len(history) < len(expected):
            if not allow_pending:
                raise DatabaseViolation(
                    "DB-SCHEMA-PENDING", "schema migrations must be applied explicitly"
                )
            status = "pending"
        else:
            status = "current"
        return SchemaStatus(
            status=status,
            table_count=len(actual),
            baseline_id=self._plan.baseline_id,
            migration_count=migration_count,
            target_id=self._plan.target_id,
        )

    @staticmethod
    def _catalog_tables(
        connection: psycopg.Connection[tuple[Any, ...]],
    ) -> frozenset[str]:
        try:
            rows = connection.execute(
                """
                SELECT relation.relname
                FROM pg_catalog.pg_class AS relation
                JOIN pg_catalog.pg_namespace AS namespace
                  ON namespace.oid = relation.relnamespace
                WHERE namespace.nspname = 'armi'
                  AND relation.relkind IN ('r', 'p')
                ORDER BY relation.relname
                """
            ).fetchall()
        except psycopg.Error:
            raise DatabaseViolation(
                "DB-SCHEMA-INVARIANT", "the schema catalog could not be inspected"
            ) from None
        return frozenset(str(row[0]) for row in rows)

    @staticmethod
    def _history(
        connection: psycopg.Connection[tuple[Any, ...]],
    ) -> tuple[tuple[str, str, str], ...]:
        try:
            rows = connection.execute(
                """
                SELECT migration_id, migration_kind, checksum
                FROM armi.schema_migrations
                ORDER BY sequence_no
                """
            ).fetchall()
        except psycopg.Error:
            raise DatabaseViolation(
                "DB-SCHEMA-HISTORY", "the schema migration history is unavailable"
            ) from None
        return tuple((str(row[0]), str(row[1]), str(row[2])) for row in rows)

    @staticmethod
    def _record(
        connection: psycopg.Connection[tuple[Any, ...]],
        migration_id: str,
        migration_kind: str,
        checksum: str,
    ) -> None:
        connection.execute(
            """
            INSERT INTO armi.schema_migrations (
                migration_id,
                migration_kind,
                checksum
            )
            VALUES (%s, %s, %s)
            """,
            (migration_id, migration_kind, checksum),
        )

    @staticmethod
    def _execute(
        connection: psycopg.Connection[tuple[Any, ...]], definition: bytes
    ) -> None:
        connection.execute(sql.SQL(cast(LiteralString, definition.decode("utf-8"))))

    @staticmethod
    def _reject_active_runtime(
        connection: psycopg.Connection[tuple[Any, ...]],
    ) -> None:
        try:
            with connection.transaction():
                connection.execute("SET LOCAL ROLE armi_owner")
                row = connection.execute(
                    """
                    SELECT EXISTS (
                        SELECT 1
                        FROM armi.runtime_instances
                        WHERE status = 'active'
                    )
                    """
                ).fetchone()
        except psycopg.Error:
            raise DatabaseViolation(
                "DB-SCHEMA-RUNTIME-STATE",
                "the Runtime state could not be verified before migration",
            ) from None
        if row != (False,):
            raise DatabaseViolation(
                "DB-SCHEMA-RUNTIME-ACTIVE",
                "stop the active Runtime before applying schema migrations",
            )

    @staticmethod
    def _acquire_lock(connection: psycopg.Connection[tuple[Any, ...]]) -> None:
        try:
            connection.execute(
                "SELECT pg_catalog.pg_advisory_lock(%s)", (_ADVISORY_LOCK,)
            )
        except psycopg.Error:
            raise DatabaseViolation(
                "DB-SCHEMA-LOCK", "the schema governance lock could not be acquired"
            ) from None

    @staticmethod
    def _release_lock(connection: psycopg.Connection[tuple[Any, ...]]) -> None:
        with suppress(psycopg.Error):
            connection.execute(
                "SELECT pg_catalog.pg_advisory_unlock(%s)", (_ADVISORY_LOCK,)
            )


__all__ = ("DatabaseViolation", "PostgreSQLSchemaGateway", "SchemaStatus")
