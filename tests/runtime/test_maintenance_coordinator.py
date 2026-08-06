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
    OpportunityAdmissionOutcome,
    OpportunityAdmissionStatus,
)
from armi_runtime.adapters.persistence.maintenance import MaintenanceProgress
from armi_runtime.composition.life_opportunity import MaintenanceCoordinator


class _Factory:
    unit = object()

    @asynccontextmanager
    async def unit_of_work(self, _lock_plan: object):
        yield self.unit


def _coordinator(
    repository: object,
    *,
    quiet_seconds: int = 60,
    notifier: object | None = None,
):
    return MaintenanceCoordinator(
        factory=cast(Any, _Factory()),
        repository=cast(Any, repository),
        opportunities=cast(Any, repository),
        consideration_seconds=57_600,
        deadline_seconds=86_400,
        quiet_seconds=quiet_seconds,
        notifier=cast(Any, notifier),
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
async def test_maintenance_phase_work_reports_first_admission_then_pending() -> None:
    repository = AsyncMock()
    session_id = uuid7()
    opportunity_id = uuid7()
    repository.maintain_active_session.side_effect = (
        MaintenanceProgress(
            session_id,
            MaintenancePhase.MEMORY_MAINTENANCE,
            MaintenanceResultStatus.RUNNING,
            2,
            "LIFE-MAINTENANCE-WORK-ADMITTED",
            opportunity_id,
            True,
        ),
        MaintenanceProgress(
            session_id,
            MaintenancePhase.MEMORY_MAINTENANCE,
            MaintenanceResultStatus.RUNNING,
            2,
            "LIFE-MAINTENANCE-WORK-PENDING",
            opportunity_id,
            False,
        ),
    )
    coordinator = _coordinator(repository)
    admitted = await coordinator.maintain_once()
    pending = await coordinator.maintain_once()
    assert admitted.status is OpportunityAdmissionStatus.ADMITTED
    assert admitted.opportunity_id == opportunity_id
    assert pending.status is OpportunityAdmissionStatus.DUPLICATE
    assert pending.opportunity_id == opportunity_id


@pytest.mark.asyncio
async def test_no_active_session_scans_the_objective_window() -> None:
    repository = AsyncMock()
    repository.maintain_active_session.return_value = None
    repository.maintain_sleep_window.return_value = OpportunityAdmissionOutcome(
        OpportunityAdmissionStatus.REJECTED,
        None,
        "LIFE-MAINTENANCE-NOT-DUE",
    )
    outcome = await _coordinator(repository).maintain_once()
    assert outcome is repository.maintain_sleep_window.return_value
    repository.maintain_sleep_window.assert_awaited_once()


@pytest.mark.asyncio
async def test_emergency_wake_is_forwarded_as_a_durable_request() -> None:
    repository = AsyncMock()
    session_id = uuid7()
    request_id = uuid7()
    repository.request_emergency_wake.return_value = session_id
    assert (
        await _coordinator(repository).request_emergency_wake(session_id, request_id)
        == session_id
    )
    repository.request_emergency_wake.assert_awaited_once_with(
        _Factory.unit,
        session_id=session_id,
        request_id=request_id,
    )


@pytest.mark.asyncio
async def test_checkpoint_publishes_a_creator_maintenance_invalidation() -> None:
    repository = AsyncMock()
    session_id = uuid7()
    repository.maintain_active_session.return_value = MaintenanceProgress(
        session_id,
        MaintenancePhase.SELF_CHECK,
        MaintenanceResultStatus.RUNNING,
        3,
        "LIFE-MAINTENANCE-ADVANCED",
    )
    notifier = AsyncMock()
    await _coordinator(repository, notifier=notifier).maintain_once()
    invalidation = notifier.notify.await_args.args[0]
    assert invalidation.resource_kind.value == "maintenance"
    assert invalidation.resource_ref == str(session_id)


def test_negative_quiet_window_is_rejected() -> None:
    with pytest.raises(LifeViolation):
        _coordinator(AsyncMock(), quiet_seconds=-1)
