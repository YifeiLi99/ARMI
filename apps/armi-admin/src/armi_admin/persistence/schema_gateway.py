"""Read-only schema ledger gateway for the Admin MCP tools."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .role_session import AdminRoleBoundPool


@dataclass(frozen=True, slots=True)
class AdminSchemaSnapshot:
    server_version_num: int
    encoding: str
    timezone: str
    migrations: tuple[tuple[int, str, str], ...]


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
                rows: list[tuple[Any, ...]] = connection.execute(
                    "SELECT version, name, sha256 "
                    "FROM armi.schema_migrations ORDER BY version"
                ).fetchall()
            return AdminSchemaSnapshot(
                server_version_num=server_version_num,
                encoding=encoding,
                timezone=timezone,
                migrations=tuple(
                    (int(row[0]), str(row[1]), str(row[2])) for row in rows
                ),
            )
        finally:
            pool.close()


__all__ = ("AdminSchemaGateway", "AdminSchemaSnapshot")
