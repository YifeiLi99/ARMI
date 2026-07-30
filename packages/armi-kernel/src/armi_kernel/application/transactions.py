"""Technology-neutral transaction, lock-plan, and CAS contracts."""

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


class LockTargetKind(StrEnum):
    SUBJECT = "subject"
    LIFE_RUNTIME = "life_runtime"
    SUBJECT_COMPONENT = "subject_component"
    RELATIONSHIP = "relationship"
    ACTIVITY = "activity"
    MEMORY = "memory"
    GOVERNANCE_EFFECT = "governance_effect"


_LOCK_ORDER = {
    kind: position
    for position, kind in enumerate(
        (
            LockTargetKind.SUBJECT,
            LockTargetKind.LIFE_RUNTIME,
            LockTargetKind.SUBJECT_COMPONENT,
            LockTargetKind.RELATIONSHIP,
            LockTargetKind.ACTIVITY,
            LockTargetKind.MEMORY,
            LockTargetKind.GOVERNANCE_EFFECT,
        )
    )
}


@dataclass(frozen=True, slots=True)
class LockTarget:
    kind: LockTargetKind
    object_id: UUID
    expected_version: int | None

    def __post_init__(self) -> None:
        if type(self.kind) is not LockTargetKind:
            raise TypeError("lock target kind must be LockTargetKind")
        if type(self.object_id) is not UUID:
            raise TypeError("lock target object_id must be UUID")
        if self.expected_version is not None and (
            type(self.expected_version) is not int or self.expected_version < 0
        ):
            raise ValueError("expected_version must be a non-negative integer or None")


@dataclass(frozen=True, slots=True)
class LockPlan:
    targets: tuple[LockTarget, ...] = ()

    def __post_init__(self) -> None:
        if type(self.targets) is not tuple or any(
            type(target) is not LockTarget for target in self.targets
        ):
            raise TypeError("lock plan targets must be a tuple of LockTarget")
        identities = [(target.kind, target.object_id) for target in self.targets]
        if len(identities) != len(set(identities)):
            raise ValueError("lock plan contains a duplicate target")
        ordered = tuple(
            sorted(
                self.targets,
                key=lambda target: (
                    _LOCK_ORDER[target.kind],
                    target.object_id.bytes,
                ),
            )
        )
        object.__setattr__(self, "targets", ordered)

    @classmethod
    def for_cas(
        cls,
        root: LockTarget,
        *additional_targets: LockTarget,
    ) -> LockPlan:
        if type(root) is not LockTarget or root.expected_version is None:
            raise ValueError("CAS root must provide expected_version")
        return cls((root, *additional_targets))


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
    def lock_plan(self) -> LockPlan:
        """Return the canonical lock plan selected before the transaction."""
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
    "LockPlan",
    "LockTarget",
    "LockTargetKind",
    "PostCommitAction",
    "TransactionIsolation",
    "UnitOfWork",
    "classify_cas_rows",
)
