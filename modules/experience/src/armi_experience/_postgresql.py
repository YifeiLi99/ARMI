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
    ) -> None:
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
            )
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
                SELECT recent.experience_id,recent.fact_class,
                       recent.first_person_gist,recent.occurred_at,recent.accepted_at,
                       recent.source_perspective,recent.uncertainty
                FROM (
                    SELECT experience_id,fact_class,first_person_gist,occurred_at,
                           accepted_at,source_perspective,uncertainty
                    FROM armi.accepted_experiences
                    WHERE subject_id=%s
                    ORDER BY accepted_at DESC,experience_id DESC LIMIT %s
                ) AS recent
                ORDER BY recent.accepted_at,recent.experience_id
                """,
                (subject_id, limit),
            )
        ).fetchall()
        return _snapshots(rows)

    async def accepted_after(
        self,
        transaction: PostgreSQLTransaction,
        *,
        subject_id: UUID,
        after_experience_id: UUID | None,
        since: datetime,
        limit: int,
    ) -> tuple[AcceptedExperienceSnapshot, ...]:
        boundary: datetime | None = None
        if after_experience_id is not None:
            row = await (
                await transaction.execute(
                    """SELECT accepted_at FROM armi.accepted_experiences
                       WHERE subject_id=%s AND experience_id=%s""",
                    (subject_id, after_experience_id),
                )
            ).fetchone()
            if row is None:
                raise ExperienceViolation("EXPERIENCE-CURSOR")
            boundary = cast(datetime, row[0])
        rows = await (
            await transaction.execute(
                """
                SELECT experience_id,fact_class,first_person_gist,occurred_at,
                       accepted_at,source_perspective,uncertainty
                FROM armi.accepted_experiences
                WHERE subject_id=%s AND (
                    (%s::uuid IS NULL AND accepted_at >= %s)
                    OR (%s::uuid IS NOT NULL
                        AND (accepted_at,experience_id) > (%s,%s))
                )
                ORDER BY accepted_at,experience_id LIMIT %s
                """,
                (
                    subject_id,
                    after_experience_id,
                    since,
                    after_experience_id,
                    boundary,
                    after_experience_id,
                    limit,
                ),
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
                SELECT experience.experience_id,experience.fact_class,
                       experience.first_person_gist,experience.occurred_at,
                       experience.accepted_at,experience.source_perspective,
                       experience.uncertainty
                FROM unnest(%s::uuid[]) WITH ORDINALITY AS requested(experience_id,ordinal)
                JOIN armi.accepted_experiences AS experience
                  ON experience.experience_id=requested.experience_id
                 AND experience.subject_id=%s
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
            ExperienceId(cast(UUID, row[0])),
            CandidateFactClass(str(row[1])),
            str(row[2]),
            cast(datetime, row[3]),
            cast(datetime, row[4]),
            ExperienceSourcePerspective(str(row[5])),
            None if row[6] is None else str(row[6]),
        )
        for row in rows
    )


__all__ = ("PostgreSQLExperienceOwner",)
