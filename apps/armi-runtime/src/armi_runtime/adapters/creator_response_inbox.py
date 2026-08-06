"""PostgreSQL Creator inbox adapter with an idempotent receiver boundary."""

from __future__ import annotations

from typing import Any, cast
from uuid import uuid7

import rfc8785
from armi_kernel.application import (
    ActionAdapterPort,
    AuditDraft,
    AuditEventId,
    AuditReference,
    AuditResultStatus,
    AuditSensitivity,
    CreatorResponseDeliveryId,
    EffectAdapterReceipt,
    EffectViolation,
    FrozenEffectRequest,
    LockPlan,
)
from armi_kernel.contracts import Digest, Instant, Purpose, SubjectId

from armi_runtime.adapters.persistence.unit_of_work import (
    PostgreSQLUnitOfWorkFactory,
)


class PostgreSQLCreatorResponseInbox(ActionAdapterPort):
    """Receive one Creator response without access to the effect ledger."""

    __slots__ = ("_factory",)

    def __init__(self, factory: PostgreSQLUnitOfWorkFactory) -> None:
        self._factory = factory

    async def dispatch(
        self, request: FrozenEffectRequest, payload: bytes
    ) -> EffectAdapterReceipt:
        if type(payload) is not bytes or len(payload) != request.payload_bytes:
            raise EffectViolation("EFFECT-RECEIVER-PAYLOAD")
        if Digest.from_bytes(payload) != request.payload_digest:
            raise EffectViolation("EFFECT-RECEIVER-PAYLOAD")
        delivery_id = uuid7()
        receipt_digest = _receipt_digest(request, delivery_id)
        async with self._factory.unit_of_work(LockPlan()) as uow:
            connection = uow._connection_for_repository()  # pyright: ignore[reportPrivateUsage]
            row = await (
                await connection.execute(
                    """
                    INSERT INTO armi.creator_response_deliveries (
                        creator_response_delivery_id, effect_id, interaction_scene_id,
                        creator_party_id, payload_artifact_id, payload_digest,
                        payload_bytes, receipt_digest, schema_version
                    )
                    SELECT %s, effect.effect_id, effect.interaction_scene_id,
                           effect.creator_party_id, effect.payload_artifact_id,
                           effect.payload_digest, effect.payload_bytes, %s, 1
                    FROM armi.effects AS effect
                    WHERE effect.effect_id = %s
                      AND effect.subject_id = %s
                      AND effect.interaction_scene_id = %s
                      AND effect.creator_party_id = %s
                      AND effect.payload_digest = %s
                      AND effect.payload_bytes = %s
                    ON CONFLICT (effect_id) DO NOTHING
                    RETURNING creator_response_delivery_id, receipt_digest, received_at
                    """,
                    (
                        delivery_id,
                        receipt_digest.value,
                        request.effect_id.value,
                        request.subject_id,
                        request.scene_id,
                        request.creator_party_id,
                        request.payload_digest.value,
                        request.payload_bytes,
                    ),
                )
            ).fetchone()
            if row is None:
                existing = await self._read(connection, request)
                if existing is None:
                    raise EffectViolation("EFFECT-RECEIVER-STATE")
                return EffectAdapterReceipt(
                    CreatorResponseDeliveryId(existing[0]),
                    Digest(str(existing[1])),
                    Instant(existing[2]),
                    duplicate=True,
                )
            timeline_item_id = uuid7()
            await connection.execute(
                """
                INSERT INTO armi.scene_timeline_items (
                    timeline_item_id, scene_id, source_kind, source_ref,
                    source_event_no, result_status, occurred_at, schema_version
                ) VALUES (%s, %s, 'creator_response', %s, 1, 'completed', %s, 1)
                """,
                (
                    timeline_item_id,
                    request.scene_id,
                    request.effect_id.value,
                    row[2],
                ),
            )
            await connection.execute(
                """
                UPDATE armi.interaction_scenes
                SET recent_context_boundary = %s
                WHERE scene_id = %s
                """,
                (timeline_item_id, request.scene_id),
            )
            await uow.audit.append(
                AuditDraft(
                    AuditEventId(uuid7()),
                    AuditReference("runtime", uow.environment_id),
                    Purpose("effect.dispatch"),
                    "creator.response.received",
                    AuditReference("creator_response_delivery", row[0]),
                    AuditResultStatus.COMPLETED,
                    request.trace_id,
                    AuditSensitivity.PRIVATE,
                    subject_id=SubjectId(request.subject_id),
                    request_digest=request.request_digest,
                    response_digest=Digest(str(row[1])),
                )
            )
            return EffectAdapterReceipt(
                CreatorResponseDeliveryId(row[0]),
                Digest(str(row[1])),
                Instant(row[2]),
            )

    async def observe(
        self, request: FrozenEffectRequest
    ) -> EffectAdapterReceipt | None:
        async with self._factory.unit_of_work(LockPlan(), read_only=True) as uow:
            connection = uow._connection_for_repository()  # pyright: ignore[reportPrivateUsage]
            row = await self._read(connection, request)
            if row is None:
                return None
            return EffectAdapterReceipt(
                CreatorResponseDeliveryId(row[0]),
                Digest(str(row[1])),
                Instant(row[2]),
                duplicate=True,
            )

    @staticmethod
    async def _read(connection: Any, request: FrozenEffectRequest) -> Any | None:
        row = await (
            await connection.execute(
                """
                SELECT creator_response_delivery_id, receipt_digest, received_at,
                       payload_digest, payload_bytes, interaction_scene_id,
                       creator_party_id
                FROM armi.creator_response_deliveries
                WHERE effect_id = %s
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
            or row[6] != request.creator_party_id
        ):
            raise EffectViolation("EFFECT-RECEIVER-CONFLICT")
        return row


def _receipt_digest(request: FrozenEffectRequest, delivery_id: object) -> Digest:
    return Digest.from_bytes(
        rfc8785.dumps(
            cast(
                Any,
                {
                    "schema_version": "armi.effect-receipt.v1",
                    "adapter_binding": (
                        "armi.creator-response-adapter.postgresql-inbox-v1"
                    ),
                    "delivery_id": str(delivery_id),
                    "effect_id": str(request.effect_id.value),
                    "payload_digest": request.payload_digest.value,
                    "payload_bytes": request.payload_bytes,
                },
            )
        )
    )


__all__ = ("PostgreSQLCreatorResponseInbox",)
