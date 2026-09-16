"""Attention's deterministic scheduling and Beijing-day quota policy."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from typing import Literal

_BEIJING = timezone(timedelta(hours=8))


@dataclass(frozen=True, slots=True)
class AutonomyPolicy:
    enabled: bool = True
    daily_request_limit: int = 48
    minimum_consideration_seconds: int = 60
    maximum_consideration_seconds: int = 21_600
    outlet: Literal["qq", "creator_web"] = "qq"

    def __post_init__(self) -> None:
        if (
            type(self.enabled) is not bool
            or type(self.daily_request_limit) is not int
            or self.daily_request_limit < 1
            or type(self.minimum_consideration_seconds) is not int
            or type(self.maximum_consideration_seconds) is not int
            or not 60
            <= self.minimum_consideration_seconds
            <= self.maximum_consideration_seconds
            <= 21_600
            or self.outlet not in {"qq", "creator_web"}
        ):
            raise ValueError("LIFE-AUTONOMY-CONFIG")

    def next_consideration(self, now: datetime, delay_seconds: int) -> datetime:
        require_aware_time(now)
        if (
            type(delay_seconds) is not int
            or not self.minimum_consideration_seconds
            <= delay_seconds
            <= self.maximum_consideration_seconds
        ):
            raise ValueError("LIFE-AUTONOMY-SCHEDULE-RANGE")
        return now + timedelta(seconds=delay_seconds)


def require_aware_time(now: datetime) -> None:
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("LIFE-AUTONOMY-TIME")


def quota_day(now: datetime) -> date:
    require_aware_time(now)
    return now.astimezone(_BEIJING).date()


def quota_reset_at(now: datetime) -> datetime:
    return datetime.combine(quota_day(now) + timedelta(days=1), time(), _BEIJING)


__all__ = ("AutonomyPolicy", "quota_day", "quota_reset_at")
