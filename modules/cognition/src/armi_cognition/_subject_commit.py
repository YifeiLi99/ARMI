"""PostgreSQL ownership for accepted cognition subject-commit facts."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from armi_expression.api import (
    ExpressionCommitContext,
    ExpressionOperationSnapshot,
    ResponseViolation,
)
from armi_kernel.application import (
    ArtifactId,
    CandidateApplicationId,
    CandidateApplicationStatus,
    SubjectCommitViolation,
)
from armi_kernel.contracts import Digest, TraceId
from armi_runtime_foundation import PostgreSQLTransaction
from armi_sleep.api import (
    CandidateSleepDecisionDraft,
    SleepCommitContext,
    SleepViolation,
)

from .api import (
    CognitionAcceptedCandidate,
    CognitionApplicationDraft,
    CognitionApplicationSnapshot,
    CognitionCommitSnapshot,
    CognitionEpisodeStatus,
    CognitionExactLifeQueryIntentDraft,
    CognitionMaintenanceProgressPort,
    CognitionOperationSnapshot,
)


class PostgreSQLCognitionSubjectCommit:
    def __init__(
        self, maintenance: CognitionMaintenanceProgressPort | None = None
    ) -> None:
        # Read/decision-only public ports never advance maintenance progress.
        self._maintenance = maintenance

    async def record_dialogue_decision(
        self,
        transaction: PostgreSQLTransaction,
        *,
        context: ExpressionCommitContext,
        decision_kind: str,
        operation_ref: UUID,
        proposal_ref: str | None = None,
        reason_class: str | None = None,
        effect_id: UUID | None = None,
    ) -> None:
        # Decisions belong to the episode; effects own delivery (DESIGN.md).
        row = await (
            await transaction.execute(
                """UPDATE armi.cognitive_episodes
               SET dialogue_decision_kind=%s, dialogue_reason_class=%s,
                   dialogue_proposal_ref=%s, dialogue_operation_ref=%s,
                   dialogue_effect_id=%s
               WHERE cognitive_episode_id=%s AND subject_id=%s
                 AND candidate_validation_id=%s AND dialogue_decision_kind IS NULL
               RETURNING cognitive_episode_id""",
                (
                    decision_kind,
                    reason_class,
                    proposal_ref,
                    operation_ref,
                    effect_id,
                    context.episode_id,
                    context.subject_id,
                    context.validation_id,
                ),
            )
        ).fetchone()
        if row is None:
            raise ResponseViolation("SUBJECT-DIALOGUE-STALE")

    async def dialogue_operation(
        self,
        transaction: PostgreSQLTransaction,
        *,
        operation_ref: UUID,
    ) -> ExpressionOperationSnapshot | None:
        row = await (
            await transaction.execute(
                """SELECT cognitive_episode_id, dialogue_decision_kind, dialogue_reason_class
               FROM armi.cognitive_episodes WHERE dialogue_operation_ref=%s""",
                (operation_ref,),
            )
        ).fetchone()
        if row is None:
            return None
        return ExpressionOperationSnapshot(
            operation_ref=operation_ref,
            intent_id=None,
            dialogue_decision_id=row[0],
            action_kind=None,
            decision_kind=row[1],
            reason_code=row[2],
        )

    async def record_sleep_decision(
        self,
        transaction: PostgreSQLTransaction,
        *,
        context: SleepCommitContext,
        application_id: UUID,
        decision: CandidateSleepDecisionDraft,
        review_not_before: datetime | None,
    ) -> None:
        # The accepted choice belongs to its episode; Sleep owns progress (DESIGN.md).
        row = await (
            await transaction.execute(
                """UPDATE armi.cognitive_episodes
               SET sleep_decision_kind=%s, sleep_cycle_anchor_ref=%s,
                   sleep_review_not_before=%s
               WHERE cognitive_episode_id=%s AND subject_id=%s
                 AND candidate_validation_id=%s AND candidate_application_id=%s
                 AND purpose='consider_sleep' AND sleep_decision_kind IS NULL
               RETURNING cognitive_episode_id""",
                (
                    decision.decision_kind.value,
                    decision.cycle_anchor_ref,
                    review_not_before,
                    context.episode_id,
                    context.subject_id,
                    context.validation_id,
                    application_id,
                ),
            )
        ).fetchone()
        if row is None:
            raise SleepViolation("SLEEP-DECISION-STALE")

    async def sleep_episode_for_validation(
        self, transaction: PostgreSQLTransaction, validation_id: UUID
    ) -> UUID | None:
        row = await (
            await transaction.execute(
                """SELECT cognitive_episode_id FROM armi.cognitive_episodes
               WHERE candidate_validation_id=%s AND sleep_decision_kind='sleep'""",
                (validation_id,),
            )
        ).fetchone()
        return None if row is None else row[0]

    async def autonomous_commit_ids(
        self,
        transaction: PostgreSQLTransaction,
        *,
        commit_ids: tuple[UUID, ...],
    ) -> frozenset[UUID]:
        if not commit_ids:
            return frozenset()
        rows = await (
            await transaction.execute(
                """SELECT subject_commit_id FROM armi.cognitive_episodes
               WHERE subject_commit_id=ANY(%s::uuid[]) AND purpose='consider_autonomous_life'""",
                (list(commit_ids),),
            )
        ).fetchall()
        return frozenset(row[0] for row in rows)

    async def opportunity_episode_states(
        self, transaction: PostgreSQLTransaction, *, opportunity_id: UUID
    ) -> tuple[tuple[UUID, str], ...]:
        rows = await (
            await transaction.execute(
                """SELECT cognitive_episode_id,status FROM armi.cognitive_episodes
                   WHERE opportunity_id=%s ORDER BY created_at""",
                (opportunity_id,),
            )
        ).fetchall()
        return tuple((row[0], str(row[1])) for row in rows)

    async def active_count(
        self, transaction: PostgreSQLTransaction, *, subject_id: UUID
    ) -> int:
        row = await (
            await transaction.execute(
                """SELECT count(*) FROM armi.cognitive_episodes
                   WHERE subject_id=%s AND status NOT IN
                   ('completed','stale','failed','cancelled','candidate_rejected')""",
                (subject_id,),
            )
        ).fetchone()
        return 0 if row is None else int(row[0])

    async def opportunity_for_episode(
        self,
        transaction: PostgreSQLTransaction,
        *,
        episode_id: UUID,
    ) -> UUID | None:
        row = await (
            await transaction.execute(
                """SELECT opportunity_id FROM armi.cognitive_episodes
                   WHERE cognitive_episode_id = %s""",
                (episode_id,),
            )
        ).fetchone()
        return None if row is None else row[0]

    async def operation_snapshot(
        self,
        transaction: PostgreSQLTransaction,
        *,
        opportunity_id: UUID,
    ) -> CognitionOperationSnapshot:
        row = await (
            await transaction.execute(
                """
                SELECT episode.status, episode.failure_code,
                       episode.application_resolution,
                       episode.observed_subject_version
                FROM armi.cognitive_episodes AS episode
                WHERE episode.opportunity_id=%s
                """,
                (opportunity_id,),
            )
        ).fetchone()
        if row is None:
            return CognitionOperationSnapshot(None, None, None, None)
        return CognitionOperationSnapshot(
            str(row[0]),
            None if row[1] is None else str(row[1]),
            None if row[2] is None else str(row[2]),
            None if row[3] is None else int(row[3]),
        )

    """Own Cognition reads and writes used by the Runtime commit coordinator."""

    __slots__ = ("_maintenance",)

    async def snapshot(
        self,
        transaction: PostgreSQLTransaction,
        *,
        episode_id: UUID,
        accepted_candidates: tuple[CognitionAcceptedCandidate, ...],
    ) -> CognitionCommitSnapshot:
        row = await (
            await transaction.execute(
                """
                SELECT episode.candidate_validation_id,
                       episode.cognitive_episode_id,
                       episode.opportunity_id,
                       episode.subject_id,
                       episode.bundle_activation_id,
                       episode.change_set_artifact_id,
                       episode.base_subject_version,
                       episode.base_state_epoch,
                       episode.compiled_context_digest,
                       episode.trace_id
                FROM armi.cognitive_episodes AS episode
                WHERE episode.cognitive_episode_id = %s
                  AND episode.status = 'finalizing'
                  AND episode.validation_status = 'accepted'
                  AND episode.change_set_artifact_id IS NOT NULL
                  AND episode.candidate_application_id IS NULL
                """,
                (episode_id,),
            )
        ).fetchone()
        if row is None:
            raise SubjectCommitViolation("SUBJECT-WORK-STALE")
        return CognitionCommitSnapshot(
            validation_id=row[0],
            episode_id=row[1],
            opportunity_id=row[2],
            subject_id=row[3],
            activation_id=row[4],
            change_set_artifact_id=ArtifactId(row[5]),
            base_subject_version=int(row[6]),
            base_state_epoch=int(row[7]),
            context_digest=Digest(str(row[8])),
            trace_id=TraceId(str(row[9])),
            accepted_candidates=accepted_candidates,
        )

    async def existing_application(
        self, transaction: PostgreSQLTransaction, *, validation_id: UUID
    ) -> CognitionApplicationSnapshot | None:
        row = await (
            await transaction.execute(
                """
                SELECT candidate_application_id, application_resolution, subject_commit_id,
                       observed_subject_version, successor_opportunity_id
                FROM armi.cognitive_episodes
                WHERE candidate_validation_id = %s
                  AND candidate_application_id IS NOT NULL
                """,
                (validation_id,),
            )
        ).fetchone()
        if row is None:
            return None
        return CognitionApplicationSnapshot(
            CandidateApplicationId(row[0]),
            CandidateApplicationStatus(str(row[1])),
            row[2],
            int(row[3]),
            row[4],
        )

    async def note_accepted_experience(
        self,
        transaction: PostgreSQLTransaction,
        *,
        subject_id: UUID,
        acceptance_ordinal: int,
    ) -> None:
        assert self._maintenance is not None
        await self._maintenance.note_accepted_experience(
            transaction, subject_id=subject_id, acceptance_ordinal=acceptance_ordinal
        )

    async def register_subject_commit(
        self,
        transaction: PostgreSQLTransaction,
        *,
        episode_id: UUID,
        validation_id: UUID,
        subject_id: UUID,
        activation_id: UUID,
        base_subject_version: int,
        base_state_epoch: int,
        commit_id: UUID,
        new_subject_version: int,
        runtime_instance_id: UUID,
        fence_token: int,
    ) -> None:
        # Runtime owns the transaction; Cognition owns its persisted receipt (DESIGN.md).
        row = await (
            await transaction.execute(
                """UPDATE armi.cognitive_episodes
               SET subject_commit_id=%s,new_subject_version=%s,
                   commit_runtime_instance_id=%s,commit_fence_token=%s
               WHERE cognitive_episode_id=%s AND candidate_validation_id=%s
                 AND subject_id=%s AND bundle_activation_id=%s
                 AND base_subject_version=%s AND base_state_epoch=%s
                 AND status='finalizing' AND subject_commit_id IS NULL
                 AND candidate_application_id IS NULL
               RETURNING cognitive_episode_id""",
                (
                    commit_id,
                    new_subject_version,
                    runtime_instance_id,
                    fence_token,
                    episode_id,
                    validation_id,
                    subject_id,
                    activation_id,
                    base_subject_version,
                    base_state_epoch,
                ),
            )
        ).fetchone()
        if row is None:
            raise SubjectCommitViolation("SUBJECT-WORK-STALE")

    async def commit_at_version(
        self,
        transaction: PostgreSQLTransaction,
        *,
        subject_id: UUID,
        subject_version: int,
    ) -> UUID | None:
        row = await (
            await transaction.execute(
                """SELECT subject_commit_id FROM armi.cognitive_episodes
               WHERE subject_id=%s AND new_subject_version=%s""",
                (subject_id, subject_version),
            )
        ).fetchone()
        return None if row is None else row[0]

    async def episode_for_commit(
        self, transaction: PostgreSQLTransaction, *, subject_commit_id: UUID
    ) -> UUID | None:
        row = await (
            await transaction.execute(
                "SELECT cognitive_episode_id FROM armi.cognitive_episodes WHERE subject_commit_id=%s",
                (subject_commit_id,),
            )
        ).fetchone()
        return None if row is None else row[0]

    async def record_application(
        self, transaction: PostgreSQLTransaction, draft: CognitionApplicationDraft
    ) -> None:
        updated = await (
            await transaction.execute(
                """
                UPDATE armi.cognitive_episodes
                SET candidate_application_id=%s, subject_commit_id=%s,
                    successor_opportunity_id=%s, observed_subject_version=%s
                WHERE cognitive_episode_id=%s AND candidate_validation_id=%s
                  AND status='finalizing' AND candidate_application_id IS NULL
                RETURNING cognitive_episode_id
                """,
                (
                    draft.application_id.value,
                    draft.subject_commit_id,
                    draft.successor_opportunity_id,
                    draft.observed_subject_version,
                    draft.episode_id,
                    draft.validation_id,
                ),
            )
        ).fetchone()
        if updated is None:
            raise SubjectCommitViolation("SUBJECT-WORK-STALE")
        if (
            draft.status is CandidateApplicationStatus.APPLIED
            and draft.purpose == "reflect_prompt"
        ):
            episode = await (
                await transaction.execute(
                    """SELECT subject_id,maintenance_source_episode_id FROM armi.cognitive_episodes
                       WHERE cognitive_episode_id=%s""",
                    (draft.episode_id,),
                )
            ).fetchone()
            if episode is None:
                raise SubjectCommitViolation("SUBJECT-EPISODE-STATE")
            completed = await (
                await transaction.execute(
                    """UPDATE armi.cognitive_episodes
                       SET maintenance_status='completed',maintenance_finished_at=statement_timestamp()
                       WHERE cognitive_episode_id=%s AND subject_id=%s
                         AND maintenance_status='running'
                       RETURNING maintenance_from_ordinal,maintenance_through_ordinal""",
                    (episode[1], episode[0]),
                )
            ).fetchone()
            if completed is not None:
                assert self._maintenance is not None
                await self._maintenance.complete_window(
                    transaction,
                    subject_id=episode[0],
                    after_ordinal=int(completed[0]),
                    through_ordinal=int(completed[1]),
                )

    async def record_exact_life_query(
        self,
        transaction: PostgreSQLTransaction,
        draft: CognitionExactLifeQueryIntentDraft,
    ) -> None:
        # Query custody stays on its source episode (DESIGN.md).
        row = await (
            await transaction.execute(
                """UPDATE armi.cognitive_episodes
                   SET exact_life_query_intent_id=%s,
                       life_query_creator_party_id=%s, life_query_proposal_ref=%s,
                       life_query_record_kind=%s, life_query_text=%s,
                       life_query_result_limit=%s, life_query_digest=%s,
                       life_query_work_id=%s, life_query_status='pending',
                       life_query_created_at=statement_timestamp()
                   WHERE opportunity_id=%s AND subject_id=%s AND scene_id=%s
                     AND trace_id=%s AND status='finalizing'
                     AND exact_life_query_intent_id IS NULL
                   RETURNING cognitive_episode_id""",
                (
                    draft.intent_id,
                    draft.creator_party_id,
                    draft.proposal_ref,
                    draft.record_kind,
                    draft.query_text,
                    draft.result_limit,
                    draft.query_digest.value,
                    draft.execution_work_id,
                    draft.source_opportunity_id,
                    draft.subject_id,
                    draft.scene_id,
                    draft.trace_id.value,
                ),
            )
        ).fetchone()
        if row is None:
            raise SubjectCommitViolation("SUBJECT-EXACT-LIFE-QUERY-STALE")

    async def finish_episode(
        self,
        transaction: PostgreSQLTransaction,
        *,
        episode_id: UUID,
        status: CognitionEpisodeStatus,
        application_status: CandidateApplicationStatus | None,
        failure_code: str | None = None,
    ) -> None:
        if status is CognitionEpisodeStatus.FAILED:
            row = await (
                await transaction.execute(
                    """
                    UPDATE armi.cognitive_episodes
                    SET status = 'failed', failure_code = %s
                    WHERE cognitive_episode_id = %s
                      AND status = 'finalizing'
                    RETURNING cognitive_episode_id
                    """,
                    (failure_code, episode_id),
                )
            ).fetchone()
        else:
            if application_status is None:
                raise SubjectCommitViolation("SUBJECT-APPLICATION-STATE")
            row = await (
                await transaction.execute(
                    """
                    UPDATE armi.cognitive_episodes
                    SET status = %s, application_resolution = %s,
                        committed_at = statement_timestamp()
                    WHERE cognitive_episode_id = %s
                      AND status = 'finalizing'
                    RETURNING cognitive_episode_id
                    """,
                    (status.value, application_status.value, episode_id),
                )
            ).fetchone()
        if row is None:
            raise SubjectCommitViolation("SUBJECT-WORK-STALE")


__all__ = ("PostgreSQLCognitionSubjectCommit",)
