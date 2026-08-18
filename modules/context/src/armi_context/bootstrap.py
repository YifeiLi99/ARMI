"""Composition-only construction of the active Context implementations."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from armi_activity.api import ActivityReadPort
from armi_artifact_store import ContentAddressedArtifactStore
from armi_attention.api import (
    OpportunityCognitionSelectionPort,
    OpportunityContextReadPort,
)
from armi_capability.api import CapabilityReadPort
from armi_codex.api import CodexTaskSourceReadPort
from armi_data_rights.api import DataRightsParticipant
from armi_effect.api import EffectOperationReadPort
from armi_evidence.api import EvidenceReadPort
from armi_expression.api import ExpressionIntentReadPort
from armi_interaction.api import InteractionContextReadPort
from armi_kernel.application import DurableWorkPort
from armi_material.api import MaterialCandidateContextPort, MaterialProjectionPort
from armi_memory.api import (
    MemoryCandidateContextPort,
    MemoryProjectionPort,
    MemoryReadPort,
)
from armi_mood.api import MoodReadPort
from armi_prompt.api import PromptReadPort
from armi_relationship.api import RelationshipReadPort
from armi_runtime_foundation import (
    EmptyRecoveryParticipant,
    PostgreSQLRuntimeUnitOfWorkFactory,
    RecoveryParticipant,
)
from armi_sleep.api import SleepReadPort
from armi_subject_state.api import SubjectStateReadPort

from ._application import ContextPipeline
from ._candidate_read import PostgreSQLContextCandidateRead
from ._data_rights import PostgreSQLContextDataRightsParticipant
from ._embedding_application import ContextEmbeddingPipeline
from ._embedding_postgresql import (
    PostgreSQLContextProjectionInvalidation,
    inspect_embedding_storage,
)
from .api import (
    ContextArtifactCatalogPort,
    ContextCognitionReadPort,
    ContextEmbeddingRuntimePort,
    ContextEpisodePort,
    ContextProjectionInvalidationPort,
    ContextRuntimePort,
    ContextRuntimeSubjectPort,
    ContextSelectionPort,
    ContextWakeupPort,
    EmbeddingPort,
)

Diagnostic = Callable[[str], None]


def bootstrap_context(
    *,
    factory: PostgreSQLRuntimeUnitOfWorkFactory,
    storage: ContentAddressedArtifactStore,
    catalog: ContextArtifactCatalogPort,
    work: DurableWorkPort,
    activity_read: ActivityReadPort,
    capability_read: CapabilityReadPort,
    memory_read: MemoryReadPort,
    memory_projection: MemoryProjectionPort,
    mood_read: MoodReadPort,
    prompt_read: PromptReadPort,
    material_projection: MaterialProjectionPort,
    relationship_read: RelationshipReadPort,
    sleep_read: SleepReadPort,
    subject_state_read: SubjectStateReadPort,
    selection: ContextSelectionPort,
    episodes: ContextEpisodePort,
    runtime_subjects: ContextRuntimeSubjectPort,
    opportunity_context: OpportunityContextReadPort,
    opportunity_transitions: OpportunityCognitionSelectionPort,
    evidence_read: EvidenceReadPort,
    interaction_context: InteractionContextReadPort,
    expression_read: ExpressionIntentReadPort,
    effect_read: EffectOperationReadPort,
    codex_read: CodexTaskSourceReadPort,
    web_search_active: bool = False,
    wakeups: ContextWakeupPort | None = None,
    diagnostic: Diagnostic | None = None,
    embedding: EmbeddingPort | None = None,
) -> ContextRuntimePort:
    return ContextPipeline(
        factory=factory,
        storage=storage,
        catalog=catalog,
        work=work,
        activity_read=activity_read,
        capability_read=capability_read,
        memory_read=memory_read,
        memory_projection=memory_projection,
        mood_read=mood_read,
        prompt_read=prompt_read,
        material_projection=material_projection,
        relationship_read=relationship_read,
        sleep_read=sleep_read,
        subject_state_read=subject_state_read,
        selection=selection,
        episodes=episodes,
        runtime_subjects=runtime_subjects,
        opportunity_context=opportunity_context,
        opportunity_transitions=opportunity_transitions,
        evidence_read=evidence_read,
        interaction_context=interaction_context,
        expression_read=expression_read,
        effect_read=effect_read,
        codex_read=codex_read,
        web_search_active=web_search_active,
        wakeups=wakeups,
        diagnostic=diagnostic,
        embedding=embedding,
    )


def bootstrap_context_embedding(
    *,
    factory: PostgreSQLRuntimeUnitOfWorkFactory,
    storage: ContentAddressedArtifactStore,
    adapter: EmbeddingPort,
    work: DurableWorkPort,
    memories: MemoryProjectionPort,
    materials: MaterialProjectionPort,
) -> ContextEmbeddingRuntimePort:
    return ContextEmbeddingPipeline(
        factory=factory,
        storage=storage,
        adapter=adapter,
        work=work,
        memories=memories,
        materials=materials,
    )


def inspect_context_embedding_storage(conninfo: str) -> dict[str, object]:
    return inspect_embedding_storage(conninfo)


def bootstrap_context_projection_invalidation() -> ContextProjectionInvalidationPort:
    return PostgreSQLContextProjectionInvalidation()


def bootstrap_context_data_rights() -> DataRightsParticipant:
    return PostgreSQLContextDataRightsParticipant()


def bootstrap_context_recovery() -> RecoveryParticipant:
    return EmptyRecoveryParticipant("context")


@dataclass(frozen=True, slots=True)
class ContextCandidateReadPorts:
    material: MaterialCandidateContextPort
    memory: MemoryCandidateContextPort
    cognition: ContextCognitionReadPort


def bootstrap_context_candidate_read() -> ContextCandidateReadPorts:
    owner = PostgreSQLContextCandidateRead()
    return ContextCandidateReadPorts(owner, owner, owner)


__all__ = (
    "ContextCandidateReadPorts",
    "bootstrap_context",
    "bootstrap_context_candidate_read",
    "bootstrap_context_data_rights",
    "bootstrap_context_embedding",
    "bootstrap_context_projection_invalidation",
    "bootstrap_context_recovery",
    "inspect_context_embedding_storage",
)
