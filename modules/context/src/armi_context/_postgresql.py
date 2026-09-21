"""Context-owned persistence and owner-port snapshot assembly."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import UUID, uuid7

import rfc8785
from armi_activity.api import ActivityContextTarget, ActivityReadPort, ActivityStatus
from armi_attention.api import (
    OpportunityCognitionSelectionPort,
    OpportunityContextReadPort,
)
from armi_capability.api import CapabilityContextStatePayload, CapabilityReadPort
from armi_codex.api import CodexTaskSourceReadPort
from armi_evidence.api import EvidenceId, EvidenceReadPort
from armi_interaction.api import InteractionContextReadPort
from armi_kernel.application import (
    ArtifactId,
    ArtifactRef,
    ArtifactViolation,
    CognitiveEpisodeId,
    ConsiderationSignal,
    WorkDraft,
    WorkId,
    WorkLease,
    WorkOwner,
    WorkPayloadRef,
    WorkResultRef,
    WorkType,
)
from armi_kernel.contracts import (
    Digest,
    IdempotencyKey,
    Instant,
    SubjectId,
    TraceId,
)
from armi_memory.api import MemoryReadPort
from armi_mind.api import MindReadPort
from armi_mood.api import MoodReadPort, mood_snapshot_bytes
from armi_prompt.api import PromptContextSource, PromptReadPort
from armi_relationship.api import RelationshipReadPort
from armi_runtime_foundation import PostgreSQLRuntimeUnitOfWork
from armi_sleep.api import SleepReadPort
from armi_subject_state.api import SubjectStateReadPort

from .api import (
    ContextArtifactCatalogPort,
    ContextDialogueItem,
    ContextDialogueReadPort,
    ContextEpisodePort,
    ContextExperienceState,
    ContextResult,
    ContextRuntimeSubjectPort,
    ContextSelectionPort,
    ContextViolation,
)

_MODEL_WORK_KIND = WorkType.COGNITION_EXECUTE


@dataclass(frozen=True, slots=True)
class ContextArtifactSource:
    ref: ArtifactRef
    source_id: UUID
    source_version: int
    source_kind: str
    task_manifest_digest: Digest | None = None


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
    observed_at: datetime
    consideration_signals: tuple[ConsiderationSignal, ...]
    component_payloads: tuple[tuple[str, UUID, int, bytes], ...]
    memory_payloads: tuple[tuple[UUID, int, bytes, str], ...]
    experience_context: tuple[ContextExperienceState, ...]
    has_memory_records: bool
    relationship_payloads: tuple[tuple[UUID, int, bytes], ...]
    relationship_commitment_payloads: tuple[tuple[UUID, int, bytes, str], ...]
    relationship_issue_payloads: tuple[tuple[UUID, int, bytes], ...]
    material_sources: tuple[ContextMaterialSource, ...]
    activity_summary_bytes: bytes
    target_activity: ActivityContextTarget | None
    capability_state_payloads: tuple[CapabilityContextStatePayload, ...]
    scene_bytes: bytes | None
    evidence: ContextArtifactSource | None
    opportunity_source_kind: str
    opportunity_source_ref: UUID
    opportunity_source_version: int
    opportunity_available_after: datetime
    opportunity_expires_at: datetime | None
    fixed_prompt: ContextArtifactSource
    creator_prompt: ContextArtifactSource | None = None
    subject_prompt: ContextArtifactSource | None = None
    recent_scene_sources: tuple[ContextDialogueItem, ...] = ()
    autonomy_context: bytes | None = None


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
        codex: CodexTaskSourceReadPort,
        memories: MemoryReadPort,
        mood: MoodReadPort,
        prompts: PromptReadPort,
        subject_state: SubjectStateReadPort,
        mind: MindReadPort,
        dialogue: ContextDialogueReadPort,
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
        self._codex = codex
        self._memories = memories
        self._mood = mood
        self._prompts = prompts
        self._subject_state = subject_state
        self._mind = mind
        self._dialogue = dialogue

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
        mood = await self._mood.snapshot(tx, subject_id=episode.subject_id)
        component_payloads = tuple(
            (
                item.kind.value,
                item.current_revision_id,
                item.version,
                item.canonical_state,
            )
            for item in components
        )
        mind = await self._mind.current_head(tx, subject_id=episode.subject_id)
        component_payloads += (
            ("mind", mind.current_revision_id, mind.version, mind.canonical_state),
        )
        signals = await self._mind.consideration_signals(
            tx,
            subject_id=subject.subject_id,
            event_purpose=opportunity.purpose,
            event_ref=opportunity.opportunity_id,
            event_at=opportunity.available_after,
            activity_id=opportunity.activity_id,
        )
        mood_signals = await self._mood.consideration_signals(
            tx,
            subject_id=subject.subject_id,
            minimum_delay_seconds=opportunity.minimum_consideration_seconds,
        )
        signals = await self._opportunities.unconsumed_signals(
            tx,
            subject_id=subject.subject_id,
            signals=(*signals, *mood_signals),
        )
        signals = tuple(
            signal for signal in signals if signal.eligible_at <= mood.as_of
        )
        component_payloads += (
            ("mood", mood.current_revision_id, mood.version, mood_snapshot_bytes(mood)),
        )
        memory_rows = await self._memories.maintenance_context(
            tx,
            subject_id=episode.subject_id,
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
            other_party_id=None
            if episode.purpose
            in {
                "perform_subject_self_check",
                "reflect_self",
                "reflect_mind",
                "reflect_mood",
                "reflect_prompt",
            }
            else episode.context_party_id,
            scope=None
            if episode.purpose
            in {
                "perform_subject_self_check",
                "reflect_self",
                "reflect_mind",
                "reflect_mood",
                "reflect_prompt",
            }
            else ("other_human_social" if other_human else "creator_social"),
        )
        activity = await self._activities.context_summary(
            tx, subject_id=episode.subject_id, enabled=not other_human
        )
        target_activity = (
            None
            if opportunity.activity_id is None
            else await self._activities.context_target(
                tx,
                subject_id=episode.subject_id,
                activity_id=opportunity.activity_id,
            )
        )
        if opportunity.activity_id is not None and (
            target_activity is None
            or (
                episode.purpose
                not in {"consider_autonomous_life", "consider_autonomy_check"}
                and target_activity.status is not ActivityStatus.IN_PROGRESS
            )
        ):
            raise ContextViolation("CTX-WORK-STALE")
        capabilities = (
            () if other_human else self._capabilities.context_state_payloads()
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
        recent: tuple[ContextDialogueItem, ...] = ()
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
                    "input_origin": "creator_delegate"
                    if scene.delegate_id is not None
                    else "party",
                    "delegate_id": str(scene.delegate_id)
                    if scene.delegate_id is not None
                    else None,
                }
            )
            dialogue_method = (
                self._dialogue.recent_other_human_dialogue
                if other_human
                else self._dialogue.recent_creator_dialogue
            )
            recent = await dialogue_method(
                unit_of_work,
                scene_id=episode.scene_id,
                before_interaction_id=current_interaction_id,
                before_time=(
                    opportunity.available_after
                    if episode.purpose
                    in {"consider_autonomous_life", "consider_autonomy_check"}
                    else None
                ),
                limit=8,
            )

        return ContextEpisodeSnapshot(
            autonomy_context=opportunity.autonomy_context,
            episode_id=episode.episode_id,
            opportunity_id=episode.opportunity_id,
            subject_id=episode.subject_id,
            scene_id=episode.scene_id,
            creator_party_id=None if other_human else episode.context_party_id,
            other_party_id=episode.context_party_id if other_human else None,
            purpose=episode.purpose,
            subject_version=episode.base_subject_version,
            state_epoch=episode.base_state_epoch,
            bundle_activation_id=episode.bundle_activation_id,
            policy_version="armi.context-policy.v5",
            mechanism_identity=episode.mechanism_identity,
            trace_id=episode.trace_id,
            observed_at=mood.as_of,
            consideration_signals=signals,
            component_payloads=component_payloads,
            memory_payloads=memory_payloads,
            experience_context=episode.experience_context,
            has_memory_records=bool(memory_rows),
            relationship_payloads=relationship_bundle.relationships,
            relationship_commitment_payloads=relationship_bundle.commitments,
            relationship_issue_payloads=relationship_bundle.open_issues,
            material_sources=(),
            activity_summary_bytes=activity,
            target_activity=target_activity,
            capability_state_payloads=capabilities,
            scene_bytes=scene_bytes,
            evidence=evidence_source,
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
        snapshot: ContextEpisodeSnapshot,
    ) -> None:
        tx = unit_of_work.transaction
        context_items: tuple[dict[str, object], ...] = tuple(
            {
                "context_item_id": str(uuid7()),
                "ordinal": item.ordinal,
                "section": item.candidate.section.value,
                "item_kind": item.candidate.item_kind,
                "source_kind": item.candidate.source.kind,
                "source_ref": (
                    str(item.candidate.source.reference)
                    if item.candidate.source.reference is not None
                    else None
                ),
                "source_version": item.candidate.source.version,
                "trust_class": item.candidate.trust_class.value,
                "privacy_scope": "private",
                "disposition": item.disposition.value,
                "reason_code": item.reason_code,
                "content_bytes": item.content_bytes,
            }
            for item in result.items
        )
        included = {
            item.candidate.source.reference
            for item in result.items
            if item.disposition.value == "included"
        }
        await self._opportunity_transitions.freeze_signals(
            tx,
            opportunity_id=snapshot.opportunity_id,
            signals=tuple(
                signal
                for signal in snapshot.consideration_signals
                if signal.object_ref in included
            ),
            frozen_at=snapshot.observed_at,
        )
        episode = await self._episodes.mark_context_prepared(
            tx,
            episode_id=episode_id,
            manifest_artifact_id=manifest_artifact.artifact_id.value,
            compiled_artifact_id=compiled_artifact.artifact_id.value,
            compiled_digest=compiled_artifact.content_digest,
            context_items=context_items,
        )
        from datetime import UTC

        now = Instant(datetime.now(UTC))
        await unit_of_work.work.enqueue(
            WorkDraft(
                WorkId(uuid7()),
                _MODEL_WORK_KIND,
                WorkOwner("cognitive_episode", episode_id),
                IdempotencyKey(f"model:{episode_id}"),
                compiled_artifact.content_digest,
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
            unit_of_work.transaction,
            opportunity_id=episode.opportunity_id,
            failure_code=code,
        ):
            raise ContextViolation("CTX-OPPORTUNITY-STATE")
        await unit_of_work.work.fail(lease, error_code=code)

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
    "PostgreSQLContextRepository",
)
