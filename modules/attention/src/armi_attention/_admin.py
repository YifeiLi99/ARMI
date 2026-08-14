"""Fixed Admin operations owned by the Attention module."""

from typing import cast
from uuid import UUID

from armi_runtime_foundation import PostgreSQLAdminTransaction

from .api import OpportunityAdminSnapshot


class PostgreSQLOpportunityAdmin:
    __slots__ = ()

    def snapshot_for_evidence(
        self, transaction: PostgreSQLAdminTransaction, *, evidence_id: UUID
    ) -> OpportunityAdminSnapshot | None:
        row = transaction.execute(
            "SELECT opportunity_id,evidence_id,current_disposition FROM armi.opportunities WHERE evidence_id=%s",
            (evidence_id,),
        ).fetchone()
        return (
            None
            if row is None
            else OpportunityAdminSnapshot(
                cast(UUID, row[0]), cast(UUID, row[1]), str(row[2])
            )
        )

    def delete_open(
        self, transaction: PostgreSQLAdminTransaction, *, opportunity_id: UUID
    ) -> bool:
        return (
            transaction.execute(
                "DELETE FROM armi.opportunities WHERE opportunity_id=%s AND current_disposition='open'",
                (opportunity_id,),
            ).rowcount
            == 1
        )

    def inspect_ids(
        self, transaction: PostgreSQLAdminTransaction, *, object_ids: tuple[UUID, ...]
    ) -> tuple[UUID, ...]:
        rows = transaction.execute(
            "SELECT opportunity_id FROM armi.opportunities WHERE opportunity_id=ANY(%s::uuid[]) ORDER BY opportunity_id",
            (object_ids,),
        ).fetchall()
        return tuple(cast(UUID, row[0]) for row in rows)


__all__ = ("PostgreSQLOpportunityAdmin",)
