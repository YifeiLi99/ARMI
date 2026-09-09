"""Authoritative T-06 effect attempt, observation, and settlement persistence."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Literal, cast
from uuid import UUID, uuid7

import rfc8785
from armi_data_rights.api import DataRightsFence
from armi_interaction.api import InteractionEffectRoutePort, OtherHumanInputViolation
from armi_kernel.application import (
    AuditDraft,
    AuditEventId,
    AuditReference,
    AuditResultStatus,
    AuditSensitivity,
    RuntimeFence,
)
from armi_kernel.contracts import Digest, Instant, Purpose, SubjectId, TraceId
from armi_runtime_foundation import PostgreSQLRuntimeUnitOfWork

from .api import (
    EffectAdapterReceipt,
    EffectAttemptId,
    EffectId,
    EffectViolation,
    FrozenEffectRequest,
)

_LOCAL_ADAPTER_BINDING = "armi.local-inbox-adapter.postgresql-v1"
_EXTERNAL_MESSAGE_ADAPTER_BINDING = "armi.external-message-adapter.v1"


class _AbsentDisposition(StrEnum):
    RETRY = "retry"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class EffectDispatchSnapshot:
    outbox_id: UUID
    claim_owner: UUID | None
    claim_token: int
    attempt_no: int
    artifact_id: UUID
    scene_key: str
    dispatch_deadline: Instant | None
    request: FrozenEffectRequest


class PostgreSQLEffectDispatchRepository:
    """The only effect-ledger writer used by the dispatcher."""

    __slots__ = ("_routes",)

    def __init__(
        self,
        routes: InteractionEffectRoutePort,
    ) -> None:
        self._routes = routes

    async def claim(
        self, uow: PostgreSQLRuntimeUnitOfWork, *, claim_owner: UUID
    ) -> EffectDispatchSnapshot | None:
        connection = uow.transaction
        row = await (
            await connection.execute(
                """
                SELECT outbox.effect_outbox_item_id, effect.effect_id,
                       effect.subject_id, effect.scene_id,
                       effect.destination_party_id, effect.payload_artifact_id,
                       effect.payload_digest, effect.payload_bytes, effect.trace_id,
                       outbox.attempt_count, outbox.claim_token,
                       effect.destination_kind, outbox.dispatch_deadline,
                       effect.live_voice_turn_id
                FROM armi.effect_outbox_items AS outbox
                JOIN armi.effects AS effect ON effect.effect_id = outbox.effect_id
                WHERE outbox.status = 'ready'
                  AND outbox.available_at <= statement_timestamp()
                  AND (outbox.dispatch_deadline IS NULL OR statement_timestamp() < outbox.dispatch_deadline)
                  AND outbox.attempt_count < outbox.max_attempts
                  AND effect.status = 'registered'
                  AND effect.destination_kind IN (
                      'creator_inbox', 'other_human_inbox', 'external_group',
                      'external_private', 'live_voice_audio'
                  )
                ORDER BY outbox.available_at, outbox.effect_outbox_item_id
                FOR UPDATE OF outbox, effect SKIP LOCKED
                LIMIT 1
                """
            )
        ).fetchone()
        if row is None:
            return None
        attempt_id = uuid7()
        attempt_no = int(row[9]) + 1
        claim_token = int(row[10]) + 1
        destination_kind = str(row[11])
        try:
            route = await self._routes.effect_route(
                connection,
                scene_id=row[3],
                context_party_id=row[4],
                intended_destination_kind=(
                    "creator_inbox"
                    if destination_kind == "live_voice_audio"
                    else destination_kind
                ),
            )
        except OtherHumanInputViolation:
            await connection.execute(
                """UPDATE armi.effects SET status='cancelled',verification_status='verified',
                   cancelled_at=statement_timestamp(),settled_at=statement_timestamp()
                   WHERE effect_id=%s AND status='registered'""",
                (row[1],),
            )
            await connection.execute(
                """UPDATE armi.effect_outbox_items SET status='cancelled',
                   cancelled_at=statement_timestamp(),last_error_code='EFFECT-DESTINATION-UNAVAILABLE'
                   WHERE effect_outbox_item_id=%s AND status='ready'""",
                (row[0],),
            )
            return None
        adapter_binding = _adapter_binding(destination_kind)
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
                claim_token, dispatch_state) VALUES (%s, %s, %s, %s, %s, 'prepared')
            """,
            (
                attempt_id,
                row[1],
                attempt_no,
                adapter_binding,
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
        request = FrozenEffectRequest(
            EffectId(row[1]),
            EffectAttemptId(attempt_id),
            row[2],
            row[3],
            row[4],
            cast(
                Literal[
                    "creator_inbox",
                    "other_human_inbox",
                    "external_group",
                    "external_private",
                    "live_voice_audio",
                ],
                destination_kind,
            ),
            route.external_channel,
            route.external_account_key,
            route.external_conversation_key,
            Digest(str(row[6])),
            int(row[7]),
            TraceId(str(row[8])),
            row[13],
        )
        return EffectDispatchSnapshot(
            row[0],
            claim_owner,
            claim_token,
            attempt_no,
            row[5],
            route.scene_key,
            None if row[12] is None else Instant(row[12]),
            request,
        )

    async def cancel_data_rights(
        self, uow: PostgreSQLRuntimeUnitOfWork, snapshot: EffectDispatchSnapshot
    ) -> None:
        """Cancel a prepared attempt that may no longer cross dispatch."""

        await self._settle(
            uow,
            snapshot,
            observation_kind="query",
            reliability="reliable",
            observation_digest=_observation_digest(
                snapshot, "query", "data_rights_blocked"
            ),
            receiver_ref=None,
            receiver_external_ref=None,
            status="cancelled",
            verification="verified",
            outbox_status="cancelled",
            operation_status="effect_cancelled",
            attempt_result="cancelled",
            error_code=None,
        )

    async def cancel_policy(
        self, uow: PostgreSQLRuntimeUnitOfWork, snapshot: EffectDispatchSnapshot
    ) -> None:
        """Cancel a prepared Effect before the external call boundary."""

        await self._settle(
            uow,
            snapshot,
            observation_kind="query",
            reliability="reliable",
            observation_digest=_observation_digest(
                snapshot, "query", "configuration_policy_blocked"
            ),
            receiver_ref=None,
            receiver_external_ref=None,
            status="cancelled",
            verification="verified",
            outbox_status="cancelled",
            operation_status="effect_cancelled",
            attempt_result="cancelled",
            error_code="EFFECT-QQ-POLICY-NOT-ALLOWED",
        )

    async def settle_overdue_ready(self, uow: PostgreSQLRuntimeUnitOfWork) -> bool:
        """Close one ready Effect whose dispatch deadline passed before dispatch."""

        connection = uow.transaction
        row = await (
            await connection.execute(
                """
                SELECT outbox.effect_outbox_item_id, outbox.attempt_count,
                       effect.effect_id, effect.subject_id, effect.purpose,
                       effect.trace_id, effect.authorization_basis,
                       effect.destination_kind, outbox.claim_token
                FROM armi.effect_outbox_items AS outbox
                JOIN armi.effects AS effect ON effect.effect_id=outbox.effect_id
                WHERE outbox.status='ready'
                  AND outbox.dispatch_deadline<=statement_timestamp()
                  AND effect.status='registered'
                  AND effect.destination_kind IN (
                      'creator_inbox', 'other_human_inbox', 'external_group',
                      'external_private', 'live_voice_audio'
                  )
                ORDER BY outbox.dispatch_deadline, outbox.effect_outbox_item_id
                FOR UPDATE OF outbox, effect SKIP LOCKED
                LIMIT 1
                """
            )
        ).fetchone()
        if row is None:
            return False
        cancelled = False
        attempt_id = uuid7()
        observation_id = uuid7()
        attempt_no = int(row[1]) + 1
        claim_token = int(row[8]) + 1
        error_code = None if cancelled else "EFFECT-DISPATCH-DEADLINE"
        result_status = "cancelled" if cancelled else "failed"
        effect_status = "cancelled" if cancelled else "failed"
        outbox_status = "cancelled" if cancelled else "dead"
        adapter_binding = _adapter_binding(str(row[7]))
        digest = Digest.from_bytes(
            rfc8785.dumps(
                {
                    "schema_version": "armi.effect-predispatch-settlement.v1",
                    "effect_id": str(row[2]),
                    "result_status": result_status,
                    "error_code": error_code,
                }
            )
        )
        settled = await (
            await connection.execute(
                """
                INSERT INTO armi.effect_attempts (
                    effect_attempt_id,effect_id,attempt_no,adapter_binding,
                    claim_token,dispatch_state,result_status,error_code,settled_at)
                VALUES (%s,%s,%s,%s,%s,'settled',%s,%s,statement_timestamp())
                RETURNING settled_at
                """,
                (
                    attempt_id,
                    row[2],
                    attempt_no,
                    adapter_binding,
                    claim_token,
                    result_status,
                    error_code,
                ),
            )
        ).fetchone()
        if settled is None:
            raise EffectViolation("EFFECT-SETTLEMENT-STALE")
        settled_at = settled[0]
        await connection.execute(
            """
            INSERT INTO armi.effect_observations (
                effect_observation_id,effect_id,effect_attempt_id,
                observation_kind,reliability,observation_digest,
                conclusion,reason_code,evidence_kind,evidence_digest,
                source_identity)
            VALUES (%s,%s,%s,'rejection','reliable',%s,%s,%s,
                    'owner_state',%s,'effect-overdue')
            """,
            (
                observation_id,
                row[2],
                attempt_id,
                digest.value,
                effect_status,
                error_code or "POLICY-GRANT-REVOKED",
                digest.value,
            ),
        )
        await connection.execute(
            """
            UPDATE armi.effects SET status=%s,verification_status='verified',
                current_attempt_id=%s,current_observation_id=%s,settled_at=%s,
                cancelled_at=CASE WHEN %s='cancelled' THEN %s ELSE NULL END
            WHERE effect_id=%s AND status='registered'
            """,
            (
                effect_status,
                attempt_id,
                observation_id,
                settled_at,
                effect_status,
                settled_at,
                row[2],
            ),
        )
        await connection.execute(
            """
            UPDATE armi.effect_outbox_items SET status=%s,
                attempt_count=%s,claim_token=%s,last_error_code=%s,
                cancelled_at=CASE WHEN %s='cancelled' THEN %s ELSE NULL END
            WHERE effect_outbox_item_id=%s AND status='ready'
            """,
            (
                outbox_status,
                attempt_no,
                claim_token,
                error_code,
                outbox_status,
                settled_at,
                row[0],
            ),
        )
        await uow.audit.append(
            AuditDraft(
                AuditEventId(uuid7()),
                AuditReference("runtime", uow.environment_id),
                Purpose(str(row[4])),
                f"effect.{effect_status}",
                AuditReference("effect", row[2]),
                (AuditResultStatus.APPLIED if cancelled else AuditResultStatus.FAILED),
                TraceId(str(row[5])),
                AuditSensitivity.PRIVATE,
                subject_id=SubjectId(row[3]),
            )
        )
        return True

    async def expired(
        self, uow: PostgreSQLRuntimeUnitOfWork
    ) -> EffectDispatchSnapshot | None:
        connection = uow.transaction
        row = await (
            await connection.execute(
                """
                SELECT outbox.effect_outbox_item_id, outbox.claim_owner,
                       outbox.claim_token, outbox.attempt_count,
                       effect.payload_artifact_id, effect.scene_id,
                       effect.effect_id, attempt.effect_attempt_id,
                       effect.subject_id, effect.scene_id,
                       effect.destination_party_id, effect.payload_digest,
                       effect.payload_bytes, effect.trace_id,
                       effect.destination_kind, NULL::text, NULL::text, NULL::text,
                       effect.live_voice_turn_id, outbox.dispatch_deadline
                FROM armi.effect_outbox_items AS outbox
                JOIN armi.effects AS effect ON effect.effect_id = outbox.effect_id
                JOIN armi.effect_attempts AS attempt
                  ON attempt.effect_attempt_id = effect.current_attempt_id
                WHERE outbox.status = 'claimed'
                  AND outbox.claim_expires_at <= statement_timestamp()
                  AND effect.status = 'dispatching'
                  AND effect.destination_kind IN (
                      'creator_inbox', 'other_human_inbox', 'external_group',
                      'external_private', 'live_voice_audio'
                  )
                  AND attempt.dispatch_state IN ('prepared', 'dispatching')
                ORDER BY outbox.claim_expires_at, outbox.effect_outbox_item_id
                FOR UPDATE OF outbox, effect, attempt SKIP LOCKED
                LIMIT 1
                """
            )
        ).fetchone()
        if row is None:
            return None
        route = await self._routes.effect_route(
            connection,
            scene_id=row[9],
            context_party_id=row[10],
            intended_destination_kind=(
                "creator_inbox" if str(row[14]) == "live_voice_audio" else str(row[14])
            ),
        )
        return EffectDispatchSnapshot(
            row[0],
            row[1],
            int(row[2]),
            int(row[3]),
            row[4],
            route.scene_key,
            None if row[19] is None else Instant(row[19]),
            FrozenEffectRequest(
                EffectId(row[6]),
                EffectAttemptId(row[7]),
                row[8],
                row[9],
                row[10],
                cast(
                    Literal[
                        "creator_inbox",
                        "other_human_inbox",
                        "external_group",
                        "external_private",
                        "live_voice_audio",
                    ],
                    str(row[14]),
                ),
                route.external_channel,
                route.external_account_key,
                route.external_conversation_key,
                Digest(str(row[11])),
                int(row[12]),
                TraceId(str(row[13])),
                row[18],
            ),
        )

    async def unknown(
        self, uow: PostgreSQLRuntimeUnitOfWork
    ) -> EffectDispatchSnapshot | None:
        connection = uow.transaction
        row = await (
            await connection.execute(
                """
                SELECT outbox.effect_outbox_item_id, attempt.effect_attempt_id,
                       outbox.claim_token, outbox.attempt_count,
                       effect.payload_artifact_id, effect.scene_id,
                       effect.effect_id, effect.subject_id,
                       effect.scene_id, effect.destination_party_id,
                       effect.payload_digest, effect.payload_bytes,
                       effect.trace_id,
                       effect.destination_kind, NULL::text, NULL::text, NULL::text,
                       effect.live_voice_turn_id, outbox.dispatch_deadline
                FROM armi.effect_outbox_items AS outbox
                JOIN armi.effects AS effect ON effect.effect_id = outbox.effect_id
                JOIN armi.effect_attempts AS attempt
                  ON attempt.effect_attempt_id = effect.current_attempt_id
                WHERE outbox.status = 'unknown'
                  AND NOT (effect.effect_kind='creator_response'
                           AND outbox.last_error_code='EFFECT-RUNTIME-INTERRUPTED')
                  AND effect.status = 'unknown'
                  AND effect.destination_kind IN (
                      'creator_inbox', 'other_human_inbox', 'external_group',
                      'external_private', 'live_voice_audio'
                  )
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
        route = await self._routes.effect_route(
            connection,
            scene_id=row[8],
            context_party_id=row[9],
            intended_destination_kind=(
                "creator_inbox" if str(row[13]) == "live_voice_audio" else str(row[13])
            ),
        )
        return EffectDispatchSnapshot(
            row[0],
            None,
            int(row[2]),
            int(row[3]),
            row[4],
            route.scene_key,
            None if row[18] is None else Instant(row[18]),
            FrozenEffectRequest(
                EffectId(row[6]),
                EffectAttemptId(row[1]),
                row[7],
                row[8],
                row[9],
                cast(
                    Literal[
                        "creator_inbox",
                        "other_human_inbox",
                        "external_group",
                        "external_private",
                        "live_voice_audio",
                    ],
                    str(row[13]),
                ),
                route.external_channel,
                route.external_account_key,
                route.external_conversation_key,
                Digest(str(row[10])),
                int(row[11]),
                TraceId(str(row[12])),
                row[17],
            ),
        )

    async def mark_dispatching(
        self,
        uow: PostgreSQLRuntimeUnitOfWork,
        snapshot: EffectDispatchSnapshot,
        *,
        runtime_fence: RuntimeFence,
        data_rights_fence: DataRightsFence,
    ) -> bool:
        if snapshot.claim_owner is None:
            raise EffectViolation("EFFECT-CLAIM-STALE")
        connection = uow.transaction
        authorization = await (
            await connection.execute(
                """
                SELECT effect.authorization_basis, effect.destination_kind,
                       effect.scene_id, effect.destination_party_id
                FROM armi.effects AS effect
                WHERE effect.effect_id = %s AND effect.current_attempt_id = %s
                """,
                (
                    snapshot.request.effect_id.value,
                    snapshot.request.attempt_id.value,
                ),
            )
        ).fetchone()
        if authorization is None:
            raise EffectViolation("EFFECT-CLAIM-STALE")
        basis = str(authorization[0])
        destination_kind = str(authorization[1])
        if basis in {"runtime_builtin", "runtime_configuration"}:
            try:
                route = await self._routes.effect_route(
                    connection,
                    scene_id=authorization[2],
                    context_party_id=authorization[3],
                    intended_destination_kind="creator_inbox"
                    if destination_kind == "live_voice_audio"
                    else destination_kind,
                )
                current_route = (
                    route.external_channel,
                    route.external_account_key,
                    route.external_conversation_key,
                )
                frozen_route = (
                    snapshot.request.external_channel,
                    snapshot.request.external_account_key,
                    snapshot.request.external_conversation_key,
                )
                route_matches = current_route == frozen_route
            except OtherHumanInputViolation:
                route_matches = False
            if not route_matches:
                await self._settle(
                    uow,
                    snapshot,
                    observation_kind="query",
                    reliability="reliable",
                    observation_digest=_observation_digest(
                        snapshot, "query", "destination_unavailable"
                    ),
                    receiver_ref=None,
                    receiver_external_ref=None,
                    status="cancelled",
                    verification="verified",
                    outbox_status="cancelled",
                    operation_status="effect_cancelled",
                    attempt_result="cancelled",
                    error_code="EFFECT-DESTINATION-UNAVAILABLE",
                )
                return False
        else:
            raise EffectViolation("EFFECT-AUTHORIZATION-INVALID")
        row = await (
            await connection.execute(
                """
                UPDATE armi.effect_attempts AS attempt
                SET dispatch_state = 'dispatching',
                    dispatched_at = statement_timestamp(),
                    dispatch_runtime_instance_id = %s,
                    dispatch_runtime_fence_token = %s,
                    data_rights_contact_generation = %s,
                    data_rights_use_generation = %s
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
                    runtime_fence.runtime_instance_id.value,
                    runtime_fence.fence_token,
                    data_rights_fence.contact_generation,
                    data_rights_fence.use_generation,
                    snapshot.request.attempt_id.value,
                    snapshot.outbox_id,
                    snapshot.claim_owner,
                    snapshot.claim_token,
                ),
            )
        ).fetchone()
        if row is None:
            raise EffectViolation("EFFECT-CLAIM-STALE")
        return True

    async def renew_claim(
        self, uow: PostgreSQLRuntimeUnitOfWork, snapshot: EffectDispatchSnapshot
    ) -> None:
        if snapshot.claim_owner is None:
            raise EffectViolation("EFFECT-CLAIM-STALE")
        connection = uow.transaction
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
        uow: PostgreSQLRuntimeUnitOfWork,
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
            receiver_external_ref=receipt.external_receiver_ref,
            status="completed",
            verification="verified",
            outbox_status="delivered",
            operation_status="effect_completed",
            attempt_result="succeeded",
            error_code=None,
        )

    async def settle_rejection(
        self,
        uow: PostgreSQLRuntimeUnitOfWork,
        snapshot: EffectDispatchSnapshot,
        *,
        error_code: str = "EFFECT-RECEIVER-NOT-DELIVERED",
    ) -> None:
        await self._settle(
            uow,
            snapshot,
            observation_kind="rejection",
            reliability="reliable",
            observation_digest=_observation_digest(
                snapshot, "rejection", "receiver_rejected"
            ),
            receiver_ref=None,
            receiver_external_ref=None,
            status="failed",
            verification="verified",
            outbox_status="dead",
            operation_status="effect_failed",
            attempt_result="failed",
            error_code=error_code,
        )

    async def settle_absent(
        self, uow: PostgreSQLRuntimeUnitOfWork, snapshot: EffectDispatchSnapshot
    ) -> bool:
        connection = uow.transaction
        disposition, attempt_state = await self._absent_disposition(
            connection, snapshot
        )
        digest = _observation_digest(snapshot, "query", "not_delivered")
        if disposition is _AbsentDisposition.RETRY:
            await self._record_retry(
                uow,
                snapshot,
                digest,
                was_dispatched=attempt_state == "dispatching",
            )
            return True
        await self._settle(
            uow,
            snapshot,
            observation_kind="rejection",
            reliability="reliable",
            observation_digest=digest,
            receiver_ref=None,
            receiver_external_ref=None,
            status="failed",
            verification="verified",
            outbox_status="dead",
            operation_status="effect_failed",
            attempt_result="failed",
            error_code="EFFECT-RECEIVER-NOT-DELIVERED",
        )
        return False

    async def _absent_disposition(
        self,
        connection: Any,
        snapshot: EffectDispatchSnapshot,
    ) -> tuple[_AbsentDisposition, str]:
        current = await (
            await connection.execute(
                """
                SELECT outbox.attempt_count, outbox.max_attempts,
                       (outbox.dispatch_deadline IS NULL OR statement_timestamp() < outbox.dispatch_deadline),
                       attempt.dispatch_state
                FROM armi.effect_outbox_items AS outbox
                JOIN armi.effects AS effect ON effect.effect_id = outbox.effect_id
                JOIN armi.effect_attempts AS attempt
                  ON attempt.effect_attempt_id = effect.current_attempt_id
                WHERE outbox.effect_outbox_item_id = %s
                  AND outbox.status = 'claimed'
                  AND outbox.claim_owner = %s
                  AND outbox.claim_token = %s
                  AND effect.effect_id = %s
                  AND effect.status = 'dispatching'
                  AND effect.current_attempt_id = %s
                  AND attempt.dispatch_state IN ('prepared', 'dispatching')
                FOR UPDATE OF outbox, effect, attempt
                """,
                (
                    snapshot.outbox_id,
                    snapshot.claim_owner,
                    snapshot.claim_token,
                    snapshot.request.effect_id.value,
                    snapshot.request.attempt_id.value,
                ),
            )
        ).fetchone()
        if current is None:
            raise EffectViolation("EFFECT-SETTLEMENT-STALE")
        return (
            _AbsentDisposition.RETRY
            if int(current[0]) < int(current[1]) and bool(current[2])
            else _AbsentDisposition.FAILED,
            str(current[3]),
        )

    async def settle_unknown(
        self, uow: PostgreSQLRuntimeUnitOfWork, snapshot: EffectDispatchSnapshot
    ) -> None:
        await self._settle(
            uow,
            snapshot,
            observation_kind="ambiguous",
            reliability="inconclusive",
            observation_digest=_observation_digest(snapshot, "ambiguous", "unknown"),
            receiver_ref=None,
            receiver_external_ref=None,
            status="unknown",
            verification="inconclusive",
            outbox_status="unknown",
            operation_status="effect_unknown",
            attempt_result="unknown",
            error_code="EFFECT-RESULT-UNKNOWN",
        )

    async def resolve_unknown_receipt(
        self,
        uow: PostgreSQLRuntimeUnitOfWork,
        snapshot: EffectDispatchSnapshot,
        receipt: EffectAdapterReceipt,
    ) -> None:
        await self._resolve_unknown(
            uow,
            snapshot,
            observation_kind="receipt",
            observation_digest=receipt.receipt_digest,
            receiver_ref=receipt.delivery_id.value,
            receiver_external_ref=receipt.external_receiver_ref,
            status="completed",
            verification="verified",
            outbox_status="delivered",
            operation_status="effect_completed",
            error_code=None,
        )

    async def resolve_unknown_absent(
        self, uow: PostgreSQLRuntimeUnitOfWork, snapshot: EffectDispatchSnapshot
    ) -> None:
        await self._resolve_unknown(
            uow,
            snapshot,
            observation_kind="query",
            observation_digest=_observation_digest(
                snapshot, "query", "confirmed_not_delivered"
            ),
            receiver_ref=None,
            receiver_external_ref=None,
            status="failed",
            verification="verified",
            outbox_status="dead",
            operation_status="effect_failed",
            error_code="EFFECT-RECEIVER-NOT-DELIVERED",
        )

    async def settle_integrity_failure(
        self, uow: PostgreSQLRuntimeUnitOfWork, snapshot: EffectDispatchSnapshot
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
            receiver_external_ref=None,
            status="failed",
            verification="verified",
            outbox_status="dead",
            operation_status="effect_failed",
            attempt_result="failed",
            error_code="EFFECT-PAYLOAD-INVALID",
        )

    async def _record_retry(
        self,
        uow: PostgreSQLRuntimeUnitOfWork,
        snapshot: EffectDispatchSnapshot,
        observation_digest: Digest,
        *,
        was_dispatched: bool,
    ) -> None:
        connection = uow.transaction
        observation_id = uuid7()
        await self._insert_observation(
            connection,
            snapshot,
            observation_id,
            "query",
            "reliable",
            observation_digest,
            None,
            None,
            "failed" if was_dispatched else "cancelled",
            "EFFECT-RECEIVER-NOT-DELIVERED"
            if was_dispatched
            else "EFFECT-PREDISPATCH-CANCELLED",
            "owner_state",
        )
        if was_dispatched:
            await connection.execute(
                """
                UPDATE armi.effect_attempts
                SET dispatch_state='settled', result_status='failed',
                    error_code='EFFECT-RECEIVER-NOT-DELIVERED',
                    settled_at=statement_timestamp()
                WHERE effect_attempt_id=%s AND dispatch_state='dispatching'
                """,
                (snapshot.request.attempt_id.value,),
            )
        else:
            await connection.execute(
                """
                UPDATE armi.effect_attempts
                SET dispatch_state='settled', result_status='cancelled',
                    error_code=NULL, settled_at=statement_timestamp()
                WHERE effect_attempt_id=%s AND dispatch_state='prepared'
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
                last_error_code=%s
            WHERE effect_outbox_item_id=%s AND claim_token=%s
            """,
            (
                "EFFECT-RECEIVER-NOT-DELIVERED" if was_dispatched else None,
                snapshot.outbox_id,
                snapshot.claim_token,
            ),
        )

    async def _settle(
        self,
        uow: PostgreSQLRuntimeUnitOfWork,
        snapshot: EffectDispatchSnapshot,
        *,
        observation_kind: str,
        reliability: str,
        observation_digest: Digest,
        receiver_ref: UUID | None,
        receiver_external_ref: str | None,
        status: str,
        verification: str,
        outbox_status: str,
        operation_status: str,
        attempt_result: str,
        error_code: str | None,
    ) -> None:
        connection = uow.transaction
        observation_id = uuid7()
        await self._insert_observation(
            connection,
            snapshot,
            observation_id,
            observation_kind,
            reliability,
            observation_digest,
            receiver_ref,
            receiver_external_ref,
            status,
            error_code
            or (
                "EFFECT-DELIVERY-CONFIRMED"
                if status == "completed"
                else "EFFECT-RESULT-UNKNOWN"
            ),
            {
                "receipt": "adapter_receipt",
                "rejection": "adapter_rejection",
                "ambiguous": "adapter_ambiguous",
                "query": "owner_state",
            }[observation_kind],
        )
        attempt = await (
            await connection.execute(
                """
                UPDATE armi.effect_attempts
                SET dispatch_state='settled', result_status=%s, error_code=%s,
                    settled_at=statement_timestamp()
                WHERE effect_attempt_id=%s AND dispatch_state IN ('prepared','dispatching')
                RETURNING settled_at
                """,
                (
                    attempt_result,
                    error_code if attempt_result in {"failed", "unknown"} else None,
                    snapshot.request.attempt_id.value,
                ),
            )
        ).fetchone()
        if attempt is None:
            raise EffectViolation("EFFECT-SETTLEMENT-STALE")
        await connection.execute(
            """
            UPDATE armi.effects SET status=%s, verification_status=%s,
                current_observation_id=%s, settled_at=%s,
                cancelled_at=CASE WHEN %s='cancelled' THEN %s ELSE NULL END
            WHERE effect_id=%s AND current_attempt_id=%s AND status='dispatching'
            """,
            (
                status,
                verification,
                observation_id,
                attempt[0],
                status,
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
            )
        )

    async def _resolve_unknown(
        self,
        uow: PostgreSQLRuntimeUnitOfWork,
        snapshot: EffectDispatchSnapshot,
        *,
        observation_kind: str,
        observation_digest: Digest,
        receiver_ref: UUID | None,
        receiver_external_ref: str | None,
        status: str,
        verification: str,
        outbox_status: str,
        operation_status: str,
        error_code: str | None,
    ) -> None:
        connection = uow.transaction
        observation_id = uuid7()
        await self._insert_observation(
            connection,
            snapshot,
            observation_id,
            observation_kind,
            "reliable",
            observation_digest,
            receiver_ref,
            receiver_external_ref,
            status,
            error_code
            or (
                "EFFECT-DELIVERY-CONFIRMED"
                if status == "completed"
                else "EFFECT-DELIVERY-NOT-CONFIRMED"
            ),
            "adapter_receipt" if observation_kind == "receipt" else "owner_state",
        )
        effect = await (
            await connection.execute(
                """
                UPDATE armi.effects
                SET status=%s, verification_status=%s,
                    current_observation_id=%s,
                    settled_at=statement_timestamp()
                WHERE effect_id=%s AND current_attempt_id=%s
                  AND status='unknown'
                RETURNING settled_at
                """,
                (
                    status,
                    verification,
                    observation_id,
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
        if outbox is None:
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
        receiver_external_ref: str | None = None,
        conclusion: str = "unknown",
        reason_code: str = "EFFECT-RESULT-UNKNOWN",
        evidence_kind: str = "inconclusive",
    ) -> None:
        await connection.execute(
            """
            INSERT INTO armi.effect_observations (
                effect_observation_id, effect_id, effect_attempt_id,
                observation_kind, reliability, receiver_ref,
                receiver_external_ref, observation_digest, conclusion,
                reason_code, evidence_kind, evidence_ref, evidence_digest,
                source_identity)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            """,
            (
                observation_id,
                snapshot.request.effect_id.value,
                snapshot.request.attempt_id.value,
                kind,
                reliability,
                receiver_ref,
                receiver_external_ref,
                digest.value,
                conclusion,
                reason_code,
                evidence_kind,
                receiver_external_ref,
                digest.value,
                _adapter_binding(snapshot.request.destination_kind),
            ),
        )


def _adapter_binding(destination_kind: str) -> str:
    if destination_kind in {"creator_inbox", "other_human_inbox"}:
        return _LOCAL_ADAPTER_BINDING
    if destination_kind in {"external_group", "external_private"}:
        return _EXTERNAL_MESSAGE_ADAPTER_BINDING
    if destination_kind == "live_voice_audio":
        return "armi.effect-adapter.live-voice-audio-v1"
    raise EffectViolation("EFFECT-ADAPTER-UNAVAILABLE")


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


__all__ = ("EffectDispatchSnapshot", "PostgreSQLEffectDispatchRepository")
