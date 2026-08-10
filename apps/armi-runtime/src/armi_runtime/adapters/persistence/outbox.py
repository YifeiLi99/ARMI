"""Explicit internal outbox dispatch with no dynamic handler discovery."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Protocol
from uuid import UUID, uuid7

from armi_kernel.application import (
    AuditDraft,
    AuditEventId,
    AuditReference,
    AuditResultStatus,
    AuditSensitivity,
    AuditViolation,
    WorkId,
    WorkViolation,
)
from armi_kernel.contracts import Purpose, TraceId

from armi_runtime.adapters.transaction_errors import DatabaseTransactionError

from .unit_of_work import PostgreSQLUnitOfWorkFactory

_TOKEN = re.compile(r"^[a-z][a-z0-9._-]{0,63}$", re.ASCII)


@dataclass(frozen=True, slots=True)
class OutboxEnvelope:
    outbox_item_id: UUID
    work_id: WorkId
    message_kind: str
    claim_owner: UUID
    claim_token: int
    attempt_count: int
    max_attempts: int
    trace_id: TraceId

    def __post_init__(self) -> None:
        for value in (self.outbox_item_id, self.claim_owner):
            if type(value) is not UUID or value.version != 7:
                raise WorkViolation("OUTBOX-DECLARATION")
        if type(self.work_id) is not WorkId:
            raise WorkViolation("OUTBOX-DECLARATION")
        if (
            type(self.message_kind) is not str
            or _TOKEN.fullmatch(self.message_kind) is None
        ):
            raise WorkViolation("OUTBOX-DECLARATION")
        if type(self.trace_id) is not TraceId:
            raise WorkViolation("OUTBOX-DECLARATION")
        if type(self.claim_token) is not int or self.claim_token <= 0:
            raise WorkViolation("OUTBOX-DECLARATION")
        if (
            type(self.attempt_count) is not int
            or type(self.max_attempts) is not int
            or not 1 <= self.attempt_count <= self.max_attempts
        ):
            raise WorkViolation("OUTBOX-DECLARATION")


class OutboxHandler(Protocol):
    async def __call__(self, envelope: OutboxEnvelope) -> None:
        """Handle one immutable, identity-stable availability notification."""
        ...


class PostgreSQLOutboxGateway:
    __slots__ = ("_factory",)

    def __init__(self, factory: PostgreSQLUnitOfWorkFactory) -> None:
        self._factory = factory

    async def claim(
        self,
        *,
        claim_owner: UUID,
        lease_seconds: int,
        limit: int,
    ) -> tuple[OutboxEnvelope, ...]:
        try:
            async with self._factory.unit_of_work() as unit_of_work:
                connection = unit_of_work._connection_for_repository()  # pyright: ignore[reportPrivateUsage]
                effective_claim_owner = (
                    unit_of_work.runtime_fence.runtime_instance_id.value
                    if unit_of_work.runtime_fence is not None
                    else claim_owner
                )
                candidates = await (
                    await connection.execute(
                        """
                        SELECT outbox_item_id
                        FROM armi.outbox_items
                        WHERE status IN ('ready', 'claimed')
                          AND available_at <= statement_timestamp()
                          AND attempt_count < max_attempts
                          AND (
                              status = 'ready'
                              OR claim_expires_at < statement_timestamp()
                          )
                        ORDER BY available_at, outbox_item_id
                        FOR UPDATE SKIP LOCKED
                        LIMIT %s
                        """,
                        (limit,),
                    )
                ).fetchall()
                envelopes: list[OutboxEnvelope] = []
                for (item_id,) in candidates:
                    row = await (
                        await connection.execute(
                            """
                            UPDATE armi.outbox_items
                            SET status = 'claimed',
                                claimed_by = %s,
                                claim_expires_at = statement_timestamp()
                                    + (%s * interval '1 second'),
                                claim_token = claim_token + 1,
                                attempt_count = attempt_count + 1,
                                last_error_code = NULL,
                                updated_at = clock_timestamp()
                            WHERE outbox_item_id = %s
                            RETURNING
                                outbox_item_id,
                                work_id,
                                message_kind,
                                claimed_by,
                                claim_token,
                                attempt_count,
                                max_attempts,
                                trace_id
                            """,
                            (effective_claim_owner, lease_seconds, item_id),
                        )
                    ).fetchone()
                    assert row is not None
                    envelopes.append(_row_to_envelope(row))
                return tuple(envelopes)
        except WorkViolation:
            raise
        except AuditViolation:
            raise WorkViolation("OUTBOX-AUDIT") from None
        except DatabaseTransactionError as error:
            raise _translate_database_error(error) from None

    async def delivered(self, envelope: OutboxEnvelope) -> None:
        await self._settle(envelope, delivered=True, error_code=None)

    async def retry_or_dead(
        self,
        envelope: OutboxEnvelope,
        *,
        error_code: str,
        delay_seconds: int,
    ) -> None:
        await self._settle(
            envelope,
            delivered=False,
            error_code=error_code,
            delay_seconds=delay_seconds,
        )

    async def _settle(
        self,
        envelope: OutboxEnvelope,
        *,
        delivered: bool,
        error_code: str | None,
        delay_seconds: int = 1,
    ) -> None:
        try:
            async with self._factory.unit_of_work() as unit_of_work:
                connection = unit_of_work._connection_for_repository()  # pyright: ignore[reportPrivateUsage]
                if delivered:
                    status = "delivered"
                    row = await (
                        await connection.execute(
                            """
                            UPDATE armi.outbox_items
                            SET status = 'delivered',
                                claimed_by = NULL,
                                claim_expires_at = NULL,
                                delivered_at = clock_timestamp(),
                                last_error_code = NULL,
                                updated_at = clock_timestamp()
                            WHERE outbox_item_id = %s
                              AND status = 'claimed'
                              AND claimed_by = %s
                              AND claim_token = %s
                              AND claim_expires_at >= statement_timestamp()
                            RETURNING outbox_item_id
                            """,
                            (
                                envelope.outbox_item_id,
                                envelope.claim_owner,
                                envelope.claim_token,
                            ),
                        )
                    ).fetchone()
                else:
                    terminal = (
                        error_code == "OUTBOX-HANDLER-UNAVAILABLE"
                        or envelope.attempt_count >= envelope.max_attempts
                    )
                    status = "dead" if terminal else "ready"
                    row = await (
                        await connection.execute(
                            """
                            UPDATE armi.outbox_items
                            SET status = %s,
                                available_at = CASE
                                    WHEN %s = 'ready'
                                    THEN statement_timestamp()
                                        + (%s * interval '1 second')
                                    ELSE available_at
                                END,
                                claimed_by = NULL,
                                claim_expires_at = NULL,
                                last_error_code = %s,
                                updated_at = clock_timestamp()
                            WHERE outbox_item_id = %s
                              AND status = 'claimed'
                              AND claimed_by = %s
                              AND claim_token = %s
                              AND claim_expires_at >= statement_timestamp()
                            RETURNING outbox_item_id
                            """,
                            (
                                status,
                                status,
                                delay_seconds,
                                error_code,
                                envelope.outbox_item_id,
                                envelope.claim_owner,
                                envelope.claim_token,
                            ),
                        )
                    ).fetchone()
                if row is None:
                    raise WorkViolation("OUTBOX-CLAIM-STALE")
                if status in {"delivered", "dead"}:
                    await unit_of_work.audit.append(
                        _outbox_audit(
                            self._factory.environment_id,
                            envelope,
                            status,
                        )
                    )
        except WorkViolation:
            raise
        except AuditViolation:
            raise WorkViolation("OUTBOX-AUDIT") from None
        except DatabaseTransactionError as error:
            raise _translate_database_error(error) from None


class OutboxDispatcher:
    """One explicit dispatcher round; never registered with Runtime startup."""

    __slots__ = ("_gateway", "_handlers")

    def __init__(
        self,
        gateway: PostgreSQLOutboxGateway,
        handlers: Mapping[str, OutboxHandler],
    ) -> None:
        self._gateway = gateway
        self._handlers = dict(handlers)

    async def dispatch_once(
        self,
        *,
        claim_owner: UUID,
        lease_seconds: int,
        limit: int,
    ) -> int:
        envelopes = await self._gateway.claim(
            claim_owner=claim_owner,
            lease_seconds=lease_seconds,
            limit=limit,
        )
        for envelope in envelopes:
            handler = self._handlers.get(envelope.message_kind)
            if handler is None:
                await self._gateway.retry_or_dead(
                    envelope,
                    error_code="OUTBOX-HANDLER-UNAVAILABLE",
                    delay_seconds=1,
                )
                continue
            try:
                await handler(envelope)
            except Exception:
                await self._gateway.retry_or_dead(
                    envelope,
                    error_code="OUTBOX-HANDLER-FAILED",
                    delay_seconds=1,
                )
            else:
                await self._gateway.delivered(envelope)
        return len(envelopes)


def _row_to_envelope(row: tuple[Any, ...]) -> OutboxEnvelope:
    try:
        return OutboxEnvelope(
            outbox_item_id=row[0],
            work_id=WorkId(row[1]),
            message_kind=str(row[2]),
            claim_owner=row[3],
            claim_token=int(row[4]),
            attempt_count=int(row[5]),
            max_attempts=int(row[6]),
            trace_id=TraceId(str(row[7])),
        )
    except TypeError, ValueError:
        raise WorkViolation("OUTBOX-DATABASE") from None


def _outbox_audit(
    actor_ref: UUID,
    envelope: OutboxEnvelope,
    operation: str,
) -> AuditDraft:
    return AuditDraft(
        audit_event_id=AuditEventId(uuid7()),
        actor=AuditReference("runtime", actor_ref),
        purpose=Purpose("work.custody"),
        operation=f"outbox.{operation}",
        target=AuditReference("outbox_item", envelope.outbox_item_id),
        result_status=(
            AuditResultStatus.COMPLETED
            if operation == "delivered"
            else AuditResultStatus.UNAVAILABLE
        ),
        trace_id=envelope.trace_id,
        sensitivity=AuditSensitivity.INTERNAL,
        request=AuditReference("durable_work", envelope.work_id.value),
    )


def _translate_database_error(error: DatabaseTransactionError) -> WorkViolation:
    if error.code == "DB-TX-COMMIT-UNKNOWN":
        return WorkViolation("OUTBOX-COMMIT-UNKNOWN")
    return WorkViolation("OUTBOX-DATABASE")


__all__ = (
    "OutboxDispatcher",
    "OutboxEnvelope",
    "OutboxHandler",
    "PostgreSQLOutboxGateway",
)
