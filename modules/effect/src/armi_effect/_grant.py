"""Effect-owned cancellation around Capability authorization decisions."""

from __future__ import annotations

from uuid import UUID, uuid7

import rfc8785
from armi_capability.api import CapabilityDispatchAuthorizationPort
from armi_kernel.application import (
    AuditDraft,
    AuditEventId,
    AuditReference,
    AuditResultStatus,
    AuditSensitivity,
)
from armi_kernel.contracts import Digest, Purpose, SubjectId, TraceId
from armi_runtime_foundation import PostgreSQLRuntimeUnitOfWork, PostgreSQLTransaction

from .api import EffectDispatchBoundaryResult


class PostgreSQLEffectGrantCancellation:
    __slots__ = ()

    async def cancel_registered(
        self,
        transaction: PostgreSQLTransaction,
        *,
        policy_decision_ids: tuple[UUID, ...],
        reason_code: str,
    ) -> tuple[tuple[UUID, UUID, UUID], ...]:
        if not policy_decision_ids:
            return ()
        rows = await (
            await transaction.execute(
                """
                SELECT effect.effect_id, effect.subject_id,
                       effect.action_intent_id, effect.destination_kind
                FROM armi.effects AS effect
                JOIN armi.effect_outbox_items AS outbox
                  ON outbox.effect_id=effect.effect_id
                WHERE effect.policy_decision_id=ANY(%s::uuid[])
                  AND effect.status='registered' AND outbox.status='ready'
                ORDER BY effect.effect_id
                FOR UPDATE OF effect, outbox
                """,
                (list(policy_decision_ids),),
            )
        ).fetchall()
        cancelled: list[tuple[UUID, UUID, UUID]] = []
        for row in rows:
            effect_id, subject_id, intent_id = row[0], row[1], row[2]
            attempt_id = uuid7()
            digest = Digest.from_bytes(
                rfc8785.dumps(
                    {
                        "schema_version": "armi.effect-cancellation.v1",
                        "effect_id": str(effect_id),
                        "reason_code": reason_code,
                    }
                )
            )
            await transaction.execute(
                """
                INSERT INTO armi.effect_attempts (
                    effect_attempt_id, effect_id, attempt_no, adapter_binding,
                    claim_token, dispatch_state, result_status, settled_at)
                VALUES (%s,%s,1,%s,1,'settled','cancelled',statement_timestamp())
                """,
                (
                    attempt_id,
                    effect_id,
                    "armi.codex-runner.openai-python-sdk-v1"
                    if str(row[3]) == "codex_workspace"
                    else "armi.local-inbox-adapter.postgresql-v1",
                ),
            )
            observation_id = uuid7()
            await transaction.execute(
                """
                INSERT INTO armi.effect_observations (
                    effect_observation_id, effect_id, effect_attempt_id,
                    observation_kind, reliability, observation_digest)
                VALUES (%s,%s,%s,'runner_cancelled','reliable',%s)
                """,
                (observation_id, effect_id, attempt_id, digest.value),
            )
            await transaction.execute(
                """
                UPDATE armi.effects SET status='cancelled',
                    verification_status='verified', current_attempt_id=%s,
                    current_observation_id=%s, settled_at=statement_timestamp(),
                    cancelled_at=statement_timestamp()
                WHERE effect_id=%s AND status='registered'
                """,
                (attempt_id, observation_id, effect_id),
            )
            await transaction.execute(
                """
                UPDATE armi.effect_outbox_items SET status='cancelled',
                    cancelled_at=statement_timestamp()
                WHERE effect_id=%s AND status='ready'
                """,
                (effect_id,),
            )
            cancelled.append((effect_id, subject_id, intent_id))
        return tuple(cancelled)


class PostgreSQLEffectDispatchBoundary:
    __slots__ = ("_authorization",)

    def __init__(self, authorization: CapabilityDispatchAuthorizationPort) -> None:
        self._authorization = authorization

    async def coordinate(
        self,
        unit_of_work: PostgreSQLRuntimeUnitOfWork,
        *,
        effect_id: UUID,
        attempt_id: UUID,
        outbox_id: UUID,
        claim_owner: UUID,
        claim_token: int,
        expected_operation_status: str,
        cancelled_operation_status: str,
    ) -> EffectDispatchBoundaryResult | None:
        del cancelled_operation_status
        if expected_operation_status not in {"effect_dispatching", "codex_dispatching"}:
            return None
        connection = unit_of_work.transaction
        current = await (
            await connection.execute(
                """
                SELECT statement_timestamp()<outbox.dispatch_deadline,
                       effect.subject_id, effect.purpose, effect.trace_id,
                       effect.policy_decision_id,
                       effect.action_intent_revision_id
                FROM armi.effect_outbox_items AS outbox
                JOIN armi.effects AS effect ON effect.effect_id=outbox.effect_id
                JOIN armi.effect_attempts AS attempt
                  ON attempt.effect_attempt_id=effect.current_attempt_id
                WHERE outbox.effect_outbox_item_id=%s AND outbox.status='claimed'
                  AND outbox.claim_owner=%s AND outbox.claim_token=%s
                  AND effect.effect_id=%s AND effect.status='dispatching'
                  AND effect.current_attempt_id=%s
                  AND attempt.dispatch_state='prepared'
                FOR UPDATE OF outbox, effect, attempt
                """,
                (outbox_id, claim_owner, claim_token, effect_id, attempt_id),
            )
        ).fetchone()
        if current is None or current[4] is None:
            return None
        authorization = await self._authorization.authorize_dispatch(
            connection,
            policy_decision_id=current[4],
            action_intent_revision_id=current[5],
            before_dispatch_deadline=bool(current[0]),
        )
        if authorization.allowed:
            return EffectDispatchBoundaryResult(True, authorization.grant_id)
        reason = authorization.reason_code or "POLICY-GRANT-NOT-CURRENT"
        digest = Digest.from_bytes(
            rfc8785.dumps(
                {
                    "schema_version": "armi.effect-cancellation.v1",
                    "effect_id": str(effect_id),
                    "grant_id": None
                    if authorization.grant_id is None
                    else str(authorization.grant_id),
                    "reason_code": reason,
                }
            )
        )
        settled = await (
            await connection.execute(
                """
                UPDATE armi.effect_attempts SET dispatch_state='settled',
                    result_status='cancelled', error_code=NULL,
                    settled_at=statement_timestamp()
                WHERE effect_attempt_id=%s AND dispatch_state='prepared'
                RETURNING settled_at
                """,
                (attempt_id,),
            )
        ).fetchone()
        if settled is None:
            return None
        observation_id = uuid7()
        await connection.execute(
            """
            INSERT INTO armi.effect_observations (
                effect_observation_id, effect_id, effect_attempt_id,
                observation_kind, reliability, observation_digest)
            VALUES (%s,%s,%s,'runner_cancelled','reliable',%s)
            """,
            (observation_id, effect_id, attempt_id, digest.value),
        )
        await connection.execute(
            """
            UPDATE armi.effects SET status='cancelled',
                verification_status='verified', current_observation_id=%s,
                settled_at=%s, cancelled_at=%s
            WHERE effect_id=%s AND status='dispatching'
              AND current_attempt_id=%s
            """,
            (observation_id, settled[0], settled[0], effect_id, attempt_id),
        )
        await connection.execute(
            """
            UPDATE armi.effect_outbox_items SET status='cancelled',
                claim_owner=NULL, claim_expires_at=NULL, cancelled_at=%s,
                delivered_at=NULL, last_error_code=NULL
            WHERE effect_outbox_item_id=%s AND status='claimed'
              AND claim_owner=%s AND claim_token=%s
            """,
            (settled[0], outbox_id, claim_owner, claim_token),
        )
        await unit_of_work.audit.append(
            AuditDraft(
                AuditEventId(uuid7()),
                AuditReference("runtime", unit_of_work.environment_id),
                Purpose(str(current[2])),
                "effect.cancelled",
                AuditReference("effect", effect_id),
                AuditResultStatus.APPLIED,
                TraceId(str(current[3])),
                AuditSensitivity.PRIVATE,
                subject_id=SubjectId(current[1]),
                grant=(
                    None
                    if authorization.grant_id is None
                    else AuditReference("permission_grant", authorization.grant_id)
                ),
            )
        )
        return EffectDispatchBoundaryResult(
            False,
            authorization.grant_id,
            reason,
        )


async def coordinate_dispatch_boundary(
    unit_of_work: PostgreSQLRuntimeUnitOfWork,
    *,
    authorization: CapabilityDispatchAuthorizationPort,
    effect_id: UUID,
    attempt_id: UUID,
    outbox_id: UUID,
    claim_owner: UUID,
    claim_token: int,
    expected_operation_status: str,
    cancelled_operation_status: str,
) -> EffectDispatchBoundaryResult | None:
    return await PostgreSQLEffectDispatchBoundary(authorization).coordinate(
        unit_of_work,
        effect_id=effect_id,
        attempt_id=attempt_id,
        outbox_id=outbox_id,
        claim_owner=claim_owner,
        claim_token=claim_token,
        expected_operation_status=expected_operation_status,
        cancelled_operation_status=cancelled_operation_status,
    )


__all__ = (
    "PostgreSQLEffectDispatchBoundary",
    "PostgreSQLEffectGrantCancellation",
    "coordinate_dispatch_boundary",
)
