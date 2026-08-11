"""PostgreSQL checkpoints and wake requests for an active maintenance session."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid7

from armi_kernel.application import (
    AuditDraft,
    AuditEventId,
    AuditReference,
    AuditResultStatus,
    AuditSensitivity,
    LifeViolation,
    MaintenancePhase,
    MaintenancePhaseState,
    MaintenanceResultStatus,
    plan_maintenance_checkpoint,
)
from armi_kernel.contracts import Purpose, SubjectId, TraceId

from .unit_of_work import PostgreSQLUnitOfWork


@dataclass(frozen=True, slots=True)
class MaintenanceProgress:
    session_id: UUID
    phase: MaintenancePhase
    result_status: MaintenanceResultStatus
    head_version: int
    reason_code: str
    opportunity_id: UUID | None = None
    opportunity_admitted: bool = False


class PostgreSQLMaintenanceRepository:
    """Advance the single active maintenance session through durable checkpoints."""

    async def maintain_active_session(
        self,
        unit_of_work: PostgreSQLUnitOfWork,
        *,
        quiet_seconds: int,
    ) -> MaintenanceProgress | None:
        """Advance one maintenance checkpoint, or wait at a safe boundary."""

        fence = unit_of_work.runtime_fence
        if fence is None:
            raise LifeViolation("LIFE-FENCE-REQUIRED")
        connection = unit_of_work._connection_for_repository()  # pyright: ignore[reportPrivateUsage]
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
                JOIN armi.subjects AS subject
                  ON subject.subject_id = session.subject_id
                 AND subject.status = 'active'
                JOIN armi.life_generations AS generation
                  ON generation.life_generation_id = session.life_generation_id
                 AND generation.subject_id = session.subject_id
                 AND generation.status = 'active'
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
            raise LifeViolation("LIFE-MAINTENANCE-STATE")

        safe_row = await (
            await connection.execute(
                """
                SELECT NOT EXISTS (
                    SELECT 1 FROM armi.cognitive_episodes
                    WHERE subject_id = %s
                      AND status NOT IN (
                          'completed', 'stale', 'failed', 'cancelled',
                          'candidate_rejected'
                      )
                ) AND NOT EXISTS (
                    SELECT 1 FROM armi.durable_work
                    WHERE subject_id = %s AND status = 'leased'
                ) AND NOT EXISTS (
                    SELECT 1 FROM armi.effects
                    WHERE subject_id = %s
                      AND status IN ('registered', 'dispatching')
                )
                """,
                (fence.subject_id, fence.subject_id, fence.subject_id),
            )
        ).fetchone()
        safe = bool(safe_row is not None and safe_row[0])
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
            raise LifeViolation("LIFE-MAINTENANCE-STATE")
        next_quiet_until = quiet_until
        if wake_requested:
            await connection.execute(
                """
                UPDATE armi.opportunities
                SET current_disposition = 'cancelled',
                    resolved_at = statement_timestamp()
                WHERE subject_id = %s
                  AND source_kind = 'maintenance_phase_revision'
                  AND source_ref = %s
                  AND current_disposition = 'open'
                """,
                (fence.subject_id, revision_id),
            )
        elif phase in {
            MaintenancePhase.MEMORY_MAINTENANCE,
            MaintenancePhase.SELF_CHECK,
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
                opportunity_id, admitted = await _admit_phase_work(
                    connection,
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
                        raise LifeViolation("LIFE-MAINTENANCE-STALE")
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
            raise LifeViolation("LIFE-MAINTENANCE-STALE")
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
        unit_of_work: PostgreSQLUnitOfWork,
        *,
        session_id: UUID,
        request_id: UUID,
    ) -> UUID:
        """Record one idempotent wake request without forcing a response."""

        if session_id.version != 7 or request_id.version != 7:
            raise LifeViolation("LIFE-WAKE-REQUEST")
        fence = unit_of_work.runtime_fence
        if fence is None:
            raise LifeViolation("LIFE-FENCE-REQUIRED")
        connection = unit_of_work._connection_for_repository()  # pyright: ignore[reportPrivateUsage]
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
            raise LifeViolation("LIFE-MAINTENANCE-NOT-ACTIVE")
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
        unit_of_work: PostgreSQLUnitOfWork,
    ) -> UUID | None:
        """Return the active session identity inside the current Runtime fence."""

        fence = unit_of_work.runtime_fence
        if fence is None:
            raise LifeViolation("LIFE-FENCE-REQUIRED")
        connection = unit_of_work._connection_for_repository()  # pyright: ignore[reportPrivateUsage]
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
    connection: Any,
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
    }[phase]
    opportunity_id = uuid7()
    row = await (
        await connection.execute(
            """
            INSERT INTO armi.opportunities (
                opportunity_id, evidence_id, subject_id, scene_id,
                context_party_id, purpose, eligibility_status,
                current_disposition, root_opportunity_id, reconsideration_no,
                source_kind, source_ref, source_version,
                activity_id) VALUES (
                %s, NULL, %s, NULL, NULL, %s, 'eligible', 'open', %s, 0,
                'maintenance_phase_revision', %s, %s, NULL)
            ON CONFLICT (
                subject_id, source_kind, source_ref, source_version,
                purpose, reconsideration_no
            ) DO NOTHING
            RETURNING opportunity_id
            """,
            (
                opportunity_id,
                subject_id,
                purpose,
                opportunity_id,
                revision_id,
                head_version,
            ),
        )
    ).fetchone()
    if row is not None:
        return row[0], True
    existing = await (
        await connection.execute(
            """
            SELECT opportunity_id, current_disposition,
                   root_opportunity_id, reconsideration_no
            FROM armi.opportunities
            WHERE subject_id = %s
              AND source_kind = 'maintenance_phase_revision'
              AND source_ref = %s AND source_version = %s
              AND purpose = %s
            ORDER BY reconsideration_no DESC
            LIMIT 1
            """,
            (subject_id, revision_id, head_version, purpose),
        )
    ).fetchone()
    if existing is None:
        raise LifeViolation("LIFE-MAINTENANCE-SOURCE-STALE")
    if str(existing[1]) in {"open", "selected"}:
        return existing[0], False
    if int(existing[3]) == 1:
        return None, False
    successor_id = uuid7()
    successor = await (
        await connection.execute(
            """
            INSERT INTO armi.opportunities (
                opportunity_id, evidence_id, subject_id, scene_id,
                context_party_id, purpose, eligibility_status,
                current_disposition, root_opportunity_id,
                predecessor_opportunity_id, reconsideration_no,
                source_kind, source_ref, source_version,
                activity_id) VALUES (
                %s, NULL, %s, NULL, NULL, %s, 'eligible', 'open',
                %s, %s, 1, 'maintenance_phase_revision', %s, %s,
                NULL)
            ON CONFLICT (
                subject_id, source_kind, source_ref, source_version,
                purpose, reconsideration_no
            ) DO NOTHING
            RETURNING opportunity_id
            """,
            (
                successor_id,
                subject_id,
                purpose,
                existing[2],
                existing[0],
                revision_id,
                head_version,
            ),
        )
    ).fetchone()
    if successor is not None:
        return successor[0], True
    return None, False


__all__ = ("MaintenanceProgress", "PostgreSQLMaintenanceRepository")
