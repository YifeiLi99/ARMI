"""Public contracts for parties, scenes, interactions and channel bindings."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable
from uuid import UUID

from armi_kernel.application import ArtifactId, ArtifactRegistration, PublishedArtifact
from armi_kernel.contracts import Digest, Instant, TraceId
from armi_runtime_foundation import (
    PostgreSQLRuntimeUnitOfWork,
    PostgreSQLTransaction,
)
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


@dataclass(frozen=True, slots=True)
class CreatorIdentityContext:
    party_id: UUID
    default_scene_key: str


@runtime_checkable
class InteractionIdentityPort(Protocol):
    async def creator_context(
        self,
        transaction: PostgreSQLTransaction,
        *,
        subject_id: UUID,
    ) -> CreatorIdentityContext | None: ...


@runtime_checkable
class InteractionBirthPort(Protocol):
    async def initialize(
        self,
        transaction: PostgreSQLTransaction,
        *,
        subject_id: UUID,
        creator_party_id: UUID,
    ) -> None: ...


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


@dataclass(frozen=True, slots=True)
class ExternalContentPartSnapshot:
    part_id: UUID
    ordinal: int
    kind: ExternalMessagePartKind
    locator: str
    file_name: str | None
    media_type: str | None
    declared_byte_size: int | None
    visual_role: ExternalVisualRole | None
    source_kind: str | None
    source_summary: str | None
    status: str


@dataclass(frozen=True, slots=True)
class ExternalRecognitionSnapshot:
    interaction_id: UUID
    subject_id: UUID
    scene_id: UUID
    source_party_id: UUID
    purpose: str
    channel: str
    account_key: str
    trace_id: TraceId
    parts: tuple[ExternalContentPartSnapshot, ...]


@dataclass(frozen=True, slots=True)
class ExternalFinalizationPart:
    ordinal: int
    kind: ExternalMessagePartKind
    text_value: str | None
    target_key: str | None
    file_name: str | None
    visual_role: ExternalVisualRole | None
    source_kind: str | None
    source_summary: str | None
    detected_media_type: str | None
    pixel_width: int | None
    pixel_height: int | None
    frame_count: int | None
    status: str
    interpretation_text: str | None
    failure_code: str | None


@dataclass(frozen=True, slots=True)
class ExternalFinalizationSnapshot:
    interaction_id: UUID
    subject_id: UUID
    scene_id: UUID
    source_party_id: UUID
    purpose: str
    trace_id: TraceId
    parts: tuple[ExternalFinalizationPart, ...]


@dataclass(frozen=True, slots=True)
class ExternalRecognitionRecovery:
    interaction_id: UUID
    subject_id: UUID
    trace_id: TraceId
    part_ids: tuple[UUID, ...]


@runtime_checkable
class InteractionPerceptionPort(Protocol):
    async def recover_terminal(
        self,
        transaction: PostgreSQLTransaction,
        interaction_ids: tuple[UUID, ...],
    ) -> tuple[ExternalRecognitionRecovery, ...]: ...

    async def recognition_snapshot(
        self, transaction: PostgreSQLTransaction, interaction_id: UUID
    ) -> ExternalRecognitionSnapshot: ...

    async def attach_raw(
        self, transaction: PostgreSQLTransaction, *, part_id: UUID, artifact_id: UUID
    ) -> None: ...

    async def attach_visual_detection(
        self,
        transaction: PostgreSQLTransaction,
        *,
        part_id: UUID,
        media_type: str,
        pixel_width: int,
        pixel_height: int,
        frame_count: int,
    ) -> None: ...

    async def settle_part_success(
        self,
        transaction: PostgreSQLTransaction,
        *,
        part_id: UUID,
        raw_artifact_id: UUID,
        interpretation_artifact_id: UUID,
        interpretation_text: str,
    ) -> None: ...

    async def settle_part_failure(
        self,
        transaction: PostgreSQLTransaction,
        *,
        part_id: UUID,
        status: str,
        error_code: str,
    ) -> None: ...

    async def has_pending_parts(
        self, transaction: PostgreSQLTransaction, interaction_id: UUID
    ) -> bool: ...

    async def finalization_snapshot(
        self, transaction: PostgreSQLTransaction, interaction_id: UUID
    ) -> ExternalFinalizationSnapshot: ...

    async def complete_finalization(
        self,
        transaction: PostgreSQLTransaction,
        *,
        snapshot: ExternalFinalizationSnapshot,
        content_digest: Digest,
    ) -> None: ...


@runtime_checkable
class InteractionEffectDeliveryPort(Protocol):
    async def record_party_response(
        self,
        transaction: PostgreSQLTransaction,
        *,
        scene_id: UUID,
        effect_id: UUID,
        occurred_at: Instant,
    ) -> None: ...


__all__ = (
    "PROJECTION_VERSION",
    "SCENE_COLLECTION_PROJECTION_VERSION",
    "ConfigureExternalCreatorCommand",
    "CreatorIdentityContext",
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
    "ExternalContentPartSnapshot",
    "ExternalConversationKey",
    "ExternalConversationKind",
    "ExternalCreatorBinding",
    "ExternalFinalizationPart",
    "ExternalFinalizationSnapshot",
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
    "ExternalRecognitionRecovery",
    "ExternalRecognitionSnapshot",
    "ExternalVisualRole",
    "InteractionArtifactCatalogPort",
    "InteractionBirthPort",
    "InteractionDataRightsGate",
    "InteractionEffectDeliveryPort",
    "InteractionIdentityPort",
    "InteractionPerceptionPort",
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
