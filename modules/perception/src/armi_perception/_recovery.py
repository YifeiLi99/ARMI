"""Perception-owned startup recovery contribution."""

from uuid import UUID

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
        visual_rows = await (
            await transaction.execute("""UPDATE armi.visual_recognition_attempts
            SET status='unknown',error_code='VISION-OUTCOME-UNKNOWN',settled_at=statement_timestamp()
            WHERE status='dispatched' RETURNING visual_attempt_id""")
        ).fetchall()
        reconciliation = OwnerReconciliationContext(
            transaction, self.owner_identity, work
        )
        unknown_ids: set[UUID] = {row[0] for row in rows}
        for item in work:
            if not item.reconciliation_required:
                continue
            if item.work_id in unknown_ids:
                await reconciliation.complete(
                    item.work_id,
                    result_kind="external_message",
                    result_ref=item.owner_ref,
                )
            else:
                await reconciliation.fail(
                    item.work_id,
                    reason_code="REC-PERCEPTION-WORK-EXHAUSTED",
                )
        return RecoveryContribution(
            self.owner_identity,
            findings=()
            if not rows and not visual_rows
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
                RecoveryMetricContribution(
                    "perception.unknown_visual_attempt_count", len(visual_rows)
                ),
            ),
        )
