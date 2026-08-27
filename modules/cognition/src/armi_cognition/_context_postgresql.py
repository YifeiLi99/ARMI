"""Cognition-owned lifecycle for Context preparation episodes."""

from __future__ import annotations

from collections.abc import Sequence
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
            cursor = await (
                await transaction.execute(
                    """SELECT latest_accepted_ordinal,processed_through_ordinal
                       FROM armi.cognition_maintenance_cursors
                       WHERE subject_id=%s AND life_generation_id=%s
                         AND latest_accepted_ordinal > processed_through_ordinal
                       FOR UPDATE""",
                    (draft.subject_id, draft.generation_id),
                )
            ).fetchone()
            if cursor is not None:
                existing = await (
                    await transaction.execute(
                        """SELECT maintenance_batch_id
                           FROM armi.cognition_maintenance_batches
                           WHERE subject_id=%s AND life_generation_id=%s
                             AND status IN ('prepared','running')
                           FOR UPDATE""",
                        (draft.subject_id, draft.generation_id),
                    )
                ).fetchone()
                if existing is None:
                    processed = int(cursor[1])
                    latest = int(cursor[0])
                    candidate_sources = (
                        await self._experiences.accepted_in_ordinal_window(
                            transaction,
                            subject_id=draft.subject_id,
                            after_ordinal=processed,
                            through_ordinal=latest,
                            limit=65,
                        )
                    )
                    sources = candidate_sources[:64]
                    frozen_through = (
                        sources[-1].acceptance_ordinal
                        if len(candidate_sources) == 65
                        else latest
                    )
                    batch_id = uuid7()
                    await transaction.execute(
                        """INSERT INTO armi.cognition_maintenance_batches (
                               maintenance_batch_id,subject_id,life_generation_id,
                               trigger_kind,status,base_subject_version,
                               frozen_from_ordinal,frozen_through_ordinal,
                               visible_source_count)
                           VALUES (%s,%s,%s,%s,'running',%s,%s,%s,%s)""",
                        (
                            batch_id,
                            draft.subject_id,
                            draft.generation_id,
                            draft.maintenance_trigger_kind,
                            draft.base_subject_version,
                            processed,
                            frozen_through,
                            len(sources),
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
                else:
                    batch_id = cast(UUID, existing[0])
                    await transaction.execute(
                        """UPDATE armi.cognition_maintenance_batches
                           SET status='running'
                           WHERE maintenance_batch_id=%s AND status='prepared'""",
                        (batch_id,),
                    )
                await transaction.execute(
                    """UPDATE armi.cognitive_episodes SET maintenance_batch_id=%s
                       WHERE cognitive_episode_id=%s""",
                    (batch_id, draft.episode_id),
                )
        elif row is not None and draft.purpose in {
            "reflect_self",
            "reflect_mind",
            "reflect_mood",
            "reflect_prompt",
        }:
            await transaction.execute(
                """UPDATE armi.cognitive_episodes AS episode
                   SET maintenance_batch_id=batch.maintenance_batch_id
                   FROM armi.cognition_maintenance_batches AS batch
                   WHERE episode.cognitive_episode_id=%s
                     AND batch.subject_id=%s
                     AND batch.life_generation_id=%s
                     AND batch.status='running'""",
                (draft.episode_id, draft.subject_id, draft.generation_id),
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
                       FROM armi.cognitive_episodes AS episode
                       JOIN armi.cognition_maintenance_batch_sources AS source
                         ON source.maintenance_batch_id=episode.maintenance_batch_id
                       JOIN armi.cognition_maintenance_batches AS batch
                         ON source.maintenance_batch_id=batch.maintenance_batch_id
                       WHERE episode.cognitive_episode_id=%s
                         AND batch.status='running'
                       ORDER BY source.ordinal""",
                    (episode_id,),
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
            "consider_creator_voice_input",
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
        manifest_digest: Digest,
        compiled_digest: Digest,
    ) -> CognitionContextEpisodeSnapshot:
        row = await (
            await transaction.execute(
                """UPDATE armi.cognitive_episodes SET status='prepared',
                      context_manifest_artifact_id=%s,
                      compiled_context_artifact_id=%s,
                      context_manifest_digest=%s, compiled_context_digest=%s,
                      prepared_at=statement_timestamp()
               WHERE cognitive_episode_id=%s AND status='preparing'
               RETURNING cognitive_episode_id, opportunity_id, subject_id, scene_id,
                         context_party_id, purpose, base_subject_version,
                         base_state_epoch, bundle_activation_id, mechanism_identity,
                         trace_id""",
                (
                    manifest_artifact_id,
                    compiled_artifact_id,
                    manifest_digest.value,
                    compiled_digest.value,
                    episode_id,
                ),
            )
        ).fetchone()
        if row is None:
            raise CandidateViolation("CANDIDATE-EPISODE-STATE")
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
