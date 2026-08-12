"""S033 Ark Web Search invocation and full restricted result custody codec."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Final, cast
from urllib.parse import urlsplit

import httpx
import rfc8785
from armi_kernel import load_yaml_mapping
from armi_kernel.application import (
    CredentialLocator,
    CredentialPort,
    CredentialPurpose,
)
from openai import APIConnectionError, APIStatusError, APITimeoutError, AsyncOpenAI

from ._observation_contract import (
    WebObservationInvocationResult,
    WebObservationResultStatus,
    WebObservationToolAction,
    WebObservationUsage,
    WebObservationViolation,
)
from ._provider_contract import API_BASE, MODEL, TOOL_DECLARATION

SCHEMA_VERSION: Final = "armi.web-search-custody.v1"
REQUEST_VERSION: Final = "armi.web-search-request.v1"
RESULT_VERSION: Final = "armi.web-search-result.v1"
MAX_REQUEST_BYTES: Final = 64 * 1024
MAX_RESULT_BYTES: Final = 1024 * 1024
MAX_TOOL_CALLS: Final = 8
MAX_CITATIONS: Final = 128
MAX_OUTPUT_TOKENS: Final = 1024
MAX_COST_MICROYUAN: Final = 1_000_000
_PURPOSE = CredentialPurpose("web.search")
_FINGERPRINT_DOMAIN = b"armi.web-search.credential-fingerprint.v1\0"
_ACTIONS = {
    "search": WebObservationToolAction.SEARCH,
    "open_page": WebObservationToolAction.OPEN_PAGE,
    "find_in_page": WebObservationToolAction.FIND_IN_PAGE,
}
_ACTION_FIELDS = {
    "search": frozenset({"type", "query", "queries", "sources"}),
    "open_page": frozenset({"type", "url"}),
    "find_in_page": frozenset({"type", "url", "pattern"}),
}
_PROHIBITED_KEYS = frozenset(
    {
        "reasoning_content",
        "encrypted_content",
        "mcp_call",
        "function_call",
        "computer_control",
        "browser_control",
    }
)


@dataclass(frozen=True, slots=True)
class WebSearchCustodyPolicy:
    binding_id: str
    input_microyuan_per_million: int
    output_microyuan_per_million: int


def load_custody_policy(raw: bytes) -> WebSearchCustodyPolicy:
    if len(raw) > 128 * 1024:
        raise WebObservationViolation("WEB-MANIFEST")
    try:
        value = load_yaml_mapping(raw)
    except ValueError:
        raise WebObservationViolation("WEB-MANIFEST") from None
    expected = {
        "binding_id": "armi.model-tool.volcengine-ark-web-search-v1",
        "credential_identity": "armi.model.ark-api-key.v1",
        "credential_locator": "model.ark_api_key",
        "credential_purpose": "web.search",
        "limits": {
            "canonical_request_bytes": MAX_REQUEST_BYTES,
            "max_citations": MAX_CITATIONS,
            "max_cost_microyuan": MAX_COST_MICROYUAN,
            "max_output_tokens": MAX_OUTPUT_TOKENS,
            "max_result_bytes": MAX_RESULT_BYTES,
            "max_tool_calls": MAX_TOOL_CALLS,
            "query_bytes": 16 * 1024,
            "step_timeout_seconds": 30,
            "total_timeout_seconds": 90,
        },
        "model": MODEL,
        "operation_class": "search_read_public",
        "production_cognition_tools": [],
        "provider": "volcengine_ark",
        "purpose": "public_web_research",
        "response_api_base": API_BASE,
        "result_contract": RESULT_VERSION,
        "schema_version": SCHEMA_VERSION,
        "store": False,
        "tool_actions": ["search", "open_page", "find_in_page"],
        "tool_declaration": TOOL_DECLARATION,
    }
    if value != expected:
        raise WebObservationViolation("WEB-MANIFEST-DRIFT")
    return WebSearchCustodyPolicy(
        "armi.model-tool.volcengine-ark-web-search-v1",
        6_000_000,
        30_000_000,
    )


def build_request_bytes(
    *,
    request_id: str,
    subject_id: str,
    runtime_instance_id: str,
    fence_token: int,
    idempotency_key: str,
    query: str,
) -> bytes:
    value = {
        "schema_version": REQUEST_VERSION,
        "request_id": request_id,
        "subject_id": subject_id,
        "runtime_fence": {
            "runtime_instance_id": runtime_instance_id,
            "fence_token": fence_token,
        },
        "idempotency_key": idempotency_key,
        "purpose": "public_web_research",
        "operation_class": "search_read_public",
        "query": query,
        "tool_declaration": TOOL_DECLARATION,
        "store": False,
        "max_output_tokens": MAX_OUTPUT_TOKENS,
    }
    raw = rfc8785.dumps(cast(Any, value)) + b"\n"
    if len(raw) > MAX_REQUEST_BYTES:
        raise WebObservationViolation("WEB-REQUEST-SIZE")
    return raw


def parse_request_bytes(raw: bytes) -> dict[str, object]:
    value = _strict_json(raw, maximum=MAX_REQUEST_BYTES)
    if not isinstance(value, dict):
        raise WebObservationViolation("WEB-REQUEST")
    mapping = cast(dict[str, object], value)
    if frozenset(mapping) != frozenset(
        {
            "schema_version",
            "request_id",
            "subject_id",
            "runtime_fence",
            "idempotency_key",
            "purpose",
            "operation_class",
            "query",
            "tool_declaration",
            "store",
            "max_output_tokens",
        }
    ):
        raise WebObservationViolation("WEB-REQUEST-FIELDS")
    query = mapping.get("query")
    if (
        mapping.get("schema_version") != REQUEST_VERSION
        or mapping.get("purpose") != "public_web_research"
        or mapping.get("operation_class") != "search_read_public"
        or mapping.get("tool_declaration") != TOOL_DECLARATION
        or mapping.get("store") is not False
        or mapping.get("max_output_tokens") != MAX_OUTPUT_TOKENS
        or type(query) is not str
        or not query.strip()
        or "\x00" in query
        or len(query.encode("utf-8")) > 16 * 1024
    ):
        raise WebObservationViolation("WEB-REQUEST")
    if rfc8785.dumps(cast(Any, mapping)) + b"\n" != raw:
        raise WebObservationViolation("WEB-REQUEST-CANONICAL")
    return mapping


def normalize_full_response(
    raw: Mapping[str, object],
) -> tuple[bytes, tuple[WebObservationToolAction, ...], WebObservationUsage, str]:
    encoded = json.dumps(raw, ensure_ascii=False, separators=(",", ":")).encode()
    if len(encoded) > MAX_RESULT_BYTES:
        raise WebObservationViolation("WEB-RESULT-SIZE")
    _reject_prohibited(raw)
    model = _text(raw.get("model"), "WEB-PROVIDER-MODEL", maximum=128)
    if not model.startswith(MODEL) or raw.get("store") is not False:
        raise WebObservationViolation("WEB-PROVIDER-MODEL")
    if raw.get("status") != "completed":
        raise WebObservationViolation("WEB-PROVIDER-STATUS")
    output = raw.get("output")
    if not isinstance(output, list):
        raise WebObservationViolation("WEB-PROVIDER-OUTPUT")
    calls: list[dict[str, object]] = []
    actions: list[WebObservationToolAction] = []
    messages: list[dict[str, object]] = []
    citation_count = 0
    for item_value in cast(list[object], output):
        if not isinstance(item_value, dict):
            raise WebObservationViolation("WEB-PROVIDER-EVENT")
        item = cast(dict[str, object], item_value)
        if item.get("type") == "web_search_call":
            action_value = item.get("action")
            if item.get("status") != "completed" or not isinstance(action_value, dict):
                raise WebObservationViolation("WEB-TOOL-CALL")
            action = cast(dict[str, object], action_value)
            action_type = action.get("type")
            if type(action_type) is not str or action_type not in _ACTIONS:
                raise WebObservationViolation("WEB-TOOL-ACTION")
            action_fields = frozenset(action)
            if (
                not action_fields.issubset(_ACTION_FIELDS[action_type])
                or "type" not in action_fields
                or (
                    action_type != "search"
                    and action_fields != _ACTION_FIELDS[action_type]
                )
            ):
                raise WebObservationViolation("WEB-TOOL-ACTION")
            normalized_action = _normalize_action(action_type, action)
            calls.append(
                {
                    "ordinal": len(calls) + 1,
                    "action_type": action_type,
                    "action": normalized_action,
                }
            )
            actions.append(_ACTIONS[action_type])
        elif item.get("type") == "message":
            if item.get("role") != "assistant" or not isinstance(
                item.get("content"), list
            ):
                raise WebObservationViolation("WEB-PROVIDER-MESSAGE")
            parts: list[dict[str, object]] = []
            for part_value in cast(list[object], item["content"]):
                if not isinstance(part_value, dict):
                    raise WebObservationViolation("WEB-PROVIDER-MESSAGE")
                part = cast(dict[str, object], part_value)
                text = _text(
                    part.get("text"), "WEB-PROVIDER-MESSAGE", maximum=MAX_RESULT_BYTES
                )
                if part.get("type") != "output_text" or not isinstance(
                    part.get("annotations", []), list
                ):
                    raise WebObservationViolation("WEB-PROVIDER-MESSAGE")
                citations: list[dict[str, object]] = []
                for citation_value in cast(list[object], part.get("annotations", [])):
                    if not isinstance(citation_value, dict):
                        raise WebObservationViolation("WEB-CITATION")
                    citation = cast(dict[str, object], citation_value)
                    if citation.get("type") != "url_citation":
                        raise WebObservationViolation("WEB-CITATION")
                    citations.append(
                        {
                            "url": _url(citation.get("url")),
                            "title": _text(
                                citation.get("title"), "WEB-CITATION", maximum=1024
                            ),
                        }
                    )
                    citation_count += 1
                parts.append({"text": text, "citations": citations})
            messages.append({"parts": parts})
        else:
            raise WebObservationViolation("WEB-PROVIDER-EVENT")
    usage_value = raw.get("usage")
    if not isinstance(usage_value, dict):
        raise WebObservationViolation("WEB-USAGE")
    usage_map = cast(dict[str, object], usage_value)
    tool_usage = usage_map.get("tool_usage")
    web_calls = (
        cast(dict[str, object], tool_usage).get("web_search")
        if isinstance(tool_usage, dict)
        else None
    )
    input_tokens = _positive_int(usage_map.get("input_tokens"), "WEB-USAGE")
    output_tokens = _positive_int(usage_map.get("output_tokens"), "WEB-USAGE")
    billed_calls = _positive_int(web_calls, "WEB-USAGE")
    if not 1 <= len(calls) <= MAX_TOOL_CALLS or len(messages) != 1:
        raise WebObservationViolation("WEB-RESULT-EVIDENCE")
    if not 1 <= citation_count <= MAX_CITATIONS or billed_calls < len(calls):
        raise WebObservationViolation("WEB-RESULT-EVIDENCE")
    cost = (
        input_tokens * 6_000_000 + output_tokens * 30_000_000 + 999_999
    ) // 1_000_000
    usage = WebObservationUsage(
        input_tokens,
        output_tokens,
        billed_calls,
        citation_count,
        cost,
    )
    result = {
        "schema_version": RESULT_VERSION,
        "provider": "volcengine_ark",
        "model": model,
        "store": False,
        "tool_calls": calls,
        "messages": messages,
        "usage": {
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "web_search_calls": billed_calls,
            "citation_count": citation_count,
            "estimated_model_cost_microyuan": cost,
            "web_search_monetary_cost_available": False,
        },
    }
    canonical = rfc8785.dumps(cast(Any, result)) + b"\n"
    if len(canonical) > MAX_RESULT_BYTES:
        raise WebObservationViolation("WEB-RESULT-SIZE")
    return canonical, tuple(actions), usage, model


class ArkWebSearchAdapter:
    """One credential-scoped Ark call; no database or evidence access."""

    __slots__ = ("_credential_port", "_locator")

    def __init__(
        self, credential_port: CredentialPort, locator: CredentialLocator
    ) -> None:
        self._credential_port = credential_port
        self._locator = locator

    def credential_fingerprint(self) -> str:
        secret = self._copy_secret()
        try:
            return (
                "sha256:"
                + hashlib.sha256(_FINGERPRINT_DOMAIN + bytes(secret)).hexdigest()
            )
        finally:
            _wipe(secret)

    async def invoke(self, request_bytes: bytes) -> WebObservationInvocationResult:
        request = parse_request_bytes(request_bytes)
        query = cast(str, request["query"])
        secret = self._copy_secret()
        client = AsyncOpenAI(
            api_key=bytes(secret).decode("utf-8"),
            base_url=API_BASE,
            max_retries=0,
            timeout=httpx.Timeout(90, connect=30, read=30, write=30, pool=30),
            http_client=httpx.AsyncClient(trust_env=False),
        )
        try:
            response = await client.responses.create(
                model=MODEL,
                input=query,
                store=False,
                tools=cast(Any, [dict(TOOL_DECLARATION)]),
                max_output_tokens=MAX_OUTPUT_TOKENS,
                extra_body={"thinking": {"type": "disabled"}},
            )
            canonical, actions, usage, model = normalize_full_response(
                cast(dict[str, object], response.model_dump(mode="json"))
            )
            return WebObservationInvocationResult(
                WebObservationResultStatus.SUCCEEDED,
                model,
                canonical,
                actions,
                usage,
            )
        except WebObservationViolation:
            raise
        except APITimeoutError:
            return _unknown("WEB-PROVIDER-TIMEOUT")
        except APIConnectionError:
            return _unknown("WEB-PROVIDER-CONNECTION")
        except APIStatusError as error:
            code = (
                "WEB-PROVIDER-RATE-LIMIT"
                if error.status_code == 429
                else "WEB-PROVIDER-STATUS"
            )
            return WebObservationInvocationResult(
                WebObservationResultStatus.FAILED,
                None,
                None,
                (),
                None,
                code,
            )
        finally:
            await client.close()
            _wipe(secret)

    def _copy_secret(self) -> bytearray:
        try:
            with self._credential_port.resolve(self._locator, _PURPOSE) as handle:
                return handle.consume(lambda value: bytearray(value))
        except Exception:
            raise WebObservationViolation("WEB-CREDENTIAL") from None


def _unknown(code: str) -> WebObservationInvocationResult:
    return WebObservationInvocationResult(
        WebObservationResultStatus.OUTCOME_UNKNOWN,
        None,
        None,
        (),
        None,
        code,
    )


def _strict_json(raw: bytes, *, maximum: int) -> object:
    if not raw or len(raw) > maximum or raw.startswith(b"\xef\xbb\xbf"):
        raise WebObservationViolation("WEB-CODEC-SIZE")
    try:
        return json.loads(
            raw.decode("utf-8", errors="strict"), object_pairs_hook=_pairs
        )
    except WebObservationViolation:
        raise
    except UnicodeDecodeError, json.JSONDecodeError:
        raise WebObservationViolation("WEB-CODEC-JSON") from None


def _pairs(values: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in values:
        if key in result:
            raise WebObservationViolation("WEB-CODEC-DUPLICATE-KEY")
        result[key] = value
    return result


def _normalize_action(
    action_type: str, action: Mapping[str, object]
) -> dict[str, object]:
    result: dict[str, object] = {"type": action_type}
    if action_type == "search":
        query_value = action.get("query")
        queries_value = action.get("queries")
        if query_value is not None:
            result["query"] = _text(query_value, "WEB-TOOL-ACTION", maximum=16 * 1024)
        if queries_value is not None:
            if not isinstance(queries_value, list):
                raise WebObservationViolation("WEB-TOOL-ACTION")
            queries = cast(list[object], queries_value)
            if not 1 <= len(queries) <= 8:
                raise WebObservationViolation("WEB-TOOL-ACTION")
            result["queries"] = [
                _text(value, "WEB-TOOL-ACTION", maximum=16 * 1024) for value in queries
            ]
        if "query" not in result and "queries" not in result:
            raise WebObservationViolation("WEB-TOOL-ACTION")
        sources_value = action.get("sources")
        if sources_value is not None:
            if not isinstance(sources_value, list):
                raise WebObservationViolation("WEB-TOOL-ACTION")
            source_values = cast(list[object], sources_value)
            if len(source_values) > MAX_CITATIONS:
                raise WebObservationViolation("WEB-TOOL-ACTION")
            sources: list[dict[str, object]] = []
            for source_value in source_values:
                if not isinstance(source_value, dict):
                    raise WebObservationViolation("WEB-TOOL-ACTION")
                source = cast(dict[str, object], source_value)
                if (
                    frozenset(source) != frozenset({"type", "url"})
                    or source.get("type") != "url"
                ):
                    raise WebObservationViolation("WEB-TOOL-ACTION")
                sources.append({"type": "url", "url": _url(source.get("url"))})
            result["sources"] = sources
    else:
        result["url"] = _url(action.get("url"))
        if action_type == "find_in_page":
            result["pattern"] = _text(
                action.get("pattern"), "WEB-TOOL-ACTION", maximum=4096
            )
    return result


def _url(value: object) -> str:
    url = _text(value, "WEB-CITATION", maximum=4096)
    parsed = urlsplit(url)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username
        or parsed.password
    ):
        raise WebObservationViolation("WEB-CITATION")
    return url


def _text(value: object, code: str, *, maximum: int) -> str:
    if type(value) is not str or not value or len(value) > maximum or "\x00" in value:
        raise WebObservationViolation(code)
    return value


def _positive_int(value: object, code: str) -> int:
    if type(value) is not int or value <= 0:
        raise WebObservationViolation(code)
    return value


def _reject_prohibited(value: object) -> None:
    if isinstance(value, dict):
        for key, child in cast(dict[object, object], value).items():
            if key in _PROHIBITED_KEYS and child not in (None, "", [], {}):
                raise WebObservationViolation("WEB-PROVIDER-PROHIBITED")
            _reject_prohibited(child)
    elif isinstance(value, list):
        for child in cast(list[object], value):
            _reject_prohibited(child)


def _wipe(value: bytearray) -> None:
    value[:] = b"\x00" * len(value)


__all__ = ()
