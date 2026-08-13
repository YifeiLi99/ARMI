"""Perception-owned startup recovery contribution."""

from armi_runtime_foundation import (
    PostgreSQLTransaction,
    RecoveryContribution,
    RecoveryFindingContribution,
    RecoveryFindingDecision,
    RecoveryMetricContribution,
    RecoveryOwnerIdentity,
    RecoveryScope,
    RecoveryWorkCommand,
    RecoveryWorkCommandKind,
    RecoveryWorkSnapshot,
)


class PerceptionRecoveryParticipant:
    owner_identity = RecoveryOwnerIdentity("perception")
    work_scopes = (("external_message", "external.content.recognize"),)

    async def recover(
        self,
        transaction: PostgreSQLTransaction,
        scope: RecoveryScope,
        work: tuple[RecoveryWorkSnapshot, ...],
    ) -> RecoveryContribution:
        del scope
        rows = await (
            await transaction.execute("""
            UPDATE armi.external_content_recognition_attempts
            SET dispatch_status='settled', result_status='unknown',
                error_code='RECOGNITION-OUTCOME-UNKNOWN', settled_at=statement_timestamp()
            WHERE dispatch_status='dispatched' RETURNING work_id
        """)
        ).fetchall()
        by_id = {item.work_id: item for item in work}
        commands = tuple(
            RecoveryWorkCommand(
                RecoveryWorkCommandKind.FAIL,
                item.work_id,
                item.work_kind,
                item.owner_kind,
                item.owner_ref,
                "REC-PERCEPTION-OUTCOME-UNKNOWN",
            )
            for row in rows
            if (item := by_id.get(row[0])) is not None
            and item.status in {"ready", "leased"}
        )
        return RecoveryContribution(
            self.owner_identity,
            findings=()
            if not rows
            else (
                RecoveryFindingContribution(
                    "recognition_attempt",
                    RecoveryFindingDecision.BLOCKED,
                    "REC-PERCEPTION-OUTCOME-UNKNOWN",
                ),
            ),
            metrics=(
                RecoveryMetricContribution(
                    "perception.unknown_attempt_count", len(rows)
                ),
            ),
            work_commands=commands,
        )
