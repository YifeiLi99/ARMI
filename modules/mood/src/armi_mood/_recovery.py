"""Mood-owned startup recovery contribution."""

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

from .api import MoodReadPort


class MoodRecoveryParticipant:
    owner_identity = RecoveryOwnerIdentity("mood")
    work_scopes: tuple[tuple[str, str], ...] = ()

    def __init__(self, read: MoodReadPort) -> None:
        self._read = read

    async def recover(
        self,
        transaction: PostgreSQLTransaction,
        scope: RecoveryScope,
        work: tuple[RecoveryWorkSnapshot, ...],
    ) -> RecoveryContribution:
        del work
        count = await self._read.current_head_count(
            transaction, subject_id=scope.subject_id
        )
        return RecoveryContribution(
            self.owner_identity,
            findings=()
            if count == 1
            else (
                RecoveryFindingContribution(
                    "mood", RecoveryFindingDecision.BLOCKED, "REC-MOOD-INVALID"
                ),
            ),
            metrics=(RecoveryMetricContribution("mood.current_head_count", count),),
        )
