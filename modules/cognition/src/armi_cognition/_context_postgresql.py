"""Cognition-owned lifecycle for Context preparation episodes."""

from __future__ import annotations

from typing import cast
from uuid import UUID

from armi_kernel.application import CandidateViolation
from armi_kernel.contracts import Digest, TraceId
from armi_runtime_foundation import PostgreSQLTransaction

from .api import CognitionContextEpisodeDraft, CognitionContextEpisodeSnapshot


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
        return _snapshot(row, life)

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
    row: tuple[object, ...], life: tuple[object, ...] | None
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
    )


__all__ = ("PostgreSQLCognitionContextLifecycle",)
