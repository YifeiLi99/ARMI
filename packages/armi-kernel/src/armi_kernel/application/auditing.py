"""Technology-neutral contracts for append-only normal audit records."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol, runtime_checkable
from uuid import UUID

from armi_kernel.contracts import (
    ErrorCategory,
    Instant,
    Purpose,
    SubjectId,
    TraceId,
)

_TOKEN = re.compile(r"^[a-z][a-z0-9._-]{0,127}$", re.ASCII)


class AuditSensitivity(StrEnum):
    INTERNAL = "internal"
    PRIVATE = "private"
    RESTRICTED = "restricted"


class AuditResultStatus(StrEnum):
    ACCEPTED = "accepted"
    APPLIED = "applied"
    WAITING = "waiting"
    REJECTED = "rejected"
    UNAVAILABLE = "unavailable"
    FAILED = "failed"
    UNKNOWN = "unknown"
    COMPLETED = "completed"


@dataclass(frozen=True, slots=True)
class AuditEventId:
    value: UUID

    def __post_init__(self) -> None:
        _require_uuid7(self.value, "AUD-EVENT-ID")

    def __str__(self) -> str:
        return str(self.value)


@dataclass(frozen=True, slots=True)
class AuditReference:
    kind: str
    reference: UUID

    def __post_init__(self) -> None:
        _require_token(self.kind, "AUD-REFERENCE")
        _require_uuid7(self.reference, "AUD-REFERENCE")


@dataclass(frozen=True, slots=True)
class AuditDraft:
    audit_event_id: AuditEventId
    actor: AuditReference
    purpose: Purpose
    operation: str
    target: AuditReference
    result_status: AuditResultStatus
    trace_id: TraceId
    sensitivity: AuditSensitivity
    subject_id: SubjectId | None = None
    request: AuditReference | None = None
    before_version: int | None = None
    after_version: int | None = None
    policy: AuditReference | None = None
    grant: AuditReference | None = None
    error_category: ErrorCategory | None = None

    def __post_init__(self) -> None:
        if type(self.audit_event_id) is not AuditEventId:
            raise AuditViolation("AUD-DECLARATION")
        if type(self.actor) is not AuditReference:
            raise AuditViolation("AUD-DECLARATION")
        if type(self.purpose) is not Purpose:
            raise AuditViolation("AUD-DECLARATION")
        _require_token(self.operation, "AUD-DECLARATION")
        if type(self.target) is not AuditReference:
            raise AuditViolation("AUD-DECLARATION")
        if type(self.result_status) is not AuditResultStatus:
            raise AuditViolation("AUD-DECLARATION")
        if type(self.trace_id) is not TraceId:
            raise AuditViolation("AUD-DECLARATION")
        if type(self.sensitivity) is not AuditSensitivity:
            raise AuditViolation("AUD-DECLARATION")
        if self.subject_id is not None and type(self.subject_id) is not SubjectId:
            raise AuditViolation("AUD-DECLARATION")
        for value in (self.request, self.policy, self.grant):
            if value is not None and type(value) is not AuditReference:
                raise AuditViolation("AUD-DECLARATION")
        _validate_versions(self.before_version, self.after_version)
        if (
            self.error_category is not None
            and type(self.error_category) is not ErrorCategory
        ):
            raise AuditViolation("AUD-DECLARATION")


@dataclass(frozen=True, slots=True)
class AuditRecord:
    draft: AuditDraft
    occurred_at: Instant

    def __post_init__(self) -> None:
        if type(self.draft) is not AuditDraft or type(self.occurred_at) is not Instant:
            raise AuditViolation("AUD-DECLARATION")


@dataclass(frozen=True, slots=True)
class AuditQuery:
    event_id: AuditEventId | None = None
    target: AuditReference | None = None
    subject_id: SubjectId | None = None
    request: AuditReference | None = None
    trace_id: TraceId | None = None
    limit: int = 100

    def __post_init__(self) -> None:
        selectors = (
            self.event_id,
            self.target,
            self.subject_id,
            self.request,
            self.trace_id,
        )
        if sum(value is not None for value in selectors) != 1:
            raise AuditViolation("AUD-QUERY")
        if self.event_id is not None and type(self.event_id) is not AuditEventId:
            raise AuditViolation("AUD-QUERY")
        if self.target is not None and type(self.target) is not AuditReference:
            raise AuditViolation("AUD-QUERY")
        if self.subject_id is not None and type(self.subject_id) is not SubjectId:
            raise AuditViolation("AUD-QUERY")
        if self.request is not None and type(self.request) is not AuditReference:
            raise AuditViolation("AUD-QUERY")
        if self.trace_id is not None and type(self.trace_id) is not TraceId:
            raise AuditViolation("AUD-QUERY")
        if type(self.limit) is not int or not 1 <= self.limit <= 100:
            raise AuditViolation("AUD-QUERY")


@dataclass(frozen=True, slots=True)
class AuditQueryResult:
    records: tuple[AuditRecord, ...]
    truncated: bool

    def __post_init__(self) -> None:
        if type(self.records) is not tuple or any(
            type(record) is not AuditRecord for record in self.records
        ):
            raise AuditViolation("AUD-QUERY")
        if type(self.truncated) is not bool:
            raise AuditViolation("AUD-QUERY")


class AuditViolation(RuntimeError):
    __slots__ = ("code",)

    def __init__(self, code: str) -> None:
        if type(code) is not str or re.fullmatch(r"AUD-[A-Z0-9-]+", code) is None:
            raise ValueError("audit violation code is invalid")
        self.code = code
        super().__init__("audit operation failed")

    def __str__(self) -> str:
        return f"{self.code}: audit operation failed"


@runtime_checkable
class AuditWriter(Protocol):
    async def append(self, draft: AuditDraft) -> None:
        """Append one event using the caller's active transaction."""
        ...


def _require_uuid7(value: object, code: str) -> None:
    if type(value) is not UUID or value.version != 7:
        raise AuditViolation(code)


def _require_token(value: object, code: str) -> None:
    if type(value) is not str or _TOKEN.fullmatch(value) is None:
        raise AuditViolation(code)


def _validate_versions(before: object, after: object) -> None:
    if (before is None) is not (after is None):
        raise AuditViolation("AUD-VERSION")
    if before is None:
        return
    if (
        type(before) is not int
        or type(after) is not int
        or before < 0
        or after <= before
    ):
        raise AuditViolation("AUD-VERSION")


__all__ = (
    "AuditDraft",
    "AuditEventId",
    "AuditQuery",
    "AuditQueryResult",
    "AuditRecord",
    "AuditReference",
    "AuditResultStatus",
    "AuditSensitivity",
    "AuditViolation",
    "AuditWriter",
)
