"""Maintenance presents actual results, including a valid empty result list."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid7

import pytest
from armi_sleep._postgresql import PostgreSQLSleepRead
from armi_sleep.api import (
    CreatorMaintenanceTimelineItem,
    MaintenancePhase,
    MaintenanceResultStatus,
    MaintenanceWorkOutcome,
)


@pytest.mark.asyncio
async def test_empty_results_do_not_hide_an_existing_session() -> None:
    factory = MagicMock()
    transaction = AsyncMock()
    transaction.execute.return_value.fetchone.return_value = (1,)
    factory.unit_of_work.return_value.__aenter__.return_value.transaction = transaction
    decisions = AsyncMock()
    decisions.maintenance_results.return_value = ()
    query = PostgreSQLSleepRead(
        factory,
        subject_id=uuid7(),
        creator_party_id=uuid7(),
        environment_id=uuid7(),
        cursor_key=b"x" * 32,
        decisions=decisions,
    )
    session_id = uuid7()
    result = await query.timeline(session_id, limit=2)
    assert result.session_id == session_id
    assert result.items == ()
    assert result.next_cursor is None


@pytest.mark.asyncio
async def test_result_pagination_keeps_the_first_page_ceiling() -> None:
    factory = MagicMock()
    transaction = AsyncMock()
    transaction.execute.return_value.fetchone.return_value = (1,)
    factory.unit_of_work.return_value.__aenter__.return_value.transaction = transaction
    decisions = AsyncMock()
    decisions.maintenance_results.return_value = tuple(
        CreatorMaintenanceTimelineItem(
            revision_id=uuid7(),
            revision_no=n,
            phase=MaintenancePhase.SELF_CHECK,
            result_status=MaintenanceResultStatus.COMPLETED,
            transition_kind="completed",
            occurred_at=datetime.now(UTC),
            work_outcome=MaintenanceWorkOutcome.NO_ISSUE,
            problem_summary=None,
        )
        for n in (5, 3, 2)
    )
    query = PostgreSQLSleepRead(
        factory,
        subject_id=uuid7(),
        creator_party_id=uuid7(),
        environment_id=uuid7(),
        cursor_key=b"x" * 32,
        decisions=decisions,
    )
    session_id = uuid7()
    first = await query.timeline(session_id, limit=2)
    assert [item.revision_no for item in first.items] == [5, 3]
    assert first.next_cursor is not None
    decisions.maintenance_results.return_value = ()
    await query.timeline(session_id, limit=2, cursor=first.next_cursor)
    assert decisions.maintenance_results.await_args.kwargs["ceiling"] == 5
    assert decisions.maintenance_results.await_args.kwargs["before"] == 3
