"""Composition-only construction of the active Context implementations."""

from __future__ import annotations

from collections.abc import Callable

from armi_activity.api import ActivityReadPort
from armi_artifact_store import ContentAddressedArtifactStore
from armi_kernel.application import DurableWorkPort
from armi_material.api import MaterialProjectionPort
from armi_memory.api import MemoryProjectionPort, MemoryReadPort
from armi_mood.api import MoodReadPort
from armi_prompt.api import PromptReadPort
from armi_relationship.api import RelationshipReadPort
from armi_runtime_foundation import PostgreSQLRuntimeUnitOfWorkFactory
from armi_sleep.api import SleepReadPort
from armi_subject_state.api import SubjectStateReadPort

from ._application import ContextPipeline
from ._embedding_application import ContextEmbeddingPipeline
from .api import (
    ContextArtifactCatalogPort,
    ContextEmbeddingRuntimePort,
    ContextRuntimePort,
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
    memory_read: MemoryReadPort,
    memory_projection: MemoryProjectionPort,
    mood_read: MoodReadPort,
    prompt_read: PromptReadPort,
    material_projection: MaterialProjectionPort,
    relationship_read: RelationshipReadPort,
    sleep_read: SleepReadPort,
    subject_state_read: SubjectStateReadPort,
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
        memory_read=memory_read,
        memory_projection=memory_projection,
        mood_read=mood_read,
        prompt_read=prompt_read,
        material_projection=material_projection,
        relationship_read=relationship_read,
        sleep_read=sleep_read,
        subject_state_read=subject_state_read,
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


__all__ = ("bootstrap_context", "bootstrap_context_embedding")
