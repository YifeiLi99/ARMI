"""Owner-only PostgreSQL reads and links for the action lifecycle."""

from __future__ import annotations

from uuid import UUID

from armi_expression.api import (
    ExpressionIntentSnapshot,
    ExpressionOperationSnapshot,
    ResponseViolation,
)
from armi_kernel.contracts import Digest
from armi_runtime_foundation import PostgreSQLTransaction

from ._family import effect_family


class PostgreSQLEffectIntentRead:
    __slots__ = ()

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
                       intent.root_opportunity_id, intent.subject_id,
                       intent.scene_id, intent.context_party_id,
                       CASE WHEN intent.effect_kind='codex_delegation' THEN 'codex_delegation' ELSE 'party_response' END, intent.effect_kind,
                       CASE WHEN intent.effect_kind <> 'codex_delegation' THEN intent.payload_artifact_id END, CASE WHEN intent.effect_kind <> 'codex_delegation' THEN intent.payload_digest END,
                       CASE WHEN intent.effect_kind <> 'codex_delegation' THEN intent.payload_bytes END, intent.codex_task_source_id,
                       CASE WHEN intent.effect_kind='codex_delegation' THEN intent.payload_digest END
                       , intent.registered_at
                FROM armi.effects AS intent
                WHERE intent.action_intent_id=%s
                """,
                (action_intent_id,),
            )
        ).fetchone()
        if row is None:
            raise ResponseViolation("RESPONSE-WORK-STALE")
        family = effect_family(str(row[7]))
        return ExpressionIntentSnapshot(
            operation_ref=row[0],
            action_intent_id=row[1],
            root_opportunity_id=row[2],
            subject_id=row[3],
            scene_id=row[4],
            context_party_id=row[5],
            action_kind=str(row[6]),
            capability_kind=family.capability_kind,
            operation_class=family.operation_class,
            purpose=family.purpose,
            response_artifact_id=row[8],
            response_digest=Digest(str(row[9])) if row[9] is not None else None,
            response_bytes=int(row[10]) if row[10] is not None else None,
            codex_task_source_id=row[11],
            task_manifest_digest=(
                Digest(str(row[12])) if row[12] is not None else None
            ),
            created_at=row[13],
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
                SELECT intent.operation_ref, intent.action_intent_id,
                       NULL, CASE WHEN intent.effect_kind='codex_delegation'
                         THEN 'codex_delegation' ELSE 'party_response' END,
                       NULL, NULL
                FROM armi.effects AS intent
                WHERE intent.operation_ref=%s OR intent.root_opportunity_id=%s
                ORDER BY (intent.effect_kind <> 'codex_delegation') DESC,
                         intent.registered_at DESC,intent.action_intent_id DESC
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
            dialogue_decision_id=row[2],
            action_kind=str(row[3]) if row[3] is not None else None,
            decision_kind=str(row[4]) if row[4] is not None else None,
            reason_code=str(row[5]) if row[5] is not None else None,
        )

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
                FROM armi.effects AS intent
                WHERE intent.subject_commit_id=%s
                  AND intent.effect_kind='codex_delegation'
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
