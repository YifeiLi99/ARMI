"""PostgreSQL-backed Activity reads and Creator projections."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal, cast
from uuid import UUID, uuid7

import rfc8785
from armi_kernel.contracts import Instant, OpaqueCursor
from armi_runtime_foundation import (
    PostgreSQLRuntimeUnitOfWorkFactory,
    PostgreSQLTransaction,
    ProjectionCursorCodec,
    ProjectionCursorInvalid,
    ProjectionCursorStale,
    RuntimeTransactionFailure,
)

from .api import (
    ACTIVITY_PROJECTION_VERSION,
    ActivityCandidateSnapshot,
    ActivityContextTarget,
    ActivityFocusReadPort,
    ActivityHeadSnapshot,
    ActivityId,
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


class PostgreSQLActivityRead:
    async def need_information_after(
        self,
        transaction: PostgreSQLTransaction,
        *,
        episode_ids: tuple[UUID, ...],
    ) -> datetime | None:
        if not episode_ids:
            return None
        row = await (
            await transaction.execute(
                """SELECT max(decided_at) FROM armi.activity_decisions
                   WHERE cognitive_episode_id = ANY(%s)
                     AND decision_kind='need_information'""",
                (episode_ids,),
            )
        ).fetchone()
        return None if row is None else row[0]

    """Read the current subject's bounded Creator-visible Activity projection."""

    __slots__ = (
        "_creator_party_id",
        "_cursor",
        "_factory",
        "_focus",
        "_subject_id",
    )

    def __init__(
        self,
        factory: PostgreSQLRuntimeUnitOfWorkFactory,
        *,
        subject_id: UUID,
        creator_party_id: UUID,
        environment_id: UUID,
        cursor_key: bytes,
        focus: ActivityFocusReadPort,
    ) -> None:
        self._creator_party_id = creator_party_id
        self._cursor = ProjectionCursorCodec(
            cursor_key, environment_id, creator_party_id
        )
        self._factory = factory
        self._focus = focus
        self._subject_id = subject_id

    async def open(self) -> None:
        return None

    async def close(self) -> None:
        return None

    async def list_current(
        self, *, limit: int, cursor: OpaqueCursor | None = None
    ) -> CreatorActivityPage:
        snapshot_at: datetime | None = None
        boundary: tuple[datetime, UUID] | None = None
        if cursor is not None:
            try:
                page = self._cursor.decode(
                    cursor,
                    projection_version=ACTIVITY_PROJECTION_VERSION,
                    resource_kind="activity-current",
                    resource_ref=None,
                    page_limit=limit,
                    query={},
                )
                snapshot_at = Instant.from_wire(page.snapshot_ceiling["at"]).value
                boundary = (
                    Instant.from_wire(page.boundary["before_at"]).value,
                    UUID(str(page.boundary["before_id"])),
                )
            except ProjectionCursorStale:
                raise ActivityViolation("ACTIVITY-CURSOR-STALE") from None
            except KeyError, TypeError, ValueError, ProjectionCursorInvalid:
                raise ActivityViolation("ACTIVITY-CURSOR") from None
        try:
            async with self._factory.unit_of_work(read_only=True) as unit_of_work:
                connection = unit_of_work.transaction
                if snapshot_at is None:
                    snapshot = await (
                        await connection.execute("SELECT statement_timestamp()")
                    ).fetchone()
                    if snapshot is None:
                        raise ActivityViolation("ACTIVITY-QUERY-UNAVAILABLE")
                    snapshot_at = cast(datetime, snapshot[0])
                subject_id = self._subject_id
                focused = frozenset(
                    str(item)
                    for item in await self._focus.active_activity_ids(
                        connection, subject_id=subject_id
                    )
                )
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
                        JOIN LATERAL (
                          SELECT candidate.* FROM armi.activity_revisions AS candidate
                          WHERE candidate.activity_id=activity.activity_id
                            AND candidate.created_at<=%s
                          ORDER BY candidate.revision_no DESC LIMIT 1
                        ) AS revision ON TRUE
                        WHERE activity.subject_id = %s
                          AND activity.created_at<=%s
                          AND (%s::timestamptz IS NULL OR
                               (revision.created_at,activity.activity_id)<(%s,%s))
                        ORDER BY revision.created_at DESC, activity.activity_id DESC
                        LIMIT %s
                        """,
                        (
                            snapshot_at,
                            subject_id,
                            snapshot_at,
                            None if boundary is None else boundary[0],
                            None if boundary is None else boundary[0],
                            None if boundary is None else boundary[1],
                            limit + 1,
                        ),
                    )
                ).fetchall()
        except ActivityViolation:
            raise
        except RuntimeTransactionFailure:
            raise ActivityViolation("ACTIVITY-QUERY-UNAVAILABLE") from None
        visible = rows[:limit]
        next_cursor = None
        if len(rows) > limit and visible:
            next_cursor = self._cursor.encode(
                projection_version=ACTIVITY_PROJECTION_VERSION,
                resource_kind="activity-current",
                resource_ref=None,
                page_limit=limit,
                query={},
                snapshot_ceiling={"at": Instant(snapshot_at).to_wire()},
                boundary={
                    "before_at": Instant(visible[-1][13]).to_wire(),
                    "before_id": str(visible[-1][0]),
                },
            )
        return CreatorActivityPage(
            tuple(self._activity(row, focused) for row in visible), next_cursor
        )

    async def timeline(
        self, activity_id: UUID, *, limit: int, cursor: OpaqueCursor | None = None
    ) -> CreatorActivityTimeline:
        ceiling: datetime | None = None
        boundary: tuple[datetime, UUID] | None = None
        if cursor is not None:
            try:
                page = self._cursor.decode(
                    cursor,
                    projection_version=ACTIVITY_PROJECTION_VERSION,
                    resource_kind="activity-timeline",
                    resource_ref=str(activity_id),
                    page_limit=limit,
                    query={},
                )
                ceiling = Instant.from_wire(page.snapshot_ceiling["at"]).value
                boundary = (
                    Instant.from_wire(page.boundary["before_at"]).value,
                    UUID(str(page.boundary["before_id"])),
                )
            except ProjectionCursorStale:
                raise ActivityViolation("ACTIVITY-CURSOR-STALE") from None
            except KeyError, TypeError, ValueError, ProjectionCursorInvalid:
                raise ActivityViolation("ACTIVITY-CURSOR") from None
        try:
            async with self._factory.unit_of_work(read_only=True) as unit_of_work:
                connection = unit_of_work.transaction
                subject_id = self._subject_id
                visible = await (
                    await connection.execute(
                        """
                        SELECT 1 FROM armi.activities
                        WHERE activity_id = %s AND subject_id = %s
                        """,
                        (activity_id, subject_id),
                    )
                ).fetchone()
                if ceiling is None:
                    snapshot = await (
                        await connection.execute("SELECT statement_timestamp()")
                    ).fetchone()
                    if snapshot is None:
                        raise ActivityViolation("ACTIVITY-QUERY-UNAVAILABLE")
                    ceiling = cast(datetime, snapshot[0])
                rows = (
                    ()
                    if visible is None
                    else await (
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
                          AND revision.created_at<=%s
                          AND (%s::timestamptz IS NULL OR
                               (revision.created_at,revision.activity_revision_id)<(%s,%s))
                        UNION ALL
                        SELECT decision.activity_decision_id,
                               decision.decision_kind,
                               NULL::text,
                               NULL::text,
                               decision.review_not_before,
                               decision.decided_at
                        FROM armi.activity_decisions AS decision
                        LEFT JOIN armi.activity_revisions AS result
                          ON result.activity_revision_id=decision.result_revision_id
                        WHERE decision.activity_id = %s
                          AND decision.decided_at<=%s
                          AND (decision.result_revision_id IS NULL OR result.created_at>%s)
                          AND (%s::timestamptz IS NULL OR
                               (decision.decided_at,decision.activity_decision_id)<(%s,%s))
                        ORDER BY 6 DESC, 1 DESC
                        LIMIT %s
                        """,
                            (
                                activity_id,
                                ceiling,
                                None if boundary is None else boundary[0],
                                None if boundary is None else boundary[0],
                                None if boundary is None else boundary[1],
                                activity_id,
                                ceiling,
                                ceiling,
                                None if boundary is None else boundary[0],
                                None if boundary is None else boundary[0],
                                None if boundary is None else boundary[1],
                                limit + 1,
                            ),
                        )
                    ).fetchall()
                )
        except ActivityViolation:
            raise
        except RuntimeTransactionFailure:
            raise ActivityViolation("ACTIVITY-QUERY-UNAVAILABLE") from None
        if visible is None:
            raise ActivityViolation("ACTIVITY-QUERY-NOT-FOUND")
        page_rows = rows[:limit]
        next_cursor = None
        if len(rows) > limit and page_rows:
            next_cursor = self._cursor.encode(
                projection_version=ACTIVITY_PROJECTION_VERSION,
                resource_kind="activity-timeline",
                resource_ref=str(activity_id),
                page_limit=limit,
                query={},
                snapshot_ceiling={"at": Instant(ceiling).to_wire()},
                boundary={
                    "before_at": Instant(page_rows[-1][5]).to_wire(),
                    "before_id": str(page_rows[-1][0]),
                },
            )
        return CreatorActivityTimeline(
            activity_id,
            tuple(self._timeline_item(row) for row in page_rows),
            next_cursor,
        )

    async def candidate_head(
        self,
        transaction: PostgreSQLTransaction,
        *,
        activity_id: UUID | None,
        expected_revision_id: UUID | None,
        expected_revision_no: int | None,
    ) -> ActivityCandidateSnapshot | None:
        if activity_id is None:
            return None
        row = await (
            await transaction.execute(
                """
                SELECT activity.activity_id, activity.current_revision_id,
                       activity.head_version, revision.status
                FROM armi.activities AS activity
                JOIN armi.activity_revisions AS revision
                  ON revision.activity_revision_id = activity.current_revision_id
                WHERE activity.activity_id = %s
                  AND activity.current_revision_id = %s
                  AND revision.revision_no = %s
                """,
                (activity_id, expected_revision_id, expected_revision_no),
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

    async def context_target(
        self,
        transaction: PostgreSQLTransaction,
        *,
        subject_id: UUID,
        activity_id: UUID,
    ) -> ActivityContextTarget | None:
        row = await (
            await transaction.execute(
                """
                SELECT activity.activity_id, revision.activity_revision_id,
                       activity.head_version, revision.status, revision.revision_no,
                       revision.goal, revision.next_safe_step,
                       revision.progress_summary, revision.waiting_condition,
                       revision.resumption_cue
                FROM armi.activities AS activity
                JOIN armi.activity_revisions AS revision
                  ON revision.activity_revision_id=activity.current_revision_id
                WHERE activity.subject_id=%s AND activity.activity_id=%s
                """,
                (subject_id, activity_id),
            )
        ).fetchone()
        if row is None:
            return None
        return ActivityContextTarget(
            activity_id=row[0],
            revision_id=row[1],
            head_version=int(row[2]),
            status=ActivityStatus(str(row[3])),
            canonical_state=rfc8785.dumps(
                {
                    "schema_version": "armi.activity-context-target.v1",
                    "activity_id": str(row[0]),
                    "revision_id": str(row[1]),
                    "head_version": int(row[2]),
                    "revision_no": int(row[4]),
                    "status": str(row[3]),
                    "goal": str(row[5]),
                    "next_safe_step": str(row[6]),
                    "progress_summary": None if row[7] is None else str(row[7]),
                    "waiting_condition": None if row[8] is None else str(row[8]),
                    "resumption_cue": None if row[9] is None else str(row[9]),
                }
            ),
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
                       revision.waiting_condition_kind,
                       revision.resume_not_before
                FROM armi.activities AS activity
                JOIN armi.activity_revisions AS revision
                  ON revision.activity_revision_id = activity.current_revision_id
                WHERE activity.subject_id = %s
                ORDER BY revision.created_at, activity.activity_id
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
                None,
                None if row[5] is None else ActivityWaitingKind(str(row[5])),
                row[6],
                False,
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
                  AND (%s::text IS NULL OR left(revision.goal || CASE WHEN revision.progress_summary IS NULL THEN '' ELSE ' — ' || revision.progress_summary END, 4096) ILIKE '%%' || %s::text || '%%')
                  AND (%s::timestamptz IS NULL OR (revision.created_at, 'activity'::text, activity.activity_id) < (%s::timestamptz, %s::text, %s::uuid))
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

    async def pause_failed_internal_work(
        self,
        transaction: PostgreSQLTransaction,
        *,
        subject_id: UUID,
        activity_id: UUID,
        expected_revision_id: UUID,
    ) -> UUID | None:
        revision_id = uuid7()
        row = await (
            await transaction.execute(
                """WITH current AS (
                     SELECT activity.head_version, revision.*
                     FROM armi.activities AS activity
                     JOIN armi.activity_revisions AS revision
                       ON revision.activity_revision_id=activity.current_revision_id
                     WHERE activity.subject_id=%s AND activity.activity_id=%s
                       AND activity.current_revision_id=%s
                       AND revision.status='in_progress'
                     FOR UPDATE OF activity
                   ), inserted AS (
                     INSERT INTO armi.activity_revisions (
                       activity_revision_id,activity_id,revision_no,
                       previous_revision_id,subject_commit_id,
                       candidate_validation_id,proposal_ref,goal,
                       progress_summary,waiting_condition,resumption_cue,
                       next_safe_step,status,terminal_reason,related_scene_id,
                       transition_kind,waiting_condition_kind,resume_not_before)
                     SELECT %s,activity_id,revision_no+1,
                       activity_revision_id,NULL,NULL,NULL,goal,progress_summary,
                       '内部工作连续失败;等待定时复查',
                       '定时复查后重新判断是否继续',next_safe_step,
                       'paused',NULL,related_scene_id,'system_pause',
                       'scheduled_review',statement_timestamp()+interval '60 seconds'
                     FROM current RETURNING activity_id
                   )
                   UPDATE armi.activities AS activity
                   SET current_revision_id=%s,head_version=head_version+1
                   FROM inserted WHERE activity.activity_id=inserted.activity_id
                   RETURNING activity.current_revision_id""",
                (
                    subject_id,
                    activity_id,
                    expected_revision_id,
                    revision_id,
                    revision_id,
                ),
            )
        ).fetchone()
        return None if row is None else row[0]

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
