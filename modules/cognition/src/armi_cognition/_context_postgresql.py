"""Cognition-owned lifecycle for Context preparation episodes."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import cast
from uuid import UUID, uuid7

from armi_experience.api import AcceptedExperienceSnapshot, ExperienceReadPort
from armi_kernel.application import CandidateViolation
from armi_kernel.contracts import Digest, TraceId
from armi_runtime_foundation import PostgreSQLTransaction

from .api import (
    CognitionContextEpisodeDraft,
    CognitionContextEpisodeSnapshot,
    CognitionExperienceContextItem,
)


class PostgreSQLCognitionContextLifecycle:
    __slots__ = ("_experiences",)

    def __init__(self, experiences: ExperienceReadPort) -> None:
        self._experiences = experiences

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
                    """SELECT dirty_since,processed_through_experience_id
                       FROM armi.cognition_maintenance_cursors
                       WHERE subject_id=%s AND life_generation_id=%s
                         AND dirty_since IS NOT NULL
                       FOR UPDATE""",
                    (draft.subject_id, draft.generation_id),
                )
            ).fetchone()
            if cursor is not None:
                sources = await self._experiences.accepted_after(
                    transaction,
                    subject_id=draft.subject_id,
                    after_experience_id=cast(UUID | None, cursor[1]),
                    since=cast(datetime, cursor[0]),
                    limit=64,
                )
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
                if sources:
                    await transaction.execute(
                        """INSERT INTO armi.cognition_maintenance_batch_sources (
                               maintenance_batch_id,experience_id,ordinal)
                           SELECT %s,source.experience_id,source.ordinal::smallint
                           FROM unnest(%s::uuid[]) WITH ORDINALITY
                             AS source(experience_id,ordinal)""",
                        (
                            batch_id,
                            [item.experience_id.value for item in sources],
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
                    """SELECT source.experience_id,source.ordinal
                       FROM armi.cognition_maintenance_batches AS batch
                       JOIN armi.cognition_maintenance_batch_sources AS source
                         ON source.maintenance_batch_id=batch.maintenance_batch_id
                       WHERE batch.subject_id=%s AND batch.status='running'
                       ORDER BY source.ordinal""",
                    (row[2],),
                )
            ).fetchall()
            snapshots = await self._experiences.by_ids(
                transaction,
                subject_id=cast(UUID, row[2]),
                experience_ids=tuple(cast(UUID, item[0]) for item in source_rows),
            )
            experiences = _experience_context(
                snapshots,
                ordinals=tuple(cast(int, item[1]) for item in source_rows),
                maintenance_source=True,
            )
        elif purpose in {
            "consider_creator_input",
            "consider_creator_voice_appraisal",
            "consider_life_query_result",
        }:
            snapshots = await self._experiences.recent(
                transaction,
                subject_id=cast(UUID, row[2]),
                limit=8,
            )
            experiences = _experience_context(
                snapshots,
                ordinals=tuple(range(len(snapshots), 0, -1)),
                maintenance_source=False,
            )
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
        purpose = str(row[5])
        branch_roles = (
            ("episode_appraisal",)
            if purpose == "consider_creator_voice_appraisal"
            else ("response_action", "episode_appraisal")
            if purpose in {"consider_creator_input", "consider_life_query_result"}
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
    snapshots: Sequence[AcceptedExperienceSnapshot],
    *,
    ordinals: tuple[int, ...],
    maintenance_source: bool,
) -> tuple[CognitionExperienceContextItem, ...]:
    return tuple(
        CognitionExperienceContextItem(
            experience_id=snapshot.experience_id.value,
            ordinal=ordinal,
            fact_class=snapshot.fact_class.value,
            first_person_gist=snapshot.first_person_gist,
            occurred_at=snapshot.occurred_at,
            accepted_at=snapshot.accepted_at,
            source_perspective=snapshot.source_perspective.value,
            uncertainty=snapshot.uncertainty,
            maintenance_source=maintenance_source,
        )
        for snapshot, ordinal in zip(snapshots, ordinals, strict=True)
    )


__all__ = ("PostgreSQLCognitionContextLifecycle",)
