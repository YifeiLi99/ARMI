"""PostgreSQL lookup for the born Creator identity."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from armi_runtime_foundation import PostgreSQLTransaction

from .api import CreatorIdentityContext, InteractionOutreachScene


class PostgreSQLInteractionIdentity:
    async def outreach_scenes(
        self, transaction: PostgreSQLTransaction, *, subject_id: UUID
    ) -> tuple[InteractionOutreachScene, ...]:
        rows = await (
            await transaction.execute(
                """
                SELECT scene.scene_id, scene.primary_party_id, scene.scene_key,
                       latest.interaction_id, latest.received_at,
                       (SELECT max(occurred_at) FROM armi.scene_timeline_items
                        WHERE scene_id=scene.scene_id
                          AND source_kind IN ('creator_input','party_response'))
                FROM armi.interaction_scenes AS scene
                LEFT JOIN LATERAL (
                    SELECT interaction_id, received_at
                    FROM armi.party_input_interactions
                    WHERE subject_id=scene.subject_id AND scene_id=scene.scene_id
                      AND source_party_id=scene.primary_party_id
                    ORDER BY received_at DESC, interaction_id DESC LIMIT 1
                ) AS latest ON true
                WHERE scene.subject_id=%s AND scene.current_status='open'
                  AND scene.scene_kind='creator_dialogue'
                ORDER BY latest.received_at DESC NULLS LAST,
                         (scene.scene_key='default') DESC, scene.scene_id
                """,
                (subject_id,),
            )
        ).fetchall()
        return tuple(
            InteractionOutreachScene(
                row[0], row[1], str(row[2]), row[3], row[4], row[5]
            )
            for row in rows
        )

    async def input_after(
        self,
        transaction: PostgreSQLTransaction,
        *,
        scene_id: UUID,
        party_id: UUID,
        after: datetime,
    ) -> bool:
        row = await (
            await transaction.execute(
                """SELECT 1 FROM armi.party_input_interactions
                   WHERE scene_id=%s AND source_party_id=%s AND received_at>%s LIMIT 1""",
                (scene_id, party_id, after),
            )
        ).fetchone()
        return row is not None

    async def creator_party(
        self,
        transaction: PostgreSQLTransaction,
        *,
        creator_party_id: UUID,
    ) -> UUID | None:
        row = await (
            await transaction.execute(
                """
                SELECT party_id FROM armi.parties
                WHERE party_id = %s AND party_kind = 'creator'
                """,
                (creator_party_id,),
            )
        ).fetchone()
        return None if row is None else row[0]

    async def other_human_party(
        self,
        transaction: PostgreSQLTransaction,
        *,
        declared_identity_key: str,
    ) -> UUID | None:
        row = await (
            await transaction.execute(
                """
                SELECT party_id FROM armi.parties
                WHERE declared_identity_key = %s AND party_kind = 'other_human'
                """,
                (declared_identity_key,),
            )
        ).fetchone()
        return None if row is None else row[0]

    async def creator_context(
        self,
        transaction: PostgreSQLTransaction,
        *,
        subject_id: UUID,
    ) -> CreatorIdentityContext | None:
        rows = await (
            await transaction.execute(
                """
                SELECT creator.party_id, scene.scene_id, scene.scene_key
                FROM armi.parties AS creator
                JOIN armi.interaction_scenes AS scene
                  ON scene.primary_party_id = creator.party_id
                 AND scene.subject_id = %s
                 AND scene.scene_key = 'default'
                 AND scene.scene_kind = 'creator_dialogue'
                 AND scene.audience_scope = 'creator'
                 AND scene.current_status = 'open'
                 AND scene.closed_at IS NULL
                WHERE creator.party_kind = 'creator'
                  AND creator.creator_role = 'unique_primary_creator'
                  AND creator.status = 'active'
                """,
                (subject_id,),
            )
        ).fetchall()
        if (
            len(rows) != 1
            or type(rows[0][0]) is not UUID
            or type(rows[0][1]) is not UUID
            or rows[0][2] != "default"
        ):
            return None
        return CreatorIdentityContext(
            party_id=rows[0][0],
            scene_id=rows[0][1],
            default_scene_key=str(rows[0][2]),
        )


__all__ = ("PostgreSQLInteractionIdentity",)
