"""Fixed PostgreSQL ownership for S023 opportunity and Context state."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import Any
from uuid import UUID, uuid7

import rfc8785
from armi_kernel.application import (
    ArtifactId,
    ArtifactIntegrityStatus,
    ArtifactPrivacyScope,
    ArtifactRef,
    AuditDraft,
    AuditEventId,
    AuditReference,
    AuditResultStatus,
    AuditSensitivity,
    CognitiveEpisodeId,
    ContextResult,
    ContextViolation,
    WorkDraft,
    WorkId,
    WorkLease,
    WorkOwner,
    WorkPayloadRef,
    WorkResultRef,
)
from armi_kernel.contracts import (
    Digest,
    IdempotencyKey,
    Instant,
    Purpose,
    SubjectId,
    TraceId,
)

from .artifact_catalog import ArtifactCatalogRepository
from .unit_of_work import PostgreSQLUnitOfWork

_WORK_KIND = "cognition.context.prepare"
_MECHANISM = "armi.context-compiler.deterministic-v1"


@dataclass(frozen=True, slots=True)
class ContextArtifactSource:
    ref: ArtifactRef
    source_id: UUID
    source_version: int


@dataclass(frozen=True, slots=True)
class ContextEpisodeSnapshot:
    episode_id: UUID
    opportunity_id: UUID
    subject_id: UUID
    scene_id: UUID
    creator_party_id: UUID
    subject_version: int
    state_epoch: int
    bundle_activation_id: UUID
    policy_digest: Digest
    mechanism_config_digest: Digest
    trace_id: TraceId
    component_payloads: tuple[tuple[str, UUID, int, bytes, Digest], ...]
    scene_bytes: bytes
    scene_digest: Digest
    evidence: ContextArtifactSource
    fixed_prompt: ContextArtifactSource


class PostgreSQLContextRepository:
    """Own SQL for selecting, freezing and settling one Context episode."""

    __slots__ = ("_catalog",)

    def __init__(self) -> None:
        self._catalog = ArtifactCatalogRepository()

    async def select_one(
        self,
        unit_of_work: PostgreSQLUnitOfWork,
        *,
        policy_digest: Digest,
        mechanism_config_digest: Digest,
    ) -> CognitiveEpisodeId | None:
        connection = unit_of_work._connection_for_repository()  # pyright: ignore[reportPrivateUsage]
        row = await (
            await connection.execute(
                """
                SELECT
                    opportunity.opportunity_id,
                    opportunity.subject_id,
                    opportunity.scene_id,
                    opportunity.creator_party_id,
                    interaction.trace_id,
                    subject.subject_version,
                    subject.state_epoch,
                    subject.current_bundle_activation_id,
                    statement_timestamp()
                FROM armi.opportunities AS opportunity
                JOIN armi.external_evidence AS evidence
                  ON evidence.evidence_id = opportunity.evidence_id
                JOIN armi.creator_input_interactions AS interaction
                  ON interaction.creator_interaction_id
                    = evidence.creator_interaction_id
                JOIN armi.subjects AS subject
                  ON subject.subject_id = opportunity.subject_id
                 AND subject.singleton_key = 1
                 AND subject.status = 'active'
                WHERE opportunity.eligibility_status = 'eligible'
                  AND opportunity.current_disposition = 'open'
                  AND opportunity.available_after <= statement_timestamp()
                  AND opportunity.expires_at IS NULL
                ORDER BY opportunity.available_after, opportunity.opportunity_id
                FOR UPDATE OF opportunity SKIP LOCKED
                LIMIT 1
                """
            )
        ).fetchone()
        if row is None:
            return None
        episode_id = uuid7()
        opportunity_id: UUID = row[0]
        trace_id = TraceId(str(row[4]))
        now = Instant(row[8])
        await connection.execute(
            """
            UPDATE armi.opportunities
            SET current_disposition = 'selected',
                selected_at = statement_timestamp()
            WHERE opportunity_id = %s
              AND current_disposition = 'open'
            """,
            (opportunity_id,),
        )
        await connection.execute(
            """
            INSERT INTO armi.cognitive_episodes (
                cognitive_episode_id,
                opportunity_id,
                subject_id,
                scene_id,
                creator_party_id,
                purpose,
                status,
                base_subject_version,
                base_state_epoch,
                bundle_activation_id,
                policy_digest,
                mechanism_identity,
                mechanism_config_digest,
                trace_id,
                schema_version
            )
            VALUES (
                %s, %s, %s, %s, %s, 'consider_creator_input', 'preparing',
                %s, %s, %s, %s, %s, %s, %s, 1
            )
            """,
            (
                episode_id,
                opportunity_id,
                row[1],
                row[2],
                row[3],
                row[5],
                row[6],
                row[7],
                policy_digest.value,
                _MECHANISM,
                mechanism_config_digest.value,
                trace_id.value,
            ),
        )
        work_digest = Digest.from_bytes(
            rfc8785.dumps(
                {
                    "episode_id": str(episode_id),
                    "opportunity_id": str(opportunity_id),
                    "policy_digest": policy_digest.value,
                    "mechanism_config_digest": mechanism_config_digest.value,
                }
            )
        )
        await unit_of_work.work.enqueue(
            WorkDraft(
                WorkId(uuid7()),
                _WORK_KIND,
                WorkOwner("cognitive_episode", episode_id),
                IdempotencyKey(f"context:{opportunity_id}"),
                work_digest,
                50,
                now,
                Instant(now.value + timedelta(seconds=3600)),
                2,
                trace_id,
                SubjectId(row[1]),
                WorkPayloadRef("cognitive_episode", episode_id),
            )
        )
        await unit_of_work.audit.append(
            AuditDraft(
                AuditEventId(uuid7()),
                AuditReference("runtime", unit_of_work.environment_id),
                Purpose("cognition.context"),
                "opportunity.selected",
                AuditReference("opportunity", opportunity_id),
                AuditResultStatus.APPLIED,
                trace_id,
                AuditSensitivity.PRIVATE,
                subject_id=SubjectId(row[1]),
                request=AuditReference("cognitive_episode", episode_id),
                details_digest=policy_digest,
            )
        )
        return CognitiveEpisodeId(episode_id)

    async def snapshot(
        self,
        unit_of_work: PostgreSQLUnitOfWork,
        lease: WorkLease,
    ) -> ContextEpisodeSnapshot:
        connection = unit_of_work._connection_for_repository()  # pyright: ignore[reportPrivateUsage]
        row = await (
            await connection.execute(
                """
                SELECT
                    episode.cognitive_episode_id,
                    episode.opportunity_id,
                    episode.subject_id,
                    episode.scene_id,
                    episode.creator_party_id,
                    episode.base_subject_version,
                    episode.base_state_epoch,
                    episode.bundle_activation_id,
                    episode.policy_digest,
                    episode.mechanism_config_digest,
                    episode.trace_id,
                    evidence.evidence_id,
                    evidence.artifact_id,
                    prompt.prompt_revision_id,
                    prompt.content_artifact_id,
                    scene.scene_key,
                    scene.scene_kind,
                    scene.audience_scope,
                    scene.current_status,
                    scene.schema_version
                FROM armi.durable_work AS work
                JOIN armi.cognitive_episodes AS episode
                  ON episode.cognitive_episode_id = work.owner_ref
                 AND work.owner_kind = 'cognitive_episode'
                 AND work.work_kind = 'cognition.context.prepare'
                JOIN armi.opportunities AS opportunity
                  ON opportunity.opportunity_id = episode.opportunity_id
                JOIN armi.external_evidence AS evidence
                  ON evidence.evidence_id = opportunity.evidence_id
                JOIN armi.interaction_scenes AS scene
                  ON scene.scene_id = episode.scene_id
                JOIN armi.prompt_documents AS document
                  ON document.subject_id = episode.subject_id
                 AND document.prompt_kind = 'personality_anchor'
                 AND document.write_authority = 'fixed'
                 AND document.status = 'active'
                JOIN armi.prompt_revisions AS prompt
                  ON prompt.prompt_revision_id = document.current_revision_id
                WHERE work.work_id = %s
                  AND work.status = 'leased'
                  AND work.current_attempt_id = %s
                  AND work.lease_owner = %s
                  AND work.lease_token = %s
                  AND work.lease_expires_at >= statement_timestamp()
                  AND episode.status = 'preparing'
                """,
                (
                    lease.work_id.value,
                    lease.attempt_id.value,
                    lease.owner,
                    lease.token,
                ),
            )
        ).fetchone()
        if row is None:
            raise ContextViolation("CTX-WORK-STALE")
        components = await (
            await connection.execute(
                """
                SELECT
                    head.component_kind,
                    revision.component_revision_id,
                    head.component_version,
                    revision.semantic_payload
                FROM armi.subject_component_heads AS head
                JOIN armi.subject_component_revisions AS revision
                  ON revision.component_revision_id = head.current_revision_id
                WHERE head.subject_id = %s
                ORDER BY
                    CASE head.component_kind
                        WHEN 'self' THEN 1
                        WHEN 'mind' THEN 2
                        WHEN 'life_mode' THEN 3
                    END
                """,
                (row[2],),
            )
        ).fetchall()
        if tuple(item[0] for item in components) != ("self", "mind", "life_mode"):
            raise ContextViolation("CTX-SOURCE-MISSING")
        component_payloads = tuple(
            (
                str(item[0]),
                item[1],
                int(item[2]),
                (payload := rfc8785.dumps(item[3])),
                Digest.from_bytes(payload),
            )
            for item in components
        )
        scene_bytes = rfc8785.dumps(
            {
                "scene_key": str(row[15]),
                "scene_kind": str(row[16]),
                "audience_scope": str(row[17]),
                "status": str(row[18]),
            }
        )
        return ContextEpisodeSnapshot(
            row[0],
            row[1],
            row[2],
            row[3],
            row[4],
            int(row[5]),
            int(row[6]),
            row[7],
            Digest(str(row[8])),
            Digest(str(row[9])),
            TraceId(str(row[10])),
            component_payloads,
            scene_bytes,
            Digest.from_bytes(scene_bytes),
            ContextArtifactSource(
                await self._artifact_ref(connection, row[12]),
                row[11],
                1,
            ),
            ContextArtifactSource(
                await self._artifact_ref(connection, row[14]),
                row[13],
                1,
            ),
        )

    async def settle_prepared(
        self,
        unit_of_work: PostgreSQLUnitOfWork,
        *,
        lease: WorkLease,
        result: ContextResult,
        manifest_artifact_id: ArtifactId,
        compiled_artifact_id: ArtifactId,
    ) -> None:
        connection = unit_of_work._connection_for_repository()  # pyright: ignore[reportPrivateUsage]
        episode_id = await self._episode_for_lease(connection, lease)
        for item in result.items:
            source = item.candidate.source
            await connection.execute(
                """
                INSERT INTO armi.cognitive_context_items (
                    context_item_id,
                    cognitive_episode_id,
                    ordinal,
                    section,
                    item_kind,
                    source_kind,
                    source_ref,
                    source_version,
                    source_digest,
                    trust_class,
                    privacy_scope,
                    disposition,
                    reason_code,
                    content_bytes,
                    schema_version
                )
                VALUES (
                    %s, %s, %s, %s, %s, %s, %s, %s, %s,
                    %s, %s, %s, %s, %s, 1
                )
                """,
                (
                    uuid7(),
                    episode_id,
                    item.ordinal,
                    item.candidate.section.value,
                    item.candidate.item_kind,
                    source.kind,
                    source.reference,
                    source.version,
                    source.digest.value if source.digest else None,
                    item.candidate.trust_class.value,
                    "private",
                    item.disposition.value,
                    item.reason_code,
                    item.content_bytes,
                ),
            )
        updated = await (
            await connection.execute(
                """
                UPDATE armi.cognitive_episodes
                SET status = 'prepared',
                    context_manifest_artifact_id = %s,
                    compiled_context_artifact_id = %s,
                    context_digest = %s,
                    prepared_at = statement_timestamp()
                WHERE cognitive_episode_id = %s
                  AND status = 'preparing'
                RETURNING subject_id, trace_id
                """,
                (
                    manifest_artifact_id.value,
                    compiled_artifact_id.value,
                    result.manifest_digest.value,
                    episode_id,
                ),
            )
        ).fetchone()
        if updated is None:
            raise ContextViolation("CTX-WORK-STALE")
        await unit_of_work.work.complete(
            lease,
            WorkResultRef("cognitive_episode", episode_id),
        )
        await unit_of_work.audit.append(
            AuditDraft(
                AuditEventId(uuid7()),
                AuditReference("runtime", unit_of_work.environment_id),
                Purpose("cognition.context"),
                "cognition.context.prepared",
                AuditReference("cognitive_episode", episode_id),
                AuditResultStatus.COMPLETED,
                TraceId(str(updated[1])),
                AuditSensitivity.PRIVATE,
                subject_id=SubjectId(updated[0]),
                response_digest=result.manifest_digest,
                artifact_digest=result.compiled.digest,
            )
        )

    async def fail(
        self,
        unit_of_work: PostgreSQLUnitOfWork,
        *,
        lease: WorkLease,
        code: str,
    ) -> None:
        connection = unit_of_work._connection_for_repository()  # pyright: ignore[reportPrivateUsage]
        episode_id = await self._episode_for_lease(connection, lease)
        updated = await (
            await connection.execute(
                """
                UPDATE armi.cognitive_episodes
                SET status = 'failed', failure_code = %s
                WHERE cognitive_episode_id = %s
                  AND status = 'preparing'
                RETURNING subject_id, trace_id
                """,
                (code, episode_id),
            )
        ).fetchone()
        if updated is None:
            raise ContextViolation("CTX-WORK-STALE")
        await unit_of_work.work.fail(lease, error_code=code)
        await unit_of_work.audit.append(
            AuditDraft(
                AuditEventId(uuid7()),
                AuditReference("runtime", unit_of_work.environment_id),
                Purpose("cognition.context"),
                "cognition.context.failed",
                AuditReference("cognitive_episode", episode_id),
                AuditResultStatus.FAILED,
                TraceId(str(updated[1])),
                AuditSensitivity.PRIVATE,
                subject_id=SubjectId(updated[0]),
            )
        )

    async def _episode_for_lease(self, connection: Any, lease: WorkLease) -> UUID:
        row = await (
            await connection.execute(
                """
                SELECT owner_ref
                FROM armi.durable_work
                WHERE work_id = %s
                  AND work_kind = 'cognition.context.prepare'
                  AND owner_kind = 'cognitive_episode'
                  AND status = 'leased'
                  AND current_attempt_id = %s
                  AND lease_owner = %s
                  AND lease_token = %s
                  AND lease_expires_at >= statement_timestamp()
                FOR UPDATE
                """,
                (
                    lease.work_id.value,
                    lease.attempt_id.value,
                    lease.owner,
                    lease.token,
                ),
            )
        ).fetchone()
        if row is None:
            raise ContextViolation("CTX-WORK-STALE")
        return row[0]

    async def _artifact_ref(self, connection: Any, artifact_id: UUID) -> ArtifactRef:
        row = await (
            await connection.execute(
                """
                SELECT
                    artifact_id,
                    content_digest,
                    byte_size,
                    media_type,
                    logical_kind,
                    privacy_scope,
                    integrity_status,
                    schema_version
                FROM armi.artifacts
                WHERE artifact_id = %s
                  AND retention_status = 'retained'
                """,
                (artifact_id,),
            )
        ).fetchone()
        if row is None:
            raise ContextViolation("CTX-SOURCE-MISSING")
        try:
            return ArtifactRef(
                ArtifactId(row[0]),
                Digest(str(row[1])),
                int(row[2]),
                str(row[3]),
                str(row[4]),
                ArtifactPrivacyScope(str(row[5])),
                ArtifactIntegrityStatus(str(row[6])),
                int(row[7]),
            )
        except TypeError, ValueError:
            raise ContextViolation("CTX-SOURCE-INVALID") from None


__all__ = (
    "ContextArtifactSource",
    "ContextEpisodeSnapshot",
    "PostgreSQLContextRepository",
)
