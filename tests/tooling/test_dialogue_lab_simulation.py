from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import Mock

import pytest
from armi_kernel.application import (
    bind_business_clock,
    business_now,
    reset_business_clock,
)
from armi_local_control import SimulationClock

from tools.dialogue_lab_pricing import estimate_calls
from tools.dialogue_lab_simulation import collect_usage


def test_business_time_advances_without_changing_real_clock(tmp_path):
    clock = SimulationClock(tmp_path, "environment")
    clock.initialize()
    clock.validate()
    real = datetime.now(UTC)
    token = bind_business_clock(clock.read)
    try:
        clock.set_offset(600_000_000)
        assert timedelta(seconds=600) <= business_now() - real < timedelta(seconds=601)
        assert datetime.now(UTC) - real < timedelta(seconds=1)
        with pytest.raises(ValueError, match="OFFSET"):
            clock.set_offset(0)
    finally:
        reset_business_clock(token)
    assert datetime.now(UTC) - business_now() < timedelta(seconds=1)


def test_usage_includes_failed_unknown_and_all_pages():
    calls = [
        {"receipt": {"call_id": "one", "outcome": "failed"}},
        {"receipt": {"call_id": "two", "outcome": "unknown"}},
    ]
    lab = SimpleNamespace(
        admin=Mock(
            side_effect=[
                {"total": 2, "items": calls[:1]},
                {"total": 2, "items": calls[1:]},
                {"auxiliary_requests": []},
                {"auxiliary_requests": []},
                {"totals": {"billable_calls": 2, "usage_unconfirmed_calls": 1}},
            ]
        )
    )
    result = collect_usage(cast(Any, lab), start="start", end="end")
    assert result["calls"] == calls
    assert lab.admin.call_args_list[1].args[1]["offset"] == 1
    assert result["summary"]["totals"]["usage_unconfirmed_calls"] == 1


def test_usage_refuses_incomplete_pagination():
    lab = SimpleNamespace(admin=Mock(return_value={"total": 1, "items": []}))
    with pytest.raises(RuntimeError, match="PAGINATION"):
        collect_usage(cast(Any, lab), start="start", end="end")


def test_jev_cost_uses_official_input_rate_without_inventing_cache_or_fx():
    receipt = {
        "call_id": "jev",
        "provider": "typesafe",
        "model": "jev-1.13.0",
        "service": "generation",
        "outcome": "returned",
        "cost": {"status": "unpriced"},
        "quantities": [
            {"unit": "input_tokens", "quantity": 4870},
            {"unit": "output_tokens", "quantity": 380},
        ],
    }
    report = estimate_calls([{"receipt": receipt}])
    assert report["known_totals"] == {"USD": "0.00020454"}
    assert report["unknown_call_ids"] == []
    receipt["quantities"] = []
    report = estimate_calls([{"receipt": receipt}])
    assert report["known_totals"] == {}
    assert report["unknown_call_ids"] == ["jev"]
    receipt["cost"] = {"status": "not_billable"}
    report = estimate_calls([{"receipt": receipt}])
    assert report["unknown_call_ids"] == []
    assert report["non_billable_call_ids"] == ["jev"]
