"""PostgreSQL-backed Creator maintenance projections."""

from __future__ import annotations

from typing import Any, cast
from uuid import UUID

from armi_kernel.contracts import OpaqueCursor
from armi_runtime_foundation import (
    PostgreSQLRuntimeUnitOfWorkFactory,
    PostgreSQLTransaction,
    ProjectionCursorCodec,
    ProjectionCursorInvalid,
    ProjectionCursorStale,
    RuntimeTransactionFailure,
)

from .api import (
    MAINTENANCE_PROJECTION_VERSION,
    CreatorMaintenanceSession,
    CreatorMaintenanceStatus,
    CreatorMaintenanceTimeline,
    CreatorMaintenanceTimelineItem,
    CreatorMaintenanceViolation,
    MaintenancePhase,
    MaintenanceResultStatus,
    MaintenanceTransitionKind,
    MaintenanceTriggerKind,
    MaintenanceWorkOutcome,
    SleepMaintenanceSnapshot,
)


def _snapshot(row: tuple[Any, ...]) -> SleepMaintenanceSnapshot:
    return SleepMaintenanceSnapshot(
        session_id=row[0],
        current_revision_id=row[1],
        head_version=int(row[2]),
        phase=MaintenancePhase(str(row[3])),
        trigger_kind=MaintenanceTriggerKind(str(row[4])),
    )


class PostgreSQLSleepRead:
    """Serve Runtime and Creator reads without exposing maintenance internals."""

    __slots__ = (
        "_creator_party_id",
        "_cursor",
        "_factory",
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
    ) -> None:
        self._creator_party_id = creator_party_id
        self._cursor = ProjectionCursorCodec(
            cursor_key, environment_id, creator_party_id
        )
        self._factory = factory
        self._subject_id = subject_id

    async def open(self) -> None:
        return None

    async def close(self) -> None:
        return None

    async def active_maintenance(
        self,
        transaction: PostgreSQLTransaction,
        *,
        subject_id: UUID,
    ) -> SleepMaintenanceSnapshot | None:
        row = await (
            await transaction.execute(
                """
                SELECT session.maintenance_session_id,
                       session.current_revision_id,
                       session.head_version, revision.phase, session.trigger_kind
                FROM armi.maintenance_sessions AS session
                JOIN armi.maintenance_session_revisions AS revision
                  ON revision.maintenance_revision_id = session.current_revision_id
                WHERE session.subject_id = %s
                  AND session.finished_at IS NULL
                """,
                (subject_id,),
            )
        ).fetchone()
        return None if row is None else _snapshot(row)

    async def candidate_maintenance(
        self,
        transaction: PostgreSQLTransaction,
        *,
        source_revision_id: UUID | None,
        expected_head_version: int | None,
    ) -> SleepMaintenanceSnapshot | None:
        if source_revision_id is None or expected_head_version is None:
            return None
        row = await (
            await transaction.execute(
                """
                SELECT session.maintenance_session_id,
                       session.current_revision_id,
                       session.head_version, revision.phase, session.trigger_kind
                FROM armi.maintenance_session_revisions AS revision
                JOIN armi.maintenance_sessions AS session
                  ON session.maintenance_session_id = revision.maintenance_session_id
                 AND session.current_revision_id = revision.maintenance_revision_id
                 AND session.head_version = %s
                 AND session.finished_at IS NULL
                WHERE revision.maintenance_revision_id = %s
                """,
                (expected_head_version, source_revision_id),
            )
        ).fetchone()
        return None if row is None else _snapshot(row)

    async def status(self) -> CreatorMaintenanceStatus:
        try:
            async with self._factory.unit_of_work(read_only=True) as unit_of_work:
                connection = unit_of_work.transaction
                subject_id = self._subject_id
                row = await (
                    await connection.execute(
                        """
                        SELECT session.maintenance_session_id,
                               session.trigger_kind, revision.phase,
                               revision.result_status, revision.revision_no,
                               session.head_version,
                               session.wake_request_id IS NOT NULL,
                               session.started_at, revision.created_at,
                               session.finished_at
                        FROM armi.maintenance_sessions AS session
                        JOIN armi.maintenance_session_revisions AS revision
                          ON revision.maintenance_revision_id
                            = session.current_revision_id
                         AND revision.maintenance_session_id
                            = session.maintenance_session_id
                        WHERE session.subject_id = %s
                        ORDER BY session.started_at DESC,
                                 session.maintenance_session_id DESC
                        LIMIT 1
                        """,
                        (subject_id,),
                    )
                ).fetchone()
                if row is None:
                    return CreatorMaintenanceStatus(None, 0)
                session = self._session(row)
                waiting_input_count = 0
        except CreatorMaintenanceViolation:
            raise
        except RuntimeTransactionFailure:
            raise CreatorMaintenanceViolation("MAINTENANCE-QUERY-UNAVAILABLE") from None
        return CreatorMaintenanceStatus(session, waiting_input_count)

    async def timeline(
        self, session_id: UUID, *, limit: int, cursor: OpaqueCursor | None = None
    ) -> CreatorMaintenanceTimeline:
        ceiling: int | None = None
        before: int | None = None
        if cursor is not None:
            try:
                page = self._cursor.decode(
                    cursor,
                    projection_version=MAINTENANCE_PROJECTION_VERSION,
                    resource_kind="maintenance-timeline",
                    resource_ref=str(session_id),
                    page_limit=limit,
                    query={},
                )
                ceiling = cast(int, page.snapshot_ceiling.get("revision_no"))
                before = cast(int, page.boundary.get("before_revision_no"))
            except ProjectionCursorStale:
                raise CreatorMaintenanceViolation(
                    "MAINTENANCE-QUERY-CURSOR-STALE"
                ) from None
            except TypeError, ValueError, ProjectionCursorInvalid:
                raise CreatorMaintenanceViolation("MAINTENANCE-QUERY-CURSOR") from None
            if (
                type(ceiling) is not int
                or ceiling < 1
                or type(before) is not int
                or before < 1
            ):
                raise CreatorMaintenanceViolation("MAINTENANCE-QUERY-CURSOR")
        try:
            async with self._factory.unit_of_work(read_only=True) as unit_of_work:
                connection = unit_of_work.transaction
                subject_id = self._subject_id
                visible = await (
                    await connection.execute(
                        """
                        SELECT 1 FROM armi.maintenance_sessions
                        WHERE maintenance_session_id = %s AND subject_id = %s
                        """,
                        (session_id, subject_id),
                    )
                ).fetchone()
                if visible is not None and ceiling is None:
                    ceiling_row = await (
                        await connection.execute(
                            """SELECT max(revision_no)
                               FROM armi.maintenance_session_revisions
                               WHERE maintenance_session_id=%s""",
                            (session_id,),
                        )
                    ).fetchone()
                    if ceiling_row is None or ceiling_row[0] is None:
                        raise CreatorMaintenanceViolation("MAINTENANCE-QUERY-NOT-FOUND")
                    ceiling = int(ceiling_row[0])
                rows = (
                    ()
                    if visible is None
                    else await (
                        await connection.execute(
                            """
                        SELECT revision.maintenance_revision_id,
                               revision.revision_no, revision.phase,
                               revision.result_status, revision.transition_kind,
                               revision.created_at, result.outcome,
                               result.creator_visible_problem
                        FROM armi.maintenance_session_revisions AS revision
                        LEFT JOIN armi.maintenance_phase_results AS result
                          ON result.maintenance_revision_id
                            = revision.maintenance_revision_id
                        WHERE revision.maintenance_session_id = %s
                          AND revision.revision_no<=%s
                          AND (%s::bigint IS NULL OR revision.revision_no<%s)
                        ORDER BY revision.revision_no DESC
                        LIMIT %s
                        """,
                            (session_id, ceiling, before, before, limit + 1),
                        )
                    ).fetchall()
                )
        except CreatorMaintenanceViolation:
            raise
        except RuntimeTransactionFailure:
            raise CreatorMaintenanceViolation("MAINTENANCE-QUERY-UNAVAILABLE") from None
        if visible is None:
            raise CreatorMaintenanceViolation("MAINTENANCE-QUERY-NOT-FOUND")
        page_rows = rows[:limit]
        next_cursor = None
        if len(rows) > limit and page_rows:
            next_cursor = self._cursor.encode(
                projection_version=MAINTENANCE_PROJECTION_VERSION,
                resource_kind="maintenance-timeline",
                resource_ref=str(session_id),
                page_limit=limit,
                query={},
                snapshot_ceiling={"revision_no": ceiling},
                boundary={"before_revision_no": int(page_rows[-1][1])},
            )
        return CreatorMaintenanceTimeline(
            session_id,
            tuple(self._timeline_item(row) for row in page_rows),
            next_cursor,
        )

    @staticmethod
    def _session(row: tuple[Any, ...]) -> CreatorMaintenanceSession:
        return CreatorMaintenanceSession(
            session_id=row[0],
            trigger_kind=MaintenanceTriggerKind(str(row[1])),
            phase=MaintenancePhase(str(row[2])),
            result_status=MaintenanceResultStatus(str(row[3])),
            revision_no=int(row[4]),
            head_version=int(row[5]),
            wake_requested=bool(row[6]),
            started_at=row[7],
            updated_at=row[8],
            finished_at=row[9],
        )

    @staticmethod
    def _timeline_item(row: tuple[Any, ...]) -> CreatorMaintenanceTimelineItem:
        return CreatorMaintenanceTimelineItem(
            revision_id=row[0],
            revision_no=int(row[1]),
            phase=MaintenancePhase(str(row[2])),
            result_status=MaintenanceResultStatus(str(row[3])),
            transition_kind=cast(MaintenanceTransitionKind, str(row[4])),
            occurred_at=row[5],
            work_outcome=(
                None if row[6] is None else MaintenanceWorkOutcome(str(row[6]))
            ),
            problem_summary=None if row[7] is None else str(row[7]),
        )


__all__ = ("PostgreSQLSleepRead",)
