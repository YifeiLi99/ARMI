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

    __slots__ = ("_pool",)

    def __init__(self, pool: AdminRoleBoundPool) -> None:
        self._pool = pool

    def read_snapshot(self) -> AdminSchemaSnapshot:
        with self._pool.connection() as connection:
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


__all__ = ("AdminSchemaGateway", "AdminSchemaSnapshot")
