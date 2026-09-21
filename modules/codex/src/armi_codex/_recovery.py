"""Codex-owned startup recovery contribution."""

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


class CodexRecoveryParticipant:
    owner_identity = RecoveryOwnerIdentity("codex")
    work_scopes: tuple[tuple[str, str], ...] = ()

    async def recover(
        self,
        transaction: PostgreSQLTransaction,
        scope: RecoveryScope,
        work: tuple[RecoveryWorkSnapshot, ...],
    ) -> RecoveryContribution:
        del scope, work
        row = await (
            await transaction.execute("""
            SELECT count(*) FROM armi.codex_task_sources AS verification
            WHERE verification.execution_status NOT IN (
                'verified', 'failed', 'unknown', 'cancelled'
            )
        """)
        ).fetchone()
        invalid = int(row[0]) if row else 0
        return RecoveryContribution(
            self.owner_identity,
            findings=()
            if invalid == 0
            else (
                RecoveryFindingContribution(
                    "codex_result", RecoveryFindingDecision.BLOCKED, "REC-CODEX-INVALID"
                ),
            ),
            metrics=(
                RecoveryMetricContribution("codex.invalid_result_count", invalid),
            ),
        )
