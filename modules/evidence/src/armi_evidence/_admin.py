"""Fixed Admin operations owned by Evidence."""

from typing import cast
from uuid import UUID

from armi_runtime_foundation import PostgreSQLAdminTransaction

from .api import EvidenceAdminSnapshot


class PostgreSQLEvidenceAdmin:
    __slots__ = ()

    def snapshot_for_interaction(
        self, transaction: PostgreSQLAdminTransaction, *, interaction_id: UUID
    ) -> EvidenceAdminSnapshot | None:
        row = transaction.execute(
            "SELECT evidence_id,interaction_id,artifact_id FROM armi.external_evidence "
            "WHERE interaction_id=%s AND source_kind='creator_input'",
            (interaction_id,),
        ).fetchone()
        return (
            None
            if row is None
            else EvidenceAdminSnapshot(
                cast(UUID, row[0]), cast(UUID, row[1]), cast(UUID, row[2])
            )
        )

    def delete(
        self, transaction: PostgreSQLAdminTransaction, *, evidence_id: UUID
    ) -> None:
        transaction.execute(
            "DELETE FROM armi.external_evidence WHERE evidence_id=%s", (evidence_id,)
        )

    def artifact_reference_count(
        self,
        transaction: PostgreSQLAdminTransaction,
        *,
        artifact_id: UUID,
        excluded_evidence_id: UUID | None = None,
    ) -> int:
        row = transaction.execute(
            "SELECT count(*) FROM armi.external_evidence WHERE artifact_id=%s AND (%s IS NULL OR evidence_id<>%s)",
            (artifact_id, excluded_evidence_id, excluded_evidence_id),
        ).fetchone()
        return 0 if row is None else int(cast(int, row[0]))


__all__ = ("PostgreSQLEvidenceAdmin",)
