"""Effect-owned read model for cross-module action assembly."""

from __future__ import annotations

from uuid import UUID

from armi_kernel.contracts import Digest, Instant
from armi_runtime_foundation import PostgreSQLTransaction

from .api import (
    EffectLedgerSnapshot,
    EffectObservationKind,
    EffectObservationReliability,
    EffectStatus,
    EffectVerificationStatus,
)


class PostgreSQLEffectOperationRead:
    __slots__ = ()

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
                       effect.action_intent_id, effect.policy_decision_id,
                       effect.subject_id, effect.scene_id, effect.context_party_id,
                       effect.payload_artifact_id, effect.payload_digest,
                       effect.payload_bytes, effect.effect_kind,
                       effect.capability_kind, effect.status,
                       effect.verification_status, effect.registered_at,
                       effect.cancelled_at, effect.settled_at,
                       (SELECT count(*) FROM armi.effect_attempts AS attempt
                        WHERE attempt.effect_id=effect.effect_id),
                       observation.observation_kind, observation.reliability
                FROM armi.effects AS effect
                LEFT JOIN armi.effect_observations AS observation
                  ON observation.effect_observation_id=effect.current_observation_id
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
            policy_decision_id=row[3],
            subject_id=row[4],
            scene_id=row[5],
            context_party_id=row[6],
            payload_artifact_id=row[7],
            payload_digest=Digest(str(row[8])),
            payload_bytes=int(row[9]),
            effect_kind=str(row[10]),
            capability_kind=str(row[11]),
            status=EffectStatus(str(row[12])),
            verification_status=EffectVerificationStatus(str(row[13])),
            registered_at=Instant(row[14]),
            cancelled_at=None if row[15] is None else Instant(row[15]),
            settled_at=None if row[16] is None else Instant(row[16]),
            attempt_count=int(row[17]),
            current_observation_kind=(
                None if row[18] is None else EffectObservationKind(str(row[18]))
            ),
            current_observation_reliability=(
                None if row[19] is None else EffectObservationReliability(str(row[19]))
            ),
        )
