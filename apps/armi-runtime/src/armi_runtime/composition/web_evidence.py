"""Deterministic S034 normalization of provider synthesis into web evidence."""

from __future__ import annotations

import ipaddress
import json
from dataclasses import dataclass
from typing import Any, cast
from urllib.parse import SplitResult, urlsplit, urlunsplit

import rfc8785
from armi_kernel.application import WebResearchViolation
from armi_kernel.contracts import Digest

WEB_EVIDENCE_VERSION = "armi.web-evidence.v1"
WEB_SOURCE_REFERENCE_VERSION = "armi.web-source-reference.v1"
_CUSTODY_RESULT_VERSION = "armi.web-search-result.v1"


@dataclass(frozen=True, slots=True)
class NormalizedWebSource:
    ordinal: int
    canonical_bytes: bytes
    canonical_url_digest: Digest


@dataclass(frozen=True, slots=True)
class NormalizedWebEvidence:
    canonical_bytes: bytes
    provider_request_digest: Digest
    sources: tuple[NormalizedWebSource, ...]


def normalize_public_url(value: str) -> str:
    """Normalize a citation identity without claiming control of provider networking."""

    if type(value) is not str or not value or len(value) > 8192:
        raise WebResearchViolation("WEB-EVIDENCE-URL")
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError:
        raise WebResearchViolation("WEB-EVIDENCE-URL") from None
    if (
        parsed.scheme.casefold() not in {"http", "https"}
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
    ):
        raise WebResearchViolation("WEB-EVIDENCE-URL")
    host_text = parsed.hostname.rstrip(".").casefold()
    if not host_text or host_text == "localhost" or host_text.endswith(".localhost"):
        raise WebResearchViolation("WEB-EVIDENCE-URL")
    try:
        ipaddress.ip_address(host_text.strip("[]"))
    except ValueError:
        pass
    else:
        raise WebResearchViolation("WEB-EVIDENCE-URL")
    try:
        host = host_text.encode("idna").decode("ascii")
    except UnicodeError:
        raise WebResearchViolation("WEB-EVIDENCE-URL") from None
    if host.endswith(".local") or host.endswith(".internal"):
        raise WebResearchViolation("WEB-EVIDENCE-URL")
    scheme = parsed.scheme.casefold()
    default_port = (scheme == "http" and port == 80) or (
        scheme == "https" and port == 443
    )
    netloc = host if port is None or default_port else f"{host}:{port}"
    normalized = SplitResult(
        scheme,
        netloc,
        parsed.path or "/",
        parsed.query,
        "",
    )
    return urlunsplit(normalized)


def normalize_web_evidence(raw: bytes) -> NormalizedWebEvidence:
    """Convert one canonical S033 result into provider-synthesis evidence bytes."""

    if type(raw) is not bytes or not raw or len(raw) > 1024 * 1024:
        raise WebResearchViolation("WEB-EVIDENCE-RESULT")
    try:
        decoded = json.loads(raw, object_pairs_hook=_unique_object)
    except UnicodeDecodeError, json.JSONDecodeError, ValueError:
        raise WebResearchViolation("WEB-EVIDENCE-RESULT") from None
    if not isinstance(decoded, dict):
        raise WebResearchViolation("WEB-EVIDENCE-RESULT")
    value = cast(dict[str, Any], decoded)
    if (
        set(value)
        != {
            "schema_version",
            "provider",
            "model",
            "store",
            "provider_request_digest",
            "tool_calls",
            "messages",
            "usage",
        }
        or value.get("schema_version") != _CUSTODY_RESULT_VERSION
        or value.get("provider") != "volcengine_ark"
        or value.get("store") is not False
        or rfc8785.dumps(cast(Any, value)) + b"\n" != raw
    ):
        raise WebResearchViolation("WEB-EVIDENCE-RESULT")
    provider_request_digest = Digest(_text(value["provider_request_digest"], 71))
    model = _text(value["model"], 128)
    if not model.startswith("doubao-seed-evolving"):
        raise WebResearchViolation("WEB-EVIDENCE-RESULT")
    messages_value = value["messages"]
    if type(messages_value) is not list:
        raise WebResearchViolation("WEB-EVIDENCE-RESULT")
    messages = cast(list[object], messages_value)
    if len(messages) != 1:
        raise WebResearchViolation("WEB-EVIDENCE-RESULT")
    message_value = messages[0]
    if type(message_value) is not dict:
        raise WebResearchViolation("WEB-EVIDENCE-RESULT")
    message = cast(dict[str, object], message_value)
    if set(message) != {"parts"}:
        raise WebResearchViolation("WEB-EVIDENCE-RESULT")
    parts_value = message["parts"]
    if type(parts_value) is not list:
        raise WebResearchViolation("WEB-EVIDENCE-RESULT")
    parts = cast(list[object], parts_value)
    if not parts:
        raise WebResearchViolation("WEB-EVIDENCE-RESULT")

    source_values: list[dict[str, object]] = []
    source_by_url: dict[str, int] = {}
    normalized_parts: list[dict[str, object]] = []
    for part in parts:
        if type(part) is not dict:
            raise WebResearchViolation("WEB-EVIDENCE-RESULT")
        part_value = cast(dict[str, object], part)
        if set(part_value) != {"text", "citations"}:
            raise WebResearchViolation("WEB-EVIDENCE-RESULT")
        text = _text(part_value["text"], 1024 * 1024)
        citations_value = part_value["citations"]
        if type(citations_value) is not list:
            raise WebResearchViolation("WEB-EVIDENCE-RESULT")
        citations = cast(list[object], citations_value)
        refs: list[int] = []
        for citation in citations:
            if type(citation) is not dict:
                raise WebResearchViolation("WEB-EVIDENCE-SOURCE")
            citation_value = cast(dict[str, object], citation)
            if set(citation_value) != {"url", "title"}:
                raise WebResearchViolation("WEB-EVIDENCE-SOURCE")
            url = normalize_public_url(_text(citation_value["url"], 8192))
            title = _text(citation_value["title"], 1024)
            ordinal = source_by_url.get(url)
            if ordinal is None:
                ordinal = len(source_values) + 1
                if ordinal > 128:
                    raise WebResearchViolation("WEB-EVIDENCE-SOURCE")
                source_by_url[url] = ordinal
                source_values.append(
                    {
                        "ordinal": ordinal,
                        "canonical_url": url,
                        "title": title,
                        "acquisition_kind": "provider_synthesis_citation",
                    }
                )
            refs.append(ordinal)
        normalized_parts.append({"text": text, "source_ordinals": refs})
    if not source_values:
        raise WebResearchViolation("WEB-EVIDENCE-SOURCE")

    sources: list[NormalizedWebSource] = []
    evidence_source_refs: list[dict[str, object]] = []
    for source in source_values:
        url = cast(str, source["canonical_url"])
        source_document = {
            "schema_version": WEB_SOURCE_REFERENCE_VERSION,
            **source,
            "provider_request_digest": provider_request_digest.value,
        }
        canonical = rfc8785.dumps(cast(Any, source_document)) + b"\n"
        normalized = NormalizedWebSource(
            cast(int, source["ordinal"]),
            canonical,
            Digest.from_bytes(url.encode("utf-8")),
        )
        sources.append(normalized)
        evidence_source_refs.append(
            {
                "ordinal": normalized.ordinal,
            }
        )
    evidence_document = {
        "schema_version": WEB_EVIDENCE_VERSION,
        "evidence_kind": "provider_synthesis",
        "trust_class": "external_claim",
        "provider": "volcengine_ark",
        "model": model,
        "provider_request_digest": provider_request_digest.value,
        "parts": normalized_parts,
        "sources": evidence_source_refs,
    }
    canonical_evidence = rfc8785.dumps(cast(Any, evidence_document)) + b"\n"
    if len(canonical_evidence) > 1024 * 1024:
        raise WebResearchViolation("WEB-EVIDENCE-SIZE")
    return NormalizedWebEvidence(
        canonical_evidence,
        provider_request_digest,
        tuple(sources),
    )


def _text(value: object, maximum: int) -> str:
    if type(value) is not str or not value or len(value.encode("utf-8")) > maximum:
        raise WebResearchViolation("WEB-EVIDENCE-RESULT")
    if "\x00" in value:
        raise WebResearchViolation("WEB-EVIDENCE-RESULT")
    return value


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate key")
        result[key] = value
    return result


__all__ = (
    "WEB_EVIDENCE_VERSION",
    "WEB_SOURCE_REFERENCE_VERSION",
    "NormalizedWebEvidence",
    "NormalizedWebSource",
    "normalize_public_url",
    "normalize_web_evidence",
)
