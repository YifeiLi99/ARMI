"""Shared Creator HTTP types, parsing, and wire projection helpers."""

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
from armi_capability.api import (
    CapabilityDecisionId,
    CapabilityPolicyPort,
    CapabilityRequestId,
    CapabilityViolation,
    CreatorGrantCommand,
    CreatorGrantDecision,
)
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
from fastapi import FastAPI, Request, Security
from fastapi.responses import (
    JSONResponse,
    RedirectResponse,
    Response,
    StreamingResponse,
)
from fastapi.security import HTTPBearer
from pydantic import ValidationError

from .browser_sessions import (
    BrowserSessionStore,
    BrowserSessionViolation,
    SessionMetadata,
)
from .creator_contract import (
    AcceptedOutcomeResponse,
    AppliedOutcomeResponse,
    BrowserSessionCurrentResponse,
    BrowserSessionResponse,
    CapabilityRequestDecisionRequest,
    CapabilityRequestItemResponse,
    CapabilityRequestPageResponse,
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
    DataRightsDeletionItemResponse,
    DataRightsOrderCollectionResponse,
    DataRightsOrderDetailResponse,
    DataRightsOrderRequest,
    DataRightsOrderResponse,
    DataRightsTimelineItemResponse,
    EffectResponse,
    LifeRecordItemResponse,
    LifeRecordKindValue,
    LifeRecordPageResponse,
    LiveResponse,
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
from .creator_events import (
    CreatorEventBroker,
    CreatorEventBrokerViolation,
    parse_last_event_id,
    stream_creator_events,
)
from .static_assets import StaticAsset, StaticAssetStore

_BEARER = re.compile(r"^Bearer ([\x21-\x7e]{1,4096})$", re.ASCII)
_PROXY_HEADERS = frozenset(
    {
        "forwarded",
        "x-forwarded-for",
        "x-forwarded-host",
        "x-forwarded-port",
        "x-forwarded-proto",
    }
)
_SECURITY_HEADERS = {
    "Cache-Control": "no-store",
    "Content-Security-Policy": (
        "default-src 'none'; script-src 'self'; style-src 'self'; "
        "img-src 'self'; font-src 'self'; connect-src 'self'; "
        "base-uri 'none'; form-action 'self'; frame-ancestors 'none'"
    ),
    "Cross-Origin-Opener-Policy": "same-origin",
    "Permissions-Policy": (
        "camera=(), display-capture=(), geolocation=(), microphone=(), "
        "payment=(), usb=()"
    ),
    "Referrer-Policy": "no-referrer",
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
}

AsyncCallback = Callable[[], Awaitable[None]]
ReadinessProvider = Callable[[], Readiness]
RuntimeStatusProvider = Callable[[], RuntimeStatusResponse]
QQChannelHealthProvider = Callable[[], Awaitable[QQChannelHealthResponse]]
LiveVoiceControlProvider = Callable[[str], Awaitable[LiveVoiceStatusResponse]]
LiveVisionControlProvider = Callable[[str], Awaitable[LiveVisionStatusResponse]]
LiveVisionPreviewProvider = Callable[[], bytes | None]
SubjectSummaryProvider = Callable[[], Awaitable[SubjectSummary]]
SecurityEvent = Callable[[str], None]


class CreatorLifeMaterialQueryPort(Protocol):
    async def get_creator_visible(
        self, material_id: UUID
    ) -> CreatorLifeMaterialItem | None: ...


class _OutcomeArguments(TypedDict):
    trace_id: TraceId
    occurred_at: Instant


class _SessionMetadataWire(TypedDict):
    contract_version: Literal["1.0"]
    environment_id: str
    creator_party_id: str
    default_scene_key: str
    issued_at: str
    expires_at: str


def _outcome_common() -> _OutcomeArguments:
    return _OutcomeArguments(
        trace_id=TraceId(secrets.token_hex(16)),
        occurred_at=Instant(datetime.now(UTC)),
    )


def _rejected(
    code: str, message: str = "The request was rejected."
) -> dict[str, object]:
    category = (
        ErrorCategory.INPUT
        if code.startswith("INPUT_")
        else ErrorCategory.SCOPE
        if code.startswith("SCOPE_")
        else ErrorCategory.CONFLICT
        if code.startswith("CONFLICT_")
        else ErrorCategory.IDEMPOTENCY
        if code.startswith("IDEMPOTENCY_")
        else ErrorCategory.AUTH
    )
    return RejectedOutcome(
        **_outcome_common(),
        message=message,
        error=ErrorDescriptor(category, code),
    ).to_wire()


def _unavailable(code: str) -> dict[str, object]:
    return UnavailableOutcome(
        **_outcome_common(),
        message="The requested local Runtime capability is unavailable.",
        error=ErrorDescriptor(ErrorCategory.DEPENDENCY, code),
    ).to_wire()


def _bearer(request: Request) -> str | None:
    authorization = request.headers.get("authorization")
    if authorization is None:
        return None
    match = _BEARER.fullmatch(authorization)
    return None if match is None else match.group(1)


def _metadata_wire(metadata: SessionMetadata) -> _SessionMetadataWire:
    return {
        "contract_version": "1.0",
        "environment_id": str(metadata.environment_id),
        "creator_party_id": str(metadata.creator_party_id),
        "default_scene_key": metadata.default_scene_key,
        "issued_at": Instant(metadata.issued_at).to_wire(),
        "expires_at": Instant(metadata.expires_at).to_wire(),
    }


def _browser_boundary(request: Request, *, canonical_origin: str) -> bool:
    return (
        request.headers.get("sec-fetch-site") == "same-origin"
        and request.headers.get("sec-fetch-mode") == "cors"
        and request.headers.get("sec-fetch-dest") == "empty"
        and (
            request.method not in {"POST", "PUT", "PATCH", "DELETE"}
            or request.headers.get("origin") == canonical_origin
        )
    )


def _strict_object_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def creator_visible_codex_artifact(
    kind: EffectArtifactKind,
    content: bytes,
    media_type: str,
) -> tuple[bytes, str]:
    """Project the verified final result as the Creator's actual deliverable."""

    if kind is not EffectArtifactKind.FINAL_RESULT:
        content.decode("utf-8", errors="strict")
        return content, media_type
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
        if set(document) != {
            "summary",
            "changed_paths",
            "deliverable",
        }:
            raise ValueError
        deliverable = document["deliverable"]
        if type(deliverable) is not str or not deliverable.strip():
            raise ValueError
        projected = deliverable.encode("utf-8", errors="strict")
        if len(projected) > 1024 * 1024:
            raise ValueError
        return projected, "text/plain"
    except UnicodeDecodeError, UnicodeEncodeError, ValueError:
        raise EffectViolation("EFFECT-ARTIFACT-INTEGRITY") from None


def _single_header(request: Request, name: bytes) -> str | None:
    values = [
        value
        for header_name, value in request.scope["headers"]
        if header_name.lower() == name
    ]
    if len(values) != 1:
        return None
    try:
        return values[0].decode("ascii")
    except UnicodeDecodeError:
        return None


async def _creator_input_request(
    request: Request,
    maximum_bytes: int,
) -> CreatorInputRequest:
    if request.headers.get("content-type") != "application/json":
        raise CreatorInputViolation("INPUT-CONTENT-TYPE")
    body = await request.body()
    if not body or len(body) > maximum_bytes:
        raise CreatorInputViolation("INPUT-SIZE")
    try:
        value = json.loads(
            body.decode("utf-8", errors="strict"),
            object_pairs_hook=_strict_object_pairs,
            parse_constant=lambda _value: (_ for _ in ()).throw(
                ValueError("non-finite JSON")
            ),
        )
        return CreatorInputRequest.model_validate(value)
    except UnicodeDecodeError, ValueError, ValidationError:
        raise CreatorInputViolation("INPUT-BODY") from None


async def _local_json_object(request: Request, maximum_bytes: int) -> dict[str, Any]:
    if request.headers.get("content-type") != "application/json":
        raise OtherHumanInputViolation("OTHER-HUMAN-INPUT-CONTENT-TYPE")
    body = await request.body()
    if not body or len(body) > maximum_bytes:
        raise OtherHumanInputViolation("OTHER-HUMAN-INPUT-BODY")
    try:
        value = json.loads(
            body.decode("utf-8", errors="strict"),
            object_pairs_hook=_strict_object_pairs,
            parse_constant=lambda _value: (_ for _ in ()).throw(ValueError()),
        )
    except UnicodeDecodeError, ValueError:
        raise OtherHumanInputViolation("OTHER-HUMAN-INPUT-BODY") from None
    if type(value) is not dict:
        raise OtherHumanInputViolation("OTHER-HUMAN-INPUT-BODY")
    return cast(dict[str, Any], value)


async def _creator_scene_create_request(
    request: Request,
    maximum_bytes: int,
) -> CreatorSceneCreateRequest:
    if request.headers.get("content-type") != "application/json":
        raise SceneQueryViolation("CON-SCENE-CONTENT-TYPE")
    body = await request.body()
    if not body or len(body) > min(maximum_bytes, 1024):
        raise SceneQueryViolation("CON-SCENE-BODY")
    try:
        value = json.loads(
            body.decode("utf-8", errors="strict"),
            object_pairs_hook=_strict_object_pairs,
            parse_constant=lambda _value: (_ for _ in ()).throw(
                ValueError("non-finite JSON")
            ),
        )
        return CreatorSceneCreateRequest.model_validate(value)
    except UnicodeDecodeError, ValueError, ValidationError:
        raise SceneQueryViolation("CON-SCENE-BODY") from None


def _scene_wire(view: CreatorSceneView) -> CreatorSceneResponse:
    return CreatorSceneResponse(
        contract_version="1.0",
        projection_version="creator-scenes.v1",
        scene_id=str(view.scene_id),
        scene_key=view.scene_key.value,
        status=view.status.value,
        opened_at=view.opened_at.to_wire(),
        closed_at=None if view.closed_at is None else view.closed_at.to_wire(),
        recent_context_boundary=(
            None
            if view.recent_context_boundary is None
            else str(view.recent_context_boundary)
        ),
        is_default=view.is_default,
    )


async def _creator_boundary_request(
    request: Request,
    maximum_bytes: int,
) -> CreatorRelationshipBoundaryRequest:
    if request.headers.get("content-type") != "application/json":
        raise CreatorInputViolation("INPUT-CONTENT-TYPE")
    body = await request.body()
    if not body or len(body) > min(maximum_bytes, 4096):
        raise CreatorInputViolation("INPUT-SIZE")
    try:
        value = json.loads(
            body.decode("utf-8", errors="strict"),
            object_pairs_hook=_strict_object_pairs,
            parse_constant=lambda _value: (_ for _ in ()).throw(
                ValueError("non-finite JSON")
            ),
        )
        return CreatorRelationshipBoundaryRequest.model_validate(value)
    except UnicodeDecodeError, ValueError, ValidationError:
        raise CreatorInputViolation("INPUT-BODY") from None


def _boundary_message(request: CreatorRelationshipBoundaryRequest) -> str:
    kind = {
        "contact": "联系",
        "address": "称呼",
        "privacy": "隐私",
        "disclosure": "信息披露",
        "exit": "结束联系",
    }[request.kind]
    action = {
        "refuse": "拒绝",
        "restrict": "限制",
        "end_contact": "结束联系",
    }[request.action]
    return (
        f"我通过 Creator 的关系边界操作明确表达: 对于{kind}, 我选择{action}。"
        f"具体说明: {request.summary}"
    )


async def _creator_codex_task_request(
    request: Request,
    maximum_bytes: int,
) -> CreatorCodexTaskRequest:
    if request.headers.get("content-type") != "application/json":
        raise CodexDelegationViolation("CODEX-TASK-REQUEST")
    body = await request.body()
    if not body or len(body) > min(maximum_bytes, 20 * 1024):
        raise CodexDelegationViolation("CODEX-TASK-REQUEST-SIZE")
    try:
        value = json.loads(
            body.decode("utf-8", errors="strict"),
            object_pairs_hook=_strict_object_pairs,
            parse_constant=lambda _value: (_ for _ in ()).throw(
                ValueError("non-finite JSON")
            ),
        )
        return CreatorCodexTaskRequest.model_validate(value)
    except UnicodeDecodeError, ValueError, ValidationError:
        raise CodexDelegationViolation("CODEX-TASK-REQUEST") from None


async def _capability_decision_request(
    request: Request,
    maximum_bytes: int,
) -> CapabilityRequestDecisionRequest:
    if request.headers.get("content-type") != "application/json":
        raise CapabilityViolation("CON-CAPABILITY-CONTENT-TYPE")
    body = await request.body()
    if not body or len(body) > maximum_bytes:
        raise CapabilityViolation("CON-CAPABILITY-BODY")
    try:
        value = json.loads(
            body.decode("utf-8", errors="strict"),
            object_pairs_hook=_strict_object_pairs,
            parse_constant=lambda _value: (_ for _ in ()).throw(
                ValueError("non-finite JSON")
            ),
        )
        return CapabilityRequestDecisionRequest.model_validate(value)
    except UnicodeDecodeError, ValueError, ValidationError:
        raise CapabilityViolation("CON-CAPABILITY-BODY") from None


async def _creator_prompt_revision_request(
    request: Request,
    maximum_bytes: int,
) -> CreatorPromptRevisionRequest:
    if request.headers.get("content-type") != "application/json":
        raise CreatorPromptViolation("CON-PROMPT-CONTENT-TYPE")
    body = await request.body()
    if not body or len(body) > maximum_bytes:
        raise CreatorPromptViolation("CON-PROMPT-BODY")
    try:
        value = json.loads(
            body.decode("utf-8", errors="strict"),
            object_pairs_hook=_strict_object_pairs,
            parse_constant=lambda _value: (_ for _ in ()).throw(
                ValueError("non-finite JSON")
            ),
        )
        return CreatorPromptRevisionRequest.model_validate(value)
    except UnicodeDecodeError, ValueError, ValidationError:
        raise CreatorPromptViolation("CON-PROMPT-BODY") from None


async def _creator_prompt_deactivate_request(
    request: Request,
    maximum_bytes: int,
) -> CreatorPromptDeactivateRequest:
    if request.headers.get("content-type") != "application/json":
        raise CreatorPromptViolation("CON-PROMPT-CONTENT-TYPE")
    body = await request.body()
    if not body or len(body) > min(maximum_bytes, 1024):
        raise CreatorPromptViolation("CON-PROMPT-BODY")
    try:
        value = json.loads(
            body.decode("utf-8", errors="strict"),
            object_pairs_hook=_strict_object_pairs,
            parse_constant=lambda _value: (_ for _ in ()).throw(
                ValueError("non-finite JSON")
            ),
        )
        return CreatorPromptDeactivateRequest.model_validate(value)
    except UnicodeDecodeError, ValueError, ValidationError:
        raise CreatorPromptViolation("CON-PROMPT-BODY") from None


async def _creator_export_request(
    request: Request,
    maximum_bytes: int,
) -> CreatorExportRequest:
    if request.headers.get("content-type") != "application/json":
        raise CreatorExportViolation("CREATOR-EXPORT-COMMAND")
    body = await request.body()
    if not body or len(body) > min(maximum_bytes, 4096):
        raise CreatorExportViolation("CREATOR-EXPORT-COMMAND")
    try:
        value = json.loads(
            body.decode("utf-8", errors="strict"),
            object_pairs_hook=_strict_object_pairs,
            parse_constant=lambda _value: (_ for _ in ()).throw(
                ValueError("non-finite JSON")
            ),
        )
        return CreatorExportRequest.model_validate(value)
    except UnicodeDecodeError, ValueError, ValidationError:
        raise CreatorExportViolation("CREATOR-EXPORT-COMMAND") from None


def _creator_prompt_response(view: CreatorPromptView) -> CreatorPromptResponse:
    return CreatorPromptResponse(
        contract_version="1.0",
        projection_version="creator-prompt.v1",
        prompt_document_id=str(view.prompt_document_id),
        prompt_kind="creator_guidance",
        status=view.status.value,
        current_revision_id=(
            None if view.current_revision_id is None else str(view.current_revision_id)
        ),
        revision_no=view.revision_no,
        previous_revision_id=(
            None
            if view.previous_revision_id is None
            else str(view.previous_revision_id)
        ),
        revision_kind=(
            None if view.revision_kind is None else view.revision_kind.value
        ),
        content=view.content,
        activated_at=(
            None if view.activated_at is None else view.activated_at.to_wire()
        ),
    )


def _creator_prompt_error(error: CreatorPromptViolation) -> JSONResponse:
    if error.code.startswith("CONFLICT-PROMPT-"):
        return JSONResponse(
            status_code=409,
            content=_rejected("CONFLICT_PROMPT_REVISION"),
        )
    if error.code.startswith("SCOPE-PROMPT-"):
        return JSONResponse(
            status_code=403,
            content=_rejected("SCOPE_PROMPT_NOT_WRITABLE"),
        )
    if error.code.startswith("CON-PROMPT-"):
        return JSONResponse(
            status_code=400,
            content=_rejected("INPUT_PROMPT_INVALID"),
        )
    return JSONResponse(
        status_code=503,
        content=_unavailable("DEPENDENCY_CREATOR_PROMPT_UNAVAILABLE"),
    )


def _creator_export_response(result: CreatorExportResult) -> CreatorExportResponse:
    return CreatorExportResponse(
        contract_version="1.0",
        projection_version="creator-export.v2",
        export_id=str(result.export_id),
        status=result.status.value,
        directory_name=result.directory_name,
        destination_path=result.destination_path,
        segment_count=result.segment_count,
        record_count=result.record_count,
        artifact_count=result.artifact_count,
        missing_artifacts=list(result.missing_artifacts),
        error_code=result.error_code,
        created_at=result.created_at.to_wire(),
        completed_at=(
            None if result.completed_at is None else result.completed_at.to_wire()
        ),
        newly_created=result.newly_created,
    )


def _creator_export_error(error: CreatorExportViolation) -> JSONResponse:
    if error.code in {
        "CREATOR-EXPORT-IDEMPOTENCY-CONFLICT",
        "CREATOR-EXPORT-DIRECTORY-EXISTS",
        "CREATOR-EXPORT-STATE",
    }:
        return JSONResponse(
            status_code=409,
            content=_rejected("CONFLICT_CREATOR_EXPORT"),
        )
    if error.code in {
        "CREATOR-EXPORT-COMMAND",
        "CREATOR-EXPORT-ID",
        "CREATOR-EXPORT-PATH",
    }:
        return JSONResponse(
            status_code=400,
            content=_rejected("INPUT_CREATOR_EXPORT_INVALID"),
        )
    return JSONResponse(
        status_code=503,
        content=_unavailable("DEPENDENCY_CREATOR_EXPORT_UNAVAILABLE"),
    )


async def _data_rights_request(
    request: Request,
    maximum_bytes: int,
) -> DataRightsOrderRequest:
    if request.headers.get("content-type") != "application/json":
        raise DataRightsViolation("DATA-RIGHTS-COMMAND")
    body = await request.body()
    if not body or len(body) > min(maximum_bytes, 1024):
        raise DataRightsViolation("DATA-RIGHTS-COMMAND")
    try:
        value = json.loads(
            body.decode("utf-8", errors="strict"),
            object_pairs_hook=_strict_object_pairs,
            parse_constant=lambda _value: (_ for _ in ()).throw(
                ValueError("non-finite JSON")
            ),
        )
        return DataRightsOrderRequest.model_validate(value)
    except UnicodeDecodeError, ValueError, ValidationError:
        raise DataRightsViolation("DATA-RIGHTS-COMMAND") from None


def _data_rights_response(result: DataRightsOrderResult) -> DataRightsOrderResponse:
    return DataRightsOrderResponse(
        contract_version="1.0",
        projection_version="data-rights-order.v1",
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
        completed_at=(
            None if result.completed_at is None else result.completed_at.to_wire()
        ),
        newly_created=result.newly_created,
    )


def _data_rights_detail_response(
    detail: DataRightsOrderDetail,
) -> DataRightsOrderDetailResponse:
    order = detail.order
    items = [
        DataRightsDeletionItemResponse(
            item_id=str(item.item_id),
            target_kind=cast(Any, item.target_kind),
            required_action=cast(Any, item.required_action),
            result_status=item.result_status.value,
            remaining_location=cast(Any, item.remaining_location),
            created_at=item.created_at.to_wire(),
            completed_at=None
            if item.completed_at is None
            else item.completed_at.to_wire(),
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
        projection_version="data-rights-order.v2",
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
        remaining_locations=cast(
            Any,
            sorted(
                {
                    item.remaining_location
                    for item in detail.items
                    if item.remaining_location is not None
                }
            ),
        ),
    )


def _data_rights_error(error: DataRightsViolation) -> JSONResponse:
    if error.code == "DATA-RIGHTS-REQUESTER-NOT-FOUND":
        return JSONResponse(
            status_code=404,
            content=_rejected("SCOPE_DATA_RIGHTS_REQUESTER_NOT_FOUND"),
        )
    if error.code == "DATA-RIGHTS-IDEMPOTENCY-CONFLICT":
        return JSONResponse(
            status_code=409,
            content=_rejected("CONFLICT_DATA_RIGHTS_IDEMPOTENCY"),
        )
    if error.code in {
        "DATA-RIGHTS-COMMAND",
        "DATA-RIGHTS-ORDER-ID",
        "DATA-RIGHTS-REQUESTER",
    }:
        return JSONResponse(
            status_code=400,
            content=_rejected("INPUT_DATA_RIGHTS_INVALID"),
        )
    return JSONResponse(
        status_code=503,
        content=_unavailable("DEPENDENCY_DATA_RIGHTS_UNAVAILABLE"),
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
                fact_id=str(item.fact_id),
                kind=item.kind.value,
                summary=item.summary,
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
        commitment_event=(
            None
            if revision.commitment_event is None
            else CreatorRelationshipCommitmentEventResponse(
                commitment_id=str(revision.commitment_event.commitment_id),
                kind=revision.commitment_event.kind.value,
                summary=revision.commitment_event.summary,
                related_commitment_id=(
                    None
                    if revision.commitment_event.related_commitment_id is None
                    else str(revision.commitment_event.related_commitment_id)
                ),
            )
        ),
        issue_resolution=(
            None
            if revision.issue_resolution is None
            else CreatorRelationshipIssueResolutionResponse(
                issue_id=str(revision.issue_resolution.issue_id),
                status="resolved",
                resolution_summary=revision.issue_resolution.resolution_summary,
            )
        ),
        status=revision.status.value,
        occurred_at=Instant(revision.occurred_at).to_wire(),
    )


def _operation_outcome_wire(operation: CreatorOperation) -> dict[str, object]:
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
            resume_condition="model_returned",
        ).to_wire()
    if operation.phase is CreatorOperationPhase.MODEL_RETURNED:
        return WaitingOutcome(
            **_outcome_common(),
            message="The model response is waiting for candidate validation.",
            result_ref=result_ref,
            waiting_for="candidate_validation",
            resume_condition="candidate_validation_available",
        ).to_wire()
    if operation.phase is CreatorOperationPhase.CANDIDATE_VALIDATING:
        return WaitingOutcome(
            **_outcome_common(),
            message="The cognition candidate is being validated.",
            result_ref=result_ref,
            waiting_for="candidate_validation",
            resume_condition="candidate_validated",
        ).to_wire()
    if operation.phase is CreatorOperationPhase.CANDIDATE_VALIDATED:
        return WaitingOutcome(
            **_outcome_common(),
            message="The validated candidate is waiting for subject commit.",
            result_ref=result_ref,
            waiting_for="subject_commit",
            resume_condition="subject_commit_available",
        ).to_wire()
    if operation.phase is CreatorOperationPhase.SUBJECT_COMMITTING:
        return WaitingOutcome(
            **_outcome_common(),
            message="The validated change is being committed.",
            result_ref=result_ref,
            waiting_for="subject_commit",
            resume_condition="subject_commit_available",
        ).to_wire()
    if operation.phase is CreatorOperationPhase.RESPONSE_ADMISSION:
        return WaitingOutcome(
            **_outcome_common(),
            message="The response intent is waiting for admission.",
            result_ref=result_ref,
            waiting_for="response_admission",
            resume_condition="response_admitted",
        ).to_wire()
    if operation.phase is CreatorOperationPhase.RESPONSE_ACCEPTED:
        return AcceptedOutcome(
            **_outcome_common(),
            message="The response is durably accepted but has not been sent.",
            result_ref=result_ref,
            custodian="runtime",
        ).to_wire()
    if operation.phase is CreatorOperationPhase.EFFECT_REGISTRATION:
        return WaitingOutcome(
            **_outcome_common(),
            message="The accepted response is waiting for effect registration.",
            result_ref=result_ref,
            waiting_for="effect_registration",
            resume_condition="effect_registered",
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
                ErrorCategory.DEPENDENCY,
                "DEPENDENCY_EFFECT_DELIVERY_FAILED",
            ),
        ).to_wire()
    if operation.phase is CreatorOperationPhase.EFFECT_UNKNOWN:
        return UnknownOutcome(
            **_outcome_common(),
            message="The Creator response result requires authoritative verification.",
            result_ref=ResultRef(cast(UUID, operation.effect_ref)),
            custodian="runtime",
            verification_action="verify_creator_inbox",
        ).to_wire()
    if operation.phase is CreatorOperationPhase.EFFECT_CANCELLED:
        return RejectedOutcome(
            **_outcome_common(),
            message="The registered effect was cancelled before dispatch.",
            error=ErrorDescriptor(ErrorCategory.POLICY, "POLICY_EFFECT_CANCELLED"),
        ).to_wire()
    if operation.phase is CreatorOperationPhase.CODEX_CAPABILITY_DECISION:
        return WaitingOutcome(
            **_outcome_common(),
            message="The Codex delegation is waiting for a Creator capability decision.",
            result_ref=result_ref,
            waiting_for="capability_decision",
            resume_condition="codex_grant_resolved",
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
            message="The verified Codex result is waiting for cognition acceptance.",
            result_ref=result_ref,
            waiting_for="codex_result_acceptance",
            resume_condition="codex_result_accepted",
        ).to_wire()
    if operation.phase is CreatorOperationPhase.CODEX_RESULT_REJECTED:
        return RejectedOutcome(
            **_outcome_common(),
            message="The verified Codex result was rejected by cognition validation.",
            error=ErrorDescriptor(
                ErrorCategory.INTEGRITY,
                "INTEGRITY_COGNITION_CANDIDATE_REJECTED",
            ),
        ).to_wire()
    if operation.phase is CreatorOperationPhase.CODEX_COMPLETED:
        return CompletedOutcome(
            **_outcome_common(),
            message="The Codex result was verified and accepted through cognition.",
            result_ref=result_ref,
        ).to_wire()
    if operation.phase is CreatorOperationPhase.CODEX_FAILED:
        return FailedOutcome(
            **_outcome_common(),
            message="The Codex delegation was confirmed failed.",
            error=ErrorDescriptor(
                ErrorCategory.DEPENDENCY,
                "DEPENDENCY_CODEX_DELEGATION_FAILED",
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
    if operation.phase is CreatorOperationPhase.RESPONSE_UNAUTHORIZED:
        return RejectedOutcome(
            **_outcome_common(),
            message="The response is not covered by a current exact grant.",
            error=ErrorDescriptor(
                ErrorCategory.SCOPE,
                "SCOPE_RESPONSE_NOT_AUTHORIZED",
            ),
        ).to_wire()
    if operation.phase is CreatorOperationPhase.RESPONSE_UNAVAILABLE:
        return UnavailableOutcome(
            **_outcome_common(),
            message="The response capability is unavailable.",
            error=ErrorDescriptor(
                ErrorCategory.DEPENDENCY,
                "DEPENDENCY_RESPONSE_CAPABILITY_UNAVAILABLE",
            ),
        ).to_wire()
    if operation.phase is CreatorOperationPhase.RESPONSE_FAILED:
        return FailedOutcome(
            **_outcome_common(),
            message="The response admission failed.",
            error=ErrorDescriptor(
                ErrorCategory.INTEGRITY,
                "INTEGRITY_RESPONSE_ADMISSION_FAILED",
            ),
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
                ErrorCategory.CONFLICT,
                "CONFLICT_SUBJECT_STATE_STALE",
            ),
        ).to_wire()
    if operation.phase is CreatorOperationPhase.CANDIDATE_REJECTED:
        return RejectedOutcome(
            **_outcome_common(),
            message="The cognition candidate was rejected.",
            error=ErrorDescriptor(
                ErrorCategory.INTEGRITY,
                "INTEGRITY_COGNITION_CANDIDATE_REJECTED",
            ),
        ).to_wire()
    if operation.phase is CreatorOperationPhase.FAILED:
        return FailedOutcome(
            **_outcome_common(),
            message="Cognition preparation failed.",
            error=ErrorDescriptor(
                ErrorCategory.INTERNAL,
                "INTERNAL_COGNITION_PREPARATION_FAILED",
            ),
        ).to_wire()
    return assert_never(operation.phase)


def operation_wire(operation: CreatorOperation) -> dict[str, object]:
    wire = _operation_outcome_wire(operation)
    phase = operation.phase
    stage = _operation_stage(phase)
    outcome = _operation_outcome(phase)
    wire["details"] = {
        "projection_version": "creator-operation.v2",
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
            {"policy_decision_ref": str(operation.policy_decision_ref)}
            if operation.policy_decision_ref
            else {}
        ),
        **(
            {"effect_ref": str(operation.effect_ref)}
            if operation.effect_ref is not None
            else {}
        ),
        **({"work_ref": str(operation.work_ref)} if operation.work_ref else {}),
        **(
            {"reason_code": operation.failure_code}
            if operation.failure_code is not None
            else {}
        ),
        **(
            {
                "codex_execution": {
                    "task_source_ref": str(operation.codex_execution.task_source_ref),
                    "verification_ref": (
                        None
                        if operation.codex_execution.verification_ref is None
                        else str(operation.codex_execution.verification_ref)
                    ),
                    "execution_status": operation.codex_execution.execution_status,
                    "model_id": operation.codex_execution.model_id,
                    "sdk_identity": operation.codex_execution.sdk_identity,
                    "validator_id": operation.codex_execution.validator_id,
                    "source_tree_digest": operation.codex_execution.source_tree_digest.value,
                    "final_tree_digest": (
                        None
                        if operation.codex_execution.final_tree_digest is None
                        else operation.codex_execution.final_tree_digest.value
                    ),
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
        CreatorOperationPhase.MODEL_RETURNED: "model_pending",
        CreatorOperationPhase.CANDIDATE_VALIDATING: "candidate_validating",
        CreatorOperationPhase.CANDIDATE_VALIDATED: "candidate_validating",
        CreatorOperationPhase.CANDIDATE_REJECTED: "candidate_rejected",
        CreatorOperationPhase.SUBJECT_COMMITTING: "subject_committing",
        CreatorOperationPhase.RESPONSE_ADMISSION: "awaiting_authorization",
        CreatorOperationPhase.RESPONSE_ACCEPTED: "awaiting_authorization",
        CreatorOperationPhase.EFFECT_REGISTRATION: "registering_effect",
        CreatorOperationPhase.EFFECT_REGISTERED: "registered",
        CreatorOperationPhase.EFFECT_DISPATCHING: "dispatching",
        CreatorOperationPhase.EFFECT_COMPLETED: "completed",
        CreatorOperationPhase.EFFECT_FAILED: "failed",
        CreatorOperationPhase.EFFECT_UNKNOWN: "unknown",
        CreatorOperationPhase.EFFECT_CANCELLED: "cancelled",
        CreatorOperationPhase.CODEX_CAPABILITY_DECISION: "awaiting_authorization",
        CreatorOperationPhase.CODEX_DISPATCHING: "dispatching",
        CreatorOperationPhase.CODEX_VERIFYING: "dispatching",
        CreatorOperationPhase.CODEX_RESULT_ACCEPTANCE: "completed",
        CreatorOperationPhase.CODEX_RESULT_REJECTED: "candidate_rejected",
        CreatorOperationPhase.CODEX_COMPLETED: "completed",
        CreatorOperationPhase.CODEX_FAILED: "failed",
        CreatorOperationPhase.CODEX_UNKNOWN: "unknown",
        CreatorOperationPhase.CODEX_CANCELLED: "cancelled",
        CreatorOperationPhase.FORMAL_DECLINED: "declined",
        CreatorOperationPhase.FORMAL_NO_ACTION: "no_action",
        CreatorOperationPhase.RESPONSE_UNAUTHORIZED: "authorization_denied",
        CreatorOperationPhase.RESPONSE_UNAVAILABLE: "unavailable",
        CreatorOperationPhase.RESPONSE_FAILED: "failed",
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
    if phase in {CreatorOperationPhase.RESPONSE_UNAVAILABLE}:
        return "unavailable"
    if phase in {
        CreatorOperationPhase.EFFECT_FAILED,
        CreatorOperationPhase.CODEX_FAILED,
        CreatorOperationPhase.RESPONSE_FAILED,
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
        CreatorOperationPhase.RESPONSE_UNAUTHORIZED,
    }:
        return "rejected"
    return "pending"


def _input_failure(error: CreatorInputViolation) -> tuple[int, dict[str, object]]:
    if error.code == "IDEMPOTENCY-MISMATCH":
        return 409, _rejected("IDEMPOTENCY_MISMATCH")
    if error.code == "SCOPE-SCENE-NOT-VISIBLE":
        return 404, _rejected("SCOPE_SCENE_NOT_VISIBLE")
    if error.code == "SCOPE-OPERATION-NOT-VISIBLE":
        return 404, _rejected("SCOPE_OPERATION_NOT_VISIBLE")
    if error.code == "SCOPE-DATA-RIGHTS-BLOCKED":
        return 403, _rejected("SCOPE_DATA_RIGHTS_BLOCKED")
    if error.code in {"CON-INPUT-SIZE", "INPUT-SIZE"}:
        return 413, _rejected("INPUT_MESSAGE_TOO_LARGE")
    if error.code.startswith(("CON-INPUT", "INPUT-")):
        return 400, _rejected("INPUT_MESSAGE_INVALID")
    return 503, _unavailable("DEPENDENCY_INPUT_ACCEPTANCE_UNAVAILABLE")


def _life_query_parameters(
    request: Request,
    *,
    allow_kind: bool,
    allow_text: bool,
) -> tuple[int, str | None, LifeRecordKind | None, OpaqueCursor | None]:
    supported_record_kinds = {
        "activity",
        "conversation",
        "experience",
        "material",
        "memory",
        "relationship",
        "self_change",
    }
    allowed = {"limit", "cursor"}
    if allow_kind:
        allowed.add("kind")
    if allow_text:
        allowed.add("q")
    pairs = list(request.query_params.multi_items())
    names = [name for name, _value in pairs]
    if set(names) - allowed or any(names.count(name) > 1 for name in allowed):
        raise ContractViolation("CON-PAGE", "query parameters are invalid")
    values = dict(pairs)
    limit_text = values.get("limit", "50")
    if not limit_text.isascii() or not limit_text.isdecimal():
        raise ContractViolation("CON-PAGE", "page limit is invalid")
    limit = int(limit_text)
    if not 1 <= limit <= 100:
        raise ContractViolation("CON-PAGE", "page limit is invalid")
    query_text = values.get("q")
    if query_text is not None:
        try:
            encoded = query_text.encode("utf-8", errors="strict")
        except UnicodeEncodeError:
            raise ContractViolation("CON-PAGE", "query text is invalid") from None
        if not query_text.strip() or b"\x00" in encoded or len(encoded) > 1024:
            raise ContractViolation("CON-PAGE", "query text is invalid")
    try:
        record_kind = None
        if allow_kind and "kind" in values:
            if values["kind"] not in supported_record_kinds:
                raise ValueError("unsupported life-record kind")
            record_kind = LifeRecordKind(values["kind"])
        cursor = (
            OpaqueCursor.from_wire(values["cursor"]) if "cursor" in values else None
        )
    except ValueError, ContractViolation:
        raise ContractViolation("CON-PAGE", "query scope is invalid") from None
    return limit, query_text, record_kind, cursor


__all__ = (
    "UTC",
    "UUID",
    "_PROXY_HEADERS",
    "_SECURITY_HEADERS",
    "AcceptedOutcomeResponse",
    "ActivityReadPort",
    "ActivityViolation",
    "Any",
    "AppliedOutcome",
    "AppliedOutcomeResponse",
    "AsyncCallback",
    "Awaitable",
    "BrowserSessionCurrentResponse",
    "BrowserSessionResponse",
    "BrowserSessionStore",
    "BrowserSessionViolation",
    "Callable",
    "CapabilityDecisionId",
    "CapabilityPolicyPort",
    "CapabilityRequestId",
    "CapabilityRequestItemResponse",
    "CapabilityRequestPageResponse",
    "CapabilityViolation",
    "CodexDelegationViolation",
    "CodexModel",
    "CodexReasoningEffort",
    "ContractViolation",
    "CreatorActivityItemResponse",
    "CreatorActivityPageResponse",
    "CreatorActivityTimelineItemResponse",
    "CreatorActivityTimelineResponse",
    "CreatorCodexTaskAdmissionPort",
    "CreatorCodexTaskCommand",
    "CreatorEmergencyWakePort",
    "CreatorEventBroker",
    "CreatorEventBrokerViolation",
    "CreatorExportCommand",
    "CreatorExportPort",
    "CreatorExportResponse",
    "CreatorExportViolation",
    "CreatorGrantCommand",
    "CreatorGrantDecision",
    "CreatorInputAcceptance",
    "CreatorInputAcceptancePort",
    "CreatorInputCommand",
    "CreatorInputViolation",
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
    "CreatorOperationQueryPort",
    "CreatorProjectionInvalidation",
    "CreatorPromptDeactivateCommand",
    "CreatorPromptPort",
    "CreatorPromptResponse",
    "CreatorPromptRevisionCommand",
    "CreatorPromptViolation",
    "CreatorRelationshipCurrentResponse",
    "CreatorRelationshipItemResponse",
    "CreatorRelationshipTimelineResponse",
    "CreatorResourceKind",
    "CreatorSceneCollectionResponse",
    "CreatorSceneCreateCommand",
    "CreatorScenePort",
    "CreatorSceneResponse",
    "CreatorSceneStatusCommand",
    "DataRightsOrderCollectionResponse",
    "DataRightsOrderCommand",
    "DataRightsOrderDetailResponse",
    "DataRightsOrderKind",
    "DataRightsOrderPort",
    "DataRightsOrderResponse",
    "DataRightsViolation",
    "EffectArtifactKind",
    "EffectId",
    "EffectLedgerPort",
    "EffectResponse",
    "EffectViolation",
    "FastAPI",
    "HTTPBearer",
    "IdempotencyKey",
    "Instant",
    "JSONResponse",
    "LifeRecordActor",
    "LifeRecordItemResponse",
    "LifeRecordKindValue",
    "LifeRecordPageResponse",
    "LifeRecordQuery",
    "LifeRecordQueryPort",
    "LifeRecordQueryViolation",
    "LifeRecordRetrievalKind",
    "LifeViolation",
    "Literal",
    "LiveResponse",
    "LiveVisionControlProvider",
    "LiveVisionPreviewProvider",
    "LiveVisionStatusResponse",
    "LiveVoiceControlProvider",
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
    "QQChannelHealthProvider",
    "QQChannelHealthResponse",
    "ReadinessProvider",
    "ReadyResponse",
    "RedirectResponse",
    "RegisterOtherHumanPartyCommand",
    "RejectedOutcomeResponse",
    "RelationshipReadPort",
    "RelationshipViolation",
    "Request",
    "Response",
    "ResultRef",
    "RuntimeStatusProvider",
    "RuntimeStatusResponse",
    "SceneKey",
    "SceneQueryViolation",
    "SceneStatus",
    "SceneTimelineItemResponse",
    "SceneTimelinePageResponse",
    "SceneTimelineQuery",
    "SceneTimelineQueryPort",
    "Security",
    "SecurityEvent",
    "StaticAsset",
    "StaticAssetStore",
    "StreamingResponse",
    "SubjectComponentSummaryResponse",
    "SubjectSummaryProvider",
    "SubjectSummaryResponse",
    "TraceId",
    "UnavailableOutcomeResponse",
    "_accepted_wire",
    "_bearer",
    "_boundary_message",
    "_browser_boundary",
    "_capability_decision_request",
    "_creator_boundary_request",
    "_creator_codex_task_request",
    "_creator_export_error",
    "_creator_export_request",
    "_creator_export_response",
    "_creator_input_request",
    "_creator_prompt_deactivate_request",
    "_creator_prompt_error",
    "_creator_prompt_response",
    "_creator_prompt_revision_request",
    "_creator_scene_create_request",
    "_data_rights_detail_response",
    "_data_rights_error",
    "_data_rights_request",
    "_data_rights_response",
    "_input_failure",
    "_life_query_parameters",
    "_local_json_object",
    "_metadata_wire",
    "_outcome_common",
    "_rejected",
    "_relationship_revision_response",
    "_scene_wire",
    "_single_header",
    "_unavailable",
    "asynccontextmanager",
    "cast",
    "creator_visible_codex_artifact",
    "datetime",
    "operation_wire",
    "parse_last_event_id",
    "re",
    "secrets",
    "stream_creator_events",
    "uuid7",
)
