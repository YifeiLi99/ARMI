"""Capability-owned startup recovery contribution."""

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


class CapabilityRecoveryParticipant:
    owner_identity = RecoveryOwnerIdentity("capability")
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
                """
            SELECT count(*) FILTER (WHERE current_status = 'pending'),
                   count(*) FILTER (
                       WHERE current_status <> 'pending' AND resolved_at IS NULL
                   )
            FROM armi.capability_requests WHERE subject_id=%s
        """,
                (scope.subject_id,),
            )
        ).fetchone()
        resumable, invalid = (0, 0) if row is None else (int(row[0]), int(row[1]))
        return RecoveryContribution(
            self.owner_identity,
            findings=()
            if invalid == 0
            else (
                RecoveryFindingContribution(
                    "capability_request",
                    RecoveryFindingDecision.BLOCKED,
                    "REC-CAPABILITY-INVALID",
                ),
            ),
            metrics=(
                RecoveryMetricContribution(
                    "capability.resumable_request_count", resumable
                ),
            ),
        )
