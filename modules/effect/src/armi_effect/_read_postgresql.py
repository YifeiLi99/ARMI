"""Effect-owned read model for cross-module action assembly."""

from __future__ import annotations

from uuid import UUID

from armi_kernel.contracts import Digest, Instant
from armi_runtime_foundation import PostgreSQLTransaction

from .api import (
    EffectLedgerSnapshot,
    EffectObservationKind,
    EffectObservationReliability,
    EffectObservationSnapshot,
    EffectStatus,
    EffectVerificationStatus,
)


class PostgreSQLEffectOperationRead:
    __slots__ = ()

    async def observe(
        self, transaction: PostgreSQLTransaction
    ) -> EffectObservationSnapshot:
        rows = await (
            await transaction.execute(
                "SELECT status, count(*) FROM armi.effects GROUP BY status ORDER BY status"
            )
        ).fetchall()
        age = await (
            await transaction.execute(
                """SELECT EXTRACT(EPOCH FROM (clock_timestamp() - min(registered_at)))
                   FROM armi.effects
                   WHERE status IN ('registered','dispatching','unknown')"""
            )
        ).fetchone()
        return EffectObservationSnapshot(
            tuple((str(row[0]), int(row[1])) for row in rows),
            None if age is None or age[0] is None else max(0, int(age[0])),
        )

    async def by_action_intent(
        self,
        transaction: PostgreSQLTransaction,
        *,
        action_intent_id: UUID,
    ) -> EffectLedgerSnapshot | None:
        row = await (
            await transaction.execute(
                "SELECT effect_id FROM armi.effects WHERE action_intent_id=%s",
                (action_intent_id,),
            )
        ).fetchone()
        if row is None:
            return None
        return await self.by_effect_id(transaction, effect_id=row[0])

    async def by_effect_id(
        self,
        transaction: PostgreSQLTransaction,
        *,
        effect_id: UUID,
    ) -> EffectLedgerSnapshot | None:
        row = await (
            await transaction.execute(
                """
                SELECT effect.effect_id, effect.action_intent_revision_id,
                       effect.action_intent_id, effect.subject_id, effect.scene_id, effect.context_party_id,
                       effect.payload_artifact_id, effect.payload_digest,
                       effect.payload_bytes, effect.effect_kind,
                       effect.capability_kind, effect.status,
                       effect.verification_status, effect.registered_at,
                       effect.cancelled_at, effect.settled_at,
                       (SELECT count(*) FROM armi.effect_attempts AS attempt
                        WHERE attempt.effect_id=effect.effect_id),
                       observation.observation_kind, observation.reliability,
                       attempt.effect_attempt_id,attempt.attempt_no,
                       attempt.dispatch_state,observation.effect_observation_id,
                       observation.conclusion,coalesce(observation.reason_code, outbox.last_error_code),
                       observation.evidence_kind
                FROM armi.effects AS effect
                LEFT JOIN armi.effect_observations AS observation
                  ON observation.effect_observation_id=effect.current_observation_id
                LEFT JOIN armi.effect_outbox_items AS outbox ON outbox.effect_id=effect.effect_id
                LEFT JOIN armi.effect_attempts AS attempt
                  ON attempt.effect_attempt_id=effect.current_attempt_id
                WHERE effect.effect_id=%s
                """,
                (effect_id,),
            )
        ).fetchone()
        if row is None:
            return None
        return EffectLedgerSnapshot(
            effect_id=row[0],
            action_intent_revision_id=row[1],
            action_intent_id=row[2],
            subject_id=row[3],
            scene_id=row[4],
            context_party_id=row[5],
            payload_artifact_id=row[6],
            payload_digest=Digest(str(row[7])),
            payload_bytes=int(row[8]),
            effect_kind=str(row[9]),
            capability_kind=str(row[10]),
            status=EffectStatus(str(row[11])),
            verification_status=EffectVerificationStatus(str(row[12])),
            registered_at=Instant(row[13]),
            cancelled_at=None if row[14] is None else Instant(row[14]),
            settled_at=None if row[15] is None else Instant(row[15]),
            attempt_count=int(row[16]),
            current_observation_kind=(
                None if row[17] is None else EffectObservationKind(str(row[17]))
            ),
            current_observation_reliability=(
                None if row[18] is None else EffectObservationReliability(str(row[18]))
            ),
            current_attempt_id=row[19],
            current_attempt_no=None if row[20] is None else int(row[20]),
            current_dispatch_state=None if row[21] is None else str(row[21]),
            current_observation_id=row[22],
            observation_conclusion=None if row[23] is None else str(row[23]),
            observation_reason=None if row[24] is None else str(row[24]),
            observation_evidence_kind=None if row[25] is None else str(row[25]),
        )
