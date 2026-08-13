"""Fixed Admin operations owned by Interaction."""

from typing import cast
from uuid import UUID

from armi_runtime_foundation import PostgreSQLAdminTransaction

from .api import InteractionAdminInputSnapshot


class PostgreSQLInteractionAdmin:
    __slots__ = ()

    def input_snapshot(
        self, transaction: PostgreSQLAdminTransaction, *, interaction_id: UUID
    ) -> InteractionAdminInputSnapshot | None:
        row = transaction.execute(
            "SELECT interaction_id,subject_id FROM armi.party_input_interactions WHERE interaction_id=%s",
            (interaction_id,),
        ).fetchone()
        return (
            None
            if row is None
            else InteractionAdminInputSnapshot(cast(UUID, row[0]), cast(UUID, row[1]))
        )

    def delete_input_chain(
        self, transaction: PostgreSQLAdminTransaction, *, interaction_id: UUID
    ) -> None:
        transaction.execute(
            "DELETE FROM armi.scene_timeline_items WHERE source_kind='creator_input' AND source_ref=%s",
            (interaction_id,),
        )
        transaction.execute(
            "DELETE FROM armi.party_input_interactions WHERE interaction_id=%s",
            (interaction_id,),
        )

    def inspect_ids(
        self, transaction: PostgreSQLAdminTransaction, *, object_ids: tuple[UUID, ...]
    ) -> tuple[UUID, ...]:
        rows = transaction.execute(
            "SELECT scene_id FROM armi.interaction_scenes WHERE scene_id=ANY(%s::uuid[]) ORDER BY scene_id",
            (object_ids,),
        ).fetchall()
        return tuple(cast(UUID, row[0]) for row in rows)

    def artifact_reference_count(
        self, transaction: PostgreSQLAdminTransaction, *, artifact_id: UUID
    ) -> int:
        row = transaction.execute(
            "SELECT count(*) FROM armi.external_message_parts "
            "WHERE raw_artifact_id=%s OR interpretation_artifact_id=%s",
            (artifact_id, artifact_id),
        ).fetchone()
        return 0 if row is None else int(cast(int, row[0]))


__all__ = ("PostgreSQLInteractionAdmin",)
