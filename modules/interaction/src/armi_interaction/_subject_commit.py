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
        if scene_id is None:
            if context_party_id is not None:
                raise SceneQueryViolation("SCENE-QUERY-UNAVAILABLE")
            return InteractionSubjectCommitSnapshot(None, None, None, None)
        row = await (
            await transaction.execute(
                """
                SELECT scene.scene_id, scene.scene_key, party.party_id,
                       party.party_kind
                FROM armi.interaction_scenes AS scene
                LEFT JOIN armi.parties AS party
                  ON party.party_id = %s AND party.status = 'active'
                WHERE scene.scene_id = %s AND scene.subject_id = %s
                """,
                (context_party_id, scene_id, subject_id),
            )
        ).fetchone()
        if row is None or (context_party_id is not None and row[2] is None):
            raise SceneQueryViolation("SCENE-QUERY-UNAVAILABLE")
        creator = row[2] if str(row[3]) == "creator" else None
        other = row[2] if row[2] is not None and creator is None else None
        return InteractionSubjectCommitSnapshot(row[0], str(row[1]), creator, other)

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
