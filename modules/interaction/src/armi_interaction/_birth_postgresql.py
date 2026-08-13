"""PostgreSQL birth participant for Interaction-owned facts."""

from __future__ import annotations

from uuid import UUID, uuid7

from armi_runtime_foundation import PostgreSQLTransaction


class PostgreSQLInteractionBirth:
    async def initialize(
        self,
        transaction: PostgreSQLTransaction,
        *,
        subject_id: UUID,
        creator_party_id: UUID,
    ) -> None:
        subject_party_id = uuid7()
        default_scene_id = uuid7()
        await transaction.execute(
            """
            INSERT INTO armi.parties (
                party_id, party_kind, represented_subject_id, creator_role)
            VALUES
                (%s, 'subject', %s, NULL),
                (%s, 'creator', NULL, 'unique_primary_creator')
            """,
            (subject_party_id, subject_id, creator_party_id),
        )
        await transaction.execute(
            """
            INSERT INTO armi.interaction_scenes (
                scene_id, subject_id, scene_key, scene_kind,
                primary_party_id, audience_scope, current_status)
            VALUES (
                %s, %s, 'default', 'creator_dialogue',
                %s, 'creator', 'open')
            """,
            (default_scene_id, subject_id, creator_party_id),
        )
        await transaction.execute(
            """
            INSERT INTO armi.scene_participants (
                scene_id, subject_id, party_id, participant_role)
            VALUES (%s, %s, %s, 'primary')
            """,
            (default_scene_id, subject_id, creator_party_id),
        )


__all__ = ("PostgreSQLInteractionBirth",)
