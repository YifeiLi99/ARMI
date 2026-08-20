"""Do not resume an interrupted microphone or speaker session after restart."""

from __future__ import annotations

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

    async def recover(
        self,
        transaction: PostgreSQLTransaction,
        scope: RecoveryScope,
        work: tuple[RecoveryWorkSnapshot, ...],
    ) -> RecoveryContribution:
        del scope, work
        provider_rows = await (
            await transaction.execute(
                """UPDATE armi.live_voice_provider_attempts
                   SET result_status='unknown',settled_at=statement_timestamp(),
                       error_code='VOICE-RUNTIME-RESTARTED'
                   WHERE settled_at IS NULL
                   RETURNING provider_attempt_id"""
            )
        ).fetchall()
        playback_rows = await (
            await transaction.execute(
                """UPDATE armi.live_voice_playback_attempts
                   SET result_status='unknown',settled_at=statement_timestamp(),
                       error_code='VOICE-RUNTIME-RESTARTED'
                   WHERE settled_at IS NULL
                   RETURNING playback_attempt_id"""
            )
        ).fetchall()
        turn_rows = await (
            await transaction.execute(
                """UPDATE armi.live_voice_turns
                   SET result_status='unknown',completed_at=statement_timestamp(),
                       error_code='VOICE-RUNTIME-RESTARTED'
                   WHERE completed_at IS NULL
                   RETURNING turn_id"""
            )
        ).fetchall()
        rows = await (
            await transaction.execute(
                """UPDATE armi.live_voice_sessions
                   SET state='failed',ended_at=statement_timestamp(),
                       error_code='VOICE-RUNTIME-RESTARTED'
                   WHERE ended_at IS NULL
                   RETURNING session_id"""
            )
        ).fetchall()
        return RecoveryContribution(
            self.owner_identity,
            findings=()
            if not rows
            else (
                RecoveryFindingContribution(
                    "live_voice_session",
                    RecoveryFindingDecision.TERMINAL,
                    "REC-LIVE-VOICE-SESSION-ENDED",
                ),
            ),
            metrics=(
                RecoveryMetricContribution(
                    "live_voice.ended_provider_attempt_count", len(provider_rows)
                ),
                RecoveryMetricContribution(
                    "live_voice.ended_playback_attempt_count", len(playback_rows)
                ),
                RecoveryMetricContribution("live_voice.ended_turn_count", len(turn_rows)),
                RecoveryMetricContribution("live_voice.ended_session_count", len(rows)),
            ),
        )


__all__ = ("LiveVoiceRecoveryParticipant",)
