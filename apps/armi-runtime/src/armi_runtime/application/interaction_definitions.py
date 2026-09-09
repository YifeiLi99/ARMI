"""Explicit Creator operation contracts shared by Web, CLI and MCP."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, TypeAliasType

from pydantic import BaseModel, TypeAdapter

from .artifact_transfer import ArtifactChunk, ArtifactReadWindow
from .creator_contract import (
    AcceptedOutcomeResponse,
    AppliedOutcomeResponse,
    CapabilityRequestDecisionRequest,
    CapabilityRequestPageResponse,
    CreatorActivityPageResponse,
    CreatorActivityTimelineResponse,
    CreatorCodexTaskRequest,
    CreatorExportRequest,
    CreatorExportResponse,
    CreatorInputRequest,
    CreatorLifeMaterialResponse,
    CreatorMaintenanceStatusResponse,
    CreatorMaintenanceTimelineResponse,
    CreatorMemoryPageResponse,
    CreatorMemoryTimelineResponse,
    CreatorPromptDeactivateRequest,
    CreatorPromptResponse,
    CreatorPromptRevisionRequest,
    CreatorRelationshipBoundaryRequest,
    CreatorRelationshipCurrentResponse,
    CreatorRelationshipTimelineResponse,
    CreatorSceneCollectionResponse,
    CreatorSceneCreateRequest,
    CreatorSceneResponse,
    DataRightsOrderCollectionResponse,
    DataRightsOrderDetailResponse,
    DataRightsOrderRequest,
    DataRightsOrderResponse,
    EffectResponse,
    LifeRecordPageResponse,
    LiveResponse,
    LiveVisionObservationResponse,
    LiveVisionStatusResponse,
    LiveVoiceStatusResponse,
    OperationOutcomeResponse,
    OtherHumanPartyRecordPageResponse,
    OtherHumanSceneRecordPageResponse,
    OtherHumanTimelineRecordPageResponse,
    QQChannelHealthResponse,
    ReadyResponse,
    RejectedOutcomeResponse,
    RuntimeStatusResponse,
    SceneTimelinePageResponse,
    SubjectSummaryResponse,
    UnavailableOutcomeResponse,
)
from .creator_media import (
    MediaMessageRequest,
    MediaMessageResult,
    MediaOrOperationResult,
)


@dataclass(frozen=True, slots=True)
class OperationContract:
    operation_id: str
    group: str
    action: str
    method: str
    path: str
    parameters: tuple[dict[str, Any], ...]
    body_model: type[BaseModel] | None
    responses: dict[str, type[BaseModel] | TypeAliasType | None]
    binary_responses: dict[str, Any]
    machine_arguments: type[BaseModel] | None = None
    machine_result: type[BaseModel] | None = None

    def http_fields(self) -> dict[str, Any]:
        result: dict[str, Any] = {"parameters": list(self.parameters)}
        if self.body_model is not None:
            result["requestBody"] = {
                "required": True,
                "content": {
                    "application/json": {
                        "schema": {
                            "$ref": "#/components/schemas/" + self.body_model.__name__
                        }
                    }
                },
            }
        return result


OPERATION_CONTRACTS = (
    OperationContract(
        "getHealthLive",
        "health",
        "live",
        "get",
        "/health/live",
        parameters=(),
        body_model=None,
        responses={"200": LiveResponse},
        binary_responses={},
    ),
    OperationContract(
        "getHealthReady",
        "health",
        "ready",
        "get",
        "/health/ready",
        parameters=(),
        body_model=None,
        responses={"200": ReadyResponse, "503": ReadyResponse},
        binary_responses={},
    ),
    OperationContract(
        "listCreatorActivities",
        "activity",
        "list",
        "get",
        "/v1/activities",
        parameters=(
            {
                "in": "query",
                "name": "limit",
                "required": False,
                "schema": {
                    "anyOf": [{"type": "string"}, {"type": "null"}],
                    "title": "Limit",
                },
            },
            {
                "in": "query",
                "name": "cursor",
                "required": False,
                "schema": {
                    "anyOf": [{"type": "string"}, {"type": "null"}],
                    "title": "Cursor",
                },
            },
        ),
        body_model=None,
        responses={
            "200": CreatorActivityPageResponse,
            "401": RejectedOutcomeResponse,
            "403": RejectedOutcomeResponse,
            "503": UnavailableOutcomeResponse,
        },
        binary_responses={},
    ),
    OperationContract(
        "getCreatorActivityTimeline",
        "activity",
        "timeline",
        "get",
        "/v1/activities/{activity_id}/timeline",
        parameters=(
            {
                "in": "path",
                "name": "activity_id",
                "required": True,
                "schema": {
                    "pattern": "[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}",
                    "title": "Activity Id",
                    "type": "string",
                },
            },
            {
                "in": "query",
                "name": "limit",
                "required": False,
                "schema": {
                    "default": 50,
                    "maximum": 100,
                    "minimum": 1,
                    "title": "Limit",
                    "type": "integer",
                },
            },
            {
                "in": "query",
                "name": "cursor",
                "required": False,
                "schema": {
                    "anyOf": [
                        {
                            "maxLength": 2048,
                            "pattern": "v1\\.[A-Za-z0-9_-]+\\.[A-Za-z0-9_-]+",
                            "type": "string",
                        },
                        {"type": "null"},
                    ],
                    "title": "Cursor",
                },
            },
        ),
        body_model=None,
        responses={
            "200": CreatorActivityTimelineResponse,
            "400": RejectedOutcomeResponse,
            "401": RejectedOutcomeResponse,
            "403": RejectedOutcomeResponse,
            "404": RejectedOutcomeResponse,
            "503": UnavailableOutcomeResponse,
        },
        binary_responses={},
    ),
    OperationContract(
        "listCapabilityRequests",
        "capability",
        "list",
        "get",
        "/v1/capability-requests",
        parameters=(
            {
                "in": "query",
                "name": "limit",
                "required": False,
                "schema": {
                    "default": 50,
                    "maximum": 100,
                    "minimum": 1,
                    "title": "Limit",
                    "type": "integer",
                },
            },
            {
                "in": "query",
                "name": "cursor",
                "required": False,
                "schema": {
                    "anyOf": [
                        {
                            "maxLength": 2048,
                            "pattern": "v1\\.[A-Za-z0-9_-]+\\.[A-Za-z0-9_-]+",
                            "type": "string",
                        },
                        {"type": "null"},
                    ],
                    "title": "Cursor",
                },
            },
        ),
        body_model=None,
        responses={
            "200": CapabilityRequestPageResponse,
            "400": RejectedOutcomeResponse,
            "401": RejectedOutcomeResponse,
            "403": RejectedOutcomeResponse,
            "409": RejectedOutcomeResponse,
            "503": UnavailableOutcomeResponse,
        },
        binary_responses={},
    ),
    OperationContract(
        "decideCapabilityRequest",
        "capability",
        "decide",
        "post",
        "/v1/capability-requests/{capability_request_id}/decision",
        parameters=(
            {
                "in": "path",
                "name": "capability_request_id",
                "required": True,
                "schema": {
                    "pattern": "[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}",
                    "title": "Capability Request Id",
                    "type": "string",
                },
            },
        ),
        body_model=CapabilityRequestDecisionRequest,
        responses={
            "200": AppliedOutcomeResponse,
            "400": RejectedOutcomeResponse,
            "401": RejectedOutcomeResponse,
            "403": RejectedOutcomeResponse,
            "404": RejectedOutcomeResponse,
            "409": RejectedOutcomeResponse,
            "413": RejectedOutcomeResponse,
            "503": UnavailableOutcomeResponse,
        },
        binary_responses={},
    ),
    OperationContract(
        "startQQChannel",
        "channel",
        "start",
        "post",
        "/v1/channels/qq/start",
        parameters=(),
        body_model=None,
        responses={"200": QQChannelHealthResponse},
        binary_responses={},
    ),
    OperationContract(
        "getQQChannelHealth",
        "channel",
        "status",
        "get",
        "/v1/channels/qq/status",
        parameters=(),
        body_model=None,
        responses={
            "200": QQChannelHealthResponse,
            "401": RejectedOutcomeResponse,
            "403": RejectedOutcomeResponse,
            "503": UnavailableOutcomeResponse,
        },
        binary_responses={},
    ),
    OperationContract(
        "stopQQChannel",
        "channel",
        "stop",
        "post",
        "/v1/channels/qq/stop",
        parameters=(),
        body_model=None,
        responses={"200": QQChannelHealthResponse},
        binary_responses={},
    ),
    OperationContract(
        "listDataRightsOrders",
        "data-rights",
        "list",
        "get",
        "/v1/data-rights/orders",
        parameters=(),
        body_model=None,
        responses={
            "200": DataRightsOrderCollectionResponse,
            "401": RejectedOutcomeResponse,
            "403": RejectedOutcomeResponse,
            "503": UnavailableOutcomeResponse,
        },
        binary_responses={},
    ),
    OperationContract(
        "createDataRightsOrder",
        "data-rights",
        "request",
        "post",
        "/v1/data-rights/orders",
        parameters=(
            {
                "in": "header",
                "name": "Idempotency-Key",
                "required": True,
                "schema": {"title": "Idempotency-Key", "type": "string"},
            },
        ),
        body_model=DataRightsOrderRequest,
        responses={
            "200": DataRightsOrderResponse,
            "201": DataRightsOrderResponse,
            "400": RejectedOutcomeResponse,
            "401": RejectedOutcomeResponse,
            "403": RejectedOutcomeResponse,
            "409": RejectedOutcomeResponse,
            "413": RejectedOutcomeResponse,
            "503": UnavailableOutcomeResponse,
        },
        binary_responses={},
    ),
    OperationContract(
        "getDataRightsOrder",
        "data-rights",
        "get",
        "get",
        "/v1/data-rights/orders/{order_id}",
        parameters=(
            {
                "in": "path",
                "name": "order_id",
                "required": True,
                "schema": {"title": "Order Id", "type": "string"},
            },
        ),
        body_model=None,
        responses={
            "200": DataRightsOrderDetailResponse,
            "400": RejectedOutcomeResponse,
            "401": RejectedOutcomeResponse,
            "403": RejectedOutcomeResponse,
            "404": RejectedOutcomeResponse,
            "503": UnavailableOutcomeResponse,
        },
        binary_responses={},
    ),
    OperationContract(
        "retryDataRightsOrder",
        "data-rights",
        "retry",
        "post",
        "/v1/data-rights/orders/{order_id}/retry",
        parameters=(
            {
                "in": "path",
                "name": "order_id",
                "required": True,
                "schema": {
                    "pattern": "[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}",
                    "title": "Order Id",
                    "type": "string",
                },
            },
            {
                "in": "header",
                "name": "Idempotency-Key",
                "required": True,
                "schema": {"title": "Idempotency-Key", "type": "string"},
            },
        ),
        body_model=None,
        responses={"200": DataRightsOrderResponse},
        binary_responses={},
    ),
    OperationContract(
        "getEffect",
        "effect",
        "get",
        "get",
        "/v1/effects/{effect_id}",
        parameters=(
            {
                "in": "path",
                "name": "effect_id",
                "required": True,
                "schema": {
                    "pattern": "[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}",
                    "title": "Effect Id",
                    "type": "string",
                },
            },
        ),
        body_model=None,
        responses={
            "200": EffectResponse,
            "400": RejectedOutcomeResponse,
            "401": RejectedOutcomeResponse,
            "403": RejectedOutcomeResponse,
            "404": RejectedOutcomeResponse,
            "503": UnavailableOutcomeResponse,
        },
        binary_responses={},
    ),
    OperationContract(
        "getEffectArtifact",
        "artifact",
        "read",
        "get",
        "/v1/effects/{effect_id}/artifacts/{artifact_kind}",
        machine_arguments=ArtifactReadWindow,
        machine_result=ArtifactChunk,
        parameters=(
            {
                "in": "path",
                "name": "effect_id",
                "required": True,
                "schema": {
                    "pattern": "[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}",
                    "title": "Effect Id",
                    "type": "string",
                },
            },
            {
                "in": "path",
                "name": "artifact_kind",
                "required": True,
                "schema": {
                    "enum": ["patch", "final_result", "validation_report"],
                    "title": "Artifact Kind",
                    "type": "string",
                },
            },
        ),
        body_model=None,
        responses={
            "200": None,
            "400": RejectedOutcomeResponse,
            "401": RejectedOutcomeResponse,
            "403": RejectedOutcomeResponse,
            "404": RejectedOutcomeResponse,
            "503": UnavailableOutcomeResponse,
        },
        binary_responses={
            "200": {
                "application/json": {"schema": {"type": "string"}},
                "text/plain": {"schema": {"type": "string"}},
            }
        },
    ),
    OperationContract(
        "createCreatorExport",
        "export",
        "create",
        "post",
        "/v1/exports",
        parameters=(
            {
                "in": "header",
                "name": "Idempotency-Key",
                "required": True,
                "schema": {"title": "Idempotency-Key", "type": "string"},
            },
        ),
        body_model=CreatorExportRequest,
        responses={
            "200": CreatorExportResponse,
            "201": CreatorExportResponse,
            "400": RejectedOutcomeResponse,
            "401": RejectedOutcomeResponse,
            "403": RejectedOutcomeResponse,
            "409": RejectedOutcomeResponse,
            "413": RejectedOutcomeResponse,
            "503": UnavailableOutcomeResponse,
        },
        binary_responses={},
    ),
    OperationContract(
        "getCreatorExport",
        "export",
        "get",
        "get",
        "/v1/exports/{export_id}",
        parameters=(
            {
                "in": "path",
                "name": "export_id",
                "required": True,
                "schema": {"title": "Export Id", "type": "string"},
            },
        ),
        body_model=None,
        responses={
            "200": CreatorExportResponse,
            "400": RejectedOutcomeResponse,
            "401": RejectedOutcomeResponse,
            "403": RejectedOutcomeResponse,
            "404": RejectedOutcomeResponse,
            "503": UnavailableOutcomeResponse,
        },
        binary_responses={},
    ),
    OperationContract(
        "queryCreatorLifeRecords",
        "life-record",
        "query",
        "get",
        "/v1/life-records",
        parameters=(
            {
                "in": "query",
                "name": "kind",
                "required": False,
                "schema": {
                    "anyOf": [
                        {"$ref": "#/components/schemas/LifeRecordKindValue"},
                        {"type": "null"},
                    ],
                    "title": "Kind",
                },
            },
            {
                "in": "query",
                "name": "q",
                "required": False,
                "schema": {
                    "anyOf": [
                        {"maxLength": 1024, "minLength": 1, "type": "string"},
                        {"type": "null"},
                    ],
                    "title": "Q",
                },
            },
            {
                "in": "query",
                "name": "limit",
                "required": False,
                "schema": {
                    "default": 50,
                    "maximum": 100,
                    "minimum": 1,
                    "title": "Limit",
                    "type": "integer",
                },
            },
            {
                "in": "query",
                "name": "cursor",
                "required": False,
                "schema": {
                    "anyOf": [
                        {
                            "maxLength": 2048,
                            "pattern": "v1\\.[A-Za-z0-9_-]+\\.[A-Za-z0-9_-]+",
                            "type": "string",
                        },
                        {"type": "null"},
                    ],
                    "title": "Cursor",
                },
            },
        ),
        body_model=None,
        responses={
            "200": LifeRecordPageResponse,
            "400": RejectedOutcomeResponse,
            "401": RejectedOutcomeResponse,
            "403": RejectedOutcomeResponse,
            "409": RejectedOutcomeResponse,
            "503": UnavailableOutcomeResponse,
        },
        binary_responses={},
    ),
    OperationContract(
        "getCreatorMaintenanceStatus",
        "maintenance",
        "status",
        "get",
        "/v1/maintenance/status",
        parameters=(),
        body_model=None,
        responses={
            "200": CreatorMaintenanceStatusResponse,
            "401": RejectedOutcomeResponse,
            "403": RejectedOutcomeResponse,
            "503": UnavailableOutcomeResponse,
        },
        binary_responses={},
    ),
    OperationContract(
        "getCreatorMaintenanceTimeline",
        "maintenance",
        "timeline",
        "get",
        "/v1/maintenance/{maintenance_session_id}/timeline",
        parameters=(
            {
                "in": "path",
                "name": "maintenance_session_id",
                "required": True,
                "schema": {
                    "pattern": "[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}",
                    "title": "Maintenance Session Id",
                    "type": "string",
                },
            },
            {
                "in": "query",
                "name": "limit",
                "required": False,
                "schema": {
                    "default": 50,
                    "maximum": 100,
                    "minimum": 1,
                    "title": "Limit",
                    "type": "integer",
                },
            },
            {
                "in": "query",
                "name": "cursor",
                "required": False,
                "schema": {
                    "anyOf": [
                        {
                            "maxLength": 2048,
                            "pattern": "v1\\.[A-Za-z0-9_-]+\\.[A-Za-z0-9_-]+",
                            "type": "string",
                        },
                        {"type": "null"},
                    ],
                    "title": "Cursor",
                },
            },
        ),
        body_model=None,
        responses={
            "200": CreatorMaintenanceTimelineResponse,
            "400": RejectedOutcomeResponse,
            "401": RejectedOutcomeResponse,
            "403": RejectedOutcomeResponse,
            "404": RejectedOutcomeResponse,
            "503": UnavailableOutcomeResponse,
        },
        binary_responses={},
    ),
    OperationContract(
        "requestCreatorEmergencyWake",
        "maintenance",
        "wake",
        "post",
        "/v1/maintenance/{maintenance_session_id}/wake",
        parameters=(
            {
                "in": "path",
                "name": "maintenance_session_id",
                "required": True,
                "schema": {
                    "pattern": "[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}",
                    "title": "Maintenance Session Id",
                    "type": "string",
                },
            },
        ),
        body_model=None,
        responses={
            "204": None,
            "401": RejectedOutcomeResponse,
            "403": RejectedOutcomeResponse,
            "404": RejectedOutcomeResponse,
            "409": RejectedOutcomeResponse,
            "503": UnavailableOutcomeResponse,
        },
        binary_responses={},
    ),
    OperationContract(
        "getCreatorLifeMaterial",
        "material",
        "get",
        "get",
        "/v1/materials/{material_id}",
        parameters=(
            {
                "in": "path",
                "name": "material_id",
                "required": True,
                "schema": {
                    "pattern": "[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}",
                    "title": "Material Id",
                    "type": "string",
                },
            },
        ),
        body_model=None,
        responses={
            "200": CreatorLifeMaterialResponse,
            "400": RejectedOutcomeResponse,
            "401": RejectedOutcomeResponse,
            "403": RejectedOutcomeResponse,
            "404": RejectedOutcomeResponse,
            "503": UnavailableOutcomeResponse,
        },
        binary_responses={},
    ),
    OperationContract(
        "listCreatorMemories",
        "memory",
        "list",
        "get",
        "/v1/memories",
        parameters=(
            {
                "in": "query",
                "name": "q",
                "required": False,
                "schema": {
                    "anyOf": [
                        {"maxLength": 1024, "minLength": 1, "type": "string"},
                        {"type": "null"},
                    ],
                    "title": "Q",
                },
            },
            {
                "in": "query",
                "name": "limit",
                "required": False,
                "schema": {
                    "default": 50,
                    "maximum": 100,
                    "minimum": 1,
                    "title": "Limit",
                    "type": "integer",
                },
            },
            {
                "in": "query",
                "name": "cursor",
                "required": False,
                "schema": {
                    "anyOf": [
                        {
                            "maxLength": 2048,
                            "pattern": "v1\\.[A-Za-z0-9_-]+\\.[A-Za-z0-9_-]+",
                            "type": "string",
                        },
                        {"type": "null"},
                    ],
                    "title": "Cursor",
                },
            },
        ),
        body_model=None,
        responses={
            "200": CreatorMemoryPageResponse,
            "400": RejectedOutcomeResponse,
            "401": RejectedOutcomeResponse,
            "403": RejectedOutcomeResponse,
            "409": RejectedOutcomeResponse,
            "503": UnavailableOutcomeResponse,
        },
        binary_responses={},
    ),
    OperationContract(
        "getCreatorMemoryTimeline",
        "memory",
        "timeline",
        "get",
        "/v1/memories/{memory_id}/timeline",
        parameters=(
            {
                "in": "path",
                "name": "memory_id",
                "required": True,
                "schema": {
                    "pattern": "[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}",
                    "title": "Memory Id",
                    "type": "string",
                },
            },
            {
                "in": "query",
                "name": "limit",
                "required": False,
                "schema": {
                    "default": 50,
                    "maximum": 100,
                    "minimum": 1,
                    "title": "Limit",
                    "type": "integer",
                },
            },
            {
                "in": "query",
                "name": "cursor",
                "required": False,
                "schema": {
                    "anyOf": [
                        {
                            "maxLength": 2048,
                            "pattern": "v1\\.[A-Za-z0-9_-]+\\.[A-Za-z0-9_-]+",
                            "type": "string",
                        },
                        {"type": "null"},
                    ],
                    "title": "Cursor",
                },
            },
        ),
        body_model=None,
        responses={
            "200": CreatorMemoryTimelineResponse,
            "400": RejectedOutcomeResponse,
            "401": RejectedOutcomeResponse,
            "403": RejectedOutcomeResponse,
            "404": RejectedOutcomeResponse,
            "409": RejectedOutcomeResponse,
            "503": UnavailableOutcomeResponse,
        },
        binary_responses={},
    ),
    OperationContract(
        "getCreatorOperation",
        "operation",
        "get",
        "get",
        "/v1/operations/{result_ref}",
        parameters=(
            {
                "in": "path",
                "name": "result_ref",
                "required": True,
                "schema": {
                    "pattern": "[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}",
                    "title": "Result Ref",
                    "type": "string",
                },
            },
        ),
        body_model=None,
        responses={
            "200": OperationOutcomeResponse,
            "400": RejectedOutcomeResponse,
            "401": RejectedOutcomeResponse,
            "403": RejectedOutcomeResponse,
            "404": RejectedOutcomeResponse,
            "503": UnavailableOutcomeResponse,
        },
        binary_responses={},
        machine_result=MediaOrOperationResult,
    ),
    OperationContract(
        "listOtherHumanRecordParties",
        "other-human",
        "list",
        "get",
        "/v1/other-human-records",
        parameters=(
            {
                "in": "query",
                "name": "limit",
                "required": False,
                "schema": {
                    "default": 25,
                    "maximum": 100,
                    "minimum": 1,
                    "title": "Limit",
                    "type": "integer",
                },
            },
            {
                "in": "query",
                "name": "cursor",
                "required": False,
                "schema": {
                    "anyOf": [
                        {
                            "maxLength": 2048,
                            "pattern": "v1\\.[A-Za-z0-9_-]+\\.[A-Za-z0-9_-]+",
                            "type": "string",
                        },
                        {"type": "null"},
                    ],
                    "title": "Cursor",
                },
            },
        ),
        body_model=None,
        responses={
            "200": OtherHumanPartyRecordPageResponse,
            "400": RejectedOutcomeResponse,
            "401": RejectedOutcomeResponse,
            "403": RejectedOutcomeResponse,
            "503": UnavailableOutcomeResponse,
        },
        binary_responses={},
    ),
    OperationContract(
        "listOtherHumanRecordScenes",
        "other-human",
        "scenes",
        "get",
        "/v1/other-human-records/{party_id}/scenes",
        parameters=(
            {
                "in": "path",
                "name": "party_id",
                "required": True,
                "schema": {
                    "pattern": "[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}",
                    "title": "Party Id",
                    "type": "string",
                },
            },
            {
                "in": "query",
                "name": "limit",
                "required": False,
                "schema": {
                    "default": 25,
                    "maximum": 100,
                    "minimum": 1,
                    "title": "Limit",
                    "type": "integer",
                },
            },
            {
                "in": "query",
                "name": "cursor",
                "required": False,
                "schema": {
                    "anyOf": [
                        {
                            "maxLength": 2048,
                            "pattern": "v1\\.[A-Za-z0-9_-]+\\.[A-Za-z0-9_-]+",
                            "type": "string",
                        },
                        {"type": "null"},
                    ],
                    "title": "Cursor",
                },
            },
        ),
        body_model=None,
        responses={
            "200": OtherHumanSceneRecordPageResponse,
            "400": RejectedOutcomeResponse,
            "401": RejectedOutcomeResponse,
            "403": RejectedOutcomeResponse,
            "404": RejectedOutcomeResponse,
            "503": UnavailableOutcomeResponse,
        },
        binary_responses={},
    ),
    OperationContract(
        "getOtherHumanRecordTimeline",
        "other-human",
        "timeline",
        "get",
        "/v1/other-human-records/{party_id}/scenes/{scene_id}/timeline",
        parameters=(
            {
                "in": "path",
                "name": "party_id",
                "required": True,
                "schema": {
                    "pattern": "[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}",
                    "title": "Party Id",
                    "type": "string",
                },
            },
            {
                "in": "path",
                "name": "scene_id",
                "required": True,
                "schema": {
                    "pattern": "[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}",
                    "title": "Scene Id",
                    "type": "string",
                },
            },
            {
                "in": "query",
                "name": "limit",
                "required": False,
                "schema": {
                    "default": 50,
                    "maximum": 100,
                    "minimum": 1,
                    "title": "Limit",
                    "type": "integer",
                },
            },
            {
                "in": "query",
                "name": "cursor",
                "required": False,
                "schema": {
                    "anyOf": [
                        {
                            "maxLength": 2048,
                            "pattern": "v1\\.[A-Za-z0-9_-]+\\.[A-Za-z0-9_-]+",
                            "type": "string",
                        },
                        {"type": "null"},
                    ],
                    "title": "Cursor",
                },
            },
        ),
        body_model=None,
        responses={
            "200": OtherHumanTimelineRecordPageResponse,
            "400": RejectedOutcomeResponse,
            "401": RejectedOutcomeResponse,
            "403": RejectedOutcomeResponse,
            "404": RejectedOutcomeResponse,
            "503": UnavailableOutcomeResponse,
        },
        binary_responses={},
    ),
    OperationContract(
        "getCreatorPrompt",
        "prompt",
        "get",
        "get",
        "/v1/prompts/creator-guidance",
        parameters=(),
        body_model=None,
        responses={
            "200": CreatorPromptResponse,
            "401": RejectedOutcomeResponse,
            "403": RejectedOutcomeResponse,
            "503": UnavailableOutcomeResponse,
        },
        binary_responses={},
    ),
    OperationContract(
        "reviseCreatorPrompt",
        "prompt",
        "revise",
        "put",
        "/v1/prompts/creator-guidance",
        parameters=(),
        body_model=CreatorPromptRevisionRequest,
        responses={
            "200": CreatorPromptResponse,
            "400": RejectedOutcomeResponse,
            "401": RejectedOutcomeResponse,
            "403": RejectedOutcomeResponse,
            "409": RejectedOutcomeResponse,
            "413": RejectedOutcomeResponse,
            "503": UnavailableOutcomeResponse,
        },
        binary_responses={},
    ),
    OperationContract(
        "deactivateCreatorPrompt",
        "prompt",
        "deactivate",
        "post",
        "/v1/prompts/creator-guidance/deactivation",
        parameters=(),
        body_model=CreatorPromptDeactivateRequest,
        responses={
            "200": CreatorPromptResponse,
            "400": RejectedOutcomeResponse,
            "401": RejectedOutcomeResponse,
            "403": RejectedOutcomeResponse,
            "409": RejectedOutcomeResponse,
            "413": RejectedOutcomeResponse,
            "503": UnavailableOutcomeResponse,
        },
        binary_responses={},
    ),
    OperationContract(
        "getCreatorRelationshipCurrent",
        "relationship",
        "get",
        "get",
        "/v1/relationships/current",
        parameters=(),
        body_model=None,
        responses={
            "200": CreatorRelationshipCurrentResponse,
            "401": RejectedOutcomeResponse,
            "403": RejectedOutcomeResponse,
            "503": UnavailableOutcomeResponse,
        },
        binary_responses={},
    ),
    OperationContract(
        "expressCreatorRelationshipBoundary",
        "relationship",
        "boundary",
        "post",
        "/v1/relationships/current/boundaries",
        parameters=(
            {
                "in": "header",
                "name": "Idempotency-Key",
                "required": True,
                "schema": {
                    "maxLength": 128,
                    "pattern": "[A-Za-z0-9][A-Za-z0-9._:-]{0,127}",
                    "title": "Idempotency-Key",
                    "type": "string",
                },
            },
        ),
        body_model=CreatorRelationshipBoundaryRequest,
        responses={
            "202": AcceptedOutcomeResponse,
            "400": RejectedOutcomeResponse,
            "401": RejectedOutcomeResponse,
            "403": RejectedOutcomeResponse,
            "409": RejectedOutcomeResponse,
            "413": RejectedOutcomeResponse,
            "503": UnavailableOutcomeResponse,
        },
        binary_responses={},
    ),
    OperationContract(
        "getCreatorRelationshipTimeline",
        "relationship",
        "timeline",
        "get",
        "/v1/relationships/{relationship_id}/timeline",
        parameters=(
            {
                "in": "path",
                "name": "relationship_id",
                "required": True,
                "schema": {
                    "pattern": "[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}",
                    "title": "Relationship Id",
                    "type": "string",
                },
            },
            {
                "in": "query",
                "name": "limit",
                "required": False,
                "schema": {
                    "default": 50,
                    "maximum": 100,
                    "minimum": 1,
                    "title": "Limit",
                    "type": "integer",
                },
            },
            {
                "in": "query",
                "name": "cursor",
                "required": False,
                "schema": {
                    "anyOf": [
                        {
                            "maxLength": 2048,
                            "pattern": "v1\\.[A-Za-z0-9_-]+\\.[A-Za-z0-9_-]+",
                            "type": "string",
                        },
                        {"type": "null"},
                    ],
                    "title": "Cursor",
                },
            },
        ),
        body_model=None,
        responses={
            "200": CreatorRelationshipTimelineResponse,
            "400": RejectedOutcomeResponse,
            "401": RejectedOutcomeResponse,
            "403": RejectedOutcomeResponse,
            "404": RejectedOutcomeResponse,
            "503": UnavailableOutcomeResponse,
        },
        binary_responses={},
    ),
    OperationContract(
        "getRuntimeStatus",
        "runtime",
        "status",
        "get",
        "/v1/runtime/status",
        parameters=(),
        body_model=None,
        responses={
            "200": RuntimeStatusResponse,
            "401": RejectedOutcomeResponse,
            "403": RejectedOutcomeResponse,
            "503": UnavailableOutcomeResponse,
        },
        binary_responses={},
    ),
    OperationContract(
        "listCreatorScenes",
        "scene",
        "list",
        "get",
        "/v1/scenes",
        parameters=(),
        body_model=None,
        responses={
            "200": CreatorSceneCollectionResponse,
            "401": RejectedOutcomeResponse,
            "403": RejectedOutcomeResponse,
            "503": UnavailableOutcomeResponse,
        },
        binary_responses={},
    ),
    OperationContract(
        "createCreatorScene",
        "scene",
        "create",
        "post",
        "/v1/scenes",
        parameters=(),
        body_model=CreatorSceneCreateRequest,
        responses={
            "201": CreatorSceneResponse,
            "400": RejectedOutcomeResponse,
            "401": RejectedOutcomeResponse,
            "403": RejectedOutcomeResponse,
            "409": RejectedOutcomeResponse,
            "503": UnavailableOutcomeResponse,
        },
        binary_responses={},
    ),
    OperationContract(
        "closeCreatorScene",
        "scene",
        "close",
        "post",
        "/v1/scenes/{scene_key}/close",
        parameters=(
            {
                "in": "path",
                "name": "scene_key",
                "required": True,
                "schema": {
                    "pattern": "[a-z0-9][a-z0-9._-]{0,63}",
                    "title": "Scene Key",
                    "type": "string",
                },
            },
        ),
        body_model=None,
        responses={
            "200": CreatorSceneResponse,
            "400": RejectedOutcomeResponse,
            "401": RejectedOutcomeResponse,
            "403": RejectedOutcomeResponse,
            "404": RejectedOutcomeResponse,
            "503": UnavailableOutcomeResponse,
        },
        binary_responses={},
    ),
    OperationContract(
        "acceptCreatorCodexTask",
        "codex",
        "submit",
        "post",
        "/v1/scenes/{scene_key}/codex-tasks",
        parameters=(
            {
                "in": "path",
                "name": "scene_key",
                "required": True,
                "schema": {
                    "pattern": "[a-z0-9][a-z0-9._-]{0,63}",
                    "title": "Scene Key",
                    "type": "string",
                },
            },
            {
                "in": "header",
                "name": "Idempotency-Key",
                "required": True,
                "schema": {
                    "maxLength": 128,
                    "pattern": "[A-Za-z0-9][A-Za-z0-9._:-]{0,127}",
                    "title": "Idempotency-Key",
                    "type": "string",
                },
            },
        ),
        body_model=CreatorCodexTaskRequest,
        responses={
            "202": AcceptedOutcomeResponse,
            "400": RejectedOutcomeResponse,
            "401": RejectedOutcomeResponse,
            "403": RejectedOutcomeResponse,
            "404": RejectedOutcomeResponse,
            "409": RejectedOutcomeResponse,
            "413": RejectedOutcomeResponse,
            "503": UnavailableOutcomeResponse,
        },
        binary_responses={},
    ),
    OperationContract(
        "acceptCreatorMessage",
        "message",
        "send",
        "post",
        "/v1/scenes/{scene_key}/messages",
        parameters=(
            {
                "in": "path",
                "name": "scene_key",
                "required": True,
                "schema": {
                    "pattern": "[a-z0-9][a-z0-9._-]{0,63}",
                    "title": "Scene Key",
                    "type": "string",
                },
            },
            {
                "in": "header",
                "name": "Idempotency-Key",
                "required": True,
                "schema": {
                    "maxLength": 128,
                    "pattern": "[A-Za-z0-9][A-Za-z0-9._:-]{0,127}",
                    "title": "Idempotency-Key",
                    "type": "string",
                },
            },
        ),
        body_model=CreatorInputRequest,
        responses={
            "202": AcceptedOutcomeResponse,
            "400": RejectedOutcomeResponse,
            "401": RejectedOutcomeResponse,
            "403": RejectedOutcomeResponse,
            "404": RejectedOutcomeResponse,
            "409": RejectedOutcomeResponse,
            "413": RejectedOutcomeResponse,
            "503": UnavailableOutcomeResponse,
        },
        binary_responses={},
        machine_arguments=MediaMessageRequest,
        machine_result=MediaMessageResult,
    ),
    OperationContract(
        "reopenCreatorScene",
        "scene",
        "reopen",
        "post",
        "/v1/scenes/{scene_key}/reopen",
        parameters=(
            {
                "in": "path",
                "name": "scene_key",
                "required": True,
                "schema": {
                    "pattern": "[a-z0-9][a-z0-9._-]{0,63}",
                    "title": "Scene Key",
                    "type": "string",
                },
            },
        ),
        body_model=None,
        responses={
            "200": CreatorSceneResponse,
            "400": RejectedOutcomeResponse,
            "401": RejectedOutcomeResponse,
            "403": RejectedOutcomeResponse,
            "404": RejectedOutcomeResponse,
            "503": UnavailableOutcomeResponse,
        },
        binary_responses={},
    ),
    OperationContract(
        "getSceneTimeline",
        "scene",
        "timeline",
        "get",
        "/v1/scenes/{scene_key}/timeline",
        parameters=(
            {
                "in": "path",
                "name": "scene_key",
                "required": True,
                "schema": {
                    "pattern": "[a-z0-9][a-z0-9._-]{0,63}",
                    "title": "Scene Key",
                    "type": "string",
                },
            },
            {
                "in": "query",
                "name": "limit",
                "required": True,
                "schema": {
                    "maximum": 100,
                    "minimum": 1,
                    "title": "Limit",
                    "type": "integer",
                },
            },
            {
                "in": "query",
                "name": "cursor",
                "required": False,
                "schema": {
                    "anyOf": [
                        {
                            "maxLength": 2048,
                            "pattern": "v1\\.[A-Za-z0-9_-]+\\.[A-Za-z0-9_-]+",
                            "type": "string",
                        },
                        {"type": "null"},
                    ],
                    "title": "Cursor",
                },
            },
        ),
        body_model=None,
        responses={
            "200": SceneTimelinePageResponse,
            "400": RejectedOutcomeResponse,
            "401": RejectedOutcomeResponse,
            "403": RejectedOutcomeResponse,
            "404": RejectedOutcomeResponse,
            "409": RejectedOutcomeResponse,
            "503": UnavailableOutcomeResponse,
        },
        binary_responses={},
    ),
    OperationContract(
        "getSubjectSummary",
        "subject",
        "summary",
        "get",
        "/v1/subject/summary",
        parameters=(),
        body_model=None,
        responses={
            "200": SubjectSummaryResponse,
            "401": RejectedOutcomeResponse,
            "403": RejectedOutcomeResponse,
            "503": UnavailableOutcomeResponse,
        },
        binary_responses={},
    ),
    OperationContract(
        "getLiveVisionObservation",
        "vision",
        "observation",
        "get",
        "/v1/vision/observations/{observation_id}",
        parameters=(
            {
                "in": "path",
                "name": "observation_id",
                "required": True,
                "schema": {"title": "Observation Id", "type": "string"},
            },
        ),
        body_model=None,
        responses={"200": LiveVisionObservationResponse, "404": None},
        binary_responses={},
    ),
    OperationContract(
        "observeLiveVision",
        "vision",
        "observe",
        "post",
        "/v1/vision/observe",
        parameters=(),
        body_model=None,
        responses={
            "200": LiveVisionObservationResponse,
            "202": LiveVisionObservationResponse,
            "409": None,
        },
        binary_responses={},
    ),
    OperationContract(
        "getLiveVisionSourcePreview",
        "vision",
        "preview",
        "get",
        "/v1/vision/sources/{source_kind}/preview",
        parameters=(
            {
                "in": "path",
                "name": "source_kind",
                "required": True,
                "schema": {"title": "Source Kind", "type": "string"},
            },
        ),
        body_model=None,
        responses={"200": None, "404": None},
        binary_responses={"200": {"image/jpeg": {}}},
    ),
    OperationContract(
        "startLiveVisionSource",
        "vision",
        "start",
        "post",
        "/v1/vision/sources/{source_kind}/start",
        parameters=(
            {
                "in": "path",
                "name": "source_kind",
                "required": True,
                "schema": {"title": "Source Kind", "type": "string"},
            },
        ),
        body_model=None,
        responses={"200": LiveVisionStatusResponse},
        binary_responses={},
    ),
    OperationContract(
        "stopLiveVisionSource",
        "vision",
        "stop",
        "post",
        "/v1/vision/sources/{source_kind}/stop",
        parameters=(
            {
                "in": "path",
                "name": "source_kind",
                "required": True,
                "schema": {"title": "Source Kind", "type": "string"},
            },
        ),
        body_model=None,
        responses={"200": LiveVisionStatusResponse},
        binary_responses={},
    ),
    OperationContract(
        "getLiveVisionStatus",
        "vision",
        "status",
        "get",
        "/v1/vision/status",
        parameters=(),
        body_model=None,
        responses={"200": LiveVisionStatusResponse},
        binary_responses={},
    ),
    OperationContract(
        "startLiveVoice",
        "voice",
        "start",
        "post",
        "/v1/voice/start",
        parameters=(),
        body_model=None,
        responses={"200": LiveVoiceStatusResponse},
        binary_responses={},
    ),
    OperationContract(
        "getLiveVoiceStatus",
        "voice",
        "status",
        "get",
        "/v1/voice/status",
        parameters=(),
        body_model=None,
        responses={"200": LiveVoiceStatusResponse},
        binary_responses={},
    ),
    OperationContract(
        "stopLiveVoice",
        "voice",
        "stop",
        "post",
        "/v1/voice/stop",
        parameters=(),
        body_model=None,
        responses={"200": LiveVoiceStatusResponse},
        binary_responses={},
    ),
)

OPERATION_NAMES = {
    item.operation_id: (item.group, item.action) for item in OPERATION_CONTRACTS
}


def interaction_contract_document() -> dict[str, Any]:
    """Project current models and operation metadata; no generated file is read."""
    definitions: dict[str, Any] = {}
    paths: dict[str, Any] = {}

    def reference(model: type[BaseModel] | TypeAliasType) -> dict[str, str]:
        schema = TypeAdapter[Any](model).json_schema(
            ref_template="#/components/schemas/{model}"
        )
        definitions.update(schema.pop("$defs", {}))
        if schema.get("$ref") != "#/components/schemas/" + model.__name__:
            definitions[model.__name__] = schema
        return {"$ref": "#/components/schemas/" + model.__name__}

    for contract in OPERATION_CONTRACTS:
        if contract.body_model is not None:
            reference(contract.body_model)
        responses: dict[str, Any] = {}
        for status, model in contract.responses.items():
            responses[status] = (
                {}
                if model is None
                else {"content": {"application/json": {"schema": reference(model)}}}
            )
        for status, content in contract.binary_responses.items():
            responses[status] = {"content": content}
        paths.setdefault(contract.path, {})[contract.method] = {
            "operationId": contract.operation_id,
            **contract.http_fields(),
            "responses": responses,
            "machineArguments": None
            if contract.machine_arguments is None
            else contract.machine_arguments.model_json_schema(),
            "machineResult": None
            if contract.machine_result is None
            else reference(contract.machine_result),
        }
    return {"paths": paths, "components": {"schemas": definitions}}


__all__ = ("OPERATION_CONTRACTS", "OPERATION_NAMES", "interaction_contract_document")
