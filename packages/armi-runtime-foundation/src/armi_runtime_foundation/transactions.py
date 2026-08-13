"""Minimal transaction surface shared with in-process business modules."""

from __future__ import annotations

from contextlib import AbstractAsyncContextManager
from typing import Any, Protocol, runtime_checkable
from uuid import UUID

from armi_kernel.application import AuditWriter, DurableWorkWriter, RuntimeFence


@runtime_checkable
class PostgreSQLTransaction(Protocol):
    """The active PostgreSQL transaction made available to owner participants."""

    execute: Any


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


class PostgreSQLRuntimeUnitOfWorkFactory(Protocol):
    """Create caller-owned Runtime transactions for a business coordinator."""

    @property
    def environment_id(self) -> UUID: ...

    async def open(self) -> None: ...
    async def close(self) -> None: ...
    def unit_of_work(
        self, *, read_only: bool = False
    ) -> AbstractAsyncContextManager[PostgreSQLRuntimeUnitOfWork]: ...


@runtime_checkable
class StopSignal(Protocol):
    """Business-neutral cooperative stop signal for long-running workers."""

    def is_set(self) -> bool: ...
    async def wait(self) -> bool: ...


class RuntimeTransactionFailure(RuntimeError):
    """Stable base for redacted transaction failures crossing module boundaries."""

    code: str


__all__ = (
    "PostgreSQLRuntimeUnitOfWork",
    "PostgreSQLRuntimeUnitOfWorkFactory",
    "PostgreSQLTransaction",
    "PostgreSQLTransactionAccess",
    "RuntimeTransactionFailure",
    "StopSignal",
)
