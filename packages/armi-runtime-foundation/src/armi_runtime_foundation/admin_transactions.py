"""Typed synchronous transaction boundary for the offline Admin process."""

from __future__ import annotations

from contextlib import AbstractContextManager
from datetime import date, datetime
from decimal import Decimal
from typing import Protocol, TypeVar
from uuid import UUID

PostgreSQLAdminScalar = (
    None | bool | int | float | str | bytes | UUID | date | datetime | Decimal
)
PostgreSQLAdminParameter = PostgreSQLAdminScalar | tuple[PostgreSQLAdminScalar, ...]
AdminRowT = TypeVar("AdminRowT", covariant=True)


class PostgreSQLAdminResult[AdminRowT](Protocol):
    @property
    def rowcount(self) -> int: ...

    def fetchone(self) -> AdminRowT | None: ...

    def fetchall(self) -> list[AdminRowT]: ...


class PostgreSQLAdminTransaction(Protocol):
    def execute(
        self,
        statement: str,
        parameters: tuple[PostgreSQLAdminParameter, ...] = (),
    ) -> PostgreSQLAdminResult[tuple[object, ...]]: ...


class PostgreSQLAdminUnitOfWork(Protocol):
    @property
    def transaction(self) -> PostgreSQLAdminTransaction: ...

    def commit(self) -> None: ...

    def rollback(self) -> None: ...


class PostgreSQLAdminUnitOfWorkFactory(Protocol):
    def repeatable_read(
        self,
    ) -> AbstractContextManager[PostgreSQLAdminUnitOfWork]: ...

    def serializable(self) -> AbstractContextManager[PostgreSQLAdminUnitOfWork]: ...


__all__ = (
    "PostgreSQLAdminParameter",
    "PostgreSQLAdminResult",
    "PostgreSQLAdminScalar",
    "PostgreSQLAdminTransaction",
    "PostgreSQLAdminUnitOfWork",
    "PostgreSQLAdminUnitOfWorkFactory",
)
