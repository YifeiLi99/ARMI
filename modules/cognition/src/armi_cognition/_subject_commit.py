"""PostgreSQL ownership for accepted cognition subject-commit facts."""

from __future__ import annotations

from uuid import UUID

from armi_kernel.application import (
    ArtifactId,
    CandidateApplicationId,
    CandidateApplicationStatus,
    CandidateFactClass,
    SubjectCommitViolation,
)
from armi_kernel.contracts import Digest, TraceId
from armi_runtime_foundation import PostgreSQLTransaction

from .api import (
    CognitionAcceptedCandidate,
    CognitionApplicationDraft,
    CognitionApplicationSnapshot,
    CognitionCommitSnapshot,
    CognitionEpisodeStatus,
    CognitionExactLifeQueryIntentDraft,
    CognitionExperienceDraft,
)


class PostgreSQLCognitionSubjectCommit:
    """Own Cognition reads and writes used by the Runtime commit coordinator."""

    __slots__ = ()

    async def snapshot(
        self, transaction: PostgreSQLTransaction, *, episode_id: UUID
    ) -> CognitionCommitSnapshot:
        row = await (
            await transaction.execute(
                """
                SELECT validation.candidate_validation_id,
                       episode.cognitive_episode_id,
                       episode.opportunity_id,
                       episode.subject_id,
                       validation.life_generation_id,
                       validation.bundle_activation_id,
                       validation.change_set_artifact_id,
                       validation.base_subject_version,
                       validation.base_state_epoch,
                       validation.context_digest,
                       episode.trace_id
                FROM armi.cognitive_episodes AS episode
                JOIN armi.cognitive_candidate_validations AS validation
                  ON validation.cognitive_episode_id = episode.cognitive_episode_id
                WHERE episode.cognitive_episode_id = %s
                  AND episode.status = 'candidate_validated'
                  AND validation.validation_status IN ('accepted', 'partially_accepted')
                  AND validation.change_set_artifact_id IS NOT NULL
                  AND NOT EXISTS (
                      SELECT 1
                      FROM armi.cognitive_candidate_applications AS application
                      WHERE application.candidate_validation_id =
                            validation.candidate_validation_id
                  )
                """,
                (episode_id,),
            )
        ).fetchone()
        if row is None:
            raise SubjectCommitViolation("SUBJECT-WORK-STALE")
        item_rows = await (
            await transaction.execute(
                """
                SELECT item.proposal_ref, item.atomic_group_ref, item.owner_kind,
                       item.fact_class, item.ordinal,
                       COALESCE(array_agg(basis.context_item_id ORDER BY basis.ordinal)
                                FILTER (WHERE basis.context_item_id IS NOT NULL), '{}')
                FROM armi.cognitive_candidate_validation_items AS item
                LEFT JOIN armi.cognitive_candidate_basis_links AS basis
                  ON basis.candidate_validation_id = item.candidate_validation_id
                 AND basis.proposal_ref = item.proposal_ref
                WHERE item.candidate_validation_id = %s
                  AND item.validation_status = 'accepted'
                GROUP BY item.proposal_ref, item.atomic_group_ref, item.owner_kind,
                         item.fact_class, item.ordinal
                ORDER BY item.ordinal
                """,
                (row[0],),
            )
        ).fetchall()
        accepted = tuple(
            CognitionAcceptedCandidate(
                proposal_ref=str(item[0]),
                atomic_group_ref=str(item[1]),
                owner_identity=str(item[2]),
                fact_class=CandidateFactClass(str(item[3])),
                ordinal=int(item[4]),
                basis_context_ids=tuple(item[5]),
            )
            for item in item_rows
        )
        return CognitionCommitSnapshot(
            validation_id=row[0],
            episode_id=row[1],
            opportunity_id=row[2],
            subject_id=row[3],
            generation_id=row[4],
            activation_id=row[5],
            change_set_artifact_id=ArtifactId(row[6]),
            base_subject_version=int(row[7]),
            base_state_epoch=int(row[8]),
            context_digest=Digest(str(row[9])),
            trace_id=TraceId(str(row[10])),
            accepted_candidates=accepted,
        )

    async def existing_application(
        self, transaction: PostgreSQLTransaction, *, validation_id: UUID
    ) -> CognitionApplicationSnapshot | None:
        row = await (
            await transaction.execute(
                """
                SELECT candidate_application_id, resolution, subject_commit_id,
                       observed_subject_version, successor_opportunity_id
                FROM armi.cognitive_candidate_applications
                WHERE candidate_validation_id = %s
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

    async def record_experience(
        self, transaction: PostgreSQLTransaction, draft: CognitionExperienceDraft
    ) -> None:
        await transaction.execute(
            """
            INSERT INTO armi.accepted_experiences (
                experience_id, subject_id, subject_commit_id, cognitive_episode_id,
                proposal_ref, experience_kind, fact_class, first_person_gist,
                scene_id, occurred_at, learned_at, source_perspective,
                uncertainty, privacy_scope
            ) VALUES (
                %s, %s, %s, %s, %s, %s, %s, %s,
                %s, %s, %s, %s, %s, 'private'
            )
            """,
            (
                draft.experience_id,
                draft.subject_id,
                draft.subject_commit_id,
                draft.episode_id,
                draft.proposal_ref,
                draft.experience_kind,
                draft.fact_class.value,
                draft.first_person_gist,
                draft.scene_id,
                draft.occurred_at,
                draft.occurred_at,
                draft.source_perspective,
                draft.uncertainty,
            ),
        )

    async def record_application(
        self, transaction: PostgreSQLTransaction, draft: CognitionApplicationDraft
    ) -> None:
        await transaction.execute(
            """
            INSERT INTO armi.cognitive_candidate_applications (
                candidate_application_id, candidate_validation_id,
                cognitive_episode_id, work_id, resolution, subject_commit_id,
                successor_opportunity_id, base_subject_version,
                observed_subject_version, runtime_instance_id, fence_token
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                draft.application_id.value,
                draft.validation_id,
                draft.episode_id,
                draft.work_id,
                draft.status.value,
                draft.subject_commit_id,
                draft.successor_opportunity_id,
                draft.base_subject_version,
                draft.observed_subject_version,
                draft.runtime_instance_id,
                draft.fence_token,
            ),
        )

    async def record_exact_life_query(
        self,
        transaction: PostgreSQLTransaction,
        draft: CognitionExactLifeQueryIntentDraft,
    ) -> None:
        await transaction.execute(
            """
            INSERT INTO armi.exact_life_query_intents (
                exact_life_query_intent_id, subject_commit_id,
                source_opportunity_id, subject_id, scene_id, creator_party_id,
                proposal_ref, record_kind, query_text, result_limit,
                query_digest, execution_work_id, status, trace_id
            ) VALUES (
                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                %s, %s, 'pending', %s
            )
            """,
            (
                draft.intent_id,
                draft.subject_commit_id,
                draft.source_opportunity_id,
                draft.subject_id,
                draft.scene_id,
                draft.creator_party_id,
                draft.proposal_ref,
                draft.record_kind,
                draft.query_text,
                draft.result_limit,
                draft.query_digest.value,
                draft.execution_work_id,
                draft.trace_id.value,
            ),
        )

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
                      AND status = 'candidate_validated'
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
                      AND status = 'candidate_validated'
                    RETURNING cognitive_episode_id
                    """,
                    (status.value, application_status.value, episode_id),
                )
            ).fetchone()
        if row is None:
            raise SubjectCommitViolation("SUBJECT-WORK-STALE")


__all__ = ("PostgreSQLCognitionSubjectCommit",)
