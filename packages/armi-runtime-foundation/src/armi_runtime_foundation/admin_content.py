"""Owner-neutral protocol for versioned, explicitly administrative content writes."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol, runtime_checkable
from uuid import UUID

from .admin_transactions import PostgreSQLAdminTransaction


class AdminContentViolation(ValueError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class AdminContentContext:
    subject_id: UUID
    change_id: UUID
    subject_party_id: UUID
    creator_party_id: UUID


@dataclass(frozen=True, slots=True)
class AdminContentCommand:
    action: Literal["create", "update", "delete"]
    object_id: UUID
    expected_version: int
    values: dict[str, object]


class AdminContentPort(Protocol):
    def apply(
        self,
        transaction: PostgreSQLAdminTransaction,
        context: AdminContentContext,
        command: AdminContentCommand,
        /,
    ) -> dict[str, object]: ...


class AdminContentGuardPort(Protocol):
    def content_busy(
        self, transaction: PostgreSQLAdminTransaction, *, subject_id: UUID
    ) -> bool: ...


@runtime_checkable
class AdminContentArtifactPort(AdminContentPort, Protocol):
    def prepare_content(
        self, command: AdminContentCommand
    ) -> tuple[bytes, str, str] | None: ...


__all__ = (
    "AdminContentArtifactPort",
    "AdminContentCommand",
    "AdminContentContext",
    "AdminContentGuardPort",
    "AdminContentPort",
    "AdminContentViolation",
)
