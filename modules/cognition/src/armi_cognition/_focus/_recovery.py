"""Focus-owned startup recovery contribution."""

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

from .api import FocusReadPort


class FocusRecoveryParticipant:
    owner_identity = RecoveryOwnerIdentity("cognition")
    work_scopes: tuple[tuple[str, str], ...] = ()

    def __init__(self, read: FocusReadPort) -> None:
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
                    "focus",
                    RecoveryFindingDecision.BLOCKED,
                    "REC-FOCUS-INVALID",
                ),
            ),
            metrics=(
                RecoveryMetricContribution("cognition.focus_current_head_count", count),
            ),
        )
