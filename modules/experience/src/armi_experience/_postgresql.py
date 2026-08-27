"""PostgreSQL owner for accepted Experiences."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import cast
from uuid import UUID

from armi_kernel.application import CandidateFactClass, ExperienceId
from armi_runtime_foundation import PostgreSQLTransaction

from .api import (
    AcceptedExperienceDraft,
    AcceptedExperienceSnapshot,
    ExperienceLifeRecordItem,
    ExperienceSourcePerspective,
    ExperienceViolation,
)


class PostgreSQLExperienceOwner:
    async def record(
        self,
        transaction: PostgreSQLTransaction,
        draft: AcceptedExperienceDraft,
    ) -> int:
        row = await (
            await transaction.execute(
                """
            INSERT INTO armi.accepted_experiences (
                experience_id, subject_id, subject_commit_id, cognitive_episode_id,
                proposal_ref, experience_kind, fact_class, first_person_gist,
                scene_id, occurred_at, learned_at, source_perspective,
                uncertainty, privacy_scope
            ) VALUES (
                %s, %s, %s, %s, %s, %s, %s, %s,
                %s, %s, %s, %s, %s, 'private'
            ) RETURNING acceptance_ordinal
            """,
                (
                    draft.experience_id.value,
                    draft.subject_id,
                    draft.subject_commit_id,
                    draft.cognitive_episode_id,
                    draft.proposal_ref,
                    draft.experience_kind.value,
                    draft.fact_class.value,
                    draft.first_person_gist,
                    draft.scene_id,
                    draft.occurred_at,
                    draft.occurred_at,
                    draft.source_perspective.value,
                    draft.uncertainty,
                ),
            )
        ).fetchone()
        if row is None:
            raise ExperienceViolation("EXPERIENCE-INSERT")
        return int(row[0])

    async def recent(
        self,
        transaction: PostgreSQLTransaction,
        *,
        subject_id: UUID,
        limit: int,
    ) -> tuple[AcceptedExperienceSnapshot, ...]:
        rows = await (
            await transaction.execute(
                """
                SELECT recent.acceptance_ordinal,recent.experience_id,recent.fact_class,
                       recent.first_person_gist,recent.occurred_at,recent.accepted_at,
                       recent.source_perspective,recent.uncertainty
                FROM (
                    SELECT acceptance_ordinal,experience_id,fact_class,first_person_gist,occurred_at,
                           accepted_at,source_perspective,uncertainty
                    FROM armi.accepted_experiences
                    WHERE subject_id=%s AND data_rights_hidden_at IS NULL
                    ORDER BY accepted_at DESC,experience_id DESC LIMIT %s
                ) AS recent
                ORDER BY recent.accepted_at,recent.experience_id
                """,
                (subject_id, limit),
            )
        ).fetchall()
        return _snapshots(rows)

    async def accepted_in_ordinal_window(
        self,
        transaction: PostgreSQLTransaction,
        *,
        subject_id: UUID,
        after_ordinal: int,
        through_ordinal: int,
        limit: int,
    ) -> tuple[AcceptedExperienceSnapshot, ...]:
        rows = await (
            await transaction.execute(
                """
                SELECT acceptance_ordinal,experience_id,fact_class,first_person_gist,occurred_at,
                       accepted_at,source_perspective,uncertainty
                FROM armi.accepted_experiences
                WHERE subject_id=%s AND data_rights_hidden_at IS NULL
                  AND acceptance_ordinal > %s
                  AND acceptance_ordinal <= %s
                ORDER BY acceptance_ordinal LIMIT %s
                """,
                (subject_id, after_ordinal, through_ordinal, limit),
            )
        ).fetchall()
        return _snapshots(rows)

    async def by_ids(
        self,
        transaction: PostgreSQLTransaction,
        *,
        subject_id: UUID,
        experience_ids: tuple[UUID, ...],
    ) -> tuple[AcceptedExperienceSnapshot, ...]:
        if not experience_ids:
            return ()
        rows = await (
            await transaction.execute(
                """
                SELECT experience.acceptance_ordinal,experience.experience_id,experience.fact_class,
                       experience.first_person_gist,experience.occurred_at,
                       experience.accepted_at,experience.source_perspective,
                       experience.uncertainty
                FROM unnest(%s::uuid[]) WITH ORDINALITY AS requested(experience_id,ordinal)
                JOIN armi.accepted_experiences AS experience
                  ON experience.experience_id=requested.experience_id
                 AND experience.subject_id=%s
                 AND experience.data_rights_hidden_at IS NULL
                ORDER BY requested.ordinal
                """,
                (list(experience_ids), subject_id),
            )
        ).fetchall()
        if len(rows) != len(experience_ids):
            raise ExperienceViolation("EXPERIENCE-NOT-FOUND")
        return _snapshots(rows)

    async def life_record_branch(
        self,
        transaction: PostgreSQLTransaction,
        *,
        subject_id: UUID,
        query_text: str | None,
        before: tuple[datetime, str, UUID] | None,
        limit: int,
    ) -> tuple[ExperienceLifeRecordItem, ...]:
        rows = await (
            await transaction.execute(
                """
                SELECT experience_id, first_person_gist, source_perspective, accepted_at
                FROM armi.accepted_experiences
                WHERE subject_id = %s
                  AND data_rights_hidden_at IS NULL
                  AND (%s::text IS NULL OR first_person_gist ILIKE '%%' || %s::text || '%%')
                  AND (%s::timestamptz IS NULL OR
                       (accepted_at, 'conversation'::text, experience_id)
                           < (%s::timestamptz,%s::text,%s::uuid))
                ORDER BY accepted_at DESC, experience_id DESC LIMIT %s
                """,
                (
                    subject_id,
                    query_text,
                    query_text,
                    None if before is None else before[0],
                    None if before is None else before[0],
                    None if before is None else before[1],
                    None if before is None else before[2],
                    limit,
                ),
            )
        ).fetchall()
        return tuple(
            ExperienceLifeRecordItem(row[0], str(row[1]), str(row[2]), row[3])
            for row in rows
        )


def _snapshots(
    rows: Sequence[tuple[object, ...]],
) -> tuple[AcceptedExperienceSnapshot, ...]:
    return tuple(
        AcceptedExperienceSnapshot(
            cast(int, row[0]),
            ExperienceId(cast(UUID, row[1])),
            CandidateFactClass(str(row[2])),
            str(row[3]),
            cast(datetime, row[4]),
            cast(datetime, row[5]),
            ExperienceSourcePerspective(str(row[6])),
            None if row[7] is None else str(row[7]),
        )
        for row in rows
    )


__all__ = ("PostgreSQLExperienceOwner",)
