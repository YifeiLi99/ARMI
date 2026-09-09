"""Named machine operations backed by the current Creator contract."""

from __future__ import annotations

import json
from copy import deepcopy
from dataclasses import dataclass
from importlib.resources import files
from typing import Any, cast

from armi_runtime.application.interaction import InteractionOperation

# The catalog assigns names, not business implementations. Request and result
# schemas remain derived from the same Pydantic/OpenAPI contract as Creator Web.
OPERATION_NAMES = {
    "getHealthLive": ("health", "live"),
    "getHealthReady": ("health", "ready"),
    "listCreatorActivities": ("activity", "list"),
    "getCreatorActivityTimeline": ("activity", "timeline"),
    "listCapabilityRequests": ("capability", "list"),
    "decideCapabilityRequest": ("capability", "decide"),
    "startQQChannel": ("channel", "start"),
    "getQQChannelHealth": ("channel", "status"),
    "stopQQChannel": ("channel", "stop"),
    "listDataRightsOrders": ("data-rights", "list"),
    "createDataRightsOrder": ("data-rights", "request"),
    "getDataRightsOrder": ("data-rights", "get"),
    "retryDataRightsOrder": ("data-rights", "retry"),
    "getEffect": ("effect", "get"),
    "getEffectArtifact": ("artifact", "read"),
    "createCreatorExport": ("export", "create"),
    "getCreatorExport": ("export", "get"),
    "queryCreatorLifeRecords": ("life-record", "query"),
    "getCreatorMaintenanceStatus": ("maintenance", "status"),
    "getCreatorMaintenanceTimeline": ("maintenance", "timeline"),
    "requestCreatorEmergencyWake": ("maintenance", "wake"),
    "getCreatorLifeMaterial": ("material", "get"),
    "listCreatorMemories": ("memory", "list"),
    "getCreatorMemoryTimeline": ("memory", "timeline"),
    "getCreatorOperation": ("operation", "get"),
    "listOtherHumanRecordParties": ("other-human", "list"),
    "listOtherHumanRecordScenes": ("other-human", "scenes"),
    "getOtherHumanRecordTimeline": ("other-human", "timeline"),
    "getCreatorPrompt": ("prompt", "get"),
    "reviseCreatorPrompt": ("prompt", "revise"),
    "deactivateCreatorPrompt": ("prompt", "deactivate"),
    "getCreatorRelationshipCurrent": ("relationship", "get"),
    "expressCreatorRelationshipBoundary": ("relationship", "boundary"),
    "getCreatorRelationshipTimeline": ("relationship", "timeline"),
    "getRuntimeStatus": ("runtime", "status"),
    "listCreatorScenes": ("scene", "list"),
    "createCreatorScene": ("scene", "create"),
    "closeCreatorScene": ("scene", "close"),
    "acceptCreatorCodexTask": ("codex", "submit"),
    "acceptCreatorMessage": ("message", "send"),
    "reopenCreatorScene": ("scene", "reopen"),
    "getSceneTimeline": ("scene", "timeline"),
    "getSubjectSummary": ("subject", "summary"),
    "getLiveVisionObservation": ("vision", "observation"),
    "observeLiveVision": ("vision", "observe"),
    "getLiveVisionSourcePreview": ("vision", "preview"),
    "startLiveVisionSource": ("vision", "start"),
    "stopLiveVisionSource": ("vision", "stop"),
    "getLiveVisionStatus": ("vision", "status"),
    "startLiveVoice": ("voice", "start"),
    "getLiveVoiceStatus": ("voice", "status"),
    "stopLiveVoice": ("voice", "stop"),
}
TRANSPORT_OPERATIONS = frozenset(
    {"createBrowserSession", "getCurrentBrowserSession", "streamSceneEvents"}
)


@dataclass(frozen=True, slots=True)
class InteractionRoute:
    operation: InteractionOperation
    operation_id: str
    method: str
    path: str
    path_names: tuple[str, ...]
    query_names: tuple[str, ...]
    header_names: tuple[tuple[str, str], ...]
    body_names: tuple[str, ...]
    body_version: str | None


def _local_refs(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: _local_refs(item) for key, item in cast(dict[str, Any], value).items()
        }
    if isinstance(value, list):
        return [_local_refs(item) for item in cast(list[Any], value)]
    if isinstance(value, str):
        return value.replace("#/components/schemas/", "#/$defs/")
    return value


def _with_reachable_definitions(
    schema: dict[str, Any], definitions: dict[str, Any]
) -> dict[str, Any]:
    reachable: dict[str, Any] = {}

    def visit(value: Any) -> None:
        if isinstance(value, dict):
            mapping = cast(dict[str, Any], value)
            reference = mapping.get("$ref")
            if isinstance(reference, str) and reference.startswith("#/$defs/"):
                name = reference.removeprefix("#/$defs/")
                if name not in reachable:
                    reachable[name] = definitions[name]
                    visit(definitions[name])
            for item in mapping.values():
                visit(item)
        elif isinstance(value, list):
            for item in cast(list[Any], value):
                visit(item)

    visit(schema)
    return {**schema, "$defs": reachable} if reachable else schema


def interaction_routes(
    document: dict[str, Any] | None = None,
) -> tuple[InteractionRoute, ...]:
    if document is None:
        resource = files("armi_runtime.interfaces.creator_web_resources").joinpath(
            "openapi.json"
        )
        document = cast(
            dict[str, Any], json.loads(resource.read_text(encoding="utf-8"))
        )
    definitions = _local_refs(document["components"]["schemas"])
    found: set[str] = set()
    routes: list[InteractionRoute] = []
    for path, methods in document["paths"].items():
        for method, spec in methods.items():
            operation_id = spec["operationId"]
            if operation_id in TRANSPORT_OPERATIONS:
                continue
            group, action = OPERATION_NAMES[operation_id]
            found.add(operation_id)
            properties: dict[str, Any] = {}
            required: list[str] = []
            parameters: dict[str, list[str]] = {"path": [], "query": []}
            headers: list[tuple[str, str]] = []
            for parameter in spec.get("parameters", []):
                if (
                    parameter["in"] == "header"
                    and parameter["name"].lower() == "authorization"
                ):
                    continue
                name = parameter["name"].lower().replace("-", "_")
                properties[name] = _local_refs(parameter["schema"])
                if parameter.get("required"):
                    required.append(name)
                if parameter["in"] == "header":
                    headers.append((name, parameter["name"].lower()))
                else:
                    parameters[parameter["in"]].append(name)
            body_names: tuple[str, ...] = ()
            body_version: str | None = None
            body = (
                spec.get("requestBody", {})
                .get("content", {})
                .get("application/json", {})
                .get("schema")
            )
            if body is not None:
                body = deepcopy(body)
                if "$ref" in body:
                    body = deepcopy(
                        document["components"]["schemas"][
                            body["$ref"].rsplit("/", 1)[-1]
                        ]
                    )
                body_properties = body.get("properties", {})
                version = body_properties.pop("contract_version", None)
                if version is not None:
                    body_version = version.get("const", version.get("default"))
                body_names = tuple(body_properties)
                if set(properties) & set(body_properties):
                    raise ValueError("INTERACTION-CONTRACT-PARAMETER-COLLISION")
                properties.update(_local_refs(body_properties))
                required.extend(
                    name
                    for name in body.get("required", [])
                    if name != "contract_version"
                )
            schema = {
                "type": "object",
                "properties": properties,
                "required": required,
                "additionalProperties": False,
            }
            responses = [
                _local_refs(response["content"]["application/json"]["schema"])
                for response in spec.get("responses", {}).values()
                if "application/json" in response.get("content", {})
            ]
            output = _with_reachable_definitions(
                {
                    "type": "object",
                    "properties": {
                        "environment_id": {"type": "string", "format": "uuid"},
                        "status": {"type": "string"},
                        "error_code": {"type": "string"},
                        "transport_status": {"type": "integer"},
                        "result": {
                            "anyOf": [
                                *responses,
                                {
                                    "type": "object",
                                    "required": ["error_code"],
                                    "properties": {"error_code": {"type": "string"}},
                                },
                                {"type": "object", "maxProperties": 0},
                            ]
                        },
                        "artifact": {
                            "type": "object",
                            "required": ["media_type", "encoding", "content"],
                            "properties": {
                                "media_type": {"type": "string"},
                                "encoding": {"const": "base64"},
                                "content": {
                                    "type": "string",
                                    "contentEncoding": "base64",
                                },
                            },
                            "additionalProperties": False,
                        },
                    },
                    "additionalProperties": False,
                },
                definitions,
            )
            operation = InteractionOperation(
                name=f"{group.replace('-', '_')}_{action}",
                group=group,
                action=action,
                mutating=method not in {"get", "head"},
                input_schema=_with_reachable_definitions(schema, definitions),
                output_schema=output,
            )
            routes.append(
                InteractionRoute(
                    operation,
                    operation_id,
                    method.upper(),
                    path,
                    tuple(parameters["path"]),
                    tuple(parameters["query"]),
                    tuple(headers),
                    body_names,
                    body_version,
                )
            )
    if found != set(OPERATION_NAMES):
        raise ValueError("INTERACTION-CONTRACT-COVERAGE")
    return tuple(routes)


__all__ = (
    "OPERATION_NAMES",
    "TRANSPORT_OPERATIONS",
    "InteractionRoute",
    "interaction_routes",
)
