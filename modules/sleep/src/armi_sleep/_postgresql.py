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
    MAINTENANCE_PROJECTION_KIND,
    CreatorMaintenanceSession,
    CreatorMaintenanceStatus,
    CreatorMaintenanceTimeline,
    CreatorMaintenanceViolation,
    MaintenancePhase,
    MaintenanceResultStatus,
    MaintenanceTriggerKind,
    SleepDecisionRecordPort,
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
        "_decisions",
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
        decisions: SleepDecisionRecordPort,
    ) -> None:
        self._decisions = decisions
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
                       session.head_version, session.phase, session.trigger_kind
                FROM armi.maintenance_sessions AS session
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
                       session.head_version, session.phase, session.trigger_kind
                FROM armi.maintenance_sessions AS session
                WHERE session.head_version = %s
                  AND session.finished_at IS NULL
                  AND session.current_revision_id = %s
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
                               session.trigger_kind, session.phase,
                               session.result_status, session.head_version,
                               session.head_version,
                               session.wake_request_id IS NOT NULL,
                               session.started_at, session.updated_at,
                               session.finished_at
                        FROM armi.maintenance_sessions AS session
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
                    projection_kind=MAINTENANCE_PROJECTION_KIND,
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
                rows = (
                    ()
                    if visible is None
                    else await self._decisions.maintenance_results(
                        connection,
                        session_id=session_id,
                        ceiling=ceiling,
                        before=before,
                        limit=limit + 1,
                    )
                )
                if ceiling is None and rows:
                    ceiling = rows[0].revision_no
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
                projection_kind=MAINTENANCE_PROJECTION_KIND,
                resource_kind="maintenance-timeline",
                resource_ref=str(session_id),
                page_limit=limit,
                query={},
                snapshot_ceiling={"revision_no": ceiling},
                boundary={"before_revision_no": page_rows[-1].revision_no},
            )
        return CreatorMaintenanceTimeline(
            session_id,
            tuple(page_rows),
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


__all__ = ("PostgreSQLSleepRead",)
