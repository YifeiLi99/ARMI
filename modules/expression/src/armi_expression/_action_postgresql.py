"""Owner-only PostgreSQL reads and links for the action lifecycle."""

from __future__ import annotations

from uuid import UUID

from armi_kernel.application import WorkRecord, WorkStatus
from armi_kernel.contracts import Digest
from armi_runtime_foundation import PostgreSQLTransaction

from .api import (
    ExpressionIntentSnapshot,
    ExpressionOperationSnapshot,
    ResponseAdmissionSnapshot,
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
                       revision.capability_request_id, intent.created_at
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
            capability_request_id=row[17],
            response_artifact_id=row[11],
            response_digest=Digest(str(row[12])) if row[12] is not None else None,
            response_bytes=int(row[13]) if row[13] is not None else None,
            codex_task_source_id=row[14],
            task_manifest_digest=(
                Digest(str(row[15])) if row[15] is not None else None
            ),
            validator_id=str(row[16]) if row[16] is not None else None,
            created_at=row[18],
        )

    async def settle_response_admission(
        self,
        transaction: PostgreSQLTransaction,
        *,
        work_id: UUID,
        action_intent_id: UUID | None,
        status: str,
        permission_grant_id: UUID | None,
        reason_code: str,
    ) -> UUID | None:
        if status not in {
            "accepted",
            "cancelled",
            "failed",
            "unauthorized",
            "unavailable",
        }:
            raise ResponseViolation("CON-RESPONSE-RESULT")
        if action_intent_id is None:
            row = await (
                await transaction.execute(
                    """UPDATE armi.response_admissions
                       SET status=%s,permission_grant_id=%s,reason_code=%s,
                           attempt_count=attempt_count+1,
                           settled_at=statement_timestamp()
                       WHERE work_id=%s AND status='pending'
                       RETURNING response_admission_id""",
                    (status, permission_grant_id, reason_code, work_id),
                )
            ).fetchone()
        else:
            row = await (
                await transaction.execute(
                    """UPDATE armi.response_admissions
                       SET status=%s,permission_grant_id=%s,reason_code=%s,
                           attempt_count=attempt_count+1,
                           settled_at=statement_timestamp()
                       WHERE work_id=%s AND action_intent_id=%s
                         AND status='pending'
                       RETURNING response_admission_id""",
                    (
                        status,
                        permission_grant_id,
                        reason_code,
                        work_id,
                        action_intent_id,
                    ),
                )
            ).fetchone()
        return None if row is None else row[0]

    async def response_admission_by_intent(
        self,
        transaction: PostgreSQLTransaction,
        *,
        action_intent_id: UUID,
    ) -> ResponseAdmissionSnapshot | None:
        row = await (
            await transaction.execute(
                """SELECT response_admission_id,status,reason_code
                   FROM armi.response_admissions WHERE action_intent_id=%s""",
                (action_intent_id,),
            )
        ).fetchone()
        if row is None:
            return None
        return ResponseAdmissionSnapshot(row[0], str(row[1]), row[2])

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
                       , revision.capability_request_id, intent.created_at
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
            capability_request_id=row[17],
            response_artifact_id=row[11],
            response_digest=Digest(str(row[12])) if row[12] is not None else None,
            response_bytes=int(row[13]) if row[13] is not None else None,
            codex_task_source_id=row[14],
            task_manifest_digest=(
                Digest(str(row[15])) if row[15] is not None else None
            ),
            validator_id=str(row[16]) if row[16] is not None else None,
            created_at=row[18],
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
                SELECT COALESCE(intent.operation_ref, dialogue.operation_ref),
                       COALESCE(intent.action_intent_id, dialogue.action_intent_id),
                       intent.current_revision_id, dialogue.dialogue_decision_id,
                       intent.action_kind, dialogue.decision_kind,
                       dialogue.reason_class, revision.capability_request_id
                FROM (SELECT %s::uuid AS operation_ref) AS requested
                LEFT JOIN armi.action_intents AS intent
                  ON intent.operation_ref=requested.operation_ref
                LEFT JOIN armi.dialogue_decisions AS dialogue
                  ON dialogue.operation_ref=requested.operation_ref
                LEFT JOIN armi.action_intent_revisions AS revision
                  ON revision.action_intent_revision_id=intent.current_revision_id
                WHERE intent.operation_ref IS NOT NULL
                   OR dialogue.operation_ref IS NOT NULL
                LIMIT 1
                """,
                (operation_ref,),
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
            capability_request_id=row[7],
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
                     AND action_kind='party_response'
                     AND purpose='respond_to_creator'
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
