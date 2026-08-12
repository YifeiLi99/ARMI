"""The authenticated same-origin Creator HTTP surface."""

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
from armi_kernel.application import (
    CapabilityDecisionId,
    CapabilityRequestId,
    CapabilityViolation,
    CodexDelegationViolation,
    CodexModel,
    CodexReasoningEffort,
    CreatorCodexTaskAdmissionPort,
    CreatorCodexTaskCommand,
    CreatorEventResourceKind,
    CreatorExportCommand,
    CreatorExportPort,
    CreatorExportResult,
    CreatorExportViolation,
    CreatorGrantCommand,
    CreatorGrantDecision,
    CreatorGrantResult,
    CreatorInputAcceptance,
    CreatorInputAcceptancePort,
    CreatorInputCommand,
    CreatorInputViolation,
    CreatorOperation,
    CreatorOperationPhase,
    CreatorOperationQueryPort,
    CreatorProjectionInvalidation,
    CreatorPromptDeactivateCommand,
    CreatorPromptPort,
    CreatorPromptRevisionCommand,
    CreatorPromptView,
    CreatorPromptViolation,
    CreatorSceneCreateCommand,
    CreatorScenePort,
    CreatorSceneStatusCommand,
    CreatorSceneView,
    DataRightsOrderCommand,
    DataRightsOrderDetail,
    DataRightsOrderKind,
    DataRightsOrderPort,
    DataRightsOrderResult,
    DataRightsViolation,
    EffectArtifactKind,
    EffectId,
    EffectLedgerPort,
    EffectViolation,
    LifeRecordActor,
    LifeRecordKind,
    LifeRecordQuery,
    LifeRecordQueryPort,
    LifeRecordQueryViolation,
    LifeRecordRetrievalKind,
    LifeViolation,
    OpportunityId,
    OtherHumanInputCommand,
    OtherHumanInputPort,
    OtherHumanInputViolation,
    OtherHumanPartyKey,
    OtherHumanRecordQueryPort,
    OtherHumanRecordViolation,
    OtherHumanSceneCommand,
    PromptKind,
    RegisterOtherHumanPartyCommand,
    SceneKey,
    SceneQueryViolation,
    SceneStatus,
    SceneTimelineQuery,
    SceneTimelineQueryPort,
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
from fastapi import FastAPI, Request
from fastapi.responses import (
    JSONResponse,
    RedirectResponse,
    Response,
    StreamingResponse,
)
from pydantic import ValidationError

from .browser_sessions import (
    BrowserSessionStore,
    BrowserSessionViolation,
    SessionMetadata,
)
from .creator_contract import (
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
    LifeRecordPageResponse,
    LiveResponse,
    OtherHumanPartyRecordPageResponse,
    OtherHumanPartyRecordResponse,
    OtherHumanSceneRecordPageResponse,
    OtherHumanSceneRecordResponse,
    OtherHumanTimelineRecordPageResponse,
    OtherHumanTimelineRecordResponse,
    Readiness,
    ReadyResponse,
    RuntimeStatusResponse,
    SceneTimelineItemResponse,
    SceneTimelinePageResponse,
    SubjectComponentSummaryResponse,
    SubjectSummaryResponse,
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
SubjectSummaryProvider = Callable[[], Awaitable[SubjectSummary]]
SecurityEvent = Callable[[str], None]


class CapabilityPolicyPort(Protocol):
    async def list_requests(
        self,
        *,
        creator_party_id: UUID,
        limit: int,
        cursor: str | None,
    ) -> dict[str, object]: ...

    async def decide(self, command: CreatorGrantCommand) -> CreatorGrantResult: ...


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


def _creator_visible_codex_artifact(
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
        projection_version="creator-export.v1",
        export_id=str(result.export_id),
        status=result.status.value,
        directory_name=result.directory_name,
        destination_path=result.destination_path,
        table_count=result.table_count,
        row_count=result.row_count,
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


def _operation_wire(operation: CreatorOperation) -> dict[str, object]:
    wire = _operation_outcome_wire(operation)
    phase = operation.phase
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
    }[phase]
    delivery_state = {
        CreatorOperationPhase.RESPONSE_ACCEPTED: "not_started",
        CreatorOperationPhase.EFFECT_REGISTRATION: "not_started",
        CreatorOperationPhase.EFFECT_REGISTERED: "registered",
        CreatorOperationPhase.EFFECT_DISPATCHING: "dispatching",
        CreatorOperationPhase.EFFECT_COMPLETED: "completed",
        CreatorOperationPhase.EFFECT_FAILED: "failed",
        CreatorOperationPhase.EFFECT_UNKNOWN: "unknown",
        CreatorOperationPhase.EFFECT_CANCELLED: "cancelled",
        CreatorOperationPhase.CODEX_CAPABILITY_DECISION: "not_started",
        CreatorOperationPhase.CODEX_DISPATCHING: "dispatching",
        CreatorOperationPhase.CODEX_VERIFYING: "dispatching",
        CreatorOperationPhase.CODEX_RESULT_ACCEPTANCE: "completed",
        CreatorOperationPhase.CODEX_RESULT_REJECTED: "completed",
        CreatorOperationPhase.CODEX_COMPLETED: "completed",
        CreatorOperationPhase.CODEX_FAILED: "failed",
        CreatorOperationPhase.CODEX_UNKNOWN: "unknown",
        CreatorOperationPhase.CODEX_CANCELLED: "cancelled",
    }.get(phase)
    wire["details"] = {
        "projection_version": "creator-operation.v1",
        "root_operation_ref": str(operation.acceptance.opportunity_id),
        "completion_kind": completion_kind,
        **({"delivery_state": delivery_state} if delivery_state is not None else {}),
        **(
            {"effect_ref": str(operation.effect_ref)}
            if operation.effect_ref is not None
            else {}
        ),
    }
    return wire


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
        record_kind = (
            LifeRecordKind(values["kind"]) if allow_kind and "kind" in values else None
        )
        cursor = (
            OpaqueCursor.from_wire(values["cursor"]) if "cursor" in values else None
        )
    except ValueError, ContractViolation:
        raise ContractViolation("CON-PAGE", "query scope is invalid") from None
    return limit, query_text, record_kind, cursor


def create_runtime_app(
    *,
    readiness: ReadinessProvider,
    runtime_status: RuntimeStatusProvider,
    assets: StaticAssetStore,
    browser_sessions: BrowserSessionStore | None,
    expected_authority: str,
    request_body_max_bytes: int,
    on_started: AsyncCallback,
    on_stopping: AsyncCallback,
    creator_scenes: CreatorScenePort | None = None,
    scene_timeline_query: SceneTimelineQueryPort | None = None,
    creator_activity_query: ActivityReadPort | None = None,
    life_record_query: LifeRecordQueryPort | None = None,
    creator_life_material_query: CreatorLifeMaterialQueryPort | None = None,
    creator_memory_query: MemoryReadPort | None = None,
    creator_maintenance_query: CreatorMaintenanceQueryPort | None = None,
    creator_relationship_query: RelationshipReadPort | None = None,
    other_human_record_query: OtherHumanRecordQueryPort | None = None,
    creator_emergency_wake: CreatorEmergencyWakePort | None = None,
    creator_events: CreatorEventBroker | None = None,
    creator_input: CreatorInputAcceptancePort | None = None,
    other_human_input: OtherHumanInputPort | None = None,
    creator_operations: CreatorOperationQueryPort | None = None,
    subject_summary: SubjectSummaryProvider | None = None,
    creator_prompt: CreatorPromptPort | None = None,
    creator_export: CreatorExportPort | None = None,
    data_rights: DataRightsOrderPort | None = None,
    capability_policy: CapabilityPolicyPort | None = None,
    effect_ledger: EffectLedgerPort | None = None,
    codex_task_admission: CreatorCodexTaskAdmissionPort | None = None,
    on_security_event: SecurityEvent | None = None,
) -> FastAPI:
    """Create the fixed Runtime app without implementation discovery."""

    canonical_origin = f"http://{expected_authority}"

    def ignore_security_event(_event: str) -> None:
        return None

    emit: SecurityEvent = (
        on_security_event if on_security_event is not None else ignore_security_event
    )

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        await on_started()
        try:
            yield
        finally:
            await on_stopping()

    app = FastAPI(
        title="ARMI Runtime",
        version="1.0",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        lifespan=lifespan,
    )

    @app.middleware("http")
    async def enforce_local_boundary(
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        if request.headers.get("host") != expected_authority or any(
            name in request.headers for name in _PROXY_HEADERS
        ):
            emit("creator.request.boundary_rejected")
            return Response(status_code=421, headers=_SECURITY_HEADERS)
        timeline_path = re.fullmatch(
            r"/v1/scenes/[^/]{1,256}/timeline",
            request.url.path,
        )
        paged_query_path = (
            request.url.path
            in {"/v1/life-records", "/v1/memories", "/v1/other-human-records"}
            or re.fullmatch(
                r"/v1/(?:memories/[^/]{1,64}/timeline|other-human-records/[^/]{1,64}/scenes(?:/[^/]{1,64}/timeline)?)",
                request.url.path,
            )
            is not None
        )
        if (
            request.url.query
            and request.url.path.startswith("/v1/")
            and timeline_path is None
            and request.url.path != "/v1/capability-requests"
            and not paged_query_path
        ):
            emit("creator.request.url_token_rejected")
            return Response(status_code=400, headers=_SECURITY_HEADERS)
        if request.url.path.startswith("/v1/") and "cookie" in request.headers:
            emit("creator.request.cookie_rejected")
            return Response(status_code=403, headers=_SECURITY_HEADERS)
        content_length = request.headers.get("content-length")
        if content_length is not None:
            try:
                length = int(content_length)
            except ValueError:
                return Response(status_code=400, headers=_SECURITY_HEADERS)
            if length < 0 or length > request_body_max_bytes:
                return Response(status_code=413, headers=_SECURITY_HEADERS)
        response = await call_next(request)
        for name, value in _SECURITY_HEADERS.items():
            response.headers.setdefault(name, value)
        return response

    @app.get("/health/live", response_model=LiveResponse)
    async def health_live() -> LiveResponse:
        return LiveResponse(status="alive")

    @app.get("/health/ready", response_model=ReadyResponse)
    async def health_ready() -> JSONResponse:
        current = readiness()
        return JSONResponse(
            status_code=200 if current.value == "ready" else 503,
            content={"status": current.value},
        )

    @app.post("/v1/browser-sessions")
    async def create_browser_session(request: Request) -> JSONResponse:
        if browser_sessions is None:
            return JSONResponse(
                status_code=503,
                content=_unavailable("DEPENDENCY_CREATOR_SESSION_UNAVAILABLE"),
            )
        if not _browser_boundary(request, canonical_origin=canonical_origin):
            emit("creator.session.boundary_rejected")
            return JSONResponse(
                status_code=403,
                content=_rejected("AUTH_BROWSER_BOUNDARY"),
            )
        established = browser_sessions.establish()
        if creator_events is not None:
            await creator_events.close_active()
        emit("creator.session.established")
        response = BrowserSessionResponse(
            **_metadata_wire(established.metadata),
            browser_session_token=established.token,
        )
        return JSONResponse(content=response.model_dump(mode="json"))

    @app.get("/v1/browser-sessions/current")
    async def current_browser_session(request: Request) -> JSONResponse:
        if browser_sessions is None or not _browser_boundary(
            request, canonical_origin=canonical_origin
        ):
            return JSONResponse(
                status_code=403 if browser_sessions is not None else 503,
                content=(
                    _rejected("AUTH_BROWSER_BOUNDARY")
                    if browser_sessions is not None
                    else _unavailable("DEPENDENCY_CREATOR_SESSION_UNAVAILABLE")
                ),
            )
        token = _bearer(request)
        try:
            if token is None:
                raise BrowserSessionViolation("AUTH_SESSION_REQUIRED")
            metadata = browser_sessions.verify(token)
        except BrowserSessionViolation as error:
            emit("creator.session.rejected")
            return JSONResponse(
                status_code=error.status_code,
                content=_rejected(error.code),
            )
        response = BrowserSessionCurrentResponse(**_metadata_wire(metadata))
        return JSONResponse(content=response.model_dump(mode="json"))

    @app.get("/v1/runtime/status")
    async def get_runtime_status(request: Request) -> JSONResponse:
        if browser_sessions is None or not _browser_boundary(
            request, canonical_origin=canonical_origin
        ):
            return JSONResponse(
                status_code=403 if browser_sessions is not None else 503,
                content=(
                    _rejected("AUTH_BROWSER_BOUNDARY")
                    if browser_sessions is not None
                    else _unavailable("DEPENDENCY_CREATOR_SESSION_UNAVAILABLE")
                ),
            )
        token = _bearer(request)
        try:
            if token is None:
                raise BrowserSessionViolation("AUTH_SESSION_REQUIRED")
            browser_sessions.verify(token)
        except BrowserSessionViolation as error:
            return JSONResponse(
                status_code=error.status_code,
                content=_rejected(error.code),
            )
        return JSONResponse(content=runtime_status().model_dump(mode="json"))

    @app.get("/v1/subject/summary")
    async def get_subject_summary(request: Request) -> JSONResponse:
        if (
            browser_sessions is None
            or subject_summary is None
            or not _browser_boundary(request, canonical_origin=canonical_origin)
        ):
            return JSONResponse(
                status_code=403 if browser_sessions is not None else 503,
                content=(
                    _rejected("AUTH_BROWSER_BOUNDARY")
                    if browser_sessions is not None
                    else _unavailable("DEPENDENCY_SUBJECT_SUMMARY_UNAVAILABLE")
                ),
            )
        token = _bearer(request)
        try:
            if token is None:
                raise BrowserSessionViolation("AUTH_SESSION_REQUIRED")
            browser_sessions.verify(token)
            summary = await subject_summary()
        except BrowserSessionViolation as error:
            return JSONResponse(
                status_code=error.status_code, content=_rejected(error.code)
            )
        except CreatorInputViolation:
            return JSONResponse(
                status_code=503,
                content=_unavailable("DEPENDENCY_SUBJECT_SUMMARY_UNAVAILABLE"),
            )
        return JSONResponse(
            content=SubjectSummaryResponse(
                contract_version="1.0",
                projection_version="subject-summary.v1",
                subject_version=summary.subject_version,
                components=[
                    SubjectComponentSummaryResponse(
                        kind=item.kind.value,
                        version=item.version,
                        schema_version=cast(
                            Literal[
                                "armi.self.v1",
                                "armi.mind.v1",
                                "armi.life-mode.v1",
                            ],
                            item.schema_version,
                        ),
                        content_visibility="private",
                    )
                    for item in summary.components
                ],
                latest_commit_ref=(
                    str(summary.latest_commit_ref)
                    if summary.latest_commit_ref is not None
                    else None
                ),
                observed_at=Instant(summary.observed_at).to_wire(),
            ).model_dump(mode="json", exclude_none=True)
        )

    @app.get("/v1/prompts/creator-guidance")
    async def get_creator_prompt(request: Request) -> JSONResponse:
        if (
            browser_sessions is None
            or creator_prompt is None
            or not _browser_boundary(request, canonical_origin=canonical_origin)
        ):
            status = (
                403
                if browser_sessions is not None and creator_prompt is not None
                else 503
            )
            return JSONResponse(
                status_code=status,
                content=(
                    _rejected("AUTH_BROWSER_BOUNDARY")
                    if status == 403
                    else _unavailable("DEPENDENCY_CREATOR_PROMPT_UNAVAILABLE")
                ),
            )
        token = _bearer(request)
        try:
            if token is None:
                raise BrowserSessionViolation("AUTH_SESSION_REQUIRED")
            browser_sessions.verify(token)
            view = await creator_prompt.get(PromptKind.CREATOR_GUIDANCE)
        except BrowserSessionViolation as error:
            return JSONResponse(
                status_code=error.status_code,
                content=_rejected(error.code),
            )
        except CreatorPromptViolation as error:
            return _creator_prompt_error(error)
        return JSONResponse(
            content=_creator_prompt_response(view).model_dump(mode="json")
        )

    @app.put("/v1/prompts/creator-guidance")
    async def revise_creator_prompt(request: Request) -> JSONResponse:
        if (
            browser_sessions is None
            or creator_prompt is None
            or not _browser_boundary(request, canonical_origin=canonical_origin)
        ):
            status = (
                403
                if browser_sessions is not None and creator_prompt is not None
                else 503
            )
            return JSONResponse(
                status_code=status,
                content=(
                    _rejected("AUTH_BROWSER_BOUNDARY")
                    if status == 403
                    else _unavailable("DEPENDENCY_CREATOR_PROMPT_UNAVAILABLE")
                ),
            )
        token = _bearer(request)
        try:
            if token is None:
                raise BrowserSessionViolation("AUTH_SESSION_REQUIRED")
            browser_sessions.verify(token)
            body = await _creator_prompt_revision_request(
                request,
                request_body_max_bytes,
            )
            view = await creator_prompt.revise(
                CreatorPromptRevisionCommand(
                    prompt_kind=PromptKind.CREATOR_GUIDANCE,
                    expected_revision_id=(
                        None
                        if body.expected_revision_id is None
                        else UUID(body.expected_revision_id)
                    ),
                    content=body.content,
                    trace_id=TraceId(secrets.token_hex(16)),
                )
            )
        except BrowserSessionViolation as error:
            return JSONResponse(
                status_code=error.status_code,
                content=_rejected(error.code),
            )
        except CreatorPromptViolation as error:
            return _creator_prompt_error(error)
        return JSONResponse(
            content=_creator_prompt_response(view).model_dump(mode="json")
        )

    @app.post("/v1/prompts/creator-guidance/deactivation")
    async def deactivate_creator_prompt(request: Request) -> JSONResponse:
        if (
            browser_sessions is None
            or creator_prompt is None
            or not _browser_boundary(request, canonical_origin=canonical_origin)
        ):
            status = (
                403
                if browser_sessions is not None and creator_prompt is not None
                else 503
            )
            return JSONResponse(
                status_code=status,
                content=(
                    _rejected("AUTH_BROWSER_BOUNDARY")
                    if status == 403
                    else _unavailable("DEPENDENCY_CREATOR_PROMPT_UNAVAILABLE")
                ),
            )
        token = _bearer(request)
        try:
            if token is None:
                raise BrowserSessionViolation("AUTH_SESSION_REQUIRED")
            browser_sessions.verify(token)
            body = await _creator_prompt_deactivate_request(
                request,
                request_body_max_bytes,
            )
            view = await creator_prompt.deactivate(
                CreatorPromptDeactivateCommand(
                    prompt_kind=PromptKind.CREATOR_GUIDANCE,
                    expected_revision_id=UUID(body.expected_revision_id),
                    trace_id=TraceId(secrets.token_hex(16)),
                )
            )
        except BrowserSessionViolation as error:
            return JSONResponse(
                status_code=error.status_code,
                content=_rejected(error.code),
            )
        except CreatorPromptViolation as error:
            return _creator_prompt_error(error)
        return JSONResponse(
            content=_creator_prompt_response(view).model_dump(mode="json")
        )

    del get_creator_prompt, revise_creator_prompt, deactivate_creator_prompt

    @app.post("/v1/exports")
    async def create_creator_export(request: Request) -> JSONResponse:
        if (
            browser_sessions is None
            or creator_export is None
            or not _browser_boundary(request, canonical_origin=canonical_origin)
        ):
            status = (
                403
                if browser_sessions is not None and creator_export is not None
                else 503
            )
            return JSONResponse(
                status_code=status,
                content=(
                    _rejected("AUTH_BROWSER_BOUNDARY")
                    if status == 403
                    else _unavailable("DEPENDENCY_CREATOR_EXPORT_UNAVAILABLE")
                ),
            )
        token = _bearer(request)
        try:
            if token is None:
                raise BrowserSessionViolation("AUTH_SESSION_REQUIRED")
            browser_sessions.verify(token)
            idempotency_value = request.headers.get("idempotency-key")
            if idempotency_value is None:
                raise CreatorExportViolation("CREATOR-EXPORT-COMMAND")
            try:
                idempotency_key = IdempotencyKey.from_wire(idempotency_value)
            except ContractViolation:
                raise CreatorExportViolation("CREATOR-EXPORT-COMMAND") from None
            body = await _creator_export_request(request, request_body_max_bytes)
            result = await creator_export.export(
                CreatorExportCommand(
                    directory_name=body.directory_name,
                    idempotency_key=idempotency_key,
                    trace_id=TraceId(secrets.token_hex(16)),
                )
            )
        except BrowserSessionViolation as error:
            return JSONResponse(
                status_code=error.status_code,
                content=_rejected(error.code),
            )
        except CreatorExportViolation as error:
            return _creator_export_error(error)
        return JSONResponse(
            status_code=201 if result.newly_created else 200,
            content=_creator_export_response(result).model_dump(mode="json"),
        )

    @app.get("/v1/exports/{export_id}")
    async def get_creator_export(request: Request, export_id: str) -> JSONResponse:
        if (
            browser_sessions is None
            or creator_export is None
            or not _browser_boundary(request, canonical_origin=canonical_origin)
        ):
            status = (
                403
                if browser_sessions is not None and creator_export is not None
                else 503
            )
            return JSONResponse(
                status_code=status,
                content=(
                    _rejected("AUTH_BROWSER_BOUNDARY")
                    if status == 403
                    else _unavailable("DEPENDENCY_CREATOR_EXPORT_UNAVAILABLE")
                ),
            )
        token = _bearer(request)
        try:
            if token is None:
                raise BrowserSessionViolation("AUTH_SESSION_REQUIRED")
            browser_sessions.verify(token)
            try:
                export_uuid = UUID(export_id)
            except ValueError:
                raise CreatorExportViolation("CREATOR-EXPORT-ID") from None
            result = await creator_export.get(export_uuid)
        except BrowserSessionViolation as error:
            return JSONResponse(
                status_code=error.status_code,
                content=_rejected(error.code),
            )
        except CreatorExportViolation as error:
            return _creator_export_error(error)
        if result is None:
            return JSONResponse(
                status_code=404,
                content=_rejected("CREATOR_EXPORT_NOT_FOUND"),
            )
        return JSONResponse(
            content=_creator_export_response(result).model_dump(mode="json")
        )

    del create_creator_export, get_creator_export

    @app.get("/v1/data-rights/orders")
    async def list_creator_data_rights_orders(request: Request) -> JSONResponse:
        if (
            browser_sessions is None
            or data_rights is None
            or not _browser_boundary(request, canonical_origin=canonical_origin)
        ):
            status = (
                403 if browser_sessions is not None and data_rights is not None else 503
            )
            return JSONResponse(
                status_code=status,
                content=_rejected("AUTH_BROWSER_BOUNDARY")
                if status == 403
                else _unavailable("DEPENDENCY_DATA_RIGHTS_UNAVAILABLE"),
            )
        try:
            token = _bearer(request)
            if token is None:
                raise BrowserSessionViolation("AUTH_SESSION_REQUIRED")
            browser_sessions.verify(token)
            details = await data_rights.list_creator()
        except BrowserSessionViolation as error:
            return JSONResponse(
                status_code=error.status_code, content=_rejected(error.code)
            )
        except DataRightsViolation as error:
            return _data_rights_error(error)
        return JSONResponse(
            content=DataRightsOrderCollectionResponse(
                contract_version="1.0",
                projection_version="data-rights-order.v2",
                orders=[_data_rights_detail_response(detail) for detail in details],
            ).model_dump(mode="json")
        )

    @app.post("/v1/data-rights/orders")
    async def create_creator_data_rights_order(request: Request) -> JSONResponse:
        if (
            browser_sessions is None
            or data_rights is None
            or not _browser_boundary(request, canonical_origin=canonical_origin)
        ):
            status = (
                403 if browser_sessions is not None and data_rights is not None else 503
            )
            return JSONResponse(
                status_code=status,
                content=(
                    _rejected("AUTH_BROWSER_BOUNDARY")
                    if status == 403
                    else _unavailable("DEPENDENCY_DATA_RIGHTS_UNAVAILABLE")
                ),
            )
        token = _bearer(request)
        try:
            if token is None:
                raise BrowserSessionViolation("AUTH_SESSION_REQUIRED")
            browser_sessions.verify(token)
            idempotency_value = request.headers.get("idempotency-key")
            if idempotency_value is None:
                raise DataRightsViolation("DATA-RIGHTS-COMMAND")
            try:
                idempotency_key = IdempotencyKey.from_wire(idempotency_value)
            except ContractViolation:
                raise DataRightsViolation("DATA-RIGHTS-COMMAND") from None
            body = await _data_rights_request(request, request_body_max_bytes)
            result = await data_rights.request_creator(
                DataRightsOrderCommand(
                    DataRightsOrderKind(body.order_kind),
                    idempotency_key,
                    TraceId(secrets.token_hex(16)),
                )
            )
        except BrowserSessionViolation as error:
            return JSONResponse(
                status_code=error.status_code,
                content=_rejected(error.code),
            )
        except DataRightsViolation as error:
            return _data_rights_error(error)
        return JSONResponse(
            status_code=201 if result.newly_created else 200,
            content=_data_rights_response(result).model_dump(mode="json"),
        )

    @app.get("/v1/data-rights/orders/{order_id}")
    async def get_creator_data_rights_order(
        request: Request, order_id: str
    ) -> JSONResponse:
        if (
            browser_sessions is None
            or data_rights is None
            or not _browser_boundary(request, canonical_origin=canonical_origin)
        ):
            status = (
                403 if browser_sessions is not None and data_rights is not None else 503
            )
            return JSONResponse(
                status_code=status,
                content=(
                    _rejected("AUTH_BROWSER_BOUNDARY")
                    if status == 403
                    else _unavailable("DEPENDENCY_DATA_RIGHTS_UNAVAILABLE")
                ),
            )
        token = _bearer(request)
        try:
            if token is None:
                raise BrowserSessionViolation("AUTH_SESSION_REQUIRED")
            browser_sessions.verify(token)
            try:
                order_uuid = UUID(order_id)
            except ValueError:
                raise DataRightsViolation("DATA-RIGHTS-ORDER-ID") from None
            result = await data_rights.detail_creator(order_uuid)
        except BrowserSessionViolation as error:
            return JSONResponse(
                status_code=error.status_code,
                content=_rejected(error.code),
            )
        except DataRightsViolation as error:
            return _data_rights_error(error)
        if result is None:
            return JSONResponse(
                status_code=404,
                content=_rejected("SCOPE_DATA_RIGHTS_ORDER_NOT_FOUND"),
            )
        return JSONResponse(
            content=_data_rights_detail_response(result).model_dump(mode="json")
        )

    del list_creator_data_rights_orders, create_creator_data_rights_order
    del get_creator_data_rights_order

    @app.get("/v1/capability-requests")
    async def list_capability_requests(request: Request) -> JSONResponse:
        if (
            browser_sessions is None
            or capability_policy is None
            or not _browser_boundary(request, canonical_origin=canonical_origin)
        ):
            status = 403 if browser_sessions is not None else 503
            return JSONResponse(
                status_code=status,
                content=(
                    _rejected("AUTH_BROWSER_BOUNDARY")
                    if status == 403
                    else _unavailable("DEPENDENCY_CAPABILITY_POLICY_UNAVAILABLE")
                ),
            )
        token = _bearer(request)
        try:
            if token is None:
                raise BrowserSessionViolation("AUTH_SESSION_REQUIRED")
            metadata = browser_sessions.verify(token)
        except BrowserSessionViolation as error:
            return JSONResponse(
                status_code=error.status_code,
                content=_rejected(error.code),
            )
        pairs = list(request.query_params.multi_items())
        names = [name for name, _value in pairs]
        if set(names) - {"limit", "cursor"} or any(
            names.count(name) > 1 for name in {"limit", "cursor"}
        ):
            return JSONResponse(
                status_code=400,
                content=_rejected("INPUT_PAGE_LIMIT"),
            )
        values = dict(pairs)
        limit_text = values.get("limit", "50")
        if not limit_text.isascii() or not limit_text.isdecimal():
            return JSONResponse(
                status_code=400,
                content=_rejected("INPUT_PAGE_LIMIT"),
            )
        limit = int(limit_text)
        if not 1 <= limit <= 100:
            return JSONResponse(
                status_code=400,
                content=_rejected("INPUT_PAGE_LIMIT"),
            )
        try:
            page = await capability_policy.list_requests(
                creator_party_id=metadata.creator_party_id,
                limit=limit,
                cursor=values.get("cursor"),
            )
        except CapabilityViolation as error:
            if error.code == "CONFLICT-CAPABILITY-CURSOR-STALE":
                return JSONResponse(
                    status_code=409,
                    content=_rejected("CONFLICT_CURSOR_STALE"),
                )
            if error.code == "CON-CAPABILITY-CURSOR":
                return JSONResponse(
                    status_code=400,
                    content=_rejected("INPUT_CURSOR_INVALID"),
                )
            return JSONResponse(
                status_code=503,
                content=_unavailable("DEPENDENCY_CAPABILITY_POLICY_UNAVAILABLE"),
            )
        raw_items = cast(list[dict[str, object]], page["items"])
        response = CapabilityRequestPageResponse(
            contract_version="1.0",
            projection_version="capability-request.v4",
            items=[
                CapabilityRequestItemResponse.model_validate(
                    {
                        **item,
                        "created_at": Instant(
                            cast(datetime, item["created_at"])
                        ).to_wire(),
                        "status_changed_at": Instant(
                            cast(datetime, item["status_changed_at"])
                        ).to_wire(),
                        **(
                            {
                                "effective_grant": {
                                    **cast(
                                        dict[str, object],
                                        item["effective_grant"],
                                    ),
                                    "valid_from": Instant(
                                        cast(
                                            datetime,
                                            cast(
                                                dict[str, object],
                                                item["effective_grant"],
                                            )["valid_from"],
                                        )
                                    ).to_wire(),
                                    "valid_until": Instant(
                                        cast(
                                            datetime,
                                            cast(
                                                dict[str, object],
                                                item["effective_grant"],
                                            )["valid_until"],
                                        )
                                    ).to_wire(),
                                    **(
                                        {
                                            "ended_at": Instant(
                                                cast(
                                                    datetime,
                                                    cast(
                                                        dict[str, object],
                                                        item["effective_grant"],
                                                    )["ended_at"],
                                                )
                                            ).to_wire()
                                        }
                                        if cast(
                                            dict[str, object],
                                            item["effective_grant"],
                                        ).get("ended_at")
                                        is not None
                                        else {}
                                    ),
                                }
                            }
                            if item.get("effective_grant") is not None
                            else {}
                        ),
                    }
                )
                for item in raw_items
            ],
            next_cursor=cast(str | None, page["next_cursor"]),
        )
        return JSONResponse(content=response.model_dump(mode="json", exclude_none=True))

    @app.post("/v1/capability-requests/{capability_request_id}/decision")
    async def decide_capability_request(
        capability_request_id: str,
        request: Request,
    ) -> JSONResponse:
        if (
            browser_sessions is None
            or capability_policy is None
            or not _browser_boundary(request, canonical_origin=canonical_origin)
        ):
            status = 403 if browser_sessions is not None else 503
            return JSONResponse(
                status_code=status,
                content=(
                    _rejected("AUTH_BROWSER_BOUNDARY")
                    if status == 403
                    else _unavailable("DEPENDENCY_CAPABILITY_POLICY_UNAVAILABLE")
                ),
            )
        token = _bearer(request)
        try:
            if token is None:
                raise BrowserSessionViolation("AUTH_SESSION_REQUIRED")
            browser_sessions.verify(token)
            body = await _capability_decision_request(
                request,
                request_body_max_bytes,
            )
            command = CreatorGrantCommand(
                CapabilityDecisionId(UUID(body.decision_id)),
                CapabilityRequestId(UUID(capability_request_id)),
                body.expected_request_version,
                CreatorGrantDecision(body.decision),
                body.valid_for_seconds,
                body.max_uses,
                body.max_payload_bytes,
                body.reason_code,
            )
            result = await capability_policy.decide(command)
        except BrowserSessionViolation as error:
            return JSONResponse(
                status_code=error.status_code,
                content=_rejected(error.code),
            )
        except (CapabilityViolation, ValueError) as error:
            code = (
                error.code
                if isinstance(error, CapabilityViolation)
                else "CON-CAPABILITY-REQUEST-ID"
            )
            if code == "SCOPE-CAPABILITY-REQUEST":
                return JSONResponse(
                    status_code=404,
                    content=_rejected("SCOPE_CAPABILITY_REQUEST_NOT_VISIBLE"),
                )
            if code.startswith(("CONFLICT-", "POLICY-", "CAPABILITY-")):
                return JSONResponse(
                    status_code=409,
                    content=_rejected("CONFLICT_CAPABILITY_DECISION"),
                )
            if code.startswith("CON-CAPABILITY"):
                return JSONResponse(
                    status_code=400,
                    content=_rejected("INPUT_CAPABILITY_DECISION_INVALID"),
                )
            return JSONResponse(
                status_code=503,
                content=_unavailable("DEPENDENCY_CAPABILITY_POLICY_UNAVAILABLE"),
            )
        applied = AppliedOutcome(
            **_outcome_common(),
            message="The Creator capability decision was applied.",
            result_ref=ResultRef(result.request_id.value),
            state_version=result.request_version,
        )
        if creator_events is not None:
            try:
                await creator_events.notify(
                    CreatorProjectionInvalidation(
                        CreatorEventResourceKind.CAPABILITY_REQUEST,
                        str(result.request_id.value),
                        Instant(datetime.now(UTC)),
                        "capability-request.v4",
                    )
                )
            except Exception:
                emit("creator.capability.notification_failed")
        return JSONResponse(content=applied.to_wire())

    del list_capability_requests, decide_capability_request

    @app.get("/v1/activities")
    async def list_creator_activities(request: Request) -> JSONResponse:
        if (
            browser_sessions is None
            or creator_activity_query is None
            or not _browser_boundary(request, canonical_origin=canonical_origin)
        ):
            status = (
                403
                if browser_sessions is not None and creator_activity_query is not None
                else 503
            )
            return JSONResponse(
                status_code=status,
                content=(
                    _rejected("AUTH_BROWSER_BOUNDARY")
                    if status == 403
                    else _unavailable("DEPENDENCY_ACTIVITY_QUERY_UNAVAILABLE")
                ),
            )
        token = _bearer(request)
        try:
            if token is None:
                raise BrowserSessionViolation("AUTH_SESSION_REQUIRED")
            browser_sessions.verify(token)
        except BrowserSessionViolation as error:
            return JSONResponse(
                status_code=error.status_code,
                content=_rejected(error.code),
            )
        try:
            page = await creator_activity_query.list_current()
        except ActivityViolation:
            return JSONResponse(
                status_code=503,
                content=_unavailable("DEPENDENCY_ACTIVITY_QUERY_UNAVAILABLE"),
            )
        response = CreatorActivityPageResponse(
            contract_version="1.0",
            projection_version="creator-activity.v1",
            items=[
                CreatorActivityItemResponse(
                    activity_id=str(item.activity_id),
                    activity_kind=item.activity_kind,
                    status=item.status.value,
                    goal=item.goal,
                    progress_summary=item.progress_summary,
                    waiting_kind=(
                        None if item.waiting_kind is None else item.waiting_kind.value
                    ),
                    waiting_summary=item.waiting_summary,
                    resume_not_before=(
                        None
                        if item.resume_not_before is None
                        else Instant(item.resume_not_before).to_wire()
                    ),
                    terminal_reason=item.terminal_reason,
                    revision_no=item.revision_no,
                    head_version=item.head_version,
                    transition_kind=item.transition_kind.value,
                    is_focused=item.is_focused,
                    created_at=Instant(item.created_at).to_wire(),
                    updated_at=Instant(item.updated_at).to_wire(),
                )
                for item in page.items
            ],
            truncated=page.truncated,
        )
        return JSONResponse(content=response.model_dump(mode="json"))

    @app.get("/v1/activities/{activity_id}/timeline")
    async def get_creator_activity_timeline(
        activity_id: str, request: Request
    ) -> JSONResponse:
        if (
            browser_sessions is None
            or creator_activity_query is None
            or not _browser_boundary(request, canonical_origin=canonical_origin)
        ):
            status = (
                403
                if browser_sessions is not None and creator_activity_query is not None
                else 503
            )
            return JSONResponse(
                status_code=status,
                content=(
                    _rejected("AUTH_BROWSER_BOUNDARY")
                    if status == 403
                    else _unavailable("DEPENDENCY_ACTIVITY_QUERY_UNAVAILABLE")
                ),
            )
        token = _bearer(request)
        try:
            if token is None:
                raise BrowserSessionViolation("AUTH_SESSION_REQUIRED")
            browser_sessions.verify(token)
        except BrowserSessionViolation as error:
            return JSONResponse(
                status_code=error.status_code,
                content=_rejected(error.code),
            )
        try:
            parsed = UUID(activity_id)
            if parsed.version != 7 or str(parsed) != activity_id:
                raise ValueError
        except ValueError:
            return JSONResponse(
                status_code=404,
                content=_rejected("SCOPE_ACTIVITY_NOT_VISIBLE"),
            )
        try:
            timeline = await creator_activity_query.timeline(parsed)
        except ActivityViolation as error:
            if error.code == "ACTIVITY-QUERY-NOT-FOUND":
                return JSONResponse(
                    status_code=404,
                    content=_rejected("SCOPE_ACTIVITY_NOT_VISIBLE"),
                )
            return JSONResponse(
                status_code=503,
                content=_unavailable("DEPENDENCY_ACTIVITY_QUERY_UNAVAILABLE"),
            )
        response = CreatorActivityTimelineResponse(
            contract_version="1.0",
            projection_version="creator-activity.v1",
            activity_id=str(timeline.activity_id),
            items=[
                CreatorActivityTimelineItemResponse(
                    event_id=str(item.event_id),
                    event_kind=item.event_kind,
                    resulting_status=(
                        None
                        if item.resulting_status is None
                        else item.resulting_status.value
                    ),
                    summary=item.summary,
                    review_not_before=(
                        None
                        if item.review_not_before is None
                        else Instant(item.review_not_before).to_wire()
                    ),
                    occurred_at=Instant(item.occurred_at).to_wire(),
                )
                for item in timeline.items
            ],
            truncated=timeline.truncated,
        )
        return JSONResponse(content=response.model_dump(mode="json"))

    del list_creator_activities, get_creator_activity_timeline

    @app.get("/v1/relationships/current")
    async def get_creator_relationship_current(request: Request) -> JSONResponse:
        if (
            browser_sessions is None
            or creator_relationship_query is None
            or not _browser_boundary(request, canonical_origin=canonical_origin)
        ):
            status = (
                403
                if browser_sessions is not None
                and creator_relationship_query is not None
                else 503
            )
            return JSONResponse(
                status_code=status,
                content=(
                    _rejected("AUTH_BROWSER_BOUNDARY")
                    if status == 403
                    else _unavailable("DEPENDENCY_RELATIONSHIP_QUERY_UNAVAILABLE")
                ),
            )
        token = _bearer(request)
        try:
            if token is None:
                raise BrowserSessionViolation("AUTH_SESSION_REQUIRED")
            browser_sessions.verify(token)
        except BrowserSessionViolation as error:
            return JSONResponse(
                status_code=error.status_code,
                content=_rejected(error.code),
            )
        try:
            item = await creator_relationship_query.current()
        except RelationshipViolation:
            return JSONResponse(
                status_code=503,
                content=_unavailable("DEPENDENCY_RELATIONSHIP_QUERY_UNAVAILABLE"),
            )
        response = CreatorRelationshipCurrentResponse(
            contract_version="1.0",
            projection_version="creator-relationship.v2",
            relationship=(
                None
                if item is None
                else CreatorRelationshipItemResponse(
                    relationship_id=str(item.relationship_id),
                    current_revision_id=str(item.current_revision_id),
                    head_version=item.head_version,
                    current=_relationship_revision_response(item.current),
                    created_at=Instant(item.created_at).to_wire(),
                )
            ),
        )
        return JSONResponse(content=response.model_dump(mode="json"))

    @app.get("/v1/relationships/{relationship_id}/timeline")
    async def get_creator_relationship_timeline(
        relationship_id: str,
        request: Request,
    ) -> JSONResponse:
        if (
            browser_sessions is None
            or creator_relationship_query is None
            or not _browser_boundary(request, canonical_origin=canonical_origin)
        ):
            status = (
                403
                if browser_sessions is not None
                and creator_relationship_query is not None
                else 503
            )
            return JSONResponse(
                status_code=status,
                content=(
                    _rejected("AUTH_BROWSER_BOUNDARY")
                    if status == 403
                    else _unavailable("DEPENDENCY_RELATIONSHIP_QUERY_UNAVAILABLE")
                ),
            )
        token = _bearer(request)
        try:
            if token is None:
                raise BrowserSessionViolation("AUTH_SESSION_REQUIRED")
            browser_sessions.verify(token)
        except BrowserSessionViolation as error:
            return JSONResponse(
                status_code=error.status_code,
                content=_rejected(error.code),
            )
        try:
            parsed = UUID(relationship_id)
            if parsed.version != 7 or str(parsed) != relationship_id:
                raise ValueError
        except ValueError:
            return JSONResponse(
                status_code=404,
                content=_rejected("SCOPE_RELATIONSHIP_NOT_VISIBLE"),
            )
        try:
            timeline = await creator_relationship_query.timeline(parsed)
        except RelationshipViolation as error:
            if error.code == "RELATIONSHIP-QUERY-NOT-FOUND":
                return JSONResponse(
                    status_code=404,
                    content=_rejected("SCOPE_RELATIONSHIP_NOT_VISIBLE"),
                )
            return JSONResponse(
                status_code=503,
                content=_unavailable("DEPENDENCY_RELATIONSHIP_QUERY_UNAVAILABLE"),
            )
        response = CreatorRelationshipTimelineResponse(
            contract_version="1.0",
            projection_version="creator-relationship.v2",
            relationship_id=str(timeline.relationship_id),
            items=[_relationship_revision_response(item) for item in timeline.items],
            truncated=timeline.truncated,
        )
        return JSONResponse(content=response.model_dump(mode="json"))

    @app.post("/v1/relationships/current/boundaries")
    async def express_creator_relationship_boundary(
        request: Request,
    ) -> JSONResponse:
        if (
            browser_sessions is None
            or creator_input is None
            or not _browser_boundary(request, canonical_origin=canonical_origin)
        ):
            status = (
                403
                if browser_sessions is not None and creator_input is not None
                else 503
            )
            return JSONResponse(
                status_code=status,
                content=(
                    _rejected("AUTH_BROWSER_BOUNDARY")
                    if status == 403
                    else _unavailable("DEPENDENCY_RELATIONSHIP_INPUT_UNAVAILABLE")
                ),
            )
        token = _bearer(request)
        try:
            if token is None:
                raise BrowserSessionViolation("AUTH_SESSION_REQUIRED")
            metadata = browser_sessions.verify(token)
        except BrowserSessionViolation as error:
            return JSONResponse(
                status_code=error.status_code,
                content=_rejected(error.code),
            )
        idempotency_value = _single_header(request, b"idempotency-key")
        if idempotency_value is None:
            return JSONResponse(
                status_code=400,
                content=_rejected("INPUT_IDEMPOTENCY_KEY"),
            )
        try:
            model = await _creator_boundary_request(request, request_body_max_bytes)
            acceptance = await creator_input.accept(
                CreatorInputCommand(
                    scene_key=metadata.default_scene_key,
                    message=_boundary_message(model),
                    idempotency_key=IdempotencyKey(idempotency_value),
                    trace_id=TraceId(secrets.token_hex(16)),
                )
            )
        except (ContractViolation, CreatorInputViolation) as error:
            if isinstance(error, ContractViolation):
                status, content = 400, _rejected("INPUT_IDEMPOTENCY_KEY")
            else:
                status, content = _input_failure(error)
            emit("creator.relationship_boundary.rejected")
            return JSONResponse(status_code=status, content=content)
        emit(
            "creator.relationship_boundary.accepted"
            if acceptance.newly_accepted
            else "creator.relationship_boundary.idempotent"
        )
        if creator_events is not None and acceptance.newly_accepted:
            try:
                await creator_events.notify(
                    CreatorProjectionInvalidation(
                        CreatorEventResourceKind.OPERATION,
                        str(acceptance.opportunity_id),
                        Instant(datetime.now(UTC)),
                        "creator-operation.v1",
                    )
                )
            except Exception:
                emit("creator.operation.notification_failed")
        return JSONResponse(status_code=202, content=_accepted_wire(acceptance))

    del (
        express_creator_relationship_boundary,
        get_creator_relationship_current,
        get_creator_relationship_timeline,
    )

    @app.get("/v1/life-records")
    async def query_creator_life_records(request: Request) -> JSONResponse:
        if (
            browser_sessions is None
            or life_record_query is None
            or not _browser_boundary(request, canonical_origin=canonical_origin)
        ):
            status = (
                403
                if browser_sessions is not None and life_record_query is not None
                else 503
            )
            return JSONResponse(
                status_code=status,
                content=(
                    _rejected("AUTH_BROWSER_BOUNDARY")
                    if status == 403
                    else _unavailable("DEPENDENCY_LIFE_QUERY_UNAVAILABLE")
                ),
            )
        token = _bearer(request)
        try:
            if token is None:
                raise BrowserSessionViolation("AUTH_SESSION_REQUIRED")
            browser_sessions.verify(token)
        except BrowserSessionViolation as error:
            return JSONResponse(
                status_code=error.status_code,
                content=_rejected(error.code),
            )
        try:
            limit, query_text, record_kind, cursor = _life_query_parameters(
                request,
                allow_kind=True,
                allow_text=True,
            )
            page = await life_record_query.query(
                LifeRecordQuery(
                    actor=LifeRecordActor.CREATOR,
                    retrieval_kind=LifeRecordRetrievalKind.CREATOR_VIEW,
                    limit=limit,
                    record_kind=record_kind,
                    query_text=query_text,
                    cursor=cursor,
                )
            )
        except ContractViolation:
            return JSONResponse(
                status_code=400,
                content=_rejected("INPUT_LIFE_QUERY_INVALID"),
            )
        except LifeRecordQueryViolation as error:
            if error.code == "LIFE-QUERY-CURSOR-INVALID":
                return JSONResponse(
                    status_code=400,
                    content=_rejected("INPUT_CURSOR_INVALID"),
                )
            if error.code == "LIFE-QUERY-CURSOR-STALE":
                return JSONResponse(
                    status_code=409,
                    content=_rejected("CONFLICT_CURSOR_STALE"),
                )
            return JSONResponse(
                status_code=503,
                content=_unavailable("DEPENDENCY_LIFE_QUERY_UNAVAILABLE"),
            )
        response = LifeRecordPageResponse(
            contract_version="1.0",
            projection_version="life-record-query.v2",
            retrieval_kind="creator_view",
            items=[
                LifeRecordItemResponse(
                    record_ref=str(item.record_ref),
                    record_kind=item.record_kind.value,
                    summary=item.summary,
                    source_kind=item.source_kind,
                    occurred_at=item.occurred_at.to_wire(),
                    naturally_recallable=item.naturally_recallable,
                    retrieval_kind=item.retrieval_kind.value,
                )
                for item in page.items
            ],
            next_cursor=(
                None if page.next_cursor is None else page.next_cursor.to_wire()
            ),
        )
        return JSONResponse(content=response.model_dump(mode="json"))

    @app.get("/v1/materials/{material_id}")
    async def get_creator_life_material(
        material_id: str,
        request: Request,
    ) -> JSONResponse:
        if (
            browser_sessions is None
            or creator_life_material_query is None
            or not _browser_boundary(request, canonical_origin=canonical_origin)
        ):
            status = (
                403
                if browser_sessions is not None
                and creator_life_material_query is not None
                else 503
            )
            return JSONResponse(
                status_code=status,
                content=(
                    _rejected("AUTH_BROWSER_BOUNDARY")
                    if status == 403
                    else _unavailable("DEPENDENCY_LIFE_MATERIAL_QUERY_UNAVAILABLE")
                ),
            )
        token = _bearer(request)
        try:
            if token is None:
                raise BrowserSessionViolation("AUTH_SESSION_REQUIRED")
            browser_sessions.verify(token)
        except BrowserSessionViolation as error:
            return JSONResponse(
                status_code=error.status_code,
                content=_rejected(error.code),
            )
        try:
            parsed = UUID(material_id)
            if parsed.version != 7 or str(parsed) != material_id:
                raise ValueError
        except ValueError:
            return JSONResponse(
                status_code=404,
                content=_rejected("SCOPE_LIFE_MATERIAL_NOT_VISIBLE"),
            )
        try:
            item = await creator_life_material_query.get_creator_visible(parsed)
        except MaterialViolation:
            return JSONResponse(
                status_code=503,
                content=_unavailable("DEPENDENCY_LIFE_MATERIAL_QUERY_UNAVAILABLE"),
            )
        if item is None:
            return JSONResponse(
                status_code=404,
                content=_rejected("SCOPE_LIFE_MATERIAL_NOT_VISIBLE"),
            )
        response = CreatorLifeMaterialResponse(
            contract_version="1.0",
            projection_version="creator-life-material.v1",
            material_id=str(item.material_id),
            material_kind=item.material_kind.value,
            revision_no=item.revision_no,
            title=item.title,
            body=item.body,
            metadata=dict(item.metadata),
            material_status=item.material_status.value,
            privacy_status="creator_visible",
            created_at=item.created_at.to_wire(),
            updated_at=item.updated_at.to_wire(),
        )
        return JSONResponse(content=response.model_dump(mode="json"))

    @app.get("/v1/memories")
    async def list_creator_memories(request: Request) -> JSONResponse:
        if (
            browser_sessions is None
            or creator_memory_query is None
            or not _browser_boundary(request, canonical_origin=canonical_origin)
        ):
            status = (
                403
                if browser_sessions is not None and creator_memory_query is not None
                else 503
            )
            return JSONResponse(
                status_code=status,
                content=(
                    _rejected("AUTH_BROWSER_BOUNDARY")
                    if status == 403
                    else _unavailable("DEPENDENCY_MEMORY_QUERY_UNAVAILABLE")
                ),
            )
        token = _bearer(request)
        try:
            if token is None:
                raise BrowserSessionViolation("AUTH_SESSION_REQUIRED")
            browser_sessions.verify(token)
        except BrowserSessionViolation as error:
            return JSONResponse(
                status_code=error.status_code,
                content=_rejected(error.code),
            )
        try:
            limit, query_text, _kind, cursor = _life_query_parameters(
                request,
                allow_kind=False,
                allow_text=True,
            )
            page = await creator_memory_query.list_current(
                limit=limit,
                query_text=query_text,
                cursor=cursor,
            )
        except ContractViolation:
            return JSONResponse(
                status_code=400,
                content=_rejected("INPUT_MEMORY_QUERY_INVALID"),
            )
        except LifeRecordQueryViolation as error:
            if error.code == "LIFE-QUERY-CURSOR-INVALID":
                return JSONResponse(
                    status_code=400,
                    content=_rejected("INPUT_CURSOR_INVALID"),
                )
            if error.code == "LIFE-QUERY-CURSOR-STALE":
                return JSONResponse(
                    status_code=409,
                    content=_rejected("CONFLICT_CURSOR_STALE"),
                )
            return JSONResponse(
                status_code=503,
                content=_unavailable("DEPENDENCY_MEMORY_QUERY_UNAVAILABLE"),
            )
        except MemoryViolation as error:
            if error.code == "MEMORY-CURSOR":
                return JSONResponse(
                    status_code=400,
                    content=_rejected("INPUT_CURSOR_INVALID"),
                )
            return JSONResponse(
                status_code=503,
                content=_unavailable("DEPENDENCY_MEMORY_QUERY_UNAVAILABLE"),
            )
        response = CreatorMemoryPageResponse(
            contract_version="1.0",
            projection_version="creator-memory.v1",
            retrieval_kind="creator_view",
            items=[
                CreatorMemoryItemResponse(
                    memory_id=str(item.memory_id),
                    summary=item.summary,
                    uncertainty=item.uncertainty,
                    source_kind=item.source_kind,
                    source_fact_class=item.source_fact_class,
                    accessibility=item.accessibility.value,
                    revision_kind=item.revision_kind.value,
                    revision_no=item.revision_no,
                    head_version=item.head_version,
                    created_at=item.created_at.to_wire(),
                    updated_at=item.updated_at.to_wire(),
                )
                for item in page.items
            ],
            next_cursor=(
                None if page.next_cursor is None else page.next_cursor.to_wire()
            ),
        )
        return JSONResponse(content=response.model_dump(mode="json"))

    @app.get("/v1/memories/{memory_id}/timeline")
    async def get_creator_memory_timeline(
        memory_id: str,
        request: Request,
    ) -> JSONResponse:
        if (
            browser_sessions is None
            or creator_memory_query is None
            or not _browser_boundary(request, canonical_origin=canonical_origin)
        ):
            status = (
                403
                if browser_sessions is not None and creator_memory_query is not None
                else 503
            )
            return JSONResponse(
                status_code=status,
                content=(
                    _rejected("AUTH_BROWSER_BOUNDARY")
                    if status == 403
                    else _unavailable("DEPENDENCY_MEMORY_QUERY_UNAVAILABLE")
                ),
            )
        token = _bearer(request)
        try:
            if token is None:
                raise BrowserSessionViolation("AUTH_SESSION_REQUIRED")
            browser_sessions.verify(token)
        except BrowserSessionViolation as error:
            return JSONResponse(
                status_code=error.status_code,
                content=_rejected(error.code),
            )
        try:
            parsed = UUID(memory_id)
            if parsed.version != 7 or str(parsed) != memory_id:
                raise ValueError
        except ValueError:
            return JSONResponse(
                status_code=404,
                content=_rejected("SCOPE_MEMORY_NOT_VISIBLE"),
            )
        try:
            limit, _query_text, _kind, cursor = _life_query_parameters(
                request,
                allow_kind=False,
                allow_text=False,
            )
            timeline = await creator_memory_query.timeline(
                parsed,
                limit=limit,
                cursor=cursor,
            )
        except ContractViolation:
            return JSONResponse(
                status_code=400,
                content=_rejected("INPUT_MEMORY_QUERY_INVALID"),
            )
        except LifeRecordQueryViolation as error:
            if error.code == "LIFE-QUERY-NOT-FOUND":
                return JSONResponse(
                    status_code=404,
                    content=_rejected("SCOPE_MEMORY_NOT_VISIBLE"),
                )
            if error.code == "LIFE-QUERY-CURSOR-INVALID":
                return JSONResponse(
                    status_code=400,
                    content=_rejected("INPUT_CURSOR_INVALID"),
                )
            if error.code == "LIFE-QUERY-CURSOR-STALE":
                return JSONResponse(
                    status_code=409,
                    content=_rejected("CONFLICT_CURSOR_STALE"),
                )
            return JSONResponse(
                status_code=503,
                content=_unavailable("DEPENDENCY_MEMORY_QUERY_UNAVAILABLE"),
            )
        except MemoryViolation as error:
            if error.code == "MEMORY-QUERY-NOT-FOUND":
                return JSONResponse(
                    status_code=404,
                    content=_rejected("SCOPE_MEMORY_NOT_VISIBLE"),
                )
            if error.code == "MEMORY-CURSOR":
                return JSONResponse(
                    status_code=400,
                    content=_rejected("INPUT_CURSOR_INVALID"),
                )
            return JSONResponse(
                status_code=503,
                content=_unavailable("DEPENDENCY_MEMORY_QUERY_UNAVAILABLE"),
            )
        response = CreatorMemoryTimelineResponse(
            contract_version="1.0",
            projection_version="creator-memory.v1",
            retrieval_kind="creator_view",
            memory_id=str(timeline.memory_id),
            items=[
                CreatorMemoryTimelineItemResponse(
                    revision_id=str(item.revision_id),
                    revision_no=item.revision_no,
                    revision_kind=item.revision_kind.value,
                    accessibility=item.accessibility.value,
                    summary=item.summary,
                    uncertainty=item.uncertainty,
                    source_kind=item.source_kind,
                    source_fact_class=item.source_fact_class,
                    relation_kind=(
                        None if item.relation_kind is None else item.relation_kind.value
                    ),
                    related_memory_id=(
                        None
                        if item.related_memory_id is None
                        else str(item.related_memory_id)
                    ),
                    occurred_at=item.occurred_at.to_wire(),
                )
                for item in timeline.items
            ],
            next_cursor=(
                None if timeline.next_cursor is None else timeline.next_cursor.to_wire()
            ),
        )
        return JSONResponse(content=response.model_dump(mode="json"))

    del get_creator_life_material, query_creator_life_records, list_creator_memories
    del get_creator_memory_timeline

    @app.get("/v1/maintenance/status")
    async def get_creator_maintenance_status(request: Request) -> JSONResponse:
        if (
            browser_sessions is None
            or creator_maintenance_query is None
            or not _browser_boundary(request, canonical_origin=canonical_origin)
        ):
            status = (
                403
                if browser_sessions is not None
                and creator_maintenance_query is not None
                else 503
            )
            return JSONResponse(
                status_code=status,
                content=(
                    _rejected("AUTH_BROWSER_BOUNDARY")
                    if status == 403
                    else _unavailable("DEPENDENCY_MAINTENANCE_QUERY_UNAVAILABLE")
                ),
            )
        token = _bearer(request)
        try:
            if token is None:
                raise BrowserSessionViolation("AUTH_SESSION_REQUIRED")
            browser_sessions.verify(token)
        except BrowserSessionViolation as error:
            return JSONResponse(
                status_code=error.status_code,
                content=_rejected(error.code),
            )
        try:
            status = await creator_maintenance_query.status()
        except CreatorMaintenanceViolation:
            return JSONResponse(
                status_code=503,
                content=_unavailable("DEPENDENCY_MAINTENANCE_QUERY_UNAVAILABLE"),
            )
        session = status.session
        response = CreatorMaintenanceStatusResponse(
            contract_version="1.0",
            projection_version="creator-maintenance.v2",
            session=(
                None
                if session is None
                else CreatorMaintenanceSessionResponse(
                    maintenance_session_id=str(session.session_id),
                    trigger_kind=session.trigger_kind.value,
                    phase=session.phase.value,
                    result_status=session.result_status.value,
                    revision_no=session.revision_no,
                    head_version=session.head_version,
                    wake_requested=session.wake_requested,
                    started_at=Instant(session.started_at).to_wire(),
                    updated_at=Instant(session.updated_at).to_wire(),
                    finished_at=(
                        None
                        if session.finished_at is None
                        else Instant(session.finished_at).to_wire()
                    ),
                )
            ),
            waiting_input_count=status.waiting_input_count,
        )
        return JSONResponse(content=response.model_dump(mode="json"))

    @app.get("/v1/maintenance/{maintenance_session_id}/timeline")
    async def get_creator_maintenance_timeline(
        maintenance_session_id: str,
        request: Request,
    ) -> JSONResponse:
        if (
            browser_sessions is None
            or creator_maintenance_query is None
            or not _browser_boundary(request, canonical_origin=canonical_origin)
        ):
            status = (
                403
                if browser_sessions is not None
                and creator_maintenance_query is not None
                else 503
            )
            return JSONResponse(
                status_code=status,
                content=(
                    _rejected("AUTH_BROWSER_BOUNDARY")
                    if status == 403
                    else _unavailable("DEPENDENCY_MAINTENANCE_QUERY_UNAVAILABLE")
                ),
            )
        token = _bearer(request)
        try:
            if token is None:
                raise BrowserSessionViolation("AUTH_SESSION_REQUIRED")
            browser_sessions.verify(token)
        except BrowserSessionViolation as error:
            return JSONResponse(
                status_code=error.status_code,
                content=_rejected(error.code),
            )
        try:
            parsed = UUID(maintenance_session_id)
            if parsed.version != 7 or str(parsed) != maintenance_session_id:
                raise ValueError
        except ValueError:
            return JSONResponse(
                status_code=404,
                content=_rejected("SCOPE_MAINTENANCE_NOT_VISIBLE"),
            )
        try:
            timeline = await creator_maintenance_query.timeline(parsed)
        except CreatorMaintenanceViolation as error:
            if error.code == "MAINTENANCE-QUERY-NOT-FOUND":
                return JSONResponse(
                    status_code=404,
                    content=_rejected("SCOPE_MAINTENANCE_NOT_VISIBLE"),
                )
            return JSONResponse(
                status_code=503,
                content=_unavailable("DEPENDENCY_MAINTENANCE_QUERY_UNAVAILABLE"),
            )
        response = CreatorMaintenanceTimelineResponse(
            contract_version="1.0",
            projection_version="creator-maintenance.v2",
            maintenance_session_id=str(timeline.session_id),
            items=[
                CreatorMaintenanceTimelineItemResponse(
                    revision_id=str(item.revision_id),
                    revision_no=item.revision_no,
                    phase=item.phase.value,
                    result_status=item.result_status.value,
                    transition_kind=item.transition_kind,
                    occurred_at=Instant(item.occurred_at).to_wire(),
                    work_outcome=(
                        None if item.work_outcome is None else item.work_outcome.value
                    ),
                    problem_summary=item.problem_summary,
                )
                for item in timeline.items
            ],
            truncated=timeline.truncated,
        )
        return JSONResponse(content=response.model_dump(mode="json"))

    @app.post("/v1/maintenance/{maintenance_session_id}/wake")
    async def request_creator_emergency_wake(
        maintenance_session_id: str,
        request: Request,
    ) -> Response:
        if (
            browser_sessions is None
            or creator_emergency_wake is None
            or not _browser_boundary(request, canonical_origin=canonical_origin)
        ):
            status = (
                403
                if browser_sessions is not None and creator_emergency_wake is not None
                else 503
            )
            return JSONResponse(
                status_code=status,
                content=(
                    _rejected("AUTH_BROWSER_BOUNDARY")
                    if status == 403
                    else _unavailable("DEPENDENCY_MAINTENANCE_WAKE_UNAVAILABLE")
                ),
            )
        token = _bearer(request)
        try:
            if token is None:
                raise BrowserSessionViolation("AUTH_SESSION_REQUIRED")
            browser_sessions.verify(token)
        except BrowserSessionViolation as error:
            return JSONResponse(
                status_code=error.status_code,
                content=_rejected(error.code),
            )
        try:
            parsed = UUID(maintenance_session_id)
            if parsed.version != 7 or str(parsed) != maintenance_session_id:
                raise ValueError
        except ValueError:
            return JSONResponse(
                status_code=404,
                content=_rejected("SCOPE_MAINTENANCE_NOT_VISIBLE"),
            )
        try:
            await creator_emergency_wake.request_emergency_wake(parsed, uuid7())
        except LifeViolation as error:
            if error.code == "LIFE-MAINTENANCE-NOT-ACTIVE":
                return JSONResponse(
                    status_code=409,
                    content=_rejected("STATE_MAINTENANCE_NOT_ACTIVE"),
                )
            return JSONResponse(
                status_code=503,
                content=_unavailable("DEPENDENCY_MAINTENANCE_WAKE_UNAVAILABLE"),
            )
        return Response(status_code=204)

    del (
        get_creator_maintenance_status,
        get_creator_maintenance_timeline,
        request_creator_emergency_wake,
    )

    @app.get("/v1/scenes")
    async def list_creator_scenes(request: Request) -> JSONResponse:
        if (
            browser_sessions is None
            or creator_scenes is None
            or not _browser_boundary(request, canonical_origin=canonical_origin)
        ):
            status = (
                403
                if browser_sessions is not None and creator_scenes is not None
                else 503
            )
            return JSONResponse(
                status_code=status,
                content=(
                    _rejected("AUTH_BROWSER_BOUNDARY")
                    if status == 403
                    else _unavailable("DEPENDENCY_SCENE_QUERY_UNAVAILABLE")
                ),
            )
        try:
            token = _bearer(request)
            if token is None:
                raise BrowserSessionViolation("AUTH_SESSION_REQUIRED")
            browser_sessions.verify(token)
            collection = await creator_scenes.list()
        except BrowserSessionViolation as error:
            return JSONResponse(
                status_code=error.status_code,
                content=_rejected(error.code),
            )
        except SceneQueryViolation:
            return JSONResponse(
                status_code=503,
                content=_unavailable("DEPENDENCY_SCENE_QUERY_UNAVAILABLE"),
            )
        response = CreatorSceneCollectionResponse(
            contract_version="1.0",
            projection_version="creator-scenes.v1",
            scenes=[_scene_wire(scene) for scene in collection.scenes],
        )
        return JSONResponse(content=response.model_dump(mode="json", exclude_none=True))

    @app.post("/v1/scenes")
    async def create_creator_scene(request: Request) -> JSONResponse:
        if (
            browser_sessions is None
            or creator_scenes is None
            or not _browser_boundary(request, canonical_origin=canonical_origin)
        ):
            status = (
                403
                if browser_sessions is not None and creator_scenes is not None
                else 503
            )
            return JSONResponse(
                status_code=status,
                content=(
                    _rejected("AUTH_BROWSER_BOUNDARY")
                    if status == 403
                    else _unavailable("DEPENDENCY_SCENE_COMMAND_UNAVAILABLE")
                ),
            )
        try:
            token = _bearer(request)
            if token is None:
                raise BrowserSessionViolation("AUTH_SESSION_REQUIRED")
            browser_sessions.verify(token)
            model = await _creator_scene_create_request(
                request,
                request_body_max_bytes,
            )
            created = await creator_scenes.create(
                CreatorSceneCreateCommand(
                    SceneKey(model.scene_key),
                    TraceId(secrets.token_hex(16)),
                )
            )
        except BrowserSessionViolation as error:
            return JSONResponse(
                status_code=error.status_code,
                content=_rejected(error.code),
            )
        except SceneQueryViolation as error:
            if error.code == "SCENE-KEY-CONFLICT":
                return JSONResponse(
                    status_code=409,
                    content=_rejected("CONFLICT_SCENE_KEY"),
                )
            if error.code.startswith("CON-SCENE"):
                return JSONResponse(
                    status_code=400,
                    content=_rejected("INPUT_SCENE_KEY"),
                )
            return JSONResponse(
                status_code=503,
                content=_unavailable("DEPENDENCY_SCENE_COMMAND_UNAVAILABLE"),
            )
        return JSONResponse(
            status_code=201,
            content=_scene_wire(created).model_dump(mode="json", exclude_none=True),
        )

    async def transition_creator_scene(
        scene_key: str,
        request: Request,
        target_status: SceneStatus,
    ) -> JSONResponse:
        if (
            browser_sessions is None
            or creator_scenes is None
            or not _browser_boundary(request, canonical_origin=canonical_origin)
        ):
            status = (
                403
                if browser_sessions is not None and creator_scenes is not None
                else 503
            )
            return JSONResponse(
                status_code=status,
                content=(
                    _rejected("AUTH_BROWSER_BOUNDARY")
                    if status == 403
                    else _unavailable("DEPENDENCY_SCENE_COMMAND_UNAVAILABLE")
                ),
            )
        try:
            token = _bearer(request)
            if token is None:
                raise BrowserSessionViolation("AUTH_SESSION_REQUIRED")
            browser_sessions.verify(token)
            changed = await creator_scenes.set_status(
                CreatorSceneStatusCommand(
                    SceneKey(scene_key),
                    target_status,
                    TraceId(secrets.token_hex(16)),
                )
            )
        except BrowserSessionViolation as error:
            return JSONResponse(
                status_code=error.status_code,
                content=_rejected(error.code),
            )
        except SceneQueryViolation as error:
            if error.code == "SCENE-NOT-VISIBLE":
                return JSONResponse(
                    status_code=404,
                    content=_rejected("SCOPE_SCENE_NOT_VISIBLE"),
                )
            if error.code.startswith("CON-SCENE"):
                return JSONResponse(
                    status_code=400,
                    content=_rejected("INPUT_SCENE_KEY"),
                )
            return JSONResponse(
                status_code=503,
                content=_unavailable("DEPENDENCY_SCENE_COMMAND_UNAVAILABLE"),
            )
        return JSONResponse(
            content=_scene_wire(changed).model_dump(mode="json", exclude_none=True)
        )

    @app.post("/v1/scenes/{scene_key}/close")
    async def close_creator_scene(scene_key: str, request: Request) -> JSONResponse:
        return await transition_creator_scene(scene_key, request, SceneStatus.CLOSED)

    @app.post("/v1/scenes/{scene_key}/reopen")
    async def reopen_creator_scene(scene_key: str, request: Request) -> JSONResponse:
        return await transition_creator_scene(scene_key, request, SceneStatus.OPEN)

    del list_creator_scenes, create_creator_scene
    del close_creator_scene, reopen_creator_scene

    @app.get("/v1/scenes/{scene_key}/timeline")
    async def get_scene_timeline(scene_key: str, request: Request) -> JSONResponse:
        if (
            browser_sessions is None
            or scene_timeline_query is None
            or not _browser_boundary(request, canonical_origin=canonical_origin)
        ):
            status = (
                403
                if browser_sessions is not None and scene_timeline_query is not None
                else 503
            )
            return JSONResponse(
                status_code=status,
                content=(
                    _rejected("AUTH_BROWSER_BOUNDARY")
                    if status == 403
                    else _unavailable("DEPENDENCY_SCENE_QUERY_UNAVAILABLE")
                ),
            )
        token = _bearer(request)
        try:
            if token is None:
                raise BrowserSessionViolation("AUTH_SESSION_REQUIRED")
            browser_sessions.verify(token)
        except BrowserSessionViolation as error:
            return JSONResponse(
                status_code=error.status_code,
                content=_rejected(error.code),
            )
        pairs = list(request.query_params.multi_items())
        names = [name for name, _value in pairs]
        if (
            set(names) - {"limit", "cursor"}
            or names.count("limit") != 1
            or names.count("cursor") > 1
        ):
            return JSONResponse(
                status_code=400,
                content=_rejected("INPUT_PAGE_LIMIT"),
            )
        values = dict(pairs)
        limit_text = values["limit"]
        if not limit_text.isascii() or not limit_text.isdecimal():
            return JSONResponse(
                status_code=400,
                content=_rejected("INPUT_PAGE_LIMIT"),
            )
        try:
            parsed_scene_key = SceneKey(scene_key)
        except SceneQueryViolation:
            return JSONResponse(
                status_code=404,
                content=_rejected("SCOPE_SCENE_NOT_VISIBLE"),
            )
        try:
            query = SceneTimelineQuery(
                scene_key=parsed_scene_key,
                limit=int(limit_text),
                cursor=(
                    OpaqueCursor.from_wire(values["cursor"])
                    if "cursor" in values
                    else None
                ),
            )
        except ContractViolation, SceneQueryViolation:
            code = "INPUT_CURSOR_INVALID" if "cursor" in values else "INPUT_PAGE_LIMIT"
            return JSONResponse(status_code=400, content=_rejected(code))
        try:
            page = await scene_timeline_query.query(query)
        except SceneQueryViolation as error:
            if error.code == "SCENE-NOT-VISIBLE":
                return JSONResponse(
                    status_code=404,
                    content=_rejected("SCOPE_SCENE_NOT_VISIBLE"),
                )
            if error.code == "SCENE-CURSOR-STALE":
                return JSONResponse(
                    status_code=409,
                    content=_rejected("CONFLICT_CURSOR_STALE"),
                )
            if error.code == "SCENE-CURSOR-INVALID":
                return JSONResponse(
                    status_code=400,
                    content=_rejected("INPUT_CURSOR_INVALID"),
                )
            return JSONResponse(
                status_code=503,
                content=_unavailable("DEPENDENCY_SCENE_QUERY_UNAVAILABLE"),
            )
        response = SceneTimelinePageResponse(
            contract_version="1.0",
            projection_version="scene-timeline.v5",
            scene_key=page.scene_key.value,
            items=[
                SceneTimelineItemResponse(
                    timeline_item_id=str(item.timeline_item_id),
                    source_kind=item.source_kind,
                    source_ref=str(item.source_ref),
                    status=item.status.value,
                    occurred_at=item.occurred_at.to_wire(),
                    operation_ref=(
                        str(item.operation_ref)
                        if item.operation_ref is not None
                        else None
                    ),
                    effect_ref=(
                        str(item.effect_ref) if item.effect_ref is not None else None
                    ),
                    message=item.message,
                )
                for item in page.items
            ],
            next_cursor=(
                page.next_cursor.to_wire() if page.next_cursor is not None else None
            ),
        )
        return JSONResponse(content=response.model_dump(mode="json", exclude_none=True))

    del get_scene_timeline

    def _other_human_party_wire(item: Any) -> OtherHumanPartyRecordResponse:
        return OtherHumanPartyRecordResponse(
            party_id=str(item.party_id),
            party_key=item.party_key,
            display_label=item.display_label,
            scene_count=item.scene_count,
            record_count=item.record_count,
            last_record_at=(
                None
                if item.last_record_at is None
                else Instant(item.last_record_at).to_wire()
            ),
        )

    async def _other_human_record_scope(
        request: Request,
    ) -> tuple[int, OpaqueCursor | None] | JSONResponse:
        if (
            browser_sessions is None
            or other_human_record_query is None
            or not _browser_boundary(request, canonical_origin=canonical_origin)
        ):
            status = (
                403
                if browser_sessions is not None and other_human_record_query is not None
                else 503
            )
            return JSONResponse(
                status_code=status,
                content=(
                    _rejected("AUTH_BROWSER_BOUNDARY")
                    if status == 403
                    else _unavailable("DEPENDENCY_OTHER_HUMAN_RECORD_UNAVAILABLE")
                ),
            )
        try:
            token = _bearer(request)
            if token is None:
                raise BrowserSessionViolation("AUTH_SESSION_REQUIRED")
            browser_sessions.verify(token)
            limit, _query, _kind, cursor = _life_query_parameters(
                request, allow_kind=False, allow_text=False
            )
            return limit, cursor
        except BrowserSessionViolation as error:
            return JSONResponse(
                status_code=error.status_code, content=_rejected(error.code)
            )
        except ContractViolation:
            return JSONResponse(status_code=400, content=_rejected("INPUT_PAGE"))

    @app.get("/v1/other-human-records")
    async def list_other_human_record_parties(request: Request) -> JSONResponse:
        scope = await _other_human_record_scope(request)
        if isinstance(scope, JSONResponse):
            return scope
        try:
            query = cast(OtherHumanRecordQueryPort, other_human_record_query)
            page = await query.list_parties(limit=scope[0], cursor=scope[1])
        except OtherHumanRecordViolation as error:
            status = 400 if error.code.endswith(("CURSOR", "LIMIT")) else 503
            return JSONResponse(
                status_code=status,
                content=(
                    _rejected("INPUT_PAGE")
                    if status == 400
                    else _unavailable("DEPENDENCY_OTHER_HUMAN_RECORD_UNAVAILABLE")
                ),
            )
        response = OtherHumanPartyRecordPageResponse(
            contract_version="1.0",
            projection_version="other-human-record.v1",
            items=[_other_human_party_wire(item) for item in page.items],
            next_cursor=None if page.next_cursor is None else page.next_cursor.value,
        )
        return JSONResponse(content=response.model_dump(mode="json", exclude_none=True))

    @app.get("/v1/other-human-records/{party_id}/scenes")
    async def list_other_human_record_scenes(
        party_id: str, request: Request
    ) -> JSONResponse:
        scope = await _other_human_record_scope(request)
        if isinstance(scope, JSONResponse):
            return scope
        try:
            query = cast(OtherHumanRecordQueryPort, other_human_record_query)
            page = await query.list_scenes(
                UUID(party_id), limit=scope[0], cursor=scope[1]
            )
        except ValueError:
            return JSONResponse(
                status_code=400, content=_rejected("INPUT_OTHER_HUMAN_PARTY")
            )
        except OtherHumanRecordViolation as error:
            if error.code.endswith("NOT-VISIBLE"):
                return JSONResponse(
                    status_code=404,
                    content=_rejected("SCOPE_OTHER_HUMAN_RECORD_NOT_VISIBLE"),
                )
            status = 400 if error.code.endswith(("CURSOR", "LIMIT", "SCOPE")) else 503
            return JSONResponse(
                status_code=status,
                content=(
                    _rejected("INPUT_PAGE")
                    if status == 400
                    else _unavailable("DEPENDENCY_OTHER_HUMAN_RECORD_UNAVAILABLE")
                ),
            )
        response = OtherHumanSceneRecordPageResponse(
            contract_version="1.0",
            projection_version="other-human-record.v1",
            party=_other_human_party_wire(page.party),
            items=[
                OtherHumanSceneRecordResponse(
                    scene_id=str(item.scene_id),
                    scene_key=item.scene_key,
                    status=cast(Literal["open", "closed"], item.status),
                    record_count=item.record_count,
                    last_record_at=(
                        None
                        if item.last_record_at is None
                        else Instant(item.last_record_at).to_wire()
                    ),
                )
                for item in page.items
            ],
            next_cursor=None if page.next_cursor is None else page.next_cursor.value,
        )
        return JSONResponse(content=response.model_dump(mode="json", exclude_none=True))

    @app.get("/v1/other-human-records/{party_id}/scenes/{scene_id}/timeline")
    async def get_other_human_record_timeline(
        party_id: str, scene_id: str, request: Request
    ) -> JSONResponse:
        scope = await _other_human_record_scope(request)
        if isinstance(scope, JSONResponse):
            return scope
        try:
            query = cast(OtherHumanRecordQueryPort, other_human_record_query)
            page = await query.timeline(
                UUID(party_id),
                UUID(scene_id),
                limit=scope[0],
                cursor=scope[1],
            )
        except ValueError:
            return JSONResponse(
                status_code=400,
                content=_rejected("INPUT_OTHER_HUMAN_RECORD_SCOPE"),
            )
        except OtherHumanRecordViolation as error:
            if error.code.endswith("NOT-VISIBLE"):
                return JSONResponse(
                    status_code=404,
                    content=_rejected("SCOPE_OTHER_HUMAN_RECORD_NOT_VISIBLE"),
                )
            status = 400 if error.code.endswith(("CURSOR", "LIMIT", "SCOPE")) else 503
            return JSONResponse(
                status_code=status,
                content=(
                    _rejected("INPUT_PAGE")
                    if status == 400
                    else _unavailable("DEPENDENCY_OTHER_HUMAN_RECORD_UNAVAILABLE")
                ),
            )
        response = OtherHumanTimelineRecordPageResponse(
            contract_version="1.0",
            projection_version="other-human-record.v1",
            party_id=str(page.party_id),
            scene_id=str(page.scene_id),
            items=[
                OtherHumanTimelineRecordResponse(
                    timeline_item_id=str(item.timeline_item_id),
                    source_ref=str(item.source_ref),
                    direction=item.direction.value,
                    status=cast(
                        Literal["accepted", "completed", "failed", "unknown"],
                        item.result_status,
                    ),
                    text=item.text,
                    occurred_at=Instant(item.occurred_at).to_wire(),
                )
                for item in page.items
            ],
            next_cursor=None if page.next_cursor is None else page.next_cursor.value,
        )
        return JSONResponse(content=response.model_dump(mode="json", exclude_none=True))

    del list_other_human_record_parties, list_other_human_record_scenes
    del get_other_human_record_timeline

    def other_human_failure(error: OtherHumanInputViolation) -> JSONResponse:
        if error.code == "SCOPE-DATA-RIGHTS-BLOCKED":
            return JSONResponse(
                status_code=403,
                content=_rejected("SCOPE_DATA_RIGHTS_BLOCKED"),
            )
        if error.code.startswith("SCOPE-"):
            return JSONResponse(
                status_code=404, content=_rejected("SCOPE_OTHER_HUMAN_NOT_VISIBLE")
            )
        if error.code.startswith("IDEMPOTENCY-"):
            return JSONResponse(
                status_code=409, content=_rejected("CONFLICT_OTHER_HUMAN_IDEMPOTENCY")
            )
        if error.code.startswith(("CON-", "OTHER-HUMAN-INPUT-")):
            return JSONResponse(
                status_code=400, content=_rejected("INPUT_OTHER_HUMAN_REQUEST")
            )
        return JSONResponse(
            status_code=503,
            content=_unavailable("DEPENDENCY_OTHER_HUMAN_INPUT_UNAVAILABLE"),
        )

    @app.post("/v1/local/other-humans/parties")
    async def register_other_human_party(request: Request) -> JSONResponse:
        if other_human_input is None:
            return JSONResponse(
                status_code=503,
                content=_unavailable("DEPENDENCY_OTHER_HUMAN_INPUT_UNAVAILABLE"),
            )
        try:
            value = await _local_json_object(request, request_body_max_bytes)
            if set(value) != {"party_key", "display_label", "role"}:
                raise OtherHumanInputViolation("OTHER-HUMAN-INPUT-BODY")
            view = await other_human_input.register_party(
                RegisterOtherHumanPartyCommand(
                    OtherHumanPartyKey(value["party_key"]),
                    value["display_label"],
                    value["role"],
                    TraceId(secrets.token_hex(16)),
                )
            )
        except (ContractViolation, OtherHumanInputViolation) as error:
            if isinstance(error, OtherHumanInputViolation):
                return other_human_failure(error)
            return JSONResponse(
                status_code=400, content=_rejected("INPUT_OTHER_HUMAN_PARTY")
            )
        return JSONResponse(
            status_code=201,
            content={
                "contract_version": "1.0",
                "party_id": str(view.party_id),
                "party_key": view.party_key.value,
                "display_label": view.display_label,
                "role": "other_human",
                "identity_assurance": view.identity_assurance,
            },
        )

    @app.put("/v1/local/other-humans/{party_key}/scenes/{scene_key}")
    async def set_other_human_scene(
        party_key: str, scene_key: str, request: Request
    ) -> JSONResponse:
        if other_human_input is None:
            return JSONResponse(
                status_code=503,
                content=_unavailable("DEPENDENCY_OTHER_HUMAN_INPUT_UNAVAILABLE"),
            )
        try:
            value = await _local_json_object(request, request_body_max_bytes)
            if set(value) != {"status"}:
                raise OtherHumanInputViolation("OTHER-HUMAN-INPUT-BODY")
            view = await other_human_input.set_scene(
                OtherHumanSceneCommand(
                    OtherHumanPartyKey(party_key),
                    SceneKey(scene_key),
                    SceneStatus(value["status"]),
                    TraceId(secrets.token_hex(16)),
                )
            )
        except (ValueError, ContractViolation, OtherHumanInputViolation) as error:
            if isinstance(error, OtherHumanInputViolation):
                return other_human_failure(error)
            return JSONResponse(
                status_code=400, content=_rejected("INPUT_OTHER_HUMAN_SCENE")
            )
        return JSONResponse(
            content={
                "contract_version": "1.0",
                "scene_id": str(view.scene_id),
                "party_id": str(view.party_id),
                "scene_key": view.scene_key.value,
                "status": view.status.value,
            }
        )

    @app.post("/v1/local/other-humans/{party_key}/scenes/{scene_key}/messages")
    async def accept_other_human_message(
        party_key: str, scene_key: str, request: Request
    ) -> JSONResponse:
        if other_human_input is None:
            return JSONResponse(
                status_code=503,
                content=_unavailable("DEPENDENCY_OTHER_HUMAN_INPUT_UNAVAILABLE"),
            )
        idempotency_value = _single_header(request, b"idempotency-key")
        if idempotency_value is None:
            return JSONResponse(
                status_code=400, content=_rejected("INPUT_IDEMPOTENCY_KEY")
            )
        try:
            value = await _local_json_object(request, request_body_max_bytes)
            if set(value) != {"message"}:
                raise OtherHumanInputViolation("OTHER-HUMAN-INPUT-BODY")
            accepted = await other_human_input.accept(
                OtherHumanInputCommand(
                    OtherHumanPartyKey(party_key),
                    SceneKey(scene_key),
                    value["message"],
                    IdempotencyKey(idempotency_value),
                    TraceId(secrets.token_hex(16)),
                )
            )
        except (ContractViolation, OtherHumanInputViolation) as error:
            if isinstance(error, OtherHumanInputViolation):
                return other_human_failure(error)
            return JSONResponse(
                status_code=400, content=_rejected("INPUT_OTHER_HUMAN_MESSAGE")
            )
        return JSONResponse(
            status_code=202,
            content={
                "contract_version": "1.0",
                "party_id": str(accepted.party_id),
                "scene_id": str(accepted.scene_id),
                "interaction_id": str(accepted.interaction_id.value),
                "evidence_id": str(accepted.evidence_id),
                "opportunity_id": str(accepted.opportunity_id),
                "newly_accepted": accepted.newly_accepted,
            },
        )

    @app.post("/v1/local/other-humans/{party_key}/data-rights/orders")
    async def create_other_human_data_rights_order(
        party_key: str, request: Request
    ) -> JSONResponse:
        if data_rights is None:
            return JSONResponse(
                status_code=503,
                content=_unavailable("DEPENDENCY_DATA_RIGHTS_UNAVAILABLE"),
            )
        idempotency_value = _single_header(request, b"idempotency-key")
        if idempotency_value is None:
            return JSONResponse(
                status_code=400, content=_rejected("INPUT_IDEMPOTENCY_KEY")
            )
        try:
            value = await _local_json_object(request, request_body_max_bytes)
            if set(value) != {"order_kind"}:
                raise DataRightsViolation("DATA-RIGHTS-COMMAND")
            result = await data_rights.request_other_human(
                OtherHumanPartyKey(party_key),
                DataRightsOrderCommand(
                    DataRightsOrderKind(value["order_kind"]),
                    IdempotencyKey(idempotency_value),
                    TraceId(secrets.token_hex(16)),
                ),
            )
        except (ValueError, ContractViolation, DataRightsViolation) as error:
            if isinstance(error, DataRightsViolation):
                return _data_rights_error(error)
            return JSONResponse(
                status_code=400,
                content=_rejected("INPUT_DATA_RIGHTS_INVALID"),
            )
        return JSONResponse(
            status_code=201 if result.newly_created else 200,
            content=_data_rights_response(result).model_dump(mode="json"),
        )

    @app.get("/v1/local/other-humans/{party_key}/data-rights/orders")
    async def list_other_human_data_rights_orders(party_key: str) -> JSONResponse:
        if data_rights is None:
            return JSONResponse(
                status_code=503,
                content=_unavailable("DEPENDENCY_DATA_RIGHTS_UNAVAILABLE"),
            )
        try:
            details = await data_rights.list_other_human(OtherHumanPartyKey(party_key))
        except (ValueError, DataRightsViolation) as error:
            if isinstance(error, DataRightsViolation):
                return _data_rights_error(error)
            return JSONResponse(
                status_code=400, content=_rejected("INPUT_DATA_RIGHTS_INVALID")
            )
        return JSONResponse(
            content=DataRightsOrderCollectionResponse(
                contract_version="1.0",
                projection_version="data-rights-order.v2",
                orders=[_data_rights_detail_response(detail) for detail in details],
            ).model_dump(mode="json")
        )

    @app.get("/v1/local/other-humans/{party_key}/data-rights/orders/{order_id}")
    async def get_other_human_data_rights_order(
        party_key: str, order_id: str
    ) -> JSONResponse:
        if data_rights is None:
            return JSONResponse(
                status_code=503,
                content=_unavailable("DEPENDENCY_DATA_RIGHTS_UNAVAILABLE"),
            )
        try:
            result = await data_rights.detail_other_human(
                OtherHumanPartyKey(party_key), UUID(order_id)
            )
        except (ValueError, ContractViolation, DataRightsViolation) as error:
            if isinstance(error, DataRightsViolation):
                return _data_rights_error(error)
            return JSONResponse(
                status_code=400,
                content=_rejected("INPUT_DATA_RIGHTS_INVALID"),
            )
        if result is None:
            return JSONResponse(
                status_code=404,
                content=_rejected("SCOPE_DATA_RIGHTS_ORDER_NOT_FOUND"),
            )
        return JSONResponse(
            content=_data_rights_detail_response(result).model_dump(mode="json")
        )

    del register_other_human_party, set_other_human_scene, accept_other_human_message
    del create_other_human_data_rights_order, list_other_human_data_rights_orders
    del get_other_human_data_rights_order

    @app.post("/v1/scenes/{scene_key}/messages")
    async def accept_creator_message(
        scene_key: str,
        request: Request,
    ) -> JSONResponse:
        if (
            browser_sessions is None
            or creator_input is None
            or not _browser_boundary(request, canonical_origin=canonical_origin)
        ):
            status = 403 if browser_sessions is not None else 503
            return JSONResponse(
                status_code=status,
                content=(
                    _rejected("AUTH_BROWSER_BOUNDARY")
                    if status == 403
                    else _unavailable("DEPENDENCY_INPUT_ACCEPTANCE_UNAVAILABLE")
                ),
            )
        token = _bearer(request)
        try:
            if token is None:
                raise BrowserSessionViolation("AUTH_SESSION_REQUIRED")
            browser_sessions.verify(token)
        except BrowserSessionViolation as error:
            return JSONResponse(
                status_code=error.status_code,
                content=_rejected(error.code),
            )
        idempotency_value = _single_header(request, b"idempotency-key")
        if idempotency_value is None:
            return JSONResponse(
                status_code=400,
                content=_rejected("INPUT_IDEMPOTENCY_KEY"),
            )
        try:
            model = await _creator_input_request(request, request_body_max_bytes)
            command = CreatorInputCommand(
                scene_key=scene_key,
                message=model.message,
                idempotency_key=IdempotencyKey(idempotency_value),
                trace_id=TraceId(secrets.token_hex(16)),
            )
            acceptance = await creator_input.accept(command)
        except (ContractViolation, CreatorInputViolation) as error:
            if isinstance(error, ContractViolation):
                status, content = 400, _rejected("INPUT_IDEMPOTENCY_KEY")
            else:
                status, content = _input_failure(error)
            emit("creator.input.rejected")
            return JSONResponse(status_code=status, content=content)
        emit(
            "creator.input.accepted"
            if acceptance.newly_accepted
            else "creator.input.idempotent"
        )
        if creator_events is not None and acceptance.newly_accepted:
            try:
                await creator_events.notify(
                    CreatorProjectionInvalidation(
                        CreatorEventResourceKind.OPERATION,
                        str(acceptance.opportunity_id),
                        Instant(datetime.now(UTC)),
                        "creator-operation.v1",
                    )
                )
            except Exception:
                emit("creator.operation.notification_failed")
        return JSONResponse(status_code=202, content=_accepted_wire(acceptance))

    del accept_creator_message

    @app.post("/v1/scenes/{scene_key}/codex-tasks")
    async def accept_creator_codex_task(
        scene_key: str,
        request: Request,
    ) -> JSONResponse:
        if browser_sessions is None or codex_task_admission is None:
            return JSONResponse(
                status_code=503,
                content=_unavailable("DEPENDENCY_CODEX_TASK_UNAVAILABLE"),
            )
        if not _browser_boundary(request, canonical_origin=canonical_origin):
            return JSONResponse(
                status_code=403,
                content=_rejected("AUTH_BROWSER_BOUNDARY"),
            )
        token = _bearer(request)
        try:
            if token is None:
                raise BrowserSessionViolation("AUTH_SESSION_REQUIRED")
            browser_sessions.verify(token)
        except BrowserSessionViolation as error:
            return JSONResponse(
                status_code=error.status_code,
                content=_rejected(error.code),
            )
        idempotency_value = _single_header(request, b"idempotency-key")
        if idempotency_value is None:
            return JSONResponse(
                status_code=400,
                content=_rejected("INPUT_IDEMPOTENCY_KEY"),
            )
        try:
            model = await _creator_codex_task_request(request, request_body_max_bytes)
            acceptance = await codex_task_admission.accept(
                CreatorCodexTaskCommand(
                    scene_key,
                    model.objective,
                    IdempotencyKey(idempotency_value),
                    TraceId(secrets.token_hex(16)),
                    CodexModel(model.model_id),
                    CodexReasoningEffort(model.reasoning_effort),
                    model.web_search,
                )
            )
        except (ContractViolation, CodexDelegationViolation) as error:
            if isinstance(error, ContractViolation):
                status, content = 400, _rejected("INPUT_IDEMPOTENCY_KEY")
                emit("creator.codex_task.rejected")
                return JSONResponse(status_code=status, content=content)
            code = getattr(error, "code", "CODEX-TASK-REQUEST")
            if code == "CODEX-TASK-IDEMPOTENCY":
                status, content = 409, _rejected("IDEMPOTENCY_MISMATCH")
            elif code == "CODEX-TASK-REQUEST-SIZE":
                status, content = 413, _rejected("INPUT_MESSAGE_TOO_LARGE")
            elif code == "CODEX-TASK-REQUEST":
                status, content = 400, _rejected("INPUT_MESSAGE_INVALID")
            elif code == "CODEX-TASK-SUBJECT":
                status, content = 404, _rejected("SCOPE_SCENE_NOT_VISIBLE")
            else:
                status, content = 503, _unavailable("DEPENDENCY_CODEX_TASK_UNAVAILABLE")
            emit("creator.codex_task.rejected")
            return JSONResponse(status_code=status, content=content)
        emit(
            "creator.codex_task.accepted"
            if acceptance.newly_accepted
            else "creator.codex_task.idempotent"
        )
        return JSONResponse(status_code=202, content=_accepted_wire(acceptance))

    del accept_creator_codex_task

    @app.get("/v1/operations/{result_ref}")
    async def get_creator_operation(
        result_ref: str,
        request: Request,
    ) -> JSONResponse:
        if (
            browser_sessions is None
            or creator_operations is None
            or not _browser_boundary(request, canonical_origin=canonical_origin)
        ):
            status = 403 if browser_sessions is not None else 503
            return JSONResponse(
                status_code=status,
                content=(
                    _rejected("AUTH_BROWSER_BOUNDARY")
                    if status == 403
                    else _unavailable("DEPENDENCY_INPUT_ACCEPTANCE_UNAVAILABLE")
                ),
            )
        token = _bearer(request)
        try:
            if token is None:
                raise BrowserSessionViolation("AUTH_SESSION_REQUIRED")
            browser_sessions.verify(token)
            operation_id = OpportunityId(UUID(result_ref))
            operation = await creator_operations.get(operation_id)
        except BrowserSessionViolation as error:
            return JSONResponse(
                status_code=error.status_code,
                content=_rejected(error.code),
            )
        except (ValueError, CreatorInputViolation) as error:
            if isinstance(error, CreatorInputViolation):
                status, content = _input_failure(error)
            else:
                status, content = 404, _rejected("SCOPE_OPERATION_NOT_VISIBLE")
            return JSONResponse(status_code=status, content=content)
        return JSONResponse(content=_operation_wire(operation))

    del get_creator_operation

    @app.get("/v1/effects/{effect_id}")
    async def get_effect(effect_id: str, request: Request) -> JSONResponse:
        if (
            browser_sessions is None
            or effect_ledger is None
            or not _browser_boundary(request, canonical_origin=canonical_origin)
        ):
            status = 403 if browser_sessions is not None else 503
            return JSONResponse(
                status_code=status,
                content=(
                    _rejected("AUTH_BROWSER_BOUNDARY")
                    if status == 403
                    else _unavailable("DEPENDENCY_EFFECT_QUERY_UNAVAILABLE")
                ),
            )
        token = _bearer(request)
        try:
            if token is None:
                raise BrowserSessionViolation("AUTH_SESSION_REQUIRED")
            metadata = browser_sessions.verify(token)
            view = await effect_ledger.get_effect(
                EffectId(UUID(effect_id)), creator_party_id=metadata.creator_party_id
            )
        except BrowserSessionViolation as error:
            return JSONResponse(
                status_code=error.status_code, content=_rejected(error.code)
            )
        except (ValueError, EffectViolation) as error:
            if (
                isinstance(error, EffectViolation)
                and error.code != "SCOPE-EFFECT-NOT-VISIBLE"
            ):
                return JSONResponse(
                    status_code=503,
                    content=_unavailable("DEPENDENCY_EFFECT_QUERY_UNAVAILABLE"),
                )
            return JSONResponse(
                status_code=404, content=_rejected("SCOPE_EFFECT_NOT_VISIBLE")
            )
        return JSONResponse(
            content=EffectResponse(
                contract_version="1.0",
                projection_version="creator-effect.v2",
                effect_id=str(view.effect_id.value),
                root_operation_ref=str(view.root_operation_ref),
                capability_request_ref=str(view.capability_request_ref),
                grant_ref=str(view.grant_ref),
                capability_kind=view.capability_kind,
                effect_kind=view.effect_kind,
                status=view.status.value,
                verification_status=view.verification_status.value,
                registered_at=view.registered_at.to_wire(),
                cancelled_at=(
                    view.cancelled_at.to_wire()
                    if view.cancelled_at is not None
                    else None
                ),
                attempt_count=view.attempt_count,
                last_observation_kind=(
                    view.last_observation_kind.value
                    if view.last_observation_kind is not None
                    else None
                ),
                last_observation_reliability=(
                    view.last_observation_reliability.value
                    if view.last_observation_reliability is not None
                    else None
                ),
                verification_action=view.verification_action,
                settled_at=(
                    view.settled_at.to_wire() if view.settled_at is not None else None
                ),
                response_text=view.response_text,
                model_id=view.model_id,
                sdk_identity=view.sdk_identity,
                source_tree_digest=(
                    view.source_tree_digest.value
                    if view.source_tree_digest is not None
                    else None
                ),
                result_tree_digest=(
                    view.result_tree_digest.value
                    if view.result_tree_digest is not None
                    else None
                ),
                patch_digest=(
                    view.patch_digest.value if view.patch_digest is not None else None
                ),
                changed_path_count=view.changed_path_count,
                validation_status=view.validation_status,
                cleanup_status=view.cleanup_status,
                result_acceptance_status=view.result_acceptance_status,
            ).model_dump(exclude_none=True)
        )

    del get_effect

    @app.get("/v1/effects/{effect_id}/artifacts/{artifact_kind}")
    async def get_effect_artifact(
        effect_id: str, artifact_kind: str, request: Request
    ) -> Response:
        if (
            browser_sessions is None
            or effect_ledger is None
            or not _browser_boundary(request, canonical_origin=canonical_origin)
        ):
            status = 403 if browser_sessions is not None else 503
            return JSONResponse(
                status_code=status,
                content=(
                    _rejected("AUTH_BROWSER_BOUNDARY")
                    if status == 403
                    else _unavailable("DEPENDENCY_EFFECT_QUERY_UNAVAILABLE")
                ),
            )
        token = _bearer(request)
        try:
            if token is None:
                raise BrowserSessionViolation("AUTH_SESSION_REQUIRED")
            metadata = browser_sessions.verify(token)
            kind = EffectArtifactKind(artifact_kind)
            artifact = await effect_ledger.read_artifact(
                EffectId(UUID(effect_id)),
                creator_party_id=metadata.creator_party_id,
                kind=kind,
            )
            content, media_type = _creator_visible_codex_artifact(
                kind,
                artifact.content,
                artifact.media_type,
            )
        except BrowserSessionViolation as error:
            return JSONResponse(
                status_code=error.status_code, content=_rejected(error.code)
            )
        except UnicodeDecodeError:
            return JSONResponse(
                status_code=503,
                content=_unavailable("DEPENDENCY_EFFECT_QUERY_UNAVAILABLE"),
            )
        except (ValueError, EffectViolation) as error:
            if isinstance(error, EffectViolation) and error.code not in {
                "SCOPE-EFFECT-NOT-VISIBLE",
                "EFFECT-ARTIFACT-KIND",
            }:
                return JSONResponse(
                    status_code=503,
                    content=_unavailable("DEPENDENCY_EFFECT_QUERY_UNAVAILABLE"),
                )
            return JSONResponse(
                status_code=404, content=_rejected("SCOPE_EFFECT_NOT_VISIBLE")
            )
        return Response(content=content, media_type=media_type)

    del get_effect_artifact

    @app.get("/v1/scenes/{scene_key}/events")
    async def get_scene_events(
        scene_key: str,
        request: Request,
    ) -> Response:
        if (
            browser_sessions is None
            or scene_timeline_query is None
            or creator_events is None
        ):
            return JSONResponse(
                status_code=503,
                content=_unavailable("DEPENDENCY_EVENT_STREAM_UNAVAILABLE"),
            )
        if not _browser_boundary(request, canonical_origin=canonical_origin):
            return JSONResponse(
                status_code=403,
                content=_rejected("AUTH_BROWSER_BOUNDARY"),
            )
        if request.headers.get("accept") != "text/event-stream":
            return JSONResponse(
                status_code=400,
                content=_rejected("INPUT_EVENT_STREAM_ACCEPT"),
            )
        try:
            last_event_id = parse_last_event_id(request.scope["headers"])
        except CreatorEventBrokerViolation as error:
            emit("creator.event_stream.parser_failure")
            return JSONResponse(
                status_code=error.status_code,
                content=_rejected(error.code),
            )
        token = _bearer(request)
        try:
            if token is None:
                raise BrowserSessionViolation("AUTH_SESSION_REQUIRED")
            browser_sessions.verify(token)
        except BrowserSessionViolation as error:
            return JSONResponse(
                status_code=error.status_code,
                content=_rejected(error.code),
            )
        try:
            parsed_scene_key = SceneKey(scene_key)
        except SceneQueryViolation:
            return JSONResponse(
                status_code=404,
                content=_rejected("SCOPE_SCENE_NOT_VISIBLE"),
            )
        try:
            await scene_timeline_query.query(
                SceneTimelineQuery(scene_key=parsed_scene_key, limit=1)
            )
        except SceneQueryViolation as error:
            if error.code == "SCENE-NOT-VISIBLE":
                return JSONResponse(
                    status_code=404,
                    content=_rejected("SCOPE_SCENE_NOT_VISIBLE"),
                )
            return JSONResponse(
                status_code=503,
                content=_unavailable("DEPENDENCY_EVENT_STREAM_UNAVAILABLE"),
            )
        try:
            subscription = await creator_events.subscribe(last_event_id)
        except CreatorEventBrokerViolation as error:
            emit(
                "creator.event_stream.gap"
                if error.status_code == 409
                else "creator.event_stream.parser_failure"
            )
            return JSONResponse(
                status_code=error.status_code,
                content=_rejected(error.code),
            )
        return StreamingResponse(
            stream_creator_events(
                subscription,
                sessions=browser_sessions,
                token=token,
                diagnostic=emit,
            ),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-store",
                "X-Accel-Buffering": "no",
            },
        )

    del get_scene_events

    @app.get("/ui", include_in_schema=False)
    async def creator_redirect() -> RedirectResponse:
        return RedirectResponse("/ui/", status_code=308)

    @app.get("/ui/", include_in_schema=False)
    async def creator_index() -> Response:
        asset = cast(StaticAsset, assets.get("index.html"))
        return Response(
            content=asset.content,
            media_type=asset.media_type,
            headers={"Cache-Control": asset.cache_control},
        )

    @app.get("/ui/{asset_path:path}", include_in_schema=False)
    async def creator_asset(asset_path: str) -> Response:
        asset = assets.get(asset_path)
        if asset is None:
            return Response(status_code=404)
        return Response(
            content=asset.content,
            media_type=asset.media_type,
            headers={"Cache-Control": asset.cache_control},
        )

    route_handlers = (
        enforce_local_boundary,
        health_live,
        health_ready,
        create_browser_session,
        current_browser_session,
        get_runtime_status,
        get_subject_summary,
        creator_redirect,
        creator_index,
        creator_asset,
    )
    del route_handlers
    return app


__all__ = ("create_runtime_app",)
