"""Terminate interrupted camera sessions; they are never resumed in place."""

from armi_runtime_foundation import (
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
    work_scopes: tuple[tuple[str, str], ...] = ()

    async def recover(
        self,
        transaction: PostgreSQLTransaction,
        scope: RecoveryScope,
        work: tuple[RecoveryWorkSnapshot, ...],
    ) -> RecoveryContribution:
        del scope, work
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
                   WHERE status='recognizing' RETURNING observation_id"""
            )
        ).fetchall()
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
