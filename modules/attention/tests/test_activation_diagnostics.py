"""Scheduler evidence survives changing projections without logging each poll."""

from contextlib import asynccontextmanager
from typing import Any, cast
from unittest.mock import AsyncMock, Mock, patch
from uuid import uuid7

import pytest
from armi_attention._activation import Activation
from armi_attention._application import OpportunityPipeline
from armi_attention.api import (
    AutonomyPolicy,
    LifeViolation,
    OpportunityAdmissionOutcome,
    OpportunityAdmissionStatus,
)
from armi_kernel.application import record_diagnostic
from armi_runtime_foundation import RuntimeTransactionFailure


class _Factory:
    active = False
    fail_commit = False

    @asynccontextmanager
    async def unit_of_work(self):
        self.active = True
        try:
            yield object()
        finally:
            self.active = False
        if self.fail_commit:
            raise RuntimeTransactionFailure("commit failed")


def _pipeline(factory):
    return OpportunityPipeline(
        factory=cast(Any, factory),
        facts=cast(
            Any,
            Mock(
                outlet_health=AsyncMock(),
                model_configuration_revision=Mock(return_value="test-model"),
            ),
        ),
        activity_read=cast(Any, AsyncMock()),
        sleep_maintenance=cast(Any, AsyncMock()),
        sleep_read=cast(Any, AsyncMock()),
        subject_state_read=cast(Any, AsyncMock()),
    )


@pytest.mark.asyncio
async def test_activation_segments_log_after_commit_and_explain_later_progress(caplog):
    caplog.set_level("INFO", logger="armi.autonomy")
    factory, policy = _Factory(), AutonomyPolicy()
    pipeline = _pipeline(factory)
    state = Activation(cycle=0, threshold=2, anchor_seconds=0, weight=50, idling=True)
    active = 0.0
    reason = "LIFE-AUTONOMY-NOT-DUE"

    async def sample(*args, observations, **kwargs):
        amount, idle = state.project(active, policy)
        observations["activation"] = {
            "state": state.model_dump(mode="json"),
            "limits": {"quiet_seconds": 60, "maximum_idle_seconds": 7200},
            "active_seconds": active,
            "projected_accumulated": amount,
            "projected_idle_seconds": idle,
        }
        return OpportunityAdmissionOutcome(
            OpportunityAdmissionStatus.REJECTED, None, reason
        )

    def emit(*args, **kwargs):
        assert not factory.active, "diagnostic file I/O must follow transaction exit"
        record_diagnostic(*args, **kwargs)

    with (
        patch(
            "armi_attention._application.PostgreSQLLifeOpportunityRepository.admit_autonomy",
            side_effect=sample,
        ),
        patch("armi_attention._application.record_diagnostic", side_effect=emit),
    ):
        await pipeline.admit_once()
        for tick in (1.0, 5.0, 60.0, 300.0, 600.0):
            active = tick
            await pipeline.admit_once()
        assert len(caplog.records) == 1
        first = caplog.records[0].armi_details["activation"]
        restored = Activation.model_validate(first["state"])
        # At weight 50: 2/hour, plus the triangular idle-maturation integral.
        expected = 2 / 3600 * (600 + 600**2 / 3600)
        assert restored.project(active, policy)[0] == pytest.approx(expected)

        state = state.changed(active=active, idling=False, need=0, policy=policy)
        reason = "LIFE-AUTONOMY-NOT-IDLE"
        await pipeline.admit_once()
        assert caplog.records[-1].armi_details["activation"]["state"][
            "accumulated"
        ] == pytest.approx(expected)
        active = 900.0
        await pipeline.admit_once()
        assert len(caplog.records) == 2

        state = state.changed(active=active, idling=True, need=0.5, policy=policy)
        reason = "LIFE-AUTONOMY-NOT-DUE"
        await pipeline.admit_once()
        assert len(caplog.records) == 3
        assert caplog.records[-1].armi_details["activation"]["state"]["need"] == 0.5

        state = state.model_copy(update={"cycle": 1, "threshold": 3, "accumulated": 0})
        await pipeline.admit_once()
        assert len(caplog.records) == 4
        assert caplog.records[-1].armi_details["activation"]["state"]["threshold"] == 3

        # A fresh pipeline records a baseline even if persisted anchors are unchanged.
        restarted = _pipeline(factory)
        await restarted.admit_once()
        assert len(caplog.records) == 5


@pytest.mark.asyncio
async def test_failed_commit_does_not_log_or_consume_the_next_baseline(caplog):
    caplog.set_level("INFO", logger="armi.autonomy")
    factory = _Factory()
    pipeline = _pipeline(factory)
    opportunity_id = uuid7()

    async def sample(*args, observations, **kwargs):
        observations["activation"] = {"state": {"cycle": 1}, "limits": {}}
        return OpportunityAdmissionOutcome(
            OpportunityAdmissionStatus.ADMITTED, opportunity_id
        )

    with patch(
        "armi_attention._application.PostgreSQLLifeOpportunityRepository.admit_autonomy",
        side_effect=sample,
    ):
        factory.fail_commit = True
        with pytest.raises(LifeViolation, match="LIFE-DATABASE"):
            await pipeline.admit_once()
        assert not caplog.records
        factory.fail_commit = False
        await pipeline.admit_once()
    assert [record.armi_event for record in caplog.records] == [
        "autonomy.activation.observed",
        "autonomy.admission.checked",
    ]
    assert all(
        record.armi_details["opportunity_id"] == opportunity_id
        for record in caplog.records
    )
