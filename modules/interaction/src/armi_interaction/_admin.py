"""Fixed Admin operations owned by Interaction."""

from typing import cast
from uuid import UUID

from armi_runtime_foundation import PostgreSQLAdminTransaction

from .api import InteractionAdminInputSnapshot, InteractionAdminNotificationSnapshot


class PostgreSQLInteractionAdmin:
    __slots__ = ()

    def notification(
        self,
        transaction: PostgreSQLAdminTransaction,
        *,
        notification_id: UUID,
    ) -> InteractionAdminNotificationSnapshot | None:
        row = transaction.execute(
            """SELECT notification_id,interaction_id,operation_id,payload_artifact_id,
                      failure_code,send_unknown FROM armi.system_notifications
               WHERE notification_id=%s""",
            (notification_id,),
        ).fetchone()
        return (
            None
            if row is None
            else InteractionAdminNotificationSnapshot(
                cast(UUID, row[0]),
                cast(UUID, row[1]),
                cast(UUID | None, row[2]),
                cast(UUID, row[3]),
                str(row[4]),
                bool(row[5]),
            )
        )

    def notification_for_input(
        self,
        transaction: PostgreSQLAdminTransaction,
        *,
        interaction_id: UUID,
    ) -> UUID | None:
        row = transaction.execute(
            "SELECT notification_id FROM armi.system_notifications WHERE interaction_id=%s",
            (interaction_id,),
        ).fetchone()
        return None if row is None else cast(UUID, row[0])

    def content_parties(
        self, transaction: PostgreSQLAdminTransaction, *, subject_id: UUID
    ) -> tuple[UUID, UUID]:
        rows = transaction.execute(
            "SELECT party_id,party_kind FROM armi.parties WHERE status='active' AND "
            "((party_kind='subject' AND represented_subject_id=%s) OR (party_kind='creator' AND creator_role='unique_primary_creator'))",
            (subject_id,),
        ).fetchall()
        parties = {str(row[1]): cast(UUID, row[0]) for row in rows}
        if set(parties) != {"subject", "creator"} or len(rows) != 2:
            raise ValueError("ADMIN-CONTENT-PARTY-IDENTITY")
        return parties["subject"], parties["creator"]

    def content_party_kind(
        self, transaction: PostgreSQLAdminTransaction, *, party_id: UUID
    ) -> str | None:
        row = transaction.execute(
            "SELECT party_kind FROM armi.parties WHERE party_id=%s AND status='active'",
            (party_id,),
        ).fetchone()
        return None if row is None else str(row[0])

    def scene_links(
        self, transaction: PostgreSQLAdminTransaction, *, scene_id: UUID
    ) -> tuple[UUID | None, tuple[UUID, ...]]:
        row = transaction.execute(
            "SELECT subject_id FROM armi.interaction_scenes WHERE scene_id=%s",
            (scene_id,),
        ).fetchone()
        inputs = transaction.execute(
            "SELECT interaction_id FROM armi.party_input_interactions WHERE scene_id=%s ORDER BY interaction_id LIMIT 201",
            (scene_id,),
        ).fetchall()
        return (
            None if row is None else cast(UUID, row[0]),
            tuple(cast(UUID, item[0]) for item in inputs),
        )

    def subject_scenes(
        self, transaction: PostgreSQLAdminTransaction, *, subject_id: UUID
    ) -> tuple[UUID, ...]:
        rows = transaction.execute(
            "SELECT scene_id FROM armi.interaction_scenes WHERE subject_id=%s ORDER BY scene_id LIMIT 201",
            (subject_id,),
        ).fetchall()
        return tuple(cast(UUID, row[0]) for row in rows)

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
            "SELECT (SELECT count(*) FROM armi.external_message_parts "
            "WHERE raw_artifact_id=%s OR interpretation_artifact_id=%s "
            "OR recognition_request_artifact_id=%s OR recognition_response_artifact_id=%s) + "
            "(SELECT count(*) FROM armi.system_notifications WHERE payload_artifact_id=%s)",
            (artifact_id, artifact_id, artifact_id, artifact_id, artifact_id),
        ).fetchone()
        return 0 if row is None else int(cast(int, row[0]))


__all__ = ("PostgreSQLInteractionAdmin",)
