"""Technology-neutral transaction and CAS contracts."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol, runtime_checkable
from uuid import UUID

_ACTION_KIND = re.compile(r"^[a-z][a-z0-9._-]{0,63}$", re.ASCII)


class TransactionIsolation(StrEnum):
    READ_COMMITTED = "read_committed"
    REPEATABLE_READ = "repeatable_read"
    SERIALIZABLE = "serializable"


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


__all__ = (
    "BeforeCommitHook",
    "PostCommitAction",
    "TransactionIsolation",
)
