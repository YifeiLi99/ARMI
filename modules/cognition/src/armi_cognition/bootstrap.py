"""Composition-only assembly for the active cognition implementation."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from armi_activity.api import ActivityCognitionPort, ActivityReadPort
from armi_artifact_store import ContentAddressedArtifactStore
from armi_kernel.application import DurableWorkPort
from armi_material.api import MaterialCognitionPort, MaterialReadPort
from armi_memory.api import MemoryCognitionPort, MemoryReadPort
from armi_mood.api import MoodCognitionPort, MoodReadPort
from armi_prompt.api import PromptCognitionPort, PromptReadPort
from armi_relationship.api import RelationshipCognitionPort, RelationshipReadPort
from armi_runtime_foundation import PostgreSQLRuntimeUnitOfWorkFactory
from armi_sleep.api import SleepCognitionPort, SleepReadPort
from armi_subject_state.api import SubjectStateCognitionPort, SubjectStateReadPort

from ._candidate_application import CandidateValidationPipeline
from ._model_application import ModelPipeline
from .api import (
    CognitionArtifactCatalogPort,
    CognitionModelAdapterFactory,
    CognitionWakeupPort,
    CognitionWorkerPort,
)


def bootstrap_cognition_model(
    *,
    factory: PostgreSQLRuntimeUnitOfWorkFactory,
    storage: ContentAddressedArtifactStore,
    catalog: CognitionArtifactCatalogPort,
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


__all__ = ("bootstrap_cognition_candidate", "bootstrap_cognition_model")
