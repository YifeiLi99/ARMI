from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from typing import cast
from uuid import uuid7

import rfc8785
from armi_kernel.application import ContextItemDisposition
from armi_kernel.contracts import Digest, TraceId
from armi_runtime.adapters.persistence.context import ContextEpisodeSnapshot
from armi_runtime.composition.context_compiler import DeterministicContextCompiler
from armi_runtime.composition.context_pipeline import _context_request


def _snapshot(
    memory_payloads: tuple[tuple[object, ...], ...],
    *,
    has_memory_records: bool = True,
    relationship_payloads: tuple[tuple[object, ...], ...] = (),
) -> ContextEpisodeSnapshot:
    source_ref = uuid7()
    return cast(
        ContextEpisodeSnapshot,
        SimpleNamespace(
            subject_id=uuid7(),
            subject_version=3,
            state_epoch=1,
            bundle_activation_id=uuid7(),
            opportunity_id=uuid7(),
            purpose="consider_creator_input",
            component_payloads=(),
            scene_id=None,
            scene_bytes=None,
            memory_payloads=memory_payloads,
            has_memory_records=has_memory_records,
            relationship_payloads=relationship_payloads,
            activity_summary_bytes=b'{"activities":[]}',
            opportunity_source_ref=source_ref,
            opportunity_source_version=1,
            opportunity_source_digest=Digest.from_bytes(b"opportunity"),
            opportunity_source_kind="external_evidence",
            opportunity_available_after=datetime(2026, 1, 1, tzinfo=UTC),
            opportunity_expires_at=None,
            evidence=None,
            fixed_prompt=SimpleNamespace(source_id=uuid7(), source_version=1),
            policy_digest=Digest.from_bytes(b"policy"),
            mechanism_config_digest=Digest.from_bytes(b"context-config"),
            trace_id=TraceId("1" * 32),
        ),
    )


def _memory(accessibility: str) -> tuple[object, ...]:
    payload = rfc8785.dumps(
        {
            "source_kind": "reported",
            "fact_class": "external_claim",
            "summary": f"{accessibility} memory",
            "uncertainty": None,
            "accessibility": accessibility,
        }
    )
    return uuid7(), 2, payload, Digest.from_bytes(payload), accessibility


def test_context_includes_only_naturally_accessible_memory_heads() -> None:
    request = _context_request(
        _snapshot((_memory("available"), _memory("faded"), _memory("forgotten"))),
        None,
        b"fixed prompt",
        web_search_active=False,
    )
    memory_items = tuple(
        item for item in request.items if item.item_kind == "current_memory"
    )
    assert tuple(item.source.version for item in memory_items) == (2, 2)
    assert tuple(item.relevance for item in memory_items) == (85, 70)
    assert all("forgotten memory" not in (item.content or "") for item in memory_items)

    compiled = DeterministicContextCompiler().compile(request)
    assert all(
        item.disposition is ContextItemDisposition.INCLUDED
        for item in compiled.items
        if item.candidate.item_kind == "current_memory"
    )


def test_context_distinguishes_no_natural_recall_from_no_database_record() -> None:
    request = _context_request(
        _snapshot((_memory("forgotten"),)),
        None,
        b"fixed prompt",
        web_search_active=False,
    )
    memory_items = tuple(item for item in request.items if item.item_kind == "memory")
    assert len(memory_items) == 1
    assert memory_items[0].content is None
    assert memory_items[0].unavailable_reason == "CTX-MEMORY-NOT-RECALLABLE"

    none = _context_request(
        _snapshot((), has_memory_records=False),
        None,
        b"fixed prompt",
        web_search_active=False,
    )
    empty = next(item for item in none.items if item.item_kind == "memory")
    assert empty.unavailable_reason == "CTX-MEMORY-NONE"


def test_context_includes_current_relationship_or_explicitly_reports_none() -> None:
    relationship_id = uuid7()
    payload = rfc8785.dumps(
        {
            "scope": "creator_social",
            "facts": [
                {"kind": "shared_experience", "summary": "我们进行过一次真实交流。"}
            ],
            "interpretation": "我正在从实际交往中了解创造者。",
            "boundaries": [],
            "status": "active",
        }
    )
    snapshot = _snapshot(
        (),
        relationship_payloads=(
            (relationship_id, 2, payload, Digest.from_bytes(payload)),
        ),
    )
    request = _context_request(
        snapshot,
        None,
        b"fixed prompt",
        web_search_active=False,
    )
    item = next(
        item for item in request.items if item.item_kind == "current_relationship"
    )
    assert item.source.reference == relationship_id
    assert item.source.version == 2
    assert item.trust_class.value == "subjective_state"

    empty_request = _context_request(
        _snapshot(()),
        None,
        b"fixed prompt",
        web_search_active=False,
    )
    empty = next(
        item for item in empty_request.items if item.item_kind == "relationship"
    )
    assert empty.unavailable_reason == "CTX-RELATIONSHIP-NONE"
