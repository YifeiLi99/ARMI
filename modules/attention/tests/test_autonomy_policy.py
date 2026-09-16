"""Virtual-clock checks for scheduling bounds and calendar quota rollover."""

from datetime import UTC, datetime, timedelta
from typing import Any, cast

import pytest
from armi_attention._autonomy_policy import AutonomyPolicy, quota_day, quota_reset_at


def test_consideration_is_bounded_and_does_not_depend_on_replies_or_night() -> None:
    policy = AutonomyPolicy()
    # 00:00 Beijing, with no input or activity required to schedule another thought.
    now = datetime(2026, 9, 16, 16, tzinfo=UTC)
    for _ in range(72):
        following = policy.next_consideration(now, 3600)
        assert following - now == timedelta(hours=1)
        now = following
    assert policy.next_consideration(now, 60) == now + timedelta(minutes=1)
    assert policy.next_consideration(now, 21_600) == now + timedelta(hours=6)
    for invalid in (0, 59, 21_601, True, 60.0):
        with pytest.raises(ValueError, match="SCHEDULE-RANGE"):
            policy.next_consideration(now, cast(Any, invalid))


def test_quota_rolls_over_at_beijing_midnight() -> None:
    before = datetime(2026, 9, 16, 15, 59, 59, tzinfo=UTC)
    after = before + timedelta(seconds=1)
    assert quota_day(before).isoformat() == "2026-09-16"
    assert quota_day(after).isoformat() == "2026-09-17"
    assert quota_reset_at(before) == after
    assert quota_reset_at(after) == after + timedelta(days=1)


def test_naive_clock_is_not_interpreted_using_host_timezone() -> None:
    now = datetime(2026, 9, 16)
    with pytest.raises(ValueError, match="AUTONOMY-TIME"):
        quota_day(now)
    with pytest.raises(ValueError, match="AUTONOMY-TIME"):
        AutonomyPolicy().next_consideration(now, 60)
