"""P1-S004 subject exact-life query execution semantics."""

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
from armi_kernel.contracts import Digest, Instant, TraceId
from armi_runtime.adapters.persistence.exact_life_query import (
    ExactLifeQuerySnapshot,
)
from armi_runtime.composition.exact_life_query_pipeline import (
    ExactLifeQueryPipeline,
    _result_bytes,
)


class _QueryPort:
    def __init__(
        self,
        page: LifeRecordPage | None = None,
        error: LifeRecordQueryViolation | None = None,
    ) -> None:
        self.page = page or LifeRecordPage(())
        self.error = error
        self.requests: list[LifeRecordQuery] = []

    async def query(self, request: LifeRecordQuery) -> LifeRecordPage:
        self.requests.append(request)
        if self.error is not None:
            raise self.error
        return self.page


def _snapshot(kind: LifeRecordKind = LifeRecordKind.MEMORY) -> ExactLifeQuerySnapshot:
    return ExactLifeQuerySnapshot(
        intent_id=uuid7(),
        subject_id=uuid7(),
        source_opportunity_id=uuid7(),
        scene_id=uuid7(),
        creator_party_id=uuid7(),
        record_kind=kind,
        query_text="曾经约定过的事情",
        limit=20,
        query_digest=Digest.from_bytes(b"query"),
        trace_id=TraceId("11" * 16),
    )


def _pipeline(port: _QueryPort) -> ExactLifeQueryPipeline:
    pipeline = object.__new__(ExactLifeQueryPipeline)
    pipeline._query = port  # pyright: ignore[reportPrivateUsage]
    return pipeline


@pytest.mark.asyncio
async def test_forgotten_record_is_returned_as_just_queried_evidence() -> None:
    item = LifeRecordItem(
        record_ref=uuid7(),
        record_kind=LifeRecordKind.MEMORY,
        summary="曾经形成、现在已经忘记的一项记忆。",
        source_kind="subjective_memory",
        occurred_at=Instant(datetime(2026, 8, 1, tzinfo=UTC)),
        naturally_recallable=False,
        retrieval_kind=LifeRecordRetrievalKind.EXACT_QUERY,
    )
    port = _QueryPort(LifeRecordPage((item,)))
    snapshot = _snapshot()

    status, page, failure = await _pipeline(port)._execute_query(snapshot)

    assert status == "succeeded"
    assert page is not None and page.items == (item,)
    assert failure is None
    request = port.requests[0]
    assert request.actor is LifeRecordActor.SUBJECT
    assert request.retrieval_kind is LifeRecordRetrievalKind.EXACT_QUERY
    assert request.record_kind is LifeRecordKind.MEMORY
    result = _result_bytes(
        snapshot,
        status=status,
        page=page,
        failure_code=failure,
    )
    assert b'"naturally_recallable":false' in result
    assert b'"retrieval_kind":"exact_query"' in result


@pytest.mark.asyncio
async def test_private_subject_material_and_empty_result_keep_distinct_outcomes() -> (
    None
):
    private_item = LifeRecordItem(
        record_ref=uuid7(),
        record_kind=LifeRecordKind.MATERIAL,
        summary="只对主体可见的私人草稿。",
        source_kind="life_material.private",
        occurred_at=Instant(datetime(2026, 8, 2, tzinfo=UTC)),
        naturally_recallable=None,
        retrieval_kind=LifeRecordRetrievalKind.EXACT_QUERY,
    )
    private_port = _QueryPort(LifeRecordPage((private_item,)))
    private_status, private_page, private_failure = await _pipeline(
        private_port
    )._execute_query(_snapshot(LifeRecordKind.MATERIAL))
    assert private_status == "succeeded"
    assert private_page is not None and private_page.items == (private_item,)
    assert private_failure is None

    empty_port = _QueryPort(LifeRecordPage(()))
    empty_status, empty_page, empty_failure = await _pipeline(
        empty_port
    )._execute_query(_snapshot(LifeRecordKind.CONVERSATION))
    assert empty_status == "empty"
    assert empty_page is not None and empty_page.items == ()
    assert empty_failure is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("code", "expected"),
    [
        ("LIFE-QUERY-UNAVAILABLE", "failed"),
        ("LIFE-QUERY-NOT-AUTHORIZED", "denied"),
    ],
)
async def test_read_failure_and_permission_denial_settle_differently(
    code: str,
    expected: str,
) -> None:
    port = _QueryPort(error=LifeRecordQueryViolation(code))

    status, page, failure = await _pipeline(port)._execute_query(_snapshot())

    assert status == expected
    assert page is None
    assert failure == code


@pytest.mark.asyncio
async def test_creator_view_result_cannot_cross_the_subject_query_harness() -> None:
    item = LifeRecordItem(
        record_ref=uuid7(),
        record_kind=LifeRecordKind.MATERIAL,
        summary="错误来源的投影。",
        source_kind="life_material",
        occurred_at=Instant(datetime(2026, 8, 2, tzinfo=UTC)),
        naturally_recallable=None,
        retrieval_kind=LifeRecordRetrievalKind.CREATOR_VIEW,
    )

    status, page, failure = await _pipeline(
        _QueryPort(LifeRecordPage((item,)))
    )._execute_query(_snapshot(LifeRecordKind.MATERIAL))

    assert status == "failed"
    assert page is None
    assert failure == "LIFE-QUERY-SCOPE"

    wrong_kind = LifeRecordItem(
        record_ref=uuid7(),
        record_kind=LifeRecordKind.RELATIONSHIP,
        summary="错误类型的记录。",
        source_kind="relationship_current",
        occurred_at=Instant(datetime(2026, 8, 2, tzinfo=UTC)),
        naturally_recallable=None,
        retrieval_kind=LifeRecordRetrievalKind.EXACT_QUERY,
    )
    status, page, failure = await _pipeline(
        _QueryPort(LifeRecordPage((wrong_kind,)))
    )._execute_query(_snapshot(LifeRecordKind.MATERIAL))

    assert status == "failed"
    assert page is None
    assert failure == "LIFE-QUERY-SCOPE"
