"""Composition-only assembly for the active cognition implementation."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from pathlib import Path
from uuid import UUID

from armi_activity.api import ActivityCognitionPort, ActivityReadPort
from armi_artifact_store import ContentAddressedArtifactStore
from armi_attention.api import (
    OpportunityCognitionPort,
    OpportunityCognitionSelectionPort,
    OpportunityContextReadPort,
)
from armi_codex.api import CodexTaskSourceReadPort
from armi_context.api import ContextCognitionReadPort
from armi_data_rights.api import DataRightsParticipant
from armi_evidence.api import EvidenceReadPort
from armi_experience.api import ExperienceReadPort
from armi_interaction.api import InteractionCognitionReadPort
from armi_kernel.application import DurableWorkPort, ExecutionCustodyPort, PriceCatalog
from armi_material.api import (
    MaterialCandidateContextPort,
    MaterialCognitionPort,
    MaterialReadPort,
)
from armi_memory.api import (
    MemoryCandidateContextPort,
    MemoryCognitionPort,
    MemoryReadPort,
)
from armi_mind.api import MindCognitionPort, MindReadPort
from armi_mood.api import MoodCognitionPort, MoodReadPort
from armi_prompt.api import PromptCognitionPort, PromptReadPort
from armi_relationship.api import RelationshipCognitionPort, RelationshipReadPort
from armi_runtime_foundation import (
    PostgreSQLRuntimeUnitOfWorkFactory,
    RecoveryParticipant,
)
from armi_sleep.api import SleepCognitionPort, SleepReadPort
from armi_subject_state.api import SubjectStateCognitionPort, SubjectStateReadPort

from ._admin import PostgreSQLCognitionAdmin
from ._autonomous_activity_contract import autonomous_schema_for_context
from ._candidate_application import CandidateValidationService, model_response_candidate
from ._context_postgresql import PostgreSQLCognitionContextLifecycle
from ._context_schema import bind_context_schema
from ._data_rights import PostgreSQLCognitionDataRightsParticipant
from ._exact_life_query import PostgreSQLCognitionExactLifeQuery
from ._model_application import ModelPipeline
from ._model_contract import (
    AUTONOMOUS_ACTIVITY_INSTRUCTIONS,
    GENERIC_COGNITION_INSTRUCTIONS,
    load_purpose_binding,
)
from ._model_contract import (
    build_request_bytes as build_model_request_bytes,
)
from ._model_contract import (
    candidate_schema as build_candidate_schema,
)
from ._model_contract import (
    checked_model_request as check_model_request,
)
from ._model_contract import (
    load_active_binding as load_active_model_binding,
)
from ._model_contract import (
    load_voice_binding as load_voice_model_binding,
)
from ._model_contract import (
    parse_candidate as parse_model_candidate,
)
from ._owners import CandidateOwner
from ._recovery import CognitionRecoveryParticipant
from ._subject_commit import PostgreSQLCognitionSubjectCommit
from ._validator import CandidateValidationContext, DeterministicCandidateValidator
from .api import (
    CandidateValidationDiagnostic,
    CandidateValidator,
    CognitionAdminPort,
    CognitionArtifactCatalogPort,
    CognitionContextLifecyclePort,
    CognitionExactLifeQueryPort,
    CognitionFinalizationPort,
    CognitionModelAdapterFactory,
    CognitionOperationReadPort,
    CognitionOwnerPort,
    CognitionRuntimeStatePort,
    CognitionSubjectCommitPort,
    CognitionSubmissionPort,
    CognitionWakeupPort,
    CognitionWorkerPort,
)


def bootstrap_cognition_validator(
    context: CandidateValidationContext,
    *,
    activity: ActivityCognitionPort,
    material: MaterialCognitionPort,
    memory: MemoryCognitionPort,
    mood: MoodCognitionPort,
    prompt: PromptCognitionPort,
    relationship: RelationshipCognitionPort,
    sleep: SleepCognitionPort,
    subject_state: SubjectStateCognitionPort,
    mind: MindCognitionPort,
) -> CandidateValidator:
    return DeterministicCandidateValidator(
        context,
        activity_cognition=activity,
        material_cognition=material,
        memory_cognition=memory,
        mood_cognition=mood,
        prompt_cognition=prompt,
        relationship_cognition=relationship,
        sleep_cognition=sleep,
        subject_state_cognition=subject_state,
        mind_cognition=mind,
    )


compose_candidate_validation_context = CandidateValidationContext
compose_deterministic_candidate_validator = DeterministicCandidateValidator


def bootstrap_cognition_admin() -> CognitionAdminPort:
    return PostgreSQLCognitionAdmin()


def bootstrap_cognition_exact_life_query() -> CognitionExactLifeQueryPort:
    return PostgreSQLCognitionExactLifeQuery()


def bootstrap_cognition_subject_commit() -> CognitionSubjectCommitPort:
    return PostgreSQLCognitionSubjectCommit()


def bootstrap_cognition_owner() -> CognitionOwnerPort:
    return PostgreSQLCognitionSubjectCommit()


def bootstrap_cognition_context(
    *, experiences: ExperienceReadPort
) -> CognitionContextLifecyclePort:
    return PostgreSQLCognitionContextLifecycle(experiences)


def bootstrap_cognition_operation() -> CognitionOperationReadPort:
    return PostgreSQLCognitionSubjectCommit()


def bootstrap_cognition_model(
    *,
    factory: PostgreSQLRuntimeUnitOfWorkFactory,
    storage: ContentAddressedArtifactStore,
    catalog: CognitionArtifactCatalogPort,
    context: ContextCognitionReadPort,
    opportunities: OpportunityCognitionSelectionPort,
    work: DurableWorkPort,
    custody: ExecutionCustodyPort,
    finalization: CognitionFinalizationPort,
    adapter_factory: CognitionModelAdapterFactory,
    binding_path: Path,
    prices: PriceCatalog,
    wakeups: CognitionWakeupPort | None = None,
    diagnostic: Callable[[str], None] | None = None,
    failure_notification: Callable[[UUID, str], Awaitable[None]] | None = None,
) -> CognitionWorkerPort:
    return ModelPipeline(
        factory=factory,
        storage=storage,
        catalog=catalog,
        context=context,
        opportunities=opportunities,
        work=work,
        custody=custody,
        finalization=finalization,
        adapter_factory=adapter_factory,
        failure_notification=failure_notification,
        binding_path=binding_path,
        prices=prices,
        wakeups=wakeups,
        diagnostic=diagnostic,
    )


def bootstrap_cognition_candidate(
    *,
    factory: PostgreSQLRuntimeUnitOfWorkFactory,
    storage: ContentAddressedArtifactStore,
    catalog: CognitionArtifactCatalogPort,
    submission: CognitionSubmissionPort,
    activity_cognition: ActivityCognitionPort,
    activity_read: ActivityReadPort,
    material_context: MaterialCandidateContextPort,
    memory_context: MemoryCandidateContextPort,
    context: ContextCognitionReadPort,
    runtime_state: CognitionRuntimeStatePort,
    interaction: InteractionCognitionReadPort,
    opportunity_context: OpportunityContextReadPort,
    opportunity_transitions: OpportunityCognitionSelectionPort,
    evidence: EvidenceReadPort,
    codex: CodexTaskSourceReadPort,
    codex_available: Callable[[], bool],
    memory_cognition: MemoryCognitionPort,
    memory_read: MemoryReadPort,
    mood_cognition: MoodCognitionPort,
    mood_read: MoodReadPort,
    prompt_cognition: PromptCognitionPort,
    prompt_read: PromptReadPort,
    material_cognition: MaterialCognitionPort,
    material_read: MaterialReadPort,
    relationship_cognition: RelationshipCognitionPort,
    relationship_read: RelationshipReadPort,
    sleep_cognition: SleepCognitionPort,
    sleep_read: SleepReadPort,
    subject_state_cognition: SubjectStateCognitionPort,
    mind_cognition: MindCognitionPort,
    subject_state_read: SubjectStateReadPort,
    mind_read: MindReadPort,
    visual_sources_active: frozenset[str] = frozenset(),
    diagnostic: Callable[[str], None] | None = None,
    validation_diagnostic: Callable[[CandidateValidationDiagnostic], None]
    | None = None,
    failure_notification: Callable[[UUID, str], Awaitable[None]] | None = None,
) -> CognitionFinalizationPort:
    return CandidateValidationService(
        failure_notification=failure_notification,
        factory=factory,
        storage=storage,
        catalog=catalog,
        submission=submission,
        activity_cognition=activity_cognition,
        activity_read=activity_read,
        material_context=material_context,
        memory_context=memory_context,
        context=context,
        runtime_state=runtime_state,
        interaction=interaction,
        opportunity_context=opportunity_context,
        opportunity_transitions=opportunity_transitions,
        evidence=evidence,
        codex=codex,
        codex_available=codex_available,
        memory_cognition=memory_cognition,
        memory_read=memory_read,
        mood_cognition=mood_cognition,
        mood_read=mood_read,
        prompt_cognition=prompt_cognition,
        prompt_read=prompt_read,
        material_cognition=material_cognition,
        material_read=material_read,
        relationship_cognition=relationship_cognition,
        relationship_read=relationship_read,
        sleep_cognition=sleep_cognition,
        sleep_read=sleep_read,
        subject_state_cognition=subject_state_cognition,
        mind_cognition=mind_cognition,
        subject_state_read=subject_state_read,
        mind_read=mind_read,
        visual_sources_active=visual_sources_active,
        diagnostic=diagnostic,
        validation_diagnostic=validation_diagnostic,
    )


def bootstrap_cognition_data_rights() -> DataRightsParticipant:
    return PostgreSQLCognitionDataRightsParticipant()


def bootstrap_cognition_recovery(
    opportunity: OpportunityCognitionPort,
) -> RecoveryParticipant:
    return CognitionRecoveryParticipant(opportunity)


__all__ = (
    "AUTONOMOUS_ACTIVITY_INSTRUCTIONS",
    "GENERIC_COGNITION_INSTRUCTIONS",
    "CandidateOwner",
    "autonomous_schema_for_context",
    "bind_context_schema",
    "bootstrap_cognition_admin",
    "bootstrap_cognition_candidate",
    "bootstrap_cognition_context",
    "bootstrap_cognition_data_rights",
    "bootstrap_cognition_exact_life_query",
    "bootstrap_cognition_model",
    "bootstrap_cognition_operation",
    "bootstrap_cognition_owner",
    "bootstrap_cognition_recovery",
    "bootstrap_cognition_subject_commit",
    "bootstrap_cognition_validator",
    "build_candidate_schema",
    "build_model_request_bytes",
    "check_model_request",
    "compose_candidate_validation_context",
    "compose_deterministic_candidate_validator",
    "load_active_model_binding",
    "load_purpose_binding",
    "load_voice_model_binding",
    "model_response_candidate",
    "parse_model_candidate",
)
