"""PostgreSQL durable-work custody using explicit short transactions."""

from __future__ import annotations

import re
from collections.abc import Sequence
from typing import TYPE_CHECKING, Any, LiteralString, cast
from uuid import UUID, uuid7

import psycopg
from armi_kernel.application import (
    AuditDraft,
    AuditEventId,
    AuditReference,
    AuditResultStatus,
    AuditSensitivity,
    AuditViolation,
    AuditWriter,
    WorkAttemptId,
    WorkDraft,
    WorkId,
    WorkLease,
    WorkOwner,
    WorkPayloadRef,
    WorkRecord,
    WorkResultRef,
    WorkStatus,
    WorkViolation,
)
from armi_kernel.contracts import (
    Digest,
    IdempotencyKey,
    Instant,
    Purpose,
    SubjectId,
    TraceId,
)

from armi_runtime.adapters.transaction_errors import DatabaseTransactionError

if TYPE_CHECKING:
    from .unit_of_work import PostgreSQLUnitOfWork, PostgreSQLUnitOfWorkFactory

_ERROR_CODE = re.compile(r"^[A-Z][A-Z0-9-]{0,127}$", re.ASCII)
_WORK_COLUMNS = """
    work_id,
    work_kind,
    owner_kind,
    owner_ref,
    subject_id,
    idempotency_key,
    payload_kind,
    payload_ref,
    payload_digest,
    priority,
    not_before,
    deadline_at,
    status,
    max_attempts,
    attempt_count,
    current_attempt_id,
    lease_owner,
    lease_expires_at,
    lease_token,
    result_kind,
    result_ref,
    last_error_code,
    trace_id
"""


class PostgreSQLDurableWorkWriter:
    """Create work and its availability outbox in one caller-owned transaction."""

    __slots__ = ("_actor_ref", "_audit", "_connection")

    def __init__(
        self,
        connection: psycopg.AsyncConnection[tuple[Any, ...]],
        audit: AuditWriter,
        actor_ref: UUID,
    ) -> None:
        self._connection = connection
        self._audit = audit
        self._actor_ref = actor_ref

    async def enqueue(self, draft: WorkDraft) -> WorkRecord:
        try:
            inserted = await (
                await self._connection.execute(
                    """
                    INSERT INTO armi.durable_work (
                        work_id,
                        work_kind,
                        owner_kind,
                        owner_ref,
                        subject_id,
                        idempotency_key,
                        payload_kind,
                        payload_ref,
                        payload_digest,
                        priority,
                        not_before,
                        deadline_at,
                        status,
                        max_attempts,
                        attempt_count,
                        lease_token,
                        trace_id)
                    VALUES (
                        %s, %s, %s, %s, %s, %s, %s, %s, %s,
                        %s, %s, %s, 'ready', %s, 0, 0, %s)
                    ON CONFLICT (
                        owner_kind,
                        owner_ref,
                        work_kind,
                        idempotency_key
                    ) DO NOTHING
                    RETURNING work_id
                    """,
                    _draft_parameters(draft),
                )
            ).fetchone()
            if inserted is None:
                existing = await self._select_by_identity(draft)
                if existing is None or not _same_declaration(existing.draft, draft):
                    raise WorkViolation("WORK-IDEMPOTENCY-CONFLICT")
                return existing
            await self._audit.append(_work_audit(self._actor_ref, draft, "enqueued"))
            return WorkRecord(draft, WorkStatus.READY, 0)
        except WorkViolation:
            raise
        except AuditViolation:
            raise WorkViolation("WORK-AUDIT") from None
        except psycopg.Error:
            raise WorkViolation("WORK-DATABASE") from None

    async def _select_by_identity(self, draft: WorkDraft) -> WorkRecord | None:
        row = await (
            await self._connection.execute(
                f"""
                SELECT {_WORK_COLUMNS}
                FROM armi.durable_work
                WHERE owner_kind = %s
                  AND owner_ref = %s
                  AND work_kind = %s
                  AND idempotency_key = %s
                """,
                (
                    draft.owner.kind,
                    draft.owner.reference,
                    draft.work_kind,
                    draft.idempotency_key.value,
                ),
            )
        ).fetchone()
        return _row_to_record(row) if row is not None else None

    async def release(
        self,
        lease: WorkLease,
        *,
        not_before: Instant,
        error_code: str | None = None,
    ) -> WorkRecord:
        return await self._settle(
            lease,
            """
            UPDATE armi.durable_work
            SET status = 'ready',
                not_before = GREATEST(%s, statement_timestamp()),
                current_attempt_id = NULL,
                lease_owner = NULL,
                lease_expires_at = NULL,
                last_error_code = %s,
                updated_at = clock_timestamp()
            WHERE work_id = %s
              AND status = 'leased'
              AND current_attempt_id = %s
              AND lease_owner = %s
              AND lease_token = %s
              AND lease_expires_at >= statement_timestamp()
              AND deadline_at > statement_timestamp()
            RETURNING
            """,
            (
                not_before.value,
                error_code,
                lease.work_id.value,
                lease.attempt_id.value,
                lease.owner,
                lease.token,
            ),
            "released",
        )

    async def complete(
        self,
        lease: WorkLease,
        result: WorkResultRef,
    ) -> WorkRecord:
        return await self._settle(
            lease,
            """
            UPDATE armi.durable_work
            SET status = 'completed',
                current_attempt_id = NULL,
                lease_owner = NULL,
                lease_expires_at = NULL,
                result_kind = %s,
                result_ref = %s,
                last_error_code = NULL,
                updated_at = clock_timestamp()
            WHERE work_id = %s
              AND status = 'leased'
              AND current_attempt_id = %s
              AND lease_owner = %s
              AND lease_token = %s
              AND lease_expires_at >= statement_timestamp()
              AND deadline_at > statement_timestamp()
            RETURNING
            """,
            (
                result.kind,
                result.reference,
                lease.work_id.value,
                lease.attempt_id.value,
                lease.owner,
                lease.token,
            ),
            "completed",
        )

    async def fail(self, lease: WorkLease, *, error_code: str) -> WorkRecord:
        return await self._settle(
            lease,
            """
            UPDATE armi.durable_work
            SET status = 'failed',
                current_attempt_id = NULL,
                lease_owner = NULL,
                lease_expires_at = NULL,
                last_error_code = %s,
                updated_at = clock_timestamp()
            WHERE work_id = %s
              AND status = 'leased'
              AND current_attempt_id = %s
              AND lease_owner = %s
              AND lease_token = %s
              AND lease_expires_at >= statement_timestamp()
            RETURNING
            """,
            (
                error_code,
                lease.work_id.value,
                lease.attempt_id.value,
                lease.owner,
                lease.token,
            ),
            "failed",
        )

    async def _settle(
        self,
        lease: WorkLease,
        sql_prefix: str,
        parameters: tuple[object, ...],
        operation: str,
    ) -> WorkRecord:
        try:
            row = await (
                await self._connection.execute(
                    cast(LiteralString, f"{sql_prefix} {_WORK_COLUMNS}"),
                    parameters,
                )
            ).fetchone()
            if row is None:
                raise WorkViolation("WORK-LEASE-STALE")
            record = _row_to_record(row)
            await self._audit.append(_record_audit(self._actor_ref, record, operation))
            return record
        except WorkViolation:
            raise
        except AuditViolation:
            raise WorkViolation("WORK-AUDIT") from None
        except psycopg.Error:
            raise WorkViolation("WORK-DATABASE") from None


class PostgreSQLDurableWorkGateway:
    """Claim and settle work through explicit short Unit of Work scopes."""

    __slots__ = ("_factory",)

    def __init__(self, factory: PostgreSQLUnitOfWorkFactory) -> None:
        self._factory = factory

    async def failed_owner_refs(self, *, work_kind: str) -> tuple[UUID, ...]:
        try:
            async with self._factory.unit_of_work(read_only=True) as unit_of_work:
                rows = await (
                    await unit_of_work.transaction.execute(
                        """SELECT owner_ref FROM armi.durable_work
                           WHERE work_kind=%s AND status='failed'
                           ORDER BY owner_ref""",
                        (work_kind,),
                    )
                ).fetchall()
                return tuple(row[0] for row in rows)
        except psycopg.Error:
            raise WorkViolation("WORK-DATABASE") from None

    async def claim(
        self,
        *,
        work_kind: str,
        lease_owner: UUID,
        lease_seconds: int,
        limit: int = 1,
    ) -> tuple[WorkRecord, ...]:
        try:
            async with self._factory.unit_of_work() as unit_of_work:
                connection = unit_of_work._connection_for_repository()  # pyright: ignore[reportPrivateUsage]
                effective_lease_owner = (
                    unit_of_work.runtime_fence.runtime_instance_id.value
                    if unit_of_work.runtime_fence is not None
                    else lease_owner
                )
                await _expire_unclaimable(connection, unit_of_work)
                candidates = await (
                    await connection.execute(
                        """
                        SELECT work_id
                        FROM armi.durable_work
                        WHERE status IN ('ready', 'leased')
                          AND work_kind = %s
                          AND not_before <= statement_timestamp()
                          AND deadline_at > statement_timestamp()
                          AND attempt_count < max_attempts
                          AND (
                              status = 'ready'
                              OR lease_expires_at < statement_timestamp()
                          )
                        ORDER BY priority DESC, not_before, work_id
                        FOR UPDATE SKIP LOCKED
                        LIMIT %s
                        """,
                        (work_kind, limit),
                    )
                ).fetchall()
                records: list[WorkRecord] = []
                for candidate in candidates:
                    attempt_id = uuid7()
                    row = await (
                        await connection.execute(
                            f"""
                            UPDATE armi.durable_work
                            SET status = 'leased',
                                attempt_count = attempt_count + 1,
                                current_attempt_id = %s,
                                lease_owner = %s,
                                lease_expires_at = LEAST(
                                    statement_timestamp()
                                        + (%s * interval '1 second'),
                                    deadline_at
                                ),
                                lease_token = lease_token + 1,
                                last_error_code = NULL,
                                updated_at = clock_timestamp()
                            WHERE work_id = %s
                            RETURNING {_WORK_COLUMNS}
                            """,
                            (
                                attempt_id,
                                effective_lease_owner,
                                lease_seconds,
                                candidate[0],
                            ),
                        )
                    ).fetchone()
                    record = _row_to_record(cast(tuple[Any, ...], row))
                    await unit_of_work.audit.append(
                        _record_audit(
                            self._factory.environment_id,
                            record,
                            "claimed",
                        )
                    )
                    records.append(record)
                return tuple(records)
        except WorkViolation:
            raise
        except AuditViolation:
            raise WorkViolation("WORK-AUDIT") from None
        except DatabaseTransactionError as error:
            raise _translate_transaction_error(error) from None

    async def renew(self, lease: WorkLease, *, lease_seconds: int) -> WorkLease:
        record = await self._transition(
            lease,
            """
            UPDATE armi.durable_work
            SET lease_expires_at = LEAST(
                    statement_timestamp() + (%s * interval '1 second'),
                    deadline_at
                ),
                updated_at = clock_timestamp()
            WHERE work_id = %s
              AND status = 'leased'
              AND current_attempt_id = %s
              AND lease_owner = %s
              AND lease_token = %s
              AND lease_expires_at >= statement_timestamp()
              AND deadline_at > statement_timestamp()
            RETURNING
            """,
            (
                lease_seconds,
                lease.work_id.value,
                lease.attempt_id.value,
                lease.owner,
                lease.token,
            ),
            operation=None,
        )
        return cast(WorkLease, record.lease)

    async def release(
        self,
        lease: WorkLease,
        *,
        not_before: Instant,
        error_code: str | None = None,
    ) -> WorkRecord:
        return await self._transition(
            lease,
            """
            UPDATE armi.durable_work
            SET status = 'ready',
                not_before = GREATEST(%s, statement_timestamp()),
                current_attempt_id = NULL,
                lease_owner = NULL,
                lease_expires_at = NULL,
                last_error_code = %s,
                updated_at = clock_timestamp()
            WHERE work_id = %s
              AND status = 'leased'
              AND current_attempt_id = %s
              AND lease_owner = %s
              AND lease_token = %s
              AND lease_expires_at >= statement_timestamp()
              AND deadline_at > statement_timestamp()
            RETURNING
            """,
            (
                not_before.value,
                error_code,
                lease.work_id.value,
                lease.attempt_id.value,
                lease.owner,
                lease.token,
            ),
            operation="released",
        )

    async def complete(
        self,
        lease: WorkLease,
        result: WorkResultRef,
    ) -> WorkRecord:
        return await self._transition(
            lease,
            """
            UPDATE armi.durable_work
            SET status = 'completed',
                current_attempt_id = NULL,
                lease_owner = NULL,
                lease_expires_at = NULL,
                result_kind = %s,
                result_ref = %s,
                last_error_code = NULL,
                updated_at = clock_timestamp()
            WHERE work_id = %s
              AND status = 'leased'
              AND current_attempt_id = %s
              AND lease_owner = %s
              AND lease_token = %s
              AND lease_expires_at >= statement_timestamp()
              AND deadline_at > statement_timestamp()
            RETURNING
            """,
            (
                result.kind,
                result.reference,
                lease.work_id.value,
                lease.attempt_id.value,
                lease.owner,
                lease.token,
            ),
            operation="completed",
        )

    async def fail(self, lease: WorkLease, *, error_code: str) -> WorkRecord:
        return await self._transition(
            lease,
            """
            UPDATE armi.durable_work
            SET status = 'failed',
                current_attempt_id = NULL,
                lease_owner = NULL,
                lease_expires_at = NULL,
                last_error_code = %s,
                updated_at = clock_timestamp()
            WHERE work_id = %s
              AND status = 'leased'
              AND current_attempt_id = %s
              AND lease_owner = %s
              AND lease_token = %s
              AND lease_expires_at >= statement_timestamp()
            RETURNING
            """,
            (
                error_code,
                lease.work_id.value,
                lease.attempt_id.value,
                lease.owner,
                lease.token,
            ),
            operation="failed",
        )

    async def cancel_ready(self, work_id: WorkId) -> WorkRecord:
        try:
            async with self._factory.unit_of_work() as unit_of_work:
                connection = unit_of_work._connection_for_repository()  # pyright: ignore[reportPrivateUsage]
                row = await (
                    await connection.execute(
                        f"""
                        UPDATE armi.durable_work
                        SET status = 'cancelled',
                            updated_at = clock_timestamp()
                        WHERE work_id = %s
                          AND status = 'ready'
                        RETURNING {_WORK_COLUMNS}
                        """,
                        (work_id.value,),
                    )
                ).fetchone()
                if row is None:
                    raise WorkViolation("WORK-STATE")
                record = _row_to_record(row)
                await unit_of_work.audit.append(
                    _record_audit(
                        self._factory.environment_id,
                        record,
                        "cancelled",
                    )
                )
                return record
        except WorkViolation:
            raise
        except AuditViolation:
            raise WorkViolation("WORK-AUDIT") from None
        except DatabaseTransactionError as error:
            raise _translate_transaction_error(error) from None

    async def _transition(
        self,
        lease: WorkLease,
        sql_prefix: str,
        parameters: tuple[object, ...],
        *,
        operation: str | None,
    ) -> WorkRecord:
        try:
            async with self._factory.unit_of_work() as unit_of_work:
                connection = unit_of_work._connection_for_repository()  # pyright: ignore[reportPrivateUsage]
                row = await (
                    await connection.execute(
                        cast(LiteralString, f"{sql_prefix} {_WORK_COLUMNS}"),
                        parameters,
                    )
                ).fetchone()
                if row is None:
                    raise WorkViolation("WORK-LEASE-STALE")
                record = _row_to_record(row)
                if operation is not None:
                    await unit_of_work.audit.append(
                        _record_audit(
                            self._factory.environment_id,
                            record,
                            operation,
                            attempt_id=lease.attempt_id,
                        )
                    )
                return record
        except WorkViolation:
            raise
        except AuditViolation:
            raise WorkViolation("WORK-AUDIT") from None
        except DatabaseTransactionError as error:
            raise _translate_transaction_error(error) from None


async def _expire_unclaimable(
    connection: psycopg.AsyncConnection[tuple[Any, ...]],
    unit_of_work: PostgreSQLUnitOfWork,
) -> None:
    rows = await (
        await connection.execute(
            f"""
            UPDATE armi.durable_work
            SET status = 'failed',
                current_attempt_id = NULL,
                lease_owner = NULL,
                lease_expires_at = NULL,
                last_error_code = CASE
                    WHEN deadline_at <= statement_timestamp()
                        THEN 'WORK-DEADLINE'
                    ELSE 'WORK-ATTEMPTS-EXHAUSTED'
                END,
                updated_at = clock_timestamp()
            WHERE status IN ('ready', 'leased')
              AND (
                  deadline_at <= statement_timestamp()
                  OR (
                      attempt_count >= max_attempts
                      AND (
                          status = 'ready'
                          OR lease_expires_at < statement_timestamp()
                      )
                  )
              )
            RETURNING {_WORK_COLUMNS}
            """
        )
    ).fetchall()
    for row in rows:
        record = _row_to_record(row)
        await unit_of_work.audit.append(
            _record_audit(
                unit_of_work.environment_id,
                record,
                "failed",
            )
        )


def _draft_parameters(draft: WorkDraft) -> tuple[object, ...]:
    return (
        draft.work_id.value,
        draft.work_kind,
        draft.owner.kind,
        draft.owner.reference,
        draft.subject_id.value if draft.subject_id is not None else None,
        draft.idempotency_key.value,
        draft.payload.kind if draft.payload is not None else None,
        draft.payload.reference if draft.payload is not None else None,
        draft.payload_digest.value,
        draft.priority,
        draft.not_before.value,
        draft.deadline_at.value,
        draft.max_attempts,
        draft.trace_id.value,
    )


def _same_declaration(existing: WorkDraft, requested: WorkDraft) -> bool:
    return (
        existing.work_kind,
        existing.owner,
        existing.idempotency_key,
        existing.payload,
        existing.payload_digest,
        existing.priority,
        existing.not_before,
        existing.deadline_at,
        existing.max_attempts,
        existing.trace_id,
        existing.subject_id,
    ) == (
        requested.work_kind,
        requested.owner,
        requested.idempotency_key,
        requested.payload,
        requested.payload_digest,
        requested.priority,
        requested.not_before,
        requested.deadline_at,
        requested.max_attempts,
        requested.trace_id,
        requested.subject_id,
    )


def _row_to_record(row: Sequence[Any]) -> WorkRecord:
    try:
        draft = WorkDraft(
            work_id=WorkId(row[0]),
            work_kind=str(row[1]),
            owner=WorkOwner(str(row[2]), row[3]),
            subject_id=SubjectId(row[4]) if row[4] is not None else None,
            idempotency_key=IdempotencyKey(str(row[5])),
            payload=(
                WorkPayloadRef(str(row[6]), row[7]) if row[6] is not None else None
            ),
            payload_digest=Digest(str(row[8])),
            priority=int(row[9]),
            not_before=Instant(row[10]),
            deadline_at=Instant(row[11]),
            max_attempts=int(row[13]),
            trace_id=TraceId(str(row[22])),
        )
        lease = (
            WorkLease(
                WorkId(row[0]),
                WorkAttemptId(row[15]),
                row[16],
                Instant(row[17]),
                int(row[18]),
            )
            if row[12] == WorkStatus.LEASED.value
            else None
        )
        result = WorkResultRef(str(row[19]), row[20]) if row[19] is not None else None
        return WorkRecord(
            draft,
            WorkStatus(str(row[12])),
            int(row[14]),
            lease,
            result,
            str(row[21]) if row[21] is not None else None,
        )
    except TypeError, ValueError:
        raise WorkViolation("WORK-DATABASE") from None


def _work_audit(actor_ref: UUID, draft: WorkDraft, operation: str) -> AuditDraft:
    return AuditDraft(
        audit_event_id=AuditEventId(uuid7()),
        actor=AuditReference("runtime", actor_ref),
        purpose=Purpose("work.custody"),
        operation=f"work.{operation}",
        target=AuditReference("durable_work", draft.work_id.value),
        result_status=AuditResultStatus.ACCEPTED,
        trace_id=draft.trace_id,
        sensitivity=AuditSensitivity.INTERNAL,
        subject_id=draft.subject_id,
    )


def _record_audit(
    actor_ref: UUID,
    record: WorkRecord,
    operation: str,
    *,
    attempt_id: WorkAttemptId | None = None,
) -> AuditDraft:
    status = {
        "claimed": AuditResultStatus.ACCEPTED,
        "released": AuditResultStatus.WAITING,
        "completed": AuditResultStatus.COMPLETED,
        "failed": AuditResultStatus.FAILED,
        "cancelled": AuditResultStatus.REJECTED,
    }[operation]
    request = (
        AuditReference("work_attempt", attempt_id.value)
        if attempt_id is not None
        else None
    )
    return AuditDraft(
        audit_event_id=AuditEventId(uuid7()),
        actor=AuditReference("runtime", actor_ref),
        purpose=Purpose("work.custody"),
        operation=f"work.{operation}",
        target=AuditReference("durable_work", record.draft.work_id.value),
        result_status=status,
        trace_id=record.draft.trace_id,
        sensitivity=AuditSensitivity.INTERNAL,
        subject_id=record.draft.subject_id,
        request=request,
    )


def _translate_transaction_error(error: DatabaseTransactionError) -> WorkViolation:
    if error.code == "DB-TX-COMMIT-UNKNOWN":
        return WorkViolation("WORK-COMMIT-UNKNOWN")
    return WorkViolation("WORK-DATABASE")


__all__ = (
    "PostgreSQLDurableWorkGateway",
    "PostgreSQLDurableWorkWriter",
)
