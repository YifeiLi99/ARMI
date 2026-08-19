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
                RecoveryMetricContribution("live_voice.ended_session_count", len(rows)),
            ),
        )


__all__ = ("LiveVoiceRecoveryParticipant",)
