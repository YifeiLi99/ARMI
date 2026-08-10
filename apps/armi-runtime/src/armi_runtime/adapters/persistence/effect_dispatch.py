"""Authoritative T-06 effect attempt, observation, and settlement persistence."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Literal, cast
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

from .effect_grant_coordination import (
    coordinate_dispatch_boundary,
    supersede_effect_policy,
)
from .unit_of_work import PostgreSQLUnitOfWork

_LOCAL_ADAPTER_BINDING = "armi.local-inbox-adapter.postgresql-v1"
_EXTERNAL_GROUP_ADAPTER_BINDING = "armi.external-group-adapter.v1"


class _AbsentDisposition(StrEnum):
    RETRY = "retry"
    FAILED = "failed"
    CANCELLED_REVOKED = "cancelled_revoked"
    CANCELLED_EXPIRED = "cancelled_expired"
    CANCELLED_SUPERSEDED = "cancelled_superseded"


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
                       effect.subject_id, effect.scene_id,
                       effect.destination_party_id, effect.payload_artifact_id,
                       effect.payload_digest, effect.payload_bytes, effect.trace_id,
                       scene.scene_key, outbox.attempt_count, outbox.claim_token,
                       effect.destination_kind, binding.channel_kind,
                       binding.account_key, binding.external_key
                FROM armi.effect_outbox_items AS outbox
                JOIN armi.effects AS effect ON effect.effect_id = outbox.effect_id
                JOIN armi.interaction_scenes AS scene
                  ON scene.scene_id = effect.scene_id
                LEFT JOIN armi.external_channel_bindings AS binding
                  ON binding.external_binding_id = effect.destination_binding_id
                WHERE outbox.status = 'ready'
                  AND outbox.available_at <= statement_timestamp()
                  AND statement_timestamp() < outbox.dispatch_deadline
                  AND outbox.attempt_count < outbox.max_attempts
                  AND effect.status = 'registered'
                  AND effect.destination_kind IN (
                      'creator_inbox', 'other_human_inbox', 'external_group'
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
        attempt_no = int(row[10]) + 1
        claim_token = int(row[11]) + 1
        adapter_binding = _adapter_binding(str(row[12]))
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
        await connection.execute(
            """
            UPDATE armi.action_operations
            SET phase = 'dispatching', outcome = NULL
            WHERE effect_id = %s AND phase = 'effect_registered' AND outcome IS NULL
            """,
            (row[1],),
        )
        request = FrozenEffectRequest(
            EffectId(row[1]),
            EffectAttemptId(attempt_id),
            row[2],
            row[3],
            row[4],
            cast(
                Literal["creator_inbox", "other_human_inbox", "external_group"],
                str(row[12]),
            ),
            None if row[13] is None else str(row[13]),
            None if row[14] is None else str(row[14]),
            None if row[15] is None else str(row[15]),
            Digest(str(row[6])),
            int(row[7]),
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
                       effect.subject_id, effect.scene_id,
                       effect.destination_party_id, effect.payload_digest,
                       effect.payload_bytes, effect.trace_id,
                       effect.destination_kind, binding.channel_kind,
                       binding.account_key, binding.external_key
                FROM armi.effect_outbox_items AS outbox
                JOIN armi.effects AS effect ON effect.effect_id = outbox.effect_id
                JOIN armi.effect_attempts AS attempt
                  ON attempt.effect_attempt_id = effect.current_attempt_id
                JOIN armi.interaction_scenes AS scene
                  ON scene.scene_id = effect.scene_id
                LEFT JOIN armi.external_channel_bindings AS binding
                  ON binding.external_binding_id = effect.destination_binding_id
                WHERE outbox.status = 'claimed'
                  AND outbox.claim_expires_at <= statement_timestamp()
                  AND effect.status = 'dispatching'
                  AND effect.destination_kind IN (
                      'creator_inbox', 'other_human_inbox', 'external_group'
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
                cast(
                    Literal["creator_inbox", "other_human_inbox", "external_group"],
                    str(row[14]),
                ),
                None if row[15] is None else str(row[15]),
                None if row[16] is None else str(row[16]),
                None if row[17] is None else str(row[17]),
                Digest(str(row[11])),
                int(row[12]),
                TraceId(str(row[13])),
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
                       effect.scene_id, effect.destination_party_id,
                       effect.payload_digest, effect.payload_bytes,
                       effect.trace_id,
                       effect.destination_kind, binding.channel_kind,
                       binding.account_key, binding.external_key
                FROM armi.effect_outbox_items AS outbox
                JOIN armi.effects AS effect ON effect.effect_id = outbox.effect_id
                JOIN armi.effect_attempts AS attempt
                  ON attempt.effect_attempt_id = effect.current_attempt_id
                JOIN armi.interaction_scenes AS scene
                  ON scene.scene_id = effect.scene_id
                LEFT JOIN armi.external_channel_bindings AS binding
                  ON binding.external_binding_id = effect.destination_binding_id
                WHERE outbox.status = 'unknown'
                  AND effect.status = 'unknown'
                  AND effect.destination_kind IN (
                      'creator_inbox', 'other_human_inbox', 'external_group'
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
                cast(
                    Literal["creator_inbox", "other_human_inbox", "external_group"],
                    str(row[13]),
                ),
                None if row[14] is None else str(row[14]),
                None if row[15] is None else str(row[15]),
                None if row[16] is None else str(row[16]),
                Digest(str(row[10])),
                int(row[11]),
                TraceId(str(row[12])),
            ),
        )

    async def mark_dispatching(
        self, uow: PostgreSQLUnitOfWork, snapshot: EffectDispatchSnapshot
    ) -> bool:
        if snapshot.claim_owner is None:
            raise EffectViolation("EFFECT-CLAIM-STALE")
        connection = uow._connection_for_repository()  # pyright: ignore[reportPrivateUsage]
        authorization = await (
            await connection.execute(
                """
                SELECT effect.authorization_basis, effect.destination_kind,
                       binding.status
                FROM armi.effects AS effect
                LEFT JOIN armi.external_channel_bindings AS binding
                  ON binding.external_binding_id = effect.destination_binding_id
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
        if basis == "creator_grant":
            boundary = await coordinate_dispatch_boundary(
                uow,
                effect_id=snapshot.request.effect_id.value,
                attempt_id=snapshot.request.attempt_id.value,
                outbox_id=snapshot.outbox_id,
                claim_owner=snapshot.claim_owner,
                claim_token=snapshot.claim_token,
                expected_operation_status="effect_dispatching",
                cancelled_operation_status="effect_cancelled",
            )
            if boundary is None:
                raise EffectViolation("EFFECT-CLAIM-STALE")
            if not boundary.allowed:
                return False
        elif not (
            (basis == "runtime_builtin" and destination_kind == "other_human_inbox")
            or (
                basis == "runtime_configuration"
                and destination_kind == "external_group"
                and authorization[2] == "active"
            )
        ):
            raise EffectViolation("EFFECT-AUTHORIZATION-INVALID")
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
        return True

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
            receiver_external_ref=receipt.external_receiver_ref,
            status="completed",
            verification="verified",
            outbox_status="delivered",
            operation_status="effect_completed",
            attempt_result="succeeded",
            error_code=None,
        )

    async def settle_rejection(
        self, uow: PostgreSQLUnitOfWork, snapshot: EffectDispatchSnapshot
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
            error_code="EFFECT-RECEIVER-NOT-DELIVERED",
        )

    async def settle_absent(
        self, uow: PostgreSQLUnitOfWork, snapshot: EffectDispatchSnapshot
    ) -> bool:
        connection = uow._connection_for_repository()  # pyright: ignore[reportPrivateUsage]
        disposition, grant_id, attempt_state = await self._absent_disposition(
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
        cancellation_reason = {
            _AbsentDisposition.CANCELLED_REVOKED: "POLICY-GRANT-REVOKED",
            _AbsentDisposition.CANCELLED_EXPIRED: "POLICY-GRANT-EXPIRED",
            _AbsentDisposition.CANCELLED_SUPERSEDED: "POLICY-GRANT-NOT-CURRENT",
        }.get(disposition)
        if cancellation_reason is not None:
            if grant_id is None:
                raise EffectViolation("EFFECT-SETTLEMENT-STALE")
            await self._settle_cancelled(
                uow,
                snapshot,
                observation_digest=digest,
                grant_id=grant_id,
                reason_code=cancellation_reason,
            )
            return False
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
    ) -> tuple[_AbsentDisposition, UUID | None, str]:
        policy_ref = await (
            await connection.execute(
                """
                SELECT effect.authorization_basis, policy.matched_grant_id
                FROM armi.effects AS effect
                LEFT JOIN armi.policy_decisions AS policy
                  ON policy.policy_decision_id = effect.policy_decision_id
                WHERE effect.effect_id = %s
                  AND effect.current_attempt_id = %s
                """,
                (
                    snapshot.request.effect_id.value,
                    snapshot.request.attempt_id.value,
                ),
            )
        ).fetchone()
        if policy_ref is None:
            raise EffectViolation("EFFECT-SETTLEMENT-STALE")
        if str(policy_ref[0]) != "creator_grant":
            current = await (
                await connection.execute(
                    """
                    SELECT outbox.attempt_count, outbox.max_attempts,
                           statement_timestamp() < outbox.dispatch_deadline,
                           attempt.dispatch_state
                    FROM armi.effect_outbox_items AS outbox
                    JOIN armi.effects AS effect
                      ON effect.effect_id = outbox.effect_id
                    JOIN armi.effect_attempts AS attempt
                      ON attempt.effect_attempt_id = effect.current_attempt_id
                    WHERE outbox.effect_outbox_item_id = %s
                      AND outbox.status = 'claimed'
                      AND outbox.claim_owner = %s
                      AND outbox.claim_token = %s
                      AND effect.effect_id = %s
                      AND effect.status = 'dispatching'
                      AND effect.current_attempt_id = %s
                      AND effect.authorization_basis IN (
                          'runtime_builtin', 'runtime_configuration'
                      )
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
                _classify_absent_effect(
                    attempt_count=int(current[0]),
                    max_attempts=int(current[1]),
                    before_dispatch_deadline=bool(current[2]),
                    policy_current=True,
                    grant_status="active",
                    grant_time_valid=True,
                ),
                None,
                str(current[3]),
            )
        if policy_ref[1] is None:
            raise EffectViolation("EFFECT-SETTLEMENT-STALE")
        grant_id = UUID(str(policy_ref[1]))
        grant = await (
            await connection.execute(
                """
                SELECT status,
                       valid_from <= statement_timestamp()
                       AND statement_timestamp() < valid_until
                FROM armi.permission_grants
                WHERE grant_id = %s
                FOR UPDATE
                """,
                (grant_id,),
            )
        ).fetchone()
        current = await (
            await connection.execute(
                """
                SELECT outbox.attempt_count, outbox.max_attempts,
                       statement_timestamp() < outbox.dispatch_deadline,
                       policy.is_current
                         AND policy.decision_outcome = 'allowed',
                       attempt.dispatch_state
                FROM armi.effect_outbox_items AS outbox
                JOIN armi.effects AS effect ON effect.effect_id = outbox.effect_id
                JOIN armi.effect_attempts AS attempt
                  ON attempt.effect_attempt_id = effect.current_attempt_id
                JOIN armi.policy_decisions AS policy
                  ON policy.policy_decision_id = effect.policy_decision_id
                WHERE outbox.effect_outbox_item_id = %s
                  AND outbox.status = 'claimed'
                  AND outbox.claim_owner = %s
                  AND outbox.claim_token = %s
                  AND effect.effect_id = %s
                  AND effect.status = 'dispatching'
                  AND effect.current_attempt_id = %s
                  AND attempt.dispatch_state IN ('prepared', 'dispatching')
                FOR UPDATE OF outbox, effect, attempt, policy
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
        if grant is None or current is None:
            raise EffectViolation("EFFECT-SETTLEMENT-STALE")
        return (
            _classify_absent_effect(
                attempt_count=int(current[0]),
                max_attempts=int(current[1]),
                before_dispatch_deadline=bool(current[2]),
                policy_current=bool(current[3]),
                grant_status=str(grant[0]),
                grant_time_valid=bool(grant[1]),
            ),
            grant_id,
            str(current[4]),
        )

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
            receiver_external_ref=receipt.external_receiver_ref,
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
            receiver_external_ref=None,
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
        uow: PostgreSQLUnitOfWork,
        snapshot: EffectDispatchSnapshot,
        observation_digest: Digest,
        *,
        was_dispatched: bool,
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
        await connection.execute(
            "UPDATE armi.action_operations SET phase='effect_registered', outcome=NULL WHERE effect_id=%s",
            (snapshot.request.effect_id.value,),
        )

    async def _settle_cancelled(
        self,
        uow: PostgreSQLUnitOfWork,
        snapshot: EffectDispatchSnapshot,
        *,
        observation_digest: Digest,
        grant_id: UUID,
        reason_code: str,
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
        attempt = await (
            await connection.execute(
                """
                UPDATE armi.effect_attempts
                SET dispatch_state='settled', result_status='cancelled',
                    error_code=NULL,
                    settled_at=statement_timestamp()
                WHERE effect_attempt_id=%s
                  AND dispatch_state IN ('prepared','dispatching')
                RETURNING settled_at
                """,
                (snapshot.request.attempt_id.value,),
            )
        ).fetchone()
        if attempt is None:
            raise EffectViolation("EFFECT-SETTLEMENT-STALE")
        effect = await (
            await connection.execute(
                """
                UPDATE armi.effects
                SET status='cancelled', verification_status='verified',
                    current_observation_id=%s,
                    settled_at=%s, cancelled_at=%s
                WHERE effect_id=%s AND current_attempt_id=%s
                  AND status='dispatching'
                RETURNING policy_decision_id, action_intent_revision_id,
                          operation_id
                """,
                (
                    observation_id,
                    attempt[0],
                    attempt[0],
                    snapshot.request.effect_id.value,
                    snapshot.request.attempt_id.value,
                ),
            )
        ).fetchone()
        outbox = await (
            await connection.execute(
                """
                UPDATE armi.effect_outbox_items
                SET status='cancelled', claim_owner=NULL, claim_expires_at=NULL,
                    cancelled_at=%s, delivered_at=NULL, last_error_code=NULL
                WHERE effect_outbox_item_id=%s AND status='claimed'
                  AND claim_token=%s
                RETURNING effect_outbox_item_id
                """,
                (attempt[0], snapshot.outbox_id, snapshot.claim_token),
            )
        ).fetchone()
        if effect is None or outbox is None:
            raise EffectViolation("EFFECT-SETTLEMENT-STALE")
        current_decision_id = await supersede_effect_policy(
            connection,
            prior_decision_id=UUID(str(effect[0])),
            action_revision_id=UUID(str(effect[1])),
            operation_id=UUID(str(effect[2])),
            reason_code=reason_code,
        )
        if current_decision_id is None:
            raise EffectViolation("EFFECT-SETTLEMENT-STALE")
        operation = await (
            await connection.execute(
                """
                UPDATE armi.action_operations
                SET phase='terminal', outcome='cancelled',
                    current_policy_decision_id=%s, reason_code=NULL,
                    completed_at=%s
                WHERE operation_id=%s
                  AND phase='dispatching' AND outcome IS NULL
                RETURNING operation_id
                """,
                (current_decision_id, attempt[0], effect[2]),
            )
        ).fetchone()
        if operation is None:
            raise EffectViolation("EFFECT-SETTLEMENT-STALE")
        await uow.audit.append(
            AuditDraft(
                AuditEventId(uuid7()),
                AuditReference("runtime", uow.environment_id),
                Purpose("effect.settlement"),
                "effect.cancelled",
                AuditReference("effect", snapshot.request.effect_id.value),
                AuditResultStatus.APPLIED,
                snapshot.request.trace_id,
                AuditSensitivity.PRIVATE,
                subject_id=SubjectId(snapshot.request.subject_id),
                grant=AuditReference("permission_grant", grant_id),
            )
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
        receiver_external_ref: str | None,
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
            receiver_external_ref,
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
                (attempt_result, error_code, snapshot.request.attempt_id.value),
            )
        ).fetchone()
        if attempt is None:
            raise EffectViolation("EFFECT-SETTLEMENT-STALE")
        await connection.execute(
            """
            UPDATE armi.effects SET status=%s, verification_status=%s,
                current_observation_id=%s, settled_at=%s
            WHERE effect_id=%s AND current_attempt_id=%s AND status='dispatching'
            """,
            (
                status,
                verification,
                observation_id,
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
            UPDATE armi.action_operations SET phase='terminal',
                outcome=CASE WHEN %s='effect_completed' THEN 'completed'
                             WHEN %s='effect_unknown' THEN 'unknown'
                             ELSE 'failed' END,
                reason_code=%s, completed_at=%s
            WHERE effect_id=%s
            """,
            (
                operation_status,
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
        receiver_external_ref: str | None,
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
            receiver_external_ref,
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
        operation = await (
            await connection.execute(
                """
                UPDATE armi.action_operations
                SET phase='terminal',
                    outcome=CASE WHEN %s='effect_completed' THEN 'completed'
                                 ELSE 'failed' END,
                    reason_code=%s, completed_at=%s
                WHERE effect_id=%s AND phase='terminal' AND outcome='unknown'
                RETURNING operation_id
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
    ) -> None:
        await connection.execute(
            """
            INSERT INTO armi.effect_observations (
                effect_observation_id, effect_id, effect_attempt_id,
                observation_kind, reliability, receiver_ref,
                receiver_external_ref, observation_digest)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
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
            ),
        )


def _adapter_binding(destination_kind: str) -> str:
    if destination_kind in {"creator_inbox", "other_human_inbox"}:
        return _LOCAL_ADAPTER_BINDING
    if destination_kind == "external_group":
        return _EXTERNAL_GROUP_ADAPTER_BINDING
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


def _classify_absent_effect(
    *,
    attempt_count: int,
    max_attempts: int,
    before_dispatch_deadline: bool,
    policy_current: bool,
    grant_status: str,
    grant_time_valid: bool,
) -> _AbsentDisposition:
    if not policy_current:
        return _AbsentDisposition.CANCELLED_SUPERSEDED
    if grant_status == "revoked":
        return _AbsentDisposition.CANCELLED_REVOKED
    if (
        grant_status == "expired"
        or not grant_time_valid
        or not before_dispatch_deadline
    ):
        return _AbsentDisposition.CANCELLED_EXPIRED
    if grant_status != "active":
        return _AbsentDisposition.CANCELLED_SUPERSEDED
    if attempt_count < max_attempts:
        return _AbsentDisposition.RETRY
    return _AbsentDisposition.FAILED


__all__ = ("EffectDispatchSnapshot", "PostgreSQLEffectDispatchRepository")
