"""Strict Ark built-in Web Search governance boundary for the active pipeline."""

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


def _reject_prohibited(value: object) -> None:
    if isinstance(value, dict):
        for key, child in cast(dict[Any, Any], value).items():
            if key in _PROHIBITED_KEYS and child not in (None, "", [], {}):
                raise WebSearchViolation("WEB-SEARCH-RESPONSE-PROHIBITED")
            _reject_prohibited(child)
    elif isinstance(value, list):
        for child in cast(list[Any], value):
            _reject_prohibited(child)


def normalize_provider_response(
    raw: Mapping[str, object],
) -> tuple[bytes, dict[str, int]]:
    """Validate once while retaining only content-free structural evidence."""

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
    calls = 0
    messages = 0
    citation_count = 0
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
            if item.get("status") != "completed" or action_type not in _ACTION_TYPES:
                raise WebSearchViolation("WEB-SEARCH-RESPONSE-CALL")
            calls += 1
            output.append(
                {
                    "type": "web_search_call",
                    "status": item.get("status"),
                    "action_type": action_type,
                }
            )
        elif item_type == "message":
            if item.get("role") != "assistant":
                raise WebSearchViolation("WEB-SEARCH-RESPONSE-MESSAGE")
            content_value = item.get("content")
            if not isinstance(content_value, list):
                raise WebSearchViolation("WEB-SEARCH-RESPONSE-MESSAGE")
            content: list[dict[str, object]] = []
            for part_value in cast(list[object], content_value):
                if not isinstance(part_value, dict):
                    raise WebSearchViolation("WEB-SEARCH-RESPONSE-MESSAGE")
                part = cast(dict[str, object], part_value)
                if part.get("type") != "output_text":
                    raise WebSearchViolation("WEB-SEARCH-RESPONSE-MESSAGE")
                annotations = part.get("annotations", [])
                if not isinstance(annotations, list):
                    raise WebSearchViolation("WEB-SEARCH-RESPONSE-MESSAGE")
                normalized_citations: list[dict[str, object]] = []
                for annotation_value in cast(list[object], annotations):
                    if not isinstance(annotation_value, dict):
                        raise WebSearchViolation("WEB-SEARCH-RESPONSE-SOURCE")
                    annotation = cast(dict[str, object], annotation_value)
                    if annotation.get("type") != "url_citation":
                        raise WebSearchViolation("WEB-SEARCH-RESPONSE-SOURCE")
                    url = _source_url(annotation.get("url"))
                    title = _text(annotation.get("title"), "WEB-SEARCH-RESPONSE-SOURCE")
                    citation_count += 1
                    normalized_citations.append({"url": url, "title": title})
                content.append(
                    {"type": part.get("type"), "citations": normalized_citations}
                )
            messages += 1
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
    web_search_calls_value = (
        tool_usage_map.get("web_search") if tool_usage_map is not None else None
    )
    input_tokens = _positive_int(usage.get("input_tokens"), "WEB-SEARCH-RESPONSE-USAGE")
    output_tokens = _positive_int(
        usage.get("output_tokens"), "WEB-SEARCH-RESPONSE-USAGE"
    )
    web_search_calls = _positive_int(
        web_search_calls_value, "WEB-SEARCH-RESPONSE-USAGE"
    )
    if calls < 1 or calls > MAX_TOOL_CALLS or messages != 1:
        raise WebSearchViolation("WEB-SEARCH-RESPONSE-EVIDENCE")
    if citation_count < 1 or citation_count > MAX_SOURCES or web_search_calls < calls:
        raise WebSearchViolation("WEB-SEARCH-RESPONSE-EVIDENCE")
    normalized: dict[str, object] = {
        "model": model,
        "store": False,
        "status": status,
        "output": output,
        "usage": {
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "web_search_calls": web_search_calls,
        },
    }
    normalized_bytes = json.dumps(
        normalized, ensure_ascii=False, separators=(",", ":")
    ).encode("utf-8")
    evidence = {
        "tool_call_count": calls,
        "provider_web_search_calls": web_search_calls,
        "citation_count": citation_count,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
    }
    return normalized_bytes, evidence


__all__ = ()
