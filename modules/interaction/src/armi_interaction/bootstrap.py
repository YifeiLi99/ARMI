"""Interaction module composition entry point."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from uuid import UUID

from armi_artifact_store.content_store import ContentAddressedArtifactStore
from armi_evidence.api import EvidenceReadPort, EvidenceWritePort
from armi_kernel.application import CreatorProjectionNotifier
from armi_opportunity.api import OpportunityAdmissionPort
from armi_runtime_foundation import PostgreSQLRuntimeUnitOfWorkFactory
from armi_subject_state.api import SubjectStateReadPort

from ._creator import EvidenceAcceptanceTransaction
from ._creator_postgresql import CreatorInputRepository
from ._external import ExternalMessageInputService
from ._external_postgresql import ExternalMessageInputRepository
from ._other_human import OtherHumanInputService
from ._other_human_postgresql import OtherHumanInputRepository
from ._perception_postgresql import PostgreSQLInteractionPerception
from ._scenes import CreatorSceneService
from ._scenes_postgresql import CreatorSceneRepository
from ._timeline_postgresql import PostgreSQLSceneTimelineQuery
from .api import (
    CreatorInputTransactionPort,
    CreatorInteractionPort,
    CreatorOperationQueryPort,
    CreatorScenePort,
    ExternalMessageInputPort,
    InteractionArtifactCatalogPort,
    InteractionDataRightsGate,
    InteractionPerceptionPort,
    InteractionWakeupPort,
    OtherHumanInputPort,
    SceneTimelineCodexTaskProjectionPort,
    SceneTimelineQueryPort,
)


@dataclass(frozen=True, slots=True)
class InteractionModule:
    creator_input: CreatorInteractionPort
    creator_operations: CreatorOperationQueryPort
    creator_transaction: CreatorInputTransactionPort
    creator_scenes: CreatorScenePort
    scene_timeline: SceneTimelineQueryPort
    other_human_input: OtherHumanInputPort
    external_message_input: ExternalMessageInputPort
    perception: InteractionPerceptionPort
    _timeline: PostgreSQLSceneTimelineQuery

    async def open(self) -> None:
        await self._timeline.open()

    async def close(self) -> None:
        await self._timeline.close()


def bootstrap_interaction(
    unit_of_work_factory: PostgreSQLRuntimeUnitOfWorkFactory,
    *,
    environment_id: UUID,
    creator_party_id: UUID,
    cursor_key: bytes,
    storage: ContentAddressedArtifactStore,
    codex_task_projection: SceneTimelineCodexTaskProjectionPort,
    catalog: InteractionArtifactCatalogPort,
    data_rights: InteractionDataRightsGate,
    subject_state: SubjectStateReadPort,
    evidence: EvidenceWritePort,
    evidence_read: EvidenceReadPort,
    opportunity: OpportunityAdmissionPort,
    notifier: CreatorProjectionNotifier | None,
    wakeups: InteractionWakeupPort | None = None,
    diagnostic: Callable[[str], None] | None = None,
    fault_injector: Callable[[str], None] | None = None,
) -> InteractionModule:
    creator_repository = CreatorInputRepository(evidence, opportunity)
    other_repository = OtherHumanInputRepository(evidence, opportunity)
    creator_input = EvidenceAcceptanceTransaction(
        creator_party_id=creator_party_id,
        storage=storage,
        catalog=catalog,
        repository=creator_repository,
        unit_of_work_factory=unit_of_work_factory,
        data_rights=data_rights,
        notifier=notifier,
        subject_state=subject_state,
        wakeups=wakeups,
        diagnostic=diagnostic,
        fault_injector=fault_injector,
    )
    creator_scenes = CreatorSceneService(
        creator_party_id=creator_party_id,
        factory=unit_of_work_factory,
        repository=CreatorSceneRepository(),
    )
    other_human = OtherHumanInputService(
        storage=storage,
        catalog=catalog,
        repository=other_repository,
        unit_of_work_factory=unit_of_work_factory,
        data_rights=data_rights,
        wakeups=wakeups,
        notifier=notifier,
    )
    external = ExternalMessageInputService(
        storage=storage,
        catalog=catalog,
        messages=ExternalMessageInputRepository(evidence_read, opportunity),
        creator_inputs=creator_repository,
        other_inputs=other_repository,
        unit_of_work_factory=unit_of_work_factory,
        data_rights=data_rights,
        wakeups=wakeups,
        notifier=notifier,
    )
    timeline = PostgreSQLSceneTimelineQuery(
        unit_of_work_factory,
        environment_id=environment_id,
        creator_party_id=creator_party_id,
        cursor_key=cursor_key,
        storage=storage,
        codex_tasks=codex_task_projection,
    )
    return InteractionModule(
        creator_input=creator_input,
        creator_operations=creator_input,
        creator_transaction=creator_repository,
        creator_scenes=creator_scenes,
        scene_timeline=timeline,
        other_human_input=other_human,
        external_message_input=external,
        perception=PostgreSQLInteractionPerception(),
        _timeline=timeline,
    )


__all__ = ("InteractionModule", "bootstrap_interaction")
