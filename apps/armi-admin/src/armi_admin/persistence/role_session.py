"""Admin-local role-bound session guard; no Runtime dependency."""

from __future__ import annotations

from contextlib import contextmanager
from typing import Any, cast

import psycopg
from armi_postgresql_contract.catalog_fingerprint import database_catalog_digest
from armi_runtime_foundation import (
    PostgreSQLAdminParameter,
    PostgreSQLAdminResult,
    PostgreSQLAdminTransaction,
    PostgreSQLAdminUnitOfWork,
)
from psycopg.abc import QueryNoTemplate
from psycopg.pq import TransactionStatus
from psycopg_pool import ConnectionPool

_SEARCH_PATH = "pg_catalog, armi"
_POOL_OPEN_TIMEOUT_SECONDS = 5.0


class AdminRoleSessionError(RuntimeError):
    code = "DB-ROLE-SESSION-DIRTY"


class AdminCommitUnknownError(RuntimeError):
    code = "ADMIN-CORRECTION-COMMIT-UNKNOWN"


class _AdminTransaction:
    __slots__ = ("_connection",)

    def __init__(self, connection: psycopg.Connection[Any]) -> None:
        self._connection = connection

    def execute(
        self,
        statement: str,
        parameters: tuple[PostgreSQLAdminParameter, ...] = (),
    ) -> PostgreSQLAdminResult[tuple[object, ...]]:
        driver_parameters = tuple(
            list(value) if isinstance(value, tuple) else value for value in parameters
        )
        return cast(
            PostgreSQLAdminResult[tuple[object, ...]],
            self._connection.execute(
                cast(QueryNoTemplate, statement), driver_parameters
            ),
        )


class _AdminUnitOfWork:
    __slots__ = ("_connection", "_transaction")

    def __init__(self, connection: psycopg.Connection[Any]) -> None:
        self._connection = connection
        self._transaction = _AdminTransaction(connection)

    @property
    def transaction(self) -> PostgreSQLAdminTransaction:
        return self._transaction

    def commit(self) -> None:
        try:
            self._connection.commit()
        except psycopg.OperationalError as exc:
            raise AdminCommitUnknownError from exc

    def rollback(self) -> None:
        self._connection.rollback()


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

    def catalog_digest(self) -> str:
        with self.connection() as connection:
            connection.execute("SET TRANSACTION READ ONLY")
            return database_catalog_digest(connection)

    @contextmanager
    def connection(self):
        with self._pool.connection() as connection:
            self._verify(connection)
            connection.commit()
            yield connection

    @contextmanager
    def repeatable_read(self):
        with self.connection() as connection:
            connection.execute("BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY")
            unit_of_work = _AdminUnitOfWork(connection)
            try:
                yield cast(PostgreSQLAdminUnitOfWork, unit_of_work)
            except BaseException:
                unit_of_work.rollback()
                raise
            finally:
                if connection.info.transaction_status != TransactionStatus.IDLE:
                    unit_of_work.rollback()

    @contextmanager
    def serializable(self):
        with self.connection() as connection:
            connection.execute("BEGIN ISOLATION LEVEL SERIALIZABLE")
            unit_of_work = _AdminUnitOfWork(connection)
            try:
                yield cast(PostgreSQLAdminUnitOfWork, unit_of_work)
            except BaseException:
                unit_of_work.rollback()
                raise
            finally:
                if connection.info.transaction_status != TransactionStatus.IDLE:
                    unit_of_work.rollback()

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
            raise AdminRoleSessionError


__all__ = (
    "AdminCommitUnknownError",
    "AdminRoleBoundPool",
    "AdminRoleSessionError",
)
