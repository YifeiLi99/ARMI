"""Fixed PostgreSQL ownership for S023 opportunity and Context state."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, cast
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
from .capability_context import CapabilityStatePayload, load_capability_state_payloads
from .unit_of_work import PostgreSQLUnitOfWork

_WORK_KIND = "cognition.context.prepare"
_MODEL_WORK_KIND = "cognition.model.invoke"
_MECHANISM = "armi.context-compiler.layered-v2"


@dataclass(frozen=True, slots=True)
class ContextArtifactSource:
    ref: ArtifactRef
    source_id: UUID
    source_version: int
    source_kind: str


@dataclass(frozen=True, slots=True)
class ContextSceneTurnSource:
    ref: ArtifactRef
    timeline_item_id: UUID
    source_version: int
    speaker: str
    occurred_at: datetime
    speaker_label: str | None = None


@dataclass(frozen=True, slots=True)
class ContextMaterialSource:
    ref: ArtifactRef
    material_id: UUID
    current_revision_id: UUID
    head_version: int
    owner_party_id: UUID
    material_kind: str
    title: str
    metadata: tuple[tuple[str, str], ...]
    material_status: str
    privacy_status: str

    def __post_init__(self) -> None:
        if (
            type(self.ref) is not ArtifactRef
            or any(
                type(value) is not UUID or value.version != 7
                for value in (
                    self.material_id,
                    self.current_revision_id,
                    self.owner_party_id,
                )
            )
            or type(self.head_version) is not int
            or self.head_version <= 0
            or self.material_kind not in {"diary", "work", "collection", "draft"}
            or type(self.title) is not str
            or not 1 <= len(self.title) <= 256
            or not self.title.strip()
            or "\x00" in self.title
            or type(self.metadata) is not tuple
            or len(self.metadata) > 32
            or any(
                type(key) is not str
                or type(value) is not str
                or "\x00" in key
                or "\x00" in value
                for key, value in self.metadata
            )
            or tuple(sorted(self.metadata)) != self.metadata
            or self.material_status not in {"active", "archived"}
            or self.privacy_status not in {"creator_visible", "private"}
        ):
            raise ContextViolation("CTX-SOURCE-INVALID")


@dataclass(frozen=True, slots=True)
class ContextEpisodeSnapshot:
    episode_id: UUID
    opportunity_id: UUID
    subject_id: UUID
    life_generation_id: UUID
    scene_id: UUID | None
    creator_party_id: UUID | None
    other_party_id: UUID | None
    purpose: str
    subject_version: int
    state_epoch: int
    bundle_activation_id: UUID
    policy_version: str
    mechanism_identity: str
    trace_id: TraceId
    component_payloads: tuple[tuple[str, UUID, int, bytes], ...]
    memory_payloads: tuple[tuple[UUID, int, bytes, str], ...]
    has_memory_records: bool
    relationship_payloads: tuple[tuple[UUID, int, bytes], ...]
    relationship_commitment_payloads: tuple[tuple[UUID, int, bytes, str], ...]
    relationship_issue_payloads: tuple[tuple[UUID, int, bytes], ...]
    material_sources: tuple[ContextMaterialSource, ...]
    activity_summary_bytes: bytes
    capability_state_payloads: tuple[CapabilityStatePayload, ...]
    scene_bytes: bytes | None
    evidence: ContextArtifactSource | None
    outreach_trigger_bytes: bytes | None
    opportunity_source_kind: str
    opportunity_source_ref: UUID
    opportunity_source_version: int
    opportunity_available_after: datetime
    opportunity_expires_at: datetime | None
    fixed_prompt: ContextArtifactSource
    creator_prompt: ContextArtifactSource | None = None
    subject_prompt: ContextArtifactSource | None = None
    recent_scene_sources: tuple[ContextSceneTurnSource, ...] = ()


class PostgreSQLContextRepository:
    """Own SQL for selecting, freezing and settling one Context episode."""

    __slots__ = ("_catalog",)

    def __init__(self) -> None:
        self._catalog = ArtifactCatalogRepository()

    async def select_one(
        self,
        unit_of_work: PostgreSQLUnitOfWork,
    ) -> CognitiveEpisodeId | None:
        connection = unit_of_work._connection_for_repository()  # pyright: ignore[reportPrivateUsage]
        row = await (
            await connection.execute(
                """
                SELECT
                    opportunity.opportunity_id,
                    opportunity.subject_id,
                    opportunity.scene_id,
                    opportunity.context_party_id,
                    COALESCE(
                        interaction.trace_id,
                        other_interaction.trace_id,
                        intent.trace_id,
                        task_source.trace_id,
                        result_task_source.trace_id,
                        replace(opportunity.opportunity_id::text, '-', '')
                    ),
                    subject.subject_version,
                    subject.state_epoch,
                    subject.current_bundle_activation_id,
                    transaction_timestamp(),
                    opportunity.purpose,
                    opportunity.context_party_id
                FROM armi.opportunities AS opportunity
                LEFT JOIN armi.external_evidence AS evidence
                  ON evidence.evidence_id = opportunity.evidence_id
                LEFT JOIN armi.party_input_interactions AS interaction
                  ON interaction.interaction_id
                    = evidence.interaction_id
                LEFT JOIN armi.party_input_interactions AS other_interaction
                  ON other_interaction.interaction_id
                    = evidence.interaction_id
                LEFT JOIN armi.web_observation_requests AS observation
                  ON observation.web_observation_request_id
                    = evidence.web_observation_request_id
                LEFT JOIN armi.web_research_intents AS intent
                  ON intent.web_research_intent_id
                    = observation.web_research_intent_id
                LEFT JOIN armi.codex_task_sources AS task_source
                  ON task_source.codex_task_source_id=evidence.codex_task_source_id
                LEFT JOIN armi.codex_verification_results AS verification
                  ON verification.codex_verification_id=evidence.codex_verification_id
                LEFT JOIN armi.effects AS result_effect
                  ON result_effect.effect_id=verification.effect_id
                LEFT JOIN armi.action_intent_revisions AS result_revision
                  ON result_revision.action_intent_revision_id=result_effect.action_intent_revision_id
                LEFT JOIN armi.codex_task_sources AS result_task_source
                  ON result_task_source.codex_task_source_id=result_revision.codex_task_source_id
                JOIN armi.subjects AS subject
                  ON subject.subject_id = opportunity.subject_id
                 AND subject.singleton_key = 1
                 AND subject.status = 'active'
                WHERE opportunity.eligibility_status = 'eligible'
                  AND opportunity.current_disposition = 'open'
                  AND opportunity.purpose IN (
                      'consider_creator_input', 'consider_web_evidence',
                      'consider_codex_task', 'consider_codex_result',
                      'consider_autonomous_life', 'consider_activity_attention',
                      'consider_activity_internal_work', 'consider_sleep',
                      'consider_life_query_result', 'maintain_subjective_memory',
                      'perform_subject_self_check', 'consider_creator_outreach'
                      , 'consider_other_human_input'
                  )
                  AND opportunity.available_after <= transaction_timestamp()
                  AND NOT EXISTS (
                      SELECT 1
                      FROM armi.deletion_orders AS deletion_order
                      WHERE deletion_order.requester_party_id = COALESCE(
                                opportunity.context_party_id,
                                opportunity.context_party_id
                            )
                        AND deletion_order.status = 'effective'
                        AND (
                            deletion_order.order_kind IN (
                                'stop_use', 'delete_related'
                            )
                            OR (
                                deletion_order.order_kind = 'stop_contact'
                                AND opportunity.purpose IN (
                                    'consider_creator_input',
                                    'consider_other_human_input',
                                    'consider_creator_outreach'
                                )
                            )
                        )
                  )
                  AND (
                      opportunity.expires_at IS NULL
                      OR opportunity.expires_at > transaction_timestamp()
                  )
                  AND (
                      NOT EXISTS (
                          SELECT 1 FROM armi.maintenance_sessions AS maintenance
                          WHERE maintenance.subject_id = opportunity.subject_id
                            AND maintenance.finished_at IS NULL
                      )
                      OR EXISTS (
                          SELECT 1
                          FROM armi.maintenance_sessions AS maintenance
                          JOIN armi.maintenance_session_revisions AS revision
                            ON revision.maintenance_revision_id =
                               maintenance.current_revision_id
                          WHERE maintenance.subject_id = opportunity.subject_id
                            AND maintenance.finished_at IS NULL
                            AND opportunity.source_kind =
                                'maintenance_phase_revision'
                            AND opportunity.source_ref =
                                maintenance.current_revision_id
                            AND opportunity.source_version =
                                maintenance.head_version
                            AND (
                                (opportunity.purpose =
                                    'maintain_subjective_memory'
                                  AND revision.phase = 'memory_maintenance')
                                OR (opportunity.purpose =
                                    'perform_subject_self_check'
                                  AND revision.phase = 'self_check')
                            )
                      )
                  )
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
                selected_at = transaction_timestamp()
            WHERE opportunity_id = %s
              AND current_disposition = 'open'
              AND (expires_at IS NULL OR expires_at > transaction_timestamp())
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
                context_party_id,
                purpose,
                status,
                base_subject_version,
                base_state_epoch,
                bundle_activation_id,
                mechanism_identity,
                trace_id)
            VALUES (
                %s, %s, %s, %s, %s, %s, 'preparing',
                %s, %s, %s, %s, %s)
            """,
            (
                episode_id,
                opportunity_id,
                row[1],
                row[2],
                row[3],
                row[9],
                row[5],
                row[6],
                row[7],
                _MECHANISM,
                trace_id.value,
            ),
        )
        work_digest = Digest.from_bytes(
            rfc8785.dumps(
                {
                    "episode_id": str(episode_id),
                    "opportunity_id": str(opportunity_id),
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
                    episode.context_party_id,
                    episode.base_subject_version,
                    episode.base_state_epoch,
                    episode.bundle_activation_id,
                    'armi.context-policy.v3',
                    episode.mechanism_identity,
                    episode.trace_id,
                    COALESCE(
                        evidence.codex_task_source_id,
                        evidence.evidence_id,
                        life_query.exact_life_query_intent_id
                    ),
                    COALESCE(evidence.artifact_id, life_query.result_artifact_id),
                    prompt.prompt_revision_id,
                    prompt.content_artifact_id,
                    scene.scene_key,
                    scene.scene_kind,
                    scene.audience_scope,
                    scene.current_status,
                    scene.scene_version,
                    episode.purpose,
                    COALESCE(evidence.source_kind, opportunity.source_kind),
                    opportunity.source_kind,
                    opportunity.source_ref,
                    opportunity.source_version,
                    opportunity.available_after,
                    opportunity.expires_at,
                    subject.current_generation_id,
                    creator_prompt.prompt_revision_id,
                    creator_prompt.revision_no,
                    creator_prompt.content_artifact_id,
                    subject_prompt.prompt_revision_id,
                    subject_prompt.revision_no,
                    subject_prompt.content_artifact_id,
                    CASE
                      WHEN episode.purpose = 'consider_creator_input'
                      THEN evidence.interaction_id
                    END,
                    CASE
                      WHEN episode.purpose = 'consider_other_human_input'
                      THEN evidence.interaction_id
                    END,
                    episode.context_party_id,
                    context_party.display_label,
                    current_interaction.addressed_to_subject,
                    scene.primary_party_id,
                    context_party.party_kind
                FROM armi.durable_work AS work
                JOIN armi.cognitive_episodes AS episode
                  ON episode.cognitive_episode_id = work.owner_ref
                 AND work.owner_kind = 'cognitive_episode'
                 AND work.work_kind = 'cognition.context.prepare'
                JOIN armi.opportunities AS opportunity
                  ON opportunity.opportunity_id = episode.opportunity_id
                JOIN armi.subjects AS subject
                  ON subject.subject_id = episode.subject_id
                LEFT JOIN armi.external_evidence AS evidence
                  ON evidence.evidence_id = opportunity.evidence_id
                LEFT JOIN armi.party_input_interactions AS current_interaction
                  ON current_interaction.interaction_id = evidence.interaction_id
                LEFT JOIN armi.exact_life_query_intents AS life_query
                  ON opportunity.source_kind = 'life_query_result'
                 AND life_query.exact_life_query_intent_id = opportunity.source_ref
                 AND life_query.result_opportunity_id = opportunity.opportunity_id
                LEFT JOIN armi.interaction_scenes AS scene
                  ON scene.scene_id = episode.scene_id
                LEFT JOIN armi.parties AS context_party
                  ON context_party.party_id = episode.context_party_id
                JOIN armi.prompt_documents AS document
                  ON document.subject_id = episode.subject_id
                 AND document.prompt_kind = 'personality_anchor'
                 AND document.write_authority = 'fixed'
                 AND document.status = 'active'
                JOIN armi.prompt_revisions AS prompt
                  ON prompt.prompt_revision_id = document.current_revision_id
                LEFT JOIN armi.prompt_documents AS creator_document
                  ON creator_document.subject_id = episode.subject_id
                 AND creator_document.prompt_kind = 'creator_guidance'
                 AND creator_document.write_authority = 'creator'
                 AND creator_document.status = 'active'
                 AND creator_document.current_revision_id IS NOT NULL
                LEFT JOIN armi.prompt_revisions AS creator_prompt
                  ON creator_prompt.prompt_revision_id =
                     creator_document.current_revision_id
                 AND creator_prompt.prompt_document_id =
                     creator_document.prompt_document_id
                LEFT JOIN armi.prompt_documents AS subject_document
                  ON subject_document.subject_id = episode.subject_id
                 AND subject_document.prompt_kind = 'subject_guidance'
                 AND subject_document.write_authority = 'subject'
                 AND subject_document.status = 'active'
                 AND subject_document.current_revision_id IS NOT NULL
                LEFT JOIN armi.prompt_revisions AS subject_prompt
                  ON subject_prompt.prompt_revision_id =
                     subject_document.current_revision_id
                 AND subject_prompt.prompt_document_id =
                     subject_document.prompt_document_id
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
                rfc8785.dumps(item[3]),
            )
            for item in components
        )
        memory_rows = await (
            await connection.execute(
                """
                SELECT memory.memory_id, memory.head_version,
                       revision.source_kind, revision.source_fact_class,
                       revision.summary, revision.uncertainty,
                       revision.accessibility
                FROM armi.subjective_memories AS memory
                JOIN armi.subjective_memory_revisions AS revision
                  ON revision.memory_revision_id = memory.current_revision_id
                WHERE memory.subject_id = %s
                  AND memory.life_generation_id = %s
                  AND %s = 'maintain_subjective_memory'
                  AND revision.accessibility IN ('available', 'faded')
                  AND NOT EXISTS (
                      SELECT 1 FROM armi.deletion_items AS deletion_item
                      WHERE deletion_item.target_kind = 'memory'
                        AND deletion_item.target_ref = memory.memory_id
                        AND deletion_item.result_status IN ('completed', 'partial')
                  )
                ORDER BY
                    CASE revision.accessibility
                        WHEN 'available' THEN 1 ELSE 2
                    END,
                    revision.created_at DESC,
                    memory.memory_id
                LIMIT 8
                """,
                (row[2], row[27], row[20]),
            )
        ).fetchall()
        memory_exists = await (
            await connection.execute(
                """
                SELECT EXISTS (
                    SELECT 1
                    FROM armi.subjective_memories AS memory
                    WHERE memory.subject_id = %s
                      AND memory.life_generation_id = %s
                      AND NOT EXISTS (
                          SELECT 1 FROM armi.deletion_items AS deletion_item
                          WHERE deletion_item.target_kind = 'memory'
                            AND deletion_item.target_ref = memory.memory_id
                            AND deletion_item.result_status IN ('completed', 'partial')
                      )
                )
                """,
                (row[2], row[27]),
            )
        ).fetchone()
        memory_payloads = tuple(
            (
                item[0],
                int(item[1]),
                rfc8785.dumps(
                    {
                        "source_kind": str(item[2]),
                        "fact_class": str(item[3]),
                        "summary": str(item[4]),
                        "uncertainty": None if item[5] is None else str(item[5]),
                        "accessibility": str(item[6]),
                    }
                ),
                str(item[6]),
            )
            for item in memory_rows
        )
        relationship_party_id = (
            row[36] if row[20] == "consider_other_human_input" else row[4]
        )
        relationship_scope = (
            "creator_social"
            if row[20] == "consider_other_human_input" and row[40] == "creator"
            else "other_human_social"
            if row[20] == "consider_other_human_input"
            else "creator_social"
        )
        relationship_rows = await (
            await connection.execute(
                """
                SELECT relationship.relationship_id,
                       relationship.head_version,
                       relationship.scope,
                       revision.facts,
                       revision.interpretation,
                       revision.boundaries,
                       revision.relationship_status,
                       revision.commitments,
                       revision.open_issues
                FROM armi.relationships AS relationship
                JOIN armi.relationship_revisions AS revision
                  ON revision.relationship_revision_id =
                     relationship.current_revision_id
                WHERE relationship.subject_id = %s
                  AND relationship.life_generation_id = %s
                  AND (
                      %s = 'perform_subject_self_check'
                      OR (
                          relationship.other_party_id = %s
                          AND relationship.scope = %s
                      )
                  )
                  AND NOT EXISTS (
                      SELECT 1 FROM armi.deletion_items AS deletion_item
                      WHERE deletion_item.target_kind = 'relationship'
                        AND deletion_item.target_ref = relationship.relationship_id
                        AND deletion_item.result_status IN ('completed', 'partial')
                  )
                ORDER BY relationship.relationship_id
                """,
                (
                    row[2],
                    row[27],
                    row[20],
                    relationship_party_id,
                    relationship_scope,
                ),
            )
        ).fetchall()
        relationship_payloads = tuple(
            (
                item[0],
                int(item[1]),
                rfc8785.dumps(
                    {
                        "scope": str(item[2]),
                        "facts": item[3],
                        "interpretation": str(item[4]),
                        "boundaries": item[5],
                        "status": str(item[6]),
                    }
                ),
            )
            for item in relationship_rows
        )
        relationship_commitment_payloads = tuple(
            (
                UUID(str(commitment["commitment_id"])),
                int(item[1]),
                rfc8785.dumps(
                    {
                        "party_role": commitment["party_role"],
                        "scope": commitment["scope"],
                        "content": commitment["content"],
                        "status": commitment["status"],
                        "last_event_kind": commitment["last_event_kind"],
                        "last_event_summary": commitment["last_event_summary"],
                    }
                ),
                str(commitment["status"]),
            )
            for item in relationship_rows
            for commitment in item[7]
        )
        relationship_issue_payloads = tuple(
            (
                UUID(str(issue["issue_id"])),
                int(item[1]),
                rfc8785.dumps(
                    {
                        "kind": issue["kind"],
                        "summary": issue["summary"],
                        "status": issue["status"],
                    }
                ),
            )
            for item in relationship_rows
            for issue in item[8]
        )
        material_sources: tuple[ContextMaterialSource, ...] = ()
        activity_rows = await (
            await connection.execute(
                """
                SELECT activity.activity_id, activity.head_version,
                       revision.revision_no, revision.status,
                       revision.goal, revision.next_safe_step,
                       revision.progress_summary, revision.waiting_condition,
                       revision.resumption_cue
                FROM armi.activities AS activity
                JOIN armi.activity_revisions AS revision
                  ON revision.activity_revision_id = activity.current_revision_id
                WHERE activity.subject_id = %s
                  AND %s <> 'consider_other_human_input'
                ORDER BY activity.activity_id
                """,
                (row[2], row[20]),
            )
        ).fetchall()
        activity_summary_bytes = rfc8785.dumps(
            {
                "schema_version": "armi.activity-context-summary.v1",
                "activities": [
                    {
                        "activity_id": str(item[0]),
                        "head_version": int(item[1]),
                        "revision_no": int(item[2]),
                        "status": str(item[3]),
                        "goal": str(item[4]),
                        "next_safe_step": str(item[5]),
                        "progress_summary": (None if item[6] is None else str(item[6])),
                        "waiting_condition": (
                            None if item[7] is None else str(item[7])
                        ),
                        "resumption_cue": (None if item[8] is None else str(item[8])),
                    }
                    for item in activity_rows
                ],
            }
        )
        capability_state_payloads = (
            ()
            if row[20] == "consider_other_human_input"
            else await load_capability_state_payloads(
                connection,
                subject_id=row[2],
            )
        )
        scene_bytes = (
            None
            if row[3] is None
            else rfc8785.dumps(
                {
                    "scene_key": str(row[15]),
                    "scene_kind": str(row[16]),
                    "audience_scope": str(row[17]),
                    "status": str(row[18]),
                    "primary_party_id": str(row[39] if row[39] is not None else row[4]),
                    "context_party_id": str(row[4]),
                    "context_party_display_label": row[37],
                    "sender_party_kind": row[40],
                    "addressed_to_subject": row[38],
                }
            )
        )
        recent_scene_sources: tuple[ContextSceneTurnSource, ...] = ()
        if row[3] is not None and row[35] is not None:
            recent_rows = await (
                await connection.execute(
                    """
                    SELECT item.timeline_item_id, item.source_event_no,
                           item.source_kind, item.occurred_at,
                            COALESCE(
                                prior_evidence.artifact_id,
                                response_revision.response_artifact_id
                            ) AS artifact_id,
                            prior_party.display_label,
                            prior_party.party_kind
                    FROM armi.scene_timeline_items AS item
                    JOIN armi.scene_timeline_items AS current_item
                      ON current_item.scene_id = item.scene_id
                     AND current_item.source_kind = 'other_human_input'
                     AND current_item.source_ref = %s
                    LEFT JOIN armi.party_input_interactions AS prior_input
                      ON item.source_kind = 'other_human_input'
                     AND prior_input.interaction_id = item.source_ref
                     AND prior_input.scene_id = item.scene_id
                    LEFT JOIN armi.external_evidence AS prior_evidence
                      ON prior_evidence.interaction_id =
                         prior_input.interaction_id
                      AND prior_evidence.scene_id = item.scene_id
                    LEFT JOIN armi.parties AS prior_party
                      ON prior_party.party_id = prior_input.source_party_id
                    LEFT JOIN armi.effects AS response_effect
                      ON item.source_kind = 'party_response'
                     AND response_effect.effect_id = item.source_ref
                     AND response_effect.scene_id = item.scene_id
                    LEFT JOIN armi.action_intent_revisions AS response_revision
                      ON response_revision.action_intent_revision_id =
                         response_effect.action_intent_revision_id
                    WHERE item.scene_id = %s
                      AND item.source_kind IN (
                          'other_human_input', 'party_response'
                      )
                      AND (item.occurred_at, item.timeline_item_id) <
                          (current_item.occurred_at, current_item.timeline_item_id)
                      AND COALESCE(
                          prior_evidence.artifact_id,
                          response_revision.response_artifact_id
                      ) IS NOT NULL
                    ORDER BY item.occurred_at DESC, item.timeline_item_id DESC
                    LIMIT 8
                    """,
                    (row[35], row[3]),
                )
            ).fetchall()
        elif row[3] is not None and row[34] is not None:
            recent_rows: list[tuple[Any, ...]] = await (
                await connection.execute(
                    """
                    SELECT item.timeline_item_id, item.source_event_no,
                           item.source_kind, item.occurred_at,
                            COALESCE(
                                prior_evidence.artifact_id,
                                response_revision.response_artifact_id
                            ) AS artifact_id,
                            prior_party.display_label,
                            prior_party.party_kind
                    FROM armi.scene_timeline_items AS item
                    JOIN armi.scene_timeline_items AS current_item
                      ON current_item.scene_id = item.scene_id
                     AND current_item.source_kind = 'creator_input'
                     AND current_item.source_ref = %s
                    LEFT JOIN armi.party_input_interactions AS prior_input
                      ON item.source_kind = 'creator_input'
                     AND prior_input.interaction_id = item.source_ref
                     AND prior_input.scene_id = item.scene_id
                     AND prior_input.purpose = 'creator_message'
                    LEFT JOIN armi.external_evidence AS prior_evidence
                      ON prior_evidence.interaction_id =
                         prior_input.interaction_id
                      AND prior_evidence.scene_id = item.scene_id
                    LEFT JOIN armi.parties AS prior_party
                      ON prior_party.party_id = prior_input.source_party_id
                    LEFT JOIN armi.effects AS response_effect
                      ON item.source_kind = 'party_response'
                     AND response_effect.effect_id = item.source_ref
                     AND response_effect.scene_id = item.scene_id
                    LEFT JOIN armi.action_intent_revisions AS response_revision
                      ON response_revision.action_intent_revision_id =
                         response_effect.action_intent_revision_id
                    WHERE item.scene_id = %s
                      AND item.source_kind IN (
                          'creator_input', 'party_response'
                      )
                      AND (
                          item.occurred_at, item.timeline_item_id
                      ) < (
                          current_item.occurred_at,
                          current_item.timeline_item_id
                      )
                      AND COALESCE(
                          prior_evidence.artifact_id,
                          response_revision.response_artifact_id
                      ) IS NOT NULL
                    ORDER BY item.occurred_at DESC, item.timeline_item_id DESC
                    LIMIT 8
                    """,
                    (row[34], row[3]),
                )
            ).fetchall()
        elif row[3] is not None and str(row[20]) == "consider_creator_outreach":
            recent_rows = await (
                await connection.execute(
                    """
                    SELECT item.timeline_item_id, item.source_event_no,
                           item.source_kind, item.occurred_at,
                            COALESCE(
                                prior_evidence.artifact_id,
                                response_revision.response_artifact_id
                            ) AS artifact_id,
                            prior_party.display_label,
                            prior_party.party_kind
                    FROM armi.scene_timeline_items AS item
                    LEFT JOIN armi.party_input_interactions AS prior_input
                      ON item.source_kind = 'creator_input'
                     AND prior_input.interaction_id = item.source_ref
                     AND prior_input.scene_id = item.scene_id
                     AND prior_input.purpose = 'creator_message'
                    LEFT JOIN armi.external_evidence AS prior_evidence
                      ON prior_evidence.interaction_id =
                         prior_input.interaction_id
                      AND prior_evidence.scene_id = item.scene_id
                    LEFT JOIN armi.parties AS prior_party
                      ON prior_party.party_id = prior_input.source_party_id
                    LEFT JOIN armi.effects AS response_effect
                      ON item.source_kind = 'party_response'
                     AND response_effect.effect_id = item.source_ref
                     AND response_effect.scene_id = item.scene_id
                    LEFT JOIN armi.action_intent_revisions AS response_revision
                      ON response_revision.action_intent_revision_id =
                         response_effect.action_intent_revision_id
                    WHERE item.scene_id = %s
                      AND item.source_kind IN (
                          'creator_input', 'party_response'
                      )
                      AND item.occurred_at <= %s
                      AND COALESCE(
                          prior_evidence.artifact_id,
                          response_revision.response_artifact_id
                      ) IS NOT NULL
                    ORDER BY item.occurred_at DESC, item.timeline_item_id DESC
                    LIMIT 8
                    """,
                    (row[3], row[25]),
                )
            ).fetchall()
        else:
            recent_rows = []
        if recent_rows:
            recent_sources: list[ContextSceneTurnSource] = []
            for item in reversed(recent_rows):
                recent_sources.append(
                    ContextSceneTurnSource(
                        ref=await self._artifact_ref(connection, item[4]),
                        timeline_item_id=item[0],
                        source_version=int(item[1]),
                        speaker=(
                            "creator"
                            if str(item[2]) == "other_human_input"
                            and item[6] == "creator"
                            else "other_human"
                            if str(item[2]) == "other_human_input"
                            else "creator"
                            if str(item[2]) == "creator_input"
                            else "armi"
                        ),
                        occurred_at=item[3],
                        speaker_label=(
                            str(item[5])
                            if row[16] == "group_dialogue" and item[5] is not None
                            else None
                        ),
                    )
                )
            recent_scene_sources = tuple(recent_sources)
        evidence = (
            None
            if row[12] is None
            else ContextArtifactSource(
                await self._artifact_ref(connection, row[12]),
                row[11],
                1,
                str(row[21]),
            )
        )
        outreach_trigger_bytes = (
            rfc8785.dumps(
                {
                    "schema_version": "armi.creator-outreach-trigger.v1",
                    "kind": str(row[22]),
                    "source_ref": str(row[23]),
                    "source_version": int(row[24]),
                    "available_after": row[25].isoformat(),
                    "scene_id": str(row[3]),
                }
            )
            if str(row[20]) == "consider_creator_outreach"
            else None
        )
        return ContextEpisodeSnapshot(
            episode_id=row[0],
            opportunity_id=row[1],
            subject_id=row[2],
            life_generation_id=row[27],
            scene_id=row[3],
            creator_party_id=(
                None if str(row[20]) == "consider_other_human_input" else row[4]
            ),
            other_party_id=(
                row[4] if str(row[20]) == "consider_other_human_input" else None
            ),
            purpose=str(row[20]),
            subject_version=int(row[5]),
            state_epoch=int(row[6]),
            bundle_activation_id=row[7],
            policy_version=str(row[8]),
            mechanism_identity=str(row[9]),
            trace_id=TraceId(str(row[10])),
            component_payloads=component_payloads,
            memory_payloads=memory_payloads,
            has_memory_records=bool(memory_exists and memory_exists[0]),
            relationship_payloads=relationship_payloads,
            relationship_commitment_payloads=relationship_commitment_payloads,
            relationship_issue_payloads=relationship_issue_payloads,
            material_sources=material_sources,
            activity_summary_bytes=activity_summary_bytes,
            capability_state_payloads=capability_state_payloads,
            scene_bytes=scene_bytes,
            evidence=evidence,
            outreach_trigger_bytes=outreach_trigger_bytes,
            opportunity_source_kind=str(row[22]),
            opportunity_source_ref=row[23],
            opportunity_source_version=int(row[24]),
            opportunity_available_after=row[25],
            opportunity_expires_at=row[26],
            fixed_prompt=ContextArtifactSource(
                await self._artifact_ref(connection, row[14]),
                row[13],
                1,
                "fixed_prompt",
            ),
            creator_prompt=(
                None
                if row[28] is None
                else ContextArtifactSource(
                    await self._artifact_ref(connection, row[30]),
                    row[28],
                    int(row[29]),
                    "creator_prompt",
                )
            ),
            subject_prompt=(
                None
                if row[31] is None
                else ContextArtifactSource(
                    await self._artifact_ref(connection, row[33]),
                    row[31],
                    int(row[32]),
                    "subject_prompt",
                )
            ),
            recent_scene_sources=recent_scene_sources,
        )

    async def settle_prepared(
        self,
        unit_of_work: PostgreSQLUnitOfWork,
        *,
        lease: WorkLease,
        result: ContextResult,
        manifest_artifact: ArtifactRef,
        compiled_artifact: ArtifactRef,
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
                    trust_class,
                    privacy_scope,
                    disposition,
                    reason_code,
                    content_bytes)
                VALUES (
                    %s, %s, %s, %s, %s, %s, %s, %s,
                    %s, %s, %s, %s, %s)
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
                RETURNING subject_id, trace_id, statement_timestamp()
                """,
                (
                    manifest_artifact.artifact_id.value,
                    compiled_artifact.artifact_id.value,
                    manifest_artifact.content_digest.value,
                    episode_id,
                ),
            )
        ).fetchone()
        if updated is None:
            raise ContextViolation("CTX-WORK-STALE")
        model_now = Instant(updated[2])
        await unit_of_work.work.enqueue(
            WorkDraft(
                WorkId(uuid7()),
                _MODEL_WORK_KIND,
                WorkOwner("cognitive_episode", episode_id),
                IdempotencyKey(f"model:{episode_id}"),
                manifest_artifact.content_digest,
                50,
                model_now,
                Instant(model_now.value + timedelta(seconds=3600)),
                2,
                TraceId(str(updated[1])),
                SubjectId(updated[0]),
                WorkPayloadRef("cognitive_episode", episode_id),
            )
        )
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
            )
        )
        await unit_of_work.audit.append(
            AuditDraft(
                AuditEventId(uuid7()),
                AuditReference("runtime", unit_of_work.environment_id),
                Purpose("cognition.model"),
                "cognition.model.queued",
                AuditReference("cognitive_episode", episode_id),
                AuditResultStatus.WAITING,
                TraceId(str(updated[1])),
                AuditSensitivity.PRIVATE,
                subject_id=SubjectId(updated[0]),
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
        resolved = await (
            await connection.execute(
                """
                UPDATE armi.opportunities AS opportunity
                SET current_disposition = 'resolved',
                    resolved_at = statement_timestamp()
                FROM armi.cognitive_episodes AS episode
                WHERE episode.cognitive_episode_id = %s
                  AND opportunity.opportunity_id = episode.opportunity_id
                  AND opportunity.current_disposition = 'selected'
                RETURNING opportunity.opportunity_id
                """,
                (episode_id,),
            )
        ).fetchone()
        if resolved is None:
            raise ContextViolation("CTX-OPPORTUNITY-STATE")
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
                    integrity_status
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
            )
        except TypeError, ValueError:
            raise ContextViolation("CTX-SOURCE-INVALID") from None


def _material_metadata(value: object) -> tuple[tuple[str, str], ...]:
    if type(value) is not dict:
        raise ContextViolation("CTX-SOURCE-INVALID")
    metadata = cast(dict[object, object], value)
    if len(metadata) > 32 or any(
        type(key) is not str or type(item) is not str or "\x00" in key or "\x00" in item
        for key, item in metadata.items()
    ):
        raise ContextViolation("CTX-SOURCE-INVALID")
    return tuple(
        sorted((cast(str, key), cast(str, item)) for key, item in metadata.items())
    )


__all__ = (
    "ContextArtifactSource",
    "ContextEpisodeSnapshot",
    "ContextMaterialSource",
    "ContextSceneTurnSource",
    "PostgreSQLContextRepository",
)
