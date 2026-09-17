"""Mind-owned startup recovery contribution."""

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

from .api import MindReadPort


class MindRecoveryParticipant:
    owner_identity = RecoveryOwnerIdentity("mind")
    work_scopes: tuple[tuple[str, str], ...] = ()

    def __init__(self, read: MindReadPort) -> None:
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
        continuous = await self._read.history_is_continuous(
            transaction, subject_id=scope.subject_id
        )
        return RecoveryContribution(
            self.owner_identity,
            findings=()
            if count == 1 and continuous
            else (
                RecoveryFindingContribution(
                    "mind",
                    RecoveryFindingDecision.BLOCKED,
                    "REC-MIND-INVALID",
                ),
            ),
            metrics=(RecoveryMetricContribution("mind.current_head_count", count),),
        )
