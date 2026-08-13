"""Typed transaction surface shared with in-process business modules."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date, datetime
from decimal import Decimal
from types import TracebackType
from typing import LiteralString, Never, Protocol, TypeVar, runtime_checkable
from uuid import UUID

from armi_kernel.application import (
    AuditWriter,
    BeforeCommitHook,
    DurableWorkWriter,
    PostCommitAction,
    RuntimeFence,
    TransactionIsolation,
)

type PostgreSQLScalar = (
    bool | int | float | Decimal | str | bytes | UUID | date | datetime | None
)
type PostgreSQLParameter = PostgreSQLScalar | Sequence[PostgreSQLScalar]
type PostgreSQLParameters = tuple[PostgreSQLParameter, ...]
RowT_co = TypeVar("RowT_co", covariant=True)


@runtime_checkable
class PostgreSQLResult(Protocol[RowT_co]):
    """Result of one literal SQL statement without exposing a driver cursor."""

    @property
    def rowcount(self) -> int: ...

    async def fetchone(self) -> RowT_co | None: ...

    async def fetchall(self) -> Sequence[RowT_co]: ...


@runtime_checkable
class PostgreSQLTransaction(Protocol):
    """The active PostgreSQL transaction made available to owner participants."""

    async def execute(
        self,
        statement: LiteralString,
        parameters: PostgreSQLParameters = (),
        /,
    ) -> PostgreSQLResult[tuple[Never, ...]]: ...


@runtime_checkable
class PostgreSQLTransactionAccess(Protocol):
    """Expose an already active caller-owned transaction without committing it."""

    @property
    def transaction(self) -> PostgreSQLTransaction: ...


@runtime_checkable
class PostgreSQLRuntimeUnitOfWork(PostgreSQLTransactionAccess, Protocol):
    """Active Runtime transaction surface required by business coordinators."""

    @property
    def environment_id(self) -> UUID: ...

    @property
    def runtime_fence(self) -> RuntimeFence | None: ...

    @property
    def audit(self) -> AuditWriter: ...

    @property
    def work(self) -> DurableWorkWriter: ...

    @property
    def committed_actions(self) -> tuple[PostCommitAction, ...]: ...

    def add_before_commit(self, hook: BeforeCommitHook) -> None: ...

    def defer_after_commit(self, action: PostCommitAction) -> None: ...

    def request_rollback(self) -> None: ...


@runtime_checkable
class PostgreSQLRuntimeUnitOfWorkContext(Protocol):
    async def __aenter__(self) -> PostgreSQLRuntimeUnitOfWork: ...

    async def __aexit__(
        self,
        exception_type: type[BaseException] | None,
        exception: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool | None: ...


class PostgreSQLRuntimeUnitOfWorkFactory(Protocol):
    """Create caller-owned Runtime transactions for a business coordinator."""

    @property
    def environment_id(self) -> UUID: ...

    async def open(self) -> None: ...
    async def close(self) -> None: ...
    def unit_of_work(
        self,
        *,
        isolation: TransactionIsolation = TransactionIsolation.READ_COMMITTED,
        read_only: bool = False,
    ) -> PostgreSQLRuntimeUnitOfWorkContext: ...


@runtime_checkable
class StopSignal(Protocol):
    """Business-neutral cooperative stop signal for long-running workers."""

    def is_set(self) -> bool: ...
    async def wait(self) -> bool: ...


class RuntimeTransactionFailure(RuntimeError):
    """Stable base for redacted transaction failures crossing module boundaries."""

    code: str


__all__ = (
    "PostgreSQLParameter",
    "PostgreSQLParameters",
    "PostgreSQLResult",
    "PostgreSQLRuntimeUnitOfWork",
    "PostgreSQLRuntimeUnitOfWorkContext",
    "PostgreSQLRuntimeUnitOfWorkFactory",
    "PostgreSQLScalar",
    "PostgreSQLTransaction",
    "PostgreSQLTransactionAccess",
    "RuntimeTransactionFailure",
    "StopSignal",
)
