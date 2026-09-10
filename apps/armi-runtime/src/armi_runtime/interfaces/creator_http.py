"""Shared Creator HTTP types, parsing, and wire projection helpers."""

from __future__ import annotations

import json
import re
import secrets
from collections.abc import Awaitable, Callable
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any, Literal, Protocol, TypedDict, cast
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
    CreatorExportViolation,
    DataRightsOrderCommand,
    DataRightsOrderKind,
    DataRightsOrderPort,
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
    CreatorOperationQueryPort,
    CreatorSceneCreateCommand,
    CreatorScenePort,
    CreatorSceneStatusCommand,
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
    AppliedOutcome,
    ContractViolation,
    IdempotencyKey,
    Instant,
    OpaqueCursor,
    ResultRef,
    TraceId,
)
from armi_material.api import CreatorLifeMaterialItem, MaterialViolation
from armi_memory.api import MemoryReadPort, MemoryViolation
from armi_prompt.api import (
    CreatorPromptDeactivateCommand,
    CreatorPromptPort,
    CreatorPromptRevisionCommand,
    CreatorPromptViolation,
    PromptKind,
)
from armi_relationship.api import RelationshipReadPort, RelationshipViolation
from armi_sleep.api import (
    CreatorEmergencyWakePort,
    CreatorMaintenanceQueryPort,
    CreatorMaintenanceViolation,
)
from armi_subject_state.api import SubjectSummary
from fastapi import FastAPI, Query, Request, Security
from fastapi.responses import (
    JSONResponse,
    RedirectResponse,
    Response,
    StreamingResponse,
)
from fastapi.security import HTTPBearer
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
    CreatorRelationshipCurrentResponse,
    CreatorRelationshipItemResponse,
    CreatorRelationshipTimelineResponse,
    CreatorSceneCollectionResponse,
    CreatorSceneCreateRequest,
    CreatorSceneResponse,
    DataRightsOrderCollectionResponse,
    DataRightsOrderDetailResponse,
    DataRightsOrderRequest,
    DataRightsOrderResponse,
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
from armi_runtime.application.creator_projection import (
    _accepted_wire,
    _boundary_message,
    _creator_export_error,
    _creator_export_response,
    _creator_prompt_error,
    _creator_prompt_response,
    _data_rights_detail_response,
    _data_rights_error,
    _data_rights_response,
    _input_failure,
    _outcome_common,
    _rejected,
    _relationship_revision_response,
    _scene_wire,
    _strict_object_pairs,
    _unavailable,
    operation_wire,
)

from .bounded_http import read_bounded_body
from .browser_sessions import (
    BrowserSessionStore,
    BrowserSessionViolation,
    SessionMetadata,
)
from .creator_events import (
    CreatorEventBroker,
    CreatorEventBrokerViolation,
    parse_last_event_id,
    stream_creator_events,
)
from .static_assets import StaticAsset, StaticAssetStore

_BEARER = re.compile("^Bearer ([\\x21-\\x7e]{1,4096})$", re.ASCII)
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
    "Content-Security-Policy": "default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self'; font-src 'self'; connect-src 'self'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'",
    "Cross-Origin-Opener-Policy": "same-origin",
    "Permissions-Policy": "camera=(), display-capture=(), geolocation=(), microphone=(), payment=(), usb=()",
    "Referrer-Policy": "no-referrer",
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
}
AsyncCallback = Callable[[], Awaitable[None]]
ReadinessProvider = Callable[[], Readiness]
RuntimeStatusProvider = Callable[[], RuntimeStatusResponse]
QQChannelHealthProvider = Callable[[], Awaitable[QQChannelHealthResponse]]
QQChannelControlProvider = Callable[[str], Awaitable[QQChannelHealthResponse]]
LiveVoiceControlProvider = Callable[[str], Awaitable[LiveVoiceStatusResponse]]
LiveVisionControlProvider = Callable[
    [str, str | None], Awaitable[LiveVisionStatusResponse]
]
LiveVisionObservationProvider = Callable[
    [str, str], Awaitable[LiveVisionObservationResponse]
]
LiveVisionObservationQueryProvider = Callable[
    [UUID], Awaitable[LiveVisionObservationResponse | None]
]
LiveVisionPreviewProvider = Callable[[str], bytes | None]
SubjectSummaryProvider = Callable[[], Awaitable[SubjectSummary]]
SecurityEvent = Callable[[str], None]


class CreatorLifeMaterialQueryPort(Protocol):
    async def get_creator_visible(
        self, material_id: UUID
    ) -> CreatorLifeMaterialItem | None: ...


class _SessionMetadataWire(TypedDict):
    contract_version: Literal["1.0"]
    environment_id: str
    creator_party_id: str
    default_scene_key: str
    issued_at: str
    expires_at: str


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
        and (request.headers.get("sec-fetch-dest") == "empty")
        and (
            request.method not in {"POST", "PUT", "PATCH", "DELETE"}
            or request.headers.get("origin") == canonical_origin
        )
    )


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
    request: Request, maximum_bytes: int
) -> CreatorInputRequest:
    if request.headers.get("content-type") != "application/json":
        raise CreatorInputViolation("INPUT-CONTENT-TYPE")
    body = await read_bounded_body(
        request,
        maximum_bytes=maximum_bytes,
        timeout_seconds=float(request.scope.get("armi.body_timeout_seconds", 10)),
    )
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
    body = await read_bounded_body(
        request,
        maximum_bytes=maximum_bytes,
        timeout_seconds=float(request.scope.get("armi.body_timeout_seconds", 10)),
    )
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
    request: Request, maximum_bytes: int
) -> CreatorSceneCreateRequest:
    if request.headers.get("content-type") != "application/json":
        raise SceneQueryViolation("CON-SCENE-CONTENT-TYPE")
    body = await read_bounded_body(
        request,
        maximum_bytes=min(maximum_bytes, 1024),
        timeout_seconds=float(request.scope.get("armi.body_timeout_seconds", 10)),
    )
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


async def _creator_boundary_request(
    request: Request, maximum_bytes: int
) -> CreatorRelationshipBoundaryRequest:
    if request.headers.get("content-type") != "application/json":
        raise CreatorInputViolation("INPUT-CONTENT-TYPE")
    body = await read_bounded_body(
        request,
        maximum_bytes=min(maximum_bytes, 4096),
        timeout_seconds=float(request.scope.get("armi.body_timeout_seconds", 10)),
    )
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


async def _creator_codex_task_request(
    request: Request, maximum_bytes: int
) -> CreatorCodexTaskRequest:
    if request.headers.get("content-type") != "application/json":
        raise CodexDelegationViolation("CODEX-TASK-REQUEST")
    body = await read_bounded_body(
        request,
        maximum_bytes=min(maximum_bytes, 20 * 1024),
        timeout_seconds=float(request.scope.get("armi.body_timeout_seconds", 10)),
    )
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


async def _creator_prompt_revision_request(
    request: Request, maximum_bytes: int
) -> CreatorPromptRevisionRequest:
    if request.headers.get("content-type") != "application/json":
        raise CreatorPromptViolation("CON-PROMPT-CONTENT-TYPE")
    body = await read_bounded_body(
        request,
        maximum_bytes=maximum_bytes,
        timeout_seconds=float(request.scope.get("armi.body_timeout_seconds", 10)),
    )
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
    request: Request, maximum_bytes: int
) -> CreatorPromptDeactivateRequest:
    if request.headers.get("content-type") != "application/json":
        raise CreatorPromptViolation("CON-PROMPT-CONTENT-TYPE")
    body = await read_bounded_body(
        request,
        maximum_bytes=min(maximum_bytes, 1024),
        timeout_seconds=float(request.scope.get("armi.body_timeout_seconds", 10)),
    )
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
    request: Request, maximum_bytes: int
) -> CreatorExportRequest:
    if request.headers.get("content-type") != "application/json":
        raise CreatorExportViolation("CREATOR-EXPORT-COMMAND")
    body = await read_bounded_body(
        request,
        maximum_bytes=min(maximum_bytes, 4096),
        timeout_seconds=float(request.scope.get("armi.body_timeout_seconds", 10)),
    )
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


async def _data_rights_request(
    request: Request, maximum_bytes: int
) -> DataRightsOrderRequest:
    if request.headers.get("content-type") != "application/json":
        raise DataRightsViolation("DATA-RIGHTS-COMMAND")
    body = await read_bounded_body(
        request,
        maximum_bytes=min(maximum_bytes, 1024),
        timeout_seconds=float(request.scope.get("armi.body_timeout_seconds", 10)),
    )
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


def _life_query_parameters(
    request: Request, *, allow_kind: bool, allow_text: bool
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
    return (limit, query_text, record_kind, cursor)


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
    "DataRightsRetryCommand",
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
    "LiveVisionObservationRequest",
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
    "QQChannelControlProvider",
    "QQChannelHealthProvider",
    "QQChannelHealthResponse",
    "Query",
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
    "_strict_object_pairs",
    "_unavailable",
    "asynccontextmanager",
    "cast",
    "datetime",
    "operation_wire",
    "parse_last_event_id",
    "re",
    "secrets",
    "stream_creator_events",
    "uuid7",
)
