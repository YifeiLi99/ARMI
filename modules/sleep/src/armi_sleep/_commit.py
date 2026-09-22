"""PostgreSQL participant for sleep decisions and maintenance results."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid7

from armi_runtime_foundation import PostgreSQLTransaction

from ._application import SleepApplication
from .api import (
    CandidateMaintenanceDecisionDraft,
    CandidateSleepDecisionDraft,
    SleepCommitContext,
    SleepDecisionKind,
    SleepDecisionRecordPort,
    SleepViolation,
)


class PostgreSQLSleepCommit:
    __slots__ = ("_cognition", "_decisions")

    def __init__(
        self, cognition: SleepApplication, decisions: SleepDecisionRecordPort
    ) -> None:
        self._cognition = cognition
        self._decisions = decisions

    async def heads_match(
        self,
        transaction: PostgreSQLTransaction,
        *,
        context: SleepCommitContext,
        drafts: tuple[
            CandidateSleepDecisionDraft | CandidateMaintenanceDecisionDraft, ...
        ],
    ) -> bool:
        sleep, maintenance = self._decode(drafts)
        if sleep is not None and not await self._sleep_current(
            transaction, context=context, decision=sleep
        ):
            return False
        return maintenance is None or await self._maintenance_current(
            transaction, context=context, decision=maintenance
        )

    def requests_reconsideration(
        self,
        *,
        context: SleepCommitContext,
        drafts: tuple[
            CandidateSleepDecisionDraft | CandidateMaintenanceDecisionDraft, ...
        ],
    ) -> bool:
        sleep, maintenance = self._decode(drafts)
        if maintenance is not None or sleep is None:
            return False
        return (
            sleep.decision_kind is SleepDecisionKind.DEFER
            and context.reconsideration_no == 0
        )

    async def commit(
        self,
        transaction: PostgreSQLTransaction,
        *,
        context: SleepCommitContext,
        application_id: UUID,
        commit_id: UUID | None,
        resulting_subject_version: int,
        drafts: tuple[
            CandidateSleepDecisionDraft | CandidateMaintenanceDecisionDraft, ...
        ],
        committed_memory_ids: tuple[UUID, ...] = (),
    ) -> None:
        sleep, maintenance = self._decode(drafts)
        if sleep is not None:
            await self._insert_sleep_decision(
                transaction,
                context=context,
                application_id=application_id,
                decision=sleep,
                resulting_subject_version=resulting_subject_version,
            )
        if maintenance is not None:
            if commit_id is None:
                raise SleepViolation("SLEEP-MAINTENANCE-COMMIT")
            await self._record_maintenance_result(
                transaction,
                context=context,
                application_id=application_id,
                commit_id=commit_id,
                decision=maintenance,
                committed_memory_ids=committed_memory_ids,
            )

    async def affected_session_ids(
        self, transaction: PostgreSQLTransaction, validation_id: UUID
    ) -> tuple[UUID, ...]:
        episode_id = await self._decisions.sleep_episode_for_validation(
            transaction, validation_id
        )
        rows = await (
            await transaction.execute(
                """SELECT maintenance_session_id FROM armi.maintenance_sessions
                   WHERE sleep_episode_id=%s""",
                (episode_id,),
            )
        ).fetchall()
        result_session = await self._decisions.maintenance_session_for_validation(
            transaction, validation_id
        )
        sessions = {UUID(str(row[0])) for row in rows}
        if result_session is not None:
            sessions.add(result_session)
        return tuple(sorted(sessions))

    def _decode(
        self,
        drafts: tuple[
            CandidateSleepDecisionDraft | CandidateMaintenanceDecisionDraft, ...
        ],
    ) -> tuple[
        CandidateSleepDecisionDraft | None, CandidateMaintenanceDecisionDraft | None
    ]:
        sleep: CandidateSleepDecisionDraft | None = None
        maintenance: CandidateMaintenanceDecisionDraft | None = None
        for value in drafts:
            if isinstance(value, CandidateSleepDecisionDraft):
                if sleep is not None:
                    raise SleepViolation("SLEEP-CANDIDATE-COUNT")
                sleep = value
            else:
                if maintenance is not None:
                    raise SleepViolation("SLEEP-MAINTENANCE-COUNT")
                maintenance = value
        if sleep is not None and maintenance is not None:
            raise SleepViolation("SLEEP-OWNER-SHAPE")
        return sleep, maintenance

    @staticmethod
    async def _sleep_current(
        transaction: PostgreSQLTransaction,
        *,
        context: SleepCommitContext,
        decision: CandidateSleepDecisionDraft,
    ) -> bool:
        if (
            context.opportunity_purpose != "consider_sleep"
            or context.source_kind != "maintenance_window"
            or context.source_ref != decision.cycle_anchor_ref
        ):
            return False
        existing = await (
            await transaction.execute(
                """
                SELECT 1 FROM armi.maintenance_sessions
                WHERE subject_id=%s
                  AND cycle_anchor_ref=%s
                """,
                (context.subject_id, context.source_ref),
            )
        ).fetchone()
        return (
            context.opportunity_expires_at is not None
            and context.opportunity_expires_at > datetime.now(UTC)
            and existing is None
        )

    @staticmethod
    async def _maintenance_current(
        transaction: PostgreSQLTransaction,
        *,
        context: SleepCommitContext,
        decision: CandidateMaintenanceDecisionDraft,
    ) -> bool:
        expected_purpose = {
            "memory_maintenance": "maintain_subjective_memory",
            "self_check": "perform_subject_self_check",
            "reflect_self": "reflect_self",
            "reflect_mind": "reflect_mind",
            "reflect_prompt": "reflect_prompt",
        }[decision.phase.value]
        if (
            context.opportunity_purpose != expected_purpose
            or context.source_kind != "maintenance_phase_revision"
            or context.source_ref != decision.current_revision_id
            or context.source_version != decision.expected_head_version
        ):
            return False
        row = await (
            await transaction.execute(
                """
                SELECT 1
                FROM armi.maintenance_sessions AS session
                WHERE session.maintenance_session_id = %s
                  AND session.subject_id = %s
                  AND session.current_revision_id = %s
                  AND session.head_version = %s
                  AND session.finished_at IS NULL
                  AND session.phase = %s
                  AND session.result_status = 'running'
                  AND session.phase_completed_at IS NULL
                """,
                (
                    decision.maintenance_session_id,
                    context.subject_id,
                    decision.current_revision_id,
                    decision.expected_head_version,
                    decision.phase.value,
                ),
            )
        ).fetchone()
        return row is not None

    async def _insert_sleep_decision(
        self,
        transaction: PostgreSQLTransaction,
        *,
        context: SleepCommitContext,
        application_id: UUID,
        decision: CandidateSleepDecisionDraft,
        resulting_subject_version: int,
    ) -> None:
        review_at = (
            datetime.now(UTC) + timedelta(hours=1)
            if decision.decision_kind is SleepDecisionKind.DEFER
            else None
        )
        await self._decisions.record_sleep_decision(
            transaction,
            context=context,
            application_id=application_id,
            decision=decision,
            review_not_before=review_at,
        )
        if decision.decision_kind is not SleepDecisionKind.SLEEP:
            return
        if context.opportunity_expires_at is None:
            raise SleepViolation("SLEEP-WINDOW")
        session_id, revision_id = uuid7(), uuid7()
        await transaction.execute(
            """
            INSERT INTO armi.maintenance_sessions (
                maintenance_session_id, subject_id,
                origin_opportunity_id, cycle_anchor_kind, cycle_anchor_ref,
                consideration_at, deadline_at, trigger_kind,
                sleep_episode_id, started_subject_version, started_state_epoch,
                current_revision_id) VALUES (%s, %s, %s, %s, %s, %s, %s,
                      'subject_choice', %s, %s, %s, %s)
            """,
            (
                session_id,
                context.subject_id,
                context.opportunity_id,
                "subject_birth"
                if context.source_ref == context.subject_id
                else "maintenance_session",
                decision.cycle_anchor_ref,
                context.opportunity_available_after,
                context.opportunity_expires_at,
                context.episode_id,
                resulting_subject_version,
                context.base_state_epoch,
                revision_id,
            ),
        )

    async def _record_maintenance_result(
        self,
        transaction: PostgreSQLTransaction,
        *,
        context: SleepCommitContext,
        application_id: UUID,
        commit_id: UUID,
        decision: CandidateMaintenanceDecisionDraft,
        committed_memory_ids: tuple[UUID, ...],
    ) -> None:
        if len(committed_memory_ids) > 1:
            raise SleepViolation("SLEEP-MAINTENANCE-MEMORY")
        memory_id = None
        if decision.memory_proposal_ref is not None:
            if len(committed_memory_ids) != 1:
                raise SleepViolation("SLEEP-MAINTENANCE-MEMORY")
            memory_id = committed_memory_ids[0]
        await self._decisions.record_maintenance_result(
            transaction,
            context=context,
            application_id=application_id,
            commit_id=commit_id,
            decision=decision,
            memory_id=memory_id,
        )
        updated = await transaction.execute(
            """UPDATE armi.maintenance_sessions
               SET phase_completed_at=statement_timestamp(), updated_at=statement_timestamp()
               WHERE maintenance_session_id=%s AND current_revision_id=%s
                 AND head_version=%s AND phase=%s AND result_status='running'
                 AND finished_at IS NULL AND phase_completed_at IS NULL
               RETURNING maintenance_session_id""",
            (
                decision.maintenance_session_id,
                decision.current_revision_id,
                decision.expected_head_version,
                decision.phase.value,
            ),
        )
        if await updated.fetchone() is None:
            raise SleepViolation("SLEEP-MAINTENANCE-COMMIT")


__all__ = ("PostgreSQLSleepCommit",)
