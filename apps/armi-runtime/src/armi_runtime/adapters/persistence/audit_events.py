"""Append-only PostgreSQL normal audit storage and exact query boundary."""

from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING, Any, LiteralString, cast

import psycopg
from armi_kernel.application import (
    AuditDraft,
    AuditEventId,
    AuditQuery,
    AuditQueryResult,
    AuditRecord,
    AuditReference,
    AuditResultStatus,
    AuditSensitivity,
    AuditViolation,
)
from armi_kernel.contracts import (
    ErrorCategory,
    Instant,
    Purpose,
    SubjectId,
    TraceId,
)

if TYPE_CHECKING:
    from .unit_of_work import PostgreSQLUnitOfWork

_COLUMNS = """
    audit_event_id,
    actor_kind,
    actor_ref,
    purpose,
    operation,
    target_kind,
    target_ref,
    result_status,
    trace_id,
    sensitivity,
    subject_id,
    request_kind,
    request_ref,
    before_version,
    after_version,
    policy_ref,
    grant_ref,
    error_category,
    occurred_at
"""


class PostgreSQLAuditWriter:
    """Write through one already active PostgreSQL transaction."""

    __slots__ = ("_connection",)

    def __init__(
        self,
        connection: psycopg.AsyncConnection[tuple[Any, ...]],
    ) -> None:
        self._connection = connection

    async def append(self, draft: AuditDraft) -> None:
        if type(draft) is not AuditDraft:
            raise AuditViolation("AUD-DECLARATION")
        try:
            await self._connection.execute(
                """
                INSERT INTO armi.audit_events (
                    audit_event_id,
                    actor_kind,
                    actor_ref,
                    purpose,
                    operation,
                    target_kind,
                    target_ref,
                    result_status,
                    trace_id,
                    sensitivity,
                    subject_id,
                    request_kind,
                    request_ref,
                    before_version,
                    after_version,
                    policy_ref,
                    grant_ref,
                    error_category)
                VALUES (
                    %s, %s, %s, %s, %s, %s, %s, %s,
                    %s, %s, %s, %s, %s, %s, %s, %s,
                    %s, %s)
                """,
                _draft_parameters(draft),
            )
        except psycopg.Error:
            raise AuditViolation("AUD-WRITE") from None


class AuditEventRepository:
    """Execute bounded exact reads using the caller's read-only UoW."""

    __slots__ = ()

    async def query(
        self,
        unit_of_work: PostgreSQLUnitOfWork,
        query: AuditQuery,
    ) -> AuditQueryResult:
        if type(query) is not AuditQuery:
            raise AuditViolation("AUD-QUERY")
        connection = unit_of_work._connection_for_repository()  # pyright: ignore[reportPrivateUsage]
        condition, parameters = _query_condition(query)
        try:
            statement = f"""
                SELECT {_COLUMNS}
                FROM armi.audit_events
                WHERE {condition}
                ORDER BY occurred_at, audit_event_id
                LIMIT %s
                """
            cursor = await connection.execute(
                cast(LiteralString, statement),
                (*parameters, query.limit + 1),
            )
            rows = await cursor.fetchall()
        except psycopg.Error:
            raise AuditViolation("AUD-READ") from None
        truncated = len(rows) > query.limit
        return AuditQueryResult(
            tuple(_row_to_record(row) for row in rows[: query.limit]),
            truncated,
        )


def _draft_parameters(draft: AuditDraft) -> tuple[object, ...]:
    return (
        draft.audit_event_id.value,
        draft.actor.kind,
        draft.actor.reference,
        draft.purpose.value,
        draft.operation,
        draft.target.kind,
        draft.target.reference,
        draft.result_status.value,
        draft.trace_id.value,
        draft.sensitivity.value,
        draft.subject_id.value if draft.subject_id is not None else None,
        draft.request.kind if draft.request is not None else None,
        draft.request.reference if draft.request is not None else None,
        draft.before_version,
        draft.after_version,
        draft.policy.reference if draft.policy is not None else None,
        draft.grant.reference if draft.grant is not None else None,
        draft.error_category.value if draft.error_category is not None else None,
    )


def _query_condition(query: AuditQuery) -> tuple[str, tuple[object, ...]]:
    if query.event_id is not None:
        return "audit_event_id = %s", (query.event_id.value,)
    if query.target is not None:
        return (
            "target_kind = %s AND target_ref = %s",
            (query.target.kind, query.target.reference),
        )
    if query.subject_id is not None:
        return "subject_id = %s", (query.subject_id.value,)
    if query.request is not None:
        return (
            "request_kind = %s AND request_ref = %s",
            (query.request.kind, query.request.reference),
        )
    assert query.trace_id is not None
    return "trace_id = %s", (query.trace_id.value,)


def _row_to_record(row: Sequence[Any]) -> AuditRecord:
    try:
        request = AuditReference(str(row[11]), row[12]) if row[11] is not None else None
        draft = AuditDraft(
            audit_event_id=AuditEventId(row[0]),
            actor=AuditReference(str(row[1]), row[2]),
            purpose=Purpose(str(row[3])),
            operation=str(row[4]),
            target=AuditReference(str(row[5]), row[6]),
            result_status=AuditResultStatus(str(row[7])),
            trace_id=TraceId(str(row[8])),
            sensitivity=AuditSensitivity(str(row[9])),
            subject_id=SubjectId(row[10]) if row[10] is not None else None,
            request=request,
            before_version=row[13],
            after_version=row[14],
            policy=(AuditReference("policy", row[15]) if row[15] is not None else None),
            grant=AuditReference("grant", row[16]) if row[16] is not None else None,
            error_category=(
                ErrorCategory(str(row[17])) if row[17] is not None else None
            ),
        )
        return AuditRecord(draft, Instant(row[18]))
    except AuditViolation, TypeError, ValueError:
        raise AuditViolation("AUD-READ") from None

__all__ = (
    "AuditEventRepository",
    "PostgreSQLAuditWriter",
)
