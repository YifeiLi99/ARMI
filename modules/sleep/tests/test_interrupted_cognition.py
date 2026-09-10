"""Interrupted phase cognition gets a fresh opportunity within the existing limit."""

from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock
from uuid import uuid7

import pytest
from armi_sleep._maintenance import PostgreSQLMaintenanceRepository
from armi_sleep.api import MaintenancePhase


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "phase",
    [
        MaintenancePhase.MEMORY_MAINTENANCE,
        MaintenancePhase.SELF_CHECK,
        MaintenancePhase.REFLECT_SELF,
        MaintenancePhase.REFLECT_MIND,
        MaintenancePhase.REFLECT_MOOD,
        MaintenancePhase.REFLECT_PROMPT,
    ],
)
@pytest.mark.parametrize("reconsideration", [0, 1])
async def test_interrupted_phase_gets_fresh_opportunity_or_exhausts(
    phase, reconsideration
) -> None:
    old = SimpleNamespace(
        opportunity_id=uuid7(),
        root_opportunity_id=uuid7(),
        disposition="cancelled",
        reconsideration_no=reconsideration,
    )
    new_id = uuid7()
    opportunities = SimpleNamespace(
        maintenance_work_state=AsyncMock(return_value=old),
        admit_sleep=AsyncMock(
            return_value=SimpleNamespace(opportunity_id=new_id, inserted=True)
        ),
    )
    repository = PostgreSQLMaintenanceRepository(
        cast(Any, object()), cast(Any, opportunities)
    )
    result = await repository._admit_phase_work(
        cast(Any, SimpleNamespace(transaction=object())),
        subject_id=uuid7(),
        session_id=uuid7(),
        revision_id=uuid7(),
        head_version=3,
        phase=phase,
    )
    if reconsideration:
        assert result == (None, False)
        opportunities.admit_sleep.assert_not_awaited()
    else:
        assert result == (new_id, True)
        draft = opportunities.admit_sleep.await_args.args[1]
        assert draft.predecessor_id == old.opportunity_id
        assert draft.reconsideration_no == 1
        assert new_id != old.opportunity_id
