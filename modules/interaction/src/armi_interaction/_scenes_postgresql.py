"""PostgreSQL owner for Creator scene lifecycle state."""

from __future__ import annotations

from uuid import UUID

from armi_kernel.contracts import Instant
from armi_runtime_foundation import PostgreSQLRuntimeUnitOfWork

from ._scene_contract import (
    CreatorSceneCollection,
    CreatorSceneView,
    SceneKey,
    SceneQueryViolation,
    SceneStatus,
)


class CreatorSceneRepository:
    __slots__ = ()

    async def list(
        self,
        unit_of_work: PostgreSQLRuntimeUnitOfWork,
        *,
        creator_party_id: UUID,
    ) -> CreatorSceneCollection:
        connection = unit_of_work.transaction
        rows = await (
            await connection.execute(
                """
                SELECT scene.scene_id, scene.scene_key, scene.current_status,
                       scene.opened_at, scene.closed_at,
                       scene.recent_context_boundary
                FROM armi.interaction_scenes AS scene
                JOIN armi.subjects AS subject
                  ON subject.subject_id = scene.subject_id
                 AND subject.singleton_key = 1
                 AND subject.status = 'active'
                JOIN armi.parties AS creator
                  ON creator.party_id = scene.primary_party_id
                 AND creator.party_kind = 'creator'
                 AND creator.creator_role = 'unique_primary_creator'
                 AND creator.status = 'active'
                WHERE scene.primary_party_id = %s
                  AND scene.scene_kind = 'creator_dialogue'
                  AND scene.audience_scope = 'creator'
                ORDER BY (scene.scene_key <> 'default'), scene.scene_key
                """,
                (creator_party_id,),
            )
        ).fetchall()
        if not rows:
            raise SceneQueryViolation("SCENE-QUERY-UNAVAILABLE")
        return CreatorSceneCollection(tuple(_view(row) for row in rows))

    async def subject_id(
        self,
        unit_of_work: PostgreSQLRuntimeUnitOfWork,
        *,
        creator_party_id: UUID,
    ) -> UUID:
        connection = unit_of_work.transaction
        row = await (
            await connection.execute(
                """
                SELECT subject.subject_id
                FROM armi.subjects AS subject
                JOIN armi.interaction_scenes AS default_scene
                  ON default_scene.subject_id = subject.subject_id
                 AND default_scene.scene_key = 'default'
                 AND default_scene.current_status = 'open'
                 AND default_scene.closed_at IS NULL
                JOIN armi.parties AS creator
                  ON creator.party_id = default_scene.primary_party_id
                 AND creator.party_id = %s
                 AND creator.party_kind = 'creator'
                 AND creator.creator_role = 'unique_primary_creator'
                 AND creator.status = 'active'
                WHERE subject.singleton_key = 1
                  AND subject.status = 'active'
                """,
                (creator_party_id,),
            )
        ).fetchone()
        if row is None or type(row[0]) is not UUID:
            raise SceneQueryViolation("SCENE-QUERY-UNAVAILABLE")
        return row[0]

    async def create(
        self,
        unit_of_work: PostgreSQLRuntimeUnitOfWork,
        *,
        scene_id: UUID,
        subject_id: UUID,
        creator_party_id: UUID,
        scene_key: SceneKey,
    ) -> CreatorSceneView:
        connection = unit_of_work.transaction
        row = await (
            await connection.execute(
                """
                INSERT INTO armi.interaction_scenes (
                    scene_id, subject_id, scene_key, scene_kind,
                    primary_party_id, audience_scope, current_status) VALUES (
                    %s, %s, %s, 'creator_dialogue', %s, 'creator', 'open')
                RETURNING scene_id, scene_key, current_status, opened_at,
                          closed_at, recent_context_boundary
                """,
                (scene_id, subject_id, scene_key.value, creator_party_id),
            )
        ).fetchone()
        if row is None:
            raise SceneQueryViolation("SCENE-CREATE-FAILED")
        await connection.execute(
            """
            INSERT INTO armi.scene_participants (
                scene_id, subject_id, party_id, participant_role
            ) VALUES (%s, %s, %s, 'primary')
            """,
            (scene_id, subject_id, creator_party_id),
        )
        return _view(row)

    async def set_status(
        self,
        unit_of_work: PostgreSQLRuntimeUnitOfWork,
        *,
        creator_party_id: UUID,
        scene_key: SceneKey,
        target_status: SceneStatus,
    ) -> tuple[UUID, CreatorSceneView, bool]:
        connection = unit_of_work.transaction
        row = await (
            await connection.execute(
                """
                SELECT scene.scene_id, scene.subject_id, scene.scene_key,
                       scene.current_status, scene.opened_at, scene.closed_at,
                       scene.recent_context_boundary
                FROM armi.interaction_scenes AS scene
                JOIN armi.subjects AS subject
                  ON subject.subject_id = scene.subject_id
                 AND subject.singleton_key = 1
                 AND subject.status = 'active'
                WHERE scene.primary_party_id = %s
                  AND scene.scene_key = %s
                  AND scene.scene_key <> 'default'
                  AND scene.scene_kind = 'creator_dialogue'
                  AND scene.audience_scope = 'creator'
                FOR UPDATE OF scene
                """,
                (creator_party_id, scene_key.value),
            )
        ).fetchone()
        if row is None:
            raise SceneQueryViolation("SCENE-NOT-VISIBLE")
        subject_id = row[1]
        current = _view((row[0], row[2], row[3], row[4], row[5], row[6]))
        if current.status is target_status:
            return subject_id, current, False
        changed_row = await (
            await connection.execute(
                """
                UPDATE armi.interaction_scenes
                SET current_status = %s,
                    closed_at = CASE
                        WHEN %s = 'closed' THEN statement_timestamp()
                        ELSE NULL
                    END,
                    scene_version = scene_version + 1
                WHERE scene_id = %s
                  AND current_status IS DISTINCT FROM %s
                RETURNING scene_id, scene_key, current_status, opened_at,
                          closed_at, recent_context_boundary
                """,
                (
                    target_status.value,
                    target_status.value,
                    current.scene_id,
                    target_status.value,
                ),
            )
        ).fetchone()
        if changed_row is None:
            raise SceneQueryViolation("SCENE-UPDATE-FAILED")
        return subject_id, _view(changed_row), True


def _view(row: tuple[object, ...]) -> CreatorSceneView:
    return CreatorSceneView(
        scene_id=row[0],  # type: ignore[arg-type]
        scene_key=SceneKey(str(row[1])),
        status=SceneStatus(str(row[2])),
        opened_at=Instant(row[3]),  # type: ignore[arg-type]
        closed_at=None if row[4] is None else Instant(row[4]),  # type: ignore[arg-type]
        recent_context_boundary=row[5],  # type: ignore[arg-type]
        is_default=str(row[1]) == "default",
    )


__all__ = ("CreatorSceneRepository",)
