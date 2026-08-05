from __future__ import annotations

import json
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import cast
from uuid import uuid7

import rfc8785
from armi_kernel.application import ContextItemDisposition
from armi_kernel.contracts import Digest, TraceId
from armi_runtime.adapters.persistence.capability_context import (
    _capability_state_payload,
)
from armi_runtime.adapters.persistence.context import (
    ContextEpisodeSnapshot,
    ContextMaterialSource,
)
from armi_runtime.composition.context_compiler import DeterministicContextCompiler
from armi_runtime.composition.context_pipeline import _context_request


def _snapshot(
    memory_payloads: tuple[tuple[object, ...], ...],
    *,
    has_memory_records: bool = True,
    relationship_payloads: tuple[tuple[object, ...], ...] = (),
    relationship_commitment_payloads: tuple[tuple[object, ...], ...] = (),
    relationship_issue_payloads: tuple[tuple[object, ...], ...] = (),
    capability_state_payloads: tuple[tuple[object, ...], ...] = (),
    scene_id: object | None = None,
    scene_bytes: bytes | None = None,
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
            scene_id=scene_id,
            scene_bytes=scene_bytes,
            memory_payloads=memory_payloads,
            has_memory_records=has_memory_records,
            relationship_payloads=relationship_payloads,
            relationship_commitment_payloads=relationship_commitment_payloads,
            relationship_issue_payloads=relationship_issue_payloads,
            activity_summary_bytes=b'{"activities":[]}',
            capability_state_payloads=capability_state_payloads,
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


def test_capability_state_separates_availability_authorization_and_desire() -> None:
    unavailable_id = uuid7()
    unavailable = _capability_state_payload(
        (
            unavailable_id,
            "codex.delegated-work",
            "execute",
            "unavailable",
            2,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
        )
    )
    request_id = uuid7()
    denied = _capability_state_payload(
        (
            uuid7(),
            "codex.delegated-work",
            "execute",
            "available",
            2,
            request_id,
            2,
            "denied",
            "creator_denied",
            None,
            None,
            "delegate_codex_work",
            "isolated_ephemeral",
            "explicit_only",
            False,
            3600,
            1,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            datetime(2026, 1, 2, tzinfo=UTC),
        )
    )
    request = _context_request(
        _snapshot((), capability_state_payloads=(unavailable, denied)),
        None,
        b"fixed prompt",
        web_search_active=False,
    )
    states = tuple(
        item for item in request.items if item.item_kind.startswith("capability_state_")
    )
    assert {item.item_kind for item in states} == {
        "capability_state_unauthorized",
        "capability_state_denied",
    }
    documents = [json.loads(item.content or "{}") for item in states]
    unavailable_document = next(
        item for item in documents if item["capability_ref"] == str(unavailable_id)
    )
    denied_document = next(
        item for item in documents if item["authorization_status"] == "denied"
    )
    assert unavailable_document["availability_status"] == "unavailable"
    assert unavailable_document["authorization_status"] == "unauthorized"
    assert denied_document["availability_status"] == "available"
    assert denied_document["current_request"]["request_ref"] == str(request_id)
    assert denied_document["current_request"]["resolution_reason_class"] == (
        "creator_denied"
    )
    assert "desire" not in denied_document


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


def test_context_includes_current_life_material_with_revision_identity() -> None:
    material_id = uuid7()
    semantic_digest = Digest.from_bytes(b"material-revision")
    source = cast(
        ContextMaterialSource,
        SimpleNamespace(
            material_id=material_id,
            head_version=4,
            semantic_digest=semantic_digest,
        ),
    )
    payload = rfc8785.dumps(
        {
            "material_kind": "diary",
            "title": "今天",
            "body": "这是当前完整正文。",
            "metadata": {"mood": "calm"},
            "material_status": "active",
            "privacy_status": "private",
        }
    )
    request = _context_request(
        _snapshot(()),
        None,
        b"fixed prompt",
        ((source, payload),),
        web_search_active=False,
    )
    item = next(item for item in request.items if item.item_kind == "current_material")
    assert item.section.value == "material"
    assert item.source.reference == material_id
    assert item.source.version == 4
    assert item.source.digest == semantic_digest
    assert item.trust_class.value == "subjective_state"
    assert "当前完整正文" in cast(str, item.content)
    assert '"privacy_status":"private"' in cast(str, item.content)


def test_commitment_context_crosses_scenes_without_copying_recent_scene_text() -> None:
    commitment_id = uuid7()
    commitment_payload = rfc8785.dumps(
        {
            "party_role": "subject",
            "scope": "主动联系",
            "content": "联系前先询问是否方便。",
            "status": "active",
            "last_event_kind": "established",
            "last_event_summary": "我明确作出了联系前先询问的承诺。",
        }
    )
    commitment = (
        commitment_id,
        3,
        commitment_payload,
        Digest.from_bytes(commitment_payload),
        "active",
    )
    first_scene = rfc8785.dumps({"scene_key": "private-alpha"})
    second_scene = rfc8785.dumps({"scene_key": "private-beta"})
    requests = tuple(
        _context_request(
            _snapshot(
                (),
                relationship_commitment_payloads=(commitment,),
                scene_id=uuid7(),
                scene_bytes=scene,
            ),
            None,
            b"fixed prompt",
            web_search_active=False,
        )
        for scene in (first_scene, second_scene)
    )
    commitment_contents = tuple(
        next(
            item.content
            for item in request.items
            if item.item_kind == "current_relationship_commitment"
        )
        for request in requests
    )
    scene_contents = tuple(
        next(
            item.content for item in request.items if item.item_kind == "current_scene"
        )
        for request in requests
    )
    assert commitment_contents[0] == commitment_contents[1]
    assert "private-alpha" not in cast(str, commitment_contents[0])
    assert "private-beta" not in cast(str, commitment_contents[0])
    assert scene_contents[0] != scene_contents[1]


def test_context_hides_forgotten_commitment_but_keeps_open_issue() -> None:
    forgotten_payload = rfc8785.dumps(
        {
            "party_role": "subject",
            "scope": "提醒",
            "content": "提醒一次。",
            "status": "forgotten",
            "last_event_kind": "forgotten",
            "last_event_summary": "这项承诺已不再能被自然想起。",
        }
    )
    issue_payload = rfc8785.dumps(
        {
            "kind": "commitment_violation",
            "summary": "这项承诺曾被违背。问题仍未解决。",
            "status": "open",
        }
    )
    request = _context_request(
        _snapshot(
            (),
            relationship_commitment_payloads=(
                (
                    uuid7(),
                    4,
                    forgotten_payload,
                    Digest.from_bytes(forgotten_payload),
                    "forgotten",
                ),
            ),
            relationship_issue_payloads=(
                (uuid7(), 4, issue_payload, Digest.from_bytes(issue_payload)),
            ),
        ),
        None,
        b"fixed prompt",
        web_search_active=False,
    )
    unavailable = next(
        item for item in request.items if item.item_kind == "relationship_commitment"
    )
    assert unavailable.unavailable_reason == "CTX-COMMITMENT-NOT-RECALLABLE"
    assert not any(
        item.item_kind == "current_relationship_commitment" for item in request.items
    )
    issue = next(
        item for item in request.items if item.item_kind == "current_relationship_issue"
    )
    assert "问题仍未解决" in cast(str, issue.content)
