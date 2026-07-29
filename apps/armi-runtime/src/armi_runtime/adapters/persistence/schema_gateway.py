"""PostgreSQL 18.4 schema-governance gateway for the fixed S009 manifest."""

from __future__ import annotations

import hashlib
import json
from contextlib import suppress
from dataclasses import dataclass
from importlib.resources import files
from typing import Any, Final, LiteralString, cast

import psycopg
import rfc8785
from psycopg import sql

_RESOURCE_PACKAGE = "armi_runtime.composition.runtime_resources"
_SCHEMA_RESOURCE = "schema"
_APPLICATION_VERSION = "0.0.0"
_ADVISORY_LOCK: Final = 4_701_932_009
_EXPECTED_COLUMNS: Final = (
    ("version", "bigint", True),
    ("name", "text", True),
    ("sha256", "text", True),
    ("applied_at", "timestamp(6) with time zone", True),
    ("application_version", "text", True),
)
_KNOWN_CODES: Final = frozenset(
    {
        "DB-CONNECTION-UNAVAILABLE",
        "DB-PG-VERSION",
        "DB-DATABASE-IDENTITY",
        "DB-RUNTIME-ROLE-UNSAFE",
        "DB-SCHEMA-DIRTY",
        "DB-SCHEMA-AHEAD",
        "DB-SCHEMA-GAP",
        "DB-SCHEMA-HASH",
        "DB-SCHEMA-MISSING",
        "DB-SCHEMA-INVARIANT",
        "DB-MIGRATION-LOCK",
        "DB-MIGRATION-FAILED",
        "DB-MANIFEST-DRIFT",
    }
)


@dataclass(frozen=True, slots=True)
class DatabaseViolation(RuntimeError):
    code: str
    message: str
    status: str = "failed"
    exit_code: int = 4

    def __post_init__(self) -> None:
        if self.code not in _KNOWN_CODES:
            raise ValueError("database failure code is not registered")

    def __str__(self) -> str:
        return f"{self.code}: {self.message}"


@dataclass(frozen=True, slots=True)
class SchemaStatus:
    status: str
    target_version: int
    applied_version: int
    migration_set_sha256: str
    catalog_sha256: str | None

    def safe_view(self) -> dict[str, object]:
        return {
            "status": self.status,
            "target_version": self.target_version,
            "applied_version": self.applied_version,
            "migration_set_sha256": self.migration_set_sha256,
            "catalog_sha256": self.catalog_sha256,
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
        self, conninfo: str, *, require_safe_runtime_role: bool = True
    ) -> SchemaStatus:
        with self._connect(conninfo) as connection:
            self._verify_database_identity(connection)
            state = self._inspect_schema(connection, allow_empty=False)
            if require_safe_runtime_role:
                self._verify_runtime_identity(connection)
            return state

    def upgrade(self, conninfo: str) -> SchemaStatus:
        with self._connect(conninfo, autocommit=True) as connection:
            self._verify_database_identity(connection)
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
                    except UnicodeDecodeError, psycopg.Error:
                        raise DatabaseViolation(
                            "DB-MIGRATION-FAILED",
                            "the packaged migration failed and was rolled back",
                        ) from None
                    current = self._inspect_schema(connection, allow_empty=False)
                return current
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

    def _verify_runtime_identity(
        self, connection: psycopg.Connection[tuple[Any, ...]]
    ) -> None:
        try:
            row = connection.execute(
                """
                SELECT
                    role.rolsuper,
                    database.datdba = role.oid,
                    COALESCE(namespace.nspowner = role.oid, false),
                    has_database_privilege(current_user, current_database(), 'CREATE'),
                    COALESCE(
                        has_schema_privilege(current_user, 'armi', 'CREATE'),
                        false
                    )
                FROM pg_catalog.pg_roles AS role
                JOIN pg_catalog.pg_database AS database
                    ON database.datname = current_database()
                LEFT JOIN pg_catalog.pg_namespace AS namespace
                    ON namespace.nspname = 'armi'
                WHERE role.rolname = current_user
                """
            ).fetchone()
        except psycopg.Error:
            raise DatabaseViolation(
                "DB-RUNTIME-ROLE-UNSAFE",
                "the Runtime database identity could not be verified",
            ) from None
        if row is None or any(bool(value) for value in row):
            raise DatabaseViolation(
                "DB-RUNTIME-ROLE-UNSAFE",
                "the Runtime database identity has unsafe authority",
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
        if objects != [("schema_migrations", "r")]:
            raise DatabaseViolation(
                "DB-SCHEMA-DIRTY",
                "the schema contains an incomplete or unmanifested object set",
            )
        self._verify_table_shape(connection)
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
        if not allow_empty and len(applied) < target:
            raise DatabaseViolation(
                "DB-SCHEMA-MISSING", "the required schema target is not installed"
            )
        self._run_invariants(connection)
        catalog = self._catalog_digest(connection)
        return SchemaStatus(
            "current" if len(applied) == target else "behind",
            target,
            len(applied),
            self.migration_set_sha256,
            catalog,
        )

    def _verify_table_shape(
        self, connection: psycopg.Connection[tuple[Any, ...]]
    ) -> None:
        try:
            columns = connection.execute(
                """
                SELECT
                    attribute.attname,
                    pg_catalog.format_type(attribute.atttypid, attribute.atttypmod),
                    attribute.attnotnull
                FROM pg_catalog.pg_attribute AS attribute
                JOIN pg_catalog.pg_class AS relation
                    ON relation.oid = attribute.attrelid
                JOIN pg_catalog.pg_namespace AS namespace
                    ON namespace.oid = relation.relnamespace
                WHERE namespace.nspname = 'armi'
                  AND relation.relname = 'schema_migrations'
                  AND attribute.attnum > 0
                  AND NOT attribute.attisdropped
                ORDER BY attribute.attnum
                """
            ).fetchall()
        except psycopg.Error:
            raise DatabaseViolation(
                "DB-SCHEMA-INVARIANT", "the migration table could not be inspected"
            ) from None
        if tuple(columns) != _EXPECTED_COLUMNS:
            raise DatabaseViolation(
                "DB-SCHEMA-DIRTY", "the migration table shape has drifted"
            )
        try:
            constraint_kinds = connection.execute(
                """
                SELECT constraint_value.contype
                FROM pg_catalog.pg_constraint AS constraint_value
                JOIN pg_catalog.pg_class AS relation
                    ON relation.oid = constraint_value.conrelid
                JOIN pg_catalog.pg_namespace AS namespace
                    ON namespace.oid = relation.relnamespace
                WHERE namespace.nspname = 'armi'
                  AND relation.relname = 'schema_migrations'
                ORDER BY constraint_value.contype
                """
            ).fetchall()
        except psycopg.Error:
            raise DatabaseViolation(
                "DB-SCHEMA-INVARIANT",
                "the migration constraints could not be inspected",
            ) from None
        if [str(row[0]) for row in constraint_kinds] != [
            "c",
            "c",
            "c",
            "n",
            "n",
            "n",
            "n",
            "n",
            "p",
        ]:
            raise DatabaseViolation(
                "DB-SCHEMA-DIRTY", "the migration table constraints have drifted"
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
            if code not in _KNOWN_CODES:
                code = "DB-SCHEMA-INVARIANT"
            raise DatabaseViolation(code, "a read-only schema invariant was violated")

    def _catalog_digest(self, connection: psycopg.Connection[tuple[Any, ...]]) -> str:
        try:
            columns = connection.execute(
                """
                SELECT
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
                  AND relation.relname = 'schema_migrations'
                  AND attribute.attnum > 0
                  AND NOT attribute.attisdropped
                ORDER BY attribute.attnum
                """
            ).fetchall()
            constraints = connection.execute(
                """
                SELECT constraint_value.contype,
                       pg_catalog.pg_get_constraintdef(constraint_value.oid, false)
                FROM pg_catalog.pg_constraint AS constraint_value
                JOIN pg_catalog.pg_class AS relation
                    ON relation.oid = constraint_value.conrelid
                JOIN pg_catalog.pg_namespace AS namespace
                    ON namespace.oid = relation.relnamespace
                WHERE namespace.nspname = 'armi'
                  AND relation.relname = 'schema_migrations'
                ORDER BY constraint_value.contype,
                         pg_catalog.pg_get_constraintdef(constraint_value.oid, false)
                """
            ).fetchall()
        except psycopg.Error:
            raise DatabaseViolation(
                "DB-SCHEMA-INVARIANT", "the schema catalog digest could not be built"
            ) from None
        value = {
            "schema": "armi",
            "objects": [{"kind": "table", "name": "schema_migrations"}],
            "columns": [
                {
                    "name": str(name),
                    "type": str(type_name),
                    "not_null": bool(not_null),
                    "default": str(default),
                }
                for name, type_name, not_null, default in columns
            ],
            "constraints": [
                {"type": str(kind), "definition": str(definition)}
                for kind, definition in constraints
            ],
        }
        return _digest(rfc8785.dumps(cast(Any, value)))


__all__ = ("DatabaseViolation", "PostgreSQLSchemaGateway", "SchemaStatus")
