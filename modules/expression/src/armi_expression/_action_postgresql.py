"""Owner-only PostgreSQL reads and links for the action lifecycle."""

from __future__ import annotations

from uuid import UUID

from armi_runtime_foundation import PostgreSQLTransaction

from .api import (
    ExpressionIntentReadPort,
    ExpressionIntentSnapshot,
    ExpressionOperationSnapshot,
)


class PostgreSQLExpressionActionOwner:
    __slots__ = ("_intents",)

    def __init__(self, intents: ExpressionIntentReadPort) -> None:
        self._intents = intents

    async def intent_snapshot(
        self, transaction: PostgreSQLTransaction, *, action_intent_id: UUID
    ) -> ExpressionIntentSnapshot:
        return await self._intents.intent_snapshot(
            transaction, action_intent_id=action_intent_id
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
                SELECT operation_ref, action_intent_id, dialogue_decision_id,
                       NULL, decision_kind, reason_class
                FROM armi.dialogue_decisions
                WHERE operation_ref=%s
                LIMIT 1
                """,
                (operation_ref,),
            )
        ).fetchone()
        intent = await self._intents.operation_snapshot(
            transaction, operation_ref=operation_ref
        )
        if row is None:
            return intent
        return ExpressionOperationSnapshot(
            operation_ref=intent.operation_ref if intent is not None else row[0],
            intent_id=intent.intent_id if intent is not None else row[1],
            dialogue_decision_id=row[2],
            action_kind=intent.action_kind if intent is not None else None,
            decision_kind=str(row[4]) if row[4] is not None else None,
            reason_code=str(row[5]) if row[5] is not None else None,
        )

    async def delegation_for_commit(
        self,
        transaction: PostgreSQLTransaction,
        *,
        subject_commit_id: UUID,
    ) -> ExpressionIntentSnapshot | None:
        return await self._intents.delegation_for_commit(
            transaction, subject_commit_id=subject_commit_id
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
