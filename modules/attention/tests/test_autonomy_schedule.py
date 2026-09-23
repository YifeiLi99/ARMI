from datetime import UTC, datetime, timedelta

import pytest
from armi_attention._autonomy_schedule import AutonomySchedule


def test_idle_day_is_bounded_without_a_daily_quota() -> None:
    start = datetime(2026, 9, 20, tzinfo=UTC)
    deadline = start + timedelta(days=1)
    schedule = AutonomySchedule()
    next_check = schedule.next_check(start)
    calls = 0
    while next_check < deadline:
        calls += 1
        schedule = schedule.settled(acted=False)
        next_check = schedule.next_check(next_check)
    assert calls == 1439
    assert schedule.interval_seconds == 60


def test_progress_restores_one_minute_and_failure_is_not_an_idle_choice() -> None:
    idle = AutonomySchedule().settled(acted=False).settled(acted=False)
    assert idle.settled(acted=True) == AutonomySchedule()
    failed = AutonomySchedule().failed()
    assert (failed.idle_streak, failed.failure_streak) == (0, 1)
    assert failed.interval_seconds == 60
    assert failed.failed().interval_seconds == 120
    assert failed.failed().failed().interval_seconds == 300
    assert idle.failed().interval_seconds == 60


def test_naive_clock_is_rejected() -> None:
    with pytest.raises(ValueError, match="AUTONOMY-TIME"):
        AutonomySchedule().next_check(datetime(2026, 9, 20))


def test_fresh_signal_cannot_start_two_checks_within_a_minute() -> None:
    started = datetime(2026, 9, 20, tzinfo=UTC)
    assert AutonomySchedule.signalled(started + timedelta(seconds=15), started) == (
        started + timedelta(seconds=60)
    )
