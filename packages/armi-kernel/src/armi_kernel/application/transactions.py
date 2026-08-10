"""Technology-neutral transaction and CAS contracts."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol, runtime_checkable
from uuid import UUID

from .auditing import AuditWriter
from .durable_work import DurableWorkWriter
from .runtime_authority import RuntimeFence

_ACTION_KIND = re.compile(r"^[a-z][a-z0-9._-]{0,63}$", re.ASCII)


class TransactionIsolation(StrEnum):
    READ_COMMITTED = "read_committed"
    REPEATABLE_READ = "repeatable_read"
    SERIALIZABLE = "serializable"


class CasStatus(StrEnum):
    APPLIED = "applied"
    CONFLICT = "conflict"


def classify_cas_rows(affected_rows: int) -> CasStatus:
    if type(affected_rows) is not int or affected_rows < 0:
        raise ValueError("affected_rows must be a non-negative integer")
    if affected_rows == 1:
        return CasStatus.APPLIED
    if affected_rows == 0:
        return CasStatus.CONFLICT
    raise ValueError("CAS affected more than one row")


@runtime_checkable
class BeforeCommitHook(Protocol):
    async def __call__(self) -> None:
        """Complete one transaction-local responsibility."""
        ...


@dataclass(frozen=True, slots=True)
class PostCommitAction:
    """A stable reference to work that may be considered after commit."""

    kind: str
    reference: UUID

    def __post_init__(self) -> None:
        if _ACTION_KIND.fullmatch(self.kind) is None:
            raise ValueError("post-commit action kind is invalid")
        if type(self.reference) is not UUID or self.reference.version != 7:
            raise ValueError("post-commit action reference must be UUIDv7")


@runtime_checkable
class UnitOfWork(Protocol):
    @property
    def audit(self) -> AuditWriter:
        """Return the writer bound to this Unit of Work transaction."""
        ...

    @property
    def work(self) -> DurableWorkWriter:
        """Return the durable-work writer bound to this transaction."""
        ...

    @property
    def runtime_fence(self) -> RuntimeFence | None:
        """Return the write fence, or ``None`` for read-only/bootstrap work."""
        ...

    @property
    def committed_actions(self) -> tuple[PostCommitAction, ...]:
        """Return actions only after the transaction is known committed."""
        ...

    def add_before_commit(self, hook: BeforeCommitHook) -> None:
        """Register one transaction-local hook before finalization."""
        ...

    def defer_after_commit(self, action: PostCommitAction) -> None:
        """Register an immutable action description, not an executable callback."""
        ...

    def request_rollback(self) -> None:
        """Require rollback without exposing transaction control to repositories."""
        ...


__all__ = (
    "BeforeCommitHook",
    "CasStatus",
    "PostCommitAction",
    "TransactionIsolation",
    "UnitOfWork",
    "classify_cas_rows",
)
