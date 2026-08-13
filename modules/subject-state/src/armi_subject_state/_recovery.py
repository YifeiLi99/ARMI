"""Subject-state-owned startup recovery contribution."""

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

from .api import SubjectStateReadPort


class SubjectStateRecoveryParticipant:
    owner_identity = RecoveryOwnerIdentity("subject-state")
    work_scopes: tuple[tuple[str, str], ...] = ()

    def __init__(self, read: SubjectStateReadPort) -> None:
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
            if count == 3
            else (
                RecoveryFindingContribution(
                    "subject_state",
                    RecoveryFindingDecision.BLOCKED,
                    "REC-SUBJECT-STATE-INVALID",
                ),
            ),
            metrics=(
                RecoveryMetricContribution("subject_state.current_head_count", count),
            ),
        )
