"""Owner-only PostgreSQL reads and links for the action lifecycle."""

from __future__ import annotations

from uuid import UUID

from armi_kernel.application import WorkRecord, WorkStatus
from armi_kernel.contracts import Digest
from armi_runtime_foundation import PostgreSQLTransaction

from .api import (
    ExpressionIntentSnapshot,
    ExpressionOperationSnapshot,
    ResponseViolation,
)


class PostgreSQLExpressionActionOwner:
    __slots__ = ()

    async def response_admission_snapshot(
        self,
        transaction: PostgreSQLTransaction,
        *,
        work: WorkRecord,
    ) -> ExpressionIntentSnapshot:
        if (
            work.status is not WorkStatus.LEASED
            or work.lease is None
            or work.draft.work_kind != "cognition.response.admit"
            or work.draft.owner.kind != "action_intent"
        ):
            raise ResponseViolation("RESPONSE-WORK-STALE")
        row = await (
            await transaction.execute(
                """
                SELECT intent.operation_ref, intent.action_intent_id,
                       revision.action_intent_revision_id,
                       intent.root_opportunity_id, intent.subject_id,
                       intent.scene_id, intent.context_party_id,
                       intent.action_kind, revision.capability_kind,
                       revision.operation_class, revision.purpose,
                       revision.response_artifact_id, revision.response_digest,
                       revision.response_bytes, revision.codex_task_source_id,
                       revision.task_manifest_digest, revision.validator_id,
                       intent.created_at
                FROM armi.action_intents AS intent
                JOIN armi.action_intent_revisions AS revision
                  ON revision.action_intent_revision_id=intent.current_revision_id
                 AND revision.action_intent_id=intent.action_intent_id
                WHERE intent.action_intent_id=%s
                FOR UPDATE OF intent
                """,
                (work.draft.owner.reference,),
            )
        ).fetchone()
        if row is None:
            raise ResponseViolation("RESPONSE-WORK-STALE")
        return ExpressionIntentSnapshot(
            operation_ref=row[0],
            action_intent_id=row[1],
            action_intent_revision_id=row[2],
            root_opportunity_id=row[3],
            subject_id=row[4],
            scene_id=row[5],
            context_party_id=row[6],
            action_kind=str(row[7]),
            capability_kind=str(row[8]),
            operation_class=str(row[9]),
            purpose=str(row[10]),
            response_artifact_id=row[11],
            response_digest=Digest(str(row[12])) if row[12] is not None else None,
            response_bytes=int(row[13]) if row[13] is not None else None,
            codex_task_source_id=row[14],
            task_manifest_digest=(
                Digest(str(row[15])) if row[15] is not None else None
            ),
            validator_id=str(row[16]) if row[16] is not None else None,
            created_at=row[17],
        )

    async def intent_snapshot(
        self,
        transaction: PostgreSQLTransaction,
        *,
        action_intent_id: UUID,
    ) -> ExpressionIntentSnapshot:
        row = await (
            await transaction.execute(
                """
                SELECT intent.operation_ref, intent.action_intent_id,
                       revision.action_intent_revision_id,
                       intent.root_opportunity_id, intent.subject_id,
                       intent.scene_id, intent.context_party_id,
                       intent.action_kind, revision.capability_kind,
                       revision.operation_class, revision.purpose,
                       revision.response_artifact_id, revision.response_digest,
                       revision.response_bytes, revision.codex_task_source_id,
                       revision.task_manifest_digest, revision.validator_id
                       , intent.created_at
                FROM armi.action_intents AS intent
                JOIN armi.action_intent_revisions AS revision
                  ON revision.action_intent_revision_id=intent.current_revision_id
                 AND revision.action_intent_id=intent.action_intent_id
                WHERE intent.action_intent_id=%s
                """,
                (action_intent_id,),
            )
        ).fetchone()
        if row is None:
            raise ResponseViolation("RESPONSE-WORK-STALE")
        return ExpressionIntentSnapshot(
            operation_ref=row[0],
            action_intent_id=row[1],
            action_intent_revision_id=row[2],
            root_opportunity_id=row[3],
            subject_id=row[4],
            scene_id=row[5],
            context_party_id=row[6],
            action_kind=str(row[7]),
            capability_kind=str(row[8]),
            operation_class=str(row[9]),
            purpose=str(row[10]),
            response_artifact_id=row[11],
            response_digest=Digest(str(row[12])) if row[12] is not None else None,
            response_bytes=int(row[13]) if row[13] is not None else None,
            codex_task_source_id=row[14],
            task_manifest_digest=(
                Digest(str(row[15])) if row[15] is not None else None
            ),
            validator_id=str(row[16]) if row[16] is not None else None,
            created_at=row[17],
        )

    async def operation_snapshot(
        self,
        transaction: PostgreSQLTransaction,
        *,
        operation_ref: UUID,
    ) -> ExpressionOperationSnapshot | None:
        row = await (
            await transaction.execute(
                """
                SELECT operation_ref, action_intent_id, current_revision_id,
                       NULL::uuid AS dialogue_decision_id,
                       action_kind, NULL::text, NULL::text
                FROM armi.action_intents WHERE operation_ref=%s
                UNION ALL
                SELECT operation_ref, action_intent_id, NULL::uuid,
                       dialogue_decision_id, NULL::text, decision_kind,
                       reason_class
                FROM armi.dialogue_decisions WHERE operation_ref=%s
                ORDER BY dialogue_decision_id NULLS LAST
                LIMIT 1
                """,
                (operation_ref, operation_ref),
            )
        ).fetchone()
        if row is None:
            return None
        return ExpressionOperationSnapshot(
            operation_ref=row[0],
            intent_id=row[1],
            intent_revision_id=row[2],
            dialogue_decision_id=row[3],
            action_kind=str(row[4]) if row[4] is not None else None,
            decision_kind=str(row[5]) if row[5] is not None else None,
            reason_code=str(row[6]) if row[6] is not None else None,
        )

    async def revision_snapshot(
        self,
        transaction: PostgreSQLTransaction,
        *,
        action_intent_revision_id: UUID,
    ) -> ExpressionIntentSnapshot:
        row = await (
            await transaction.execute(
                """SELECT action_intent_id FROM armi.action_intent_revisions
                   WHERE action_intent_revision_id=%s""",
                (action_intent_revision_id,),
            )
        ).fetchone()
        if row is None:
            raise ResponseViolation("RESPONSE-WORK-STALE")
        return await self.intent_snapshot(transaction, action_intent_id=row[0])

    async def delegation_for_commit(
        self,
        transaction: PostgreSQLTransaction,
        *,
        subject_commit_id: UUID,
    ) -> ExpressionIntentSnapshot | None:
        row = await (
            await transaction.execute(
                """
                SELECT intent.action_intent_id
                FROM armi.action_intents AS intent
                JOIN armi.action_intent_revisions AS revision
                  ON revision.action_intent_revision_id=intent.current_revision_id
                 AND revision.action_intent_id=intent.action_intent_id
                WHERE revision.subject_commit_id=%s
                  AND intent.action_kind='codex_delegation'
                """,
                (subject_commit_id,),
            )
        ).fetchone()
        if row is None:
            return None
        return await self.intent_snapshot(
            transaction,
            action_intent_id=row[0],
        )

    async def link_effect(
        self,
        transaction: PostgreSQLTransaction,
        *,
        action_intent_id: UUID,
        effect_id: UUID,
    ) -> None:
        await transaction.execute(
            """
            UPDATE armi.dialogue_decisions
            SET effect_id=%s
            WHERE action_intent_id=%s AND decision_kind='reply'
              AND (effect_id IS NULL OR effect_id=%s)
            """,
            (effect_id, action_intent_id, effect_id),
        )

    async def outreach_intents(
        self,
        transaction: PostgreSQLTransaction,
        *,
        subject_id: UUID,
        scene_id: UUID,
        context_party_id: UUID,
    ) -> tuple[ExpressionIntentSnapshot, ...]:
        rows = await (
            await transaction.execute(
                """SELECT action_intent_id FROM armi.action_intents
                   WHERE subject_id=%s AND scene_id=%s AND context_party_id=%s
                     AND action_kind='creator_response'
                   ORDER BY created_at DESC""",
                (subject_id, scene_id, context_party_id),
            )
        ).fetchall()
        return tuple(
            [
                await self.intent_snapshot(transaction, action_intent_id=row[0])
                for row in rows
            ]
        )


__all__ = ("PostgreSQLExpressionActionOwner",)
