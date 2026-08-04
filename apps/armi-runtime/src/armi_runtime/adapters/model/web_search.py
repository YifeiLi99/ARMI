"""Strict, inactive Ark built-in Web Search governance boundary.

S032 proves the provider-managed tool contract only. Production cognition keeps
``tools=[]`` until S033 adds durable tool-call custody.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any, Final, cast
from urllib.parse import urlsplit

PROVIDER: Final = "volcengine_ark"
MODEL: Final = "doubao-seed-evolving"
API_BASE: Final = "https://ark.cn-beijing.volces.com/api/v3"
BINDING_ID: Final = "armi.model-tool.volcengine-ark-web-search-v1"
TOOL_DECLARATION: Final = {"type": "web_search"}
MAX_RESPONSE_BYTES: Final = 1024 * 1024
MAX_TOOL_CALLS: Final = 8
MAX_SOURCES: Final = 128

_ACTION_TYPES = frozenset({"search", "open_page", "find_in_page"})
_PROHIBITED_KEYS = frozenset(
    {
        "reasoning_content",
        "encrypted_content",
        "computer_control",
        "browser_control",
        "mcp_call",
        "function_call",
    }
)


class WebSearchViolation(ValueError):
    """A stable, content-free Web Search boundary failure."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def _pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise WebSearchViolation("WEB-SEARCH-CODEC-DUPLICATE-KEY")
        result[key] = value
    return result


def strict_json_bytes(raw: bytes, *, maximum: int) -> Any:
    """Decode one UTF-8 JSON value and reject duplicate keys and BOM."""

    if not raw or len(raw) > maximum or raw.startswith(b"\xef\xbb\xbf"):
        raise WebSearchViolation("WEB-SEARCH-CODEC-SIZE")
    try:
        return json.loads(
            raw.decode("utf-8", errors="strict"), object_pairs_hook=_pairs
        )
    except WebSearchViolation:
        raise
    except UnicodeDecodeError, json.JSONDecodeError:
        raise WebSearchViolation("WEB-SEARCH-CODEC-JSON") from None


def _exact(value: Mapping[str, Any], keys: frozenset[str], code: str) -> None:
    if frozenset(value) != keys:
        raise WebSearchViolation(code)


def _positive_int(value: object, code: str) -> int:
    if type(value) is not int or value <= 0:
        raise WebSearchViolation(code)
    return value


def _text(value: object, code: str, *, maximum: int = 1024) -> str:
    if not isinstance(value, str) or not value or len(value) > maximum:
        raise WebSearchViolation(code)
    return value


def _source_url(value: object) -> str:
    url = _text(value, "WEB-SEARCH-SOURCE", maximum=4096)
    parsed = urlsplit(url)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.hostname.lower() in {"localhost", "localhost.localdomain"}
    ):
        raise WebSearchViolation("WEB-SEARCH-SOURCE")
    return url


def validate_tool_declaration(value: object) -> None:
    """Allow only Ark's provider-managed built-in Web Search tool."""

    if value != TOOL_DECLARATION:
        raise WebSearchViolation("WEB-SEARCH-TOOL-DRIFT")


def _reject_prohibited(value: object) -> None:
    if isinstance(value, dict):
        for key, child in cast(dict[Any, Any], value).items():
            if key in _PROHIBITED_KEYS and child not in (None, "", [], {}):
                raise WebSearchViolation("WEB-SEARCH-RESPONSE-PROHIBITED")
            _reject_prohibited(child)
    elif isinstance(value, list):
        for child in cast(list[Any], value):
            _reject_prohibited(child)


def normalize_provider_response(raw: Mapping[str, object]) -> bytes:
    """Remove content and retain only structural data needed for validation."""

    encoded = json.dumps(raw, ensure_ascii=False, separators=(",", ":")).encode()
    if len(encoded) > MAX_RESPONSE_BYTES:
        raise WebSearchViolation("WEB-SEARCH-RESPONSE-SIZE")
    _reject_prohibited(raw)
    model = _text(raw.get("model"), "WEB-SEARCH-RESPONSE-MODEL")
    if not model.startswith(MODEL) or raw.get("store") is not False:
        raise WebSearchViolation("WEB-SEARCH-RESPONSE-MODEL")
    status = raw.get("status")
    if status not in {"completed", "incomplete"}:
        raise WebSearchViolation("WEB-SEARCH-RESPONSE-STATUS")
    output_value = raw.get("output")
    if not isinstance(output_value, list):
        raise WebSearchViolation("WEB-SEARCH-RESPONSE-OUTPUT")
    output: list[dict[str, object]] = []
    for item_value in cast(list[object], output_value):
        if not isinstance(item_value, dict):
            raise WebSearchViolation("WEB-SEARCH-RESPONSE-ITEM")
        item = cast(dict[str, object], item_value)
        item_type = item.get("type")
        if item_type == "web_search_call":
            action_value = item.get("action")
            action = (
                cast(dict[str, object], action_value)
                if isinstance(action_value, dict)
                else None
            )
            action_type = action.get("type") if action is not None else None
            output.append(
                {
                    "type": "web_search_call",
                    "status": item.get("status"),
                    "action_type": action_type,
                }
            )
        elif item_type == "message":
            content_value = item.get("content")
            if not isinstance(content_value, list):
                raise WebSearchViolation("WEB-SEARCH-RESPONSE-MESSAGE")
            content: list[dict[str, object]] = []
            for part_value in cast(list[object], content_value):
                if not isinstance(part_value, dict):
                    raise WebSearchViolation("WEB-SEARCH-RESPONSE-MESSAGE")
                part = cast(dict[str, object], part_value)
                annotations = part.get("annotations", [])
                if not isinstance(annotations, list):
                    raise WebSearchViolation("WEB-SEARCH-RESPONSE-MESSAGE")
                citations: list[dict[str, object]] = []
                for annotation_value in cast(list[object], annotations):
                    if not isinstance(annotation_value, dict):
                        raise WebSearchViolation("WEB-SEARCH-RESPONSE-SOURCE")
                    annotation = cast(dict[str, object], annotation_value)
                    if annotation.get("type") != "url_citation":
                        raise WebSearchViolation("WEB-SEARCH-RESPONSE-SOURCE")
                    citations.append(
                        {"url": annotation.get("url"), "title": annotation.get("title")}
                    )
                content.append({"type": part.get("type"), "citations": citations})
            output.append(
                {"type": "message", "role": item.get("role"), "content": content}
            )
        else:
            raise WebSearchViolation("WEB-SEARCH-RESPONSE-UNKNOWN-EVENT")
    usage_value = raw.get("usage")
    if not isinstance(usage_value, dict):
        raise WebSearchViolation("WEB-SEARCH-RESPONSE-USAGE")
    usage = cast(dict[str, object], usage_value)
    tool_usage = usage.get("tool_usage")
    tool_usage_map = (
        cast(dict[str, object], tool_usage) if isinstance(tool_usage, dict) else None
    )
    web_search_calls = (
        tool_usage_map.get("web_search") if tool_usage_map is not None else None
    )
    normalized: dict[str, object] = {
        "model": model,
        "store": False,
        "status": status,
        "output": output,
        "usage": {
            "input_tokens": usage.get("input_tokens"),
            "output_tokens": usage.get("output_tokens"),
            "web_search_calls": web_search_calls,
        },
    }
    return json.dumps(normalized, ensure_ascii=False, separators=(",", ":")).encode(
        "utf-8"
    )


def validate_response(raw: bytes) -> dict[str, int]:
    """Validate normalized provider output and return content-free counts."""

    parsed = strict_json_bytes(raw, maximum=MAX_RESPONSE_BYTES)
    if not isinstance(parsed, dict):
        raise WebSearchViolation("WEB-SEARCH-RESPONSE-FORMAT")
    value = cast(dict[str, Any], parsed)
    _exact(
        value,
        frozenset({"model", "store", "status", "output", "usage"}),
        "WEB-SEARCH-RESPONSE-FIELDS",
    )
    if (
        not _text(value["model"], "WEB-SEARCH-RESPONSE-MODEL").startswith(MODEL)
        or value["store"] is not False
        or value["status"] not in {"completed", "incomplete"}
    ):
        raise WebSearchViolation("WEB-SEARCH-RESPONSE-MODEL")
    output_value = value["output"]
    if not isinstance(output_value, list) or not output_value:
        raise WebSearchViolation("WEB-SEARCH-RESPONSE-OUTPUT")
    calls = 0
    messages = 0
    citations = 0
    for item_value in cast(list[Any], output_value):
        if not isinstance(item_value, dict):
            raise WebSearchViolation("WEB-SEARCH-RESPONSE-ITEM")
        item = cast(dict[str, Any], item_value)
        if item.get("type") == "web_search_call":
            _exact(
                item,
                frozenset({"type", "status", "action_type"}),
                "WEB-SEARCH-RESPONSE-CALL-FIELDS",
            )
            if (
                item["status"] != "completed"
                or item["action_type"] not in _ACTION_TYPES
            ):
                raise WebSearchViolation("WEB-SEARCH-RESPONSE-CALL")
            calls += 1
        elif item.get("type") == "message":
            _exact(
                item,
                frozenset({"type", "role", "content"}),
                "WEB-SEARCH-RESPONSE-MESSAGE-FIELDS",
            )
            if item["role"] != "assistant" or not isinstance(item["content"], list):
                raise WebSearchViolation("WEB-SEARCH-RESPONSE-MESSAGE")
            messages += 1
            for part_value in cast(list[Any], item["content"]):
                if not isinstance(part_value, dict):
                    raise WebSearchViolation("WEB-SEARCH-RESPONSE-MESSAGE")
                part = cast(dict[str, Any], part_value)
                _exact(
                    part,
                    frozenset({"type", "citations"}),
                    "WEB-SEARCH-RESPONSE-MESSAGE-FIELDS",
                )
                if part["type"] != "output_text" or not isinstance(
                    part["citations"], list
                ):
                    raise WebSearchViolation("WEB-SEARCH-RESPONSE-MESSAGE")
                for source_value in cast(list[Any], part["citations"]):
                    if not isinstance(source_value, dict):
                        raise WebSearchViolation("WEB-SEARCH-RESPONSE-SOURCE")
                    source = cast(dict[str, Any], source_value)
                    _exact(
                        source,
                        frozenset({"url", "title"}),
                        "WEB-SEARCH-RESPONSE-SOURCE-FIELDS",
                    )
                    _source_url(source["url"])
                    _text(source["title"], "WEB-SEARCH-RESPONSE-SOURCE")
                    citations += 1
        else:
            raise WebSearchViolation("WEB-SEARCH-RESPONSE-UNKNOWN-EVENT")
    usage_value = value["usage"]
    if not isinstance(usage_value, dict):
        raise WebSearchViolation("WEB-SEARCH-RESPONSE-USAGE")
    usage = cast(dict[str, Any], usage_value)
    _exact(
        usage,
        frozenset({"input_tokens", "output_tokens", "web_search_calls"}),
        "WEB-SEARCH-RESPONSE-USAGE-FIELDS",
    )
    input_tokens = _positive_int(usage["input_tokens"], "WEB-SEARCH-RESPONSE-USAGE")
    output_tokens = _positive_int(usage["output_tokens"], "WEB-SEARCH-RESPONSE-USAGE")
    billed_calls = _positive_int(usage["web_search_calls"], "WEB-SEARCH-RESPONSE-USAGE")
    if calls < 1 or calls > MAX_TOOL_CALLS or messages != 1:
        raise WebSearchViolation("WEB-SEARCH-RESPONSE-EVIDENCE")
    if citations < 1 or citations > MAX_SOURCES or billed_calls < calls:
        raise WebSearchViolation("WEB-SEARCH-RESPONSE-EVIDENCE")
    return {
        "tool_call_count": calls,
        "provider_web_search_calls": billed_calls,
        "citation_count": citations,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
    }


__all__ = ()
