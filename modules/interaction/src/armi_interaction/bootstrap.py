"""Interaction module composition entry point."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from uuid import UUID

from armi_artifact_store.content_store import ContentAddressedArtifactStore
from armi_attention.api import OpportunityAdmissionPort
from armi_data_rights.api import DataRightsParticipant, DataRightsVisibilityPort
from armi_evidence.api import EvidenceReadPort, EvidenceWritePort
from armi_kernel.application import CreatorProjectionNotifier
from armi_runtime_foundation import (
    PostgreSQLRuntimeUnitOfWorkFactory,
    RecoveryParticipant,
)
from armi_subject_state.api import SubjectStateReadPort

from ._action_postgresql import PostgreSQLInteractionActionOwner
from ._admin import PostgreSQLInteractionAdmin
from ._birth_postgresql import PostgreSQLInteractionBirth
from ._context_postgresql import PostgreSQLInteractionContextRead
from ._creator import EvidenceAcceptanceTransaction
from ._creator_postgresql import CreatorInputRepository
from ._data_rights import PostgreSQLInteractionDataRightsParticipant
from ._external import ExternalMessageInputService
from ._external_postgresql import ExternalMessageInputRepository
from ._identity_postgresql import PostgreSQLInteractionIdentity
from ._other_human import OtherHumanInputService
from ._other_human_postgresql import OtherHumanInputRepository
from ._perception_postgresql import PostgreSQLInteractionPerception
from ._recovery import InteractionRecoveryParticipant
from ._scenes import CreatorSceneService
from ._scenes_postgresql import CreatorSceneRepository
from ._subject_commit import PostgreSQLInteractionSubjectCommit
from ._timeline_postgresql import PostgreSQLSceneTimelineQuery
from .api import (
    CreatorInputTransactionPort,
    CreatorInteractionPort,
    CreatorScenePort,
    ExternalMessageInputPort,
    InteractionAdminPort,
    InteractionArtifactCatalogPort,
    InteractionBirthPort,
    InteractionCognitionReadPort,
    InteractionContextReadPort,
    InteractionCreatorTimelineProjectionPort,
    InteractionDataRightsGate,
    InteractionEffectDeliveryPort,
    InteractionEffectRoutePort,
    InteractionIdentityPort,
    InteractionOtherHumanReadPort,
    InteractionPerceptionPort,
    InteractionSceneTransitionPort,
    InteractionSubjectCommitPort,
    InteractionWakeupPort,
    OtherHumanInputPort,
    SceneTimelineCodexTaskProjectionPort,
    SceneTimelineQueryPort,
)


def bootstrap_interaction_admin() -> InteractionAdminPort:
    return PostgreSQLInteractionAdmin()


def bootstrap_interaction_identity() -> InteractionIdentityPort:
    return PostgreSQLInteractionIdentity()


def bootstrap_interaction_birth() -> InteractionBirthPort:
    return PostgreSQLInteractionBirth()


def bootstrap_interaction_subject_commit() -> InteractionSubjectCommitPort:
    return PostgreSQLInteractionSubjectCommit()


@dataclass(frozen=True, slots=True)
class InteractionCognitionPorts:
    context: InteractionContextReadPort
    cognition: InteractionCognitionReadPort


def bootstrap_interaction_cognition() -> InteractionCognitionPorts:
    owner = PostgreSQLInteractionContextRead()
    return InteractionCognitionPorts(owner, owner)


@dataclass(frozen=True, slots=True)
class InteractionModule:
    creator_input: CreatorInteractionPort
    creator_transaction: CreatorInputTransactionPort
    creator_scenes: CreatorScenePort
    scene_timeline: SceneTimelineQueryPort
    other_human_input: OtherHumanInputPort
    external_message_input: ExternalMessageInputPort
    perception: InteractionPerceptionPort
    effect_delivery: InteractionEffectDeliveryPort
    effect_routes: InteractionEffectRoutePort
    scene_transitions: InteractionSceneTransitionPort
    identity: InteractionIdentityPort
    other_human_read: InteractionOtherHumanReadPort
    context_read: InteractionContextReadPort
    cognition_read: InteractionCognitionReadPort
    subject_commit: InteractionSubjectCommitPort
    _timeline: PostgreSQLSceneTimelineQuery

    async def open(self) -> None:
        await self._timeline.open()

    async def close(self) -> None:
        await self._timeline.close()


@dataclass(frozen=True, slots=True)
class InteractionActionPorts:
    routes: InteractionEffectRoutePort
    scenes: InteractionSceneTransitionPort


def bootstrap_interaction_action_ports() -> InteractionActionPorts:
    owner = PostgreSQLInteractionActionOwner()
    return InteractionActionPorts(owner, owner)


# Fixed constructors for the Runtime PostgreSQL integration composition.
compose_creator_input_repository = CreatorInputRepository
compose_external_message_input_service = ExternalMessageInputService
compose_external_message_input_repository = ExternalMessageInputRepository
compose_other_human_input_repository = OtherHumanInputRepository
compose_interaction_perception = PostgreSQLInteractionPerception
compose_scene_timeline_query = PostgreSQLSceneTimelineQuery


def bootstrap_interaction(
    unit_of_work_factory: PostgreSQLRuntimeUnitOfWorkFactory,
    *,
    environment_id: UUID,
    subject_id: UUID,
    creator_party_id: UUID,
    cursor_key: bytes,
    storage: ContentAddressedArtifactStore,
    codex_task_projection: SceneTimelineCodexTaskProjectionPort,
    catalog: InteractionArtifactCatalogPort,
    data_rights: InteractionDataRightsGate,
    visibility: DataRightsVisibilityPort,
    subject_state: SubjectStateReadPort,
    evidence: EvidenceWritePort,
    evidence_read: EvidenceReadPort,
    opportunity: OpportunityAdmissionPort,
    notifier: CreatorProjectionNotifier | None,
    wakeups: InteractionWakeupPort | None = None,
    diagnostic: Callable[[str], None] | None = None,
    fault_injector: Callable[[str], None] | None = None,
    identity: InteractionIdentityPort,
    timeline_projections: InteractionCreatorTimelineProjectionPort,
) -> InteractionModule:
    creator_repository = CreatorInputRepository(evidence, evidence_read, opportunity)
    other_repository = OtherHumanInputRepository(evidence, evidence_read, opportunity)
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
        subject_id=subject_id,
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
        subject_id=subject_id,
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
        subject_id=subject_id,
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
        visibility=visibility,
        projections=timeline_projections,
    )
    perception = PostgreSQLInteractionPerception()
    actions = bootstrap_interaction_action_ports()
    cognition = PostgreSQLInteractionContextRead()
    return InteractionModule(
        creator_input=creator_input,
        creator_transaction=creator_repository,
        creator_scenes=creator_scenes,
        scene_timeline=timeline,
        other_human_input=other_human,
        external_message_input=external,
        perception=perception,
        effect_delivery=perception,
        effect_routes=actions.routes,
        scene_transitions=actions.scenes,
        identity=identity,
        other_human_read=other_repository,
        context_read=cognition,
        cognition_read=cognition,
        subject_commit=PostgreSQLInteractionSubjectCommit(),
        _timeline=timeline,
    )


def bootstrap_interaction_data_rights() -> DataRightsParticipant:
    return PostgreSQLInteractionDataRightsParticipant()


def bootstrap_interaction_recovery() -> RecoveryParticipant:
    return InteractionRecoveryParticipant()


__all__ = (
    "InteractionActionPorts",
    "InteractionCognitionPorts",
    "InteractionModule",
    "bootstrap_interaction",
    "bootstrap_interaction_action_ports",
    "bootstrap_interaction_admin",
    "bootstrap_interaction_birth",
    "bootstrap_interaction_cognition",
    "bootstrap_interaction_data_rights",
    "bootstrap_interaction_identity",
    "bootstrap_interaction_recovery",
    "bootstrap_interaction_subject_commit",
    "compose_creator_input_repository",
    "compose_external_message_input_repository",
    "compose_external_message_input_service",
    "compose_interaction_perception",
    "compose_other_human_input_repository",
    "compose_scene_timeline_query",
)
