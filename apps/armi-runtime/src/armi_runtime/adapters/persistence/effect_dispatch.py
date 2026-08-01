"""Authoritative T-06 effect attempt, observation, and settlement persistence."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, cast
from uuid import UUID, uuid7

import rfc8785
from armi_kernel.application import (
    AuditDraft,
    AuditEventId,
    AuditReference,
    AuditResultStatus,
    AuditSensitivity,
    EffectAdapterReceipt,
    EffectAttemptId,
    EffectId,
    EffectViolation,
    FrozenEffectRequest,
)
from armi_kernel.contracts import Digest, Purpose, SubjectId, TraceId

from .unit_of_work import PostgreSQLUnitOfWork

_ADAPTER_BINDING = "armi.creator-response-adapter.postgresql-inbox-v1"


@dataclass(frozen=True, slots=True)
class EffectDispatchSnapshot:
    outbox_id: UUID
    claim_owner: UUID | None
    claim_token: int
    attempt_no: int
    artifact_id: UUID
    scene_key: str
    request: FrozenEffectRequest


class PostgreSQLEffectDispatchRepository:
    """The only effect-ledger writer used by the dispatcher."""

    __slots__ = ()

    async def claim(
        self, uow: PostgreSQLUnitOfWork, *, claim_owner: UUID
    ) -> EffectDispatchSnapshot | None:
        connection = uow._connection_for_repository()  # pyright: ignore[reportPrivateUsage]
        row = await (
            await connection.execute(
                """
                SELECT outbox.effect_outbox_item_id, effect.effect_id,
                       effect.subject_id, effect.interaction_scene_id,
                       effect.creator_party_id, effect.payload_artifact_id,
                       effect.payload_digest, effect.payload_bytes, effect.trace_id,
                       scene.scene_key, outbox.attempt_count, outbox.claim_token
                FROM armi.effect_outbox_items AS outbox
                JOIN armi.effects AS effect ON effect.effect_id = outbox.effect_id
                JOIN armi.interaction_scenes AS scene
                  ON scene.scene_id = effect.interaction_scene_id
                WHERE outbox.status = 'ready'
                  AND outbox.available_at <= statement_timestamp()
                  AND statement_timestamp() < outbox.dispatch_deadline
                  AND outbox.attempt_count < outbox.max_attempts
                  AND effect.status = 'registered'
                ORDER BY outbox.available_at, outbox.effect_outbox_item_id
                FOR UPDATE OF outbox, effect SKIP LOCKED
                LIMIT 1
                """
            )
        ).fetchone()
        if row is None:
            return None
        attempt_id = uuid7()
        attempt_no = int(row[10]) + 1
        claim_token = int(row[11]) + 1
        request_digest = _request_digest(row[1], row[6], int(row[7]))
        updated = await (
            await connection.execute(
                """
                UPDATE armi.effect_outbox_items
                SET status = 'claimed', claim_owner = %s,
                    claim_expires_at = statement_timestamp() + interval '60 seconds',
                    claim_token = %s, attempt_count = %s
                WHERE effect_outbox_item_id = %s AND status = 'ready'
                RETURNING effect_outbox_item_id
                """,
                (claim_owner, claim_token, attempt_no, row[0]),
            )
        ).fetchone()
        if updated is None:
            raise EffectViolation("EFFECT-CLAIM-STALE")
        await connection.execute(
            """
            INSERT INTO armi.effect_attempts (
                effect_attempt_id, effect_id, attempt_no, adapter_binding,
                request_digest, claim_token, dispatch_state, schema_version
            ) VALUES (%s, %s, %s, %s, %s, %s, 'prepared', 1)
            """,
            (
                attempt_id,
                row[1],
                attempt_no,
                _ADAPTER_BINDING,
                request_digest.value,
                claim_token,
            ),
        )
        await connection.execute(
            """
            UPDATE armi.effects
            SET status = 'dispatching', verification_status = 'pending',
                current_attempt_id = %s
            WHERE effect_id = %s AND status = 'registered'
            """,
            (attempt_id, row[1]),
        )
        await connection.execute(
            """
            UPDATE armi.creator_response_operations
            SET current_status = 'effect_dispatching'
            WHERE effect_id = %s AND current_status = 'effect_registered'
            """,
            (row[1],),
        )
        request = FrozenEffectRequest(
            EffectId(row[1]),
            EffectAttemptId(attempt_id),
            row[2],
            row[3],
            row[4],
            Digest(str(row[6])),
            int(row[7]),
            request_digest,
            TraceId(str(row[8])),
        )
        return EffectDispatchSnapshot(
            row[0], claim_owner, claim_token, attempt_no, row[5], str(row[9]), request
        )

    async def expired(self, uow: PostgreSQLUnitOfWork) -> EffectDispatchSnapshot | None:
        connection = uow._connection_for_repository()  # pyright: ignore[reportPrivateUsage]
        row = await (
            await connection.execute(
                """
                SELECT outbox.effect_outbox_item_id, outbox.claim_owner,
                       outbox.claim_token, outbox.attempt_count,
                       effect.payload_artifact_id, scene.scene_key,
                       effect.effect_id, attempt.effect_attempt_id,
                       effect.subject_id, effect.interaction_scene_id,
                       effect.creator_party_id, effect.payload_digest,
                       effect.payload_bytes, attempt.request_digest, effect.trace_id
                FROM armi.effect_outbox_items AS outbox
                JOIN armi.effects AS effect ON effect.effect_id = outbox.effect_id
                JOIN armi.effect_attempts AS attempt
                  ON attempt.effect_attempt_id = effect.current_attempt_id
                JOIN armi.interaction_scenes AS scene
                  ON scene.scene_id = effect.interaction_scene_id
                WHERE outbox.status = 'claimed'
                  AND outbox.claim_expires_at <= statement_timestamp()
                  AND effect.status = 'dispatching'
                  AND attempt.dispatch_state IN ('prepared', 'dispatching')
                ORDER BY outbox.claim_expires_at, outbox.effect_outbox_item_id
                FOR UPDATE OF outbox, effect, attempt SKIP LOCKED
                LIMIT 1
                """
            )
        ).fetchone()
        if row is None:
            return None
        assert row[1] is not None
        return EffectDispatchSnapshot(
            row[0],
            row[1],
            int(row[2]),
            int(row[3]),
            row[4],
            str(row[5]),
            FrozenEffectRequest(
                EffectId(row[6]),
                EffectAttemptId(row[7]),
                row[8],
                row[9],
                row[10],
                Digest(str(row[11])),
                int(row[12]),
                Digest(str(row[13])),
                TraceId(str(row[14])),
            ),
        )

    async def unknown(self, uow: PostgreSQLUnitOfWork) -> EffectDispatchSnapshot | None:
        connection = uow._connection_for_repository()  # pyright: ignore[reportPrivateUsage]
        row = await (
            await connection.execute(
                """
                SELECT outbox.effect_outbox_item_id, attempt.effect_attempt_id,
                       outbox.claim_token, outbox.attempt_count,
                       effect.payload_artifact_id, scene.scene_key,
                       effect.effect_id, effect.subject_id,
                       effect.interaction_scene_id, effect.creator_party_id,
                       effect.payload_digest, effect.payload_bytes,
                       attempt.request_digest, effect.trace_id
                FROM armi.effect_outbox_items AS outbox
                JOIN armi.effects AS effect ON effect.effect_id = outbox.effect_id
                JOIN armi.effect_attempts AS attempt
                  ON attempt.effect_attempt_id = effect.current_attempt_id
                JOIN armi.interaction_scenes AS scene
                  ON scene.scene_id = effect.interaction_scene_id
                WHERE outbox.status = 'unknown'
                  AND effect.status = 'unknown'
                  AND attempt.dispatch_state = 'settled'
                  AND attempt.result_status = 'unknown'
                ORDER BY effect.settled_at, effect.effect_id
                FOR UPDATE OF outbox, effect SKIP LOCKED
                LIMIT 1
                """
            )
        ).fetchone()
        if row is None:
            return None
        return EffectDispatchSnapshot(
            row[0],
            None,
            int(row[2]),
            int(row[3]),
            row[4],
            str(row[5]),
            FrozenEffectRequest(
                EffectId(row[6]),
                EffectAttemptId(row[1]),
                row[7],
                row[8],
                row[9],
                Digest(str(row[10])),
                int(row[11]),
                Digest(str(row[12])),
                TraceId(str(row[13])),
            ),
        )

    async def mark_dispatching(
        self, uow: PostgreSQLUnitOfWork, snapshot: EffectDispatchSnapshot
    ) -> None:
        connection = uow._connection_for_repository()  # pyright: ignore[reportPrivateUsage]
        row = await (
            await connection.execute(
                """
                UPDATE armi.effect_attempts AS attempt
                SET dispatch_state = 'dispatching', dispatched_at = statement_timestamp()
                FROM armi.effect_outbox_items AS outbox
                WHERE attempt.effect_attempt_id = %s
                  AND attempt.dispatch_state = 'prepared'
                  AND outbox.effect_outbox_item_id = %s
                  AND outbox.status = 'claimed' AND outbox.claim_owner = %s
                  AND outbox.claim_token = %s
                  AND outbox.claim_expires_at > statement_timestamp()
                RETURNING attempt.effect_attempt_id
                """,
                (
                    snapshot.request.attempt_id.value,
                    snapshot.outbox_id,
                    snapshot.claim_owner,
                    snapshot.claim_token,
                ),
            )
        ).fetchone()
        if row is None:
            raise EffectViolation("EFFECT-CLAIM-STALE")

    async def renew_claim(
        self, uow: PostgreSQLUnitOfWork, snapshot: EffectDispatchSnapshot
    ) -> None:
        if snapshot.claim_owner is None:
            raise EffectViolation("EFFECT-CLAIM-STALE")
        connection = uow._connection_for_repository()  # pyright: ignore[reportPrivateUsage]
        row = await (
            await connection.execute(
                """
                UPDATE armi.effect_outbox_items AS outbox
                SET claim_expires_at = statement_timestamp() + interval '60 seconds'
                FROM armi.effect_attempts AS attempt
                WHERE outbox.effect_outbox_item_id = %s
                  AND outbox.status = 'claimed'
                  AND outbox.claim_owner = %s
                  AND outbox.claim_token = %s
                  AND outbox.claim_expires_at > statement_timestamp()
                  AND attempt.effect_attempt_id = %s
                  AND attempt.dispatch_state = 'dispatching'
                RETURNING outbox.effect_outbox_item_id
                """,
                (
                    snapshot.outbox_id,
                    snapshot.claim_owner,
                    snapshot.claim_token,
                    snapshot.request.attempt_id.value,
                ),
            )
        ).fetchone()
        if row is None:
            raise EffectViolation("EFFECT-CLAIM-STALE")

    async def settle_receipt(
        self,
        uow: PostgreSQLUnitOfWork,
        snapshot: EffectDispatchSnapshot,
        receipt: EffectAdapterReceipt,
    ) -> None:
        await self._settle(
            uow,
            snapshot,
            observation_kind="receipt",
            reliability="reliable",
            observation_digest=receipt.receipt_digest,
            receiver_ref=receipt.delivery_id.value,
            status="completed",
            verification="verified",
            outbox_status="delivered",
            operation_status="effect_completed",
            attempt_result="succeeded",
            error_code=None,
        )

    async def settle_absent(
        self, uow: PostgreSQLUnitOfWork, snapshot: EffectDispatchSnapshot
    ) -> bool:
        connection = uow._connection_for_repository()  # pyright: ignore[reportPrivateUsage]
        budget = await (
            await connection.execute(
                """
                SELECT attempt_count < max_attempts
                       AND statement_timestamp() < dispatch_deadline
                FROM armi.effect_outbox_items
                WHERE effect_outbox_item_id = %s
                """,
                (snapshot.outbox_id,),
            )
        ).fetchone()
        retry = bool(budget and budget[0])
        digest = _observation_digest(snapshot, "query", "not_delivered")
        if retry:
            await self._record_retry(uow, snapshot, digest)
            return True
        await self._settle(
            uow,
            snapshot,
            observation_kind="rejection",
            reliability="reliable",
            observation_digest=digest,
            receiver_ref=None,
            status="failed",
            verification="verified",
            outbox_status="dead",
            operation_status="effect_failed",
            attempt_result="failed",
            error_code="EFFECT-RECEIVER-NOT-DELIVERED",
        )
        return False

    async def settle_unknown(
        self, uow: PostgreSQLUnitOfWork, snapshot: EffectDispatchSnapshot
    ) -> None:
        await self._settle(
            uow,
            snapshot,
            observation_kind="ambiguous",
            reliability="inconclusive",
            observation_digest=_observation_digest(snapshot, "ambiguous", "unknown"),
            receiver_ref=None,
            status="unknown",
            verification="inconclusive",
            outbox_status="unknown",
            operation_status="effect_unknown",
            attempt_result="unknown",
            error_code="EFFECT-RESULT-UNKNOWN",
        )

    async def resolve_unknown_receipt(
        self,
        uow: PostgreSQLUnitOfWork,
        snapshot: EffectDispatchSnapshot,
        receipt: EffectAdapterReceipt,
    ) -> None:
        await self._resolve_unknown(
            uow,
            snapshot,
            observation_kind="receipt",
            observation_digest=receipt.receipt_digest,
            receiver_ref=receipt.delivery_id.value,
            status="completed",
            verification="verified",
            outbox_status="delivered",
            operation_status="effect_completed",
            error_code=None,
        )

    async def resolve_unknown_absent(
        self, uow: PostgreSQLUnitOfWork, snapshot: EffectDispatchSnapshot
    ) -> None:
        await self._resolve_unknown(
            uow,
            snapshot,
            observation_kind="query",
            observation_digest=_observation_digest(
                snapshot, "query", "confirmed_not_delivered"
            ),
            receiver_ref=None,
            status="failed",
            verification="verified",
            outbox_status="dead",
            operation_status="effect_failed",
            error_code="EFFECT-RECEIVER-NOT-DELIVERED",
        )

    async def settle_integrity_failure(
        self, uow: PostgreSQLUnitOfWork, snapshot: EffectDispatchSnapshot
    ) -> None:
        await self._settle(
            uow,
            snapshot,
            observation_kind="rejection",
            reliability="reliable",
            observation_digest=_observation_digest(
                snapshot, "rejection", "payload_invalid"
            ),
            receiver_ref=None,
            status="failed",
            verification="verified",
            outbox_status="dead",
            operation_status="effect_failed",
            attempt_result="failed",
            error_code="EFFECT-PAYLOAD-INVALID",
        )

    async def _record_retry(
        self,
        uow: PostgreSQLUnitOfWork,
        snapshot: EffectDispatchSnapshot,
        observation_digest: Digest,
    ) -> None:
        connection = uow._connection_for_repository()  # pyright: ignore[reportPrivateUsage]
        observation_id = uuid7()
        await self._insert_observation(
            connection,
            snapshot,
            observation_id,
            "query",
            "reliable",
            observation_digest,
            None,
        )
        await connection.execute(
            """
            UPDATE armi.effect_attempts
            SET dispatch_state='settled', result_status='failed',
                error_code='EFFECT-RECEIVER-NOT-DELIVERED',
                dispatched_at=COALESCE(dispatched_at, statement_timestamp()),
                settled_at=statement_timestamp()
            WHERE effect_attempt_id=%s AND dispatch_state IN ('prepared','dispatching')
            """,
            (snapshot.request.attempt_id.value,),
        )
        await connection.execute(
            """
            UPDATE armi.effects SET status='registered', verification_status='not_started',
                current_attempt_id=NULL, current_observation_id=NULL
            WHERE effect_id=%s AND current_attempt_id=%s
            """,
            (snapshot.request.effect_id.value, snapshot.request.attempt_id.value),
        )
        await connection.execute(
            """
            UPDATE armi.effect_outbox_items SET status='ready', available_at=statement_timestamp(),
                claim_owner=NULL, claim_expires_at=NULL,
                last_error_code='EFFECT-RECEIVER-NOT-DELIVERED'
            WHERE effect_outbox_item_id=%s AND claim_token=%s
            """,
            (snapshot.outbox_id, snapshot.claim_token),
        )
        await connection.execute(
            "UPDATE armi.creator_response_operations SET current_status='effect_registered' WHERE effect_id=%s",
            (snapshot.request.effect_id.value,),
        )

    async def _settle(
        self,
        uow: PostgreSQLUnitOfWork,
        snapshot: EffectDispatchSnapshot,
        *,
        observation_kind: str,
        reliability: str,
        observation_digest: Digest,
        receiver_ref: UUID | None,
        status: str,
        verification: str,
        outbox_status: str,
        operation_status: str,
        attempt_result: str,
        error_code: str | None,
    ) -> None:
        connection = uow._connection_for_repository()  # pyright: ignore[reportPrivateUsage]
        observation_id = uuid7()
        await self._insert_observation(
            connection,
            snapshot,
            observation_id,
            observation_kind,
            reliability,
            observation_digest,
            receiver_ref,
        )
        settlement_digest = _settlement_digest(
            snapshot, status, verification, observation_digest
        )
        attempt = await (
            await connection.execute(
                """
                UPDATE armi.effect_attempts
                SET dispatch_state='settled', result_status=%s, error_code=%s,
                    dispatched_at=COALESCE(dispatched_at, statement_timestamp()),
                    settled_at=statement_timestamp()
                WHERE effect_attempt_id=%s AND dispatch_state IN ('prepared','dispatching')
                RETURNING settled_at
                """,
                (attempt_result, error_code, snapshot.request.attempt_id.value),
            )
        ).fetchone()
        if attempt is None:
            raise EffectViolation("EFFECT-SETTLEMENT-STALE")
        await connection.execute(
            """
            UPDATE armi.effects SET status=%s, verification_status=%s,
                current_observation_id=%s, settlement_digest=%s, settled_at=%s
            WHERE effect_id=%s AND current_attempt_id=%s AND status='dispatching'
            """,
            (
                status,
                verification,
                observation_id,
                settlement_digest.value,
                attempt[0],
                snapshot.request.effect_id.value,
                snapshot.request.attempt_id.value,
            ),
        )
        await connection.execute(
            """
            UPDATE armi.effect_outbox_items SET status=%s,
                claim_owner=NULL, claim_expires_at=NULL,
                delivered_at=CASE WHEN %s='delivered' THEN %s ELSE NULL END,
                last_error_code=%s
            WHERE effect_outbox_item_id=%s AND claim_token=%s
            """,
            (
                outbox_status,
                outbox_status,
                attempt[0],
                error_code,
                snapshot.outbox_id,
                snapshot.claim_token,
            ),
        )
        await connection.execute(
            """
            UPDATE armi.creator_response_operations SET current_status=%s,
                reason_code=%s, completed_at=%s
            WHERE effect_id=%s
            """,
            (
                operation_status,
                error_code,
                attempt[0],
                snapshot.request.effect_id.value,
            ),
        )
        await uow.audit.append(
            AuditDraft(
                AuditEventId(uuid7()),
                AuditReference("runtime", uow.environment_id),
                Purpose("effect.settlement"),
                f"effect.{status}",
                AuditReference("effect", snapshot.request.effect_id.value),
                (
                    AuditResultStatus.COMPLETED
                    if status == "completed"
                    else (
                        AuditResultStatus.UNKNOWN
                        if status == "unknown"
                        else AuditResultStatus.FAILED
                    )
                ),
                snapshot.request.trace_id,
                AuditSensitivity.PRIVATE,
                subject_id=SubjectId(snapshot.request.subject_id),
                request_digest=snapshot.request.request_digest,
                response_digest=settlement_digest,
            )
        )

    async def _resolve_unknown(
        self,
        uow: PostgreSQLUnitOfWork,
        snapshot: EffectDispatchSnapshot,
        *,
        observation_kind: str,
        observation_digest: Digest,
        receiver_ref: UUID | None,
        status: str,
        verification: str,
        outbox_status: str,
        operation_status: str,
        error_code: str | None,
    ) -> None:
        connection = uow._connection_for_repository()  # pyright: ignore[reportPrivateUsage]
        observation_id = uuid7()
        await self._insert_observation(
            connection,
            snapshot,
            observation_id,
            observation_kind,
            "reliable",
            observation_digest,
            receiver_ref,
        )
        settlement_digest = _settlement_digest(
            snapshot, status, verification, observation_digest
        )
        effect = await (
            await connection.execute(
                """
                UPDATE armi.effects
                SET status=%s, verification_status=%s,
                    current_observation_id=%s, settlement_digest=%s,
                    settled_at=statement_timestamp()
                WHERE effect_id=%s AND current_attempt_id=%s
                  AND status='unknown'
                RETURNING settled_at
                """,
                (
                    status,
                    verification,
                    observation_id,
                    settlement_digest.value,
                    snapshot.request.effect_id.value,
                    snapshot.request.attempt_id.value,
                ),
            )
        ).fetchone()
        if effect is None:
            raise EffectViolation("EFFECT-SETTLEMENT-STALE")
        outbox = await (
            await connection.execute(
                """
                UPDATE armi.effect_outbox_items
                SET status=%s,
                    delivered_at=CASE WHEN %s='delivered' THEN %s ELSE NULL END,
                    last_error_code=%s
                WHERE effect_outbox_item_id=%s AND status='unknown'
                RETURNING effect_outbox_item_id
                """,
                (
                    outbox_status,
                    outbox_status,
                    effect[0],
                    error_code,
                    snapshot.outbox_id,
                ),
            )
        ).fetchone()
        operation = await (
            await connection.execute(
                """
                UPDATE armi.creator_response_operations
                SET current_status=%s, reason_code=%s, completed_at=%s
                WHERE effect_id=%s AND current_status='effect_unknown'
                RETURNING creator_response_operation_id
                """,
                (
                    operation_status,
                    error_code,
                    effect[0],
                    snapshot.request.effect_id.value,
                ),
            )
        ).fetchone()
        if outbox is None or operation is None:
            raise EffectViolation("EFFECT-SETTLEMENT-STALE")
        await uow.audit.append(
            AuditDraft(
                AuditEventId(uuid7()),
                AuditReference("runtime", uow.environment_id),
                Purpose("effect.settlement"),
                f"effect.{status}",
                AuditReference("effect", snapshot.request.effect_id.value),
                (
                    AuditResultStatus.COMPLETED
                    if status == "completed"
                    else AuditResultStatus.FAILED
                ),
                snapshot.request.trace_id,
                AuditSensitivity.PRIVATE,
                subject_id=SubjectId(snapshot.request.subject_id),
                request_digest=snapshot.request.request_digest,
                response_digest=settlement_digest,
            )
        )

    @staticmethod
    async def _insert_observation(
        connection: Any,
        snapshot: EffectDispatchSnapshot,
        observation_id: UUID,
        kind: str,
        reliability: str,
        digest: Digest,
        receiver_ref: UUID | None,
    ) -> None:
        await connection.execute(
            """
            INSERT INTO armi.effect_observations (
                effect_observation_id, effect_id, effect_attempt_id,
                observation_kind, reliability, receiver_ref,
                observation_digest, schema_version
            ) VALUES (%s,%s,%s,%s,%s,%s,%s,1)
            """,
            (
                observation_id,
                snapshot.request.effect_id.value,
                snapshot.request.attempt_id.value,
                kind,
                reliability,
                receiver_ref,
                digest.value,
            ),
        )


def _request_digest(effect_id: object, payload_digest: object, size: int) -> Digest:
    return Digest.from_bytes(
        rfc8785.dumps(
            cast(
                Any,
                {
                    "schema_version": "armi.effect-dispatch.v1",
                    "adapter_binding": _ADAPTER_BINDING,
                    "effect_id": str(effect_id),
                    "payload_digest": str(payload_digest),
                    "payload_bytes": size,
                },
            )
        )
    )


def _observation_digest(
    snapshot: EffectDispatchSnapshot, kind: str, result: str
) -> Digest:
    return Digest.from_bytes(
        rfc8785.dumps(
            cast(
                Any,
                {
                    "schema_version": "armi.effect-observation.v1",
                    "effect_id": str(snapshot.request.effect_id.value),
                    "attempt_id": str(snapshot.request.attempt_id.value),
                    "kind": kind,
                    "result": result,
                },
            )
        )
    )


def _settlement_digest(
    snapshot: EffectDispatchSnapshot,
    status: str,
    verification: str,
    observation_digest: Digest,
) -> Digest:
    return Digest.from_bytes(
        rfc8785.dumps(
            cast(
                Any,
                {
                    "schema_version": "armi.effect-settlement.v1",
                    "effect_id": str(snapshot.request.effect_id.value),
                    "attempt_id": str(snapshot.request.attempt_id.value),
                    "status": status,
                    "verification": verification,
                    "observation_digest": observation_digest.value,
                },
            )
        )
    )


__all__ = ("EffectDispatchSnapshot", "PostgreSQLEffectDispatchRepository")
