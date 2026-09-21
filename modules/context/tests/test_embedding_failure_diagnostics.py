from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock, patch
from uuid import uuid7

import pytest
from armi_context._embedding_application import ContextEmbeddingPipeline
from armi_context.api import EmbeddingResponse
from armi_context.bootstrap import bootstrap_context_recovery
from armi_kernel.application import ModelViolation


@pytest.mark.asyncio
@pytest.mark.parametrize("outcome", ["success", "failed", "stale"])
async def test_projection_keeps_work_and_source_checks_without_attempt_rows(outcome):
    events = []
    lease = object()
    unit = SimpleNamespace(
        work=SimpleNamespace(validate_lease=AsyncMock(), complete=AsyncMock()),
        add_before_commit=lambda callback: None,
    )

    class Transaction:
        async def __aenter__(self):
            return unit

        async def __aexit__(self, *args):
            return None

    repository = SimpleNamespace(
        prepare_source_set=AsyncMock(),
        store_projection=AsyncMock(
            return_value=None if outcome == "stale" else uuid7()
        ),
        mark_source_set_stale=AsyncMock(),
        complete_source_set=AsyncMock(return_value=True),
        note_projection_work_settled=AsyncMock(),
    )
    pipeline = ContextEmbeddingPipeline.__new__(ContextEmbeddingPipeline)
    pipeline._factory = cast(Any, SimpleNamespace(unit_of_work=Transaction))
    pipeline._repository = cast(Any, repository)
    pipeline._attempt_diagnostic = events.append
    pipeline._work = cast(
        Any, SimpleNamespace(renew=AsyncMock(return_value=lease), release=AsyncMock())
    )
    source = SimpleNamespace(
        source_kind="life_material", source_ref=uuid7(), source_version=3
    )
    record = SimpleNamespace(
        attempt_count=1,
        draft=SimpleNamespace(max_attempts=3, work_id=SimpleNamespace(value=uuid7())),
    )
    invoke = AsyncMock(
        return_value=(EmbeddingResponse((0.0,) * 1024, "local-call", 8),)
    )
    if outcome == "failed":
        invoke.side_effect = ModelViolation("MODEL-UNAVAILABLE")
    with (
        patch.object(
            ContextEmbeddingPipeline,
            "_source_chunks",
            AsyncMock(return_value=(("私密正文", "检索正文"),)),
        ),
        patch.object(ContextEmbeddingPipeline, "_embed_with_renewal", invoke),
    ):
        assert await pipeline._project_source(
            cast(Any, record), cast(Any, lease), cast(Any, source)
        )
    assert [event.status for event in events] == [
        "dispatched",
        "failed" if outcome == "failed" else "returned",
    ]
    assert all(event.source_ref == str(source.source_ref) for event in events)
    assert "正文" not in repr(events)
    if outcome == "failed":
        pipeline._work.release.assert_awaited_once()
        repository.store_projection.assert_not_awaited()
        unit.work.complete.assert_not_awaited()
    else:
        repository.store_projection.assert_awaited_once()
        unit.work.complete.assert_awaited_once()
        if outcome == "stale":
            repository.mark_source_set_stale.assert_awaited_once()
            repository.complete_source_set.assert_not_awaited()
        else:
            repository.complete_source_set.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "deterministic,rollback", [(True, False), (False, False), (False, True)]
)
async def test_live_failure_logs_only_after_settlement(deterministic, rollback):
    events = []
    unit = SimpleNamespace(
        work=SimpleNamespace(validate_lease=AsyncMock(), fail=AsyncMock()),
        transaction=SimpleNamespace(execute=AsyncMock()),
        add_before_commit=lambda callback: None,
    )

    class Transaction:
        async def __aenter__(self):
            return unit

        async def __aexit__(self, *args):
            assert not events
            if rollback:
                raise RuntimeError("commit failed")

    pipeline = ContextEmbeddingPipeline.__new__(ContextEmbeddingPipeline)
    pipeline._factory = cast(Any, SimpleNamespace(unit_of_work=Transaction))
    pipeline._repository = cast(
        Any, SimpleNamespace(note_projection_work_settled=AsyncMock())
    )
    pipeline._failure_diagnostic = events.append
    source = SimpleNamespace(
        source_kind="life_material", source_ref=uuid7(), source_version=3
    )
    record = SimpleNamespace(
        draft=SimpleNamespace(generation=3, work_id=SimpleNamespace(value=uuid7()))
    )

    async def settle():
        await pipeline._terminal_or_successor(
            cast(Any, record),
            cast(Any, object()),
            cast(Any, source),
            "MODEL-UNAVAILABLE",
            deterministic=deterministic,
        )

    if rollback:
        with pytest.raises(RuntimeError, match="commit failed"):
            await settle()
        assert not events
    else:
        await settle()
        unit.work.fail.assert_awaited_once()
        assert events[0].disposition == ("terminal" if deterministic else "degraded")
        assert events[0].source_ref == str(source.source_ref)


@pytest.mark.asyncio
@pytest.mark.parametrize("generation,delay", [(1, 60), (2, 300), (3, None)])
async def test_interrupted_embedding_logs_failure_and_keeps_retry_policy(
    generation, delay
):
    events = []
    participant = bootstrap_context_recovery(events.append)
    transaction = AsyncMock()
    item = SimpleNamespace(
        work_id=uuid7(),
        subject_id=uuid7(),
        owner_kind="subjective_memory",
        owner_ref=uuid7(),
        idempotency_key="embedding:7:source",
        generation=generation,
        deadline_at=datetime.now(UTC),
        reconciliation_required=True,
        last_error_code="MODEL-UNAVAILABLE",
    )
    reconciliation = SimpleNamespace(fail_with_successor=AsyncMock(), fail=AsyncMock())
    before = datetime.now(UTC)
    with patch(
        "armi_context._recovery.OwnerReconciliationContext", return_value=reconciliation
    ):
        await participant.recover(transaction, cast(Any, object()), (cast(Any, item),))
    assert len(events) == 1
    assert events[0].work_id == str(item.work_id)
    assert events[0].source_ref == str(item.owner_ref)
    assert events[0].source_version == 7
    assert events[0].error_code == "MODEL-UNAVAILABLE"
    if delay is not None:
        reconciliation.fail_with_successor.assert_awaited_once()
        retry = reconciliation.fail_with_successor.call_args.kwargs["not_before"]
        assert delay <= (retry - before).total_seconds() < delay + 5
        assert events[0].retry_at == retry.isoformat()
        assert events[0].disposition == "retry_wait"
        transaction.execute.assert_not_awaited()
    else:
        reconciliation.fail.assert_awaited_once()
        reconciliation.fail_with_successor.assert_not_awaited()
        assert events[0].retry_at is None
        assert events[0].disposition == "degraded"
        assert "coverage_state='degraded'" in transaction.execute.call_args.args[0]
