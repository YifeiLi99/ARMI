"""Fixed PostgreSQL VACUUM/ANALYZE driver for explicit operator use."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

import psycopg
from armi_kernel.contracts import Instant
from psycopg import sql

from armi_runtime.adapters.database_errors import DatabaseViolation

from .role_policy import PostgreSQLRolePolicyGateway


@dataclass(frozen=True, slots=True)
class DatabaseMaintenanceReport:
    table_count: int
    completed_at: str

    def safe_view(self) -> dict[str, object]:
        return {
            "schema_version": "armi.database-maintenance.v1",
            "status": "applied",
            "table_count": self.table_count,
            "completed_at": self.completed_at,
        }


class PostgreSQLDatabaseMaintenance:
    """Maintain only current ``armi`` tables through the migrator owner grant."""

    __slots__ = ()

    def run(
        self,
        conninfo: str,
        *,
        environment_id: UUID,
        statement_timeout_seconds: int,
        lock_timeout_seconds: int,
    ) -> DatabaseMaintenanceReport:
        if (
            environment_id.version != 7
            or type(statement_timeout_seconds) is not int
            or statement_timeout_seconds <= 0
            or type(lock_timeout_seconds) is not int
            or lock_timeout_seconds <= 0
        ):
            raise DatabaseViolation(
                "DB-MAINTENANCE-FAILED",
                "database maintenance configuration is invalid",
            )
        try:
            with psycopg.connect(conninfo, autocommit=True) as connection:
                connection.execute("SET search_path TO pg_catalog, armi")
                PostgreSQLRolePolicyGateway().verify(
                    connection,
                    environment_id=environment_id,
                    role_class="migrator",
                )
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
                tables = tuple(str(row[0]) for row in rows)
                if not tables:
                    raise DatabaseViolation(
                        "DB-MAINTENANCE-FAILED",
                        "database maintenance found no current tables",
                    )
                connection.execute("SET ROLE armi_owner")
                connection.execute(
                    "SELECT set_config('statement_timeout', %s, false)",
                    (str(statement_timeout_seconds * 1000),),
                )
                connection.execute(
                    "SELECT set_config('lock_timeout', %s, false)",
                    (str(lock_timeout_seconds * 1000),),
                )
                for table in tables:
                    connection.execute(
                        sql.SQL("VACUUM (ANALYZE) {}.{}").format(
                            sql.Identifier("armi"),
                            sql.Identifier(table),
                        )
                    )
        except DatabaseViolation:
            raise
        except psycopg.Error:
            raise DatabaseViolation(
                "DB-MAINTENANCE-FAILED",
                "database maintenance did not complete",
            ) from None
        return DatabaseMaintenanceReport(
            table_count=len(tables),
            completed_at=Instant(datetime.now(UTC)).to_wire(),
        )


__all__ = ("DatabaseMaintenanceReport", "PostgreSQLDatabaseMaintenance")
