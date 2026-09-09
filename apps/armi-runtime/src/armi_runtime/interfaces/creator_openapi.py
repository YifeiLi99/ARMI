"""Deterministic Creator OpenAPI derived from the real Runtime routes."""

from __future__ import annotations

from copy import deepcopy
from typing import Any, cast

from armi_kernel.contracts import CONTRACT_VERSION
from fastapi import FastAPI

from armi_runtime.application.creator_contract import (
    CapabilityRequestDecisionRequest,
    CreatorProjectionEventResponse,
    CreatorRelationshipBoundaryRequest,
    QQChannelHealthResponse,
    Readiness,
)
from armi_runtime.application.interaction_definitions import OPERATION_CONTRACTS

from .creator_app import create_runtime_app
from .static_assets import StaticAssetStore

_OPERATION_OVERRIDES = {
    item.operation_id: item.http_fields() for item in OPERATION_CONTRACTS
}
_OPERATION_OVERRIDES["streamSceneEvents"] = {
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
}
_REQUEST_MODELS = tuple(
    dict.fromkeys(
        item.body_model for item in OPERATION_CONTRACTS if item.body_model is not None
    )
)


async def _unused_async() -> None:
    raise AssertionError("schema construction must not invoke Runtime dependencies")


async def _unused_qq_health() -> QQChannelHealthResponse:
    raise AssertionError("schema construction must not invoke Runtime dependencies")


async def _unused_qq_control(_action: str) -> QQChannelHealthResponse:
    raise AssertionError("schema construction must not invoke Runtime dependencies")


def _unused_sync() -> Any:
    raise AssertionError("schema construction must not invoke Runtime dependencies")


def create_creator_openapi_app() -> FastAPI:
    app = create_runtime_app(
        readiness=lambda: Readiness.NOT_READY,
        runtime_status=_unused_sync,
        qq_channel_health=_unused_qq_health,
        qq_channel_control=_unused_qq_control,
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
