"""Install and inspect the authoritative PostgreSQL schema."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final
from uuid import UUID

import psycopg
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from alembic.util.exc import CommandError
from sqlalchemy import create_engine
from sqlalchemy.engine import Connection
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.pool import NullPool

from armi_runtime.adapters.database_errors import DatabaseViolation

from .role_policy import PostgreSQLRolePolicyGateway

_ADVISORY_LOCK: Final = 4_701_932_009
_EXPECTED_POSTGRESQL: Final = 180004
_EXPECTED_PGVECTOR: Final = "0.8.6"
_EXPECTED_PGTRGM: Final = "1.6"
_EXPECTED_PGVECTOR_SCHEMA: Final = "armi_extensions"
_EXPECTED_ENCODING: Final = "UTF8"
_EXPECTED_TIMEZONE: Final = "UTC"
_EXPECTED_LOCALE: Final = "C.UTF-8"
_VERSION_TABLE: Final = "alembic_version"
_BASELINE_IDENTITY: Final = "armi.schema-baseline.v1"


@dataclass(frozen=True, slots=True)
class SchemaStatus:
    status: str
    table_count: int
    current_revision: str
    head_revision: str
    baseline_identity: str = _BASELINE_IDENTITY

    def safe_view(self) -> dict[str, object]:
        return {
            "status": self.status,
            "table_count": self.table_count,
            "current_revision": self.current_revision,
            "head_revision": self.head_revision,
            "baseline_identity": self.baseline_identity,
        }


class PostgreSQLSchemaGateway:
    """Govern one authoritative schema through its sole Alembic baseline."""

    __slots__ = ("_config", "_head")

    def __init__(self, *, resource_root: Path | None = None) -> None:
        schema_root = resource_root or (
            Path(__file__).resolve().parents[2]
            / "composition"
            / "runtime_resources"
            / "schema"
        )
        config = Config()
        config.set_main_option("script_location", str(schema_root / "alembic"))
        config.attributes["schema_root"] = schema_root
        try:
            script = ScriptDirectory.from_config(config)
            heads = script.get_heads()
            if len(heads) != 1:
                raise ValueError
        except CommandError, OSError, ValueError:
            raise DatabaseViolation(
                "DB-SCHEMA-RESOURCE",
                "the packaged Alembic revision history is invalid",
            ) from None
        self._config = config
        self._head = heads[0]

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
                require_head_dml=True,
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
            if self._catalog_user_objects(connection):
                raise DatabaseViolation(
                    "DB-SCHEMA-EXISTS",
                    "the authoritative database must be empty before install",
                )
            try:
                with connection.transaction():
                    connection.execute("SET LOCAL ROLE armi_owner")
                    connection.execute("CREATE SCHEMA armi")
                self._upgrade(conninfo)
            except (
                psycopg.Error,
                CommandError,
                OSError,
                SQLAlchemyError,
                UnicodeError,
            ):
                raise DatabaseViolation(
                    "DB-SCHEMA-INSTALL-FAILED",
                    "the Alembic schema install failed",
                ) from None
            state = self._inspect_schema(connection)
            role_gateway.verify(
                connection,
                environment_id=environment_id,
                role_class="migrator",
                require_head_dml=True,
            )
            return state

    def reset(self, conninfo: str, *, environment_id: UUID) -> None:
        """Remove the sole ARMI schema after verifying the migrator boundary."""

        with self._connect(conninfo, autocommit=True) as connection:
            self._verify_database_identity(connection)
            PostgreSQLRolePolicyGateway().verify(
                connection,
                environment_id=environment_id,
                role_class="migrator",
                require_objects=False,
            )
            self._acquire_lock(connection)
            try:
                with connection.transaction():
                    connection.execute("SET LOCAL ROLE armi_owner")
                    connection.execute("DROP SCHEMA IF EXISTS armi CASCADE")
            except psycopg.Error:
                raise DatabaseViolation(
                    "DB-SCHEMA-RESET-FAILED",
                    "the authoritative schema reset failed",
                ) from None

    def _upgrade(self, conninfo: str) -> None:
        engine = create_engine(
            "postgresql+psycopg://",
            creator=lambda: psycopg.connect(conninfo),
            poolclass=NullPool,
        )
        try:
            with engine.connect() as connection:
                self._set_owner_role(connection)
                self._config.attributes["connection"] = connection
                try:
                    command.upgrade(self._config, "head")
                finally:
                    self._config.attributes.pop("connection", None)
                    if connection.in_transaction():
                        connection.rollback()
                    connection.exec_driver_sql("RESET ROLE")
                    connection.commit()
        finally:
            engine.dispose()

    @staticmethod
    def _set_owner_role(connection: Connection) -> None:
        connection.exec_driver_sql("SET ROLE armi_owner")
        connection.commit()

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
            extension_rows = connection.execute(
                """
                SELECT extension.extname, extension.extversion, namespace.nspname
                FROM pg_catalog.pg_extension AS extension
                JOIN pg_catalog.pg_namespace AS namespace
                  ON namespace.oid = extension.extnamespace
                WHERE extension.extname IN ('pg_trgm', 'vector')
                ORDER BY extension.extname
                """
            ).fetchall()
            if (
                version_row is None
                or encoding_row is None
                or timezone_row is None
                or locale_row is None
            ):
                raise ValueError
            version = int(str(version_row[0]))
            encoding = str(encoding_row[0])
            timezone = str(timezone_row[0])
            provider, locale = str(locale_row[0]), str(locale_row[1])
            extensions = [tuple(str(value) for value in row) for row in extension_rows]
        except psycopg.Error, TypeError, ValueError:
            raise DatabaseViolation(
                "DB-DATABASE-IDENTITY",
                "database identity properties could not be verified",
            ) from None
        if version != _EXPECTED_POSTGRESQL:
            raise DatabaseViolation(
                "DB-PG-VERSION", "PostgreSQL must be exactly version 18.4"
            )
        if extensions != [
            ("pg_trgm", _EXPECTED_PGTRGM, _EXPECTED_PGVECTOR_SCHEMA),
            ("vector", _EXPECTED_PGVECTOR, _EXPECTED_PGVECTOR_SCHEMA),
        ]:
            raise DatabaseViolation(
                "DB-PGVECTOR-IDENTITY",
                "PostgreSQL extensions must match the locked database identity",
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
    ) -> SchemaStatus:
        tables = self._catalog_tables(connection)
        if _VERSION_TABLE not in tables:
            raise DatabaseViolation(
                "DB-SCHEMA-MISSING",
                "the Alembic version table is unavailable",
            )
        try:
            rows = connection.execute(
                "SELECT version_num FROM armi.alembic_version"
            ).fetchall()
        except psycopg.Error:
            raise DatabaseViolation(
                "DB-SCHEMA-CONTRACT",
                "the Alembic revision is unavailable",
            ) from None
        if len(rows) != 1:
            raise DatabaseViolation(
                "DB-SCHEMA-CONTRACT",
                "the Alembic revision history is invalid",
            )
        current = str(rows[0][0])
        if current != self._head:
            raise DatabaseViolation(
                "DB-SCHEMA-CONTRACT",
                "the database revision does not match the sole baseline",
            )
        try:
            identity_rows = connection.execute(
                "SELECT singleton_key, baseline_identity "
                "FROM armi.schema_baseline_identity"
            ).fetchall()
        except psycopg.Error:
            identity_rows = []
        if identity_rows != [(True, _BASELINE_IDENTITY)]:
            raise DatabaseViolation(
                "DB-SCHEMA-CONTRACT",
                "the database baseline identity does not match this build",
            )
        return SchemaStatus(
            "current", len(tables), current, self._head, _BASELINE_IDENTITY
        )

    @staticmethod
    def _catalog_user_objects(
        connection: psycopg.Connection[tuple[Any, ...]],
    ) -> frozenset[tuple[str, str]]:
        try:
            rows = connection.execute(
                """
                SELECT namespace.nspname, relation.relname
                FROM pg_catalog.pg_class AS relation
                JOIN pg_catalog.pg_namespace AS namespace
                  ON namespace.oid = relation.relnamespace
                LEFT JOIN pg_catalog.pg_depend AS dependency
                  ON dependency.objid = relation.oid AND dependency.deptype = 'e'
                WHERE namespace.nspname NOT IN (
                        'pg_catalog', 'information_schema', 'armi_extensions'
                      )
                  AND namespace.nspname NOT LIKE 'pg_toast%'
                  AND relation.relkind IN ('r', 'p', 'S', 'v', 'm', 'f')
                  AND dependency.objid IS NULL
                ORDER BY namespace.nspname, relation.relname
                """
            ).fetchall()
        except psycopg.Error:
            raise DatabaseViolation(
                "DB-SCHEMA-INVARIANT",
                "the database catalog could not be inspected",
            ) from None
        return frozenset((str(row[0]), str(row[1])) for row in rows)

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
                "DB-SCHEMA-INVARIANT",
                "the schema catalog could not be inspected",
            ) from None
        return frozenset(str(row[0]) for row in rows)

    @staticmethod
    def _acquire_lock(connection: psycopg.Connection[tuple[Any, ...]]) -> None:
        try:
            connection.execute(
                "SELECT pg_catalog.pg_advisory_lock(%s)", (_ADVISORY_LOCK,)
            )
        except psycopg.Error:
            raise DatabaseViolation(
                "DB-SCHEMA-LOCK",
                "the schema migration lock could not be acquired",
            ) from None


__all__ = ("DatabaseViolation", "PostgreSQLSchemaGateway", "SchemaStatus")
