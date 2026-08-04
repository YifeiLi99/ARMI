"""Install and inspect the disposable development database schema."""

from __future__ import annotations

import re
from contextlib import suppress
from dataclasses import dataclass
from importlib.resources import files
from typing import Any, Final, LiteralString, cast
from uuid import UUID

import psycopg
from psycopg import sql

from armi_runtime.adapters.database_errors import DatabaseViolation

from .role_policy import PostgreSQLRolePolicyGateway

_RESOURCE_PACKAGE = "armi_runtime.composition.runtime_resources"
_CURRENT_SCHEMA_RESOURCE = "schema/current"
_ADVISORY_LOCK: Final = 4_701_932_009
_EXPECTED_POSTGRESQL: Final = 180004
_EXPECTED_ENCODING: Final = "UTF8"
_EXPECTED_TIMEZONE: Final = "UTC"
_EXPECTED_LOCALE: Final = "C.UTF-8"
_TABLE_PATTERN = re.compile(rb"\bCREATE TABLE armi\.([a-z][a-z0-9_]*)\s*\(")


@dataclass(frozen=True, slots=True)
class SchemaStatus:
    status: str
    table_count: int

    def safe_view(self) -> dict[str, object]:
        return {"status": self.status, "table_count": self.table_count}


@dataclass(frozen=True, slots=True)
class _CurrentSchema:
    definitions: tuple[bytes, ...]
    tables: frozenset[str]


def _load_current_schema() -> _CurrentSchema:
    current = files(_RESOURCE_PACKAGE).joinpath(_CURRENT_SCHEMA_RESOURCE)
    try:
        entries = sorted(
            (entry for entry in current.iterdir() if entry.name.endswith(".sql")),
            key=lambda entry: entry.name,
        )
        definitions = tuple(entry.read_bytes() for entry in entries)
    except OSError:
        raise DatabaseViolation(
            "DB-SCHEMA-RESOURCE",
            "the packaged current schema is unavailable",
        ) from None
    if not definitions or any(not definition.strip() for definition in definitions):
        raise DatabaseViolation(
            "DB-SCHEMA-RESOURCE",
            "the packaged current schema is incomplete",
        )
    tables = frozenset(
        match.group(1).decode("ascii")
        for definition in definitions
        for match in _TABLE_PATTERN.finditer(definition)
    )
    if not tables:
        raise DatabaseViolation(
            "DB-SCHEMA-RESOURCE",
            "the packaged current schema contains no tables",
        )
    return _CurrentSchema(definitions, tables)


class PostgreSQLSchemaGateway:
    """Install the current schema into an empty disposable database."""

    __slots__ = ("_schema",)

    def __init__(self) -> None:
        self._schema = _load_current_schema()

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
            try:
                connection.execute(
                    "SELECT pg_catalog.pg_advisory_lock(%s)",
                    (_ADVISORY_LOCK,),
                )
            except psycopg.Error:
                raise DatabaseViolation(
                    "DB-SCHEMA-LOCK",
                    "the development schema install lock could not be acquired",
                ) from None
            try:
                if self._inspect_schema(connection, allow_empty=True).status != "empty":
                    raise DatabaseViolation(
                        "DB-SCHEMA-EXISTS",
                        "reset the disposable database before installing the current schema",
                    )
                try:
                    with connection.transaction():
                        connection.execute("SET LOCAL ROLE armi_owner")
                        for definition in self._schema.definitions:
                            connection.execute(
                                sql.SQL(cast(LiteralString, definition.decode("utf-8")))
                            )
                except UnicodeDecodeError, psycopg.Error:
                    raise DatabaseViolation(
                        "DB-SCHEMA-INSTALL-FAILED",
                        "the current schema install failed and was rolled back",
                    ) from None
                role_gateway.verify(
                    connection,
                    environment_id=environment_id,
                    role_class="migrator",
                )
                return self._inspect_schema(connection, allow_empty=False)
            finally:
                with suppress(psycopg.Error):
                    connection.execute(
                        "SELECT pg_catalog.pg_advisory_unlock(%s)",
                        (_ADVISORY_LOCK,),
                    )

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
                application_name="armi-schema-development",
            )
        except (psycopg.Error, UnicodeError, ValueError):
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
            if None in (version_row, encoding_row, timezone_row, locale_row):
                raise ValueError
            version = int(str(cast(tuple[object, ...], version_row)[0]))
            encoding = str(cast(tuple[object, ...], encoding_row)[0])
            timezone = str(cast(tuple[object, ...], timezone_row)[0])
            provider, locale = cast(tuple[object, object], locale_row)
        except (psycopg.Error, TypeError, ValueError):
            raise DatabaseViolation(
                "DB-DATABASE-IDENTITY",
                "database identity properties could not be verified",
            ) from None
        if version != _EXPECTED_POSTGRESQL:
            raise DatabaseViolation(
                "DB-PG-VERSION",
                "PostgreSQL must be exactly version 18.4",
            )
        if (
            encoding != _EXPECTED_ENCODING
            or timezone != _EXPECTED_TIMEZONE
            or provider != "b"
            or locale != _EXPECTED_LOCALE
        ):
            raise DatabaseViolation(
                "DB-DATABASE-IDENTITY",
                "database encoding, timezone, or locale is not the development baseline",
            )

    def _inspect_schema(
        self,
        connection: psycopg.Connection[tuple[Any, ...]],
        *,
        allow_empty: bool,
    ) -> SchemaStatus:
        try:
            schema_row = connection.execute(
                "SELECT EXISTS ("
                "SELECT 1 FROM pg_catalog.pg_namespace WHERE nspname = 'armi')"
            ).fetchone()
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
            if schema_row is None:
                raise ValueError
        except (psycopg.Error, ValueError):
            raise DatabaseViolation(
                "DB-SCHEMA-INVARIANT",
                "the schema catalog could not be inspected",
            ) from None
        actual = frozenset(str(row[0]) for row in rows)
        if schema_row[0] is not True and not actual:
            if allow_empty:
                return SchemaStatus("empty", 0)
            raise DatabaseViolation(
                "DB-SCHEMA-MISSING",
                "the current development schema is not installed",
            )
        if actual != self._schema.tables:
            raise DatabaseViolation(
                "DB-SCHEMA-DIRTY",
                "reset the disposable database and install the current schema",
            )
        return SchemaStatus("current", len(actual))


__all__ = ("DatabaseViolation", "PostgreSQLSchemaGateway", "SchemaStatus")
