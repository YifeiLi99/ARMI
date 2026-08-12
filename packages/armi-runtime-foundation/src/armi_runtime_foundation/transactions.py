"""Minimal transaction surface shared with in-process business modules."""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable
from uuid import UUID


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
    def runtime_fence(self) -> Any: ...

    @property
    def audit(self) -> Any: ...


__all__ = (
    "PostgreSQLRuntimeUnitOfWork",
    "PostgreSQLTransaction",
    "PostgreSQLTransactionAccess",
)
