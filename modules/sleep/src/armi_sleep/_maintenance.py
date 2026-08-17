"""PostgreSQL checkpoints and wake requests for an active maintenance session."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid7

from armi_kernel.application import (
    AuditDraft,
    AuditEventId,
    AuditReference,
    AuditResultStatus,
    AuditSensitivity,
)
from armi_kernel.contracts import Purpose, SubjectId, TraceId
from armi_runtime_foundation import PostgreSQLRuntimeUnitOfWork

from ._domain import (
    MaintenancePhase,
    MaintenancePhaseState,
    MaintenanceResultStatus,
    plan_maintenance_checkpoint,
)
from .api import (
    MaintenanceOpportunityOutcome,
    MaintenanceOpportunityStatus,
    MaintenanceProgress,
    SleepOpportunityDraft,
    SleepOpportunityPort,
    SleepRuntimeFactsPort,
    SleepViolation,
)


class PostgreSQLMaintenanceRepository:
    """Advance the single active maintenance session through durable checkpoints."""

    __slots__ = ("_opportunities", "_runtime")

    def __init__(
        self,
        runtime: SleepRuntimeFactsPort,
        opportunities: SleepOpportunityPort,
    ) -> None:
        self._runtime = runtime
        self._opportunities = opportunities

    async def maintain_window(
        self,
        unit_of_work: PostgreSQLRuntimeUnitOfWork,
        *,
        consideration_after_seconds: int,
        deadline_after_seconds: int,
    ) -> MaintenanceOpportunityOutcome:
        """Admit the current sleep window or force its objective deadline."""

        fence = unit_of_work.runtime_fence
        if fence is None:
            raise SleepViolation("SLEEP-FENCE-REQUIRED")
        connection = unit_of_work.transaction
        last = await (
            await connection.execute(
                """
                SELECT maintenance_session_id, finished_at
                FROM armi.maintenance_sessions
                WHERE subject_id=%s AND life_generation_id=%s
                  AND finished_at IS NOT NULL
                ORDER BY finished_at DESC LIMIT 1
                """,
                (fence.subject_id, fence.life_generation_id),
            )
        ).fetchone()
        runtime = await self._runtime.snapshot(unit_of_work)
        anchor_kind = "maintenance_session" if last is not None else "life_generation"
        anchor_ref = last[0] if last is not None else fence.life_generation_id
        anchor_at = last[1] if last is not None else runtime.generation_created_at
        consideration_at = anchor_at + timedelta(seconds=consideration_after_seconds)
        deadline_at = anchor_at + timedelta(seconds=deadline_after_seconds)
        now = datetime.now(UTC)
        if now >= deadline_at:
            session_id = uuid7()
            revision_id = uuid7()
            inserted = await (
                await connection.execute(
                    """
                    INSERT INTO armi.maintenance_sessions (
                        maintenance_session_id, subject_id, life_generation_id,
                        origin_opportunity_id, cycle_anchor_kind, cycle_anchor_ref,
                        consideration_at, deadline_at,
                        trigger_kind, sleep_decision_id, started_subject_version,
                        started_state_epoch, current_revision_id) VALUES (
                        %s, %s, %s, NULL, %s, %s, %s, %s,
                        'system_deadline', NULL, %s, %s, %s)
                    ON CONFLICT (subject_id, life_generation_id, cycle_anchor_ref)
                    DO NOTHING RETURNING maintenance_session_id
                    """,
                    (
                        session_id,
                        fence.subject_id,
                        fence.life_generation_id,
                        anchor_kind,
                        anchor_ref,
                        consideration_at,
                        deadline_at,
                        runtime.subject_version,
                        runtime.state_epoch,
                        revision_id,
                    ),
                )
            ).fetchone()
            if inserted is not None:
                await connection.execute(
                    """
                    INSERT INTO armi.maintenance_session_revisions (
                        maintenance_revision_id, maintenance_session_id,
                        revision_no, previous_revision_id, phase,
                        result_status, transition_kind) VALUES (
                        %s, %s, 1, NULL, 'preparing', 'running', 'started')
                    """,
                    (revision_id, session_id),
                )
            await self._opportunities.cancel_sleep_source(
                connection,
                subject_id=fence.subject_id,
                source_kind="maintenance_window",
                source_ref=anchor_ref,
            )
            return MaintenanceOpportunityOutcome(
                MaintenanceOpportunityStatus.REJECTED,
                None,
                "LIFE-MAINTENANCE-DEADLINE",
            )
        if now < consideration_at:
            return MaintenanceOpportunityOutcome(
                MaintenanceOpportunityStatus.REJECTED,
                None,
                "LIFE-MAINTENANCE-NOT-DUE",
            )
        admitted = await self._opportunities.admit_sleep(
            connection,
            SleepOpportunityDraft(
                fence.subject_id,
                "consider_sleep",
                "maintenance_window",
                anchor_ref,
                1,
                consideration_at,
                deadline_at,
            ),
        )
        if not admitted.inserted:
            if admitted.opportunity_id is None:
                raise SleepViolation("SLEEP-SOURCE-STALE")
            return MaintenanceOpportunityOutcome(
                MaintenanceOpportunityStatus.DUPLICATE, admitted.opportunity_id
            )
        return MaintenanceOpportunityOutcome(
            MaintenanceOpportunityStatus.ADMITTED, admitted.opportunity_id
        )

    async def maintain_active_session(
        self,
        unit_of_work: PostgreSQLRuntimeUnitOfWork,
        *,
        quiet_seconds: int,
    ) -> MaintenanceProgress | None:
        """Advance one maintenance checkpoint, or wait at a safe boundary."""

        fence = unit_of_work.runtime_fence
        if fence is None:
            raise SleepViolation("SLEEP-FENCE-REQUIRED")
        connection = unit_of_work.transaction
        row = await (
            await connection.execute(
                """
                SELECT session.maintenance_session_id, session.head_version,
                       session.wake_request_id, session.quiet_until,
                       revision.maintenance_revision_id, revision.revision_no,
                       revision.phase, revision.result_status
                FROM armi.maintenance_sessions AS session
                JOIN armi.maintenance_session_revisions AS revision
                  ON revision.maintenance_revision_id = session.current_revision_id
                WHERE session.subject_id = %s
                  AND session.life_generation_id = %s
                  AND session.finished_at IS NULL
                FOR UPDATE OF session
                """,
                (fence.subject_id, fence.life_generation_id),
            )
        ).fetchone()
        if row is None:
            return None
        session_id: UUID = row[0]
        head_version = int(row[1])
        wake_requested = row[2] is not None
        quiet_until = row[3]
        revision_id: UUID = row[4]
        revision_no = int(row[5])
        phase = MaintenancePhase(str(row[6]))
        result = MaintenanceResultStatus(str(row[7]))
        if result is not MaintenanceResultStatus.RUNNING or head_version != revision_no:
            raise SleepViolation("SLEEP-MAINTENANCE-STATE")

        safe = await self._runtime.safe_for_maintenance(unit_of_work)
        if not safe:
            return MaintenanceProgress(
                session_id,
                phase,
                result,
                head_version,
                "LIFE-MAINTENANCE-WAITING-SAFE-POINT",
            )

        now = datetime.now(UTC)
        if phase is MaintenancePhase.LIFE_QUIET and quiet_until is None:
            raise SleepViolation("SLEEP-MAINTENANCE-STATE")
        next_quiet_until = quiet_until
        if wake_requested:
            await self._opportunities.cancel_sleep_source(
                connection,
                subject_id=fence.subject_id,
                source_kind="maintenance_phase_revision",
                source_ref=revision_id,
            )
        elif phase in {
            MaintenancePhase.MEMORY_MAINTENANCE,
            MaintenancePhase.SELF_CHECK,
            MaintenancePhase.REFLECT_SELF,
            MaintenancePhase.REFLECT_MIND,
            MaintenancePhase.REFLECT_PROMPT,
        }:
            completed = await (
                await connection.execute(
                    """
                    SELECT 1
                    FROM armi.maintenance_phase_results
                    WHERE maintenance_session_id = %s
                      AND maintenance_revision_id = %s
                      AND expected_head_version = %s
                    """,
                    (session_id, revision_id, head_version),
                )
            ).fetchone()
            if completed is None:
                opportunity_id, admitted = await self._admit_phase_work(
                    unit_of_work,
                    subject_id=fence.subject_id,
                    session_id=session_id,
                    revision_id=revision_id,
                    head_version=head_version,
                    phase=phase,
                )
                if opportunity_id is None:
                    failed_revision_id = uuid7()
                    await connection.execute(
                        """
                        INSERT INTO armi.maintenance_session_revisions (
                            maintenance_revision_id, maintenance_session_id,
                            revision_no, previous_revision_id, phase,
                            result_status, transition_kind) VALUES (
                            %s, %s, %s, %s, %s,
                            'failed', 'system_failed')
                        """,
                        (
                            failed_revision_id,
                            session_id,
                            revision_no + 1,
                            revision_id,
                            phase.value,
                        ),
                    )
                    failed_update = await connection.execute(
                        """
                        UPDATE armi.maintenance_sessions
                        SET current_revision_id = %s,
                            head_version = head_version + 1,
                            finished_at = statement_timestamp()
                        WHERE maintenance_session_id = %s
                          AND current_revision_id = %s
                          AND head_version = %s
                          AND finished_at IS NULL
                        """,
                        (
                            failed_revision_id,
                            session_id,
                            revision_id,
                            head_version,
                        ),
                    )
                    if failed_update.rowcount != 1:
                        raise SleepViolation("SLEEP-MAINTENANCE-STALE")
                    await unit_of_work.audit.append(
                        AuditDraft(
                            AuditEventId(uuid7()),
                            AuditReference("runtime", unit_of_work.environment_id),
                            Purpose("life.maintenance.work"),
                            "life.maintenance.work.failed",
                            AuditReference("maintenance_session", session_id),
                            AuditResultStatus.FAILED,
                            TraceId(failed_revision_id.hex),
                            AuditSensitivity.PRIVATE,
                            subject_id=SubjectId(fence.subject_id),
                            request=AuditReference("maintenance_revision", revision_id),
                        )
                    )
                    return MaintenanceProgress(
                        session_id,
                        phase,
                        MaintenanceResultStatus.FAILED,
                        head_version + 1,
                        "LIFE-MAINTENANCE-WORK-FAILED",
                    )
                if admitted:
                    await unit_of_work.audit.append(
                        AuditDraft(
                            AuditEventId(uuid7()),
                            AuditReference("runtime", unit_of_work.environment_id),
                            Purpose("life.maintenance.work"),
                            "life.maintenance.work.admitted",
                            AuditReference("opportunity", opportunity_id),
                            AuditResultStatus.ACCEPTED,
                            TraceId(opportunity_id.hex),
                            AuditSensitivity.PRIVATE,
                            subject_id=SubjectId(fence.subject_id),
                            request=AuditReference("maintenance_revision", revision_id),
                        )
                    )
                return MaintenanceProgress(
                    session_id,
                    phase,
                    result,
                    head_version,
                    (
                        "LIFE-MAINTENANCE-WORK-ADMITTED"
                        if admitted
                        else "LIFE-MAINTENANCE-WORK-PENDING"
                    ),
                    opportunity_id,
                    admitted,
                )

        plan = plan_maintenance_checkpoint(
            MaintenancePhaseState(phase, result),
            wake_requested=wake_requested,
            quiet_elapsed=quiet_until is not None and now >= quiet_until,
        )
        if plan is None:
            return MaintenanceProgress(
                session_id,
                phase,
                result,
                head_version,
                "LIFE-MAINTENANCE-QUIET",
            )
        following_phase = plan.following.phase
        following_result = plan.following.result_status
        if following_phase is MaintenancePhase.LIFE_QUIET:
            next_quiet_until = now + timedelta(seconds=quiet_seconds)

        next_revision_id = uuid7()
        await connection.execute(
            """
            INSERT INTO armi.maintenance_session_revisions (
                maintenance_revision_id, maintenance_session_id,
                revision_no, previous_revision_id, phase,
                result_status, transition_kind) VALUES (%s, %s, %s, %s, %s, %s, %s)
            """,
            (
                next_revision_id,
                session_id,
                revision_no + 1,
                revision_id,
                following_phase.value,
                following_result.value,
                plan.transition_kind,
            ),
        )
        updated = (
            await connection.execute(
                """
                UPDATE armi.maintenance_sessions
                SET current_revision_id = %s,
                    head_version = head_version + 1,
                    quiet_until = %s,
                    finished_at = CASE WHEN %s THEN statement_timestamp()
                                       ELSE NULL END
                WHERE maintenance_session_id = %s
                  AND current_revision_id = %s
                  AND head_version = %s
                  AND finished_at IS NULL
                """,
                (
                    next_revision_id,
                    next_quiet_until,
                    plan.terminal,
                    session_id,
                    revision_id,
                    head_version,
                ),
            )
        ).rowcount
        if updated != 1:
            raise SleepViolation("SLEEP-MAINTENANCE-STALE")
        await unit_of_work.audit.append(
            AuditDraft(
                AuditEventId(uuid7()),
                AuditReference("runtime", unit_of_work.environment_id),
                Purpose("life.maintenance"),
                "life.maintenance.checkpoint",
                AuditReference("maintenance_session", session_id),
                AuditResultStatus.APPLIED,
                TraceId(next_revision_id.hex),
                AuditSensitivity.PRIVATE,
                subject_id=SubjectId(fence.subject_id),
                request=AuditReference("maintenance_revision", revision_id),
            )
        )
        return MaintenanceProgress(
            session_id,
            following_phase,
            following_result,
            head_version + 1,
            (
                "LIFE-MAINTENANCE-INTERRUPTED"
                if following_result is MaintenanceResultStatus.INTERRUPTED
                else "LIFE-MAINTENANCE-COMPLETED"
                if following_result is MaintenanceResultStatus.COMPLETED
                else "LIFE-MAINTENANCE-ADVANCED"
            ),
        )

    async def request_emergency_wake(
        self,
        unit_of_work: PostgreSQLRuntimeUnitOfWork,
        *,
        session_id: UUID,
        request_id: UUID,
    ) -> UUID:
        """Record one idempotent wake request without forcing a response."""

        if session_id.version != 7 or request_id.version != 7:
            raise SleepViolation("SLEEP-WAKE-REQUEST")
        fence = unit_of_work.runtime_fence
        if fence is None:
            raise SleepViolation("SLEEP-FENCE-REQUIRED")
        connection = unit_of_work.transaction
        row = await (
            await connection.execute(
                """
                SELECT maintenance_session_id, wake_request_id, finished_at
                FROM armi.maintenance_sessions
                WHERE maintenance_session_id = %s
                  AND subject_id = %s AND life_generation_id = %s
                FOR UPDATE
                """,
                (session_id, fence.subject_id, fence.life_generation_id),
            )
        ).fetchone()
        if row is None or (row[2] is not None and row[1] is None):
            raise SleepViolation("SLEEP-MAINTENANCE-NOT-ACTIVE")
        existing = row[1]
        if existing is None:
            await connection.execute(
                """
                UPDATE armi.maintenance_sessions
                SET wake_request_id = %s,
                    wake_requested_at = statement_timestamp()
                WHERE maintenance_session_id = %s
                  AND wake_request_id IS NULL
                  AND finished_at IS NULL
                """,
                (request_id, session_id),
            )
            await unit_of_work.audit.append(
                AuditDraft(
                    AuditEventId(uuid7()),
                    AuditReference("runtime", unit_of_work.environment_id),
                    Purpose("life.maintenance.wake"),
                    "life.maintenance.wake_requested",
                    AuditReference("maintenance_session", session_id),
                    AuditResultStatus.APPLIED,
                    TraceId(request_id.hex),
                    AuditSensitivity.PRIVATE,
                    subject_id=SubjectId(fence.subject_id),
                    request=AuditReference("wake_request", request_id),
                )
            )
        return session_id

    async def active_session_id(
        self,
        unit_of_work: PostgreSQLRuntimeUnitOfWork,
    ) -> UUID | None:
        """Return the active session identity inside the current Runtime fence."""

        fence = unit_of_work.runtime_fence
        if fence is None:
            raise SleepViolation("SLEEP-FENCE-REQUIRED")
        connection = unit_of_work.transaction
        row = await (
            await connection.execute(
                """
                SELECT maintenance_session_id
                FROM armi.maintenance_sessions
                WHERE subject_id = %s AND life_generation_id = %s
                  AND finished_at IS NULL
                """,
                (fence.subject_id, fence.life_generation_id),
            )
        ).fetchone()
        return None if row is None else row[0]

    async def _admit_phase_work(
        self,
        unit_of_work: PostgreSQLRuntimeUnitOfWork,
        *,
        subject_id: UUID,
        session_id: UUID,
        revision_id: UUID,
        head_version: int,
        phase: MaintenancePhase,
    ) -> tuple[UUID | None, bool]:
        purpose = {
            MaintenancePhase.MEMORY_MAINTENANCE: "maintain_subjective_memory",
            MaintenancePhase.SELF_CHECK: "perform_subject_self_check",
            MaintenancePhase.REFLECT_SELF: "reflect_self",
            MaintenancePhase.REFLECT_MIND: "reflect_mind",
            MaintenancePhase.REFLECT_PROMPT: "reflect_prompt",
        }[phase]
        first = await self._opportunities.admit_sleep(
            unit_of_work.transaction,
            SleepOpportunityDraft(
                subject_id,
                purpose,
                "maintenance_phase_revision",
                revision_id,
                head_version,
                datetime.now(UTC),
            ),
        )
        return first.opportunity_id, first.inserted


__all__ = ("MaintenanceProgress", "PostgreSQLMaintenanceRepository")
