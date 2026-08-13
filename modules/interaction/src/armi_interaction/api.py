"""Public contracts for parties, scenes, interactions and channel bindings."""

from __future__ import annotations

from typing import Protocol, runtime_checkable
from uuid import UUID

from armi_kernel.application import ArtifactId, ArtifactRegistration, PublishedArtifact
from armi_runtime_foundation import PostgreSQLRuntimeUnitOfWork
from armi_subject_state.api import SubjectSummary

from ._creator_contract import (
    CreatorInputAcceptance,
    CreatorInputAcceptancePort,
    CreatorInputCommand,
    CreatorInputContext,
    CreatorInputViolation,
    CreatorInteractionId,
    CreatorOperation,
    CreatorOperationPhase,
    CreatorOperationQueryPort,
    OpportunityId,
)
from ._external_contract import (
    ConfigureExternalCreatorCommand,
    ExternalAccountKey,
    ExternalChannel,
    ExternalConversationKey,
    ExternalConversationKind,
    ExternalCreatorBinding,
    ExternalMessageInputAcceptance,
    ExternalMessageInputPort,
    ExternalMessageInteractionId,
    ExternalMessageKey,
    ExternalMessageOutputPart,
    ExternalMessageOutputPartKind,
    ExternalMessagePart,
    ExternalMessagePartKind,
    ExternalMessageSendPort,
    ExternalMessageSendReceipt,
    ExternalMessageSendRequest,
    ExternalMessageViolation,
    ExternalPartyKey,
    ExternalVisualRole,
    ObservedExternalMessage,
)
from ._other_human_contract import (
    OtherHumanInputAcceptance,
    OtherHumanInputCommand,
    OtherHumanInputPort,
    OtherHumanInputViolation,
    OtherHumanInteractionId,
    OtherHumanPartyKey,
    OtherHumanPartyView,
    OtherHumanSceneCommand,
    OtherHumanSceneView,
    RegisterOtherHumanPartyCommand,
)
from ._scene_contract import (
    PROJECTION_VERSION,
    SCENE_COLLECTION_PROJECTION_VERSION,
    CreatorSceneCollection,
    CreatorSceneCreateCommand,
    CreatorScenePort,
    CreatorSceneStatusCommand,
    CreatorSceneView,
    SceneKey,
    SceneQueryViolation,
    SceneStatus,
    SceneTimelineCodexTaskProjectionPort,
    SceneTimelineItem,
    SceneTimelinePage,
    SceneTimelineQuery,
    SceneTimelineQueryPort,
    TimelineItemId,
)


@runtime_checkable
class InteractionArtifactCatalogPort(Protocol):
    async def register(
        self,
        unit_of_work: PostgreSQLRuntimeUnitOfWork,
        artifact_id: ArtifactId,
        published: PublishedArtifact,
    ) -> ArtifactRegistration: ...


@runtime_checkable
class InteractionDataRightsGate(Protocol):
    async def blocks_new_interaction(
        self,
        unit_of_work: PostgreSQLRuntimeUnitOfWork,
        requester_party_id: UUID,
    ) -> bool: ...


@runtime_checkable
class InteractionWakeupPort(Protocol):
    def notify(self, channel: str) -> None: ...


@runtime_checkable
class CreatorInteractionPort(
    CreatorInputAcceptancePort,
    CreatorOperationQueryPort,
    Protocol,
):
    async def get_subject_summary(self) -> SubjectSummary: ...


@runtime_checkable
class CreatorInputTransactionPort(Protocol):
    async def lock_scene(
        self,
        unit_of_work: PostgreSQLRuntimeUnitOfWork,
        *,
        scene_id: UUID,
    ) -> None: ...

    async def context(
        self,
        unit_of_work: PostgreSQLRuntimeUnitOfWork,
        *,
        scene_key: str,
        creator_party_id: UUID,
    ) -> CreatorInputContext: ...


__all__ = (
    "PROJECTION_VERSION",
    "SCENE_COLLECTION_PROJECTION_VERSION",
    "ConfigureExternalCreatorCommand",
    "CreatorInputAcceptance",
    "CreatorInputAcceptancePort",
    "CreatorInputCommand",
    "CreatorInputContext",
    "CreatorInputTransactionPort",
    "CreatorInputViolation",
    "CreatorInteractionId",
    "CreatorInteractionPort",
    "CreatorOperation",
    "CreatorOperationPhase",
    "CreatorOperationQueryPort",
    "CreatorSceneCollection",
    "CreatorSceneCreateCommand",
    "CreatorScenePort",
    "CreatorSceneStatusCommand",
    "CreatorSceneView",
    "ExternalAccountKey",
    "ExternalChannel",
    "ExternalConversationKey",
    "ExternalConversationKind",
    "ExternalCreatorBinding",
    "ExternalMessageInputAcceptance",
    "ExternalMessageInputPort",
    "ExternalMessageInteractionId",
    "ExternalMessageKey",
    "ExternalMessageOutputPart",
    "ExternalMessageOutputPartKind",
    "ExternalMessagePart",
    "ExternalMessagePartKind",
    "ExternalMessageSendPort",
    "ExternalMessageSendReceipt",
    "ExternalMessageSendRequest",
    "ExternalMessageViolation",
    "ExternalPartyKey",
    "ExternalVisualRole",
    "InteractionArtifactCatalogPort",
    "InteractionDataRightsGate",
    "InteractionWakeupPort",
    "ObservedExternalMessage",
    "OpportunityId",
    "OtherHumanInputAcceptance",
    "OtherHumanInputCommand",
    "OtherHumanInputPort",
    "OtherHumanInputViolation",
    "OtherHumanInteractionId",
    "OtherHumanPartyKey",
    "OtherHumanPartyView",
    "OtherHumanSceneCommand",
    "OtherHumanSceneView",
    "RegisterOtherHumanPartyCommand",
    "SceneKey",
    "SceneQueryViolation",
    "SceneStatus",
    "SceneTimelineCodexTaskProjectionPort",
    "SceneTimelineItem",
    "SceneTimelinePage",
    "SceneTimelineQuery",
    "SceneTimelineQueryPort",
    "TimelineItemId",
)
