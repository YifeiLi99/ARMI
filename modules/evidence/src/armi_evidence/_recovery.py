"""Evidence-owned startup recovery contribution."""

from armi_runtime_foundation import (
    PostgreSQLTransaction,
    RecoveryContribution,
    RecoveryMetricContribution,
    RecoveryOwnerIdentity,
    RecoveryScope,
    RecoveryWorkSnapshot,
)


class EvidenceRecoveryParticipant:
    owner_identity = RecoveryOwnerIdentity("evidence")
    work_scopes: tuple[tuple[str, str], ...] = ()

    async def recover(
        self,
        transaction: PostgreSQLTransaction,
        scope: RecoveryScope,
        work: tuple[RecoveryWorkSnapshot, ...],
    ) -> RecoveryContribution:
        del work
        row = await (
            await transaction.execute(
                "SELECT count(*) FROM armi.external_evidence WHERE subject_id=%s",
                (scope.subject_id,),
            )
        ).fetchone()
        return RecoveryContribution(
            self.owner_identity,
            metrics=(
                RecoveryMetricContribution(
                    "evidence.fact_count", int(row[0]) if row else 0
                ),
            ),
        )
