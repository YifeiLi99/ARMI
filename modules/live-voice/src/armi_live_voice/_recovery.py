"""Do not resume an interrupted microphone or speaker session after restart."""

from __future__ import annotations

from armi_interaction.api import mark_voice_activity_ended
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


class LiveVoiceRecoveryParticipant:
    owner_identity = RecoveryOwnerIdentity("live-voice")
    work_scopes: tuple[tuple[str, str], ...] = ()

    async def end_interrupted_work(
        self,
        transaction: PostgreSQLTransaction,
        scope: RecoveryScope,
        work: tuple[RecoveryWorkSnapshot, ...],
    ) -> None:
        await self.recover(transaction, scope, work)

    async def recover(
        self,
        transaction: PostgreSQLTransaction,
        scope: RecoveryScope,
        work: tuple[RecoveryWorkSnapshot, ...],
    ) -> RecoveryContribution:
        del scope, work
        turn_rows = await (
            await transaction.execute(
                """UPDATE armi.live_voice_turns AS turn
                   SET result_status=CASE
                           WHEN result_status IN ('recognizing','thinking','speaking')
                           THEN 'unknown' ELSE result_status END,
                       completed_at=statement_timestamp(),
                       error_code=CASE
                           WHEN result_status IN ('recognizing','thinking','speaking')
                           THEN 'VOICE-RUNTIME-RESTARTED' ELSE error_code END
                   WHERE turn.completed_at IS NULL
                   RETURNING turn_id,scene_id"""
            )
        ).fetchall()
        if turn_rows:
            await mark_voice_activity_ended(
                transaction, scene_ids=tuple({row[1] for row in turn_rows})
            )
        return RecoveryContribution(
            self.owner_identity,
            findings=()
            if not turn_rows
            else (
                RecoveryFindingContribution(
                    "live_voice_turn",
                    RecoveryFindingDecision.TERMINAL,
                    "REC-LIVE-VOICE-TURN-ENDED",
                ),
            ),
            metrics=(
                RecoveryMetricContribution(
                    "live_voice.ended_turn_count", len(turn_rows)
                ),
            ),
        )


__all__ = ("LiveVoiceRecoveryParticipant",)
