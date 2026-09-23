"""Bounded, non-executable technical evidence; no locals or request payloads."""

from __future__ import annotations

import json
import re
import traceback
from collections.abc import Callable, Mapping
from enum import Enum
from pathlib import Path
from typing import cast
from urllib.parse import urlsplit, urlunsplit
from uuid import UUID

_PRIVATE = re.compile(
    r"password|passwd|secret|(?:^|_)token$|authorization|cookie|api.?key|credential|"
    r"private.?key|request_body|prompt|messages|input_text|audio_data|image_data|^sql$|parameters",
    re.I,
)
_ASSIGNMENT = re.compile(
    r"(?i)((?:authorization|api[_-]?key|password|secret|access[_-]?token|cookie)"
    r"[\s\"']*[:=][\s\"']*)(?:Bearer\s+)?[^\s,;\"'}]+"
)
_BEARER = re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]+")
_KEY = re.compile(r"\b(?:sk|ts|jev)-[A-Za-z0-9_-]{12,}\b")
_URL = re.compile(r"https?://[^\s\"'<>]+")


def safe_text(value: str, limit: int = 16384) -> str:
    value = _ASSIGNMENT.sub(r"\1[REDACTED]", value)
    value = _BEARER.sub("Bearer [REDACTED]", value)
    value = _KEY.sub("[REDACTED]", value)

    def clean_url(match: re.Match[str]) -> str:
        try:
            url = urlsplit(match.group())
            return urlunsplit((url.scheme, url.hostname or "", url.path, "", ""))
        except ValueError:
            return "[INVALID-URL]"

    value = _URL.sub(clean_url, value)
    encoded = value.encode("utf-8", errors="replace")
    if len(encoded) > limit:
        return encoded[:limit].decode("utf-8", errors="ignore") + " [TRUNCATED]"
    return value


def redact(value: object, *, depth: int = 0) -> object:
    if depth > 8:
        return "[DEPTH-LIMIT]"
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, Enum):
        return redact(value.value, depth=depth + 1)
    if isinstance(value, Mapping):
        return {
            str(key): "[REDACTED]"
            if _PRIVATE.search(str(key))
            else redact(item, depth=depth + 1)
            for key, item in cast(Mapping[object, object], value).items()
        }
    if isinstance(value, (list, tuple)):
        return [
            redact(item, depth=depth + 1)
            for item in cast(list[object] | tuple[object, ...], value)[:128]
        ]
    if isinstance(value, str):
        return safe_text(value)
    if value is None or isinstance(value, (bool, int, float)):
        return value
    # Never call repr() on arbitrary objects: SDK objects can contain credentials.
    return f"[{type(value).__name__}]"


def exception_evidence(error: BaseException | None) -> dict[str, object]:
    chain: list[dict[str, object]] = []
    seen: set[int] = set()
    while error is not None and id(error) not in seen and len(chain) < 8:
        seen.add(id(error))
        module = type(error).__module__
        if module.startswith("pydantic") and callable(getattr(error, "errors", None)):
            message = json.dumps(
                redact(
                    cast(Callable[..., object], error.errors)(
                        include_input=False, include_url=False, include_context=False
                    )
                ),
                ensure_ascii=False,
            )
        elif module.startswith("psycopg"):
            # SQL errors may echo whole parameter values; use code and constraint evidence.
            message = (
                "Database operation failed; inspect sqlstate and constraint metadata."
            )
        elif module == "subprocess":
            message = "Subprocess operation failed; command arguments and process payloads omitted."
        else:
            message = str(error)
        item: dict[str, object] = {
            "type": type(error).__name__,
            "message": safe_text(message, 2048),
            "frames": [
                {
                    "file": Path(frame.filename).name,
                    "line": frame.lineno,
                    "function": frame.name,
                }
                for frame in traceback.extract_tb(error.__traceback__)[-64:]
            ],
        }
        for name in (
            "errno",
            "winerror",
            "sqlstate",
            "status_code",
            "code",
            "returncode",
            "timeout",
        ):
            value = getattr(error, name, None)
            if isinstance(value, (str, int)):
                item[name] = safe_text(value) if isinstance(value, str) else value
        diag = getattr(error, "diag", None)
        if diag is not None:
            item["database"] = {
                name: safe_text(value)
                for name in (
                    "constraint_name",
                    "table_name",
                    "column_name",
                    "severity_nonlocalized",
                )
                if isinstance(value := getattr(diag, name, None), str)
            }
        try:
            request = getattr(error, "request", None)
        except RuntimeError:
            request = None
        if request is not None:
            item["method"] = safe_text(str(getattr(request, "method", "")), 16)
            item["target"] = safe_text(str(getattr(request, "url", "")), 1024)
        response = getattr(error, "response", None)
        if response is not None:
            status = getattr(response, "status_code", None)
            if isinstance(status, int):
                item["http_status"] = status
            headers = getattr(response, "headers", {})
            item["provider_request_id"] = headers.get("x-request-id") or headers.get(
                "request-id"
            )
            try:
                body = response.text
                if isinstance(body, str):
                    body_size = len(body.encode("utf-8"))
                    item["error_body_bytes"] = body_size
                    try:
                        cleaned = json.dumps(
                            redact(response.json()), ensure_ascii=False
                        )
                    except ValueError, TypeError:
                        cleaned = safe_text(body, limit=body_size)
                    item["error_body_truncated"] = len(cleaned.encode("utf-8")) > 16384
                    item["error_body"] = safe_text(cleaned, 16360)
            except RuntimeError, AttributeError:
                item["error_body_unavailable"] = True
        chain.append(item)
        error = error.__cause__ or error.__context__
    return {"chain": chain, "chain_truncated": error is not None}
