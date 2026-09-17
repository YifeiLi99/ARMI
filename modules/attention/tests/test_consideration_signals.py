import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock
from uuid import uuid7

import pytest
from armi_attention._signals import freeze_signals, unconsumed_signals
from armi_attention.api import LifeViolation, project_signal_status
from armi_kernel.application import ConsiderationSignal


def signal(at, *, object_ref=None, version="condition-1"):
    return ConsiderationSignal(
        "mind", object_ref or uuid7(), version, "review_time_reached", at
    )


@pytest.mark.asyncio
async def test_consumption_is_by_object_and_version_not_round_finish_time():
    now = datetime(2026, 9, 17, tzinfo=UTC)
    accepted = signal(now)
    became_due_during_call = signal(now + timedelta(minutes=2))
    changed = signal(now, object_ref=accepted.object_ref, version="condition-2")
    tx = SimpleNamespace(execute=AsyncMock())
    tx.execute.return_value.fetchone = AsyncMock()
    tx.execute.return_value.fetchall = AsyncMock(return_value=[accepted.identity])
    remaining = await unconsumed_signals(
        cast(Any, tx),
        subject_id=uuid7(),
        signals=(accepted, became_due_during_call, changed),
    )
    assert remaining == (became_due_during_call, changed)


@pytest.mark.asyncio
async def test_freeze_rejects_future_conditions_and_records_only_supplied_signals():
    now = datetime(2026, 9, 17, tzinfo=UTC)
    tx = SimpleNamespace(execute=AsyncMock(return_value=SimpleNamespace(rowcount=1)))
    with pytest.raises(LifeViolation, match="LIFE-SIGNAL-NOT-DUE"):
        await freeze_signals(
            cast(Any, tx),
            opportunity_id=uuid7(),
            signals=(signal(now + timedelta(seconds=1)),),
            frozen_at=now,
        )
    tx.execute.assert_not_awaited()
    accepted = signal(now)
    await freeze_signals(
        cast(Any, tx), opportunity_id=uuid7(), signals=(accepted,), frozen_at=now
    )
    payload = json.loads(tx.execute.call_args.args[1][0])
    assert payload["signals"][0]["condition_version"] == accepted.condition_version
    assert payload["frozen_at"] == now.isoformat()
    assert "source_commit_id" not in payload["signals"][0]
    tx.execute.return_value.rowcount = 0
    with pytest.raises(LifeViolation, match="LIFE-SIGNAL-FREEZE-STALE"):
        await freeze_signals(
            cast(Any, tx), opportunity_id=uuid7(), signals=(), frozen_at=now
        )


def test_withdrawing_early_signal_restores_base_plan_without_mutating_it():
    now = datetime(2026, 9, 17, tzinfo=UTC)
    base = now + timedelta(hours=6)
    state: dict[str, object] = {
        "next_consideration_at": base.isoformat(),
        "observed_at": now.isoformat(),
        "state": "scheduled",
    }
    due = signal(now)
    project_signal_status(state, (due,), frozenset())
    assert state["state"] == "ready"
    assert state["effective_consideration_at"] == now.isoformat()
    assert state["next_consideration_at"] == base.isoformat()
    project_signal_status(state, (), frozenset())
    assert state["state"] == "scheduled"
    assert state["effective_consideration_at"] == base.isoformat()
    project_signal_status(state, (due,), frozenset({due.identity}))
    assert state["consideration_signals"] == []
