"""Minimal transaction surface shared with in-process business modules."""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class PostgreSQLTransaction(Protocol):
    """The active PostgreSQL transaction made available to owner participants."""

    execute: Any


@runtime_checkable
class PostgreSQLTransactionAccess(Protocol):
    """Expose an already active caller-owned transaction without committing it."""

    @property
    def transaction(self) -> PostgreSQLTransaction: ...


__all__ = ("PostgreSQLTransaction", "PostgreSQLTransactionAccess")
