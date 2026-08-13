from typing import cast
from uuid import UUID

from armi_runtime_foundation import PostgreSQLAdminTransaction

from .api import ExpressionAdminSnapshot


class PostgreSQLExpressionAdmin:
    __slots__ = ()

    @staticmethod
    def _snapshot(row: tuple[object, ...] | None) -> ExpressionAdminSnapshot | None:
        return (
            None
            if row is None
            else ExpressionAdminSnapshot(
                cast(UUID, row[0]), cast(UUID, row[1]), cast(UUID, row[2])
            )
        )

    def operation(
        self, transaction: PostgreSQLAdminTransaction, *, operation_ref: UUID
    ) -> ExpressionAdminSnapshot | None:
        return self._snapshot(
            transaction.execute(
                "SELECT action_intent_id,operation_ref,root_opportunity_id FROM armi.action_intents WHERE operation_ref=%s OR root_opportunity_id=%s LIMIT 1",
                (operation_ref, operation_ref),
            ).fetchone()
        )

    def intent(
        self, transaction: PostgreSQLAdminTransaction, *, action_intent_id: UUID
    ) -> ExpressionAdminSnapshot | None:
        return self._snapshot(
            transaction.execute(
                "SELECT action_intent_id,operation_ref,root_opportunity_id FROM armi.action_intents WHERE action_intent_id=%s",
                (action_intent_id,),
            ).fetchone()
        )

    def inspect_ids(
        self, transaction: PostgreSQLAdminTransaction, *, object_ids: tuple[UUID, ...]
    ) -> tuple[UUID, ...]:
        rows = transaction.execute(
            "SELECT operation_ref FROM armi.action_intents WHERE operation_ref=ANY(%s::uuid[]) ORDER BY operation_ref",
            (object_ids,),
        ).fetchall()
        return tuple(cast(UUID, row[0]) for row in rows)

    def artifact_reference_count(
        self, transaction: PostgreSQLAdminTransaction, *, artifact_id: UUID
    ) -> int:
        row = transaction.execute(
            "SELECT count(*) FROM armi.action_intent_revisions WHERE response_artifact_id=%s",
            (artifact_id,),
        ).fetchone()
        return 0 if row is None else int(cast(int, row[0]))


__all__ = ("PostgreSQLExpressionAdmin",)
