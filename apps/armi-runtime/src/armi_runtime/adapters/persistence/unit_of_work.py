"""Async PostgreSQL transaction coordination with no implicit replay."""

from __future__ import annotations

import asyncio
from contextlib import suppress
from contextvars import ContextVar, Token
from enum import StrEnum
from types import TracebackType
from typing import Any, Protocol, Self
from uuid import UUID

import psycopg
from armi_kernel.application import (
    BeforeCommitHook,
    LockPlan,
    LockTarget,
    PostCommitAction,
    TransactionIsolation,
)
from psycopg import sql
from psycopg.pq import TransactionStatus
from psycopg_pool import AsyncConnectionPool, PoolTimeout

from armi_runtime.adapters.persistence.role_policy import physical_role_name
from armi_runtime.adapters.transaction_errors import (
    CommitState,
    DatabaseFailureKind,
    DatabaseTransactionError,
    map_database_error,
)

_SEARCH_PATH = "pg_catalog, armi"
_ACTIVE_UOW: ContextVar[PostgreSQLUnitOfWork | None] = ContextVar(
    "armi_active_postgresql_uow",
    default=None,
)
_ISOLATION_SQL = {
    TransactionIsolation.READ_COMMITTED: sql.SQL("READ COMMITTED"),
    TransactionIsolation.REPEATABLE_READ: sql.SQL("REPEATABLE READ"),
    TransactionIsolation.SERIALIZABLE: sql.SQL("SERIALIZABLE"),
}


class LockAcquirer(Protocol):
    async def __call__(
        self,
        connection: psycopg.AsyncConnection[tuple[Any, ...]],
        target: LockTarget,
    ) -> None:
        """Acquire exactly one registered target without dynamic SQL."""
        ...


class _State(StrEnum):
    NEW = "new"
    ACTIVE = "active"
    COMMITTED = "committed"
    ROLLED_BACK = "rolled_back"
    COMMIT_UNKNOWN = "commit_unknown"


class _RollbackRequested(Exception):
    pass


def _transaction_error(
    code: str,
    kind: DatabaseFailureKind = DatabaseFailureKind.INTERNAL,
) -> DatabaseTransactionError:
    return DatabaseTransactionError(code, kind, False, CommitState.NOT_STARTED)


async def _configure_connection(
    connection: psycopg.AsyncConnection[tuple[Any, ...]],
) -> None:
    await connection.set_autocommit(True)
    await connection.execute("SET search_path TO pg_catalog, armi")


async def _verify_connection(
    connection: psycopg.AsyncConnection[tuple[Any, ...]],
    expected_role: str,
) -> None:
    row = await (
        await connection.execute(
            "SELECT session_user, current_user, current_setting('search_path')"
        )
    ).fetchone()
    if row != (expected_role, expected_role, _SEARCH_PATH):
        raise _transaction_error(
            "DB-TX-SESSION-IDENTITY",
            DatabaseFailureKind.INTEGRITY,
        )


async def _reset_connection(
    connection: psycopg.AsyncConnection[tuple[Any, ...]],
) -> None:
    if connection.info.transaction_status != TransactionStatus.IDLE:
        await connection.rollback()
    await connection.execute("RESET ROLE")
    await connection.execute("RESET ALL")
    await connection.execute("SET search_path TO pg_catalog, armi")


class PostgreSQLUnitOfWorkFactory:
    """Own one runtime-role pool without opening it during composition."""

    __slots__ = (
        "_acquire_timeout_seconds",
        "_environment_id",
        "_expected_role",
        "_lock_acquirer",
        "_pool",
        "_statement_timeout_milliseconds",
    )

    def __init__(
        self,
        conninfo: str,
        *,
        environment_id: UUID,
        lock_acquirer: LockAcquirer,
        pool_min: int,
        pool_max: int,
        acquire_timeout_seconds: int,
        statement_timeout_seconds: int,
    ) -> None:
        if environment_id.version != 7:
            raise ValueError("environment_id must be UUIDv7")
        for name, value in (
            ("pool_min", pool_min),
            ("pool_max", pool_max),
            ("acquire_timeout_seconds", acquire_timeout_seconds),
            ("statement_timeout_seconds", statement_timeout_seconds),
        ):
            if type(value) is not int or value <= 0:
                raise ValueError(f"{name} must be a positive integer")
        if pool_min > pool_max:
            raise ValueError("pool_min must not exceed pool_max")
        self._environment_id = environment_id
        self._expected_role = physical_role_name(environment_id, "runtime")
        self._acquire_timeout_seconds = acquire_timeout_seconds
        self._statement_timeout_milliseconds = statement_timeout_seconds * 1000

        async def check(
            connection: psycopg.AsyncConnection[tuple[Any, ...]],
        ) -> None:
            await _verify_connection(connection, self._expected_role)

        self._pool = AsyncConnectionPool[psycopg.AsyncConnection[tuple[Any, ...]]](
            conninfo,
            min_size=pool_min,
            max_size=pool_max,
            open=False,
            configure=_configure_connection,
            check=check,
            reset=_reset_connection,
            timeout=float(acquire_timeout_seconds),
            name="armi-runtime-uow",
        )
        self._lock_acquirer = lock_acquirer

    async def open(self) -> None:
        try:
            await self._pool.open(wait=True)
        except PoolTimeout as error:
            raise map_database_error(error) from None

    async def close(self) -> None:
        await self._pool.close()

    def unit_of_work(
        self,
        lock_plan: LockPlan,
        *,
        isolation: TransactionIsolation = TransactionIsolation.READ_COMMITTED,
        read_only: bool = False,
    ) -> PostgreSQLUnitOfWork:
        return PostgreSQLUnitOfWork(
            self._pool,
            expected_role=self._expected_role,
            lock_plan=lock_plan,
            lock_acquirer=self._lock_acquirer,
            isolation=isolation,
            read_only=read_only,
            statement_timeout_milliseconds=self._statement_timeout_milliseconds,
            acquire_timeout_seconds=self._acquire_timeout_seconds,
        )


class PostgreSQLUnitOfWork:
    """Coordinate one explicit outer transaction and immutable commit actions."""

    __slots__ = (
        "_acquire_timeout_seconds",
        "_active_token",
        "_before_commit",
        "_committed_actions",
        "_connection",
        "_deferred_actions",
        "_expected_role",
        "_isolation",
        "_lock_acquirer",
        "_lock_plan",
        "_pool",
        "_read_only",
        "_rollback_requested",
        "_state",
        "_statement_timeout_milliseconds",
        "_transaction",
    )

    def __init__(
        self,
        pool: AsyncConnectionPool[psycopg.AsyncConnection[tuple[Any, ...]]],
        *,
        expected_role: str,
        lock_plan: LockPlan,
        lock_acquirer: LockAcquirer,
        isolation: TransactionIsolation,
        read_only: bool,
        statement_timeout_milliseconds: int,
        acquire_timeout_seconds: int,
    ) -> None:
        if type(lock_plan) is not LockPlan:
            raise TypeError("lock_plan must be LockPlan")
        if type(isolation) is not TransactionIsolation:
            raise TypeError("isolation must be TransactionIsolation")
        if type(read_only) is not bool:
            raise TypeError("read_only must be bool")
        self._pool = pool
        self._expected_role = expected_role
        self._lock_plan = lock_plan
        self._lock_acquirer = lock_acquirer
        self._isolation = isolation
        self._read_only = read_only
        self._statement_timeout_milliseconds = statement_timeout_milliseconds
        self._acquire_timeout_seconds = acquire_timeout_seconds
        self._state = _State.NEW
        self._connection: psycopg.AsyncConnection[tuple[Any, ...]] | None = None
        self._transaction: Any = None
        self._active_token: Token[PostgreSQLUnitOfWork | None] | None = None
        self._before_commit: list[BeforeCommitHook] = []
        self._deferred_actions: list[PostCommitAction] = []
        self._committed_actions: tuple[PostCommitAction, ...] = ()
        self._rollback_requested = False

    @property
    def lock_plan(self) -> LockPlan:
        return self._lock_plan

    @property
    def committed_actions(self) -> tuple[PostCommitAction, ...]:
        return self._committed_actions

    def add_before_commit(self, hook: BeforeCommitHook) -> None:
        self._require_active()
        if not callable(hook):
            raise TypeError("before-commit hook must be callable")
        self._before_commit.append(hook)

    def defer_after_commit(self, action: PostCommitAction) -> None:
        self._require_active()
        if type(action) is not PostCommitAction:
            raise TypeError("post-commit action must be PostCommitAction")
        self._deferred_actions.append(action)

    def request_rollback(self) -> None:
        self._require_active()
        self._rollback_requested = True

    async def __aenter__(self) -> Self:
        if self._state is not _State.NEW:
            raise _transaction_error("DB-TX-STATE")
        if _ACTIVE_UOW.get() is not None:
            raise _transaction_error("DB-TX-NESTED")
        try:
            self._connection = await self._pool.getconn(
                timeout=float(self._acquire_timeout_seconds)
            )
            await _verify_connection(self._connection, self._expected_role)
            self._transaction = self._connection.transaction()
            await self._transaction.__aenter__()
            await self._set_transaction_characteristics()
            for target in self._lock_plan.targets:
                await self._lock_acquirer(self._connection, target)
        except BaseException as error:
            await self._rollback_after_enter_failure(error)
            if isinstance(error, asyncio.CancelledError):
                raise
            if isinstance(error, DatabaseTransactionError):
                raise
            if isinstance(error, (psycopg.Error, PoolTimeout)):
                raise map_database_error(error, rolled_back=True) from None
            raise
        self._state = _State.ACTIVE
        self._active_token = _ACTIVE_UOW.set(self)
        return self

    async def __aexit__(
        self,
        exception_type: type[BaseException] | None,
        exception: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool:
        if self._state is not _State.ACTIVE or self._connection is None:
            raise _transaction_error("DB-TX-STATE")
        try:
            if exception is not None:
                await self._finish_rollback(exception_type, exception, traceback)
                if isinstance(exception, (psycopg.Error, PoolTimeout)):
                    raise map_database_error(exception, rolled_back=True) from None
                return False
            if self._rollback_requested:
                rollback = _RollbackRequested()
                await self._finish_rollback(
                    _RollbackRequested,
                    rollback,
                    rollback.__traceback__,
                )
                return False
            for hook in self._before_commit:
                await hook()
            try:
                await self._transaction.__aexit__(None, None, None)
            except BaseException as error:
                self._state = _State.COMMIT_UNKNOWN
                self._committed_actions = ()
                if isinstance(error, asyncio.CancelledError):
                    raise DatabaseTransactionError(
                        "DB-TX-COMMIT-UNKNOWN",
                        DatabaseFailureKind.UNKNOWN,
                        False,
                        CommitState.UNKNOWN,
                    ) from None
                if isinstance(error, Exception):
                    raise map_database_error(error, during_commit=True) from None
                raise
            self._state = _State.COMMITTED
            self._committed_actions = tuple(self._deferred_actions)
            return False
        except BaseException as error:
            await self._rollback_after_failure(error)
            if isinstance(error, asyncio.CancelledError):
                raise
            if isinstance(error, DatabaseTransactionError):
                raise
            if isinstance(error, (psycopg.Error, PoolTimeout)):
                raise map_database_error(error, rolled_back=True) from None
            raise
        finally:
            self._clear_active()
            await self._return_connection()

    def _require_active(self) -> None:
        if self._state is not _State.ACTIVE:
            raise _transaction_error("DB-TX-STATE")

    async def _set_transaction_characteristics(self) -> None:
        assert self._connection is not None
        await self._connection.execute(
            sql.SQL("SET TRANSACTION ISOLATION LEVEL {}").format(
                _ISOLATION_SQL[self._isolation]
            )
        )
        if self._read_only:
            await self._connection.execute("SET TRANSACTION READ ONLY")
        await self._connection.execute(
            "SELECT pg_catalog.set_config('statement_timeout', %s, true)",
            (f"{self._statement_timeout_milliseconds}ms",),
        )

    async def _finish_rollback(
        self,
        exception_type: type[BaseException] | None,
        exception: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        await self._transaction.__aexit__(exception_type, exception, traceback)
        self._state = _State.ROLLED_BACK
        self._committed_actions = ()

    async def _rollback_after_enter_failure(self, error: BaseException) -> None:
        if self._transaction is not None:
            with suppress(BaseException):
                await self._transaction.__aexit__(
                    type(error),
                    error,
                    error.__traceback__,
                )
        self._state = _State.ROLLED_BACK
        await self._return_connection()

    async def _rollback_after_failure(self, error: BaseException) -> None:
        if self._state in {_State.ROLLED_BACK, _State.COMMIT_UNKNOWN}:
            return
        with suppress(BaseException):
            await self._transaction.__aexit__(
                type(error),
                error,
                error.__traceback__,
            )
        self._state = _State.ROLLED_BACK
        self._committed_actions = ()

    def _clear_active(self) -> None:
        if self._active_token is not None:
            _ACTIVE_UOW.reset(self._active_token)
            self._active_token = None

    async def _return_connection(self) -> None:
        if self._connection is not None:
            connection = self._connection
            self._connection = None
            await self._pool.putconn(connection)

    def _connection_for_repository(
        self,
    ) -> psycopg.AsyncConnection[tuple[Any, ...]]:
        """Package-private access for registered persistence adapters."""
        self._require_active()
        assert self._connection is not None
        return self._connection


__all__ = (
    "LockAcquirer",
    "PostgreSQLUnitOfWork",
    "PostgreSQLUnitOfWorkFactory",
)
