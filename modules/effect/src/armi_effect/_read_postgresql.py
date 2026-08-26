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
    EffectResponsibilitySnapshot,
    EffectStatus,
    EffectVerificationStatus,
)


class PostgreSQLEffectOperationRead:
    __slots__ = ()

    async def registration_by_intent(
        self,
        transaction: PostgreSQLTransaction,
        *,
        action_intent_id: UUID,
    ) -> EffectResponsibilitySnapshot | None:
        row = await (
            await transaction.execute(
                """SELECT effect_registration_id,status,reason_code,
                          capability_request_id,permission_grant_id
                   FROM armi.effect_registrations WHERE action_intent_id=%s""",
                (action_intent_id,),
            )
        ).fetchone()
        if row is None:
            return None
        return EffectResponsibilitySnapshot(row[0], str(row[1]), row[2], row[3], row[4])

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
                       effect.action_intent_id, effect.policy_decision_id,
                       effect.capability_request_id,effect.permission_grant_id,
                       effect.subject_id, effect.scene_id, effect.context_party_id,
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
                       observation.conclusion,observation.reason_code,
                       observation.evidence_kind
                FROM armi.effects AS effect
                LEFT JOIN armi.effect_observations AS observation
                  ON observation.effect_observation_id=effect.current_observation_id
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
            policy_decision_id=row[3],
            capability_request_id=row[4],
            permission_grant_id=row[5],
            subject_id=row[6],
            scene_id=row[7],
            context_party_id=row[8],
            payload_artifact_id=row[9],
            payload_digest=Digest(str(row[10])),
            payload_bytes=int(row[11]),
            effect_kind=str(row[12]),
            capability_kind=str(row[13]),
            status=EffectStatus(str(row[14])),
            verification_status=EffectVerificationStatus(str(row[15])),
            registered_at=Instant(row[16]),
            cancelled_at=None if row[17] is None else Instant(row[17]),
            settled_at=None if row[18] is None else Instant(row[18]),
            attempt_count=int(row[19]),
            current_observation_kind=(
                None if row[20] is None else EffectObservationKind(str(row[20]))
            ),
            current_observation_reliability=(
                None if row[21] is None else EffectObservationReliability(str(row[21]))
            ),
            current_attempt_id=row[22],
            current_attempt_no=None if row[23] is None else int(row[23]),
            current_dispatch_state=None if row[24] is None else str(row[24]),
            current_observation_id=row[25],
            observation_conclusion=None if row[26] is None else str(row[26]),
            observation_reason=None if row[27] is None else str(row[27]),
            observation_evidence_kind=None if row[28] is None else str(row[28]),
        )
