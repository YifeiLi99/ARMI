"""Effect-owned lifecycle used by the Codex adapter."""

from __future__ import annotations

from uuid import UUID, uuid7

from armi_capability.api import CapabilityDispatchAuthorizationPort
from armi_kernel.contracts import Digest, TraceId
from armi_runtime_foundation import PostgreSQLRuntimeUnitOfWork, PostgreSQLTransaction

from ._grant import PostgreSQLEffectDispatchBoundary
from .api import EffectCodexClaim, EffectViolation

_BINDING = "armi.codex-runner.openai-python-sdk-v1"


class PostgreSQLEffectCodexLifecycle:
    __slots__ = ("_boundary",)

    def __init__(self, authorization: CapabilityDispatchAuthorizationPort) -> None:
        self._boundary = PostgreSQLEffectDispatchBoundary(authorization)

    async def claim_codex(
        self,
        unit_of_work: PostgreSQLRuntimeUnitOfWork,
        *,
        claim_owner: UUID,
    ) -> EffectCodexClaim | None:
        transaction = unit_of_work.transaction
        row = await (
            await transaction.execute(
                """
                SELECT outbox.effect_outbox_item_id, effect.effect_id,
                       effect.action_intent_id, effect.action_intent_revision_id,
                       effect.subject_id, effect.scene_id, effect.context_party_id,
                       effect.trace_id, outbox.claim_token
                FROM armi.effect_outbox_items AS outbox
                JOIN armi.effects AS effect ON effect.effect_id=outbox.effect_id
                WHERE outbox.status='ready'
                  AND outbox.available_at<=statement_timestamp()
                  AND statement_timestamp()<outbox.dispatch_deadline
                  AND outbox.attempt_count=0 AND outbox.max_attempts=1
                  AND effect.status='registered'
                  AND effect.effect_kind='codex_delegation'
                ORDER BY outbox.available_at, outbox.effect_outbox_item_id
                FOR UPDATE OF outbox, effect SKIP LOCKED LIMIT 1
                """
            )
        ).fetchone()
        if row is None:
            return None
        attempt_id, token = uuid7(), int(row[8]) + 1
        await transaction.execute(
            """
            UPDATE armi.effect_outbox_items SET status='claimed', claim_owner=%s,
                claim_expires_at=statement_timestamp()+interval '60 seconds',
                claim_token=%s, attempt_count=1
            WHERE effect_outbox_item_id=%s AND status='ready'
            """,
            (claim_owner, token, row[0]),
        )
        await transaction.execute(
            """
            INSERT INTO armi.effect_attempts (
                effect_attempt_id, effect_id, attempt_no, adapter_binding,
                claim_token, dispatch_state)
            VALUES (%s,%s,1,%s,%s,'prepared')
            """,
            (attempt_id, row[1], _BINDING, token),
        )
        await transaction.execute(
            """
            UPDATE armi.effects SET status='dispatching',
                verification_status='pending', current_attempt_id=%s
            WHERE effect_id=%s AND status='registered'
            """,
            (attempt_id, row[1]),
        )
        return EffectCodexClaim(
            row[0],
            row[1],
            attempt_id,
            claim_owner,
            token,
            row[2],
            row[3],
            row[4],
            row[5],
            row[6],
            TraceId(str(row[7])),
        )

    async def mark_codex_dispatching(
        self,
        unit_of_work: PostgreSQLRuntimeUnitOfWork,
        claim: EffectCodexClaim,
    ) -> bool:
        boundary = await self._boundary.coordinate(
            unit_of_work,
            effect_id=claim.effect_id,
            attempt_id=claim.attempt_id,
            outbox_id=claim.outbox_id,
            claim_owner=claim.claim_owner,
            claim_token=claim.claim_token,
            expected_operation_status="codex_dispatching",
            cancelled_operation_status="codex_cancelled",
        )
        if boundary is None:
            raise EffectViolation("EFFECT-CLAIM-STALE")
        if not boundary.allowed:
            return False
        row = await (
            await unit_of_work.transaction.execute(
                """
                UPDATE armi.effect_attempts SET dispatch_state='dispatching',
                    dispatched_at=statement_timestamp()
                WHERE effect_attempt_id=%s AND dispatch_state='prepared'
                RETURNING effect_attempt_id
                """,
                (claim.attempt_id,),
            )
        ).fetchone()
        return row is not None

    async def heartbeat_codex(
        self,
        transaction: PostgreSQLTransaction,
        claim: EffectCodexClaim,
    ) -> bool:
        row = await (
            await transaction.execute(
                """
                UPDATE armi.effect_outbox_items
                SET claim_expires_at=statement_timestamp()+interval '60 seconds'
                WHERE effect_outbox_item_id=%s AND status='claimed'
                  AND claim_owner=%s AND claim_token=%s
                RETURNING effect_outbox_item_id
                """,
                (claim.outbox_id, claim.claim_owner, claim.claim_token),
            )
        ).fetchone()
        return row is not None

    async def settle_codex(
        self,
        transaction: PostgreSQLTransaction,
        *,
        claim: EffectCodexClaim,
        status: str,
        observation_digest: Digest,
        error_code: str | None,
    ) -> None:
        mapping = {
            "verified": (
                "succeeded",
                "completed",
                "verified",
                "delivered",
                "runner_verified",
                "reliable",
            ),
            "failed": (
                "failed",
                "failed",
                "verified",
                "dead",
                "runner_failed",
                "reliable",
            ),
            "unknown": (
                "unknown",
                "unknown",
                "inconclusive",
                "unknown",
                "runner_unknown",
                "inconclusive",
            ),
            "cancelled": (
                "cancelled",
                "cancelled",
                "verified",
                "cancelled",
                "runner_cancelled",
                "reliable",
            ),
        }.get(status)
        if mapping is None:
            raise EffectViolation("EFFECT-SETTLEMENT-STALE")
        (
            attempt_result,
            effect_status,
            verification,
            outbox_status,
            observation,
            reliability,
        ) = mapping
        observation_id = uuid7()
        await transaction.execute(
            """
            INSERT INTO armi.effect_observations (
                effect_observation_id, effect_id, effect_attempt_id,
                observation_kind, reliability, observation_digest)
            VALUES (%s,%s,%s,%s,%s,%s)
            """,
            (
                observation_id,
                claim.effect_id,
                claim.attempt_id,
                observation,
                reliability,
                observation_digest.value,
            ),
        )
        await transaction.execute(
            """
            UPDATE armi.effect_attempts SET dispatch_state='settled',
                result_status=%s, error_code=%s, settled_at=statement_timestamp()
            WHERE effect_attempt_id=%s AND dispatch_state='dispatching'
            """,
            (attempt_result, error_code, claim.attempt_id),
        )
        await transaction.execute(
            """
            UPDATE armi.effects SET status=%s, verification_status=%s,
                current_observation_id=%s, settled_at=statement_timestamp(),
                cancelled_at=CASE WHEN %s='cancelled' THEN statement_timestamp() ELSE NULL END
            WHERE effect_id=%s AND current_attempt_id=%s
            """,
            (
                effect_status,
                verification,
                observation_id,
                effect_status,
                claim.effect_id,
                claim.attempt_id,
            ),
        )
        await transaction.execute(
            """
            UPDATE armi.effect_outbox_items SET status=%s, claim_owner=NULL,
                claim_expires_at=NULL,
                delivered_at=CASE WHEN %s='delivered' THEN statement_timestamp() ELSE NULL END,
                cancelled_at=CASE WHEN %s='cancelled' THEN statement_timestamp() ELSE NULL END,
                last_error_code=%s
            WHERE effect_outbox_item_id=%s AND claim_owner=%s AND claim_token=%s
            """,
            (
                outbox_status,
                outbox_status,
                outbox_status,
                error_code,
                claim.outbox_id,
                claim.claim_owner,
                claim.claim_token,
            ),
        )


__all__ = ("PostgreSQLEffectCodexLifecycle",)
