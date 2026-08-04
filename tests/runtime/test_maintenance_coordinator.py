from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any, cast
from unittest.mock import AsyncMock
from uuid import uuid7

import pytest
from armi_kernel.application import (
    LifeViolation,
    MaintenancePhase,
    MaintenanceResultStatus,
)
from armi_runtime.adapters.persistence.maintenance import MaintenanceProgress
from armi_runtime.composition.life_opportunity import MaintenanceCoordinator


class _Factory:
    unit = object()

    @asynccontextmanager
    async def unit_of_work(self, _lock_plan: object):
        yield self.unit


def _coordinator(repository: object, *, quiet_seconds: int = 60):
    return MaintenanceCoordinator(
        factory=cast(Any, _Factory()),
        repository=cast(Any, repository),
        opportunities=cast(Any, repository),
        consideration_seconds=57_600,
        deadline_seconds=86_400,
        quiet_seconds=quiet_seconds,
    )


@pytest.mark.asyncio
async def test_active_session_checkpoint_precedes_new_sleep_window() -> None:
    repository = AsyncMock()
    repository.maintain_active_session.return_value = MaintenanceProgress(
        uuid7(),
        MaintenancePhase.SELF_CHECK,
        MaintenanceResultStatus.RUNNING,
        3,
        "LIFE-MAINTENANCE-ADVANCED",
    )
    outcome = await _coordinator(repository).maintain_once()
    assert outcome.reason_code == "LIFE-MAINTENANCE-ADVANCED"
    repository.maintain_sleep_window.assert_not_awaited()


@pytest.mark.asyncio
async def test_no_active_session_scans_the_objective_window() -> None:
    repository = AsyncMock()
    repository.maintain_active_session.return_value = None
    repository.maintain_sleep_window.return_value = object()
    outcome = await _coordinator(repository).maintain_once()
    assert outcome is repository.maintain_sleep_window.return_value
    repository.maintain_sleep_window.assert_awaited_once()


@pytest.mark.asyncio
async def test_emergency_wake_is_forwarded_as_a_durable_request() -> None:
    repository = AsyncMock()
    request_id = uuid7()
    session_id = uuid7()
    repository.request_emergency_wake.return_value = session_id
    assert (
        await _coordinator(repository).request_emergency_wake(request_id) == session_id
    )
    repository.request_emergency_wake.assert_awaited_once_with(
        _Factory.unit,
        request_id=request_id,
    )


def test_negative_quiet_window_is_rejected() -> None:
    with pytest.raises(LifeViolation):
        _coordinator(AsyncMock(), quiet_seconds=-1)
