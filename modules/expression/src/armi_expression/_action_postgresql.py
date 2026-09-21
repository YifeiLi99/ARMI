"""Owner-only PostgreSQL reads and links for the action lifecycle."""

from __future__ import annotations

from uuid import UUID

from armi_kernel.contracts import Digest
from armi_runtime_foundation import PostgreSQLTransaction

from .api import (
    ExpressionIntentSnapshot,
    ExpressionOperationSnapshot,
    ResponseViolation,
)


class PostgreSQLExpressionActionOwner:
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
                       intent.action_kind, intent.capability_kind,
                       intent.operation_class, intent.purpose,
                       intent.response_artifact_id, intent.response_digest,
                       intent.response_bytes, intent.codex_task_source_id,
                       intent.task_manifest_digest
                       , intent.created_at
                FROM armi.action_intents AS intent
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
            root_opportunity_id=row[2],
            subject_id=row[3],
            scene_id=row[4],
            context_party_id=row[5],
            action_kind=str(row[6]),
            capability_kind=str(row[7]),
            operation_class=str(row[8]),
            purpose=str(row[9]),
            response_artifact_id=row[10],
            response_digest=Digest(str(row[11])) if row[11] is not None else None,
            response_bytes=int(row[12]) if row[12] is not None else None,
            codex_task_source_id=row[13],
            task_manifest_digest=(
                Digest(str(row[14])) if row[14] is not None else None
            ),
            created_at=row[15],
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
                       dialogue.dialogue_decision_id,
                       intent.action_kind, dialogue.decision_kind,
                       dialogue.reason_class
                FROM (SELECT %s::uuid AS operation_ref) AS requested
                LEFT JOIN armi.action_intents AS intent
                  ON intent.operation_ref=requested.operation_ref
                  OR intent.root_opportunity_id=requested.operation_ref
                LEFT JOIN armi.dialogue_decisions AS dialogue
                  ON dialogue.operation_ref=requested.operation_ref
                WHERE intent.operation_ref IS NOT NULL
                   OR dialogue.operation_ref IS NOT NULL
                ORDER BY (intent.action_kind='party_response') DESC NULLS LAST,
                         intent.created_at DESC,intent.action_intent_id DESC
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
                FROM armi.action_intents AS intent
                WHERE intent.subject_commit_id=%s
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
            WHERE action_intent_id=%s
              AND (effect_id IS NULL OR effect_id=%s)
            """,
            (effect_id, action_intent_id, effect_id),
        )


__all__ = ("PostgreSQLExpressionActionOwner",)
