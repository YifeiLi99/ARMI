"""Combine cognition decisions and effect intents through their owner ports."""

from __future__ import annotations

from uuid import UUID

from armi_runtime_foundation import PostgreSQLTransaction

from .api import (
    DialogueDecisionRecordPort,
    ExpressionIntentReadPort,
    ExpressionIntentSnapshot,
    ExpressionOperationSnapshot,
)


class PostgreSQLExpressionActionOwner:
    __slots__ = ("_decisions", "_intents")

    def __init__(
        self, intents: ExpressionIntentReadPort, decisions: DialogueDecisionRecordPort
    ) -> None:
        self._intents = intents
        self._decisions = decisions

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
        decision = await self._decisions.dialogue_operation(
            transaction, operation_ref=operation_ref
        )
        intent = await self._intents.operation_snapshot(
            transaction, operation_ref=operation_ref
        )
        if decision is None:
            return intent
        return ExpressionOperationSnapshot(
            operation_ref=intent.operation_ref
            if intent is not None
            else decision.operation_ref,
            intent_id=intent.intent_id if intent is not None else decision.intent_id,
            dialogue_decision_id=decision.dialogue_decision_id,
            action_kind=intent.action_kind if intent is not None else None,
            decision_kind=decision.decision_kind,
            reason_code=decision.reason_code,
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


__all__ = ("PostgreSQLExpressionActionOwner",)
