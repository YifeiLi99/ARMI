"""Strict, inactive Remote MCP governance and response boundary.

S032 validates a provider-hosted binding only.  Production cognition deliberately
continues to send ``tools=[]`` until S033 introduces durable tool-call custody.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Final, cast
from urllib.parse import urlsplit

SCHEMA_VERSION: Final = "armi.remote-mcp-binding.v1"
PROVIDER: Final = "volcengine_ark"
MODEL: Final = "doubao-seed-evolving"
API_BASE: Final = "https://ark.cn-beijing.volces.com/api/v3"
MAX_ARGUMENT_BYTES: Final = 16 * 1024
MAX_RESULT_BYTES: Final = 512 * 1024
MAX_RESPONSE_BYTES: Final = 1024 * 1024
MAX_TOOL_CALLS: Final = 8
MAX_SOURCES: Final = 128

_ROOT_KEYS = frozenset(
    {
        "schema_version",
        "provider",
        "model",
        "api_base",
        "active_binding",
        "binding",
        "candidate",
        "discovery",
        "live_gate",
        "production_model_tools",
        "reason_code",
        "store",
        "transport",
        "activation",
    }
)
_WRITE_WORDS = frozenset(
    {
        "create",
        "delete",
        "download",
        "execute",
        "login",
        "post",
        "purchase",
        "send",
        "update",
        "upload",
        "write",
    }
)
_CAPABILITIES = frozenset({"search", "read", "citations"})
_PROHIBITED_KEYS = frozenset(
    {
        "reasoning",
        "reasoning_content",
        "encrypted_content",
        "computer_control",
        "browser_control",
    }
)


class RemoteMcpViolation(ValueError):
    """A stable, content-free Remote MCP boundary failure."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def _pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise RemoteMcpViolation("MCP-CODEC-DUPLICATE-KEY")
        result[key] = value
    return result


def strict_json_bytes(raw: bytes, *, maximum: int) -> Any:
    """Decode one strict UTF-8 JSON value with duplicate-key rejection."""

    if not raw or len(raw) > maximum or raw.startswith(b"\xef\xbb\xbf"):
        raise RemoteMcpViolation("MCP-CODEC-SIZE")
    try:
        text = raw.decode("utf-8", errors="strict")
        value = json.loads(text, object_pairs_hook=_pairs)
    except RemoteMcpViolation:
        raise
    except UnicodeDecodeError, json.JSONDecodeError:
        raise RemoteMcpViolation("MCP-CODEC-JSON") from None
    return value


def _exact(value: Mapping[str, Any], keys: frozenset[str], code: str) -> None:
    if frozenset(value) != keys:
        raise RemoteMcpViolation(code)


def _text(value: object, code: str, *, maximum: int = 256) -> str:
    if not isinstance(value, str) or not value or len(value) > maximum:
        raise RemoteMcpViolation(code)
    return value


def _https_endpoint(value: object) -> str:
    endpoint = _text(value, "MCP-BINDING-ENDPOINT", maximum=2048)
    parsed = urlsplit(endpoint)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        raise RemoteMcpViolation("MCP-BINDING-ENDPOINT")
    return endpoint


@dataclass(frozen=True, slots=True)
class RemoteMcpTool:
    name: str
    capability: str
    input_schema: Mapping[str, Any]
    source_fields: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class RemoteMcpBinding:
    binding_id: str
    service_id: str
    operator: str
    endpoint: str
    tools: tuple[RemoteMcpTool, ...]


@dataclass(frozen=True, slots=True)
class RemoteMcpGovernance:
    status: str
    reason_code: str | None
    binding: RemoteMcpBinding | None


def load_governance(raw: bytes) -> RemoteMcpGovernance:
    """Validate the versioned governance manifest without discovering services."""

    parsed = strict_json_bytes(raw, maximum=256 * 1024)
    if not isinstance(parsed, dict):
        raise RemoteMcpViolation("MCP-MANIFEST-FORMAT")
    value = cast(dict[str, Any], parsed)
    _exact(value, _ROOT_KEYS, "MCP-MANIFEST-FIELDS")
    if (
        value["schema_version"] != SCHEMA_VERSION
        or value["provider"] != PROVIDER
        or value["model"] != MODEL
        or value["api_base"] != API_BASE
        or value["store"] is not False
        or value["production_model_tools"] != []
    ):
        raise RemoteMcpViolation("MCP-MANIFEST-IDENTITY")
    transport_value = value["transport"]
    if not isinstance(transport_value, dict):
        raise RemoteMcpViolation("MCP-MANIFEST-TRANSPORT")
    transport = cast(dict[str, Any], transport_value)
    if transport != {
        "beta_header": "ark-beta-mcp",
        "max_retries": 0,
        "response_api": True,
    }:
        raise RemoteMcpViolation("MCP-MANIFEST-TRANSPORT")
    discovery_value = value["discovery"]
    if not isinstance(discovery_value, dict):
        raise RemoteMcpViolation("MCP-MANIFEST-DISCOVERY")
    discovery = cast(dict[str, Any], discovery_value)
    if discovery.get("dynamic_discovery") is not False:
        raise RemoteMcpViolation("MCP-MANIFEST-DISCOVERY")
    if discovery.get("additional_credential_allowed") is not False:
        raise RemoteMcpViolation("MCP-MANIFEST-CREDENTIAL")
    if value["active_binding"] is None:
        if value["binding"] is not None or discovery.get("status") != "blocked":
            raise RemoteMcpViolation("MCP-MANIFEST-BLOCKED")
        reason = _text(value["reason_code"], "MCP-MANIFEST-BLOCKED")
        return RemoteMcpGovernance("blocked", reason, None)
    binding = _binding(value["active_binding"], value["binding"])
    if discovery.get("status") != "verified" or value["reason_code"] is not None:
        raise RemoteMcpViolation("MCP-MANIFEST-ACTIVE")
    return RemoteMcpGovernance("verified", None, binding)


def _binding(identity: object, value: object) -> RemoteMcpBinding:
    binding_id = _text(identity, "MCP-BINDING-IDENTITY")
    if not isinstance(value, dict):
        raise RemoteMcpViolation("MCP-BINDING-FORMAT")
    binding = cast(dict[str, Any], value)
    _exact(
        binding,
        frozenset({"binding_id", "service_id", "operator", "endpoint", "tools"}),
        "MCP-BINDING-FIELDS",
    )
    if binding["binding_id"] != binding_id:
        raise RemoteMcpViolation("MCP-BINDING-IDENTITY")
    raw_tools = binding["tools"]
    if not isinstance(raw_tools, list) or not raw_tools:
        raise RemoteMcpViolation("MCP-BINDING-TOOLS")
    tools = tuple(_tool(item) for item in cast(list[Any], raw_tools))
    if len({tool.name for tool in tools}) != len(tools):
        raise RemoteMcpViolation("MCP-BINDING-TOOLS")
    if {tool.capability for tool in tools} != set(_CAPABILITIES):
        raise RemoteMcpViolation("MCP-BINDING-COVERAGE")
    return RemoteMcpBinding(
        binding_id=binding_id,
        service_id=_text(binding["service_id"], "MCP-BINDING-IDENTITY"),
        operator=_text(binding["operator"], "MCP-BINDING-IDENTITY"),
        endpoint=_https_endpoint(binding["endpoint"]),
        tools=tools,
    )


def _tool(value: object) -> RemoteMcpTool:
    if not isinstance(value, dict):
        raise RemoteMcpViolation("MCP-BINDING-TOOLS")
    tool = cast(dict[str, Any], value)
    _exact(
        tool,
        frozenset({"name", "capability", "input_schema", "source_fields"}),
        "MCP-BINDING-TOOL-FIELDS",
    )
    name = _text(tool["name"], "MCP-BINDING-TOOL-NAME")
    lowered = name.lower().replace("-", "_")
    if any(word in lowered.split("_") for word in _WRITE_WORDS):
        raise RemoteMcpViolation("MCP-BINDING-WRITE-TOOL")
    capability = _text(tool["capability"], "MCP-BINDING-CAPABILITY")
    if capability not in _CAPABILITIES:
        raise RemoteMcpViolation("MCP-BINDING-CAPABILITY")
    schema_value = tool["input_schema"]
    sources_value = tool["source_fields"]
    if not isinstance(schema_value, dict):
        raise RemoteMcpViolation("MCP-BINDING-SCHEMA")
    schema = cast(dict[str, Any], schema_value)
    if schema.get("type") != "object":
        raise RemoteMcpViolation("MCP-BINDING-SCHEMA")
    if not isinstance(sources_value, list):
        raise RemoteMcpViolation("MCP-BINDING-SOURCES")
    sources = cast(list[Any], sources_value)
    if not sources or not all(isinstance(item, str) and item for item in sources):
        raise RemoteMcpViolation("MCP-BINDING-SOURCES")
    return RemoteMcpTool(name, capability, schema, tuple(cast(list[str], sources)))


def validate_tool_declaration(binding: RemoteMcpBinding, value: object) -> None:
    """Require an exact, approval-free Remote MCP declaration."""

    expected = {
        "type": "mcp",
        "server_label": binding.binding_id,
        "server_url": binding.endpoint,
        "require_approval": "never",
        "allowed_tools": {"tool_names": [tool.name for tool in binding.tools]},
    }
    if value != expected:
        raise RemoteMcpViolation("MCP-DECLARATION-DRIFT")


def validate_response(raw: bytes, binding: RemoteMcpBinding) -> dict[str, object]:
    """Validate provider output and return content-free structural evidence."""

    parsed = strict_json_bytes(raw, maximum=MAX_RESPONSE_BYTES)
    if not isinstance(parsed, dict):
        raise RemoteMcpViolation("MCP-RESPONSE-FORMAT")
    value = cast(dict[str, Any], parsed)
    output = value.get("output")
    if not isinstance(output, list):
        raise RemoteMcpViolation("MCP-RESPONSE-OUTPUT")
    output_items = cast(list[Any], output)
    if not output_items or len(output_items) > MAX_TOOL_CALLS + 2:
        raise RemoteMcpViolation("MCP-RESPONSE-OUTPUT")
    _reject_prohibited(value)
    allowed = {tool.name: tool for tool in binding.tools}
    calls = 0
    citations = 0
    final_messages = 0
    for item_value in output_items:
        if not isinstance(item_value, dict):
            raise RemoteMcpViolation("MCP-RESPONSE-ITEM")
        item = cast(dict[str, Any], item_value)
        item_type = item.get("type")
        if item_type == "mcp_list_tools":
            _validate_list(item, allowed)
        elif item_type == "mcp_call":
            calls += 1
            citations += _validate_call(item, allowed)
        elif item_type == "message":
            final_messages += 1
            citations += _validate_message(item)
        else:
            raise RemoteMcpViolation("MCP-RESPONSE-UNKNOWN-EVENT")
    if calls < 1 or final_messages != 1 or citations < 1 or citations > MAX_SOURCES:
        raise RemoteMcpViolation("MCP-RESPONSE-EVIDENCE")
    return {"tool_call_count": calls, "citation_count": citations}


def _reject_prohibited(value: object) -> None:
    if isinstance(value, dict):
        for key, child in cast(dict[Any, Any], value).items():
            if key in _PROHIBITED_KEYS:
                raise RemoteMcpViolation("MCP-RESPONSE-PROHIBITED")
            _reject_prohibited(child)
    elif isinstance(value, list):
        for child in cast(list[Any], value):
            _reject_prohibited(child)


def _validate_list(
    item: Mapping[str, Any], allowed: Mapping[str, RemoteMcpTool]
) -> None:
    if set(item) != {"type", "server_label", "tools"}:
        raise RemoteMcpViolation("MCP-RESPONSE-LIST-FIELDS")
    tools_value = item["tools"]
    if item["server_label"] == "" or not isinstance(tools_value, list):
        raise RemoteMcpViolation("MCP-RESPONSE-LIST")
    names: list[str] = []
    for tool_value in cast(list[Any], tools_value):
        if not isinstance(tool_value, dict):
            raise RemoteMcpViolation("MCP-RESPONSE-LIST")
        tool = cast(dict[str, Any], tool_value)
        if set(tool) != {"name", "input_schema"}:
            raise RemoteMcpViolation("MCP-RESPONSE-LIST")
        names.append(_text(tool["name"], "MCP-RESPONSE-LIST"))
    if names != list(allowed):
        raise RemoteMcpViolation("MCP-RESPONSE-TOOL-DRIFT")


def _validate_call(
    item: Mapping[str, Any], allowed: Mapping[str, RemoteMcpTool]
) -> int:
    if set(item) != {"type", "server_label", "name", "arguments", "result"}:
        raise RemoteMcpViolation("MCP-RESPONSE-CALL-FIELDS")
    name = item["name"]
    if name not in allowed:
        raise RemoteMcpViolation("MCP-RESPONSE-UNKNOWN-TOOL")
    arguments = item["arguments"]
    result = item["result"]
    encoded_arguments = json.dumps(arguments, ensure_ascii=False).encode("utf-8")
    encoded_result = json.dumps(result, ensure_ascii=False).encode("utf-8")
    if len(encoded_arguments) > MAX_ARGUMENT_BYTES:
        raise RemoteMcpViolation("MCP-RESPONSE-ARGUMENT-SIZE")
    if len(encoded_result) > MAX_RESULT_BYTES:
        raise RemoteMcpViolation("MCP-RESPONSE-RESULT-SIZE")
    if not isinstance(arguments, dict) or not isinstance(result, dict):
        raise RemoteMcpViolation("MCP-RESPONSE-CALL")
    result_value = cast(dict[str, Any], result)
    sources_value = result_value.get("sources")
    if not isinstance(sources_value, list) or not sources_value:
        raise RemoteMcpViolation("MCP-RESPONSE-SOURCES")
    sources = cast(list[Any], sources_value)
    for source_value in sources:
        if not isinstance(source_value, dict):
            raise RemoteMcpViolation("MCP-RESPONSE-SOURCES")
        source = cast(dict[str, Any], source_value)
        if set(source) != {"url", "title"}:
            raise RemoteMcpViolation("MCP-RESPONSE-SOURCES")
        _https_endpoint(source["url"])
        _text(source["title"], "MCP-RESPONSE-SOURCES", maximum=1024)
    return len(sources)


def _validate_message(item: Mapping[str, Any]) -> int:
    if set(item) != {"type", "role", "content"} or item["role"] != "assistant":
        raise RemoteMcpViolation("MCP-RESPONSE-MESSAGE")
    content_value = item["content"]
    if not isinstance(content_value, list) or not content_value:
        raise RemoteMcpViolation("MCP-RESPONSE-MESSAGE")
    content = cast(list[Any], content_value)
    citations = 0
    for part_value in content:
        if not isinstance(part_value, dict):
            raise RemoteMcpViolation("MCP-RESPONSE-MESSAGE")
        part = cast(dict[str, Any], part_value)
        if set(part) != {"type", "text", "citations"}:
            raise RemoteMcpViolation("MCP-RESPONSE-MESSAGE")
        if part["type"] != "output_text" or not isinstance(part["text"], str):
            raise RemoteMcpViolation("MCP-RESPONSE-MESSAGE")
        refs_value = part["citations"]
        if not isinstance(refs_value, list):
            raise RemoteMcpViolation("MCP-RESPONSE-MESSAGE")
        refs = cast(list[Any], refs_value)
        for ref_value in refs:
            if not isinstance(ref_value, dict):
                raise RemoteMcpViolation("MCP-RESPONSE-SOURCES")
            ref = cast(dict[str, Any], ref_value)
            if set(ref) != {"url", "title"}:
                raise RemoteMcpViolation("MCP-RESPONSE-SOURCES")
            _https_endpoint(ref["url"])
            _text(ref["title"], "MCP-RESPONSE-SOURCES", maximum=1024)
        citations += len(refs)
    return citations


__all__ = ()
