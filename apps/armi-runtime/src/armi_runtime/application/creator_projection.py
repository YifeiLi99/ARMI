from __future__ import annotations

import json
import re
import secrets
from collections.abc import Awaitable, Callable
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any, Literal, Protocol, TypedDict, assert_never, cast
from uuid import UUID, uuid7

from armi_activity.api import ActivityReadPort, ActivityViolation
from armi_attention.api import LifeViolation
from armi_codex.api import (
    CodexDelegationViolation,
    CodexModel,
    CodexReasoningEffort,
    CreatorCodexTaskAdmissionPort,
    CreatorCodexTaskCommand,
)
from armi_data_rights.api import (
    CreatorExportCommand,
    CreatorExportPort,
    CreatorExportResult,
    CreatorExportViolation,
    DataRightsOrderCommand,
    DataRightsOrderDetail,
    DataRightsOrderKind,
    DataRightsOrderPort,
    DataRightsOrderResult,
    DataRightsRetryCommand,
    DataRightsViolation,
)
from armi_effect.api import (
    EffectArtifactKind,
    EffectId,
    EffectLedgerPort,
    EffectViolation,
)
from armi_interaction.api import (
    CreatorInputAcceptance,
    CreatorInputAcceptancePort,
    CreatorInputCommand,
    CreatorInputViolation,
    CreatorOperation,
    CreatorOperationPhase,
    CreatorOperationQueryPort,
    CreatorSceneCreateCommand,
    CreatorScenePort,
    CreatorSceneStatusCommand,
    CreatorSceneView,
    OpportunityId,
    OtherHumanInputCommand,
    OtherHumanInputPort,
    OtherHumanInputViolation,
    OtherHumanPartyKey,
    OtherHumanSceneCommand,
    RegisterOtherHumanPartyCommand,
    SceneKey,
    SceneQueryViolation,
    SceneStatus,
    SceneTimelineQuery,
    SceneTimelineQueryPort,
)
from armi_kernel.application import (
    CreatorProjectionInvalidation,
    CreatorResourceKind,
    LifeRecordActor,
    LifeRecordKind,
    LifeRecordQuery,
    LifeRecordQueryPort,
    LifeRecordQueryViolation,
    LifeRecordRetrievalKind,
    OtherHumanRecordQueryPort,
    OtherHumanRecordViolation,
)
from armi_kernel.contracts import (
    AcceptedOutcome,
    AppliedOutcome,
    CompletedOutcome,
    ContractViolation,
    ErrorCategory,
    ErrorDescriptor,
    FailedOutcome,
    IdempotencyKey,
    Instant,
    OpaqueCursor,
    RejectedOutcome,
    ResultRef,
    TraceId,
    UnavailableOutcome,
    UnknownOutcome,
    WaitingOutcome,
)
from armi_material.api import CreatorLifeMaterialItem, MaterialViolation
from armi_memory.api import MemoryReadPort, MemoryViolation
from armi_prompt.api import (
    CreatorPromptDeactivateCommand,
    CreatorPromptPort,
    CreatorPromptRevisionCommand,
    CreatorPromptView,
    CreatorPromptViolation,
    PromptKind,
)
from armi_relationship.api import (
    CreatorRelationshipRevision,
    RelationshipReadPort,
    RelationshipViolation,
)
from armi_sleep.api import (
    CreatorEmergencyWakePort,
    CreatorMaintenanceQueryPort,
    CreatorMaintenanceViolation,
)
from armi_subject_state.api import SubjectSummary
from pydantic import ValidationError

from armi_runtime.application.creator_contract import (
    AcceptedOutcomeResponse,
    AppliedOutcomeResponse,
    BrowserSessionCurrentResponse,
    BrowserSessionResponse,
    CreatorActivityItemResponse,
    CreatorActivityPageResponse,
    CreatorActivityTimelineItemResponse,
    CreatorActivityTimelineResponse,
    CreatorCodexTaskRequest,
    CreatorExportRequest,
    CreatorExportResponse,
    CreatorInputRequest,
    CreatorLifeMaterialResponse,
    CreatorMaintenanceSessionResponse,
    CreatorMaintenanceStatusResponse,
    CreatorMaintenanceTimelineItemResponse,
    CreatorMaintenanceTimelineResponse,
    CreatorMemoryItemResponse,
    CreatorMemoryPageResponse,
    CreatorMemoryTimelineItemResponse,
    CreatorMemoryTimelineResponse,
    CreatorPromptDeactivateRequest,
    CreatorPromptResponse,
    CreatorPromptRevisionRequest,
    CreatorRelationshipBoundaryRequest,
    CreatorRelationshipBoundaryResponse,
    CreatorRelationshipCommitmentEventResponse,
    CreatorRelationshipCommitmentResponse,
    CreatorRelationshipCurrentResponse,
    CreatorRelationshipFactResponse,
    CreatorRelationshipIssueResolutionResponse,
    CreatorRelationshipIssueResponse,
    CreatorRelationshipItemResponse,
    CreatorRelationshipRevisionResponse,
    CreatorRelationshipTimelineResponse,
    CreatorSceneCollectionResponse,
    CreatorSceneCreateRequest,
    CreatorSceneResponse,
    DataRightsOrderCollectionResponse,
    DataRightsOrderDetailResponse,
    DataRightsOrderItemResponse,
    DataRightsOrderRequest,
    DataRightsOrderResponse,
    DataRightsTimelineItemResponse,
    EffectResponse,
    LifeRecordItemResponse,
    LifeRecordKindValue,
    LifeRecordPageResponse,
    LiveResponse,
    LiveVisionObservationRequest,
    LiveVisionObservationResponse,
    LiveVisionStatusResponse,
    LiveVoiceStatusResponse,
    OperationOutcomeResponse,
    OtherHumanPartyRecordPageResponse,
    OtherHumanPartyRecordResponse,
    OtherHumanSceneRecordPageResponse,
    OtherHumanSceneRecordResponse,
    OtherHumanTimelineRecordPageResponse,
    OtherHumanTimelineRecordResponse,
    QQChannelHealthResponse,
    Readiness,
    ReadyResponse,
    RejectedOutcomeResponse,
    RuntimeStatusResponse,
    SceneTimelineItemResponse,
    SceneTimelinePageResponse,
    SubjectComponentSummaryResponse,
    SubjectSummaryResponse,
    UnavailableOutcomeResponse,
)

from .creator_calls import creator_result
from .interaction import InteractionResult

SubjectSummaryProvider = Callable[[], Awaitable[SubjectSummary]]
SecurityEvent = Callable[[str], None]


class CreatorLifeMaterialQueryPort(Protocol):
    async def get_creator_visible(
        self, material_id: UUID
    ) -> CreatorLifeMaterialItem | None: ...


class _OutcomeArguments(TypedDict):
    trace_id: TraceId
    occurred_at: Instant


def _outcome_common() -> _OutcomeArguments:
    return _OutcomeArguments(
        trace_id=TraceId(secrets.token_hex(16)), occurred_at=Instant(datetime.now(UTC))
    )


def _rejected(
    code: str, message: str = "The request was rejected."
) -> dict[str, object]:
    category = ErrorCategory(code.partition("_")[0].lower())
    return RejectedOutcome(
        **_outcome_common(), message=message, error=ErrorDescriptor(category, code)
    ).to_wire()


def _unavailable(code: str) -> dict[str, object]:
    return UnavailableOutcome(
        **_outcome_common(),
        message="The requested local Runtime capability is unavailable.",
        error=ErrorDescriptor(ErrorCategory.DEPENDENCY, code),
    ).to_wire()


def creator_visible_codex_artifact(
    kind: EffectArtifactKind, content: bytes, media_type: str
) -> tuple[bytes, str]:
    """Project the verified final result as the Creator's actual deliverable."""
    if kind is not EffectArtifactKind.FINAL_RESULT:
        content.decode("utf-8", errors="strict")
        return (content, media_type)
    try:
        value = cast(
            object,
            json.loads(
                content.decode("utf-8", errors="strict"),
                object_pairs_hook=_strict_object_pairs,
                parse_constant=lambda _value: (_ for _ in ()).throw(
                    ValueError("non-finite JSON")
                ),
            ),
        )
        if type(value) is not dict:
            raise ValueError
        document = cast(dict[str, object], value)
        if set(document) != {"summary", "changed_paths", "deliverable"}:
            raise ValueError
        deliverable = document["deliverable"]
        if type(deliverable) is not str or not deliverable.strip():
            raise ValueError
        projected = deliverable.encode("utf-8", errors="strict")
        if len(projected) > 1024 * 1024:
            raise ValueError
        return (projected, "text/plain")
    except UnicodeDecodeError, UnicodeEncodeError, ValueError:
        raise EffectViolation("EFFECT-ARTIFACT-INTEGRITY") from None


def _scene_wire(view: CreatorSceneView) -> CreatorSceneResponse:
    return CreatorSceneResponse(
        contract_version="1.0",
        projection_version="creator-scenes.v1",
        scene_id=str(view.scene_id),
        scene_key=view.scene_key.value,
        status=view.status.value,
        opened_at=view.opened_at.to_wire(),
        closed_at=None if view.closed_at is None else view.closed_at.to_wire(),
        recent_context_boundary=None
        if view.recent_context_boundary is None
        else str(view.recent_context_boundary),
        is_default=view.is_default,
    )


def _boundary_message(call: CreatorRelationshipBoundaryRequest) -> str:
    kind = {
        "contact": "联系",
        "address": "称呼",
        "privacy": "隐私",
        "disclosure": "信息披露",
        "exit": "结束联系",
    }[call.kind]
    action = {"refuse": "拒绝", "restrict": "限制", "end_contact": "结束联系"}[
        call.action
    ]
    return f"我通过 Creator 的关系边界操作明确表达: 对于{kind}, 我选择{action}。具体说明: {call.summary}"


def _creator_prompt_response(view: CreatorPromptView) -> CreatorPromptResponse:
    return CreatorPromptResponse(
        contract_version="1.0",
        projection_version="creator-prompt.v1",
        prompt_document_id=str(view.prompt_document_id),
        prompt_kind="creator_guidance",
        status=view.status.value,
        current_revision_id=None
        if view.current_revision_id is None
        else str(view.current_revision_id),
        revision_no=view.revision_no,
        previous_revision_id=None
        if view.previous_revision_id is None
        else str(view.previous_revision_id),
        revision_kind=None if view.revision_kind is None else view.revision_kind.value,
        content=view.content,
        activated_at=None if view.activated_at is None else view.activated_at.to_wire(),
    )


def _creator_prompt_error(error: CreatorPromptViolation) -> InteractionResult:
    if error.code.startswith("CONFLICT-PROMPT-"):
        return creator_result(
            status_code=409, content=_rejected("CONFLICT_PROMPT_REVISION")
        )
    if error.code.startswith("SCOPE-PROMPT-"):
        return creator_result(
            status_code=403, content=_rejected("SCOPE_PROMPT_NOT_WRITABLE")
        )
    if error.code.startswith("CON-PROMPT-"):
        return creator_result(
            status_code=400, content=_rejected("INPUT_PROMPT_INVALID")
        )
    return creator_result(
        status_code=503, content=_unavailable("DEPENDENCY_CREATOR_PROMPT_UNAVAILABLE")
    )


def _creator_export_response(result: CreatorExportResult) -> CreatorExportResponse:
    return CreatorExportResponse(
        contract_version="1.0",
        projection_version="creator-export.v5",
        export_id=str(result.export_id),
        status=result.status.value,
        directory_name=result.directory_name,
        destination_path=result.destination_path,
        segment_count=result.segment_count,
        record_count=result.record_count,
        artifact_count=result.artifact_count,
        missing_artifact_count=result.missing_artifact_count,
        error_code=result.error_code,
        created_at=result.created_at.to_wire(),
        completed_at=None
        if result.completed_at is None
        else result.completed_at.to_wire(),
        newly_created=result.newly_created,
    )


def _creator_export_error(error: CreatorExportViolation) -> InteractionResult:
    if error.code in {
        "CREATOR-EXPORT-IDEMPOTENCY-CONFLICT",
        "CREATOR-EXPORT-DIRECTORY-EXISTS",
        "CREATOR-EXPORT-STATE",
    }:
        return creator_result(
            status_code=409, content=_rejected("CONFLICT_CREATOR_EXPORT")
        )
    if error.code in {
        "CREATOR-EXPORT-COMMAND",
        "CREATOR-EXPORT-ID",
        "CREATOR-EXPORT-PATH",
    }:
        return creator_result(
            status_code=400, content=_rejected("INPUT_CREATOR_EXPORT_INVALID")
        )
    return creator_result(
        status_code=503, content=_unavailable("DEPENDENCY_CREATOR_EXPORT_UNAVAILABLE")
    )


def _data_rights_response(result: DataRightsOrderResult) -> DataRightsOrderResponse:
    return DataRightsOrderResponse(
        contract_version="1.0",
        projection_version="data-rights-order-summary.v3",
        order_id=str(result.order_id),
        requester_party_id=str(result.requester_party_id),
        requester_kind=result.requester_kind.value,
        order_kind=result.order_kind.value,
        scope_kind=result.scope_kind.value,
        scope_party_id=str(result.scope_party_id),
        status="effective",
        execution_status=result.execution_status.value,
        request_digest=result.request_digest.value,
        effective_at=result.effective_at.to_wire(),
        completed_at=None
        if result.completed_at is None
        else result.completed_at.to_wire(),
        newly_created=result.newly_created,
    )


def _data_rights_detail_response(
    detail: DataRightsOrderDetail,
) -> DataRightsOrderDetailResponse:
    order = detail.order
    items = [
        DataRightsOrderItemResponse(
            item_id=str(item.item_id),
            target_kind=cast(Any, item.target_kind),
            required_action=cast(Any, item.required_action),
            responsible_owner=item.responsible_owner,
            result_status=item.result_status.value,
            retention_reason=cast(Any, item.retention_reason),
            created_at=item.created_at.to_wire(),
            completed_at=None
            if item.completed_at is None
            else item.completed_at.to_wire(),
            artifact_deletion_id=None
            if item.artifact_deletion_id is None
            else str(item.artifact_deletion_id),
            retryable=item.retryable,
            deletion_attempt_count=item.deletion_attempt_count,
            last_error_code=item.last_error_code,
            operator_action_required=item.operator_action_required,
        )
        for item in detail.items
    ]
    timeline = [
        DataRightsTimelineItemResponse(
            event_kind="order_effective",
            occurred_at=order.effective_at.to_wire(),
            item_id=None,
            status="effective",
        )
    ]
    timeline.extend(
        DataRightsTimelineItemResponse(
            event_kind="item_status",
            occurred_at=(item.completed_at or item.created_at).to_wire(),
            item_id=str(item.item_id),
            status=item.result_status.value,
        )
        for item in detail.items
    )
    timeline.sort(key=lambda item: (item.occurred_at, item.item_id or ""))
    return DataRightsOrderDetailResponse(
        contract_version="1.0",
        projection_version="data-rights-order-detail.v3",
        order_id=str(order.order_id),
        requester_party_id=str(order.requester_party_id),
        requester_kind=order.requester_kind.value,
        order_kind=order.order_kind.value,
        scope_kind=order.scope_kind.value,
        scope_party_id=str(order.scope_party_id),
        status="effective",
        execution_status=order.execution_status.value,
        request_digest=order.request_digest.value,
        effective_at=order.effective_at.to_wire(),
        completed_at=None
        if order.completed_at is None
        else order.completed_at.to_wire(),
        newly_created=order.newly_created,
        items=items,
        timeline=timeline,
        retention_reasons=cast(
            Any,
            sorted(
                {
                    item.retention_reason
                    for item in detail.items
                    if item.retention_reason is not None
                }
            ),
        ),
    )


def _data_rights_error(error: DataRightsViolation) -> InteractionResult:
    if error.code == "DATA-RIGHTS-REQUESTER-NOT-FOUND":
        return creator_result(
            status_code=404, content=_rejected("SCOPE_DATA_RIGHTS_REQUESTER_NOT_FOUND")
        )
    if error.code == "DATA-RIGHTS-IDEMPOTENCY-CONFLICT":
        return creator_result(
            status_code=409, content=_rejected("CONFLICT_DATA_RIGHTS_IDEMPOTENCY")
        )
    if error.code in {
        "DATA-RIGHTS-COMMAND",
        "DATA-RIGHTS-ORDER-ID",
        "DATA-RIGHTS-REQUESTER",
    }:
        return creator_result(
            status_code=400, content=_rejected("INPUT_DATA_RIGHTS_INVALID")
        )
    return creator_result(
        status_code=503, content=_unavailable("DEPENDENCY_DATA_RIGHTS_UNAVAILABLE")
    )


def _accepted_wire(acceptance: CreatorInputAcceptance) -> dict[str, object]:
    return AcceptedOutcome(
        **_outcome_common(),
        message="The Creator input is durably accepted.",
        result_ref=ResultRef(acceptance.opportunity_id.value),
        custodian="runtime",
        details={
            "interaction_id": str(acceptance.interaction_id),
            "evidence_id": str(acceptance.evidence_id),
            "opportunity_id": str(acceptance.opportunity_id),
            "operation_url": f"/v1/operations/{acceptance.opportunity_id}",
        },
    ).to_wire()


def _relationship_revision_response(
    revision: CreatorRelationshipRevision,
) -> CreatorRelationshipRevisionResponse:
    return CreatorRelationshipRevisionResponse(
        relationship_revision_id=str(revision.relationship_revision_id),
        revision_no=revision.revision_no,
        facts=[
            CreatorRelationshipFactResponse(
                fact_id=str(item.fact_id), kind=item.kind.value, summary=item.summary
            )
            for item in revision.facts
        ],
        interpretation=revision.interpretation,
        boundaries=[
            CreatorRelationshipBoundaryResponse(
                party_role=item.party_role.value,
                kind=item.kind.value,
                action=item.action.value,
                summary=item.summary,
            )
            for item in revision.boundaries
        ],
        commitments=[
            CreatorRelationshipCommitmentResponse(
                commitment_id=str(item.commitment_id),
                party_role=item.party_role.value,
                scope=item.scope,
                content=item.content,
                status=item.status.value,
                last_event_kind=item.last_event_kind.value,
                last_event_summary=item.last_event_summary,
            )
            for item in revision.commitments
        ],
        open_issues=[
            CreatorRelationshipIssueResponse(
                issue_id=str(item.issue_id),
                kind=item.kind.value,
                commitment_ids=[str(value) for value in item.commitment_ids],
                summary=item.summary,
                status=cast(Literal["open"], item.status.value),
            )
            for item in revision.open_issues
        ],
        commitment_event=None
        if revision.commitment_event is None
        else CreatorRelationshipCommitmentEventResponse(
            commitment_id=str(revision.commitment_event.commitment_id),
            kind=revision.commitment_event.kind.value,
            summary=revision.commitment_event.summary,
            related_commitment_id=None
            if revision.commitment_event.related_commitment_id is None
            else str(revision.commitment_event.related_commitment_id),
        ),
        issue_resolution=None
        if revision.issue_resolution is None
        else CreatorRelationshipIssueResolutionResponse(
            issue_id=str(revision.issue_resolution.issue_id),
            status="resolved",
            resolution_summary=revision.issue_resolution.resolution_summary,
        ),
        status=revision.status.value,
        occurred_at=Instant(revision.occurred_at).to_wire(),
    )


def _operation_outcome_wire(operation: CreatorOperation) -> dict[str, object]:
    if operation.failure_code in {
        "ACTION-RUNTIME-INTERRUPTED",
        "COGNITION-RUNTIME-INTERRUPTED",
    }:
        return FailedOutcome(
            **_outcome_common(),
            message="This conversation ended when the Runtime stopped. Any completed changes remain; unfinished replies will not be resent.",
            error=ErrorDescriptor(
                ErrorCategory.DEPENDENCY, "DEPENDENCY_RUNTIME_INTERRUPTED"
            ),
        ).to_wire()
    if operation.failure_code == "ACTION-EFFECT-DESTINATION-UNAVAILABLE":
        return FailedOutcome(
            **_outcome_common(),
            message="The reply destination is no longer available.",
            error=ErrorDescriptor(
                ErrorCategory.DEPENDENCY, "DEPENDENCY_REPLY_DESTINATION_UNAVAILABLE"
            ),
        ).to_wire()
    if operation.phase is CreatorOperationPhase.ACCEPTED:
        return _accepted_wire(operation.acceptance)
    result_ref = ResultRef(operation.acceptance.opportunity_id.value)
    if operation.phase is CreatorOperationPhase.CONTEXT_PREPARING:
        return WaitingOutcome(
            **_outcome_common(),
            message="The Context snapshot is being prepared.",
            result_ref=result_ref,
            waiting_for="context_preparation",
            resume_condition="context_prepared",
        ).to_wire()
    if operation.phase is CreatorOperationPhase.CONTEXT_PREPARED:
        return WaitingOutcome(
            **_outcome_common(),
            message="The prepared Context is waiting for a model attempt.",
            result_ref=result_ref,
            waiting_for="model_attempt",
            resume_condition="model_step_available",
        ).to_wire()
    if operation.phase is CreatorOperationPhase.MODEL_CALLING:
        return WaitingOutcome(
            **_outcome_common(),
            message="The model attempt is awaiting a provider response.",
            result_ref=result_ref,
            waiting_for="model_response",
            resume_condition="finalizing",
        ).to_wire()
    if operation.phase is CreatorOperationPhase.FINALIZING:
        return WaitingOutcome(
            **_outcome_common(),
            message="The cognition result is being validated and committed.",
            result_ref=result_ref,
            waiting_for="cognition_finalization",
            resume_condition="cognition_settled",
        ).to_wire()
    if operation.phase is CreatorOperationPhase.EFFECT_REGISTERED:
        return AcceptedOutcome(
            **_outcome_common(),
            message="The effect is registered but has not been dispatched.",
            result_ref=ResultRef(cast(UUID, operation.effect_ref)),
            custodian="runtime",
        ).to_wire()
    if operation.phase is CreatorOperationPhase.EFFECT_DISPATCHING:
        return WaitingOutcome(
            **_outcome_common(),
            message="The registered effect is being dispatched.",
            result_ref=result_ref,
            waiting_for="effect_dispatch",
            resume_condition="effect_settled",
        ).to_wire()
    if operation.phase is CreatorOperationPhase.EFFECT_COMPLETED:
        return CompletedOutcome(
            **_outcome_common(),
            message="The Creator response was received and verified.",
            result_ref=result_ref,
        ).to_wire()
    if operation.phase is CreatorOperationPhase.EFFECT_FAILED:
        return FailedOutcome(
            **_outcome_common(),
            message="The Creator response was confirmed not delivered.",
            error=ErrorDescriptor(
                ErrorCategory.DEPENDENCY, "DEPENDENCY_EFFECT_DELIVERY_FAILED"
            ),
        ).to_wire()
    if operation.phase is CreatorOperationPhase.EFFECT_UNKNOWN:
        return UnknownOutcome(
            **_outcome_common(),
            message="The Creator response result requires authoritative verification.",
            result_ref=ResultRef(cast(UUID, operation.effect_ref)),
            custodian="runtime",
            verification_action="verify_external_delivery"
            if operation.operation_kind == "other_human_response"
            else "verify_local_inbox",
        ).to_wire()
    if operation.phase is CreatorOperationPhase.EFFECT_CANCELLED:
        return RejectedOutcome(
            **_outcome_common(),
            message="The registered effect was cancelled before dispatch.",
            error=ErrorDescriptor(ErrorCategory.POLICY, "POLICY_EFFECT_CANCELLED"),
        ).to_wire()
    if operation.phase is CreatorOperationPhase.CODEX_DISPATCHING:
        return WaitingOutcome(
            **_outcome_common(),
            message="The Codex delegation is running in its isolated workspace.",
            result_ref=result_ref,
            waiting_for="codex_dispatch",
            resume_condition="codex_dispatched",
        ).to_wire()
    if operation.phase is CreatorOperationPhase.CODEX_VERIFYING:
        return WaitingOutcome(
            **_outcome_common(),
            message="The Codex result is being independently verified.",
            result_ref=result_ref,
            waiting_for="codex_verification",
            resume_condition="codex_verified",
        ).to_wire()
    if operation.phase is CreatorOperationPhase.CODEX_RESULT_ACCEPTANCE:
        return WaitingOutcome(
            **_outcome_common(),
            message="The Codex execution result is being processed by cognition.",
            result_ref=result_ref,
            waiting_for="codex_result_acceptance",
            resume_condition="codex_result_accepted",
        ).to_wire()
    if operation.phase is CreatorOperationPhase.CODEX_RESULT_REJECTED:
        return RejectedOutcome(
            **_outcome_common(),
            message="The verified Codex result was rejected by cognition validation.",
            error=ErrorDescriptor(
                ErrorCategory.INTEGRITY, "INTEGRITY_COGNITION_CANDIDATE_REJECTED"
            ),
        ).to_wire()
    if operation.phase is CreatorOperationPhase.CODEX_COMPLETED:
        return CompletedOutcome(
            **_outcome_common(),
            message="Codex execution and subsequent cognition have finished; see their separate results.",
            result_ref=result_ref,
        ).to_wire()
    if operation.phase is CreatorOperationPhase.CODEX_FAILED:
        return FailedOutcome(
            **_outcome_common(),
            message="The Codex delegation was confirmed failed.",
            error=ErrorDescriptor(
                ErrorCategory.DEPENDENCY, "DEPENDENCY_CODEX_DELEGATION_FAILED"
            ),
        ).to_wire()
    if operation.phase is CreatorOperationPhase.CODEX_UNKNOWN:
        return UnknownOutcome(
            **_outcome_common(),
            message="The Codex delegation result requires authoritative verification.",
            result_ref=ResultRef(cast(UUID, operation.effect_ref)),
            custodian="runtime",
            verification_action="verify_codex_result",
        ).to_wire()
    if operation.phase is CreatorOperationPhase.CODEX_CANCELLED:
        return RejectedOutcome(
            **_outcome_common(),
            message="The Codex delegation was cancelled before completion.",
            error=ErrorDescriptor(ErrorCategory.POLICY, "POLICY_CODEX_CANCELLED"),
        ).to_wire()
    if operation.phase is CreatorOperationPhase.FORMAL_DECLINED:
        return CompletedOutcome(
            **_outcome_common(),
            message="Cognition formally declined to respond.",
            result_ref=result_ref,
        ).to_wire()
    if operation.phase is CreatorOperationPhase.FORMAL_NO_ACTION:
        return CompletedOutcome(
            **_outcome_common(),
            message="Cognition formally chose not to act.",
            result_ref=result_ref,
        ).to_wire()
    if operation.phase is CreatorOperationPhase.APPLIED:
        return AppliedOutcome(
            **_outcome_common(),
            message="The subject change is authoritatively committed.",
            result_ref=result_ref,
            state_version=cast(int, operation.subject_version),
        ).to_wire()
    if operation.phase is CreatorOperationPhase.COMPLETED:
        return CompletedOutcome(
            **_outcome_common(),
            message="Cognition completed without a subject change.",
            result_ref=result_ref,
        ).to_wire()
    if operation.phase is CreatorOperationPhase.DEFERRED:
        return WaitingOutcome(
            **_outcome_common(),
            message="Cognition deferred this opportunity.",
            result_ref=result_ref,
            waiting_for="future_opportunity",
            resume_condition="opportunity_available",
        ).to_wire()
    if operation.phase is CreatorOperationPhase.NEED_INFORMATION:
        return WaitingOutcome(
            **_outcome_common(),
            message="Cognition requires new evidence.",
            result_ref=result_ref,
            waiting_for="new_evidence",
            resume_condition="creator_evidence_accepted",
        ).to_wire()
    if operation.phase is CreatorOperationPhase.STALE_CONFLICT:
        return RejectedOutcome(
            **_outcome_common(),
            message="The subject state changed before the candidate could commit.",
            error=ErrorDescriptor(
                ErrorCategory.CONFLICT, "CONFLICT_SUBJECT_STATE_STALE"
            ),
        ).to_wire()
    if operation.phase is CreatorOperationPhase.CANDIDATE_REJECTED:
        return RejectedOutcome(
            **_outcome_common(),
            message="The cognition candidate was rejected.",
            error=ErrorDescriptor(
                ErrorCategory.INTEGRITY, "INTEGRITY_COGNITION_CANDIDATE_REJECTED"
            ),
        ).to_wire()
    if operation.phase is CreatorOperationPhase.FAILED:
        return FailedOutcome(
            **_outcome_common(),
            message="Cognition preparation failed.",
            error=ErrorDescriptor(
                ErrorCategory.INTERNAL, "INTERNAL_COGNITION_PREPARATION_FAILED"
            ),
        ).to_wire()
    return assert_never(operation.phase)


def operation_wire(operation: CreatorOperation) -> dict[str, object]:
    wire = _operation_outcome_wire(operation)
    phase = operation.phase
    stage = _operation_stage(phase)
    outcome = _operation_outcome(phase)
    wire["details"] = {
        "projection_version": "creator-operation.v7",
        "operation_ref": str(operation.acceptance.opportunity_id),
        "operation_kind": operation.operation_kind,
        "stage": stage,
        "outcome": outcome,
        **({"intent_ref": str(operation.intent_ref)} if operation.intent_ref else {}),
        **(
            {"dialogue_decision_ref": str(operation.dialogue_decision_ref)}
            if operation.dialogue_decision_ref
            else {}
        ),
        **(
            {"effect_ref": str(operation.effect_ref)}
            if operation.effect_ref is not None
            else {}
        ),
        **({"work_ref": str(operation.work_ref)} if operation.work_ref else {}),
        **(
            {"effect_attempt_ref": str(operation.effect_attempt_ref)}
            if operation.effect_attempt_ref is not None
            else {}
        ),
        **(
            {"effect_attempt_no": operation.effect_attempt_no}
            if operation.effect_attempt_no is not None
            else {}
        ),
        **(
            {"effect_dispatch_state": operation.effect_dispatch_state}
            if operation.effect_dispatch_state is not None
            else {}
        ),
        **(
            {"effect_observation_ref": str(operation.effect_observation_ref)}
            if operation.effect_observation_ref is not None
            else {}
        ),
        **(
            {"effect_observation_conclusion": operation.effect_observation_conclusion}
            if operation.effect_observation_conclusion is not None
            else {}
        ),
        **(
            {"effect_observation_reliability": operation.effect_observation_reliability}
            if operation.effect_observation_reliability is not None
            else {}
        ),
        **(
            {"owner_reason": operation.owner_reason}
            if operation.owner_reason is not None
            else {}
        ),
        **(
            {"reason_code": operation.failure_code}
            if operation.failure_code is not None
            else {}
        ),
        **(
            {
                "codex_execution": {
                    "task_source_ref": str(operation.codex_execution.task_source_ref),
                    "verification_ref": None
                    if operation.codex_execution.verification_ref is None
                    else str(operation.codex_execution.verification_ref),
                    "execution_status": operation.codex_execution.execution_status,
                    "result_processing_phase": operation.codex_execution.result_processing_phase,
                    "result_processing_reason": operation.codex_execution.result_processing_reason,
                    "model_id": operation.codex_execution.model_id,
                    "sdk_identity": operation.codex_execution.sdk_identity,
                    "validator_id": operation.codex_execution.validator_id,
                    "source_tree_digest": operation.codex_execution.source_tree_digest.value,
                    "final_tree_digest": None
                    if operation.codex_execution.final_tree_digest is None
                    else operation.codex_execution.final_tree_digest.value,
                }
            }
            if operation.codex_execution is not None
            else {}
        ),
    }
    return wire


def _operation_stage(phase: CreatorOperationPhase) -> str:
    return {
        CreatorOperationPhase.ACCEPTED: "accepted",
        CreatorOperationPhase.CONTEXT_PREPARING: "context_preparing",
        CreatorOperationPhase.CONTEXT_PREPARED: "context_preparing",
        CreatorOperationPhase.MODEL_CALLING: "model_pending",
        CreatorOperationPhase.FINALIZING: "model_pending",
        CreatorOperationPhase.FINALIZING: "finalizing",
        CreatorOperationPhase.CANDIDATE_REJECTED: "candidate_rejected",
        CreatorOperationPhase.EFFECT_REGISTERED: "registered",
        CreatorOperationPhase.EFFECT_DISPATCHING: "dispatching",
        CreatorOperationPhase.EFFECT_COMPLETED: "completed",
        CreatorOperationPhase.EFFECT_FAILED: "failed",
        CreatorOperationPhase.EFFECT_UNKNOWN: "unknown",
        CreatorOperationPhase.EFFECT_CANCELLED: "cancelled",
        CreatorOperationPhase.CODEX_DISPATCHING: "dispatching",
        CreatorOperationPhase.CODEX_VERIFYING: "dispatching",
        CreatorOperationPhase.CODEX_RESULT_ACCEPTANCE: "model_pending",
        CreatorOperationPhase.CODEX_RESULT_REJECTED: "candidate_rejected",
        CreatorOperationPhase.CODEX_COMPLETED: "completed",
        CreatorOperationPhase.CODEX_FAILED: "failed",
        CreatorOperationPhase.CODEX_UNKNOWN: "unknown",
        CreatorOperationPhase.CODEX_CANCELLED: "cancelled",
        CreatorOperationPhase.FORMAL_DECLINED: "declined",
        CreatorOperationPhase.FORMAL_NO_ACTION: "no_action",
        CreatorOperationPhase.APPLIED: "applied",
        CreatorOperationPhase.COMPLETED: "no_change",
        CreatorOperationPhase.DEFERRED: "deferred",
        CreatorOperationPhase.NEED_INFORMATION: "need_information",
        CreatorOperationPhase.STALE_CONFLICT: "stale",
        CreatorOperationPhase.FAILED: "failed",
    }[phase]


def _operation_outcome(phase: CreatorOperationPhase) -> str:
    if phase is CreatorOperationPhase.APPLIED:
        return "applied"
    if phase in {
        CreatorOperationPhase.EFFECT_COMPLETED,
        CreatorOperationPhase.CODEX_COMPLETED,
        CreatorOperationPhase.COMPLETED,
    }:
        return "completed"
    if phase is CreatorOperationPhase.FORMAL_NO_ACTION:
        return "no_action"
    if phase is CreatorOperationPhase.DEFERRED:
        return "deferred"
    if phase is CreatorOperationPhase.STALE_CONFLICT:
        return "stale"
    if phase in {
        CreatorOperationPhase.EFFECT_FAILED,
        CreatorOperationPhase.CODEX_FAILED,
        CreatorOperationPhase.FAILED,
    }:
        return "failed"
    if phase in {
        CreatorOperationPhase.EFFECT_UNKNOWN,
        CreatorOperationPhase.CODEX_UNKNOWN,
    }:
        return "unknown"
    if phase in {
        CreatorOperationPhase.EFFECT_CANCELLED,
        CreatorOperationPhase.CODEX_CANCELLED,
    }:
        return "cancelled"
    if phase in {
        CreatorOperationPhase.CANDIDATE_REJECTED,
        CreatorOperationPhase.CODEX_RESULT_REJECTED,
        CreatorOperationPhase.FORMAL_DECLINED,
    }:
        return "rejected"
    return "pending"


def _input_failure(error: CreatorInputViolation) -> tuple[int, dict[str, object]]:
    if error.code == "IDEMPOTENCY-MISMATCH":
        return (409, _rejected("IDEMPOTENCY_MISMATCH"))
    if error.code == "SCOPE-SCENE-NOT-VISIBLE":
        return (404, _rejected("SCOPE_SCENE_NOT_VISIBLE"))
    if error.code == "SCOPE-OPERATION-NOT-VISIBLE":
        return (404, _rejected("SCOPE_OPERATION_NOT_VISIBLE"))
    if error.code == "SCOPE-DATA-RIGHTS-BLOCKED":
        return (403, _rejected("SCOPE_DATA_RIGHTS_BLOCKED"))
    if error.code in {"CON-INPUT-SIZE", "INPUT-SIZE"}:
        return (413, _rejected("INPUT_MESSAGE_TOO_LARGE"))
    if error.code.startswith(("CON-INPUT", "INPUT-")):
        return (400, _rejected("INPUT_MESSAGE_INVALID"))
    return (503, _unavailable("DEPENDENCY_INPUT_ACCEPTANCE_UNAVAILABLE"))


def _strict_object_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


__all__ = (
    "UTC",
    "UUID",
    "AcceptedOutcome",
    "AcceptedOutcomeResponse",
    "ActivityReadPort",
    "ActivityViolation",
    "Any",
    "AppliedOutcome",
    "AppliedOutcomeResponse",
    "Awaitable",
    "BrowserSessionCurrentResponse",
    "BrowserSessionResponse",
    "Callable",
    "CodexDelegationViolation",
    "CodexModel",
    "CodexReasoningEffort",
    "CompletedOutcome",
    "ContractViolation",
    "CreatorActivityItemResponse",
    "CreatorActivityPageResponse",
    "CreatorActivityTimelineItemResponse",
    "CreatorActivityTimelineResponse",
    "CreatorCodexTaskAdmissionPort",
    "CreatorCodexTaskCommand",
    "CreatorCodexTaskRequest",
    "CreatorEmergencyWakePort",
    "CreatorExportCommand",
    "CreatorExportPort",
    "CreatorExportRequest",
    "CreatorExportResponse",
    "CreatorExportResult",
    "CreatorExportViolation",
    "CreatorInputAcceptance",
    "CreatorInputAcceptancePort",
    "CreatorInputCommand",
    "CreatorInputRequest",
    "CreatorInputViolation",
    "CreatorLifeMaterialItem",
    "CreatorLifeMaterialQueryPort",
    "CreatorLifeMaterialResponse",
    "CreatorMaintenanceQueryPort",
    "CreatorMaintenanceSessionResponse",
    "CreatorMaintenanceStatusResponse",
    "CreatorMaintenanceTimelineItemResponse",
    "CreatorMaintenanceTimelineResponse",
    "CreatorMaintenanceViolation",
    "CreatorMemoryItemResponse",
    "CreatorMemoryPageResponse",
    "CreatorMemoryTimelineItemResponse",
    "CreatorMemoryTimelineResponse",
    "CreatorOperation",
    "CreatorOperationPhase",
    "CreatorOperationQueryPort",
    "CreatorProjectionInvalidation",
    "CreatorPromptDeactivateCommand",
    "CreatorPromptDeactivateRequest",
    "CreatorPromptPort",
    "CreatorPromptResponse",
    "CreatorPromptRevisionCommand",
    "CreatorPromptRevisionRequest",
    "CreatorPromptView",
    "CreatorPromptViolation",
    "CreatorRelationshipBoundaryRequest",
    "CreatorRelationshipBoundaryResponse",
    "CreatorRelationshipCommitmentEventResponse",
    "CreatorRelationshipCommitmentResponse",
    "CreatorRelationshipCurrentResponse",
    "CreatorRelationshipFactResponse",
    "CreatorRelationshipIssueResolutionResponse",
    "CreatorRelationshipIssueResponse",
    "CreatorRelationshipItemResponse",
    "CreatorRelationshipRevision",
    "CreatorRelationshipRevisionResponse",
    "CreatorRelationshipTimelineResponse",
    "CreatorResourceKind",
    "CreatorSceneCollectionResponse",
    "CreatorSceneCreateCommand",
    "CreatorSceneCreateRequest",
    "CreatorScenePort",
    "CreatorSceneResponse",
    "CreatorSceneStatusCommand",
    "CreatorSceneView",
    "DataRightsOrderCollectionResponse",
    "DataRightsOrderCommand",
    "DataRightsOrderDetail",
    "DataRightsOrderDetailResponse",
    "DataRightsOrderItemResponse",
    "DataRightsOrderKind",
    "DataRightsOrderPort",
    "DataRightsOrderRequest",
    "DataRightsOrderResponse",
    "DataRightsOrderResult",
    "DataRightsRetryCommand",
    "DataRightsTimelineItemResponse",
    "DataRightsViolation",
    "EffectArtifactKind",
    "EffectId",
    "EffectLedgerPort",
    "EffectResponse",
    "EffectViolation",
    "ErrorCategory",
    "ErrorDescriptor",
    "FailedOutcome",
    "IdempotencyKey",
    "Instant",
    "InteractionResult",
    "LifeRecordActor",
    "LifeRecordItemResponse",
    "LifeRecordKind",
    "LifeRecordKindValue",
    "LifeRecordPageResponse",
    "LifeRecordQuery",
    "LifeRecordQueryPort",
    "LifeRecordQueryViolation",
    "LifeRecordRetrievalKind",
    "LifeViolation",
    "Literal",
    "LiveResponse",
    "LiveVisionObservationRequest",
    "LiveVisionObservationResponse",
    "LiveVisionStatusResponse",
    "LiveVoiceStatusResponse",
    "MaterialViolation",
    "MemoryReadPort",
    "MemoryViolation",
    "OpaqueCursor",
    "OperationOutcomeResponse",
    "OpportunityId",
    "OtherHumanInputCommand",
    "OtherHumanInputPort",
    "OtherHumanInputViolation",
    "OtherHumanPartyKey",
    "OtherHumanPartyRecordPageResponse",
    "OtherHumanPartyRecordResponse",
    "OtherHumanRecordQueryPort",
    "OtherHumanRecordViolation",
    "OtherHumanSceneCommand",
    "OtherHumanSceneRecordPageResponse",
    "OtherHumanSceneRecordResponse",
    "OtherHumanTimelineRecordPageResponse",
    "OtherHumanTimelineRecordResponse",
    "PromptKind",
    "Protocol",
    "QQChannelHealthResponse",
    "Readiness",
    "ReadyResponse",
    "RegisterOtherHumanPartyCommand",
    "RejectedOutcome",
    "RejectedOutcomeResponse",
    "RelationshipReadPort",
    "RelationshipViolation",
    "ResultRef",
    "RuntimeStatusResponse",
    "SceneKey",
    "SceneQueryViolation",
    "SceneStatus",
    "SceneTimelineItemResponse",
    "SceneTimelinePageResponse",
    "SceneTimelineQuery",
    "SceneTimelineQueryPort",
    "SecurityEvent",
    "SubjectComponentSummaryResponse",
    "SubjectSummary",
    "SubjectSummaryProvider",
    "SubjectSummaryResponse",
    "TraceId",
    "TypedDict",
    "UnavailableOutcome",
    "UnavailableOutcomeResponse",
    "UnknownOutcome",
    "ValidationError",
    "WaitingOutcome",
    "_OutcomeArguments",
    "_accepted_wire",
    "_boundary_message",
    "_creator_export_error",
    "_creator_export_response",
    "_creator_prompt_error",
    "_creator_prompt_response",
    "_data_rights_detail_response",
    "_data_rights_error",
    "_data_rights_response",
    "_input_failure",
    "_operation_outcome",
    "_operation_outcome_wire",
    "_operation_stage",
    "_outcome_common",
    "_rejected",
    "_relationship_revision_response",
    "_scene_wire",
    "_strict_object_pairs",
    "_unavailable",
    "assert_never",
    "asynccontextmanager",
    "cast",
    "creator_result",
    "creator_visible_codex_artifact",
    "datetime",
    "json",
    "operation_wire",
    "re",
    "secrets",
    "uuid7",
)
