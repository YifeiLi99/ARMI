"""PostgreSQL Activity commit participant."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid7

from armi_runtime_foundation import PostgreSQLTransaction

from ._application import ActivityApplication
from .api import (
    ActivityAttentionDecisionKind,
    ActivityCommitContext,
    ActivityCommitResult,
    ActivityViolation,
    CandidateActivityDecisionDraft,
    CandidateActivityDraft,
)


class PostgreSQLActivityCommit:
    __slots__ = ("_cognition",)

    def __init__(self, cognition: ActivityApplication) -> None:
        self._cognition = cognition

    def _drafts(
        self,
        drafts: tuple[CandidateActivityDraft | CandidateActivityDecisionDraft, ...],
    ) -> tuple[CandidateActivityDraft | CandidateActivityDecisionDraft, ...]:
        return drafts

    async def heads_match(
        self,
        transaction: PostgreSQLTransaction,
        *,
        context: ActivityCommitContext,
        drafts: tuple[CandidateActivityDraft | CandidateActivityDecisionDraft, ...],
    ) -> bool:
        values = self._drafts(drafts)
        if (
            len(values) > 4
            or sum(isinstance(item, CandidateActivityDecisionDraft) for item in values)
            > 1
        ):
            raise ActivityViolation("ACTIVITY-COMMIT-SHAPE")
        for value in sorted(values, key=lambda item: str(item.activity_id)):
            row = await (
                await transaction.execute(
                    """
                    SELECT current_revision_id, head_version, subject_id
                    FROM armi.activities
                    WHERE activity_id = %s
                    FOR UPDATE
                    """,
                    (value.activity_id,),
                )
            ).fetchone()
            if isinstance(value, CandidateActivityDraft):
                if row is not None:
                    return False
            elif (
                row is None
                or row[0] != value.current_revision_id
                or int(row[1]) != value.expected_head_version
                or row[2] != context.subject_id
                or context.source_activity_id != value.activity_id
                or context.source_ref != value.current_revision_id
            ):
                return False
        return True

    def requests_reconsideration(
        self,
        *,
        context: ActivityCommitContext,
        drafts: tuple[CandidateActivityDraft | CandidateActivityDecisionDraft, ...],
    ) -> bool:
        decisions = tuple(
            item
            for item in self._drafts(drafts)
            if isinstance(item, CandidateActivityDecisionDraft)
        )
        return (
            context.opportunity_purpose == "consider_activity_attention"
            and len(decisions) == 1
            and decisions[0].decision_kind is ActivityAttentionDecisionKind.DEFER
            and context.reconsideration_no == 0
        )

    async def commit(
        self,
        transaction: PostgreSQLTransaction,
        *,
        context: ActivityCommitContext,
        commit_id: UUID,
        drafts: tuple[CandidateActivityDraft | CandidateActivityDecisionDraft, ...],
    ) -> ActivityCommitResult:
        creates: list[CandidateActivityDraft] = []
        decisions: list[CandidateActivityDecisionDraft] = []
        for item in self._drafts(drafts):
            if isinstance(item, CandidateActivityDraft):
                creates.append(item)
            else:
                decisions.append(item)
        for activity in creates:
            await transaction.execute(
                """
                INSERT INTO armi.activities (
                    activity_id, subject_id, activity_kind, origin_opportunity_id,
                    current_revision_id, head_version, privacy_scope)
                VALUES (%s, %s, %s, %s, NULL, 0, %s)
                """,
                (
                    activity.activity_id,
                    context.subject_id,
                    activity.activity_kind,
                    context.opportunity_id,
                    activity.privacy_scope,
                ),
            )
            revision_id = uuid7()
            await transaction.execute(
                """
                INSERT INTO armi.activity_revisions (
                    activity_revision_id, activity_id, revision_no,
                    previous_revision_id, subject_commit_id, candidate_validation_id,
                    proposal_ref, goal, progress_summary, waiting_condition,
                    resumption_cue, next_safe_step, status, terminal_reason,
                    related_scene_id, transition_kind, waiting_condition_kind,
                    resume_not_before) VALUES (
                    %s, %s, 1, NULL, %s, %s, %s, %s,
                    NULL, NULL, NULL, %s, %s, NULL, %s, 'created', NULL, NULL)
                """,
                (
                    revision_id,
                    activity.activity_id,
                    commit_id,
                    context.validation_id,
                    activity.proposal_ref,
                    activity.goal,
                    activity.next_safe_step,
                    activity.status.value,
                    context.scene_id,
                ),
            )
            updated = await (
                await transaction.execute(
                    """
                    UPDATE armi.activities SET current_revision_id = %s, head_version = 1
                    WHERE activity_id = %s AND current_revision_id IS NULL AND head_version = 0
                    RETURNING activity_id
                    """,
                    (revision_id, activity.activity_id),
                )
            ).fetchone()
            if updated is None:
                raise ActivityViolation("ACTIVITY-HEAD-STALE")
        if not decisions:
            return ActivityCommitResult(None, None, None, False)
        if len(decisions) != 1:
            raise ActivityViolation("ACTIVITY-COMMIT-SHAPE")
        decision = decisions[0]
        if decision.decision_kind in {
            ActivityAttentionDecisionKind.NO_ACTION,
            ActivityAttentionDecisionKind.DEFER,
            ActivityAttentionDecisionKind.NEED_INFORMATION,
        }:
            return ActivityCommitResult(None, None, None, False)
        result_revision_id = await self._transition(
            transaction, context=context, commit_id=commit_id, decision=decision
        )
        return ActivityCommitResult(
            result_revision_id,
            decision.activity_id
            if decision.decision_kind is ActivityAttentionDecisionKind.ENGAGE
            else None,
            decision.proposal_ref,
            True,
        )

    async def record_decision(
        self,
        transaction: PostgreSQLTransaction,
        *,
        context: ActivityCommitContext,
        application_id: UUID,
        drafts: tuple[CandidateActivityDraft | CandidateActivityDecisionDraft, ...],
        result_revision_id: UUID | None,
        output_material_ids: tuple[UUID, ...] = (),
    ) -> None:
        decisions = tuple(
            item
            for item in self._drafts(drafts)
            if isinstance(item, CandidateActivityDecisionDraft)
        )
        if context.opportunity_purpose == "consider_activity_attention":
            if not decisions:
                return
            if len(decisions) != 1:
                raise ActivityViolation("ACTIVITY-COMMIT-SHAPE")
            decision = decisions[0]
            review_not_before = (
                datetime.now(UTC) + timedelta(seconds=60)
                if decision.decision_kind is ActivityAttentionDecisionKind.DEFER
                else None
            )
            await transaction.execute(
                """
                INSERT INTO armi.activity_decisions (
                    activity_decision_id, decision_source, opportunity_id,
                    cognitive_episode_id, candidate_validation_id,
                    candidate_application_id, activity_id, expected_revision_id,
                    expected_head_version, decision_kind, result_revision_id,
                    review_not_before) VALUES (
                    %s, 'attention', %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    uuid7(),
                    context.opportunity_id,
                    context.episode_id,
                    context.validation_id,
                    application_id,
                    decision.activity_id,
                    decision.current_revision_id,
                    decision.expected_head_version,
                    decision.decision_kind.value,
                    result_revision_id,
                    review_not_before,
                ),
            )
            return
        if context.opportunity_purpose != "consider_activity_internal_work":
            return
        if (
            len(decisions) != 1
            or result_revision_id is None
            or len(output_material_ids) > 1
        ):
            raise ActivityViolation("ACTIVITY-WORK-SHAPE")
        decision = decisions[0]
        outcome = {
            ActivityAttentionDecisionKind.PROGRESS: "progress",
            ActivityAttentionDecisionKind.COMPLETE: "complete",
            ActivityAttentionDecisionKind.WAIT: "need_information",
            ActivityAttentionDecisionKind.ABANDON: "abandon",
            ActivityAttentionDecisionKind.PAUSE: "no_result",
        }.get(decision.decision_kind)
        if outcome is None:
            raise ActivityViolation("ACTIVITY-WORK-SHAPE")
        await transaction.execute(
            """
            INSERT INTO armi.activity_decisions (
                activity_decision_id, decision_source, opportunity_id,
                cognitive_episode_id, candidate_validation_id,
                candidate_application_id, activity_id, expected_revision_id,
                expected_head_version, decision_kind, result_revision_id,
                output_material_id) VALUES (
                %s, 'internal_work', %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                uuid7(),
                context.opportunity_id,
                context.episode_id,
                context.validation_id,
                application_id,
                decision.activity_id,
                decision.current_revision_id,
                decision.expected_head_version,
                outcome,
                result_revision_id,
                None if not output_material_ids else output_material_ids[0],
            ),
        )

    async def affected_activity_ids(
        self, transaction: PostgreSQLTransaction, validation_id: UUID
    ) -> tuple[UUID, ...]:
        rows = await (
            await transaction.execute(
                """
                SELECT activity_id FROM armi.activity_revisions
                WHERE candidate_validation_id = %s
                UNION
                SELECT activity_id FROM armi.activity_decisions
                WHERE candidate_validation_id = %s
                ORDER BY activity_id
                """,
                (validation_id, validation_id),
            )
        ).fetchall()
        return tuple(UUID(str(row[0])) for row in rows)

    async def _transition(
        self,
        transaction: PostgreSQLTransaction,
        *,
        context: ActivityCommitContext,
        commit_id: UUID,
        decision: CandidateActivityDecisionDraft,
    ) -> UUID:
        row = await (
            await transaction.execute(
                """
                SELECT activity.current_revision_id, activity.head_version,
                       revision.revision_no, revision.goal, revision.progress_summary,
                       revision.next_safe_step, revision.status
                FROM armi.activities AS activity
                JOIN armi.activity_revisions AS revision
                  ON revision.activity_revision_id = activity.current_revision_id
                WHERE activity.activity_id = %s AND activity.subject_id = %s
                FOR UPDATE OF activity
                """,
                (decision.activity_id, context.subject_id),
            )
        ).fetchone()
        if (
            row is None
            or row[0] != decision.current_revision_id
            or int(row[1]) != decision.expected_head_version
        ):
            raise ActivityViolation("ACTIVITY-HEAD-STALE")
        kind = decision.decision_kind.value
        target = {
            "engage": "in_progress",
            "progress": "in_progress",
            "wait": "waiting",
            "pause": "paused",
            "resume": "resuming",
            "complete": "completed",
            "abandon": "abandoned",
        }.get(kind)
        allowed = {
            "ready": {"engage"},
            "in_progress": {
                "engage",
                "progress",
                "wait",
                "pause",
                "complete",
                "abandon",
            },
            "waiting": {"resume"},
            "paused": {"resume"},
            "resuming": {"engage"},
        }
        if target is None or kind not in allowed.get(str(row[6]), set()):
            raise ActivityViolation("ACTIVITY-TRANSITION")
        revision_id = uuid7()
        resume_at = (
            None
            if decision.delay_seconds is None
            else datetime.now(UTC) + timedelta(seconds=decision.delay_seconds)
        )
        await transaction.execute(
            """
            INSERT INTO armi.activity_revisions (
                activity_revision_id, activity_id, revision_no,
                previous_revision_id, subject_commit_id, candidate_validation_id,
                proposal_ref, goal, progress_summary, waiting_condition,
                resumption_cue, next_safe_step, status, terminal_reason,
                related_scene_id, transition_kind, waiting_condition_kind,
                resume_not_before) VALUES (
                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                %s, %s, %s, %s, NULL, %s, %s, %s)
            """,
            (
                revision_id,
                decision.activity_id,
                int(row[2]) + 1,
                decision.current_revision_id,
                commit_id,
                context.validation_id,
                decision.proposal_ref,
                str(row[3]),
                decision.progress_summary
                if decision.progress_summary is not None
                else row[4],
                decision.waiting_summary,
                decision.resumption_cue,
                decision.next_safe_step
                if decision.next_safe_step is not None
                else None
                if target in {"completed", "abandoned"}
                else row[5],
                target,
                decision.terminal_reason,
                kind,
                None if decision.waiting_kind is None else decision.waiting_kind.value,
                resume_at,
            ),
        )
        updated = await (
            await transaction.execute(
                """
                UPDATE armi.activities
                SET current_revision_id = %s, head_version = head_version + 1
                WHERE activity_id = %s AND current_revision_id = %s AND head_version = %s
                RETURNING activity_id
                """,
                (
                    revision_id,
                    decision.activity_id,
                    decision.current_revision_id,
                    decision.expected_head_version,
                ),
            )
        ).fetchone()
        if updated is None:
            raise ActivityViolation("ACTIVITY-HEAD-STALE")
        return revision_id


__all__ = ("PostgreSQLActivityCommit",)
