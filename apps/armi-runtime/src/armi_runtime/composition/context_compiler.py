"""Deterministic, repository-free Context compiler."""

from __future__ import annotations

import json
from typing import Any, cast

import rfc8785
from armi_kernel.application import (
    CompiledContext,
    ContextCompiler,
    ContextItemCandidate,
    ContextItemDisposition,
    ContextItemResult,
    ContextRequest,
    ContextResult,
    ContextSection,
    ContextViolation,
)

CONTEXT_MANIFEST_VERSION = "armi.context-manifest.v1"
CONTEXT_POLICY_VERSION = "armi.context-policy.v3"
CONTEXT_MECHANISM = "armi.context-compiler.deterministic-v1"

_SECTION_ORDER = tuple(ContextSection)
_SECTION_RANK = {section: index for index, section in enumerate(_SECTION_ORDER)}


class DeterministicContextCompiler(ContextCompiler):
    """Compile only immutable inputs supplied by the caller."""

    def compile(self, request: ContextRequest) -> ContextResult:
        if request.mechanism_identity != CONTEXT_MECHANISM:
            raise ContextViolation("CTX-MECHANISM")

        ordered = sorted(request.items, key=_sort_key)
        required_items = tuple(
            candidate
            for candidate in ordered
            if candidate.content is not None and candidate.required
        )
        if len(required_items) > request.max_items:
            raise ContextViolation("CTX-BUDGET-REQUIRED")
        for candidate in required_items:
            assert candidate.content is not None
            if len(candidate.content.encode("utf-8")) > request.max_item_bytes:
                raise ContextViolation("CTX-BUDGET-REQUIRED")

        results: list[ContextItemResult] = []
        optional_slots = request.max_items - len(required_items)
        included_optional = 0
        for candidate in ordered:
            ordinal = len(results) + 1
            if candidate.content is None:
                results.append(
                    ContextItemResult(
                        candidate,
                        ordinal,
                        ContextItemDisposition.UNAVAILABLE,
                        0,
                        candidate.unavailable_reason,
                    )
                )
                continue
            content_bytes = len(candidate.content.encode("utf-8"))
            if content_bytes > request.max_item_bytes:
                if candidate.required:
                    raise ContextViolation("CTX-BUDGET-REQUIRED")
                results.append(
                    ContextItemResult(
                        candidate,
                        ordinal,
                        ContextItemDisposition.EXCLUDED_BUDGET,
                        content_bytes,
                        "CTX-BUDGET-ITEM",
                    )
                )
                continue
            if not candidate.required and included_optional >= optional_slots:
                results.append(
                    ContextItemResult(
                        candidate,
                        ordinal,
                        ContextItemDisposition.EXCLUDED_BUDGET,
                        content_bytes,
                        "CTX-BUDGET-ITEM-COUNT",
                    )
                )
                continue
            if not candidate.required:
                included_optional += 1
            results.append(
                ContextItemResult(
                    candidate,
                    ordinal,
                    ContextItemDisposition.INCLUDED,
                    content_bytes,
                )
            )

        compiled_bytes = _compiled_bytes(request, results)
        while len(compiled_bytes) > request.max_compiled_bytes:
            removable = _budget_removals(results)
            if not removable:
                raise ContextViolation("CTX-BUDGET-REQUIRED")
            for index in removable:
                previous = results[index]
                results[index] = ContextItemResult(
                    previous.candidate,
                    previous.ordinal,
                    ContextItemDisposition.EXCLUDED_BUDGET,
                    previous.content_bytes,
                    "CTX-BUDGET-COMPILED",
                )
            compiled_bytes = _compiled_bytes(request, results)

        compiled = CompiledContext(compiled_bytes)
        manifest = {
            "schema_version": CONTEXT_MANIFEST_VERSION,
            "policy": {
                "schema_version": CONTEXT_POLICY_VERSION,
                "version": request.policy_version,
                "max_items": request.max_items,
                "max_item_bytes": request.max_item_bytes,
                "max_compiled_bytes": request.max_compiled_bytes,
            },
            "mechanism": {"identity": request.mechanism_identity},
            "snapshot": {
                "purpose": request.purpose.value,
                "subject_id": str(request.subject_id),
                "subject_version": request.base_subject_version,
                "state_epoch": request.base_state_epoch,
                "bundle_activation_id": str(request.bundle_activation_id),
            },
            "items": [_manifest_item(result) for result in results],
        }
        if request.scene_id is not None:
            cast(dict[str, object], manifest["snapshot"])["scene_id"] = str(
                request.scene_id
            )
        manifest_bytes = rfc8785.dumps(cast(Any, manifest)) + b"\n"
        return ContextResult(
            manifest_bytes,
            compiled,
            tuple(results),
        )


def _sort_key(candidate: ContextItemCandidate) -> tuple[object, ...]:
    source_time = (
        candidate.business_time.to_wire() if candidate.business_time is not None else ""
    )
    source_ref = str(candidate.source.reference) if candidate.source.reference else ""
    if candidate.item_kind == "current_memory":
        source_ref = ""
    return (
        _SECTION_RANK[candidate.section],
        -candidate.relevance,
        source_time,
        source_ref,
        candidate.item_kind,
    )


def _budget_removals(results: list[ContextItemResult]) -> tuple[int, ...]:
    included = [
        (index, result)
        for index, result in enumerate(results)
        if result.disposition is ContextItemDisposition.INCLUDED
        and not result.candidate.required
    ]
    if not included:
        return ()
    recent = [
        (index, result)
        for index, result in included
        if result.candidate.item_kind == "recent_scene_turn"
    ]
    if recent:
        recent.sort(
            key=lambda pair: (
                pair[1].candidate.business_time.to_wire()
                if pair[1].candidate.business_time is not None
                else "",
                pair[1].ordinal,
            )
        )
        first_index, first = recent[0]
        if _scene_speaker(first) in {"creator", "other_human"} and len(recent) > 1:
            second_index, second = recent[1]
            if _scene_speaker(second) == "armi":
                return (first_index, second_index)
        return (first_index,)
    memories = [
        (index, result)
        for index, result in included
        if result.candidate.item_kind == "current_memory"
    ]
    if memories:
        index, _ = min(
            memories,
            key=lambda pair: (pair[1].candidate.relevance, -pair[1].ordinal),
        )
        return (index,)
    index, _ = min(
        included,
        key=lambda pair: (pair[1].candidate.relevance, -pair[1].ordinal),
    )
    return (index,)


def _scene_speaker(result: ContextItemResult) -> object:
    content = result.candidate.content
    if content is None:
        return None
    try:
        value = json.loads(content)
    except json.JSONDecodeError:
        return None
    return value.get("speaker") if isinstance(value, dict) else None


def _source(candidate: ContextItemCandidate) -> dict[str, object]:
    source: dict[str, object] = {"kind": candidate.source.kind}
    if candidate.source.reference is not None:
        source.update(
            {
                "reference": str(candidate.source.reference),
                "version": candidate.source.version,
            }
        )
    return source


def _compiled_bytes(
    request: ContextRequest,
    results: list[ContextItemResult],
) -> bytes:
    sections: list[dict[str, object]] = []
    for section in _SECTION_ORDER:
        items = [
            {
                "item_kind": result.candidate.item_kind,
                "source": _source(result.candidate),
                "trust": result.candidate.trust_class.value,
                "privacy": result.candidate.privacy_scope,
                "content": result.candidate.content,
            }
            for result in results
            if result.candidate.section is section
            and result.disposition is ContextItemDisposition.INCLUDED
        ]
        sections.append({"section": section.value, "items": items})
    value = {
        "schema_version": "armi.compiled-context.v1",
        "purpose": request.purpose.value,
        "sections": sections,
    }
    return rfc8785.dumps(cast(Any, value)) + b"\n"


def _manifest_item(result: ContextItemResult) -> dict[str, object]:
    candidate = result.candidate
    value: dict[str, object] = {
        "ordinal": result.ordinal,
        "section": candidate.section.value,
        "item_kind": candidate.item_kind,
        "source": _source(candidate),
        "trust": candidate.trust_class.value,
        "privacy": candidate.privacy_scope,
        "required": candidate.required,
        "relevance": candidate.relevance,
        "disposition": result.disposition.value,
        "content_bytes": result.content_bytes,
    }
    if candidate.business_time is not None:
        value["source_time"] = candidate.business_time.to_wire()
    if result.reason_code is not None:
        value["reason_code"] = result.reason_code
    return value


__all__ = (
    "CONTEXT_MANIFEST_VERSION",
    "CONTEXT_MECHANISM",
    "CONTEXT_POLICY_VERSION",
    "DeterministicContextCompiler",
)
