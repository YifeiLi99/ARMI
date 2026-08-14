"""Context-owned persistence and owner-port snapshot assembly."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import UUID, uuid7

import rfc8785
from armi_activity.api import ActivityReadPort
from armi_capability.api import CapabilityContextStatePayload, CapabilityReadPort
from armi_codex.api import CodexTaskSourceReadPort
from armi_effect.api import EffectOperationReadPort
from armi_evidence.api import EvidenceId, EvidenceReadPort
from armi_expression.api import ExpressionIntentReadPort
from armi_interaction.api import InteractionContextReadPort, InteractionContextTurn
from armi_kernel.application import (
    ArtifactId,
    ArtifactRef,
    ArtifactViolation,
    AuditDraft,
    AuditEventId,
    AuditReference,
    AuditResultStatus,
    AuditSensitivity,
    CognitiveEpisodeId,
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
from armi_memory.api import MemoryReadPort
from armi_mood.api import MoodReadPort
from armi_opportunity.api import (
    OpportunityCognitionSelectionPort,
    OpportunityContextReadPort,
)
from armi_prompt.api import PromptContextSource, PromptReadPort
from armi_relationship.api import RelationshipReadPort
from armi_runtime_foundation import PostgreSQLRuntimeUnitOfWork
from armi_sleep.api import SleepReadPort
from armi_subject_state.api import SubjectStateReadPort

from .api import (
    ContextArtifactCatalogPort,
    ContextEpisodePort,
    ContextResult,
    ContextRuntimeSubjectPort,
    ContextSelectionPort,
    ContextViolation,
)

_MODEL_WORK_KIND = "cognition.model.invoke"


@dataclass(frozen=True, slots=True)
class ContextArtifactSource:
    ref: ArtifactRef
    source_id: UUID
    source_version: int
    source_kind: str
    task_manifest_digest: Digest | None = None


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
    capability_state_payloads: tuple[CapabilityContextStatePayload, ...]
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
    def __init__(
        self,
        relationships: RelationshipReadPort,
        sleep: SleepReadPort,
        activities: ActivityReadPort,
        capabilities: CapabilityReadPort,
        catalog: ContextArtifactCatalogPort,
        *,
        selection: ContextSelectionPort,
        episodes: ContextEpisodePort,
        subjects: ContextRuntimeSubjectPort,
        opportunities: OpportunityContextReadPort,
        opportunity_transitions: OpportunityCognitionSelectionPort,
        evidence: EvidenceReadPort,
        interaction: InteractionContextReadPort,
        expression: ExpressionIntentReadPort,
        effects: EffectOperationReadPort,
        codex: CodexTaskSourceReadPort,
        memories: MemoryReadPort,
        mood: MoodReadPort,
        prompts: PromptReadPort,
        subject_state: SubjectStateReadPort,
    ) -> None:
        self._relationships = relationships
        self._sleep = sleep
        self._activities = activities
        self._capabilities = capabilities
        self._catalog = catalog
        self._selection = selection
        self._episodes = episodes
        self._subjects = subjects
        self._opportunities = opportunities
        self._opportunity_transitions = opportunity_transitions
        self._evidence = evidence
        self._interaction = interaction
        self._expression = expression
        self._effects = effects
        self._codex = codex
        self._memories = memories
        self._mood = mood
        self._prompts = prompts
        self._subject_state = subject_state

    async def select_one(self) -> CognitiveEpisodeId | None:
        return await self._selection.select_once()

    async def snapshot(
        self, unit_of_work: PostgreSQLRuntimeUnitOfWork, episode_id: UUID
    ) -> ContextEpisodeSnapshot:
        tx = unit_of_work.transaction
        episode = await self._episodes.context_episode(tx, episode_id=episode_id)
        opportunity = await self._opportunities.context_snapshot(
            tx, opportunity_id=episode.opportunity_id
        )
        subject = await self._subjects.current_subject(
            tx, subject_id=episode.subject_id
        )
        if (
            subject.subject_version != episode.base_subject_version
            or subject.state_epoch != episode.base_state_epoch
            or subject.bundle_activation_id != episode.bundle_activation_id
        ):
            raise ContextViolation("CTX-WORK-STALE")

        prompt_sources = await self._prompts.context_sources(
            tx, subject_id=episode.subject_id
        )
        components = await self._subject_state.current_heads(
            tx, subject_id=episode.subject_id
        )
        mood = await self._mood.current(tx, subject_id=episode.subject_id)
        component_payloads = tuple(
            (
                item.kind.value,
                item.current_revision_id,
                item.version,
                item.canonical_state,
            )
            for item in components
        )
        component_payloads += (
            ("mood", mood.current_revision_id, mood.version, mood.canonical_state),
        )
        memory_rows = await self._memories.maintenance_context(
            tx,
            subject_id=episode.subject_id,
            generation_id=subject.generation_id,
            enabled=episode.purpose == "maintain_subjective_memory",
            limit=8,
        )
        memory_payloads = tuple(
            (
                item.memory_id,
                item.head_version,
                rfc8785.dumps(
                    {
                        "source_kind": item.source_kind.value,
                        "fact_class": item.fact_class.value,
                        "summary": item.summary,
                        "uncertainty": item.uncertainty,
                        "accessibility": item.accessibility.value,
                    }
                ),
                item.accessibility.value,
            )
            for item in memory_rows
        )
        other_human = episode.purpose == "consider_other_human_input"
        relationship_bundle = await self._relationships.context_bundle(
            tx,
            subject_id=episode.subject_id,
            generation_id=subject.generation_id,
            other_party_id=None
            if episode.purpose == "perform_subject_self_check"
            else episode.context_party_id,
            scope=None
            if episode.purpose == "perform_subject_self_check"
            else ("other_human_social" if other_human else "creator_social"),
        )
        activity = await self._activities.context_summary(
            tx, subject_id=episode.subject_id, enabled=not other_human
        )
        capabilities = (
            ()
            if other_human
            else await self._capabilities.context_state_payloads(
                tx, subject_id=episode.subject_id
            )
        )

        evidence_source = None
        current_interaction_id = None
        task_manifest_digest = None
        if opportunity.evidence_id is not None:
            item = await self._evidence.snapshot(
                tx, evidence_id=EvidenceId(opportunity.evidence_id)
            )
            current_interaction_id = item.interaction_id
            source_id = item.codex_task_source_id or item.evidence_id.value
            if item.codex_task_source_id is not None:
                task = await self._codex.task_source(
                    tx, task_source_id=item.codex_task_source_id
                )
                task_manifest_digest = task.task_manifest_digest
            evidence_source = ContextArtifactSource(
                await self._artifact_ref(unit_of_work, item.artifact_id),
                source_id,
                1,
                item.source_kind.value,
                task_manifest_digest,
            )
        elif episode.life_query_result_artifact_id is not None:
            evidence_source = ContextArtifactSource(
                await self._artifact_ref(
                    unit_of_work, episode.life_query_result_artifact_id
                ),
                episode.life_query_intent_id or opportunity.source_ref,
                1,
                "life_query_result",
            )

        scene_bytes = None
        recent: tuple[ContextSceneTurnSource, ...] = ()
        if episode.scene_id is not None:
            scene = await self._interaction.context_scene(
                tx,
                scene_id=episode.scene_id,
                context_party_id=episode.context_party_id,
                current_interaction_id=current_interaction_id,
            )
            scene_bytes = rfc8785.dumps(
                {
                    "scene_key": scene.scene_key,
                    "scene_kind": scene.scene_kind,
                    "audience_scope": scene.audience_scope,
                    "status": scene.status,
                    "primary_party_id": str(
                        scene.primary_party_id or episode.context_party_id
                    ),
                    "context_party_id": str(episode.context_party_id),
                    "context_party_display_label": scene.context_party_label,
                    "sender_party_kind": scene.context_party_kind,
                    "addressed_to_subject": scene.addressed_to_subject,
                }
            )
            kinds = (
                ("other_human_input", "party_response")
                if other_human
                else ("creator_input", "party_response")
            )
            turns = await self._interaction.recent_context_turns(
                tx,
                scene_id=episode.scene_id,
                before_interaction_id=current_interaction_id,
                before_time=(
                    opportunity.available_after
                    if episode.purpose == "consider_creator_outreach"
                    else None
                ),
                source_kinds=kinds,
                limit=8,
            )
            recent_items: list[ContextSceneTurnSource] = []
            for turn in turns:
                source = await self._turn_source(unit_of_work, turn)
                if source is not None:
                    recent_items.append(source)
            recent = tuple(recent_items)

        outreach = (
            rfc8785.dumps(
                {
                    "schema_version": "armi.creator-outreach-trigger.v1",
                    "kind": opportunity.source_kind,
                    "source_ref": str(opportunity.source_ref),
                    "source_version": opportunity.source_version,
                    "available_after": opportunity.available_after.isoformat(),
                    "scene_id": str(episode.scene_id),
                }
            )
            if episode.purpose == "consider_creator_outreach"
            else None
        )
        return ContextEpisodeSnapshot(
            episode_id=episode.episode_id,
            opportunity_id=episode.opportunity_id,
            subject_id=episode.subject_id,
            life_generation_id=subject.generation_id,
            scene_id=episode.scene_id,
            creator_party_id=None if other_human else episode.context_party_id,
            other_party_id=episode.context_party_id if other_human else None,
            purpose=episode.purpose,
            subject_version=episode.base_subject_version,
            state_epoch=episode.base_state_epoch,
            bundle_activation_id=episode.bundle_activation_id,
            policy_version="armi.context-policy.v3",
            mechanism_identity=episode.mechanism_identity,
            trace_id=episode.trace_id,
            component_payloads=component_payloads,
            memory_payloads=memory_payloads,
            has_memory_records=bool(memory_rows),
            relationship_payloads=relationship_bundle.relationships,
            relationship_commitment_payloads=relationship_bundle.commitments,
            relationship_issue_payloads=relationship_bundle.open_issues,
            material_sources=(),
            activity_summary_bytes=activity,
            capability_state_payloads=capabilities,
            scene_bytes=scene_bytes,
            evidence=evidence_source,
            outreach_trigger_bytes=outreach,
            opportunity_source_kind=opportunity.source_kind,
            opportunity_source_ref=opportunity.source_ref,
            opportunity_source_version=opportunity.source_version,
            opportunity_available_after=opportunity.available_after,
            opportunity_expires_at=opportunity.expires_at,
            fixed_prompt=await self._prompt_source(
                unit_of_work, prompt_sources.fixed, "fixed_prompt"
            ),
            creator_prompt=None
            if prompt_sources.creator is None
            else await self._prompt_source(
                unit_of_work, prompt_sources.creator, "creator_prompt"
            ),
            subject_prompt=None
            if prompt_sources.subject is None
            else await self._prompt_source(
                unit_of_work, prompt_sources.subject, "subject_prompt"
            ),
            recent_scene_sources=recent,
        )

    async def settle_prepared(
        self,
        unit_of_work: PostgreSQLRuntimeUnitOfWork,
        *,
        lease: WorkLease,
        episode_id: UUID,
        result: ContextResult,
        manifest_artifact: ArtifactRef,
        compiled_artifact: ArtifactRef,
    ) -> None:
        tx = unit_of_work.transaction
        for item in result.items:
            source = item.candidate.source
            await tx.execute(
                """INSERT INTO armi.cognitive_context_items (
                   context_item_id,cognitive_episode_id,ordinal,section,item_kind,
                   source_kind,source_ref,source_version,trust_class,privacy_scope,
                   disposition,reason_code,content_bytes)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,'private',%s,%s,%s)""",
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
                    item.disposition.value,
                    item.reason_code,
                    item.content_bytes,
                ),
            )
        episode = await self._episodes.mark_context_prepared(
            tx,
            episode_id=episode_id,
            manifest_artifact_id=manifest_artifact.artifact_id.value,
            compiled_artifact_id=compiled_artifact.artifact_id.value,
            context_digest=manifest_artifact.content_digest,
        )
        from datetime import UTC

        now = Instant(datetime.now(UTC))
        await unit_of_work.work.enqueue(
            WorkDraft(
                WorkId(uuid7()),
                _MODEL_WORK_KIND,
                WorkOwner("cognitive_episode", episode_id),
                IdempotencyKey(f"model:{episode_id}"),
                manifest_artifact.content_digest,
                50,
                now,
                Instant(now.value + timedelta(seconds=3600)),
                2,
                episode.trace_id,
                SubjectId(episode.subject_id),
                WorkPayloadRef("cognitive_episode", episode_id),
            )
        )
        await unit_of_work.work.complete(
            lease, WorkResultRef("cognitive_episode", episode_id)
        )
        await unit_of_work.audit.append(
            AuditDraft(
                AuditEventId(uuid7()),
                AuditReference("runtime", unit_of_work.environment_id),
                Purpose("cognition.context"),
                "cognition.context.prepared",
                AuditReference("cognitive_episode", episode_id),
                AuditResultStatus.COMPLETED,
                episode.trace_id,
                AuditSensitivity.PRIVATE,
                subject_id=SubjectId(episode.subject_id),
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
                episode.trace_id,
                AuditSensitivity.PRIVATE,
                subject_id=SubjectId(episode.subject_id),
            )
        )

    async def fail(
        self,
        unit_of_work: PostgreSQLRuntimeUnitOfWork,
        *,
        lease: WorkLease,
        episode_id: UUID,
        code: str,
    ) -> None:
        episode = await self._episodes.fail_context(
            unit_of_work.transaction, episode_id=episode_id, error_code=code
        )
        if not await self._opportunity_transitions.resolve_cognition_failure(
            unit_of_work.transaction, opportunity_id=episode.opportunity_id
        ):
            raise ContextViolation("CTX-OPPORTUNITY-STATE")
        await unit_of_work.work.fail(lease, error_code=code)

    async def _turn_source(
        self, unit: PostgreSQLRuntimeUnitOfWork, turn: InteractionContextTurn
    ) -> ContextSceneTurnSource | None:
        artifact_id = None
        if turn.source_kind in {"creator_input", "other_human_input"}:
            evidence_id = await self._evidence.find_by_interaction(
                unit.transaction, interaction_id=turn.source_ref
            )
            if evidence_id is not None:
                artifact_id = (
                    await self._evidence.snapshot(
                        unit.transaction, evidence_id=evidence_id
                    )
                ).artifact_id
        elif turn.source_kind == "party_response":
            effect = await self._effects.by_effect_id(
                unit.transaction, effect_id=turn.source_ref
            )
            if effect is not None:
                intent = await self._expression.revision_snapshot(
                    unit.transaction,
                    action_intent_revision_id=effect.action_intent_revision_id,
                )
                artifact_id = intent.response_artifact_id
        if artifact_id is None:
            return None
        speaker = (
            "creator"
            if turn.source_kind == "creator_input"
            else "other_human"
            if turn.source_kind == "other_human_input"
            else "armi"
        )
        return ContextSceneTurnSource(
            await self._artifact_ref(unit, artifact_id),
            turn.timeline_item_id,
            turn.source_event_no,
            speaker,
            turn.occurred_at,
            turn.speaker_label,
        )

    async def _prompt_source(
        self, unit: PostgreSQLRuntimeUnitOfWork, source: PromptContextSource, kind: str
    ) -> ContextArtifactSource:
        return ContextArtifactSource(
            await self._artifact_ref(unit, source.artifact_id),
            source.source_id,
            source.source_version,
            kind,
        )

    async def _artifact_ref(
        self, unit: PostgreSQLRuntimeUnitOfWork, artifact_id: UUID
    ) -> ArtifactRef:
        try:
            ref = await self._catalog.retained_ref(unit, ArtifactId(artifact_id))
        except ArtifactViolation:
            raise ContextViolation("CTX-SOURCE-INVALID") from None
        if ref is None:
            raise ContextViolation("CTX-SOURCE-MISSING")
        return ref


__all__ = (
    "ContextArtifactSource",
    "ContextEpisodeSnapshot",
    "ContextMaterialSource",
    "ContextSceneTurnSource",
    "PostgreSQLContextRepository",
)
