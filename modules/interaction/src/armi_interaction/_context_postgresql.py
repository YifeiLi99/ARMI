"""Interaction-owned Context and Cognition read projections."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from armi_kernel.contracts import TraceId
from armi_runtime_foundation import PostgreSQLTransaction

from .api import (
    CreatorInputViolation,
    InteractionCognitionSnapshot,
    InteractionContextSceneSnapshot,
    InteractionContextTurn,
)


class PostgreSQLInteractionContextRead:
    async def context_scene(
        self,
        transaction: PostgreSQLTransaction,
        *,
        scene_id: UUID,
        context_party_id: UUID | None,
        current_interaction_id: UUID | None,
    ) -> InteractionContextSceneSnapshot:
        row = await (
            await transaction.execute(
                """SELECT scene.scene_id, scene.scene_key, scene.scene_kind,
                      scene.audience_scope, scene.current_status, scene.scene_version,
                      scene.primary_party_id, party.party_id, party.display_label,
                      party.party_kind, input.addressed_to_subject
               FROM armi.interaction_scenes AS scene
               LEFT JOIN armi.parties AS party ON party.party_id=%s
               LEFT JOIN armi.party_input_interactions AS input
                 ON input.interaction_id=%s AND input.scene_id=scene.scene_id
               WHERE scene.scene_id=%s""",
                (context_party_id, current_interaction_id, scene_id),
            )
        ).fetchone()
        if row is None:
            raise RuntimeError("INTERACTION-CONTEXT-SCENE")
        return InteractionContextSceneSnapshot(
            row[0],
            str(row[1]),
            str(row[2]),
            str(row[3]),
            str(row[4]),
            int(row[5]),
            row[6],
            row[7],
            None if row[8] is None else str(row[8]),
            None if row[9] is None else str(row[9]),
            row[10],
        )

    async def recent_context_turns(
        self,
        transaction: PostgreSQLTransaction,
        *,
        scene_id: UUID,
        before_interaction_id: UUID | None,
        before_time: datetime | None,
        source_kinds: tuple[str, ...],
        limit: int,
    ) -> tuple[InteractionContextTurn, ...]:
        anchor = None
        if before_interaction_id is not None:
            anchor = await (
                await transaction.execute(
                    "SELECT occurred_at, timeline_item_id FROM armi.scene_timeline_items "
                    "WHERE scene_id=%s AND source_ref=%s",
                    (scene_id, before_interaction_id),
                )
            ).fetchone()
        rows = await (
            await transaction.execute(
                """SELECT item.timeline_item_id, item.source_event_no, item.source_kind,
                      item.source_ref, item.occurred_at, party.display_label, party.party_kind
               FROM armi.scene_timeline_items AS item
               LEFT JOIN armi.party_input_interactions AS input
                 ON input.interaction_id=item.source_ref
                AND item.source_kind IN ('creator_input','other_human_input')
               LEFT JOIN armi.parties AS party ON party.party_id=input.source_party_id
               WHERE item.scene_id=%s AND item.source_kind=ANY(%s)
                 AND (%s::timestamptz IS NULL OR (item.occurred_at,item.timeline_item_id)<(%s,%s))
                 AND (%s::timestamptz IS NULL OR item.occurred_at<=%s)
               ORDER BY item.occurred_at DESC, item.timeline_item_id DESC LIMIT %s""",
                (
                    scene_id,
                    list(source_kinds),
                    None if anchor is None else anchor[0],
                    None if anchor is None else anchor[0],
                    None if anchor is None else anchor[1],
                    before_time,
                    before_time,
                    limit,
                ),
            )
        ).fetchall()
        return tuple(
            InteractionContextTurn(
                r[0],
                int(r[1]),
                str(r[2]),
                r[3],
                r[4],
                None if r[5] is None else str(r[5]),
                None if r[6] is None else str(r[6]),
            )
            for r in reversed(rows)
        )

    async def cognition_snapshot(
        self,
        transaction: PostgreSQLTransaction,
        *,
        subject_id: UUID,
        scene_id: UUID | None,
        context_party_id: UUID | None,
    ) -> InteractionCognitionSnapshot:
        row = await (
            await transaction.execute(
                """SELECT scene.scene_kind, context.party_kind, subject_party.party_id
               FROM armi.parties AS subject_party
               LEFT JOIN armi.interaction_scenes AS scene ON scene.scene_id=%s
               LEFT JOIN armi.parties AS context ON context.party_id=%s
               WHERE subject_party.party_kind='subject'
                 AND subject_party.represented_subject_id=%s""",
                (scene_id, context_party_id, subject_id),
            )
        ).fetchone()
        if row is None:
            raise RuntimeError("INTERACTION-COGNITION-SNAPSHOT")
        return InteractionCognitionSnapshot(
            None if row[0] is None else str(row[0]),
            None if row[1] is None else str(row[1]),
            row[2],
        )

    async def interaction_trace(
        self,
        transaction: PostgreSQLTransaction,
        *,
        interaction_id: UUID,
    ) -> TraceId:
        row = await (
            await transaction.execute(
                "SELECT trace_id FROM armi.party_input_interactions "
                "WHERE interaction_id=%s",
                (interaction_id,),
            )
        ).fetchone()
        if row is None:
            raise CreatorInputViolation("DB-INPUT-STATE")
        return TraceId(str(row[0]))


__all__ = ("PostgreSQLInteractionContextRead",)
