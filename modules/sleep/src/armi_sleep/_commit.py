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
    SleepViolation,
)


class PostgreSQLSleepCommit:
    __slots__ = ("_cognition",)

    def __init__(self, cognition: SleepApplication) -> None:
        self._cognition = cognition

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
            await self._insert_maintenance_result(
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
        rows = await (
            await transaction.execute(
                """
                SELECT session.maintenance_session_id
                FROM armi.sleep_decisions AS decision
                JOIN armi.maintenance_sessions AS session
                  ON session.sleep_decision_id = decision.sleep_decision_id
                WHERE decision.candidate_validation_id = %s
                UNION
                SELECT maintenance_session_id
                FROM armi.maintenance_phase_results
                WHERE candidate_validation_id = %s
                ORDER BY maintenance_session_id
                """,
                (validation_id, validation_id),
            )
        ).fetchall()
        return tuple(UUID(str(row[0])) for row in rows)

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
        row = await (
            await transaction.execute(
                """
                SELECT opportunity.expires_at > statement_timestamp()
                       AND NOT EXISTS (
                           SELECT 1 FROM armi.maintenance_sessions AS session
                           WHERE session.subject_id = opportunity.subject_id
                             AND session.life_generation_id = %s
                             AND session.cycle_anchor_ref = opportunity.source_ref
                       )
                FROM armi.opportunities AS opportunity
                WHERE opportunity.opportunity_id = %s
                """,
                (context.generation_id, context.opportunity_id),
            )
        ).fetchone()
        return row is not None and bool(row[0])

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
                JOIN armi.maintenance_session_revisions AS revision
                  ON revision.maintenance_revision_id = session.current_revision_id
                 AND revision.maintenance_session_id = session.maintenance_session_id
                WHERE session.maintenance_session_id = %s
                  AND session.subject_id = %s
                  AND session.life_generation_id = %s
                  AND session.current_revision_id = %s
                  AND session.head_version = %s
                  AND session.finished_at IS NULL
                  AND revision.phase = %s
                  AND revision.result_status = 'running'
                """,
                (
                    decision.maintenance_session_id,
                    context.subject_id,
                    context.generation_id,
                    decision.current_revision_id,
                    decision.expected_head_version,
                    decision.phase.value,
                ),
            )
        ).fetchone()
        return row is not None

    @staticmethod
    async def _insert_sleep_decision(
        transaction: PostgreSQLTransaction,
        *,
        context: SleepCommitContext,
        application_id: UUID,
        decision: CandidateSleepDecisionDraft,
        resulting_subject_version: int,
    ) -> None:
        decision_id = uuid7()
        review_at = (
            datetime.now(UTC) + timedelta(hours=1)
            if decision.decision_kind is SleepDecisionKind.DEFER
            else None
        )
        await transaction.execute(
            """
            INSERT INTO armi.sleep_decisions (
                sleep_decision_id, opportunity_id, cognitive_episode_id,
                candidate_validation_id, candidate_application_id, subject_id,
                life_generation_id, cycle_anchor_ref,
                decision_kind, review_not_before) VALUES (
                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                decision_id,
                context.opportunity_id,
                context.episode_id,
                context.validation_id,
                application_id,
                context.subject_id,
                context.generation_id,
                decision.cycle_anchor_ref,
                decision.decision_kind.value,
                review_at,
            ),
        )
        if decision.decision_kind is not SleepDecisionKind.SLEEP:
            return
        window = await (
            await transaction.execute(
                """
                SELECT available_after, expires_at,
                       CASE WHEN source_ref = %s THEN 'life_generation'
                            ELSE 'maintenance_session' END
                FROM armi.opportunities WHERE opportunity_id = %s
                """,
                (context.generation_id, context.opportunity_id),
            )
        ).fetchone()
        if window is None or window[1] is None:
            raise SleepViolation("SLEEP-WINDOW")
        session_id, revision_id = uuid7(), uuid7()
        await transaction.execute(
            """
            INSERT INTO armi.maintenance_sessions (
                maintenance_session_id, subject_id, life_generation_id,
                origin_opportunity_id, cycle_anchor_kind, cycle_anchor_ref,
                consideration_at, deadline_at, trigger_kind,
                sleep_decision_id, started_subject_version, started_state_epoch,
                current_revision_id) VALUES (%s, %s, %s, %s, %s, %s, %s, %s,
                      'subject_choice', %s, %s, %s, %s)
            """,
            (
                session_id,
                context.subject_id,
                context.generation_id,
                context.opportunity_id,
                str(window[2]),
                decision.cycle_anchor_ref,
                window[0],
                window[1],
                decision_id,
                resulting_subject_version,
                context.base_state_epoch,
                revision_id,
            ),
        )
        await transaction.execute(
            """
            INSERT INTO armi.maintenance_session_revisions (
                maintenance_revision_id, maintenance_session_id, revision_no,
                previous_revision_id, phase, result_status, transition_kind)
            VALUES (%s, %s, 1, NULL, 'preparing', 'running', 'started')
            """,
            (revision_id, session_id),
        )

    @staticmethod
    async def _insert_maintenance_result(
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
        await transaction.execute(
            """
            INSERT INTO armi.maintenance_phase_results (
                maintenance_phase_result_id, opportunity_id,
                cognitive_episode_id, candidate_validation_id,
                candidate_application_id, subject_commit_id,
                maintenance_session_id, maintenance_revision_id,
                expected_head_version, phase, outcome, result_summary,
                creator_visible_problem, memory_id) VALUES (
                %s, %s, %s, %s, %s, %s, %s, %s,
                %s, %s, %s, %s, %s, %s)
            """,
            (
                uuid7(),
                context.opportunity_id,
                context.episode_id,
                context.validation_id,
                application_id,
                commit_id,
                decision.maintenance_session_id,
                decision.current_revision_id,
                decision.expected_head_version,
                decision.phase.value,
                decision.outcome.value,
                decision.result_summary,
                decision.creator_visible_problem,
                memory_id,
            ),
        )


__all__ = ("PostgreSQLSleepCommit",)
