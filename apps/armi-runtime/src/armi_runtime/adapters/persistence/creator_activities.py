"""PostgreSQL-backed Creator Activity projections."""

from __future__ import annotations

from typing import Any, Literal, cast
from uuid import UUID

import psycopg
from armi_kernel.application import (
    ActivityStatus,
    ActivityTimelineKind,
    ActivityTransition,
    ActivityWaitingKind,
    CreatorActivityItem,
    CreatorActivityPage,
    CreatorActivityTimeline,
    CreatorActivityTimelineItem,
    CreatorActivityViolation,
)
from psycopg.pq import TransactionStatus
from psycopg_pool import AsyncConnectionPool, PoolTimeout

from .role_policy import physical_role_name

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


class PostgreSQLCreatorActivityQuery:
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
        environment_id: UUID,
        creator_party_id: UUID,
        pool_timeout_seconds: int,
    ) -> None:
        self._creator_party_id = creator_party_id
        self._expected_role = physical_role_name(environment_id, "runtime")
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
                raise CreatorActivityViolation("ACTIVITY-QUERY-UNAVAILABLE")

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
            raise CreatorActivityViolation("ACTIVITY-QUERY-UNAVAILABLE") from None

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
        except CreatorActivityViolation:
            raise
        except psycopg.Error, PoolTimeout:
            raise CreatorActivityViolation("ACTIVITY-QUERY-UNAVAILABLE") from None
        return CreatorActivityPage(
            tuple(self._activity(row, focused) for row in rows[:_PAGE_SIZE]),
            len(rows) > _PAGE_SIZE,
        )

    async def timeline(self, activity_id: UUID) -> CreatorActivityTimeline:
        if type(activity_id) is not UUID or activity_id.version != 7:
            raise CreatorActivityViolation("ACTIVITY-QUERY-ID")
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
                    raise CreatorActivityViolation("ACTIVITY-QUERY-NOT-FOUND")
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
        except CreatorActivityViolation:
            raise
        except psycopg.Error, PoolTimeout:
            raise CreatorActivityViolation("ACTIVITY-QUERY-UNAVAILABLE") from None
        return CreatorActivityTimeline(
            activity_id,
            tuple(self._timeline_item(row) for row in rows[:_PAGE_SIZE]),
            len(rows) > _PAGE_SIZE,
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
            raise CreatorActivityViolation("ACTIVITY-QUERY-UNAVAILABLE")
        payload = row[1]
        if not isinstance(payload, dict):
            raise CreatorActivityViolation("ACTIVITY-QUERY-UNAVAILABLE")
        active = cast(dict[str, object], payload).get("active_activities")
        if type(active) is not list:
            raise CreatorActivityViolation("ACTIVITY-QUERY-UNAVAILABLE")
        active_values = cast(list[object], active)
        if len(active_values) > 1 or any(
            type(item) is not str for item in active_values
        ):
            raise CreatorActivityViolation("ACTIVITY-QUERY-UNAVAILABLE")
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


__all__ = ("PostgreSQLCreatorActivityQuery",)
