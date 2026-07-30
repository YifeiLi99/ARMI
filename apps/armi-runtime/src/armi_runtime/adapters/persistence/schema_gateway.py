"""PostgreSQL 18.4 schema-governance gateway for the fixed S009 manifest."""

from __future__ import annotations

import hashlib
import json
from contextlib import suppress
from dataclasses import dataclass
from importlib.resources import files
from typing import Any, Final, LiteralString, cast
from uuid import UUID

import psycopg
import rfc8785
from psycopg import sql

from armi_runtime.adapters.database_errors import (
    KNOWN_DATABASE_CODES,
    DatabaseViolation,
)

from .role_policy import PostgreSQLRolePolicyGateway

_RESOURCE_PACKAGE = "armi_runtime.composition.runtime_resources"
_SCHEMA_RESOURCE = "schema"
_APPLICATION_VERSION = "0.0.0"
_ADVISORY_LOCK: Final = 4_701_932_009
_EXPECTED_TABLE_COLUMNS: Final = {
    "schema_migrations": (
        ("version", "bigint", True),
        ("name", "text", True),
        ("sha256", "text", True),
        ("applied_at", "timestamp(6) with time zone", True),
        ("application_version", "text", True),
    ),
    "artifacts": (
        ("artifact_id", "uuid", True),
        ("content_digest", "text", True),
        ("media_type", "text", True),
        ("byte_size", "bigint", True),
        ("storage_locator", "text", True),
        ("logical_kind", "text", True),
        ("producer_kind", "text", True),
        ("producer_trace_id", "text", True),
        ("privacy_scope", "text", True),
        ("integrity_status", "text", True),
        ("retention_status", "text", True),
        ("created_at", "timestamp(6) with time zone", True),
        ("deleted_at", "timestamp(6) with time zone", False),
        ("schema_version", "smallint", True),
    ),
}
_EXPECTED_CONSTRAINT_KINDS: Final = {
    "schema_migrations": tuple(sorted(("c", "c", "c", "n", "n", "n", "n", "n", "p"))),
    "artifacts": tuple(sorted((*("c",) * 13, *("n",) * 13, "p", "u", "u"))),
}


@dataclass(frozen=True, slots=True)
class SchemaStatus:
    status: str
    target_version: int
    applied_version: int
    migration_set_sha256: str
    catalog_sha256: str | None
    role_policy_sha256: str | None = None
    privilege_catalog_sha256: str | None = None

    def safe_view(self) -> dict[str, object]:
        return {
            "status": self.status,
            "target_version": self.target_version,
            "applied_version": self.applied_version,
            "migration_set_sha256": self.migration_set_sha256,
            "catalog_sha256": self.catalog_sha256,
            "role_policy_sha256": self.role_policy_sha256,
            "privilege_catalog_sha256": self.privilege_catalog_sha256,
        }


@dataclass(frozen=True, slots=True)
class _PackagedSchema:
    manifest: dict[str, Any]
    migrations: tuple[tuple[int, str, str, bytes], ...]
    invariants: bytes


def _digest(value: bytes) -> str:
    return f"sha256:{hashlib.sha256(value).hexdigest()}"


def _load_packaged_schema() -> _PackagedSchema:
    root = files(_RESOURCE_PACKAGE).joinpath(_SCHEMA_RESOURCE)
    try:
        manifest_bytes = root.joinpath("manifests/schema-manifest.json").read_bytes()
        manifest = cast(dict[str, Any], json.loads(manifest_bytes))
    except OSError, UnicodeDecodeError, json.JSONDecodeError:
        raise DatabaseViolation(
            "DB-MANIFEST-DRIFT",
            "the packaged schema manifest is unavailable or malformed",
        ) from None
    if (
        manifest.get("schema_version") != "armi.schema-manifest.v1"
        or rfc8785.dumps(cast(Any, manifest)) + b"\n" != manifest_bytes
        or manifest.get("runtime_upgrade_allowed") is not False
    ):
        raise DatabaseViolation(
            "DB-MANIFEST-DRIFT", "the packaged schema manifest has drifted"
        )
    migrations: list[tuple[int, str, str, bytes]] = []
    expected_version = 1
    migration_set = bytearray()
    try:
        entries = cast(list[dict[str, Any]], manifest["migrations"])
        for entry in entries:
            version = int(entry["version"])
            name = str(entry["name"])
            path = str(entry["path"])
            declared_digest = str(entry["sha256"])
            if version != expected_version or not path.startswith("schema/migrations/"):
                raise DatabaseViolation(
                    "DB-SCHEMA-GAP", "the packaged migration sequence is not continuous"
                )
            value = root.joinpath(path.removeprefix("schema/")).read_bytes()
            if _digest(value) != declared_digest:
                raise DatabaseViolation(
                    "DB-SCHEMA-HASH", "a packaged migration digest does not match"
                )
            migration_set.extend(f"{version}\t{path}\t{declared_digest}\n".encode())
            migrations.append((version, name, declared_digest, value))
            expected_version += 1
        invariant_entry = cast(dict[str, Any], manifest["invariants"])
        invariant_path = str(invariant_entry["path"])
        invariants = root.joinpath(invariant_path.removeprefix("schema/")).read_bytes()
    except DatabaseViolation:
        raise
    except KeyError, TypeError, ValueError, OSError:
        raise DatabaseViolation(
            "DB-MANIFEST-DRIFT", "the packaged schema resource set is incomplete"
        ) from None
    if (
        _digest(bytes(migration_set)) != manifest.get("migration_set_sha256")
        or _digest(invariants) != invariant_entry.get("sha256")
        or int(cast(dict[str, Any], manifest.get("target", {})).get("version", 0))
        != len(migrations)
    ):
        raise DatabaseViolation(
            "DB-MANIFEST-DRIFT", "the packaged schema resource digest has drifted"
        )
    return _PackagedSchema(manifest, tuple(migrations), invariants)


class PostgreSQLSchemaGateway:
    """Validate and advance only the packaged schema migration set."""

    __slots__ = ("_packaged",)

    def __init__(self) -> None:
        self._packaged = _load_packaged_schema()

    @property
    def migration_set_sha256(self) -> str:
        return str(self._packaged.manifest["migration_set_sha256"])

    def status(
        self,
        conninfo: str,
        *,
        environment_id: UUID,
        role_class: str = "runtime",
    ) -> SchemaStatus:
        with self._connect(conninfo) as connection:
            self._verify_database_identity(connection)
            state = self._inspect_schema(connection, allow_empty=False)
            role_status = PostgreSQLRolePolicyGateway().verify(
                connection,
                environment_id=environment_id,
                role_class=role_class,
            )
            return SchemaStatus(
                state.status,
                state.target_version,
                state.applied_version,
                state.migration_set_sha256,
                state.catalog_sha256,
                role_status.role_policy_sha256,
                role_status.privilege_catalog_sha256,
            )

    def upgrade(self, conninfo: str, *, environment_id: UUID) -> SchemaStatus:
        with self._connect(conninfo, autocommit=True) as connection:
            self._verify_database_identity(connection)
            role_gateway = PostgreSQLRolePolicyGateway()
            role_gateway.verify(
                connection,
                environment_id=environment_id,
                role_class="migrator",
                require_objects=False,
            )
            try:
                connection.execute(
                    "SELECT pg_catalog.pg_advisory_lock(%s)", (_ADVISORY_LOCK,)
                )
            except psycopg.Error:
                raise DatabaseViolation(
                    "DB-MIGRATION-LOCK",
                    "the fixed schema migration lock could not be acquired",
                ) from None
            try:
                current = self._inspect_schema(connection, allow_empty=True)
                for version, name, digest, migration in self._packaged.migrations:
                    if version <= current.applied_version:
                        continue
                    try:
                        with connection.transaction():
                            connection.execute("SET LOCAL ROLE armi_owner")
                            connection.execute(
                                sql.SQL(cast(LiteralString, migration.decode("utf-8")))
                            )
                            connection.execute(
                                """
                                INSERT INTO armi.schema_migrations
                                    (version, name, sha256, application_version)
                                VALUES (%s, %s, %s, %s)
                                """,
                                (version, name, digest, _APPLICATION_VERSION),
                            )
                            current = self._inspect_schema(
                                connection,
                                allow_empty=True,
                            )
                    except UnicodeDecodeError, psycopg.Error:
                        raise DatabaseViolation(
                            "DB-MIGRATION-FAILED",
                            "the packaged migration failed and was rolled back",
                        ) from None
                role_status = role_gateway.verify(
                    connection,
                    environment_id=environment_id,
                    role_class="migrator",
                )
                return SchemaStatus(
                    current.status,
                    current.target_version,
                    current.applied_version,
                    current.migration_set_sha256,
                    current.catalog_sha256,
                    role_status.role_policy_sha256,
                    role_status.privilege_catalog_sha256,
                )
            finally:
                with suppress(psycopg.Error):
                    connection.execute(
                        "SELECT pg_catalog.pg_advisory_unlock(%s)", (_ADVISORY_LOCK,)
                    )

    def _connect(
        self, conninfo: str, *, autocommit: bool = False
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

    def _verify_database_identity(
        self, connection: psycopg.Connection[tuple[Any, ...]]
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
            if (
                version_row is None
                or encoding_row is None
                or timezone_row is None
                or locale_row is None
            ):
                raise ValueError
            version = int(version_row[0])
            encoding = str(encoding_row[0])
            timezone = str(timezone_row[0])
            provider, locale = locale_row
        except psycopg.Error, TypeError, ValueError:
            raise DatabaseViolation(
                "DB-DATABASE-IDENTITY",
                "database identity properties could not be verified",
            ) from None
        expected = self._packaged.manifest
        if version != int(expected["postgresql"]["server_version_num"]):
            raise DatabaseViolation(
                "DB-PG-VERSION", "PostgreSQL must be exactly version 18.4"
            )
        if (
            encoding != expected["database"]["encoding"]
            or timezone != expected["database"]["timezone"]
            or provider != "b"
            or locale != expected["database"]["locale"]
        ):
            raise DatabaseViolation(
                "DB-DATABASE-IDENTITY",
                "database encoding, timezone, or locale is not the frozen identity",
            )

    def _inspect_schema(
        self,
        connection: psycopg.Connection[tuple[Any, ...]],
        *,
        allow_empty: bool,
    ) -> SchemaStatus:
        try:
            objects = connection.execute(
                """
                SELECT relation.relname, relation.relkind
                FROM pg_catalog.pg_class AS relation
                JOIN pg_catalog.pg_namespace AS namespace
                    ON namespace.oid = relation.relnamespace
                WHERE namespace.nspname = 'armi'
                  AND relation.relkind IN ('r', 'p', 'v', 'm', 'S', 'f')
                ORDER BY relation.relname, relation.relkind
                """
            ).fetchall()
            exists_row = connection.execute(
                """
                SELECT EXISTS (
                    SELECT 1 FROM pg_catalog.pg_namespace
                    WHERE nspname = 'armi'
                )
                """
            ).fetchone()
            if exists_row is None:
                raise ValueError
            schema_exists = exists_row[0] is True
        except psycopg.Error, ValueError:
            raise DatabaseViolation(
                "DB-SCHEMA-INVARIANT", "the schema catalog could not be inspected"
            ) from None
        if not schema_exists and not objects:
            if allow_empty:
                return SchemaStatus(
                    "empty",
                    len(self._packaged.migrations),
                    0,
                    self.migration_set_sha256,
                    None,
                )
            raise DatabaseViolation(
                "DB-SCHEMA-MISSING", "the required schema baseline is not installed"
            )
        if ("schema_migrations", "r") not in objects:
            raise DatabaseViolation(
                "DB-SCHEMA-DIRTY",
                "the schema contains an incomplete or unmanifested object set",
            )
        self._verify_table_shapes(connection, ("schema_migrations",))
        applied = self._read_applied(connection)
        target = len(self._packaged.migrations)
        for expected, row in enumerate(applied, start=1):
            if row[0] != expected:
                raise DatabaseViolation(
                    "DB-SCHEMA-GAP", "the applied migration sequence has a gap"
                )
            if expected > target:
                continue
            packaged = self._packaged.migrations[expected - 1]
            if row[1] != packaged[1] or row[2] != packaged[2]:
                raise DatabaseViolation(
                    "DB-SCHEMA-HASH", "an applied migration identity has drifted"
                )
        if applied and applied[-1][0] > target:
            raise DatabaseViolation(
                "DB-SCHEMA-AHEAD", "the database schema is ahead of this Runtime"
            )
        applied_version = len(applied)
        expected_objects = [("schema_migrations", "r")]
        expected_tables = ["schema_migrations"]
        if applied_version >= 3:
            expected_objects.insert(0, ("artifacts", "r"))
            expected_tables.insert(0, "artifacts")
        if objects != expected_objects:
            raise DatabaseViolation(
                "DB-SCHEMA-DIRTY",
                "the schema contains an incomplete or unmanifested object set",
            )
        self._verify_table_shapes(connection, tuple(expected_tables))
        if not allow_empty and len(applied) < target:
            raise DatabaseViolation(
                "DB-SCHEMA-MISSING", "the required schema target is not installed"
            )
        if len(applied) == target:
            self._run_invariants(connection)
        catalog = self._catalog_digest(connection)
        return SchemaStatus(
            "current" if len(applied) == target else "behind",
            target,
            len(applied),
            self.migration_set_sha256,
            catalog,
        )

    def _verify_table_shapes(
        self,
        connection: psycopg.Connection[tuple[Any, ...]],
        table_names: tuple[str, ...],
    ) -> None:
        try:
            columns = connection.execute(
                """
                SELECT
                    relation.relname,
                    attribute.attname,
                    pg_catalog.format_type(attribute.atttypid, attribute.atttypmod),
                    attribute.attnotnull
                FROM pg_catalog.pg_attribute AS attribute
                JOIN pg_catalog.pg_class AS relation
                    ON relation.oid = attribute.attrelid
                JOIN pg_catalog.pg_namespace AS namespace
                    ON namespace.oid = relation.relnamespace
                WHERE namespace.nspname = 'armi'
                  AND relation.relname = ANY(%s)
                  AND attribute.attnum > 0
                  AND NOT attribute.attisdropped
                ORDER BY relation.relname, attribute.attnum
                """,
                (list(table_names),),
            ).fetchall()
        except psycopg.Error:
            raise DatabaseViolation(
                "DB-SCHEMA-INVARIANT", "the manifest tables could not be inspected"
            ) from None
        actual_columns: dict[str, list[tuple[str, str, bool]]] = {}
        for table_name, name, type_name, not_null in columns:
            actual_columns.setdefault(str(table_name), []).append(
                (str(name), str(type_name), bool(not_null))
            )
        for table_name in table_names:
            if tuple(actual_columns.get(table_name, ())) != _EXPECTED_TABLE_COLUMNS.get(
                table_name
            ):
                raise DatabaseViolation(
                    "DB-SCHEMA-DIRTY", "a manifest table shape has drifted"
                )
        try:
            constraint_kinds = connection.execute(
                """
                SELECT relation.relname, constraint_value.contype
                FROM pg_catalog.pg_constraint AS constraint_value
                JOIN pg_catalog.pg_class AS relation
                    ON relation.oid = constraint_value.conrelid
                JOIN pg_catalog.pg_namespace AS namespace
                    ON namespace.oid = relation.relnamespace
                WHERE namespace.nspname = 'armi'
                  AND relation.relname = ANY(%s)
                ORDER BY relation.relname, constraint_value.contype
                """,
                (list(table_names),),
            ).fetchall()
        except psycopg.Error:
            raise DatabaseViolation(
                "DB-SCHEMA-INVARIANT",
                "the manifest table constraints could not be inspected",
            ) from None
        actual_constraints: dict[str, list[str]] = {}
        for table_name, kind in constraint_kinds:
            actual_constraints.setdefault(str(table_name), []).append(str(kind))
        for table_name in table_names:
            if tuple(actual_constraints.get(table_name, ())) != (
                _EXPECTED_CONSTRAINT_KINDS.get(table_name)
            ):
                raise DatabaseViolation(
                    "DB-SCHEMA-DIRTY", "a manifest table constraint set has drifted"
                )

    def _read_applied(
        self, connection: psycopg.Connection[tuple[Any, ...]]
    ) -> list[tuple[int, str, str]]:
        try:
            rows = connection.execute(
                """
                SELECT version, name, sha256
                FROM armi.schema_migrations
                ORDER BY version
                """
            ).fetchall()
            return [(int(row[0]), str(row[1]), str(row[2])) for row in rows]
        except psycopg.Error, TypeError, ValueError:
            raise DatabaseViolation(
                "DB-SCHEMA-DIRTY", "the migration ledger could not be read"
            ) from None

    def _run_invariants(self, connection: psycopg.Connection[tuple[Any, ...]]) -> None:
        try:
            violations = connection.execute(
                sql.SQL(
                    cast(
                        LiteralString,
                        self._packaged.invariants.decode("utf-8"),
                    )
                )
            ).fetchall()
        except UnicodeDecodeError, psycopg.Error:
            raise DatabaseViolation(
                "DB-SCHEMA-INVARIANT", "the read-only schema invariants failed"
            ) from None
        if violations:
            code = str(violations[0][0])
            if code not in KNOWN_DATABASE_CODES:
                code = "DB-SCHEMA-INVARIANT"
            raise DatabaseViolation(code, "a read-only schema invariant was violated")

    def _catalog_digest(self, connection: psycopg.Connection[tuple[Any, ...]]) -> str:
        try:
            columns = connection.execute(
                """
                SELECT
                    relation.relname,
                    attribute.attname,
                    pg_catalog.format_type(attribute.atttypid, attribute.atttypmod),
                    attribute.attnotnull,
                    COALESCE(
                        pg_catalog.pg_get_expr(default_value.adbin, default_value.adrelid),
                        ''
                    )
                FROM pg_catalog.pg_attribute AS attribute
                JOIN pg_catalog.pg_class AS relation
                    ON relation.oid = attribute.attrelid
                JOIN pg_catalog.pg_namespace AS namespace
                    ON namespace.oid = relation.relnamespace
                LEFT JOIN pg_catalog.pg_attrdef AS default_value
                    ON default_value.adrelid = relation.oid
                   AND default_value.adnum = attribute.attnum
                WHERE namespace.nspname = 'armi'
                  AND relation.relkind IN ('r', 'p')
                  AND attribute.attnum > 0
                  AND NOT attribute.attisdropped
                ORDER BY relation.relname, attribute.attnum
                """
            ).fetchall()
            constraints = connection.execute(
                """
                SELECT relation.relname,
                       constraint_value.contype,
                       pg_catalog.pg_get_constraintdef(constraint_value.oid, false)
                FROM pg_catalog.pg_constraint AS constraint_value
                JOIN pg_catalog.pg_class AS relation
                    ON relation.oid = constraint_value.conrelid
                JOIN pg_catalog.pg_namespace AS namespace
                    ON namespace.oid = relation.relnamespace
                WHERE namespace.nspname = 'armi'
                  AND relation.relkind IN ('r', 'p')
                ORDER BY relation.relname,
                         constraint_value.contype,
                         pg_catalog.pg_get_constraintdef(constraint_value.oid, false)
                """
            ).fetchall()
            objects = connection.execute(
                """
                SELECT relation.relname, relation.relkind
                FROM pg_catalog.pg_class AS relation
                JOIN pg_catalog.pg_namespace AS namespace
                    ON namespace.oid = relation.relnamespace
                WHERE namespace.nspname = 'armi'
                  AND relation.relkind IN ('r', 'p')
                ORDER BY relation.relname, relation.relkind
                """
            ).fetchall()
        except psycopg.Error:
            raise DatabaseViolation(
                "DB-SCHEMA-INVARIANT", "the schema catalog digest could not be built"
            ) from None
        value = {
            "schema": "armi",
            "objects": [
                {"kind": str(kind), "name": str(name)} for name, kind in objects
            ],
            "columns": [
                {
                    "table": str(table_name),
                    "name": str(name),
                    "type": str(type_name),
                    "not_null": bool(not_null),
                    "default": str(default),
                }
                for table_name, name, type_name, not_null, default in columns
            ],
            "constraints": [
                {
                    "table": str(table_name),
                    "type": str(kind),
                    "definition": str(definition),
                }
                for table_name, kind, definition in constraints
            ],
        }
        return _digest(rfc8785.dumps(cast(Any, value)))


__all__ = ("DatabaseViolation", "PostgreSQLSchemaGateway", "SchemaStatus")
