"""PostgreSQL local inbox adapter with an idempotent receiver boundary."""

from __future__ import annotations

from typing import Any, cast
from uuid import uuid7

import rfc8785
from armi_kernel.application import (
    AuditDraft,
    AuditEventId,
    AuditReference,
    AuditResultStatus,
    AuditSensitivity,
)
from armi_kernel.contracts import Digest, Instant, Purpose, SubjectId
from armi_runtime_foundation import PostgreSQLRuntimeUnitOfWorkFactory

from .api import (
    ActionAdapterPort,
    EffectAdapterReceipt,
    EffectDeliveryId,
    EffectViolation,
    FrozenEffectRequest,
)


class PostgreSQLLocalInbox(ActionAdapterPort):
    """Record a local receipt on its effect before the separate settlement."""

    __slots__ = ("_factory",)

    def __init__(self, factory: PostgreSQLRuntimeUnitOfWorkFactory) -> None:
        self._factory = factory

    def validate(self, request: FrozenEffectRequest) -> None:
        if request.destination_kind not in {"creator_inbox", "other_human_inbox"}:
            raise EffectViolation("EFFECT-ADAPTER-UNAVAILABLE")

    def payload_parts(
        self, request: FrozenEffectRequest, payload: bytes
    ) -> tuple[bytes, ...]:
        return (payload,)

    async def dispatch(
        self, request: FrozenEffectRequest, payload: bytes
    ) -> EffectAdapterReceipt:
        if type(payload) is not bytes or len(payload) != request.payload_bytes:
            raise EffectViolation("EFFECT-RECEIVER-PAYLOAD")
        delivery_id = uuid7()
        receipt_digest = _receipt_digest(request, delivery_id)
        async with self._factory.unit_of_work() as uow:
            connection = uow.transaction
            # Receipt persistence precedes settlement; see DESIGN.md's local inbox contract.
            row = await (
                await connection.execute(
                    """
                    UPDATE armi.effects AS effect
                    SET local_delivery_id = %s,
                        local_receipt_digest = %s,
                        local_delivered_at = statement_timestamp()
                    WHERE effect.effect_id = %s
                      AND effect.subject_id = %s
                      AND effect.scene_id = %s
                      AND effect.destination_party_id = %s
                      AND effect.payload_digest = %s
                      AND effect.payload_bytes = %s
                      AND effect.destination_kind = %s
                      AND effect.local_delivery_id IS NULL
                    RETURNING local_delivery_id, local_receipt_digest, local_delivered_at
                    """,
                    (
                        delivery_id,
                        receipt_digest.value,
                        request.effect_id.value,
                        request.subject_id,
                        request.scene_id,
                        request.destination_party_id,
                        request.payload_digest.value,
                        request.payload_bytes,
                        request.destination_kind,
                    ),
                )
            ).fetchone()
            if row is None:
                existing = await self._read(connection, request)
                if existing is None:
                    raise EffectViolation("EFFECT-RECEIVER-STATE")
                return EffectAdapterReceipt(
                    EffectDeliveryId(existing[0]),
                    Digest(str(existing[1])),
                    Instant(existing[2]),
                    duplicate=True,
                )
            await uow.audit.append(
                AuditDraft(
                    AuditEventId(uuid7()),
                    AuditReference("runtime", uow.environment_id),
                    Purpose("effect.dispatch"),
                    "party.response.received",
                    AuditReference("local_inbox_delivery", row[0]),
                    AuditResultStatus.COMPLETED,
                    request.trace_id,
                    AuditSensitivity.PRIVATE,
                    subject_id=SubjectId(request.subject_id),
                )
            )
            return EffectAdapterReceipt(
                EffectDeliveryId(row[0]),
                Digest(str(row[1])),
                Instant(row[2]),
            )

    async def observe(
        self, request: FrozenEffectRequest
    ) -> EffectAdapterReceipt | None:
        async with self._factory.unit_of_work(read_only=True) as uow:
            connection = uow.transaction
            row = await self._read(connection, request)
            if row is None:
                return None
            return EffectAdapterReceipt(
                EffectDeliveryId(row[0]),
                Digest(str(row[1])),
                Instant(row[2]),
                duplicate=True,
            )

    @staticmethod
    async def _read(connection: Any, request: FrozenEffectRequest) -> Any | None:
        row = await (
            await connection.execute(
                """
                SELECT local_delivery_id, local_receipt_digest, local_delivered_at,
                       payload_digest, payload_bytes, scene_id,
                       destination_party_id, subject_id, destination_kind
                FROM armi.effects
                WHERE effect_id = %s AND local_delivery_id IS NOT NULL
                """,
                (request.effect_id.value,),
            )
        ).fetchone()
        if row is None:
            return None
        if (
            str(row[3]) != request.payload_digest.value
            or int(row[4]) != request.payload_bytes
            or row[5] != request.scene_id
            or row[6] != request.destination_party_id
            or row[7] != request.subject_id
            or row[8] != request.destination_kind
        ):
            raise EffectViolation("EFFECT-RECEIVER-CONFLICT")
        return row


def _receipt_digest(request: FrozenEffectRequest, delivery_id: object) -> Digest:
    return Digest.from_bytes(
        rfc8785.dumps(
            cast(
                Any,
                {
                    "schema_kind": "armi.effect-receipt",
                    "adapter_binding": ("armi.local-inbox-adapter.postgresql"),
                    "delivery_id": str(delivery_id),
                    "effect_id": str(request.effect_id.value),
                    "payload_digest": request.payload_digest.value,
                    "payload_bytes": request.payload_bytes,
                },
            )
        )
    )


__all__ = ("PostgreSQLLocalInbox",)
