"""Effect-owned startup recovery contribution."""

from uuid import uuid7

from armi_kernel.contracts import Digest
from armi_runtime_foundation import (
    PostgreSQLTransaction,
    RecoveryAuditContribution,
    RecoveryContribution,
    RecoveryFindingContribution,
    RecoveryFindingDecision,
    RecoveryMetricContribution,
    RecoveryOwnerIdentity,
    RecoveryScope,
    RecoveryWorkSnapshot,
)


class EffectRecoveryParticipant:
    owner_identity = RecoveryOwnerIdentity("effect")
    work_scopes = (("action_intent", "effect.register"), ("effect", "effect.dispatch"))

    async def recover(
        self,
        transaction: PostgreSQLTransaction,
        scope: RecoveryScope,
        work: tuple[RecoveryWorkSnapshot, ...],
    ) -> RecoveryContribution:
        del work
        dispatched = await (
            await transaction.execute(
                """
                SELECT effect.effect_id, attempt.effect_attempt_id,
                       outbox.effect_outbox_item_id, outbox.claim_token
                FROM armi.effects AS effect
                JOIN armi.effect_attempts AS attempt
                  ON attempt.effect_attempt_id = effect.current_attempt_id
                 AND attempt.effect_id = effect.effect_id
                JOIN armi.effect_outbox_items AS outbox
                  ON outbox.effect_id = effect.effect_id
                WHERE effect.subject_id = %s
                  AND effect.status = 'dispatching'
                  AND attempt.dispatch_state = 'dispatching'
                  AND outbox.status = 'claimed'
                ORDER BY effect.effect_id
                FOR UPDATE OF effect, attempt, outbox
                """,
                (scope.subject_id,),
            )
        ).fetchall()
        audits: list[RecoveryAuditContribution] = []
        for effect_id, attempt_id, outbox_id, claim_token in dispatched:
            observation_id = uuid7()
            digest = Digest.from_bytes(
                f"recovery:{effect_id}:{attempt_id}:unknown".encode()
            )
            await transaction.execute(
                """
                INSERT INTO armi.effect_observations (
                    effect_observation_id, effect_id, effect_attempt_id,
                    observation_kind, reliability, observation_digest)
                VALUES (%s, %s, %s, 'ambiguous', 'inconclusive', %s)
                """,
                (observation_id, effect_id, attempt_id, digest.value),
            )
            await transaction.execute(
                """
                UPDATE armi.effect_attempts
                SET dispatch_state = 'settled', result_status = 'unknown',
                    error_code = 'EFFECT-RESULT-UNKNOWN',
                    settled_at = statement_timestamp()
                WHERE effect_attempt_id = %s AND dispatch_state = 'dispatching'
                """,
                (attempt_id,),
            )
            await transaction.execute(
                """
                UPDATE armi.effects
                SET status = 'unknown', verification_status = 'inconclusive',
                    current_observation_id = %s,
                    settled_at = statement_timestamp()
                WHERE effect_id = %s AND current_attempt_id = %s
                  AND status = 'dispatching'
                """,
                (observation_id, effect_id, attempt_id),
            )
            await transaction.execute(
                """
                UPDATE armi.effect_outbox_items
                SET status = 'unknown', claim_owner = NULL,
                    claim_expires_at = NULL,
                    last_error_code = 'EFFECT-RESULT-UNKNOWN'
                WHERE effect_outbox_item_id = %s AND claim_token = %s
                  AND status = 'claimed'
                """,
                (outbox_id, claim_token),
            )
            audits.append(
                RecoveryAuditContribution(
                    "effect.recovered.unknown",
                    "effect",
                    effect_id,
                    "REC-EFFECT-OUTCOME-UNKNOWN",
                )
            )
        row = await (
            await transaction.execute(
                """
            SELECT
                count(*) FILTER (
                    WHERE effect.status IN ('registered', 'dispatching', 'unknown')
                ),
                count(*) FILTER (
                    WHERE (effect.status = 'registered' AND outbox.status <> 'ready')
                       OR (effect.status = 'dispatching' AND (
                           outbox.status <> 'claimed'
                           OR attempt.dispatch_state <> 'dispatching'
                       ))
                       OR (effect.status = 'unknown' AND (
                           outbox.status <> 'unknown'
                           OR attempt.result_status <> 'unknown'
                           OR observation.reliability <> 'inconclusive'
                       ))
                )
            FROM armi.effects AS effect
            JOIN armi.effect_outbox_items AS outbox
              ON outbox.effect_id = effect.effect_id
            LEFT JOIN armi.effect_attempts AS attempt
              ON attempt.effect_attempt_id = effect.current_attempt_id
             AND attempt.effect_id = effect.effect_id
            LEFT JOIN armi.effect_observations AS observation
              ON observation.effect_observation_id = effect.current_observation_id
             AND observation.effect_id = effect.effect_id
            WHERE effect.subject_id=%s
        """,
                (scope.subject_id,),
            )
        ).fetchone()
        resumable, invalid = (0, 0) if row is None else (int(row[0]), int(row[1]))
        return RecoveryContribution(
            self.owner_identity,
            findings=()
            if invalid == 0 and not dispatched
            else (
                RecoveryFindingContribution(
                    "effect",
                    RecoveryFindingDecision.BLOCKED,
                    ("REC-EFFECT-INVALID" if invalid else "REC-EFFECT-OUTCOME-UNKNOWN"),
                    None if invalid else dispatched[0][0],
                ),
            ),
            metrics=(
                RecoveryMetricContribution("effect.resumable_effect_count", resumable),
                RecoveryMetricContribution(
                    "effect.unknown_attempt_count", len(dispatched)
                ),
            ),
            audits=tuple(audits),
        )
