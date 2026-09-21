from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock
from uuid import uuid7

import pytest
from armi_artifact_store._lifecycle import ArtifactLifecycleCoordinator


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "error,attempt,status",
    [
        (None, 1, "completed"),
        ("ART-IO", 1, "retryable"),
        ("ART-IO", 8, "blocked"),
        ("ART-PATH-UNSAFE", 1, "blocked"),
    ],
)
async def test_deletion_logs_after_commit_and_preserves_retry_control(
    error, attempt, status
):
    events = []
    transaction = SimpleNamespace(
        execute=AsyncMock(return_value=SimpleNamespace(rowcount=1))
    )

    class Unit:
        async def __aenter__(self):
            return SimpleNamespace(transaction=transaction)

        async def __aexit__(self, *args):
            assert not events

    work = SimpleNamespace(complete=AsyncMock(), release=AsyncMock(), fail=AsyncMock())
    coordinator = ArtifactLifecycleCoordinator(
        cast(Any, object()),
        cast(Any, SimpleNamespace(unit_of_work=Unit)),
        cast(Any, work),
        events.append,
    )
    record = SimpleNamespace(
        lease=SimpleNamespace(attempt_id=SimpleNamespace(value=uuid7())),
        draft=SimpleNamespace(owner=SimpleNamespace(reference=uuid7())),
        attempt_count=attempt,
    )
    if error is None:
        await coordinator._settle_success(cast(Any, record))
        work.complete.assert_awaited_once()
    else:
        await coordinator._settle_failure(cast(Any, record), error)
        if status == "blocked":
            work.fail.assert_awaited_once()
            work.release.assert_not_awaited()
        else:
            work.release.assert_awaited_once()
            work.fail.assert_not_awaited()
    assert len(events) == 1
    assert events[0].result_status == status
    assert events[0].error_code == error
    assert events[0].deletion_id == str(record.draft.owner.reference)
    assert events[0].attempt_no == attempt
