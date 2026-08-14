from __future__ import annotations

import unittest
from datetime import UTC, datetime
from typing import Any, cast
from uuid import UUID, uuid7

from armi_activity.api import (
    ActivityStatus,
    ActivityTransition,
    ActivityViolation,
    CreatorActivityItem,
    CreatorActivityPage,
    CreatorActivityTimeline,
    CreatorActivityTimelineItem,
)
from armi_capability.api import (
    CapabilityRequestPage,
    CapabilityRequestSnapshot,
    CapabilityRequestStatus,
    CreatorGrantCommand,
    CreatorGrantResult,
)
from armi_codex.api import CodexModel, CreatorCodexTaskCommand
from armi_data_rights.api import (
    CreatorExportCommand,
    CreatorExportResult,
    CreatorExportStatus,
    DataRightsExecutionStatus,
    DataRightsOrderCommand,
    DataRightsOrderDetail,
    DataRightsOrderKind,
    DataRightsOrderResult,
    DataRightsPartyKey,
    DataRightsRequesterKind,
    DataRightsScopeKind,
    DataRightsViolation,
)
from armi_effect.api import EffectArtifactKind
from armi_evidence.api import EvidenceId
from armi_interaction.api import (
    CreatorInputAcceptance,
    CreatorInputCommand,
    CreatorInteractionId,
    CreatorOperation,
    CreatorOperationPhase,
    CreatorSceneCollection,
    CreatorSceneCreateCommand,
    CreatorSceneStatusCommand,
    CreatorSceneView,
    OpportunityId,
    OtherHumanInputAcceptance,
    OtherHumanInputCommand,
    OtherHumanInputViolation,
    OtherHumanInteractionId,
    OtherHumanPartyView,
    OtherHumanSceneCommand,
    OtherHumanSceneView,
    RegisterOtherHumanPartyCommand,
    SceneKey,
    SceneQueryViolation,
    SceneStatus,
    SceneTimelinePage,
    SceneTimelineQuery,
)
from armi_kernel.application import (
    LifeRecordActor,
    LifeRecordItem,
    LifeRecordKind,
    LifeRecordPage,
    LifeRecordQuery,
    LifeRecordQueryViolation,
    OtherHumanPartyRecord,
    OtherHumanPartyRecordPage,
    OtherHumanRecordDirection,
    OtherHumanSceneRecord,
    OtherHumanSceneRecordPage,
    OtherHumanTimelineRecord,
    OtherHumanTimelineRecordPage,
)
from armi_kernel.contracts import Digest, Instant
from armi_material.api import (
    CreatorLifeMaterialItem,
    LifeMaterialKind,
    LifeMaterialPrivacyStatus,
    LifeMaterialStatus,
    MaterialViolation,
)
from armi_memory.api import (
    CreatorMemoryItem,
    CreatorMemoryPage,
    CreatorMemoryTimeline,
    CreatorMemoryTimelineItem,
)
from armi_memory.api import (
    MemoryAccessibility as QueryMemoryAccessibility,
)
from armi_memory.api import (
    MemoryRevisionKind as QueryMemoryRevisionKind,
)
from armi_prompt.api import (
    CreatorPromptDeactivateCommand,
    CreatorPromptRevisionCommand,
    CreatorPromptView,
    CreatorPromptViolation,
    PromptDocumentStatus,
    PromptKind,
    PromptRevisionKind,
)
from armi_relationship.api import (
    CreatorRelationshipItem,
    CreatorRelationshipRevision,
    CreatorRelationshipTimeline,
    RelationshipBoundary,
    RelationshipBoundaryAction,
    RelationshipBoundaryKind,
    RelationshipFact,
    RelationshipFactKind,
    RelationshipPartyRole,
    RelationshipStatus,
)
from armi_relationship.api import (
    RelationshipViolation as CreatorRelationshipViolation,
)
from armi_runtime.composition.lifecycle import LifecycleController
from armi_runtime.interfaces.browser_sessions import BrowserSessionStore
from armi_runtime.interfaces.creator_app import (
    create_runtime_app,
    creator_visible_codex_artifact,
    operation_wire,
)
from armi_runtime.interfaces.creator_contract import (
    QQChannelHealthResponse,
    Readiness,
    RuntimeStatusResponse,
)
from armi_runtime.interfaces.creator_events import CreatorEventBroker
from armi_runtime.interfaces.static_assets import StaticAsset, StaticAssetStore
from armi_sleep.api import (
    CreatorMaintenanceSession,
    CreatorMaintenanceStatus,
    CreatorMaintenanceTimeline,
    CreatorMaintenanceTimelineItem,
    CreatorMaintenanceViolation,
    MaintenancePhase,
    MaintenanceResultStatus,
    MaintenanceTriggerKind,
    MaintenanceWorkOutcome,
)
from fastapi.testclient import TestClient

ENVIRONMENT_ID = "01980f7d-7b8f-7e2a-8a11-2ab8e1234567"
CREATOR_ID = "01980f7d-7b8f-7e2a-8a11-2ab8e1234568"
AUTHORITY = "127.0.0.1:45678"
CREATOR_BEARER = f"creator-v1.{'a' * 43}"


class _SceneTimelineQuery:
    async def query(self, request: SceneTimelineQuery) -> SceneTimelinePage:
        if request.scene_key.value != "default":
            raise SceneQueryViolation("SCENE-NOT-VISIBLE")
        return SceneTimelinePage(scene_key=request.scene_key, items=())


class _OtherHumanInput:
    def __init__(self) -> None:
        self.party_id = uuid7()
        self.scene_id = uuid7()
        self.commands: list[object] = []
        self.party_key: str | None = None
        self.scene_status = SceneStatus.CLOSED
        self.accepted: dict[str, tuple[str, OtherHumanInputAcceptance]] = {}

    async def register_party(
        self, command: RegisterOtherHumanPartyCommand
    ) -> OtherHumanPartyView:
        self.commands.append(command)
        self.party_key = command.party_key.value
        return OtherHumanPartyView(
            self.party_id, command.party_key, command.display_label
        )

    async def set_scene(self, command: OtherHumanSceneCommand) -> OtherHumanSceneView:
        self.commands.append(command)
        if command.party_key.value != self.party_key:
            raise OtherHumanInputViolation("SCOPE-OTHER-HUMAN-PARTY-NOT-VISIBLE")
        self.scene_status = command.target_status
        return OtherHumanSceneView(
            self.scene_id, self.party_id, command.scene_key, command.target_status
        )

    async def accept(
        self, command: OtherHumanInputCommand
    ) -> OtherHumanInputAcceptance:
        self.commands.append(command)
        if (
            command.party_key.value != self.party_key
            or self.scene_status is SceneStatus.CLOSED
        ):
            raise OtherHumanInputViolation("SCOPE-OTHER-HUMAN-SCENE-NOT-VISIBLE")
        prior = self.accepted.get(command.idempotency_key.value)
        content_digest = Digest.from_bytes(command.message_bytes)
        if prior is not None:
            if prior[0] != content_digest.value:
                raise OtherHumanInputViolation("IDEMPOTENCY-OTHER-HUMAN-INPUT-MISMATCH")
            return OtherHumanInputAcceptance(
                prior[1].party_id,
                prior[1].scene_id,
                prior[1].interaction_id,
                prior[1].evidence_id,
                prior[1].opportunity_id,
                prior[1].request_digest,
                prior[1].content_digest,
                False,
            )
        acceptance = OtherHumanInputAcceptance(
            self.party_id,
            self.scene_id,
            OtherHumanInteractionId(uuid7()),
            EvidenceId(uuid7()),
            OpportunityId(uuid7()),
            Digest.from_bytes(b"request"),
            content_digest,
            True,
        )
        self.accepted[command.idempotency_key.value] = (
            content_digest.value,
            acceptance,
        )
        return acceptance


class _OtherHumanRecordQuery:
    def __init__(self) -> None:
        self.party_id = uuid7()
        self.scene_id = uuid7()
        self.now = datetime.now(UTC)

    async def list_parties(self, *, limit: int, cursor=None):
        del limit, cursor
        return OtherHumanPartyRecordPage(
            (OtherHumanPartyRecord(self.party_id, "friend-1", "朋友", 1, 2, self.now),),
            None,
        )

    async def list_scenes(self, party_id, *, limit: int, cursor=None):
        del limit, cursor
        return OtherHumanSceneRecordPage(
            OtherHumanPartyRecord(party_id, "friend-1", "朋友", 1, 2, self.now),
            (OtherHumanSceneRecord(self.scene_id, "tea", "open", 2, self.now),),
            None,
        )

    async def timeline(self, party_id, scene_id, *, limit: int, cursor=None):
        del limit, cursor
        return OtherHumanTimelineRecordPage(
            party_id,
            scene_id,
            (
                OtherHumanTimelineRecord(
                    uuid7(),
                    uuid7(),
                    OtherHumanRecordDirection.RECEIVED,
                    "accepted",
                    "你好",
                    self.now,
                ),
            ),
            None,
        )


class _CreatorScenes:
    def __init__(self) -> None:
        self.opened_at = Instant(datetime(2026, 8, 6, 8, 0, tzinfo=UTC))
        default = CreatorSceneView(
            uuid7(),
            SceneKey("default"),
            SceneStatus.OPEN,
            self.opened_at,
            None,
            None,
            True,
        )
        self.scenes = {"default": default}

    async def list(self) -> CreatorSceneCollection:
        return CreatorSceneCollection(
            tuple(
                sorted(
                    self.scenes.values(),
                    key=lambda scene: (not scene.is_default, scene.scene_key.value),
                )
            )
        )

    async def create(self, command: CreatorSceneCreateCommand) -> CreatorSceneView:
        created = CreatorSceneView(
            uuid7(),
            command.scene_key,
            SceneStatus.OPEN,
            self.opened_at,
            None,
            None,
            False,
        )
        self.scenes[command.scene_key.value] = created
        return created

    async def set_status(
        self,
        command: CreatorSceneStatusCommand,
    ) -> CreatorSceneView:
        current = self.scenes[command.scene_key.value]
        changed = CreatorSceneView(
            current.scene_id,
            current.scene_key,
            command.target_status,
            current.opened_at,
            (
                None
                if command.target_status is SceneStatus.OPEN
                else Instant(datetime(2026, 8, 6, 9, 0, tzinfo=UTC))
            ),
            current.recent_context_boundary,
            False,
        )
        self.scenes[command.scene_key.value] = changed
        return changed


class _CreatorActivityQuery:
    def __init__(self) -> None:
        self.activity_id = uuid7()
        self.created_at = datetime(2026, 8, 4, 10, 0, tzinfo=UTC)

    async def list_current(self) -> CreatorActivityPage:
        return CreatorActivityPage(
            (
                CreatorActivityItem(
                    activity_id=self.activity_id,
                    activity_kind="self_directed",
                    status=ActivityStatus.READY,
                    goal="整理今天想继续探索的事情",
                    progress_summary=None,
                    waiting_kind=None,
                    waiting_summary=None,
                    resume_not_before=None,
                    terminal_reason=None,
                    revision_no=1,
                    head_version=1,
                    transition_kind=ActivityTransition.CREATED,
                    is_focused=False,
                    created_at=self.created_at,
                    updated_at=self.created_at,
                ),
            ),
            False,
        )

    async def timeline(self, activity_id: UUID) -> CreatorActivityTimeline:
        if activity_id != self.activity_id:
            raise ActivityViolation("ACTIVITY-QUERY-NOT-FOUND")
        return CreatorActivityTimeline(
            activity_id,
            (
                CreatorActivityTimelineItem(
                    event_id=uuid7(),
                    event_kind="created",
                    resulting_status=ActivityStatus.READY,
                    summary=None,
                    review_not_before=None,
                    occurred_at=self.created_at,
                ),
            ),
            False,
        )


class _CreatorRelationshipQuery:
    def __init__(self) -> None:
        self.relationship_id = uuid7()
        self.revision_id = uuid7()
        self.occurred_at = datetime(2026, 8, 5, 10, 0, tzinfo=UTC)

    def _revision(self) -> CreatorRelationshipRevision:
        return CreatorRelationshipRevision(
            relationship_revision_id=self.revision_id,
            revision_no=1,
            facts=(
                RelationshipFact(
                    uuid7(),
                    RelationshipFactKind.PARTY_EXPRESSION,
                    "Creator 表达了联系限制",
                ),
            ),
            interpretation="我会尊重这项边界",
            boundaries=(
                RelationshipBoundary(
                    RelationshipPartyRole.OTHER,
                    RelationshipBoundaryKind.CONTACT,
                    RelationshipBoundaryAction.RESTRICT,
                    "不要在深夜联系",
                ),
            ),
            commitments=(),
            open_issues=(),
            commitment_event=None,
            status=RelationshipStatus.ACTIVE,
            occurred_at=self.occurred_at,
        )

    async def current(self) -> CreatorRelationshipItem:
        current = self._revision()
        return CreatorRelationshipItem(
            relationship_id=self.relationship_id,
            current_revision_id=self.revision_id,
            head_version=1,
            current=current,
            created_at=self.occurred_at,
        )

    async def timeline(self, relationship_id: UUID) -> CreatorRelationshipTimeline:
        if relationship_id != self.relationship_id:
            raise CreatorRelationshipViolation("RELATIONSHIP-QUERY-NOT-FOUND")
        return CreatorRelationshipTimeline(
            relationship_id,
            (self._revision(),),
            False,
        )


class _CreatorMaintenanceQuery:
    def __init__(self) -> None:
        self.session_id = uuid7()
        self.revision_id = uuid7()
        self.occurred_at = datetime(2026, 8, 4, 11, 0, tzinfo=UTC)
        self.wake_requested = False

    async def status(self) -> CreatorMaintenanceStatus:
        return CreatorMaintenanceStatus(
            CreatorMaintenanceSession(
                session_id=self.session_id,
                trigger_kind=MaintenanceTriggerKind.SYSTEM_DEADLINE,
                phase=MaintenancePhase.SELF_CHECK,
                result_status=MaintenanceResultStatus.RUNNING,
                revision_no=3,
                head_version=3,
                wake_requested=self.wake_requested,
                started_at=self.occurred_at,
                updated_at=self.occurred_at,
                finished_at=None,
            ),
            2,
        )

    async def timeline(self, session_id: UUID) -> CreatorMaintenanceTimeline:
        if session_id != self.session_id:
            raise CreatorMaintenanceViolation("MAINTENANCE-QUERY-NOT-FOUND")
        return CreatorMaintenanceTimeline(
            session_id,
            (
                CreatorMaintenanceTimelineItem(
                    revision_id=self.revision_id,
                    revision_no=3,
                    phase=MaintenancePhase.SELF_CHECK,
                    result_status=MaintenanceResultStatus.RUNNING,
                    transition_kind="advanced",
                    occurred_at=self.occurred_at,
                    work_outcome=MaintenanceWorkOutcome.ISSUE_FOUND,
                    problem_summary="有一项内部责任需要后续关注。",
                ),
            ),
            False,
        )


class _LifeRecordQuery:
    def __init__(self) -> None:
        self.memory_id = uuid7()
        self.material_id = uuid7()
        self.material_unavailable = False
        self.revision_id = uuid7()
        self.occurred_at = datetime(2026, 8, 4, 10, 30, tzinfo=UTC)
        self.requests: list[LifeRecordQuery] = []

    async def get_creator_visible(
        self,
        material_id: UUID,
    ) -> CreatorLifeMaterialItem | None:
        if self.material_unavailable:
            raise MaterialViolation("MATERIAL-QUERY-UNAVAILABLE")
        if material_id != self.material_id:
            return None
        body = "这段正文经过服务端可见性授权。"
        return CreatorLifeMaterialItem(
            material_id=self.material_id,
            current_revision_id=self.revision_id,
            material_kind=LifeMaterialKind.DIARY,
            revision_no=2,
            head_version=2,
            title="雨天随记",
            body=body,
            metadata=(("mood", "quiet"),),
            material_status=LifeMaterialStatus.ACTIVE,
            privacy_status=LifeMaterialPrivacyStatus.CREATOR_VISIBLE,
            created_at=Instant(self.occurred_at),
            updated_at=Instant(self.occurred_at),
        )

    async def query(self, request: LifeRecordQuery) -> LifeRecordPage:
        self.requests.append(request)
        return LifeRecordPage(
            (
                LifeRecordItem(
                    record_ref=self.memory_id,
                    record_kind=LifeRecordKind("memory"),
                    summary="刚从记录查到的旧理解",
                    source_kind="reported",
                    occurred_at=Instant(self.occurred_at),
                    naturally_recallable=False,
                    retrieval_kind=request.retrieval_kind,
                ),
            )
        )

    async def list_current(
        self,
        *,
        limit: int,
        query_text: str | None = None,
        cursor=None,
    ) -> CreatorMemoryPage:
        del limit, query_text, cursor
        return CreatorMemoryPage(
            (
                CreatorMemoryItem(
                    memory_id=self.memory_id,
                    summary="刚从记录查到的旧理解",
                    uncertainty="来源是转述",
                    source_kind="reported",
                    source_fact_class="external_claim",
                    accessibility=QueryMemoryAccessibility.FORGOTTEN,
                    revision_kind=QueryMemoryRevisionKind.FORGOTTEN,
                    revision_no=2,
                    head_version=2,
                    created_at=Instant(self.occurred_at),
                    updated_at=Instant(self.occurred_at),
                ),
            )
        )

    async def timeline(
        self,
        memory_id: UUID,
        *,
        limit: int,
        cursor=None,
    ) -> CreatorMemoryTimeline:
        del limit, cursor
        if memory_id != self.memory_id:
            raise LifeRecordQueryViolation("LIFE-QUERY-NOT-FOUND")
        return CreatorMemoryTimeline(
            memory_id,
            (
                CreatorMemoryTimelineItem(
                    revision_id=self.revision_id,
                    revision_no=2,
                    revision_kind=QueryMemoryRevisionKind.FORGOTTEN,
                    accessibility=QueryMemoryAccessibility.FORGOTTEN,
                    summary="刚从记录查到的旧理解",
                    uncertainty="来源是转述",
                    source_kind="reported",
                    source_fact_class="external_claim",
                    relation_kind=None,
                    related_memory_id=None,
                    occurred_at=Instant(self.occurred_at),
                ),
            ),
        )


class _EmergencyWake:
    def __init__(self, query: _CreatorMaintenanceQuery) -> None:
        self.query = query
        self.requests: list[tuple[UUID, UUID]] = []

    async def request_emergency_wake(
        self,
        session_id: UUID,
        request_id: UUID,
    ) -> UUID:
        if session_id != self.query.session_id:
            raise AssertionError("unexpected maintenance session")
        self.requests.append((session_id, request_id))
        self.query.wake_requested = True
        return session_id


class _CreatorInput:
    def __init__(self) -> None:
        self.acceptance = CreatorInputAcceptance(
            CreatorInteractionId(uuid7()),
            EvidenceId(uuid7()),
            OpportunityId(uuid7()),
            Digest.from_bytes(b"request"),
            Digest.from_bytes(b"message"),
            True,
        )
        self.commands: list[CreatorInputCommand] = []

    async def accept(self, command: CreatorInputCommand) -> CreatorInputAcceptance:
        self.commands.append(command)
        return self.acceptance

    async def get(self, opportunity_id: OpportunityId) -> CreatorOperation:
        self.assert_opportunity(opportunity_id)
        value = self.acceptance
        return CreatorOperation(
            CreatorInputAcceptance(
                value.interaction_id,
                value.evidence_id,
                value.opportunity_id,
                value.request_digest,
                value.content_digest,
                False,
            ),
            CreatorOperationPhase.ACCEPTED,
        )

    def assert_opportunity(self, opportunity_id: OpportunityId) -> None:
        if opportunity_id != self.acceptance.opportunity_id:
            raise AssertionError("unexpected opportunity")


class _CreatorCodexTask:
    def __init__(self) -> None:
        self.acceptance = CreatorInputAcceptance(
            CreatorInteractionId(uuid7()),
            EvidenceId(uuid7()),
            OpportunityId(uuid7()),
            Digest.from_bytes(b"codex-request"),
            Digest.from_bytes(b"codex-task-manifest"),
            True,
        )
        self.commands: list[CreatorCodexTaskCommand] = []

    async def accept(self, command: CreatorCodexTaskCommand) -> CreatorInputAcceptance:
        self.commands.append(command)
        return self.acceptance


class _CapabilityPolicy:
    def __init__(self) -> None:
        self.request_id = uuid7()
        self.commands: list[CreatorGrantCommand] = []

    async def open(self) -> None:
        return None

    async def close(self) -> None:
        return None

    def stop(self) -> None:
        return None

    async def run_expiry_reconciler(self) -> None:
        return None

    async def expire_once(self, *, limit: int = 100) -> int:
        del limit
        return 0

    async def list_requests(
        self,
        *,
        creator_party_id: UUID,
        limit: int,
        cursor: str | None,
    ) -> CapabilityRequestPage:
        del cursor
        item = CapabilityRequestSnapshot(
            self.request_id,
            "creator.scene.reply",
            "send",
            UUID(ENVIRONMENT_ID),
            UUID(ENVIRONMENT_ID),
            "creator",
            "creator_visible_response",
            "respond_to_creator",
            None,
            None,
            None,
            60,
            1,
            1024,
            "pending",
            1,
            datetime.now(UTC),
            datetime.now(UTC),
            "available",
            None,
            None,
        )
        del creator_party_id
        return CapabilityRequestPage((item,)[:limit], None)

    async def decide(self, command: CreatorGrantCommand) -> CreatorGrantResult:
        self.commands.append(command)
        return CreatorGrantResult(
            command.request_id,
            command.expected_version + 1,
            CapabilityRequestStatus.DENIED,
        )


class _CreatorPrompt:
    def __init__(self) -> None:
        self.document_id = uuid7()
        self.current = CreatorPromptView(
            prompt_document_id=self.document_id,
            prompt_kind=PromptKind.CREATOR_GUIDANCE,
            status=PromptDocumentStatus.ACTIVE,
            current_revision_id=None,
            revision_no=None,
            previous_revision_id=None,
            revision_kind=None,
            content=None,
            activated_at=None,
        )

    async def get(self, prompt_kind: PromptKind) -> CreatorPromptView:
        if prompt_kind is not PromptKind.CREATOR_GUIDANCE:
            raise CreatorPromptViolation("SCOPE-PROMPT-NOT-WRITABLE")
        return self.current

    async def revise(
        self,
        command: CreatorPromptRevisionCommand,
    ) -> CreatorPromptView:
        if command.expected_revision_id != self.current.current_revision_id:
            raise CreatorPromptViolation("CONFLICT-PROMPT-REVISION")
        revision_id = uuid7()
        self.current = CreatorPromptView(
            prompt_document_id=self.document_id,
            prompt_kind=PromptKind.CREATOR_GUIDANCE,
            status=PromptDocumentStatus.ACTIVE,
            current_revision_id=revision_id,
            revision_no=(self.current.revision_no or 0) + 1,
            previous_revision_id=self.current.current_revision_id,
            revision_kind=(
                PromptRevisionKind.CREATED
                if self.current.current_revision_id is None
                else PromptRevisionKind.REVISED
            ),
            content=command.content,
            activated_at=Instant(datetime.now(UTC)),
        )
        return self.current

    async def deactivate(
        self,
        command: CreatorPromptDeactivateCommand,
    ) -> CreatorPromptView:
        if command.expected_revision_id != self.current.current_revision_id:
            raise CreatorPromptViolation("CONFLICT-PROMPT-REVISION")
        assert self.current.content is not None
        revision_id = uuid7()
        self.current = CreatorPromptView(
            prompt_document_id=self.document_id,
            prompt_kind=PromptKind.CREATOR_GUIDANCE,
            status=PromptDocumentStatus.INACTIVE,
            current_revision_id=revision_id,
            revision_no=(self.current.revision_no or 0) + 1,
            previous_revision_id=self.current.current_revision_id,
            revision_kind=PromptRevisionKind.DEACTIVATED,
            content=self.current.content,
            activated_at=Instant(datetime.now(UTC)),
        )
        return self.current


class _CreatorExport:
    def __init__(self) -> None:
        self.results: dict[UUID, CreatorExportResult] = {}
        self.commands: list[CreatorExportCommand] = []

    async def export(self, command: CreatorExportCommand) -> CreatorExportResult:
        self.commands.append(command)
        export_id = uuid7()
        now = Instant(datetime.now(UTC))
        partial = command.directory_name == "partial-export"
        result = CreatorExportResult(
            export_id=export_id,
            status=(
                CreatorExportStatus.PARTIAL
                if partial
                else CreatorExportStatus.COMPLETED
            ),
            directory_name=command.directory_name,
            destination_path=f"data/exports/{command.directory_name}",
            segment_count=39,
            record_count=120,
            artifact_count=4,
            missing_artifacts=(Digest.from_bytes(b"missing").value,) if partial else (),
            error_code=None,
            created_at=now,
            completed_at=now,
            newly_created=True,
        )
        self.results[export_id] = result
        return result

    async def get(self, export_id: UUID) -> CreatorExportResult | None:
        return self.results.get(export_id)


class _DataRightsOrders:
    def __init__(self, other_party_id: UUID) -> None:
        self.other_party_id = other_party_id
        self.results: dict[UUID, DataRightsOrderResult] = {}
        self.idempotent: dict[tuple[UUID, str], DataRightsOrderResult] = {}

    async def request_creator(
        self, command: DataRightsOrderCommand
    ) -> DataRightsOrderResult:
        return self._request(UUID(CREATOR_ID), DataRightsRequesterKind.CREATOR, command)

    async def request_other_human(
        self, party_key: DataRightsPartyKey, command: DataRightsOrderCommand
    ) -> DataRightsOrderResult:
        if party_key.value != "friend-1":
            raise DataRightsViolation("DATA-RIGHTS-REQUESTER-NOT-FOUND")
        return self._request(
            self.other_party_id,
            DataRightsRequesterKind.OTHER_HUMAN,
            command,
        )

    async def get_creator(self, order_id: UUID) -> DataRightsOrderResult | None:
        result = self.results.get(order_id)
        return (
            result
            if result is not None
            and result.requester_kind is DataRightsRequesterKind.CREATOR
            else None
        )

    async def get_other_human(
        self, party_key: DataRightsPartyKey, order_id: UUID
    ) -> DataRightsOrderResult | None:
        if party_key.value != "friend-1":
            raise DataRightsViolation("DATA-RIGHTS-REQUESTER-NOT-FOUND")
        result = self.results.get(order_id)
        return (
            result
            if result is not None
            and result.requester_kind is DataRightsRequesterKind.OTHER_HUMAN
            else None
        )

    async def list_creator(self) -> tuple[DataRightsOrderDetail, ...]:
        return tuple(
            DataRightsOrderDetail(result, ())
            for result in reversed(tuple(self.results.values()))
        )

    async def detail_creator(self, order_id: UUID) -> DataRightsOrderDetail | None:
        result = self.results.get(order_id)
        return None if result is None else DataRightsOrderDetail(result, ())

    async def list_other_human(
        self, party_key: DataRightsPartyKey
    ) -> tuple[DataRightsOrderDetail, ...]:
        if party_key.value != "friend-1":
            raise DataRightsViolation("DATA-RIGHTS-REQUESTER-NOT-FOUND")
        return tuple(
            DataRightsOrderDetail(result, ())
            for result in reversed(tuple(self.results.values()))
            if result.requester_kind is DataRightsRequesterKind.OTHER_HUMAN
        )

    async def detail_other_human(
        self, party_key: DataRightsPartyKey, order_id: UUID
    ) -> DataRightsOrderDetail | None:
        result = await self.get_other_human(party_key, order_id)
        return None if result is None else DataRightsOrderDetail(result, ())

    def _request(
        self,
        party_id: UUID,
        requester_kind: DataRightsRequesterKind,
        command: DataRightsOrderCommand,
    ) -> DataRightsOrderResult:
        key = (party_id, command.idempotency_key.value)
        existing = self.idempotent.get(key)
        if existing is not None:
            return DataRightsOrderResult(
                existing.order_id,
                existing.requester_party_id,
                existing.requester_kind,
                existing.order_kind,
                existing.scope_kind,
                existing.scope_party_id,
                existing.status,
                existing.execution_status,
                existing.request_digest,
                existing.effective_at,
                existing.completed_at,
                False,
            )
        now = Instant(datetime.now(UTC))
        result = DataRightsOrderResult(
            uuid7(),
            party_id,
            requester_kind,
            command.order_kind,
            (
                DataRightsScopeKind.PARTY_CONTACT
                if command.order_kind is DataRightsOrderKind.STOP_CONTACT
                else DataRightsScopeKind.PARTY_LOCAL_DATA
            ),
            party_id,
            "effective",
            (
                DataRightsExecutionStatus.PENDING
                if command.order_kind is DataRightsOrderKind.DELETE_RELATED
                else DataRightsExecutionStatus.NOT_REQUIRED
            ),
            Digest.from_bytes(command.order_kind.value.encode()),
            now,
            None,
            True,
        )
        self.idempotent[key] = result
        self.results[result.order_id] = result
        return result


class CreatorRuntimeAppTests(unittest.TestCase):
    def setUp(self) -> None:
        self.lifecycle = LifecycleController(environment_id=ENVIRONMENT_ID)
        self.assets = StaticAssetStore(
            {
                "index.html": StaticAsset(
                    b"<!doctype html><title>ARMI Creator</title>",
                    "text/html",
                    "no-store",
                ),
                "assets/app-a1.js": StaticAsset(
                    b"export {};",
                    "text/javascript",
                    "public, max-age=31536000, immutable",
                ),
            }
        )
        self.sessions = BrowserSessionStore(
            environment_id=UUID(ENVIRONMENT_ID),
            creator_party_id=UUID(CREATOR_ID),
            session_ttl_seconds=28_800,
        )
        self.events = CreatorEventBroker(epoch=b"\x06" * 16)
        self.creator_input = _CreatorInput()
        self.other_human_input = _OtherHumanInput()
        self.data_rights = _DataRightsOrders(self.other_human_input.party_id)
        self.other_human_record_query = _OtherHumanRecordQuery()
        self.creator_scenes = _CreatorScenes()
        self.creator_codex_task = _CreatorCodexTask()
        self.capability_policy = _CapabilityPolicy()
        self.creator_prompt = _CreatorPrompt()
        self.creator_export = _CreatorExport()
        self.activity_query = _CreatorActivityQuery()
        self.life_record_query = _LifeRecordQuery()
        self.maintenance_query = _CreatorMaintenanceQuery()
        self.relationship_query = _CreatorRelationshipQuery()
        self.emergency_wake = _EmergencyWake(self.maintenance_query)

    def test_every_creator_operation_phase_has_an_explicit_projection(self) -> None:
        acceptance = self.creator_input.acceptance
        expected_status = {
            CreatorOperationPhase.ACCEPTED: "accepted",
            CreatorOperationPhase.CONTEXT_PREPARING: "waiting",
            CreatorOperationPhase.CONTEXT_PREPARED: "waiting",
            CreatorOperationPhase.MODEL_CALLING: "waiting",
            CreatorOperationPhase.MODEL_RETURNED: "waiting",
            CreatorOperationPhase.CANDIDATE_VALIDATING: "waiting",
            CreatorOperationPhase.CANDIDATE_VALIDATED: "waiting",
            CreatorOperationPhase.CANDIDATE_REJECTED: "rejected",
            CreatorOperationPhase.SUBJECT_COMMITTING: "waiting",
            CreatorOperationPhase.RESPONSE_ADMISSION: "waiting",
            CreatorOperationPhase.RESPONSE_ACCEPTED: "accepted",
            CreatorOperationPhase.EFFECT_REGISTRATION: "waiting",
            CreatorOperationPhase.EFFECT_REGISTERED: "accepted",
            CreatorOperationPhase.EFFECT_DISPATCHING: "waiting",
            CreatorOperationPhase.EFFECT_COMPLETED: "completed",
            CreatorOperationPhase.EFFECT_FAILED: "failed",
            CreatorOperationPhase.EFFECT_UNKNOWN: "unknown",
            CreatorOperationPhase.EFFECT_CANCELLED: "rejected",
            CreatorOperationPhase.CODEX_CAPABILITY_DECISION: "waiting",
            CreatorOperationPhase.CODEX_DISPATCHING: "waiting",
            CreatorOperationPhase.CODEX_VERIFYING: "waiting",
            CreatorOperationPhase.CODEX_RESULT_ACCEPTANCE: "waiting",
            CreatorOperationPhase.CODEX_RESULT_REJECTED: "rejected",
            CreatorOperationPhase.CODEX_COMPLETED: "completed",
            CreatorOperationPhase.CODEX_FAILED: "failed",
            CreatorOperationPhase.CODEX_UNKNOWN: "unknown",
            CreatorOperationPhase.CODEX_CANCELLED: "rejected",
            CreatorOperationPhase.FORMAL_DECLINED: "completed",
            CreatorOperationPhase.FORMAL_NO_ACTION: "completed",
            CreatorOperationPhase.RESPONSE_UNAUTHORIZED: "rejected",
            CreatorOperationPhase.RESPONSE_UNAVAILABLE: "unavailable",
            CreatorOperationPhase.RESPONSE_FAILED: "failed",
            CreatorOperationPhase.APPLIED: "applied",
            CreatorOperationPhase.COMPLETED: "completed",
            CreatorOperationPhase.DEFERRED: "waiting",
            CreatorOperationPhase.NEED_INFORMATION: "waiting",
            CreatorOperationPhase.STALE_CONFLICT: "rejected",
            CreatorOperationPhase.FAILED: "failed",
        }
        completion_kind = {
            CreatorOperationPhase.ACCEPTED: "cognition",
            CreatorOperationPhase.CONTEXT_PREPARING: "cognition",
            CreatorOperationPhase.CONTEXT_PREPARED: "cognition",
            CreatorOperationPhase.MODEL_CALLING: "cognition",
            CreatorOperationPhase.MODEL_RETURNED: "cognition",
            CreatorOperationPhase.CANDIDATE_VALIDATING: "cognition",
            CreatorOperationPhase.CANDIDATE_VALIDATED: "cognition",
            CreatorOperationPhase.CANDIDATE_REJECTED: "cognition",
            CreatorOperationPhase.SUBJECT_COMMITTING: "cognition",
            CreatorOperationPhase.RESPONSE_ADMISSION: "response_effect",
            CreatorOperationPhase.RESPONSE_ACCEPTED: "response_effect",
            CreatorOperationPhase.EFFECT_REGISTRATION: "response_effect",
            CreatorOperationPhase.EFFECT_REGISTERED: "response_effect",
            CreatorOperationPhase.EFFECT_DISPATCHING: "response_effect",
            CreatorOperationPhase.EFFECT_COMPLETED: "response_effect",
            CreatorOperationPhase.EFFECT_FAILED: "response_effect",
            CreatorOperationPhase.EFFECT_UNKNOWN: "response_effect",
            CreatorOperationPhase.EFFECT_CANCELLED: "response_effect",
            CreatorOperationPhase.CODEX_CAPABILITY_DECISION: "codex_effect",
            CreatorOperationPhase.CODEX_DISPATCHING: "codex_effect",
            CreatorOperationPhase.CODEX_VERIFYING: "codex_effect",
            CreatorOperationPhase.CODEX_RESULT_ACCEPTANCE: "codex_effect",
            CreatorOperationPhase.CODEX_RESULT_REJECTED: "codex_effect",
            CreatorOperationPhase.CODEX_COMPLETED: "codex_effect",
            CreatorOperationPhase.CODEX_FAILED: "codex_effect",
            CreatorOperationPhase.CODEX_UNKNOWN: "codex_effect",
            CreatorOperationPhase.CODEX_CANCELLED: "codex_effect",
            CreatorOperationPhase.FORMAL_DECLINED: "formal_decline",
            CreatorOperationPhase.FORMAL_NO_ACTION: "formal_no_action",
            CreatorOperationPhase.RESPONSE_UNAUTHORIZED: "response_effect",
            CreatorOperationPhase.RESPONSE_UNAVAILABLE: "response_effect",
            CreatorOperationPhase.RESPONSE_FAILED: "response_effect",
            CreatorOperationPhase.APPLIED: "subject_change",
            CreatorOperationPhase.COMPLETED: "no_change",
            CreatorOperationPhase.DEFERRED: "cognition",
            CreatorOperationPhase.NEED_INFORMATION: "cognition",
            CreatorOperationPhase.STALE_CONFLICT: "cognition",
            CreatorOperationPhase.FAILED: "cognition",
        }
        effect_phases = {
            CreatorOperationPhase.EFFECT_REGISTERED,
            CreatorOperationPhase.EFFECT_DISPATCHING,
            CreatorOperationPhase.EFFECT_COMPLETED,
            CreatorOperationPhase.EFFECT_FAILED,
            CreatorOperationPhase.EFFECT_UNKNOWN,
            CreatorOperationPhase.EFFECT_CANCELLED,
            CreatorOperationPhase.CODEX_DISPATCHING,
            CreatorOperationPhase.CODEX_VERIFYING,
            CreatorOperationPhase.CODEX_RESULT_ACCEPTANCE,
            CreatorOperationPhase.CODEX_RESULT_REJECTED,
            CreatorOperationPhase.CODEX_COMPLETED,
            CreatorOperationPhase.CODEX_FAILED,
            CreatorOperationPhase.CODEX_UNKNOWN,
            CreatorOperationPhase.CODEX_CANCELLED,
        }
        failure_phases = {
            CreatorOperationPhase.RESPONSE_UNAUTHORIZED,
            CreatorOperationPhase.RESPONSE_UNAVAILABLE,
            CreatorOperationPhase.RESPONSE_FAILED,
            CreatorOperationPhase.EFFECT_FAILED,
            CreatorOperationPhase.EFFECT_UNKNOWN,
            CreatorOperationPhase.CODEX_FAILED,
            CreatorOperationPhase.CODEX_UNKNOWN,
        }

        self.assertEqual(set(expected_status), set(CreatorOperationPhase))
        self.assertEqual(set(completion_kind), set(CreatorOperationPhase))
        for phase in CreatorOperationPhase:
            failure_code = None
            if phase is CreatorOperationPhase.FAILED:
                failure_code = "MODEL-FAILED"
            elif phase in {
                CreatorOperationPhase.CANDIDATE_REJECTED,
                CreatorOperationPhase.CODEX_RESULT_REJECTED,
            }:
                failure_code = "CANDIDATE-REJECTED"
            elif phase is CreatorOperationPhase.STALE_CONFLICT:
                failure_code = "CONFLICT_SUBJECT_STATE_STALE"
            elif phase in failure_phases:
                failure_code = "PROJECTION-FAILED"
            operation = CreatorOperation(
                acceptance,
                phase,
                failure_code=failure_code,
                subject_version=2 if phase is CreatorOperationPhase.APPLIED else None,
                effect_ref=uuid7() if phase in effect_phases else None,
            )
            with self.subTest(phase=phase.value):
                wire = operation_wire(operation)
                details = cast(dict[str, object], wire["details"])
                self.assertIsInstance(details, dict)
                self.assertEqual(wire["status"], expected_status[phase])
                self.assertEqual(details["projection_version"], "creator-operation.v2")
                self.assertEqual(
                    details["operation_ref"], str(acceptance.opportunity_id)
                )
                self.assertIn("stage", details)
                self.assertIn("outcome", details)
                self.assertNotIn("completion_kind", details)
                self.assertNotIn("delivery_state", details)

    def test_codex_final_result_projects_only_verified_deliverable(self) -> None:
        content, media_type = creator_visible_codex_artifact(
            EffectArtifactKind.FINAL_RESULT,
            b'{"changed_paths":["result.md"],"deliverable":"done\\n","summary":"ok"}',
            "application/json",
        )
        self.assertEqual(content, b"done\n")
        self.assertEqual(media_type, "text/plain")

    def _status(self) -> RuntimeStatusResponse:
        snapshot = self.lifecycle.snapshot()
        return RuntimeStatusResponse(
            contract_version="1.0",
            environment_id=snapshot.environment_id,
            runtime_state=snapshot.runtime_state,
            readiness=snapshot.readiness,
            reason_codes=list(snapshot.reason_codes),
            observed_at=snapshot.observed_at,
        )

    async def _qq_health(self) -> QQChannelHealthResponse:
        return QQChannelHealthResponse(
            contract_version="1.0",
            projection_version="creator-channel-health.v2",
            channel="qq",
            driver="napcat",
            state="ready",
            ingress_ready=True,
            api_reachable=True,
            account_online=True,
            account_matches=True,
            webui_url="http://127.0.0.1:6099/webui/",
            observed_at="2026-08-14T08:00:00.000000Z",
            reason_codes=[],
        )

    def _app(self, *, sessions: bool = True):
        async def started() -> None:
            self.lifecycle.start()
            self.lifecycle.complete_startup(("TEST_BLOCKER",))

        async def stopping() -> None:
            self.lifecycle.drain()
            self.lifecycle.stop()

        return create_runtime_app(
            readiness=lambda: self.lifecycle.snapshot().readiness,
            runtime_status=self._status,
            qq_channel_health=self._qq_health,
            assets=self.assets,
            browser_sessions=self.sessions if sessions else None,
            expected_authority=AUTHORITY,
            request_body_max_bytes=1024,
            on_started=started,
            on_stopping=stopping,
            creator_scenes=self.creator_scenes,
            scene_timeline_query=_SceneTimelineQuery(),
            creator_activity_query=cast(Any, self.activity_query),
            life_record_query=self.life_record_query,
            creator_life_material_query=self.life_record_query,
            creator_memory_query=cast(Any, self.life_record_query),
            creator_maintenance_query=self.maintenance_query,
            creator_relationship_query=cast(Any, self.relationship_query),
            creator_emergency_wake=self.emergency_wake,
            creator_events=self.events,
            creator_input=self.creator_input,
            other_human_input=self.other_human_input,
            other_human_record_query=self.other_human_record_query,
            codex_task_admission=self.creator_codex_task,
            creator_operations=self.creator_input,
            creator_prompt=self.creator_prompt,
            creator_export=self.creator_export,
            data_rights=self.data_rights,
            capability_policy=self.capability_policy,
        )

    @staticmethod
    def _browser_headers(token: str | None = None) -> dict[str, str]:
        headers = {
            "Origin": f"http://{AUTHORITY}",
            "Sec-Fetch-Site": "same-origin",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Dest": "empty",
        }
        if token is not None:
            headers["Authorization"] = f"Bearer {token}"
        return headers

    def _connect_browser(self, client: TestClient) -> str:
        response = client.post(
            "/v1/browser-sessions",
            headers=self._browser_headers(),
            content=b"",
        )
        self.assertEqual(response.status_code, 200)
        return str(response.json()["browser_session_token"])

    def test_local_other_human_party_scene_and_input_are_role_scoped(self) -> None:
        with TestClient(self._app(), base_url=f"http://{AUTHORITY}") as client:
            wrong_role = client.post(
                "/v1/local/other-humans/parties",
                json={
                    "party_key": "friend-1",
                    "display_label": "朋友",
                    "role": "creator",
                },
            )
            self.assertEqual(wrong_role.status_code, 400)

            party = client.post(
                "/v1/local/other-humans/parties",
                json={
                    "party_key": "friend-1",
                    "display_label": "朋友",
                    "role": "other_human",
                },
            )
            self.assertEqual(party.status_code, 201)
            self.assertEqual(party.json()["identity_assurance"], "caller_declared")

            scene = client.put(
                "/v1/local/other-humans/friend-1/scenes/default",
                json={"status": "open"},
            )
            self.assertEqual(scene.status_code, 200)
            accepted = client.post(
                "/v1/local/other-humans/friend-1/scenes/default/messages",
                headers={"Idempotency-Key": "message-1"},
                json={"message": "你好"},
            )
            self.assertEqual(accepted.status_code, 202)
            self.assertTrue(accepted.json()["newly_accepted"])
            self.assertIsInstance(
                self.other_human_input.commands[-1], OtherHumanInputCommand
            )

            duplicate = client.post(
                "/v1/local/other-humans/friend-1/scenes/default/messages",
                headers={"Idempotency-Key": "message-1"},
                json={"message": "你好"},
            )
            self.assertEqual(duplicate.status_code, 202)
            self.assertFalse(duplicate.json()["newly_accepted"])
            mismatch = client.post(
                "/v1/local/other-humans/friend-1/scenes/default/messages",
                headers={"Idempotency-Key": "message-1"},
                json={"message": "不同内容"},
            )
            self.assertEqual(mismatch.status_code, 409)
            cross_party = client.post(
                "/v1/local/other-humans/stranger/scenes/default/messages",
                headers={"Idempotency-Key": "message-2"},
                json={"message": "不应接纳"},
            )
            self.assertEqual(cross_party.status_code, 404)
            closed = client.put(
                "/v1/local/other-humans/friend-1/scenes/default",
                json={"status": "closed"},
            )
            self.assertEqual(closed.status_code, 200)
            after_close = client.post(
                "/v1/local/other-humans/friend-1/scenes/default/messages",
                headers={"Idempotency-Key": "message-3"},
                json={"message": "关闭后输入"},
            )
            self.assertEqual(after_close.status_code, 404)

    def test_creator_reads_other_human_records_by_party_and_scene(self) -> None:
        with TestClient(self._app(), base_url=f"http://{AUTHORITY}") as client:
            session = client.post(
                "/v1/browser-sessions",
                headers=self._browser_headers(),
                content=b"",
            )
            headers = self._browser_headers(session.json()["browser_session_token"])
            parties = client.get("/v1/other-human-records?limit=20", headers=headers)
            self.assertEqual(parties.status_code, 200)
            party = parties.json()["items"][0]
            self.assertEqual(party["display_label"], "朋友")
            scenes = client.get(
                f"/v1/other-human-records/{party['party_id']}/scenes?limit=20",
                headers=headers,
            )
            self.assertEqual(scenes.status_code, 200)
            scene_id = scenes.json()["items"][0]["scene_id"]
            timeline = client.get(
                f"/v1/other-human-records/{party['party_id']}/scenes/{scene_id}/timeline?limit=50",
                headers=headers,
            )
            self.assertEqual(timeline.status_code, 200)
            self.assertEqual(timeline.json()["items"][0]["text"], "你好")
            self.assertEqual(timeline.json()["items"][0]["direction"], "received")

    def test_health_and_static_surface_are_exact(self) -> None:
        with TestClient(self._app(), base_url=f"http://{AUTHORITY}") as client:
            live = client.get("/health/live")
            ready = client.get("/health/ready")
            redirect = client.get("/ui", follow_redirects=False)
            index = client.get("/ui/")
            asset = client.get("/ui/assets/app-a1.js")

            self.assertEqual(live.json(), {"status": "alive"})
            self.assertEqual(ready.status_code, 503)
            self.assertEqual(redirect.status_code, 308)
            self.assertEqual(index.status_code, 200)
            self.assertEqual(asset.status_code, 200)
            self.assertNotIn("access-control-allow-origin", index.headers)
            self.assertEqual(client.get("/docs").status_code, 404)
            self.assertEqual(client.get("/openapi.json").status_code, 404)
        self.assertEqual(self.lifecycle.snapshot().runtime_state.value, "stopped")

    def test_capability_request_list_and_decision_are_session_bound(self) -> None:
        with TestClient(self._app(), base_url=f"http://{AUTHORITY}") as client:
            session = client.post(
                "/v1/browser-sessions",
                headers=self._browser_headers(),
                content=b"",
            )
            token = session.json()["browser_session_token"]
            page = client.get(
                "/v1/capability-requests?limit=50",
                headers=self._browser_headers(token),
            )
            self.assertEqual(page.status_code, 200)
            self.assertEqual(len(page.json()["items"]), 1)
            decision = client.post(
                f"/v1/capability-requests/{self.capability_policy.request_id}/decision",
                headers=self._browser_headers(token),
                json={
                    "contract_version": "1.0",
                    "decision_id": str(uuid7()),
                    "expected_request_version": 1,
                    "decision": "deny",
                },
            )
            self.assertEqual(decision.status_code, 200)
            self.assertEqual(decision.json()["status"], "applied")
            self.assertEqual(decision.json()["state_version"], 2)
            self.assertEqual(len(self.capability_policy.commands), 1)
            rejected = client.post(
                f"/v1/capability-requests/{self.capability_policy.request_id}/decision",
                headers={**self._browser_headers(token), "Origin": "http://invalid"},
                json={
                    "contract_version": "1.0",
                    "decision_id": str(uuid7()),
                    "expected_request_version": 1,
                    "decision": "deny",
                },
            )
            self.assertEqual(rejected.status_code, 403)

    def test_creator_prompt_create_revise_stale_and_deactivate(self) -> None:
        with TestClient(self._app(), base_url=f"http://{AUTHORITY}") as client:
            session = client.post(
                "/v1/browser-sessions",
                headers=self._browser_headers(),
                content=b"",
            )
            token = session.json()["browser_session_token"]
            headers = self._browser_headers(token)

            initial = client.get(
                "/v1/prompts/creator-guidance",
                headers=headers,
            )
            created = client.put(
                "/v1/prompts/creator-guidance",
                headers=headers,
                json={
                    "contract_version": "1.0",
                    "expected_revision_id": None,
                    "content": "请在形成结论前区分事实与推测。",
                },
            )
            first_revision = created.json()["current_revision_id"]
            revised = client.put(
                "/v1/prompts/creator-guidance",
                headers=headers,
                json={
                    "contract_version": "1.0",
                    "expected_revision_id": first_revision,
                    "content": "请区分事实、推测与仍然未知的部分。",
                },
            )
            stale = client.put(
                "/v1/prompts/creator-guidance",
                headers=headers,
                json={
                    "contract_version": "1.0",
                    "expected_revision_id": first_revision,
                    "content": "这条旧版本写入不应生效。",
                },
            )
            deactivated = client.post(
                "/v1/prompts/creator-guidance/deactivation",
                headers=headers,
                json={
                    "contract_version": "1.0",
                    "expected_revision_id": revised.json()["current_revision_id"],
                },
            )
            unauthenticated = client.get(
                "/v1/prompts/creator-guidance",
                headers=self._browser_headers(),
            )
            wrong_origin = client.put(
                "/v1/prompts/creator-guidance",
                headers={**headers, "Origin": "http://invalid"},
                json={
                    "contract_version": "1.0",
                    "expected_revision_id": deactivated.json()["current_revision_id"],
                    "content": "不能越过浏览器边界。",
                },
            )

        self.assertEqual(initial.status_code, 200)
        self.assertIsNone(initial.json()["current_revision_id"])
        self.assertEqual(created.status_code, 200)
        self.assertEqual(created.json()["revision_kind"], "created")
        self.assertEqual(revised.json()["revision_no"], 2)
        self.assertEqual(revised.json()["previous_revision_id"], first_revision)
        self.assertEqual(stale.status_code, 409)
        self.assertEqual(deactivated.status_code, 200)
        self.assertEqual(deactivated.json()["status"], "inactive")
        self.assertEqual(deactivated.json()["revision_kind"], "deactivated")
        self.assertEqual(deactivated.json()["revision_no"], 3)
        self.assertEqual(unauthenticated.status_code, 401)
        self.assertEqual(wrong_origin.status_code, 403)

    def test_creator_local_export_is_session_bound_and_queryable(self) -> None:
        with TestClient(self._app(), base_url=f"http://{AUTHORITY}") as client:
            session = client.post(
                "/v1/browser-sessions",
                headers=self._browser_headers(),
                content=b"",
            )
            headers = {
                **self._browser_headers(session.json()["browser_session_token"]),
                "Idempotency-Key": "export-request-1",
            }
            exported = client.post(
                "/v1/exports",
                headers=headers,
                json={
                    "contract_version": "1.0",
                    "directory_name": "creator-export-20260808",
                },
            )
            queried = client.get(
                f"/v1/exports/{exported.json()['export_id']}",
                headers=self._browser_headers(session.json()["browser_session_token"]),
            )
            invalid = client.post(
                "/v1/exports",
                headers=headers,
                json={"contract_version": "1.0", "directory_name": "../escape"},
            )
            wrong_origin = client.post(
                "/v1/exports",
                headers={**headers, "Origin": "http://invalid"},
                json={"contract_version": "1.0", "directory_name": "blocked"},
            )

        self.assertEqual(exported.status_code, 201)
        self.assertEqual(exported.json()["status"], "completed")
        self.assertEqual(exported.json()["segment_count"], 39)
        self.assertEqual(queried.status_code, 200)
        self.assertEqual(queried.json()["export_id"], exported.json()["export_id"])
        self.assertEqual(invalid.status_code, 400)
        self.assertEqual(wrong_origin.status_code, 403)
        self.assertEqual(len(self.creator_export.commands), 1)

    def test_creator_and_other_human_data_rights_are_requester_scoped(self) -> None:
        with TestClient(self._app(), base_url=f"http://{AUTHORITY}") as client:
            session = client.post(
                "/v1/browser-sessions",
                headers=self._browser_headers(),
                content=b"",
            )
            creator_headers = {
                **self._browser_headers(session.json()["browser_session_token"]),
                "Idempotency-Key": "creator-stop-use-1",
            }
            creator_order = client.post(
                "/v1/data-rights/orders",
                headers=creator_headers,
                json={"contract_version": "1.0", "order_kind": "stop_use"},
            )
            creator_repeat = client.post(
                "/v1/data-rights/orders",
                headers=creator_headers,
                json={"contract_version": "1.0", "order_kind": "stop_use"},
            )
            creator_query = client.get(
                f"/v1/data-rights/orders/{creator_order.json()['order_id']}",
                headers=self._browser_headers(session.json()["browser_session_token"]),
            )
            other_order = client.post(
                "/v1/local/other-humans/friend-1/data-rights/orders",
                headers={"Idempotency-Key": "friend-delete-1"},
                json={"order_kind": "delete_related"},
            )
            other_query = client.get(
                "/v1/local/other-humans/friend-1/data-rights/orders/"
                f"{other_order.json()['order_id']}"
            )
            creator_results = client.get(
                "/v1/data-rights/orders",
                headers=self._browser_headers(session.json()["browser_session_token"]),
            )
            creator_reads_other = client.get(
                f"/v1/data-rights/orders/{other_order.json()['order_id']}",
                headers=self._browser_headers(session.json()["browser_session_token"]),
            )
            other_results = client.get(
                "/v1/local/other-humans/friend-1/data-rights/orders"
            )
            wrong_party = client.get(
                "/v1/local/other-humans/stranger/data-rights/orders/"
                f"{other_order.json()['order_id']}"
            )

        self.assertEqual(creator_order.status_code, 201)
        self.assertEqual(creator_order.json()["scope_kind"], "party_local_data")
        self.assertEqual(creator_order.json()["execution_status"], "not_required")
        self.assertEqual(creator_repeat.status_code, 200)
        self.assertFalse(creator_repeat.json()["newly_created"])
        self.assertEqual(creator_query.status_code, 200)
        self.assertEqual(other_order.status_code, 201)
        self.assertEqual(other_order.json()["execution_status"], "pending")
        self.assertIsNone(other_order.json()["completed_at"])
        self.assertEqual(other_query.status_code, 200)
        self.assertEqual(len(creator_results.json()["orders"]), 2)
        self.assertEqual(creator_reads_other.json()["requester_kind"], "other_human")
        self.assertEqual(len(other_results.json()["orders"]), 1)
        self.assertEqual(
            other_results.json()["orders"][0]["requester_kind"], "other_human"
        )
        self.assertEqual(wrong_party.status_code, 404)

    def test_same_origin_browser_connects_without_login(self) -> None:
        with TestClient(self._app(), base_url=f"http://{AUTHORITY}") as client:
            established = client.post(
                "/v1/browser-sessions",
                headers=self._browser_headers(),
                content=b"",
            )
            self.assertEqual(established.status_code, 200)
            token = established.json()["browser_session_token"]
            self.assertEqual(established.json()["default_scene_key"], "default")

            current = client.get(
                "/v1/browser-sessions/current",
                headers=self._browser_headers(token),
            )
            status = client.get(
                "/v1/runtime/status",
                headers=self._browser_headers(token),
            )
            qq_status = client.get(
                "/v1/channels/qq/status",
                headers=self._browser_headers(token),
            )

        self.assertEqual(current.status_code, 200)
        self.assertEqual(current.json()["creator_party_id"], CREATOR_ID)
        self.assertEqual(current.json()["default_scene_key"], "default")
        self.assertNotIn("browser_session_token", current.json())
        self.assertEqual(status.status_code, 200)
        self.assertEqual(status.json()["runtime_state"], "blocked")
        self.assertEqual(qq_status.status_code, 200)
        self.assertEqual(qq_status.json()["state"], "ready")
        self.assertNotIn("account_id", qq_status.json())

    def test_timeline_is_authenticated_and_query_parameters_are_exact(self) -> None:
        with TestClient(self._app(), base_url=f"http://{AUTHORITY}") as client:
            established = client.post(
                "/v1/browser-sessions",
                headers=self._browser_headers(),
                content=b"",
            )
            token = established.json()["browser_session_token"]
            timeline = client.get(
                "/v1/scenes/default/timeline?limit=50",
                headers=self._browser_headers(token),
            )
            duplicate = client.get(
                "/v1/scenes/default/timeline?limit=50&limit=51",
                headers=self._browser_headers(token),
            )
            unrelated = client.get(
                "/v1/runtime/status?limit=50",
                headers=self._browser_headers(token),
            )

        self.assertEqual(
            timeline.json(),
            {
                "contract_version": "1.0",
                "projection_version": "scene-timeline.v5",
                "scene_key": "default",
                "items": [],
            },
        )
        self.assertEqual(duplicate.status_code, 400)
        self.assertEqual(unrelated.status_code, 400)

    def test_creator_can_create_select_close_and_reopen_named_scene(self) -> None:
        with TestClient(self._app(), base_url=f"http://{AUTHORITY}") as client:
            session = client.post(
                "/v1/browser-sessions",
                headers=self._browser_headers(),
                content=b"",
            )
            token = session.json()["browser_session_token"]
            headers = self._browser_headers(token)
            created = client.post(
                "/v1/scenes",
                headers=headers,
                json={"contract_version": "1.0", "scene_key": "night-talk"},
            )
            listed = client.get("/v1/scenes", headers=headers)
            closed = client.post("/v1/scenes/night-talk/close", headers=headers)
            reopened = client.post("/v1/scenes/night-talk/reopen", headers=headers)
            message = client.post(
                "/v1/scenes/night-talk/messages",
                headers={**headers, "Idempotency-Key": "scene-message-1"},
                json={"contract_version": "1.0", "message": "只属于夜谈场合"},
            )
            default_close = client.post("/v1/scenes/default/close", headers=headers)

        self.assertEqual(created.status_code, 201)
        self.assertEqual(created.json()["scene_key"], "night-talk")
        self.assertEqual(
            [scene["scene_key"] for scene in listed.json()["scenes"]],
            ["default", "night-talk"],
        )
        self.assertEqual(closed.json()["status"], "closed")
        self.assertEqual(reopened.json()["status"], "open")
        self.assertEqual(message.status_code, 202)
        self.assertEqual(self.creator_input.commands[-1].scene_key, "night-talk")
        self.assertEqual(default_close.status_code, 400)

    def test_activity_overview_and_timeline_are_read_only_and_session_bound(
        self,
    ) -> None:
        with TestClient(self._app(), base_url=f"http://{AUTHORITY}") as client:
            session = client.post(
                "/v1/browser-sessions",
                headers=self._browser_headers(),
                content=b"",
            )
            token = session.json()["browser_session_token"]
            activities = client.get(
                "/v1/activities",
                headers=self._browser_headers(token),
            )
            timeline = client.get(
                f"/v1/activities/{self.activity_query.activity_id}/timeline",
                headers=self._browser_headers(token),
            )
            missing = client.get(
                f"/v1/activities/{uuid7()}/timeline",
                headers=self._browser_headers(token),
            )
            unauthenticated = client.get(
                "/v1/activities",
                headers=self._browser_headers(),
            )

        self.assertEqual(activities.status_code, 200)
        self.assertEqual(activities.json()["projection_version"], "creator-activity.v1")
        self.assertEqual(activities.json()["items"][0]["status"], "ready")
        self.assertNotIn("resumption_cue", activities.text)
        self.assertEqual(timeline.status_code, 200)
        self.assertEqual(timeline.json()["items"][0]["event_kind"], "created")
        self.assertEqual(missing.status_code, 404)
        self.assertEqual(unauthenticated.status_code, 401)

    def test_exact_life_query_and_memory_history_do_not_masquerade_as_recall(
        self,
    ) -> None:
        with TestClient(self._app(), base_url=f"http://{AUTHORITY}") as client:
            session = client.post(
                "/v1/browser-sessions",
                headers=self._browser_headers(),
                content=b"",
            )
            token = session.json()["browser_session_token"]
            records = client.get(
                "/v1/life-records?kind=memory&q=%E6%97%A7%E7%90%86%E8%A7%A3&limit=20",
                headers=self._browser_headers(token),
            )
            memories = client.get(
                "/v1/memories?limit=20",
                headers=self._browser_headers(token),
            )
            timeline = client.get(
                f"/v1/memories/{self.life_record_query.memory_id}/timeline?limit=20",
                headers=self._browser_headers(token),
            )
            invalid = client.get(
                "/v1/life-records?kind=secret",
                headers=self._browser_headers(token),
            )
            missing = client.get(
                f"/v1/memories/{uuid7()}/timeline?limit=20",
                headers=self._browser_headers(token),
            )

        self.assertEqual(records.status_code, 200)
        self.assertEqual(records.json()["retrieval_kind"], "creator_view")
        self.assertFalse(records.json()["items"][0]["naturally_recallable"])
        request = self.life_record_query.requests[0]
        self.assertIs(request.actor, LifeRecordActor.CREATOR)
        self.assertEqual(request.record_kind, LifeRecordKind("memory"))
        self.assertEqual(request.query_text, "旧理解")
        self.assertEqual(memories.json()["items"][0]["accessibility"], "forgotten")
        self.assertEqual(timeline.json()["items"][0]["revision_kind"], "forgotten")
        self.assertEqual(invalid.status_code, 400)
        self.assertEqual(missing.status_code, 404)

    def test_life_material_detail_is_server_filtered_and_never_leaks_on_failure(
        self,
    ) -> None:
        with TestClient(self._app(), base_url=f"http://{AUTHORITY}") as client:
            session = client.post(
                "/v1/browser-sessions",
                headers=self._browser_headers(),
                content=b"",
            )
            token = session.json()["browser_session_token"]
            visible = client.get(
                f"/v1/materials/{self.life_record_query.material_id}",
                headers=self._browser_headers(token),
            )
            hidden = client.get(
                f"/v1/materials/{uuid7()}",
                headers=self._browser_headers(token),
            )
            invalid = client.get(
                "/v1/materials/not-a-uuid",
                headers=self._browser_headers(token),
            )
            unauthenticated = client.get(
                f"/v1/materials/{self.life_record_query.material_id}",
                headers=self._browser_headers(),
            )
            self.life_record_query.material_unavailable = True
            unavailable = client.get(
                f"/v1/materials/{self.life_record_query.material_id}",
                headers=self._browser_headers(token),
            )

        self.assertEqual(visible.status_code, 200)
        self.assertEqual(
            visible.json()["projection_version"], "creator-life-material.v1"
        )
        self.assertEqual(visible.json()["privacy_status"], "creator_visible")
        self.assertEqual(visible.json()["body"], "这段正文经过服务端可见性授权。")
        self.assertEqual(visible.headers["cache-control"], "no-store")
        for forbidden in ("owner_party_id", "artifact_id", "body_digest"):
            self.assertNotIn(forbidden, visible.text)
        self.assertEqual(hidden.status_code, 404)
        self.assertEqual(invalid.status_code, 404)
        self.assertEqual(
            hidden.json()["error"]["code"], invalid.json()["error"]["code"]
        )
        self.assertEqual(unauthenticated.status_code, 401)
        self.assertEqual(unavailable.status_code, 503)
        self.assertNotIn("这段正文经过服务端可见性授权。", unavailable.text)

    def test_relationship_projection_and_boundary_expression_are_session_bound(
        self,
    ) -> None:
        with TestClient(self._app(), base_url=f"http://{AUTHORITY}") as client:
            session = client.post(
                "/v1/browser-sessions",
                headers=self._browser_headers(),
                content=b"",
            )
            token = session.json()["browser_session_token"]
            headers = self._browser_headers(token)
            current = client.get(
                "/v1/relationships/current",
                headers=headers,
            )
            timeline = client.get(
                (
                    "/v1/relationships/"
                    f"{self.relationship_query.relationship_id}/timeline"
                ),
                headers=headers,
            )
            missing = client.get(
                f"/v1/relationships/{uuid7()}/timeline",
                headers=headers,
            )
            accepted = client.post(
                "/v1/relationships/current/boundaries",
                headers={**headers, "Idempotency-Key": "boundary-1"},
                json={
                    "contract_version": "1.0",
                    "kind": "contact",
                    "action": "restrict",
                    "summary": "不要在深夜联系",
                },
            )
            invalid = client.post(
                "/v1/relationships/current/boundaries",
                headers={**headers, "Idempotency-Key": "boundary-2"},
                json={
                    "contract_version": "1.0",
                    "kind": "contact",
                    "action": "end_contact",
                    "summary": "错误组合",
                },
            )
            unauthenticated = client.get(
                "/v1/relationships/current",
                headers=self._browser_headers(),
            )

        self.assertEqual(current.status_code, 200)
        self.assertEqual(
            current.json()["projection_version"],
            "creator-relationship.v2",
        )
        self.assertEqual(
            current.json()["relationship"]["current"]["boundaries"][0]["kind"],
            "contact",
        )
        self.assertNotIn("scene_key", current.text)
        self.assertNotIn("message", current.text)
        self.assertEqual(timeline.status_code, 200)
        self.assertEqual(timeline.json()["items"][0]["revision_no"], 1)
        self.assertEqual(missing.status_code, 404)
        self.assertEqual(accepted.status_code, 202)
        self.assertEqual(invalid.status_code, 400)
        self.assertEqual(unauthenticated.status_code, 401)
        command = self.creator_input.commands[-1]
        self.assertEqual(command.scene_key, "default")
        self.assertIn("不要在深夜联系", command.message)
        self.assertNotIn("scene_key", command.message)

    def test_maintenance_status_timeline_and_wake_are_session_bound(self) -> None:
        with TestClient(self._app(), base_url=f"http://{AUTHORITY}") as client:
            session = client.post(
                "/v1/browser-sessions",
                headers=self._browser_headers(),
                content=b"",
            )
            token = session.json()["browser_session_token"]
            status = client.get(
                "/v1/maintenance/status",
                headers=self._browser_headers(token),
            )
            timeline = client.get(
                f"/v1/maintenance/{self.maintenance_query.session_id}/timeline",
                headers=self._browser_headers(token),
            )
            missing = client.get(
                f"/v1/maintenance/{uuid7()}/timeline",
                headers=self._browser_headers(token),
            )
            wake = client.post(
                f"/v1/maintenance/{self.maintenance_query.session_id}/wake",
                headers=self._browser_headers(token),
            )
            unauthenticated = client.get(
                "/v1/maintenance/status",
                headers=self._browser_headers(),
            )

        self.assertEqual(status.status_code, 200)
        self.assertEqual(
            status.json()["session"]["trigger_kind"],
            "system_deadline",
        )
        self.assertEqual(status.json()["waiting_input_count"], 2)
        self.assertNotIn("memory", status.text)
        self.assertEqual(timeline.status_code, 200)
        self.assertEqual(timeline.json()["items"][0]["phase"], "self_check")
        self.assertEqual(
            timeline.json()["items"][0]["problem_summary"],
            "有一项内部责任需要后续关注。",
        )
        self.assertEqual(missing.status_code, 404)
        self.assertEqual(wake.status_code, 204)
        self.assertEqual(len(self.emergency_wake.requests), 1)
        self.assertEqual(
            self.emergency_wake.requests[0][0], self.maintenance_query.session_id
        )
        self.assertEqual(self.emergency_wake.requests[0][1].version, 7)
        self.assertEqual(unauthenticated.status_code, 401)

    def test_creator_message_acceptance_and_operation_are_authoritative(self) -> None:
        with TestClient(self._app(), base_url=f"http://{AUTHORITY}") as client:
            session = client.post(
                "/v1/browser-sessions",
                headers=self._browser_headers(),
                content=b"",
            )
            token = session.json()["browser_session_token"]
            accepted = client.post(
                "/v1/scenes/default/messages",
                headers={
                    **self._browser_headers(token),
                    "Idempotency-Key": "request-1",
                },
                json={
                    "contract_version": "1.0",
                    "message": "  exact\r\ntext  ",
                },
            )
            operation = client.get(
                accepted.json()["details"]["operation_url"],
                headers=self._browser_headers(token),
            )
            blank = client.post(
                "/v1/scenes/default/messages",
                headers={
                    **self._browser_headers(token),
                    "Idempotency-Key": "request-2",
                },
                json={"contract_version": "1.0", "message": " \r\n "},
            )
            duplicate = client.post(
                "/v1/scenes/default/messages",
                headers={
                    **self._browser_headers(token),
                    "Idempotency-Key": "request-3",
                    "Content-Type": "application/json",
                },
                content=b'{"contract_version":"1.0","message":"a","message":"b"}',
            )
            duplicate_idempotency = client.post(
                "/v1/scenes/default/messages",
                headers=[
                    *self._browser_headers(token).items(),
                    ("Idempotency-Key", "request-4"),
                    ("Idempotency-Key", "request-5"),
                    ("Content-Type", "application/json"),
                ],
                content=b'{"contract_version":"1.0","message":"valid"}',
            )
            wrong_content_type = client.post(
                "/v1/scenes/default/messages",
                headers={
                    **self._browser_headers(token),
                    "Idempotency-Key": "request-6",
                    "Content-Type": "text/plain",
                },
                content=b'{"contract_version":"1.0","message":"valid"}',
            )
            invalid_utf8 = client.post(
                "/v1/scenes/default/messages",
                headers={
                    **self._browser_headers(token),
                    "Idempotency-Key": "request-7",
                    "Content-Type": "application/json",
                },
                content=b'{"contract_version":"1.0","message":"\xff"}',
            )
            query = client.post(
                "/v1/scenes/default/messages?token=x",
                headers={
                    **self._browser_headers(token),
                    "Idempotency-Key": "request-8",
                },
                json={"contract_version": "1.0", "message": "valid"},
            )

        self.assertEqual(accepted.status_code, 202)
        self.assertEqual(accepted.json()["status"], "accepted")
        self.assertEqual(accepted.json()["custodian"], "runtime")
        self.assertEqual(operation.status_code, 200)
        self.assertEqual(operation.json()["result_ref"], accepted.json()["result_ref"])
        self.assertEqual(self.creator_input.commands[0].message, "  exact\r\ntext  ")
        self.assertEqual(blank.status_code, 400)
        self.assertEqual(duplicate.status_code, 400)
        self.assertEqual(duplicate_idempotency.status_code, 400)
        self.assertEqual(wrong_content_type.status_code, 400)
        self.assertEqual(invalid_utf8.status_code, 400)
        self.assertEqual(query.status_code, 400)

    def test_creator_codex_task_is_explicit_authenticated_intake(self) -> None:
        with TestClient(self._app(), base_url=f"http://{AUTHORITY}") as client:
            session = client.post(
                "/v1/browser-sessions",
                headers=self._browser_headers(),
                content=b"",
            )
            token = session.json()["browser_session_token"]
            accepted = client.post(
                "/v1/scenes/default/codex-tasks",
                headers={
                    **self._browser_headers(token),
                    "Idempotency-Key": "codex-task-1",
                },
                json={
                    "contract_version": "1.0",
                    "objective": "整理一份可核验的交付说明。",
                },
            )
            research = client.post(
                "/v1/scenes/default/codex-tasks",
                headers={
                    **self._browser_headers(token),
                    "Idempotency-Key": "codex-task-research-1",
                },
                json={
                    "contract_version": "1.0",
                    "objective": "查询今天的公开新闻并附来源。",
                    "model_id": "gpt-5.6-luna",
                    "reasoning_effort": "low",
                    "web_search": True,
                },
            )
            blank = client.post(
                "/v1/scenes/default/codex-tasks",
                headers={
                    **self._browser_headers(token),
                    "Idempotency-Key": "codex-task-2",
                },
                json={"contract_version": "1.0", "objective": "  \r\n"},
            )
            wrong_origin = client.post(
                "/v1/scenes/default/codex-tasks",
                headers={
                    **self._browser_headers(token),
                    "Origin": "http://localhost:45678",
                    "Idempotency-Key": "codex-task-3",
                },
                json={"contract_version": "1.0", "objective": "valid"},
            )

        self.assertEqual(accepted.status_code, 202)
        self.assertEqual(research.status_code, 202)
        self.assertEqual(accepted.json()["status"], "accepted")
        self.assertEqual(
            self.creator_codex_task.commands[0].objective,
            "整理一份可核验的交付说明。",
        )
        self.assertIs(self.creator_codex_task.commands[1].model_id, CodexModel.LUNA)
        self.assertTrue(self.creator_codex_task.commands[1].web_search)
        self.assertEqual(blank.status_code, 400)
        self.assertEqual(wrong_origin.status_code, 403)

    def test_reconnect_reuses_local_token_and_boundary_requests_are_rejected(
        self,
    ) -> None:
        with TestClient(self._app(), base_url=f"http://{AUTHORITY}") as client:
            first = client.post(
                "/v1/browser-sessions",
                headers=self._browser_headers(),
                content=b"",
            )
            reconnect = client.post(
                "/v1/browser-sessions",
                headers=self._browser_headers(),
                content=b"",
            )
            current = client.get(
                "/v1/browser-sessions/current",
                headers=self._browser_headers(first.json()["browser_session_token"]),
            )
            wrong_origin = client.post(
                "/v1/browser-sessions",
                headers={
                    **self._browser_headers(),
                    "Origin": "http://localhost:45678",
                },
                content=b"",
            )
            wrong_kind = client.get(
                "/v1/runtime/status",
                headers=self._browser_headers(CREATOR_BEARER),
            )
            proxy = client.get(
                "/health/live",
                headers={"Forwarded": "host=127.0.0.1"},
            )

        self.assertEqual(first.status_code, 200)
        self.assertEqual(reconnect.status_code, 200)
        self.assertEqual(current.status_code, 200)
        self.assertEqual(wrong_origin.status_code, 403)
        self.assertEqual(wrong_kind.status_code, 401)
        self.assertEqual(proxy.status_code, 421)

    def test_connection_ignores_body_while_other_boundary_checks_remain(self) -> None:
        headers = {
            **self._browser_headers(),
            "Content-Type": "application/json",
        }
        with TestClient(self._app(), base_url=f"http://{AUTHORITY}") as client:
            duplicate = client.post(
                "/v1/browser-sessions",
                headers=headers,
                content=b'{"ignored":"value"}',
            )
            cookie = client.get(
                "/v1/runtime/status",
                headers={
                    **self._browser_headers("browser-v1." + "a" * 43),
                    "Cookie": "x=y",
                },
            )
            query = client.get(
                "/v1/runtime/status?token=x",
                headers=self._browser_headers("browser-v1." + "a" * 43),
            )
            oversized = client.get("/health/live", headers={"Content-Length": "1025"})

        self.assertEqual(duplicate.status_code, 200)
        self.assertEqual(cookie.status_code, 403)
        self.assertEqual(query.status_code, 400)
        self.assertEqual(oversized.status_code, 413)

    def test_event_stream_validates_boundary_accept_and_replay_header(self) -> None:
        with TestClient(self._app(), base_url=f"http://{AUTHORITY}") as client:
            session = client.post(
                "/v1/browser-sessions",
                headers=self._browser_headers(),
                content=b"",
            )
            token = session.json()["browser_session_token"]
            base = self._browser_headers(token)
            wrong_accept = client.get(
                "/v1/scenes/default/events",
                headers=base,
            )
            query = client.get(
                "/v1/scenes/default/events?token=x",
                headers={**base, "Accept": "text/event-stream"},
            )
            malformed = client.get(
                "/v1/scenes/default/events",
                headers={
                    **base,
                    "Accept": "text/event-stream",
                    "Last-Event-ID": "invalid",
                },
            )
            stale = client.get(
                "/v1/scenes/default/events",
                headers={
                    **base,
                    "Accept": "text/event-stream",
                    "Last-Event-ID": f"sse-v1.{'A' * 22}.1",
                },
            )
            invisible = client.get(
                "/v1/scenes/other/events",
                headers={**base, "Accept": "text/event-stream"},
            )

        self.assertEqual(wrong_accept.status_code, 400)
        self.assertEqual(query.status_code, 400)
        self.assertEqual(malformed.status_code, 400)
        self.assertEqual(malformed.json()["error"]["code"], "INPUT_EVENT_ID_INVALID")
        self.assertEqual(stale.status_code, 409)
        self.assertEqual(stale.json()["error"]["code"], "CONFLICT_EVENT_GAP")
        self.assertEqual(invisible.status_code, 404)

    def test_host_fetch_origin_preflight_and_creator_route_matrix(self) -> None:
        ignored_body = {"ignored": "value"}
        with TestClient(self._app(), base_url=f"http://{AUTHORITY}") as client:
            host_variants = tuple(
                client.get(
                    "/health/live",
                    headers={"Host": host},
                ).status_code
                for host in (
                    "localhost:45678",
                    "127.0.0.1.:45678",
                    "[::1]:45678",
                    "127.0.0.1",
                    "127.0.0.1:80",
                )
            )
            missing_fetch = client.post(
                "/v1/browser-sessions",
                headers={
                    "Origin": f"http://{AUTHORITY}",
                    "Content-Type": "application/json",
                },
                json=ignored_body,
            )
            cross_site = client.post(
                "/v1/browser-sessions",
                headers={
                    **self._browser_headers(),
                    "Sec-Fetch-Site": "cross-site",
                },
                json=ignored_body,
            )
            preflight = client.options(
                "/v1/browser-sessions",
                headers={
                    "Origin": f"http://{AUTHORITY}",
                    "Access-Control-Request-Method": "POST",
                },
            )
        self.assertEqual(host_variants, (421, 421, 421, 421, 421))
        self.assertEqual(missing_fetch.status_code, 403)
        self.assertEqual(cross_site.status_code, 403)
        self.assertEqual(preflight.status_code, 405)
        self.assertNotIn("access-control-allow-origin", preflight.headers)

    def test_missing_session_capability_is_unavailable(self) -> None:
        with TestClient(
            self._app(sessions=False),
            base_url=f"http://{AUTHORITY}",
        ) as client:
            response = client.post(
                "/v1/browser-sessions",
                headers=self._browser_headers(),
                content=b"",
            )
        self.assertEqual(response.status_code, 503)

    def test_readiness_provider_is_never_implicitly_ready(self) -> None:
        self.assertEqual(self.lifecycle.snapshot().readiness, Readiness.NOT_READY)


if __name__ == "__main__":
    unittest.main()
