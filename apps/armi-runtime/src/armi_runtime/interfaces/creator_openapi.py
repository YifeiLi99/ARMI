"""Deterministic Creator OpenAPI derived from the real Runtime routes."""

from __future__ import annotations

from copy import deepcopy
from typing import Any, cast

from armi_kernel.contracts import CONTRACT_VERSION
from fastapi import FastAPI

from .creator_app import create_runtime_app
from .creator_contract import (
    CapabilityRequestDecisionRequest,
    CreatorCodexTaskRequest,
    CreatorExportRequest,
    CreatorInputRequest,
    CreatorProjectionEventResponse,
    CreatorPromptDeactivateRequest,
    CreatorPromptRevisionRequest,
    CreatorRelationshipBoundaryRequest,
    CreatorSceneCreateRequest,
    DataRightsOrderRequest,
    QQChannelHealthResponse,
    Readiness,
)
from .static_assets import StaticAssetStore

_OPERATION_OVERRIDES: dict[str, dict[str, object]] = {
    "acceptCreatorCodexTask": {
        "parameters": [
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
        ],
        "requestBody": {
            "content": {
                "application/json": {
                    "schema": {"$ref": "#/components/schemas/CreatorCodexTaskRequest"}
                }
            },
            "required": True,
        },
    },
    "acceptCreatorMessage": {
        "parameters": [
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
        ],
        "requestBody": {
            "content": {
                "application/json": {
                    "schema": {"$ref": "#/components/schemas/CreatorInputRequest"}
                }
            },
            "required": True,
        },
    },
    "closeCreatorScene": {
        "parameters": [
            {
                "in": "path",
                "name": "scene_key",
                "required": True,
                "schema": {
                    "pattern": "[a-z0-9][a-z0-9._-]{0,63}",
                    "title": "Scene Key",
                    "type": "string",
                },
            }
        ]
    },
    "createCreatorExport": {
        "parameters": [
            {
                "in": "header",
                "name": "Idempotency-Key",
                "required": True,
                "schema": {"title": "Idempotency-Key", "type": "string"},
            }
        ],
        "requestBody": {
            "content": {
                "application/json": {
                    "schema": {"$ref": "#/components/schemas/CreatorExportRequest"}
                }
            },
            "required": True,
        },
    },
    "createCreatorScene": {
        "requestBody": {
            "content": {
                "application/json": {
                    "schema": {"$ref": "#/components/schemas/CreatorSceneCreateRequest"}
                }
            },
            "required": True,
        }
    },
    "createDataRightsOrder": {
        "parameters": [
            {
                "in": "header",
                "name": "Idempotency-Key",
                "required": True,
                "schema": {"title": "Idempotency-Key", "type": "string"},
            }
        ],
        "requestBody": {
            "content": {
                "application/json": {
                    "schema": {"$ref": "#/components/schemas/DataRightsOrderRequest"}
                }
            },
            "required": True,
        },
        "summary": "Create Data Rights Order",
    },
    "deactivateCreatorPrompt": {
        "requestBody": {
            "content": {
                "application/json": {
                    "schema": {
                        "$ref": "#/components/schemas/CreatorPromptDeactivateRequest"
                    }
                }
            },
            "required": True,
        }
    },
    "decideCapabilityRequest": {
        "parameters": [
            {
                "in": "path",
                "name": "capability_request_id",
                "required": True,
                "schema": {
                    "pattern": "[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}",
                    "title": "Capability Request Id",
                    "type": "string",
                },
            }
        ],
        "requestBody": {
            "content": {
                "application/json": {
                    "schema": {
                        "$ref": "#/components/schemas/CapabilityRequestDecisionRequest"
                    }
                }
            },
            "required": True,
        },
    },
    "expressCreatorRelationshipBoundary": {
        "parameters": [
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
            }
        ],
        "requestBody": {
            "content": {
                "application/json": {
                    "schema": {
                        "$ref": "#/components/schemas/CreatorRelationshipBoundaryRequest"
                    }
                }
            },
            "required": True,
        },
    },
    "getCreatorActivityTimeline": {
        "parameters": [
            {
                "in": "path",
                "name": "activity_id",
                "required": True,
                "schema": {
                    "pattern": "[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}",
                    "title": "Activity Id",
                    "type": "string",
                },
            }
        ]
    },
    "getCreatorLifeMaterial": {
        "parameters": [
            {
                "in": "path",
                "name": "material_id",
                "required": True,
                "schema": {
                    "pattern": "[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}",
                    "title": "Material Id",
                    "type": "string",
                },
            }
        ]
    },
    "getCreatorMaintenanceTimeline": {
        "parameters": [
            {
                "in": "path",
                "name": "maintenance_session_id",
                "required": True,
                "schema": {
                    "pattern": "[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}",
                    "title": "Maintenance Session Id",
                    "type": "string",
                },
            }
        ]
    },
    "getCreatorMemoryTimeline": {
        "parameters": [
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
        ]
    },
    "getCreatorOperation": {
        "parameters": [
            {
                "in": "path",
                "name": "result_ref",
                "required": True,
                "schema": {
                    "pattern": "[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}",
                    "title": "Result Ref",
                    "type": "string",
                },
            }
        ]
    },
    "getCreatorRelationshipTimeline": {
        "parameters": [
            {
                "in": "path",
                "name": "relationship_id",
                "required": True,
                "schema": {
                    "pattern": "[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}",
                    "title": "Relationship Id",
                    "type": "string",
                },
            }
        ]
    },
    "getDataRightsOrder": {"summary": "Get Data Rights Order"},
    "getEffect": {
        "parameters": [
            {
                "in": "path",
                "name": "effect_id",
                "required": True,
                "schema": {
                    "pattern": "[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}",
                    "title": "Effect Id",
                    "type": "string",
                },
            }
        ]
    },
    "getEffectArtifact": {
        "parameters": [
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
        ]
    },
    "getLiveVisionPreview": {"summary": "Live Vision Preview"},
    "getLiveVisionStatus": {"summary": "Live Vision Status"},
    "getLiveVoiceStatus": {"summary": "Live Voice Status"},
    "getOtherHumanRecordTimeline": {
        "parameters": [
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
        ]
    },
    "getQQChannelHealth": {"summary": "Qq Channel Health"},
    "getRuntimeStatus": {"summary": "Runtime Status"},
    "getSceneTimeline": {
        "parameters": [
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
        ],
        "summary": "Scene Timeline",
    },
    "getSubjectSummary": {"summary": "Subject Summary"},
    "listCapabilityRequests": {
        "parameters": [
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
        ]
    },
    "listCreatorMemories": {
        "parameters": [
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
        ]
    },
    "listDataRightsOrders": {"summary": "List Data Rights Orders"},
    "listOtherHumanRecordParties": {
        "parameters": [
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
        ]
    },
    "listOtherHumanRecordScenes": {
        "parameters": [
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
        ]
    },
    "queryCreatorLifeRecords": {
        "parameters": [
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
        ]
    },
    "reopenCreatorScene": {
        "parameters": [
            {
                "in": "path",
                "name": "scene_key",
                "required": True,
                "schema": {
                    "pattern": "[a-z0-9][a-z0-9._-]{0,63}",
                    "title": "Scene Key",
                    "type": "string",
                },
            }
        ]
    },
    "requestCreatorEmergencyWake": {
        "parameters": [
            {
                "in": "path",
                "name": "maintenance_session_id",
                "required": True,
                "schema": {
                    "pattern": "[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}",
                    "title": "Maintenance Session Id",
                    "type": "string",
                },
            }
        ]
    },
    "reviseCreatorPrompt": {
        "requestBody": {
            "content": {
                "application/json": {
                    "schema": {
                        "$ref": "#/components/schemas/CreatorPromptRevisionRequest"
                    }
                }
            },
            "required": True,
        }
    },
    "streamSceneEvents": {
        "parameters": [
            {
                "in": "path",
                "name": "scene_key",
                "required": True,
                "schema": {
                    "pattern": "[a-z0-9][a-z0-9._-]{0,63}",
                    "title": "Scene Key",
                    "type": "string",
                },
            }
        ],
        "summary": "Scene Events",
    },
}
_REQUEST_MODELS = (
    CapabilityRequestDecisionRequest,
    CreatorCodexTaskRequest,
    CreatorExportRequest,
    CreatorInputRequest,
    CreatorPromptDeactivateRequest,
    CreatorPromptRevisionRequest,
    CreatorRelationshipBoundaryRequest,
    CreatorSceneCreateRequest,
    DataRightsOrderRequest,
)


async def _unused_async() -> None:
    raise AssertionError("schema construction must not invoke Runtime dependencies")


async def _unused_qq_health() -> QQChannelHealthResponse:
    raise AssertionError("schema construction must not invoke Runtime dependencies")


def _unused_sync() -> Any:
    raise AssertionError("schema construction must not invoke Runtime dependencies")


def create_creator_openapi_app() -> FastAPI:
    app = create_runtime_app(
        readiness=lambda: Readiness.NOT_READY,
        runtime_status=_unused_sync,
        qq_channel_health=_unused_qq_health,
        assets=StaticAssetStore({}),
        browser_sessions=None,
        expected_authority="127.0.0.1:6198",
        request_body_max_bytes=1,
        on_started=_unused_async,
        on_stopping=_unused_async,
    )
    app.title = "ARMI Creator Interface"
    app.version = CONTRACT_VERSION
    return app


def build_creator_openapi() -> dict[str, object]:
    """Build the public schema without starting Runtime or external resources."""

    app = create_creator_openapi_app()
    schema: dict[str, Any] = app.openapi()
    schema.pop("servers", None)
    paths = cast(dict[str, object], schema["paths"])
    for raw_path_item in paths.values():
        if not isinstance(raw_path_item, dict):
            continue
        path_item = cast(dict[str, object], raw_path_item)
        for raw_operation in path_item.values():
            if not isinstance(raw_operation, dict):
                continue
            operation = cast(dict[str, object], raw_operation)
            raw_responses = operation.get("responses")
            if isinstance(raw_responses, dict):
                responses = cast(dict[str, object], raw_responses)
                responses.pop("422", None)
            operation_id = operation.get("operationId")
            if isinstance(operation_id, str) and operation_id in _OPERATION_OVERRIDES:
                operation.update(deepcopy(_OPERATION_OVERRIDES[operation_id]))
    schemas = cast(dict[str, object], schema["components"]["schemas"])
    for model in (*_REQUEST_MODELS, CreatorProjectionEventResponse):
        schemas[model.__name__] = model.model_json_schema(
            ref_template="#/components/schemas/{model}"
        )
    relationship_boundary = cast(
        dict[str, object], schemas[CreatorRelationshipBoundaryRequest.__name__]
    )
    relationship_boundary.pop("$defs", None)
    capability_decision = cast(
        dict[str, Any], schemas[CapabilityRequestDecisionRequest.__name__]
    )
    capability_properties = cast(
        dict[str, dict[str, Any]], capability_decision["properties"]
    )
    for name in (
        "valid_for_seconds",
        "max_uses",
        "max_payload_bytes",
        "reason_code",
    ):
        capability_properties[name].pop("default", None)
    for name in ("expected_request_version",):
        capability_properties[name]["minimum"] = float(
            capability_properties[name]["minimum"]
        )
    for name in ("valid_for_seconds", "max_uses", "max_payload_bytes"):
        constrained = capability_properties[name]["anyOf"][0]
        constrained["minimum"] = float(constrained["minimum"])
        constrained["maximum"] = float(constrained["maximum"])
    return cast(dict[str, object], schema)


__all__ = ("build_creator_openapi", "create_creator_openapi_app")
