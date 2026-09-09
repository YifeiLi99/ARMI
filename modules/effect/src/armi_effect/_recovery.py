"""Effect-owned startup recovery contribution."""

from uuid import uuid7

from armi_kernel.contracts import Digest
from armi_runtime_foundation import (
    OwnerReconciliationContext,
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
    work_scopes = (("action_intent", "effect.register"),)

    async def recover(
        self,
        transaction: PostgreSQLTransaction,
        scope: RecoveryScope,
        work: tuple[RecoveryWorkSnapshot, ...],
        *,
        conversation_only: bool = False,
    ) -> RecoveryContribution:
        if conversation_only:
            work = ()
        reconciliation = OwnerReconciliationContext(
            transaction, self.owner_identity, work
        )
        for item in work:
            if not item.reconciliation_required:
                continue
            row = await (
                await transaction.execute(
                    """SELECT registration.effect_registration_id,
                              registration.status,registration.effect_id,
                              registration.action_intent_id
                       FROM armi.effect_registrations AS registration
                       WHERE registration.work_id=%s
                       FOR UPDATE OF registration""",
                    (item.work_id,),
                )
            ).fetchone()
            if row is None:
                raise ValueError("effect registration responsibility is missing")
            if str(row[1]) == "succeeded" and row[2] is not None:
                await reconciliation.complete(
                    item.work_id, result_kind="effect", result_ref=row[2]
                )
            elif str(row[1]) != "pending":
                await reconciliation.complete(
                    item.work_id,
                    result_kind="creator_response_operation",
                    result_ref=row[3],
                )
            else:
                await transaction.execute(
                    """UPDATE armi.effect_registrations
                       SET status='failed',reason_code='EFFECT-WORK-EXHAUSTED',
                           attempt_count=attempt_count+1,
                           settled_at=statement_timestamp()
                       WHERE effect_registration_id=%s""",
                    (row[0],),
                )
                await reconciliation.fail(
                    item.work_id,
                    reason_code="REC-EFFECT-WORK-EXHAUSTED",
                )
        # A normal reply belongs to the running conversation. Startup closes
        # unsent replies; it never turns them into another delivery attempt.
        await transaction.execute(
            """UPDATE armi.effect_attempts AS attempt
               SET dispatch_state='settled',result_status='cancelled',
                   settled_at=statement_timestamp()
               FROM armi.effects AS effect
               WHERE effect.subject_id=%s AND effect.effect_kind='creator_response'
                 AND effect.current_attempt_id=attempt.effect_attempt_id
                 AND attempt.dispatch_state='prepared'""",
            (scope.subject_id,),
        )
        cancelled = await (
            await transaction.execute(
                """UPDATE armi.effects AS effect
                   SET status='cancelled',verification_status='verified',
                       cancelled_at=statement_timestamp(),settled_at=statement_timestamp()
                   WHERE subject_id=%s AND effect_kind='creator_response'
                     AND (status='registered' OR (status='dispatching' AND EXISTS (
                       SELECT 1 FROM armi.effect_attempts AS attempt
                       WHERE attempt.effect_attempt_id=effect.current_attempt_id
                         AND attempt.dispatched_at IS NULL)))
                   RETURNING effect_id""",
                (scope.subject_id,),
            )
        ).fetchall()
        await transaction.execute(
            """UPDATE armi.effect_outbox_items
               SET status='cancelled',cancelled_at=statement_timestamp(),
                   claim_owner=NULL,claim_expires_at=NULL,
                   last_error_code='EFFECT-RUNTIME-INTERRUPTED'
               WHERE effect_id=ANY(%s::uuid[])""",
            ([row[0] for row in cancelled],),
        )
        dispatched = await (
            await transaction.execute(
                """
                SELECT effect.effect_id, attempt.effect_attempt_id,
                       outbox.effect_outbox_item_id, outbox.claim_token, effect.effect_kind
                FROM armi.effects AS effect
                JOIN armi.effect_attempts AS attempt
                  ON attempt.effect_attempt_id = effect.current_attempt_id
                 AND attempt.effect_id = effect.effect_id
                JOIN armi.effect_outbox_items AS outbox
                  ON outbox.effect_id = effect.effect_id
                WHERE effect.subject_id = %s
                  AND effect.status = 'dispatching'
                  AND (NOT %s OR effect.effect_kind='creator_response')
                  AND attempt.dispatch_state = 'dispatching'
                  AND outbox.status = 'claimed'
                ORDER BY effect.effect_id
                FOR UPDATE OF effect, attempt, outbox
                """,
                (scope.subject_id, conversation_only),
            )
        ).fetchall()
        audits: list[RecoveryAuditContribution] = []
        for effect_id, attempt_id, outbox_id, claim_token, effect_kind in dispatched:
            reason = (
                "EFFECT-RUNTIME-INTERRUPTED"
                if effect_kind == "creator_response"
                else "EFFECT-RESULT-UNKNOWN"
            )
            observation_id = uuid7()
            digest = Digest.from_bytes(
                f"recovery:{effect_id}:{attempt_id}:unknown".encode()
            )
            await transaction.execute(
                """
                INSERT INTO armi.effect_observations (
                    effect_observation_id, effect_id, effect_attempt_id,
                    observation_kind, reliability, observation_digest,
                    conclusion, reason_code, evidence_kind, evidence_digest,
                    source_identity)
                VALUES (%s, %s, %s, 'ambiguous', 'inconclusive', %s,
                        'unknown',%s,'adapter_ambiguous',%s,
                        'effect-recovery')
                """,
                (
                    observation_id,
                    effect_id,
                    attempt_id,
                    digest.value,
                    reason,
                    digest.value,
                ),
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
                    last_error_code = %s
                WHERE effect_outbox_item_id = %s AND claim_token = %s
                  AND status = 'claimed'
                """,
                (reason, outbox_id, claim_token),
            )
            audits.append(
                RecoveryAuditContribution(
                    "effect.recovered.unknown",
                    "effect",
                    effect_id,
                    "REC-EFFECT-OUTCOME-UNKNOWN",
                )
            )
        await transaction.execute(
            """UPDATE armi.effect_outbox_items AS outbox
               SET last_error_code='EFFECT-RUNTIME-INTERRUPTED'
               FROM armi.effects AS effect
               WHERE outbox.effect_id=effect.effect_id AND effect.subject_id=%s
                 AND effect.effect_kind='creator_response' AND effect.status='unknown'""",
            (scope.subject_id,),
        )
        row = await (
            await transaction.execute(
                """
            SELECT
                count(*) FILTER (
                    WHERE effect.status IN ('registered', 'dispatching', 'unknown')
                      AND effect.effect_kind <> 'creator_response'
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
        uncertain_external_work = [
            row for row in dispatched if row[4] != "creator_response"
        ]
        return RecoveryContribution(
            self.owner_identity,
            findings=()
            if invalid == 0 and not uncertain_external_work
            else (
                RecoveryFindingContribution(
                    "effect",
                    RecoveryFindingDecision.BLOCKED,
                    ("REC-EFFECT-INVALID" if invalid else "REC-EFFECT-OUTCOME-UNKNOWN"),
                    None if invalid else uncertain_external_work[0][0],
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

    async def end_conversations(
        self,
        transaction: PostgreSQLTransaction,
        scope: RecoveryScope,
        work: tuple[RecoveryWorkSnapshot, ...],
    ) -> None:
        await self.recover(transaction, scope, work, conversation_only=True)
