"""Perception-owned startup recovery contribution."""

from uuid import UUID

from armi_interaction.api import InteractionPerceptionPort
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

    def __init__(self, interaction: InteractionPerceptionPort) -> None:
        self._interaction = interaction

    async def _end_conversations(
        self,
        transaction: PostgreSQLTransaction,
        work: tuple[RecoveryWorkSnapshot, ...],
    ) -> set[UUID]:
        input_ids = await self._interaction.creator_input_ids(
            transaction,
            tuple(
                item.owner_ref for item in work if item.status in {"ready", "leased"}
            ),
        )
        await transaction.execute(
            """UPDATE armi.external_content_recognition_attempts
               SET dispatch_status='settled',result_status='unknown',
                   error_code='RECOGNITION-RUNTIME-INTERRUPTED',settled_at=statement_timestamp()
               WHERE interaction_id=ANY(%s::uuid[]) AND dispatch_status='dispatched'""",
            (list(input_ids),),
        )
        reconciliation = OwnerReconciliationContext(
            transaction, self.owner_identity, work
        )
        cancelled: set[UUID] = set()
        for item in work:
            if item.owner_ref in input_ids and item.status in {"ready", "leased"}:
                await reconciliation.cancel(
                    item.work_id, reason_code="REC-CONVERSATION-INTERRUPTED"
                )
                cancelled.add(item.work_id)
        return cancelled

    async def end_conversations(
        self,
        transaction: PostgreSQLTransaction,
        scope: RecoveryScope,
        work: tuple[RecoveryWorkSnapshot, ...],
    ) -> None:
        await self._end_conversations(transaction, work)

    async def recover(
        self,
        transaction: PostgreSQLTransaction,
        scope: RecoveryScope,
        work: tuple[RecoveryWorkSnapshot, ...],
    ) -> RecoveryContribution:
        del scope
        cancelled = await self._end_conversations(transaction, work)
        work = tuple(item for item in work if item.work_id not in cancelled)
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
