"""Grant/effect coordination at the external dispatch boundary."""

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
)
from armi_kernel.contracts import Digest, Purpose, SubjectId, TraceId

from .unit_of_work import PostgreSQLUnitOfWork


@dataclass(frozen=True, slots=True)
class DispatchBoundaryResult:
    allowed: bool
    grant_id: UUID
    reason_code: str | None = None


async def coordinate_dispatch_boundary(
    uow: PostgreSQLUnitOfWork,
    *,
    effect_id: UUID,
    attempt_id: UUID,
    outbox_id: UUID,
    claim_owner: UUID,
    claim_token: int,
    expected_operation_status: str,
    cancelled_operation_status: str,
) -> DispatchBoundaryResult | None:
    """Serialize dispatch with grant revoke/expiry and cancel before I/O."""

    del cancelled_operation_status
    connection = uow._connection_for_repository()  # pyright: ignore[reportPrivateUsage]
    expected_phase = {
        "effect_dispatching": "dispatching",
        "codex_dispatching": "dispatching",
    }.get(expected_operation_status)
    if expected_phase is None:
        return None
    policy_ref = await (
        await connection.execute(
            """
            SELECT policy.matched_grant_id
            FROM armi.effects AS effect
            JOIN armi.policy_decisions AS policy
              ON policy.policy_decision_id = effect.policy_decision_id
            WHERE effect.effect_id=%s AND effect.current_attempt_id=%s
            """,
            (effect_id, attempt_id),
        )
    ).fetchone()
    if policy_ref is None or policy_ref[0] is None:
        return None
    grant_id = UUID(str(policy_ref[0]))
    grant = await (
        await connection.execute(
            """
            SELECT status,
                   valid_from <= statement_timestamp()
                   AND statement_timestamp() < valid_until
            FROM armi.permission_grants
            WHERE grant_id=%s
            FOR UPDATE
            """,
            (grant_id,),
        )
    ).fetchone()
    current = await (
        await connection.execute(
            """
            SELECT policy.is_current
                     AND policy.decision_outcome='allowed',
                   statement_timestamp() < outbox.dispatch_deadline,
                   effect.subject_id, effect.purpose, effect.trace_id,
                   effect.policy_decision_id,
                   effect.action_intent_revision_id,
                   effect.operation_id
            FROM armi.effect_outbox_items AS outbox
            JOIN armi.effects AS effect ON effect.effect_id=outbox.effect_id
            JOIN armi.effect_attempts AS attempt
              ON attempt.effect_attempt_id=effect.current_attempt_id
            JOIN armi.policy_decisions AS policy
              ON policy.policy_decision_id=effect.policy_decision_id
            JOIN armi.action_operations AS operation
              ON operation.operation_id=
                 effect.operation_id
            WHERE outbox.effect_outbox_item_id=%s
              AND outbox.status='claimed' AND outbox.claim_owner=%s
              AND outbox.claim_token=%s
              AND effect.effect_id=%s AND effect.status='dispatching'
              AND effect.current_attempt_id=%s
              AND attempt.dispatch_state='prepared'
              AND operation.phase=%s AND operation.outcome IS NULL
            FOR UPDATE OF outbox, effect, attempt, policy, operation
            """,
            (
                outbox_id,
                claim_owner,
                claim_token,
                effect_id,
                attempt_id,
                expected_phase,
            ),
        )
    ).fetchone()
    if grant is None or current is None:
        return None
    reason_code = _dispatch_cancellation_reason(
        policy_current=bool(current[0]),
        before_dispatch_deadline=bool(current[1]),
        grant_status=str(grant[0]),
        grant_time_valid=bool(grant[1]),
    )
    if reason_code is None:
        return DispatchBoundaryResult(True, grant_id)

    cancellation_digest = Digest.from_bytes(
        rfc8785.dumps(
            cast(
                Any,
                {
                    "schema_version": "armi.effect-cancellation.v1",
                    "effect_id": str(effect_id),
                    "grant_id": str(grant_id),
                    "reason_code": reason_code,
                },
            )
        )
    )
    attempt = await (
        await connection.execute(
            """
            UPDATE armi.effect_attempts
            SET dispatch_state='settled', result_status='cancelled',
                error_code=NULL, settled_at=statement_timestamp()
            WHERE effect_attempt_id=%s AND dispatch_state='prepared'
            RETURNING settled_at
            """,
            (attempt_id,),
        )
    ).fetchone()
    if attempt is None:
        return None
    effect = await (
        await connection.execute(
            """
            UPDATE armi.effects
            SET status='cancelled', verification_status='not_started',
                current_attempt_id=NULL, cancelled_at=%s
            WHERE effect_id=%s AND status='dispatching'
              AND current_attempt_id=%s
            RETURNING effect_id
            """,
            (attempt[0], effect_id, attempt_id),
        )
    ).fetchone()
    outbox = await (
        await connection.execute(
            """
            UPDATE armi.effect_outbox_items
            SET status='cancelled', claim_owner=NULL, claim_expires_at=NULL,
                cancelled_at=%s, delivered_at=NULL, last_error_code=NULL
            WHERE effect_outbox_item_id=%s AND status='claimed'
              AND claim_owner=%s AND claim_token=%s
            RETURNING effect_outbox_item_id
            """,
            (attempt[0], outbox_id, claim_owner, claim_token),
        )
    ).fetchone()
    if effect is None or outbox is None:
        return None
    current_decision_id = await supersede_effect_policy(
        connection,
        prior_decision_id=UUID(str(current[5])),
        action_revision_id=UUID(str(current[6])),
        operation_id=UUID(str(current[7])),
        decision_digest=cancellation_digest,
        reason_code=reason_code,
    )
    if current_decision_id is None:
        return None
    operation = await (
        await connection.execute(
            """
            UPDATE armi.action_operations
            SET phase='terminal', outcome='cancelled', current_policy_decision_id=%s,
                reason_code=NULL, completed_at=%s
            WHERE operation_id=%s
              AND phase=%s AND outcome IS NULL
            RETURNING operation_id
            """,
            (
                current_decision_id,
                attempt[0],
                current[7],
                expected_phase,
            ),
        )
    ).fetchone()
    if operation is None:
        return None
    await uow.audit.append(
        AuditDraft(
            AuditEventId(uuid7()),
            AuditReference("runtime", uow.environment_id),
            Purpose(str(current[3])),
            "effect.cancelled",
            AuditReference("effect", effect_id),
            AuditResultStatus.APPLIED,
            TraceId(str(current[4])),
            AuditSensitivity.PRIVATE,
            subject_id=SubjectId(UUID(str(current[2]))),
            request_digest=cancellation_digest,
            grant=AuditReference("permission_grant", grant_id),
        )
    )
    return DispatchBoundaryResult(False, grant_id, reason_code)


async def supersede_effect_policy(
    connection: Any,
    *,
    prior_decision_id: UUID,
    action_revision_id: UUID,
    operation_id: UUID,
    decision_digest: Digest,
    reason_code: str,
) -> UUID | None:
    superseded = await (
        await connection.execute(
            """
            UPDATE armi.policy_decisions SET is_current=false
            WHERE policy_decision_id=%s AND is_current
            RETURNING policy_decision_id
            """,
            (prior_decision_id,),
        )
    ).fetchone()
    if superseded is None:
        current = await (
            await connection.execute(
                """
                SELECT policy_decision_id FROM armi.policy_decisions
                WHERE action_intent_revision_id=%s AND is_current
                """,
                (action_revision_id,),
            )
        ).fetchone()
        if current is None:
            return None
        return UUID(str(current[0]))
    decision_id = uuid7()
    await connection.execute(
        """
        INSERT INTO armi.policy_decisions (
            policy_decision_id, action_intent_revision_id,
            operation_id, decision_outcome,
            policy_identity, decision_digest, reason_code,
            supersedes_policy_decision_id, schema_version
        ) VALUES (
            %s,%s,%s,'denied','armi.policy-engine.deterministic-v1',
            %s,%s,%s,1
        )
        """,
        (
            decision_id,
            action_revision_id,
            operation_id,
            decision_digest.value,
            reason_code,
            prior_decision_id,
        ),
    )
    return decision_id


def _dispatch_cancellation_reason(
    *,
    policy_current: bool,
    before_dispatch_deadline: bool,
    grant_status: str,
    grant_time_valid: bool,
) -> str | None:
    if not policy_current:
        return "POLICY-GRANT-NOT-CURRENT"
    if grant_status == "revoked":
        return "POLICY-GRANT-REVOKED"
    if (
        grant_status == "expired"
        or not grant_time_valid
        or not before_dispatch_deadline
    ):
        return "POLICY-GRANT-EXPIRED"
    if grant_status != "active":
        return "POLICY-GRANT-NOT-CURRENT"
    return None


__all__ = (
    "DispatchBoundaryResult",
    "coordinate_dispatch_boundary",
    "supersede_effect_policy",
)
