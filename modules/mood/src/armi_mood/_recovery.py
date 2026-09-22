"""Mood-owned startup recovery contribution."""

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

from .api import MoodReadPort


class MoodRecoveryParticipant:
    owner_identity = RecoveryOwnerIdentity("mood")
    work_scopes = (("cognitive_episode", "mood.evaluate"),)

    def __init__(self, read: MoodReadPort) -> None:
        self._read = read

    async def recover(
        self,
        transaction: PostgreSQLTransaction,
        scope: RecoveryScope,
        work: tuple[RecoveryWorkSnapshot, ...],
    ) -> RecoveryContribution:
        reconciliation = OwnerReconciliationContext(
            transaction, self.owner_identity, work
        )
        for item in work:
            if item.status in {"ready", "leased"}:
                await reconciliation.cancel(
                    item.work_id, reason_code="REC-MOOD-INTERRUPTED"
                )
        await transaction.execute(
            """UPDATE armi.mood_assessments SET status='interrupted',
                   error_code='MOOD-RUNTIME-INTERRUPTED',completed_at=statement_timestamp()
               WHERE subject_id=%s AND status='running'""",
            (scope.subject_id,),
        )
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
