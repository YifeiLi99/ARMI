"""Interaction module composition entry point."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from uuid import UUID

from armi_artifact_store.content_store import ContentAddressedArtifactStore
from armi_kernel.application import CreatorProjectionNotifier
from armi_runtime_foundation import PostgreSQLRuntimeUnitOfWorkFactory
from armi_subject_state.api import SubjectStateReadPort

from ._creator import EvidenceAcceptanceTransaction
from ._creator_postgresql import CreatorInputRepository
from ._external import ExternalMessageInputService
from ._external_postgresql import ExternalMessageInputRepository
from ._other_human import OtherHumanInputService
from ._other_human_postgresql import OtherHumanInputRepository
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
    InteractionWakeupPort,
    OtherHumanInputPort,
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
    _factory: PostgreSQLRuntimeUnitOfWorkFactory
    _timeline: PostgreSQLSceneTimelineQuery

    async def open(self) -> None:
        await self._factory.open()
        try:
            await self._timeline.open()
        except Exception:
            await self._factory.close()
            raise

    async def close(self) -> None:
        await self._timeline.close()
        await self._factory.close()


def bootstrap_interaction(
    conninfo: str,
    *,
    expected_role: str,
    environment_id: UUID,
    creator_party_id: UUID,
    cursor_key: bytes,
    pool_timeout_seconds: int,
    unit_of_work_factory: PostgreSQLRuntimeUnitOfWorkFactory,
    storage: ContentAddressedArtifactStore,
    catalog: InteractionArtifactCatalogPort,
    data_rights: InteractionDataRightsGate,
    subject_state: SubjectStateReadPort,
    notifier: CreatorProjectionNotifier | None,
    wakeups: InteractionWakeupPort | None = None,
    diagnostic: Callable[[str], None] | None = None,
    fault_injector: Callable[[str], None] | None = None,
) -> InteractionModule:
    creator_repository = CreatorInputRepository()
    other_repository = OtherHumanInputRepository()
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
        messages=ExternalMessageInputRepository(),
        creator_inputs=creator_repository,
        other_inputs=other_repository,
        unit_of_work_factory=unit_of_work_factory,
        data_rights=data_rights,
        wakeups=wakeups,
        notifier=notifier,
    )
    timeline = PostgreSQLSceneTimelineQuery(
        conninfo,
        environment_id=environment_id,
        expected_role=expected_role,
        creator_party_id=creator_party_id,
        cursor_key=cursor_key,
        storage=storage,
        pool_timeout_seconds=pool_timeout_seconds,
    )
    return InteractionModule(
        creator_input=creator_input,
        creator_operations=creator_input,
        creator_transaction=creator_repository,
        creator_scenes=creator_scenes,
        scene_timeline=timeline,
        other_human_input=other_human,
        external_message_input=external,
        _factory=unit_of_work_factory,
        _timeline=timeline,
    )


__all__ = ("InteractionModule", "bootstrap_interaction")
