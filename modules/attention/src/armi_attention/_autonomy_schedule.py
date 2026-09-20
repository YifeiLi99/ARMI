"""Bounded idle checks; model choices never set the scheduler's clock."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

CHECK_INTERVALS = (60, 120, 300)


@dataclass(frozen=True, slots=True)
class AutonomySchedule:
    idle_streak: int = 0
    failure_streak: int = 0

    def __post_init__(self) -> None:
        if any(
            type(value) is not int or value < 0
            for value in (
                self.idle_streak,
                self.failure_streak,
            )
        ):
            raise ValueError("LIFE-AUTONOMY-SCHEDULE")

    @property
    def interval_seconds(self) -> int:
        level = self.failure_streak - 1 if self.failure_streak else self.idle_streak
        return CHECK_INTERVALS[min(level, len(CHECK_INTERVALS) - 1)]

    def settled(self, *, acted: bool) -> AutonomySchedule:
        return AutonomySchedule(0 if acted else min(self.idle_streak + 1, 2))

    def failed(self) -> AutonomySchedule:
        return AutonomySchedule(self.idle_streak, min(self.failure_streak + 1, 3))

    def next_check(self, now: datetime) -> datetime:
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("LIFE-AUTONOMY-TIME")
        return now + timedelta(seconds=self.interval_seconds)

    @staticmethod
    def signalled(now: datetime, last_started_at: datetime | None) -> datetime:
        earliest = (
            now
            if last_started_at is None
            else max(now, last_started_at + timedelta(seconds=CHECK_INTERVALS[0]))
        )
        return earliest
