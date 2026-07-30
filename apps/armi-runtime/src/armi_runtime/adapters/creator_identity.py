"""Read-only database adapter for the unique born Creator identity."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

import psycopg


@dataclass(frozen=True, slots=True)
class CreatorContext:
    party_id: UUID
    default_scene_key: str


def read_creator_context(conninfo: str) -> CreatorContext | None:
    """Return the sole active Creator and visible default scene."""

    try:
        with psycopg.connect(conninfo, autocommit=True) as connection:
            rows = connection.execute(
                """
                SELECT creator.party_id, scene.scene_key
                FROM armi.parties AS creator
                JOIN armi.interaction_scenes AS scene
                  ON scene.primary_party_id = creator.party_id
                 AND scene.scene_key = 'default'
                 AND scene.scene_kind = 'creator_dialogue'
                 AND scene.audience_scope = 'creator'
                 AND scene.current_status = 'open'
                 AND scene.closed_at IS NULL
                JOIN armi.subjects AS subject
                  ON subject.subject_id = scene.subject_id
                 AND subject.singleton_key = 1
                WHERE creator.party_kind = 'creator'
                  AND creator.creator_role = 'unique_primary_creator'
                  AND creator.status = 'active'
                """
            ).fetchall()
    except psycopg.Error:
        return None
    if len(rows) != 1 or not isinstance(rows[0][0], UUID) or rows[0][1] != "default":
        return None
    return CreatorContext(party_id=rows[0][0], default_scene_key=rows[0][1])


def read_creator_party_id(conninfo: str) -> UUID | None:
    context = read_creator_context(conninfo)
    return None if context is None else context.party_id


__all__ = ("CreatorContext", "read_creator_context", "read_creator_party_id")
