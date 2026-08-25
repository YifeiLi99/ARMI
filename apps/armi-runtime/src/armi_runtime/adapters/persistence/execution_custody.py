"""Session advisory-lock custody for slow Runtime operations."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any, Literal
from uuid import UUID

import psycopg
from armi_kernel.application import (
    ExecutionCustodyMode,
    ExecutionCustodyPermit,
    ExecutionCustodyRequest,
    ExecutionCustodyViolation,
)
from armi_kernel.contracts import Instant
from psycopg.pq import TransactionStatus
from psycopg_pool import AsyncConnectionPool, PoolTimeout

from .role_policy import physical_role_name

_SEARCH_PATH = "pg_catalog, armi"


async def _configure(connection: psycopg.AsyncConnection[tuple[Any, ...]]) -> None:
    await connection.set_autocommit(True)
    await connection.execute("SET search_path TO pg_catalog, armi")


async def _reset(connection: psycopg.AsyncConnection[tuple[Any, ...]]) -> None:
    if connection.info.transaction_status != TransactionStatus.IDLE:
        await connection.rollback()
    await connection.execute("SELECT pg_catalog.pg_advisory_unlock_all()")
    await connection.execute("RESET ALL")
    await connection.execute("SET search_path TO pg_catalog, armi")


class PostgreSQLExecutionCustody:
    __slots__ = ("_pool", "_pool_timeout_seconds")

    def __init__(
        self,
        conninfo: str,
        *,
        environment_id: UUID,
        pool_max: int,
        pool_timeout_seconds: int,
        role_kind: Literal["runtime", "migrator"] = "runtime",
    ) -> None:
        expected_role = physical_role_name(environment_id, role_kind)
        self._pool_timeout_seconds = pool_timeout_seconds

        async def check(connection: psycopg.AsyncConnection[tuple[Any, ...]]) -> None:
            row = await (
                await connection.execute(
                    "SELECT session_user,current_user,current_setting('search_path')"
                )
            ).fetchone()
            if row != (expected_role, expected_role, _SEARCH_PATH):
                raise ExecutionCustodyViolation("CUSTODY-SESSION-IDENTITY")

        self._pool = AsyncConnectionPool[psycopg.AsyncConnection[tuple[Any, ...]]](
            conninfo,
            min_size=0,
            max_size=pool_max,
            open=False,
            configure=_configure,
            check=check,
            reset=_reset,
            timeout=float(pool_timeout_seconds),
            name="armi-execution-custody",
        )

    async def open(self) -> None:
        try:
            await self._pool.open(wait=True)
        except psycopg.Error, PoolTimeout:
            raise ExecutionCustodyViolation("CUSTODY-DATABASE") from None

    async def close(self) -> None:
        await self._pool.close()

    @asynccontextmanager
    async def hold(
        self,
        requests: tuple[ExecutionCustodyRequest, ...],
        *,
        deadline_at: Instant | None,
    ) -> AsyncGenerator[ExecutionCustodyPermit]:
        permit = ExecutionCustodyPermit(requests)
        timeout = self._timeout(deadline_at)
        try:
            async with self._pool.connection(
                timeout=float(self._pool_timeout_seconds)
            ) as connection:
                deadline = (
                    asyncio.timeout(timeout) if timeout is not None else _no_timeout()
                )
                async with deadline:
                    for request in requests:
                        function = (
                            "pg_catalog.pg_advisory_lock_shared"
                            if request.mode is ExecutionCustodyMode.SHARED
                            else "pg_catalog.pg_advisory_lock"
                        )
                        await connection.execute(
                            f"SELECT {function}(pg_catalog.hashtextextended(%s,0))",
                            (request.scope.lock_name,),
                        )
                try:
                    yield permit
                finally:
                    await connection.execute(
                        "SELECT pg_catalog.pg_advisory_unlock_all()"
                    )
        except TimeoutError:
            raise ExecutionCustodyViolation("CUSTODY-TIMEOUT") from None
        except ExecutionCustodyViolation:
            raise
        except psycopg.Error, PoolTimeout:
            raise ExecutionCustodyViolation("CUSTODY-DATABASE") from None

    @staticmethod
    def _timeout(deadline_at: Instant | None) -> float | None:
        if deadline_at is None:
            return None
        remaining = (deadline_at.value - datetime.now(UTC)).total_seconds()
        if remaining <= 0:
            raise ExecutionCustodyViolation("CUSTODY-DEADLINE")
        return remaining


@asynccontextmanager
async def _no_timeout() -> AsyncGenerator[None]:
    yield


__all__ = ("PostgreSQLExecutionCustody",)
