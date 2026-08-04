"""Read-only current-schema gateway for the Admin MCP tools."""

from __future__ import annotations

from dataclasses import dataclass

from .role_session import AdminRoleBoundPool


@dataclass(frozen=True, slots=True)
class AdminSchemaSnapshot:
    server_version_num: int
    encoding: str
    timezone: str
    tables: tuple[str, ...]


class AdminSchemaGateway:
    """Open one role-bound pool and execute only fixed read statements."""

    __slots__ = ("_conninfo", "_expected_role")

    def __init__(self, conninfo: str, *, expected_role: str) -> None:
        self._conninfo = conninfo
        self._expected_role = expected_role

    def read_snapshot(self) -> AdminSchemaSnapshot:
        pool = AdminRoleBoundPool(
            self._conninfo,
            expected_role=self._expected_role,
        )
        try:
            pool.open()
            with pool.connection() as connection:
                version_row = connection.execute("SHOW server_version_num").fetchone()
                encoding_row = connection.execute("SHOW server_encoding").fetchone()
                timezone_row = connection.execute("SHOW TimeZone").fetchone()
                if version_row is None or encoding_row is None or timezone_row is None:
                    raise RuntimeError("ADMIN-DB-IDENTITY")
                server_version_num = int(version_row[0])
                encoding = str(encoding_row[0])
                timezone = str(timezone_row[0])
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
            return AdminSchemaSnapshot(
                server_version_num=server_version_num,
                encoding=encoding,
                timezone=timezone,
                tables=tuple(str(row[0]) for row in rows),
            )
        finally:
            pool.close()


__all__ = ("AdminSchemaGateway", "AdminSchemaSnapshot")
