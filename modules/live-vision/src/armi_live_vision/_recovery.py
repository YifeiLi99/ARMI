"""Terminate interrupted visual sessions; dispatched work is never guessed."""

from uuid import UUID

from armi_perception.api import VisualRecognitionAttemptPort
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


class LiveVisionRecoveryParticipant:
    owner_identity = RecoveryOwnerIdentity("live-vision")
    work_scopes = (
        ("live_vision_observation", "live.vision.capture"),
        ("live_vision_observation", "live.vision.observe"),
    )

    def __init__(self, attempts: VisualRecognitionAttemptPort) -> None:
        self._attempts = attempts

    async def _end_conversations(
        self,
        transaction: PostgreSQLTransaction,
        work: tuple[RecoveryWorkSnapshot, ...],
    ) -> set[UUID]:
        rows = await (
            await transaction.execute(
                """UPDATE armi.live_vision_observations
                   SET status=CASE WHEN status IN ('capturing','recognizing')
                         THEN 'unknown' ELSE 'failed' END,
                       error_code='VISION-RUNTIME-INTERRUPTED',
                       settled_at=statement_timestamp()
                   WHERE origin_kind='subject' AND origin_scene_id IS NOT NULL
                     AND status IN ('capture_pending','capturing','registered','recognizing')
                   RETURNING observation_id"""
            )
        ).fetchall()
        observation_ids: set[UUID] = {row[0] for row in rows}
        await self._attempts.settle_interrupted(
            transaction,
            observation_ids=tuple(observation_ids),
            error_code="VISION-RUNTIME-INTERRUPTED",
        )
        reconciliation = OwnerReconciliationContext(
            transaction, self.owner_identity, work
        )
        cancelled: set[UUID] = set()
        for item in work:
            if item.owner_ref in observation_ids and item.status in {"ready", "leased"}:
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
        reconciliation = OwnerReconciliationContext(
            transaction, self.owner_identity, work
        )
        rows = await (
            await transaction.execute(
                """UPDATE armi.live_vision_sessions SET state='failed',ended_at=statement_timestamp(),
               error_code='VISION-RUNTIME-RESTARTED' WHERE ended_at IS NULL RETURNING session_id"""
            )
        ).fetchall()
        observation_rows = await (
            await transaction.execute(
                """UPDATE armi.live_vision_observations
                   SET status='unknown',error_code='VISION-OUTCOME-UNKNOWN',
                       settled_at=statement_timestamp()
                   WHERE status IN ('capturing','recognizing') RETURNING observation_id"""
            )
        ).fetchall()
        unknown_ids = {str(row[0]) for row in observation_rows}
        for item in work:
            if (
                str(item.owner_ref) not in unknown_ids
                or not item.reconciliation_required
            ):
                continue
            await reconciliation.complete(
                item.work_id,
                result_kind="live_vision_observation",
                result_ref=item.owner_ref,
            )
        return RecoveryContribution(
            self.owner_identity,
            findings=()
            if not rows and not observation_rows
            else (
                RecoveryFindingContribution(
                    "live_vision_runtime_state",
                    RecoveryFindingDecision.TERMINAL,
                    "REC-LIVE-VISION-SESSION-ENDED",
                ),
            ),
            metrics=(
                RecoveryMetricContribution(
                    "live_vision.ended_session_count", len(rows)
                ),
                RecoveryMetricContribution(
                    "live_vision.unknown_observation_count", len(observation_rows)
                ),
            ),
        )


__all__ = ("LiveVisionRecoveryParticipant",)
