"""Terminate interrupted visual sessions; dispatched work is never guessed."""

from armi_runtime_foundation import (
    OwnerReconciliationContext,
    PostgreSQLTransaction,
    RecoveryContribution,
    RecoveryFindingContribution,
    RecoveryFindingDecision,
    RecoveryMetricContribution,
    RecoveryOwnerIdentity,
    RecoveryScope,
    RecoveryWorkSnapshot,
)


class LiveVisionRecoveryParticipant:
    owner_identity = RecoveryOwnerIdentity("live-vision")
    work_scopes = (
        ("live_vision_observation", "live.vision.capture"),
        ("live_vision_observation", "live.vision.observe"),
    )

    async def recover(
        self,
        transaction: PostgreSQLTransaction,
        scope: RecoveryScope,
        work: tuple[RecoveryWorkSnapshot, ...],
    ) -> RecoveryContribution:
        del scope
        reconciliation = OwnerReconciliationContext(
            transaction, self.owner_identity, work
        )
        rows = await (
            await transaction.execute(
                """UPDATE armi.live_vision_sessions SET state='failed',ended_at=statement_timestamp(),
               error_code='VISION-RUNTIME-RESTARTED' WHERE ended_at IS NULL RETURNING session_id"""
            )
        ).fetchall()
        observation_rows = await (
            await transaction.execute(
                """UPDATE armi.live_vision_observations
                   SET status='unknown',error_code='VISION-OUTCOME-UNKNOWN',
                       settled_at=statement_timestamp()
                   WHERE status IN ('capturing','recognizing') RETURNING observation_id"""
            )
        ).fetchall()
        unknown_ids = {str(row[0]) for row in observation_rows}
        for item in work:
            if (
                str(item.owner_ref) not in unknown_ids
                or not item.reconciliation_required
            ):
                continue
            await reconciliation.complete(
                item.work_id,
                result_kind="live_vision_observation",
                result_ref=item.owner_ref,
            )
        return RecoveryContribution(
            self.owner_identity,
            findings=()
            if not rows and not observation_rows
            else (
                RecoveryFindingContribution(
                    "live_vision_runtime_state",
                    RecoveryFindingDecision.TERMINAL,
                    "REC-LIVE-VISION-SESSION-ENDED",
                ),
            ),
            metrics=(
                RecoveryMetricContribution(
                    "live_vision.ended_session_count", len(rows)
                ),
                RecoveryMetricContribution(
                    "live_vision.unknown_observation_count", len(observation_rows)
                ),
            ),
        )


__all__ = ("LiveVisionRecoveryParticipant",)
