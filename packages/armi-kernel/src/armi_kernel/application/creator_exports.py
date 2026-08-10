"""Creator commands and projections for one local complete-data export."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol, runtime_checkable
from uuid import UUID

from armi_kernel.contracts import IdempotencyKey, Instant, TraceId

_DIRECTORY = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$", re.ASCII)


class CreatorExportStatus(StrEnum):
    RUNNING = "running"
    COMPLETED = "completed"
    PARTIAL = "partial"
    FAILED = "failed"


class CreatorExportViolation(RuntimeError):
    __slots__ = ("code",)

    def __init__(self, code: str) -> None:
        if type(code) is not str or not code.startswith("CREATOR-EXPORT-"):
            raise ValueError("Creator export violation code is invalid")
        self.code = code
        super().__init__("Creator export failed")


@dataclass(frozen=True, slots=True)
class CreatorExportCommand:
    directory_name: str
    idempotency_key: IdempotencyKey
    trace_id: TraceId

    def __post_init__(self) -> None:
        if (
            type(self.directory_name) is not str
            or _DIRECTORY.fullmatch(self.directory_name) is None
            or self.directory_name in {".", ".."}
            or type(self.idempotency_key) is not IdempotencyKey
            or type(self.trace_id) is not TraceId
        ):
            raise CreatorExportViolation("CREATOR-EXPORT-COMMAND")


@dataclass(frozen=True, slots=True)
class CreatorExportResult:
    export_id: UUID
    status: CreatorExportStatus
    directory_name: str
    destination_path: str
    table_count: int
    row_count: int
    artifact_count: int
    missing_artifacts: tuple[str, ...]
    error_code: str | None
    created_at: Instant
    completed_at: Instant | None
    newly_created: bool

    def __post_init__(self) -> None:
        if (
            type(self.export_id) is not UUID
            or self.export_id.version != 7
            or _DIRECTORY.fullmatch(self.directory_name) is None
            or type(self.destination_path) is not str
            or not self.destination_path
            or type(self.status) is not CreatorExportStatus
            or any(
                type(value) is not int or value < 0
                for value in (self.table_count, self.row_count, self.artifact_count)
            )
            or type(self.missing_artifacts) is not tuple
            or any(
                type(value) is not str or not value for value in self.missing_artifacts
            )
            or len(set(self.missing_artifacts)) != len(self.missing_artifacts)
            or (self.error_code is not None and type(self.error_code) is not str)
            or type(self.created_at) is not Instant
            or (
                self.completed_at is not None and type(self.completed_at) is not Instant
            )
            or type(self.newly_created) is not bool
            or (
                self.status is CreatorExportStatus.RUNNING
                and self.completed_at is not None
            )
            or (
                self.status is not CreatorExportStatus.RUNNING
                and self.completed_at is None
            )
        ):
            raise CreatorExportViolation("CREATOR-EXPORT-RESULT")


@runtime_checkable
class CreatorExportPort(Protocol):
    async def export(self, command: CreatorExportCommand) -> CreatorExportResult: ...

    async def get(self, export_id: UUID) -> CreatorExportResult | None: ...


__all__ = (
    "CreatorExportCommand",
    "CreatorExportPort",
    "CreatorExportResult",
    "CreatorExportStatus",
    "CreatorExportViolation",
)
