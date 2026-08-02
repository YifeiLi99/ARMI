"""Admin-local role-bound session guard; no Runtime dependency."""

from __future__ import annotations

from contextlib import contextmanager
from typing import Any

import psycopg
from psycopg.pq import TransactionStatus
from psycopg_pool import ConnectionPool

_SEARCH_PATH = "pg_catalog, armi"
_POOL_OPEN_TIMEOUT_SECONDS = 5.0


class AdminRoleSessionError(RuntimeError):
    pass


class AdminRoleBoundPool:
    """Reset and verify an Admin database session before every reuse."""

    __slots__ = ("_expected_role", "_pool")

    def __init__(self, conninfo: str, *, expected_role: str) -> None:
        if not expected_role.startswith("armi_") or not expected_role.endswith(
            "_admin"
        ):
            raise ValueError("expected_role must be an environment Admin login")
        self._expected_role = expected_role
        self._pool = ConnectionPool(
            conninfo,
            min_size=0,
            max_size=1,
            open=False,
            configure=self._configure,
            reset=self._reset,
            kwargs={"application_name": "armi-admin-role-pool"},
        )

    def open(self) -> None:
        self._pool.open(wait=True, timeout=_POOL_OPEN_TIMEOUT_SECONDS)

    def close(self) -> None:
        self._pool.close()

    @contextmanager
    def connection(self):
        with self._pool.connection() as connection:
            self._verify(connection)
            yield connection

    def _configure(self, connection: psycopg.Connection[Any]) -> None:
        connection.execute("SET search_path TO pg_catalog, armi")
        connection.commit()

    def _reset(self, connection: psycopg.Connection[Any]) -> None:
        if connection.info.transaction_status != TransactionStatus.IDLE:
            connection.rollback()
        connection.execute("RESET ROLE")
        connection.execute("RESET ALL")
        connection.execute("SET search_path TO pg_catalog, armi")
        self._verify(connection)
        connection.commit()

    def _verify(self, connection: psycopg.Connection[Any]) -> None:
        row = connection.execute(
            "SELECT session_user, current_user, current_setting('search_path')"
        ).fetchone()
        if row != (self._expected_role, self._expected_role, _SEARCH_PATH):
            raise AdminRoleSessionError("DB-ROLE-SESSION-DIRTY")


__all__ = ("AdminRoleBoundPool", "AdminRoleSessionError")
