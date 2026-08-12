"""PostgreSQL-backed Activity reads and Creator projections."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal, cast
from uuid import UUID

import psycopg
import rfc8785
from armi_kernel.contracts import ActivityId
from armi_runtime_foundation import PostgreSQLTransaction
from psycopg.pq import TransactionStatus
from psycopg_pool import AsyncConnectionPool, PoolTimeout

from .api import (
    ActivityAttentionRootState,
    ActivityCandidateSnapshot,
    ActivityHeadSnapshot,
    ActivityLifeRecordItem,
    ActivityOutreachSource,
    ActivityStatus,
    ActivityTimelineKind,
    ActivityTransition,
    ActivityViolation,
    ActivityWaitingKind,
    ActivityWorkHead,
    CreatorActivityItem,
    CreatorActivityPage,
    CreatorActivityTimeline,
    CreatorActivityTimelineItem,
)

_SEARCH_PATH = "pg_catalog, armi"
_PAGE_SIZE = 100


async def _configure(
    connection: psycopg.AsyncConnection[tuple[Any, ...]],
) -> None:
    await connection.set_autocommit(True)
    await connection.execute("SET search_path TO pg_catalog, armi")


async def _reset(connection: psycopg.AsyncConnection[tuple[Any, ...]]) -> None:
    if connection.info.transaction_status != TransactionStatus.IDLE:
        await connection.rollback()
    await connection.execute("RESET ROLE")
    await connection.execute("RESET ALL")
    await connection.execute("SET search_path TO pg_catalog, armi")


class PostgreSQLActivityRead:
    """Read the current subject's bounded Creator-visible Activity projection."""

    __slots__ = (
        "_creator_party_id",
        "_expected_role",
        "_pool",
        "_pool_timeout_seconds",
    )

    def __init__(
        self,
        conninfo: str,
        *,
        expected_role: str,
        creator_party_id: UUID,
        pool_timeout_seconds: int,
    ) -> None:
        self._creator_party_id = creator_party_id
        self._expected_role = expected_role
        self._pool_timeout_seconds = pool_timeout_seconds

        async def check(
            connection: psycopg.AsyncConnection[tuple[Any, ...]],
        ) -> None:
            row = await (
                await connection.execute(
                    "SELECT session_user, current_user, current_setting('search_path')"
                )
            ).fetchone()
            if row != (self._expected_role, self._expected_role, _SEARCH_PATH):
                raise ActivityViolation("ACTIVITY-QUERY-UNAVAILABLE")

        self._pool = AsyncConnectionPool[psycopg.AsyncConnection[tuple[Any, ...]]](
            conninfo,
            min_size=1,
            max_size=1,
            open=False,
            configure=_configure,
            check=check,
            reset=_reset,
            timeout=float(pool_timeout_seconds),
            name="armi-creator-activity-query",
        )

    async def open(self) -> None:
        try:
            await self._pool.open(wait=True)
        except psycopg.Error, PoolTimeout:
            raise ActivityViolation("ACTIVITY-QUERY-UNAVAILABLE") from None

    async def close(self) -> None:
        await self._pool.close()

    async def list_current(self) -> CreatorActivityPage:
        try:
            async with (
                self._pool.connection(
                    timeout=float(self._pool_timeout_seconds)
                ) as connection,
                connection.transaction(),
            ):
                await connection.execute("SET TRANSACTION READ ONLY")
                subject_id, focused = await self._scope(connection)
                rows = await (
                    await connection.execute(
                        """
                        SELECT activity.activity_id, activity.activity_kind,
                               revision.status, revision.goal,
                               revision.progress_summary,
                               revision.waiting_condition_kind,
                               revision.waiting_condition,
                               revision.resume_not_before,
                               revision.terminal_reason,
                               revision.revision_no, activity.head_version,
                               revision.transition_kind, activity.created_at,
                               revision.created_at
                        FROM armi.activities AS activity
                        JOIN armi.activity_revisions AS revision
                          ON revision.activity_revision_id = activity.current_revision_id
                         AND revision.activity_id = activity.activity_id
                        WHERE activity.subject_id = %s
                        ORDER BY revision.created_at DESC, activity.activity_id DESC
                        LIMIT %s
                        """,
                        (subject_id, _PAGE_SIZE + 1),
                    )
                ).fetchall()
        except ActivityViolation:
            raise
        except psycopg.Error, PoolTimeout:
            raise ActivityViolation("ACTIVITY-QUERY-UNAVAILABLE") from None
        return CreatorActivityPage(
            tuple(self._activity(row, focused) for row in rows[:_PAGE_SIZE]),
            len(rows) > _PAGE_SIZE,
        )

    async def timeline(self, activity_id: UUID) -> CreatorActivityTimeline:
        try:
            async with (
                self._pool.connection(
                    timeout=float(self._pool_timeout_seconds)
                ) as connection,
                connection.transaction(),
            ):
                await connection.execute("SET TRANSACTION READ ONLY")
                subject_id, _ = await self._scope(connection)
                visible = await (
                    await connection.execute(
                        """
                        SELECT 1 FROM armi.activities
                        WHERE activity_id = %s AND subject_id = %s
                        """,
                        (activity_id, subject_id),
                    )
                ).fetchone()
                if visible is None:
                    raise ActivityViolation("ACTIVITY-QUERY-NOT-FOUND")
                rows = await (
                    await connection.execute(
                        """
                        SELECT revision.activity_revision_id,
                               revision.transition_kind,
                               revision.status,
                               COALESCE(
                                   revision.progress_summary,
                                   revision.waiting_condition,
                                   revision.terminal_reason
                               ),
                               NULL::timestamptz,
                               revision.created_at
                        FROM armi.activity_revisions AS revision
                        WHERE revision.activity_id = %s
                        UNION ALL
                        SELECT decision.activity_decision_id,
                               decision.decision_kind,
                               NULL::text,
                               NULL::text,
                               decision.review_not_before,
                               decision.decided_at
                        FROM armi.activity_decisions AS decision
                        WHERE decision.activity_id = %s
                          AND decision.result_revision_id IS NULL
                        ORDER BY 6 DESC, 1 DESC
                        LIMIT %s
                        """,
                        (activity_id, activity_id, _PAGE_SIZE + 1),
                    )
                ).fetchall()
        except ActivityViolation:
            raise
        except psycopg.Error, PoolTimeout:
            raise ActivityViolation("ACTIVITY-QUERY-UNAVAILABLE") from None
        return CreatorActivityTimeline(
            activity_id,
            tuple(self._timeline_item(row) for row in rows[:_PAGE_SIZE]),
            len(rows) > _PAGE_SIZE,
        )

    async def candidate_head(
        self,
        transaction: PostgreSQLTransaction,
        *,
        episode_id: UUID,
    ) -> ActivityCandidateSnapshot | None:
        row = await (
            await transaction.execute(
                """
                SELECT opportunity.activity_id, activity.current_revision_id,
                       activity.head_version, revision.status
                FROM armi.cognitive_episodes AS episode
                JOIN armi.opportunities AS opportunity
                  ON opportunity.opportunity_id = episode.opportunity_id
                JOIN armi.activities AS activity
                  ON activity.activity_id = opportunity.activity_id
                JOIN armi.activity_revisions AS revision
                  ON revision.activity_revision_id = activity.current_revision_id
                WHERE episode.cognitive_episode_id = %s
                  AND episode.purpose IN (
                      'consider_activity_attention',
                      'consider_activity_internal_work'
                  )
                  AND opportunity.source_ref = activity.current_revision_id
                """,
                (episode_id,),
            )
        ).fetchone()
        if row is None:
            return None
        return ActivityCandidateSnapshot(
            row[0], row[1], int(row[2]), ActivityStatus(str(row[3]))
        )

    async def context_summary(
        self,
        transaction: PostgreSQLTransaction,
        *,
        subject_id: UUID,
        enabled: bool,
    ) -> bytes:
        rows = ()
        if enabled:
            rows = await (
                await transaction.execute(
                    """
                    SELECT activity.activity_id, activity.head_version,
                           revision.revision_no, revision.status,
                           revision.goal, revision.next_safe_step,
                           revision.progress_summary, revision.waiting_condition,
                           revision.resumption_cue
                    FROM armi.activities AS activity
                    JOIN armi.activity_revisions AS revision
                      ON revision.activity_revision_id = activity.current_revision_id
                    WHERE activity.subject_id = %s
                    ORDER BY activity.activity_id
                    """,
                    (subject_id,),
                )
            ).fetchall()
        return rfc8785.dumps(
            {
                "schema_version": "armi.activity-context-summary.v1",
                "activities": [
                    {
                        "activity_id": str(item[0]),
                        "head_version": int(item[1]),
                        "revision_no": int(item[2]),
                        "status": str(item[3]),
                        "goal": str(item[4]),
                        "next_safe_step": str(item[5]),
                        "progress_summary": None if item[6] is None else str(item[6]),
                        "waiting_condition": None if item[7] is None else str(item[7]),
                        "resumption_cue": None if item[8] is None else str(item[8]),
                    }
                    for item in rows
                ],
            }
        )

    async def scheduling_heads(
        self,
        transaction: PostgreSQLTransaction,
        *,
        subject_id: UUID,
    ) -> tuple[ActivityHeadSnapshot, ...]:
        rows = await (
            await transaction.execute(
                """
                SELECT activity.activity_id, revision.activity_revision_id,
                       revision.revision_no, revision.status, revision.created_at,
                       max(previous.available_after) AS last_considered_at,
                       revision.waiting_condition_kind,
                       revision.resume_not_before,
                       CASE
                         WHEN revision.waiting_condition_kind = 'creator_input' THEN EXISTS (
                           SELECT 1 FROM armi.party_input_interactions AS input
                           WHERE input.received_at > revision.created_at
                         )
                         WHEN revision.waiting_condition_kind = 'external_evidence' THEN EXISTS (
                           SELECT 1 FROM armi.external_evidence AS evidence
                           WHERE evidence.subject_id = activity.subject_id
                             AND evidence.received_at > revision.created_at
                         )
                         ELSE false
                       END AS waiting_signal_available
                FROM armi.activities AS activity
                JOIN armi.activity_revisions AS revision
                  ON revision.activity_revision_id = activity.current_revision_id
                LEFT JOIN armi.opportunities AS previous
                  ON previous.source_kind = 'activity_revision'
                 AND previous.source_ref = revision.activity_revision_id
                 AND previous.purpose = 'consider_activity_attention'
                WHERE activity.subject_id = %s
                  AND (
                    NOT EXISTS (
                        SELECT 1 FROM armi.opportunities AS candidate_root
                        WHERE candidate_root.subject_id = activity.subject_id
                          AND candidate_root.source_kind = 'activity_revision'
                          AND candidate_root.source_ref = revision.activity_revision_id
                          AND candidate_root.source_version = revision.revision_no
                          AND candidate_root.purpose = 'consider_activity_attention'
                          AND candidate_root.reconsideration_no = 0
                    )
                    OR EXISTS (
                        SELECT 1 FROM armi.opportunities AS candidate_root
                        WHERE candidate_root.subject_id = activity.subject_id
                          AND candidate_root.source_kind = 'activity_revision'
                          AND candidate_root.source_ref = revision.activity_revision_id
                          AND candidate_root.source_version = revision.revision_no
                          AND candidate_root.purpose = 'consider_activity_attention'
                          AND candidate_root.reconsideration_no = 0
                          AND candidate_root.current_disposition = 'resolved'
                          AND (
                            EXISTS (
                              SELECT 1 FROM armi.cognitive_episodes AS failed_episode
                              WHERE failed_episode.opportunity_id = candidate_root.opportunity_id
                                AND failed_episode.status IN ('failed', 'candidate_rejected')
                                AND candidate_root.resolved_at + interval '60 seconds' <= statement_timestamp()
                            )
                            OR EXISTS (
                              SELECT 1 FROM armi.cognitive_episodes AS waiting_episode
                              JOIN armi.activity_decisions AS decision USING (cognitive_episode_id)
                              WHERE waiting_episode.opportunity_id = candidate_root.opportunity_id
                                AND waiting_episode.status = 'completed'
                                AND decision.decision_kind = 'need_information'
                                AND EXISTS (
                                  SELECT 1 FROM armi.party_input_interactions AS input
                                  WHERE input.received_at > decision.decided_at
                                )
                            )
                          )
                          AND NOT EXISTS (
                              SELECT 1 FROM armi.opportunities AS candidate_successor
                              WHERE candidate_successor.predecessor_opportunity_id = candidate_root.opportunity_id
                          )
                    )
                  )
                GROUP BY activity.activity_id, revision.activity_revision_id
                """,
                (subject_id,),
            )
        ).fetchall()
        return tuple(
            ActivityHeadSnapshot(
                ActivityId(row[0]),
                row[1],
                int(row[2]),
                ActivityStatus(str(row[3])),
                row[4],
                row[5],
                None if row[6] is None else ActivityWaitingKind(str(row[6])),
                row[7],
                bool(row[8]),
            )
            for row in rows
        )

    async def focused_work_head(
        self,
        transaction: PostgreSQLTransaction,
        *,
        subject_id: UUID,
        activity_id: UUID,
    ) -> ActivityWorkHead | None:
        row = await (
            await transaction.execute(
                """
                SELECT activity.activity_id, revision.activity_revision_id,
                       revision.revision_no
                FROM armi.activities AS activity
                JOIN armi.activity_revisions AS revision
                  ON revision.activity_revision_id = activity.current_revision_id
                WHERE activity.subject_id = %s AND activity.activity_id = %s
                  AND revision.status = 'in_progress'
                """,
                (subject_id, activity_id),
            )
        ).fetchone()
        return None if row is None else ActivityWorkHead(row[0], row[1], int(row[2]))

    async def completed_outreach_source(
        self,
        transaction: PostgreSQLTransaction,
        *,
        subject_id: UUID,
        after: datetime,
    ) -> ActivityOutreachSource | None:
        row = await (
            await transaction.execute(
                """
                SELECT revision.activity_revision_id, activity.head_version,
                       activity.activity_id, revision.created_at
                FROM armi.activities AS activity
                JOIN armi.activity_revisions AS revision
                  ON revision.activity_revision_id = activity.current_revision_id
                WHERE activity.subject_id = %s
                  AND revision.status = 'completed'
                  AND revision.created_at > %s
                  AND NOT EXISTS (
                      SELECT 1 FROM armi.opportunities AS existing
                      WHERE existing.subject_id = activity.subject_id
                        AND existing.source_kind = 'creator_outreach_activity'
                        AND existing.source_ref = revision.activity_revision_id
                        AND existing.source_version = activity.head_version
                        AND existing.purpose = 'consider_creator_outreach'
                  )
                ORDER BY revision.created_at DESC, revision.activity_revision_id DESC
                LIMIT 1
                """,
                (subject_id, after),
            )
        ).fetchone()
        return (
            None
            if row is None
            else ActivityOutreachSource(row[0], int(row[1]), row[2], row[3])
        )

    async def life_record_branch(
        self,
        transaction: PostgreSQLTransaction,
        *,
        subject_id: UUID,
        query_text: str | None,
        before: tuple[datetime, str, UUID] | None,
        limit: int,
    ) -> tuple[ActivityLifeRecordItem, ...]:
        rows = await (
            await transaction.execute(
                """
                SELECT activity.activity_id,
                       left(revision.goal || CASE WHEN revision.progress_summary IS NULL THEN '' ELSE ' — ' || revision.progress_summary END, 4096),
                       revision.created_at
                FROM armi.activities AS activity
                JOIN armi.activity_revisions AS revision
                  ON revision.activity_revision_id = activity.current_revision_id
                WHERE activity.subject_id = %s
                  AND (%s IS NULL OR left(revision.goal || CASE WHEN revision.progress_summary IS NULL THEN '' ELSE ' — ' || revision.progress_summary END, 4096) ILIKE '%%' || %s || '%%')
                  AND (%s IS NULL OR (revision.created_at, 'activity'::text, activity.activity_id) < (%s, %s, %s))
                ORDER BY revision.created_at DESC, activity.activity_id DESC
                LIMIT %s
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
            ActivityLifeRecordItem(row[0], str(row[1]), row[2]) for row in rows
        )

    async def attention_root_state(
        self,
        transaction: PostgreSQLTransaction,
        *,
        subject_id: UUID,
        revision_id: UUID,
        revision_no: int,
    ) -> ActivityAttentionRootState | None:
        row = await (
            await transaction.execute(
                """
                SELECT root.opportunity_id, root.current_disposition,
                       (
                         EXISTS (
                           SELECT 1 FROM armi.cognitive_episodes AS failed_episode
                           WHERE failed_episode.opportunity_id = root.opportunity_id
                             AND failed_episode.status IN ('failed', 'candidate_rejected')
                             AND root.resolved_at + interval '60 seconds' <= statement_timestamp()
                         )
                         OR EXISTS (
                           SELECT 1 FROM armi.cognitive_episodes AS waiting_episode
                           JOIN armi.activity_decisions AS decision USING (cognitive_episode_id)
                           WHERE waiting_episode.opportunity_id = root.opportunity_id
                             AND waiting_episode.status = 'completed'
                             AND decision.decision_kind = 'need_information'
                             AND EXISTS (
                               SELECT 1 FROM armi.party_input_interactions AS input
                               WHERE input.received_at > decision.decided_at
                             )
                         )
                       ), successor.opportunity_id
                FROM armi.opportunities AS root
                LEFT JOIN armi.opportunities AS successor
                  ON successor.predecessor_opportunity_id = root.opportunity_id
                WHERE root.subject_id = %s
                  AND root.source_kind = 'activity_revision'
                  AND root.source_ref = %s AND root.source_version = %s
                  AND root.purpose = 'consider_activity_attention'
                  AND root.reconsideration_no = 0
                """,
                (subject_id, revision_id, revision_no),
            )
        ).fetchone()
        return (
            None
            if row is None
            else ActivityAttentionRootState(row[0], str(row[1]), bool(row[2]), row[3])
        )

    async def _scope(
        self, connection: psycopg.AsyncConnection[tuple[Any, ...]]
    ) -> tuple[UUID, frozenset[str]]:
        creator = await (
            await connection.execute(
                """
                SELECT 1 FROM armi.parties
                WHERE party_id = %s AND party_kind = 'creator'
                  AND creator_role = 'unique_primary_creator' AND status = 'active'
                """,
                (self._creator_party_id,),
            )
        ).fetchone()
        row = await (
            await connection.execute(
                """
                SELECT subject.subject_id, revision.semantic_payload
                FROM armi.subjects AS subject
                JOIN armi.subject_component_heads AS head
                  ON head.subject_id = subject.subject_id
                 AND head.component_kind = 'life_mode'
                JOIN armi.subject_component_revisions AS revision
                  ON revision.component_revision_id = head.current_revision_id
                WHERE subject.singleton_key = 1
                """
            )
        ).fetchone()
        if creator is None or row is None or not isinstance(row[0], UUID):
            raise ActivityViolation("ACTIVITY-QUERY-UNAVAILABLE")
        payload = row[1]
        if not isinstance(payload, dict):
            raise ActivityViolation("ACTIVITY-QUERY-UNAVAILABLE")
        active = cast(dict[str, object], payload).get("active_activities")
        if type(active) is not list:
            raise ActivityViolation("ACTIVITY-QUERY-UNAVAILABLE")
        active_values = cast(list[object], active)
        if len(active_values) > 1 or any(
            type(item) is not str for item in active_values
        ):
            raise ActivityViolation("ACTIVITY-QUERY-UNAVAILABLE")
        return row[0], frozenset(cast(list[str], active_values))

    @staticmethod
    def _activity(row: tuple[Any, ...], focused: frozenset[str]) -> CreatorActivityItem:
        return CreatorActivityItem(
            activity_id=row[0],
            activity_kind=cast(Literal["self_directed"], str(row[1])),
            status=ActivityStatus(str(row[2])),
            goal=str(row[3]),
            progress_summary=None if row[4] is None else str(row[4]),
            waiting_kind=(None if row[5] is None else ActivityWaitingKind(str(row[5]))),
            waiting_summary=None if row[6] is None else str(row[6]),
            resume_not_before=row[7],
            terminal_reason=None if row[8] is None else str(row[8]),
            revision_no=int(row[9]),
            head_version=int(row[10]),
            transition_kind=ActivityTransition(str(row[11])),
            is_focused=str(row[0]) in focused,
            created_at=row[12],
            updated_at=row[13],
        )

    @staticmethod
    def _timeline_item(row: tuple[Any, ...]) -> CreatorActivityTimelineItem:
        return CreatorActivityTimelineItem(
            event_id=row[0],
            event_kind=cast(ActivityTimelineKind, str(row[1])),
            resulting_status=None if row[2] is None else ActivityStatus(str(row[2])),
            summary=None if row[3] is None else str(row[3]),
            review_not_before=row[4],
            occurred_at=row[5],
        )


__all__ = ("PostgreSQLActivityRead",)
