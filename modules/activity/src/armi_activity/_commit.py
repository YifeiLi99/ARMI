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
            await transaction.execute(
                """SELECT activity_revision_id FROM armi.activity_revisions
                   WHERE activity_id=%s AND revision_no=1 FOR UPDATE""",
                (value.activity_id,),
            )
            row = await (
                await transaction.execute(
                    """
                    SELECT activity_revision_id, revision_no, subject_id
                    FROM armi.activity_revisions
                    WHERE activity_id = %s AND is_current
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
                or (
                    context.opportunity_purpose != "consider_autonomous_life"
                    and context.source_ref != value.current_revision_id
                )
            ):
                return False
        return True

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
            revision_id = uuid7()
            await transaction.execute(
                """
                INSERT INTO armi.activity_revisions (
                    activity_revision_id, activity_id, revision_no,
                    previous_revision_id, subject_commit_id, candidate_validation_id,
                    proposal_ref, goal, progress_summary, waiting_condition,
                    resumption_cue, next_safe_step, status, terminal_reason,
                    related_scene_id, transition_kind, waiting_condition_kind,
                    resume_not_before,subject_id,activity_kind,origin_opportunity_id,
                    privacy_scope,activity_created_at) VALUES (
                    %s, %s, 1, NULL, %s, %s, %s, %s,
                    NULL, NULL, NULL, %s, %s, NULL, %s, 'created', NULL, NULL,
                    %s,%s,%s,%s,statement_timestamp())
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
                    context.subject_id,
                    activity.activity_kind,
                    context.opportunity_id,
                    activity.privacy_scope,
                ),
            )
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
            if decision.decision_kind
            in {
                ActivityAttentionDecisionKind.ENGAGE,
                ActivityAttentionDecisionKind.PROGRESS,
            }
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
        if context.opportunity_purpose != "consider_autonomous_life":
            return
        if not decisions:
            return
        if (
            len(decisions) != 1
            or result_revision_id is None
            or len(output_material_ids) > 1
        ):
            raise ActivityViolation("ACTIVITY-WORK-SHAPE")
        decision = decisions[0]
        if decision.decision_kind not in {
            ActivityAttentionDecisionKind.PROGRESS,
            ActivityAttentionDecisionKind.COMPLETE,
            ActivityAttentionDecisionKind.WAIT,
            ActivityAttentionDecisionKind.ABANDON,
            ActivityAttentionDecisionKind.PAUSE,
        }:
            raise ActivityViolation("ACTIVITY-WORK-SHAPE")
        updated = await transaction.execute(
            """
            UPDATE armi.activity_revisions
            SET opportunity_id=%s, cognitive_episode_id=%s,
                candidate_application_id=%s, output_material_id=%s
            WHERE activity_revision_id=%s AND activity_id=%s
              AND candidate_validation_id=%s AND previous_revision_id=%s
              AND opportunity_id IS NULL
            RETURNING activity_revision_id
            """,
            (
                context.opportunity_id,
                context.episode_id,
                application_id,
                None if not output_material_ids else output_material_ids[0],
                result_revision_id,
                decision.activity_id,
                context.validation_id,
                decision.current_revision_id,
            ),
        )
        if await updated.fetchone() is None:
            raise ActivityViolation("ACTIVITY-HEAD-STALE")

    async def affected_activity_ids(
        self, transaction: PostgreSQLTransaction, validation_id: UUID
    ) -> tuple[UUID, ...]:
        rows = await (
            await transaction.execute(
                """
                SELECT DISTINCT activity_id FROM armi.activity_revisions
                WHERE candidate_validation_id = %s
                ORDER BY activity_id
                """,
                (validation_id,),
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
        await transaction.execute(
            """SELECT activity_revision_id FROM armi.activity_revisions
               WHERE activity_id=%s AND revision_no=1 FOR UPDATE""",
            (decision.activity_id,),
        )
        row = await (
            await transaction.execute(
                """
                SELECT revision.activity_revision_id, revision.revision_no,
                       revision.revision_no, revision.goal, revision.progress_summary,
                       revision.next_safe_step, revision.status,
                       revision.subject_id,revision.activity_kind,
                       revision.origin_opportunity_id,revision.origin_admin_change_id,
                       revision.activity_created_at,revision.privacy_scope
                FROM armi.activity_revisions AS revision
                WHERE revision.activity_id = %s AND revision.subject_id = %s
                  AND revision.is_current
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
        if context.opportunity_purpose == "consider_autonomous_life":
            for current in ("considering", "ready", "waiting", "paused", "resuming"):
                allowed.setdefault(current, set()).update(
                    {"progress", "wait", "pause", "complete", "abandon"}
                )
        if target is None or kind not in allowed.get(str(row[6]), set()):
            raise ActivityViolation("ACTIVITY-TRANSITION")
        revision_id = uuid7()
        resume_at = (
            None
            if decision.delay_seconds is None
            else datetime.now(UTC) + timedelta(seconds=decision.delay_seconds)
        )
        await transaction.execute(
            "UPDATE armi.activity_revisions SET is_current=false "
            "WHERE activity_revision_id=%s",
            (decision.current_revision_id,),
        )
        await transaction.execute(
            """
            INSERT INTO armi.activity_revisions (
                activity_revision_id, activity_id, revision_no,
                previous_revision_id, subject_commit_id, candidate_validation_id,
                proposal_ref, goal, progress_summary, waiting_condition,
                resumption_cue, next_safe_step, status, terminal_reason,
                related_scene_id, transition_kind, waiting_condition_kind,
                resume_not_before,subject_id,activity_kind,origin_opportunity_id,
                origin_admin_change_id,activity_created_at,privacy_scope) VALUES (
                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                %s, %s, %s, %s, NULL, %s, %s, %s,
                %s,%s,%s,%s,%s,%s)
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
                *row[7:13],
            ),
        )
        return revision_id


__all__ = ("PostgreSQLActivityCommit",)
