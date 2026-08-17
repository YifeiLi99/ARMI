"""Cognition-owned lifecycle for Context preparation episodes."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import cast
from uuid import UUID, uuid7

from armi_kernel.application import CandidateViolation
from armi_kernel.contracts import Digest, TraceId
from armi_runtime_foundation import PostgreSQLTransaction

from .api import (
    CognitionContextEpisodeDraft,
    CognitionContextEpisodeSnapshot,
    CognitionExperienceContextItem,
)


class PostgreSQLCognitionContextLifecycle:
    async def create_context_episode(
        self, transaction: PostgreSQLTransaction, draft: CognitionContextEpisodeDraft
    ) -> bool:
        row = await (
            await transaction.execute(
                """INSERT INTO armi.cognitive_episodes (
                   cognitive_episode_id, opportunity_id, subject_id, scene_id,
                   context_party_id, purpose, status, base_subject_version,
                   base_state_epoch, bundle_activation_id, mechanism_identity, trace_id)
               VALUES (%s,%s,%s,%s,%s,%s,'preparing',%s,%s,%s,%s,%s)
               ON CONFLICT (opportunity_id) DO NOTHING
               RETURNING cognitive_episode_id""",
                (
                    draft.episode_id,
                    draft.opportunity_id,
                    draft.subject_id,
                    draft.scene_id,
                    draft.context_party_id,
                    draft.purpose,
                    draft.base_subject_version,
                    draft.base_state_epoch,
                    draft.bundle_activation_id,
                    draft.mechanism_identity,
                    draft.trace_id.value,
                ),
            )
        ).fetchone()
        if row is not None and draft.purpose == "maintain_subjective_memory":
            if draft.maintenance_trigger_kind not in {"runtime_idle", "sleep"}:
                raise CandidateViolation("CANDIDATE-MAINTENANCE-TRIGGER")
            await transaction.execute(
                """UPDATE armi.cognition_maintenance_batches
                   SET status='interrupted',failure_code='MODEL-MAINTENANCE-PREEMPTED',
                       finished_at=statement_timestamp()
                   WHERE subject_id=%s AND life_generation_id=%s
                     AND status IN ('prepared','running')""",
                (draft.subject_id, draft.generation_id),
            )
            cursor = await (
                await transaction.execute(
                    """SELECT cursor.dirty_since,processed.accepted_at,
                              cursor.processed_through_experience_id
                       FROM armi.cognition_maintenance_cursors AS cursor
                       LEFT JOIN armi.accepted_experiences AS processed
                         ON processed.experience_id=
                            cursor.processed_through_experience_id
                       WHERE cursor.subject_id=%s AND cursor.life_generation_id=%s
                         AND cursor.dirty_since IS NOT NULL
                       FOR UPDATE OF cursor""",
                    (draft.subject_id, draft.generation_id),
                )
            ).fetchone()
            if cursor is not None:
                batch_id = uuid7()
                await transaction.execute(
                    """INSERT INTO armi.cognition_maintenance_batches (
                           maintenance_batch_id,subject_id,life_generation_id,
                           trigger_kind,status,base_subject_version)
                       VALUES (%s,%s,%s,%s,'running',%s)""",
                    (
                        batch_id,
                        draft.subject_id,
                        draft.generation_id,
                        draft.maintenance_trigger_kind,
                        draft.base_subject_version,
                    ),
                )
                await transaction.execute(
                    """INSERT INTO armi.cognition_maintenance_batch_sources (
                           maintenance_batch_id,experience_id,ordinal)
                       SELECT %s,experience_id,
                              row_number() OVER (
                                ORDER BY accepted_at,experience_id)::smallint
                       FROM (
                         SELECT experience_id,accepted_at
                         FROM armi.accepted_experiences
                         WHERE subject_id=%s AND (
                           (%s::uuid IS NULL AND accepted_at >= %s)
                           OR
                           (%s::uuid IS NOT NULL
                            AND (accepted_at,experience_id) > (%s,%s))
                         )
                         ORDER BY accepted_at,experience_id LIMIT 64
                       ) AS source""",
                    (
                        batch_id,
                        draft.subject_id,
                        cursor[2],
                        cursor[0],
                        cursor[2],
                        cursor[1],
                        cursor[2],
                    ),
                )
        return row is not None

    async def context_episode(
        self, transaction: PostgreSQLTransaction, *, episode_id: UUID
    ) -> CognitionContextEpisodeSnapshot:
        row = await (
            await transaction.execute(
                """SELECT cognitive_episode_id, opportunity_id, subject_id, scene_id,
                      context_party_id, purpose, base_subject_version,
                      base_state_epoch, bundle_activation_id, mechanism_identity,
                      trace_id
               FROM armi.cognitive_episodes
               WHERE cognitive_episode_id=%s AND status='preparing'""",
                (episode_id,),
            )
        ).fetchone()
        if row is None:
            raise CandidateViolation("CANDIDATE-EPISODE-STATE")
        life = await (
            await transaction.execute(
                """SELECT exact_life_query_intent_id, result_artifact_id
               FROM armi.exact_life_query_intents
               WHERE result_opportunity_id=%s""",
                (row[1],),
            )
        ).fetchone()
        experiences: tuple[CognitionExperienceContextItem, ...] = ()
        purpose = str(row[5])
        if purpose == "maintain_subjective_memory":
            source_rows = await (
                await transaction.execute(
                    """SELECT experience.experience_id,source.ordinal,
                              experience.fact_class,experience.first_person_gist,
                              experience.occurred_at,experience.accepted_at,
                              experience.source_perspective,experience.uncertainty
                       FROM armi.cognition_maintenance_batches AS batch
                       JOIN armi.cognition_maintenance_batch_sources AS source
                         ON source.maintenance_batch_id=batch.maintenance_batch_id
                       JOIN armi.accepted_experiences AS experience
                         ON experience.experience_id=source.experience_id
                       WHERE batch.subject_id=%s AND batch.status='running'
                       ORDER BY source.ordinal""",
                    (row[2],),
                )
            ).fetchall()
            experiences = _experience_context(source_rows, maintenance_source=True)
        elif purpose in {"consider_creator_input", "consider_life_query_result"}:
            source_rows = await (
                await transaction.execute(
                    """SELECT recent.experience_id,recent.ordinal,recent.fact_class,
                              recent.first_person_gist,recent.occurred_at,
                              recent.accepted_at,recent.source_perspective,
                              recent.uncertainty
                       FROM (
                         SELECT experience_id,
                                row_number() OVER (
                                  ORDER BY accepted_at DESC,experience_id DESC
                                ) AS ordinal,
                                fact_class,first_person_gist,occurred_at,accepted_at,
                                source_perspective,uncertainty
                         FROM armi.accepted_experiences
                         WHERE subject_id=%s
                         ORDER BY accepted_at DESC,experience_id DESC LIMIT 8
                       ) AS recent
                       ORDER BY recent.accepted_at,recent.experience_id""",
                    (row[2],),
                )
            ).fetchall()
            experiences = _experience_context(source_rows, maintenance_source=False)
        return _snapshot(row, life, experiences)

    async def mark_context_prepared(
        self,
        transaction: PostgreSQLTransaction,
        *,
        episode_id: UUID,
        manifest_artifact_id: UUID,
        compiled_artifact_id: UUID,
        context_digest: Digest,
    ) -> CognitionContextEpisodeSnapshot:
        row = await (
            await transaction.execute(
                """UPDATE armi.cognitive_episodes SET status='prepared',
                      context_manifest_artifact_id=%s,
                      compiled_context_artifact_id=%s, context_digest=%s,
                      prepared_at=statement_timestamp()
               WHERE cognitive_episode_id=%s AND status='preparing'
               RETURNING cognitive_episode_id, opportunity_id, subject_id, scene_id,
                         context_party_id, purpose, base_subject_version,
                         base_state_epoch, bundle_activation_id, mechanism_identity,
                         trace_id""",
                (
                    manifest_artifact_id,
                    compiled_artifact_id,
                    context_digest.value,
                    episode_id,
                ),
            )
        ).fetchone()
        if row is None:
            raise CandidateViolation("CANDIDATE-EPISODE-STATE")
        branch_roles = (
            ("response_action", "episode_appraisal")
            if str(row[5]) in {"consider_creator_input", "consider_life_query_result"}
            else ("primary",)
        )
        for role in branch_roles:
            await transaction.execute(
                """INSERT INTO armi.cognitive_branches (
                       cognitive_branch_id,cognitive_episode_id,branch_role,status)
                   VALUES (%s,%s,%s,'prepared')
                   ON CONFLICT (cognitive_episode_id,branch_role) DO NOTHING""",
                (uuid7(), episode_id, role),
            )
        return _snapshot(row, None)

    async def fail_context(
        self,
        transaction: PostgreSQLTransaction,
        *,
        episode_id: UUID,
        error_code: str,
    ) -> CognitionContextEpisodeSnapshot:
        row = await (
            await transaction.execute(
                """UPDATE armi.cognitive_episodes SET status='failed', failure_code=%s
               WHERE cognitive_episode_id=%s AND status='preparing'
               RETURNING cognitive_episode_id, opportunity_id, subject_id, scene_id,
                         context_party_id, purpose, base_subject_version,
                         base_state_epoch, bundle_activation_id, mechanism_identity,
                         trace_id""",
                (error_code, episode_id),
            )
        ).fetchone()
        if row is None:
            raise CandidateViolation("CANDIDATE-EPISODE-STATE")
        return _snapshot(row, None)


def _snapshot(
    row: tuple[object, ...],
    life: tuple[object, ...] | None,
    experiences: tuple[CognitionExperienceContextItem, ...] = (),
) -> CognitionContextEpisodeSnapshot:
    return CognitionContextEpisodeSnapshot(
        episode_id=cast(UUID, row[0]),
        opportunity_id=cast(UUID, row[1]),
        subject_id=cast(UUID, row[2]),
        scene_id=cast(UUID | None, row[3]),
        context_party_id=cast(UUID | None, row[4]),
        purpose=str(row[5]),
        base_subject_version=cast(int, row[6]),
        base_state_epoch=cast(int, row[7]),
        bundle_activation_id=cast(UUID, row[8]),
        mechanism_identity=str(row[9]),
        trace_id=TraceId(str(row[10])),
        life_query_intent_id=None if life is None else cast(UUID, life[0]),
        life_query_result_artifact_id=None if life is None else cast(UUID, life[1]),
        experience_context=experiences,
    )


def _experience_context(
    rows: Sequence[tuple[object, ...]], *, maintenance_source: bool
) -> tuple[CognitionExperienceContextItem, ...]:
    return tuple(
        CognitionExperienceContextItem(
            experience_id=cast(UUID, row[0]),
            ordinal=cast(int, row[1]),
            fact_class=str(row[2]),
            first_person_gist=str(row[3]),
            occurred_at=cast(datetime, row[4]),
            accepted_at=cast(datetime, row[5]),
            source_perspective=str(row[6]),
            uncertainty=None if row[7] is None else str(row[7]),
            maintenance_source=maintenance_source,
        )
        for row in rows
    )


__all__ = ("PostgreSQLCognitionContextLifecycle",)
