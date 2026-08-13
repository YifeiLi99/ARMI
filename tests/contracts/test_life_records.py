from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid7

import pytest
from armi_kernel.application import (
    LifeRecordActor,
    LifeRecordItem,
    LifeRecordKind,
    LifeRecordPage,
    LifeRecordQuery,
    LifeRecordQueryViolation,
    LifeRecordRetrievalKind,
)
from armi_kernel.contracts import Instant, OpaqueCursor
from armi_memory.api import (
    CreatorMemoryItem,
    CreatorMemoryPage,
    MemoryAccessibility,
    MemoryRevisionKind,
)
from armi_runtime.adapters.persistence.life_records import LifeRecordCursorCodec


def _now() -> Instant:
    return Instant(datetime(2026, 8, 4, 12, 0, tzinfo=UTC))


def test_subject_exact_query_and_creator_view_are_distinct() -> None:
    subject = LifeRecordQuery(
        actor=LifeRecordActor.SUBJECT,
        retrieval_kind=LifeRecordRetrievalKind.EXACT_QUERY,
        limit=20,
        record_kind=LifeRecordKind("memory"),
        query_text="旧理解",
    )
    creator = LifeRecordQuery(
        actor=LifeRecordActor.CREATOR,
        retrieval_kind=LifeRecordRetrievalKind.CREATOR_VIEW,
        limit=20,
    )

    assert subject.retrieval_kind is LifeRecordRetrievalKind.EXACT_QUERY
    assert creator.retrieval_kind is LifeRecordRetrievalKind.CREATOR_VIEW
    with pytest.raises(LifeRecordQueryViolation, match="CON-LIFE-QUERY-REQUEST"):
        LifeRecordQuery(
            actor=LifeRecordActor.SUBJECT,
            retrieval_kind=LifeRecordRetrievalKind.CREATOR_VIEW,
            limit=20,
        )
    with pytest.raises(LifeRecordQueryViolation, match="CON-LIFE-QUERY-REQUEST"):
        LifeRecordQuery(
            actor=LifeRecordActor.CREATOR,
            retrieval_kind=LifeRecordRetrievalKind.CREATOR_VIEW,
            limit=True,
        )


def test_exact_query_can_return_a_forgotten_memory_without_changing_its_head() -> None:
    memory_id = uuid7()
    record = LifeRecordItem(
        record_ref=memory_id,
        record_kind=LifeRecordKind("memory"),
        summary="记录仍存在、但当前没有自然想起",
        source_kind="reported",
        occurred_at=_now(),
        naturally_recallable=False,
        retrieval_kind=LifeRecordRetrievalKind.EXACT_QUERY,
    )
    page = LifeRecordPage((record,))
    memory = CreatorMemoryItem(
        memory_id=memory_id,
        summary=record.summary,
        uncertainty=None,
        source_kind="reported",
        source_fact_class="external_claim",
        accessibility=MemoryAccessibility.FORGOTTEN,
        revision_kind=MemoryRevisionKind.FORGOTTEN,
        revision_no=3,
        head_version=3,
        created_at=_now(),
        updated_at=_now(),
    )

    assert page.items[0].naturally_recallable is False
    assert CreatorMemoryPage((memory,)).items[0].head_version == 3
    with pytest.raises(LifeRecordQueryViolation, match="CON-LIFE-QUERY-ITEM"):
        LifeRecordItem(
            record_ref=memory_id,
            record_kind=LifeRecordKind("activity"),
            summary="活动",
            source_kind="activity_current",
            occurred_at=_now(),
            naturally_recallable=False,
            retrieval_kind=LifeRecordRetrievalKind.EXACT_QUERY,
        )


def test_exact_query_accepts_current_relationship_understanding() -> None:
    relationship = LifeRecordItem(
        record_ref=uuid7(),
        record_kind=LifeRecordKind("relationship"),
        summary="我理解我们正在从真实交往中了解彼此。",
        source_kind="relationship_current",
        occurred_at=_now(),
        naturally_recallable=None,
        retrieval_kind=LifeRecordRetrievalKind.EXACT_QUERY,
    )

    assert LifeRecordPage((relationship,)).items[0].record_kind == (
        LifeRecordKind("relationship")
    )


def test_creator_view_accepts_only_projected_material_summary_shape() -> None:
    material = LifeRecordItem(
        record_ref=uuid7(),
        record_kind=LifeRecordKind("material"),
        summary="一份由 ARMI 决定对 Creator 可见的日记",
        source_kind="life_material_current",
        occurred_at=_now(),
        naturally_recallable=None,
        retrieval_kind=LifeRecordRetrievalKind.CREATOR_VIEW,
    )

    page = LifeRecordPage((material,))
    assert page.items[0].record_kind == LifeRecordKind("material")
    assert page.projection_version == "life-record-query.v2"


def test_cursor_is_signed_and_bound_to_query_scope() -> None:
    environment_id = uuid7()
    creator_id = uuid7()
    codec = LifeRecordCursorCodec(
        key=b"k" * 32,
        environment_id=environment_id,
        creator_party_id=creator_id,
    )
    scope = {
        "projection_version": "creator-memory.v1",
        "resource": "memory_current",
        "query_text": "旧理解",
        "limit": 20,
    }
    cursor = codec.encode(
        scope=scope,
        boundary={
            "before_at": _now().to_wire(),
            "before_id": str(uuid7()),
        },
    )

    decoded = codec.decode(
        cursor,
        scope=scope,
        boundary_keys=frozenset({"before_at", "before_id"}),
    )
    assert decoded["before_at"] == _now().to_wire()
    with pytest.raises(LifeRecordQueryViolation, match="LIFE-QUERY-CURSOR-STALE"):
        codec.decode(
            cursor,
            scope={**scope, "query_text": "另一个查询"},
            boundary_keys=frozenset({"before_at", "before_id"}),
        )
    damaged = OpaqueCursor(
        cursor.value[:-1] + ("A" if cursor.value[-1] != "A" else "B")
    )
    with pytest.raises(LifeRecordQueryViolation, match="LIFE-QUERY-CURSOR-INVALID"):
        codec.decode(
            damaged,
            scope=scope,
            boundary_keys=frozenset({"before_at", "before_id"}),
        )
