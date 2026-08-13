"""PostgreSQL birth participant for Interaction-owned facts."""

from __future__ import annotations

from uuid import UUID, uuid7

from armi_runtime_foundation import PostgreSQLAdminTransaction, PostgreSQLTransaction

from .api import InteractionBirthContinuity


class PostgreSQLInteractionBirth:
    def continuity(
        self,
        transaction: PostgreSQLAdminTransaction,
        *,
        subject_id: UUID | None,
    ) -> InteractionBirthContinuity:
        if subject_id is None:
            row = transaction.execute(
                """SELECT
                   (SELECT count(*) FROM armi.parties),
                   (SELECT count(*) FROM armi.interaction_scenes),
                   (SELECT count(*) FROM armi.scene_timeline_items)"""
            ).fetchone()
        else:
            row = transaction.execute(
                """SELECT
                   (SELECT count(*) FROM armi.parties
                    WHERE represented_subject_id=%s
                       OR creator_role='unique_primary_creator'),
                   (SELECT count(*) FROM armi.interaction_scenes
                    WHERE subject_id=%s AND scene_key='default'
                      AND scene_kind='creator_dialogue' AND audience_scope='creator'
                      AND current_status='open' AND closed_at IS NULL),
                   (SELECT count(*) FROM armi.scene_timeline_items AS item
                    JOIN armi.interaction_scenes AS scene
                      ON scene.scene_id=item.scene_id
                    WHERE scene.subject_id=%s)""",
                (subject_id, subject_id, subject_id),
            ).fetchone()
        if row is None:
            return InteractionBirthContinuity(-1, -1, -1)
        return InteractionBirthContinuity(*(int(str(value)) for value in row))

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
