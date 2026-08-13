"""Interaction-owned scene context for the subject commit coordinator."""

from __future__ import annotations

from uuid import UUID, uuid7

from armi_runtime_foundation import PostgreSQLTransaction

from .api import InteractionSubjectCommitSnapshot, SceneQueryViolation


class PostgreSQLInteractionSubjectCommit:
    __slots__ = ()

    async def snapshot(
        self,
        transaction: PostgreSQLTransaction,
        *,
        subject_id: UUID,
        scene_id: UUID | None,
        context_party_id: UUID | None,
    ) -> InteractionSubjectCommitSnapshot:
        row = await (
            await transaction.execute(
                """
                SELECT subject_party.party_id, scene.scene_id, scene.scene_key,
                       party.party_id, party.party_kind
                FROM armi.parties AS subject_party
                LEFT JOIN armi.interaction_scenes AS scene
                  ON scene.scene_id = %s AND scene.subject_id = %s
                LEFT JOIN armi.parties AS party
                  ON party.party_id = %s AND party.status = 'active'
                WHERE subject_party.represented_subject_id = %s
                  AND subject_party.party_kind = 'subject'
                  AND subject_party.status = 'active'
                """,
                (scene_id, subject_id, context_party_id, subject_id),
            )
        ).fetchone()
        if (
            row is None
            or (scene_id is None) != (row[1] is None)
            or (context_party_id is not None and row[3] is None)
        ):
            raise SceneQueryViolation("SCENE-QUERY-UNAVAILABLE")
        creator = row[3] if str(row[4]) == "creator" else None
        other = row[3] if row[3] is not None and creator is None else None
        return InteractionSubjectCommitSnapshot(
            row[0],
            row[1],
            str(row[2]) if row[2] is not None else None,
            creator,
            other,
        )

    async def append_timeline(
        self,
        transaction: PostgreSQLTransaction,
        *,
        scene_id: UUID,
        subject_commit_id: UUID,
    ) -> None:
        await transaction.execute(
            """
            INSERT INTO armi.scene_timeline_items (
                timeline_item_id, scene_id, source_kind, source_ref,
                source_event_no, result_status, occurred_at
            ) VALUES (
                %s, %s, 'subject_commit', %s, 1, 'applied',
                statement_timestamp()
            )
            """,
            (uuid7(), scene_id, subject_commit_id),
        )


__all__ = ("PostgreSQLInteractionSubjectCommit",)
