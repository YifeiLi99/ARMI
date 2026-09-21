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

    async def _end_interrupted_work(
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
        await self._interaction.interrupt_recognition(
            transaction,
            interaction_ids=input_ids,
            error_code="RECOGNITION-RUNTIME-INTERRUPTED",
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

    async def end_interrupted_work(
        self,
        transaction: PostgreSQLTransaction,
        scope: RecoveryScope,
        work: tuple[RecoveryWorkSnapshot, ...],
    ) -> None:
        await self._end_interrupted_work(transaction, work)

    async def recover(
        self,
        transaction: PostgreSQLTransaction,
        scope: RecoveryScope,
        work: tuple[RecoveryWorkSnapshot, ...],
    ) -> RecoveryContribution:
        del scope
        cancelled = await self._end_interrupted_work(transaction, work)
        work = tuple(item for item in work if item.work_id not in cancelled)
        unknown_ids = set(
            await self._interaction.interrupt_recognition(
                transaction,
                interaction_ids=None,
                error_code="RECOGNITION-OUTCOME-UNKNOWN",
            )
        )
        reconciliation = OwnerReconciliationContext(
            transaction, self.owner_identity, work
        )
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
            if not unknown_ids
            else (
                RecoveryFindingContribution(
                    "recognition_attempt",
                    RecoveryFindingDecision.BLOCKED,
                    "REC-PERCEPTION-OUTCOME-UNKNOWN",
                ),
            ),
            metrics=(
                RecoveryMetricContribution(
                    "perception.unknown_attempt_count", len(unknown_ids)
                ),
            ),
        )
