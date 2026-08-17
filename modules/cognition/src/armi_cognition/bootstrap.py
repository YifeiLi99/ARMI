"""Composition-only assembly for the active cognition implementation."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from armi_activity.api import ActivityCognitionPort, ActivityReadPort
from armi_artifact_store import ContentAddressedArtifactStore
from armi_attention.api import (
    OpportunityCognitionSelectionPort,
    OpportunityContextReadPort,
)
from armi_codex.api import CodexTaskSourceReadPort
from armi_context.api import ContextCognitionReadPort
from armi_data_rights.api import DataRightsParticipant
from armi_evidence.api import EvidenceReadPort
from armi_experience.api import ExperienceReadPort
from armi_interaction.api import InteractionCognitionReadPort
from armi_kernel.application import DurableWorkPort
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
from ._candidate_application import CandidateValidationPipeline
from ._change_set_codec import parse_subject_change_set
from ._context_postgresql import PostgreSQLCognitionContextLifecycle
from ._data_rights import PostgreSQLCognitionDataRightsParticipant
from ._exact_life_query import PostgreSQLCognitionExactLifeQuery
from ._model_application import ModelPipeline
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
    parse_candidate as parse_model_candidate,
)
from ._recovery import CognitionRecoveryParticipant
from ._subject_commit import PostgreSQLCognitionSubjectCommit
from ._validator import CandidateValidationContext, DeterministicCandidateValidator
from .api import (
    CandidateValidator,
    CognitionAdminPort,
    CognitionArtifactCatalogPort,
    CognitionContextLifecyclePort,
    CognitionExactLifeQueryPort,
    CognitionModelAdapterFactory,
    CognitionOperationReadPort,
    CognitionOwnerPort,
    CognitionRuntimeStatePort,
    CognitionSubjectCommitPort,
    CognitionWakeupPort,
    CognitionWorkerPort,
    SubjectChangeSet,
    SubjectChangeSetCodec,
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


class _BoundSubjectChangeSetCodec:
    __slots__ = (
        "_activity",
        "_material",
        "_memory",
        "_mood",
        "_prompt",
        "_relationship",
        "_sleep",
        "_subject_state",
    )

    def __init__(
        self,
        *,
        activity: ActivityCognitionPort,
        material: MaterialCognitionPort,
        memory: MemoryCognitionPort,
        mood: MoodCognitionPort,
        prompt: PromptCognitionPort,
        relationship: RelationshipCognitionPort,
        sleep: SleepCognitionPort,
        subject_state: SubjectStateCognitionPort,
    ) -> None:
        self._activity = activity
        self._material = material
        self._memory = memory
        self._mood = mood
        self._prompt = prompt
        self._relationship = relationship
        self._sleep = sleep
        self._subject_state = subject_state

    def decode(self, value: bytes) -> SubjectChangeSet:
        return parse_subject_change_set(
            value,
            self._relationship,
            self._memory,
            self._sleep,
            self._activity,
            self._material,
            self._subject_state,
            self._mood,
            self._prompt,
        )


def bootstrap_cognition_change_set_codec(
    *,
    activity: ActivityCognitionPort,
    material: MaterialCognitionPort,
    memory: MemoryCognitionPort,
    mood: MoodCognitionPort,
    prompt: PromptCognitionPort,
    relationship: RelationshipCognitionPort,
    sleep: SleepCognitionPort,
    subject_state: SubjectStateCognitionPort,
) -> SubjectChangeSetCodec:
    return _BoundSubjectChangeSetCodec(
        activity=activity,
        material=material,
        memory=memory,
        mood=mood,
        prompt=prompt,
        relationship=relationship,
        sleep=sleep,
        subject_state=subject_state,
    )


def bootstrap_cognition_model(
    *,
    factory: PostgreSQLRuntimeUnitOfWorkFactory,
    storage: ContentAddressedArtifactStore,
    catalog: CognitionArtifactCatalogPort,
    context: ContextCognitionReadPort,
    opportunities: OpportunityCognitionSelectionPort,
    work: DurableWorkPort,
    adapter_factory: CognitionModelAdapterFactory,
    binding_path: Path,
    web_search_active: bool = False,
    wakeups: CognitionWakeupPort | None = None,
    diagnostic: Callable[[str], None] | None = None,
) -> CognitionWorkerPort:
    return ModelPipeline(
        factory=factory,
        storage=storage,
        catalog=catalog,
        context=context,
        opportunities=opportunities,
        work=work,
        adapter_factory=adapter_factory,
        binding_path=binding_path,
        web_search_active=web_search_active,
        wakeups=wakeups,
        diagnostic=diagnostic,
    )


def bootstrap_cognition_candidate(
    *,
    factory: PostgreSQLRuntimeUnitOfWorkFactory,
    storage: ContentAddressedArtifactStore,
    catalog: CognitionArtifactCatalogPort,
    work: DurableWorkPort,
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
    subject_state_read: SubjectStateReadPort,
    web_search_active: bool = False,
    wakeups: CognitionWakeupPort | None = None,
    diagnostic: Callable[[str], None] | None = None,
) -> CognitionWorkerPort:
    return CandidateValidationPipeline(
        factory=factory,
        storage=storage,
        catalog=catalog,
        work=work,
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
        subject_state_read=subject_state_read,
        web_search_active=web_search_active,
        wakeups=wakeups,
        diagnostic=diagnostic,
    )


def bootstrap_cognition_data_rights() -> DataRightsParticipant:
    return PostgreSQLCognitionDataRightsParticipant()


def bootstrap_cognition_recovery() -> RecoveryParticipant:
    return CognitionRecoveryParticipant()


__all__ = (
    "bootstrap_cognition_admin",
    "bootstrap_cognition_candidate",
    "bootstrap_cognition_change_set_codec",
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
    "parse_model_candidate",
)
