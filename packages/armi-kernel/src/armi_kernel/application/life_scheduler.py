"""Pure single-focus Activity scheduling policy."""

from __future__ import annotations

from datetime import datetime, timedelta

from .life import (
    ActivityHeadSnapshot,
    ActivityStatus,
    ActivityWaitingKind,
    LifeScheduler,
    LifeSchedulingDecision,
    LifeSchedulingDisposition,
    LifeSchedulingSnapshot,
)

_COOLDOWN = timedelta(seconds=60)
_TERMINAL = {
    ActivityStatus.COMPLETED,
    ActivityStatus.ABANDONED,
    ActivityStatus.FAILED,
}


class PostgreSqlFairLifeScheduler(LifeScheduler):
    """Order eligible immutable heads; persistence still owns admission CAS."""

    __slots__ = ()

    def select(self, snapshot: LifeSchedulingSnapshot) -> LifeSchedulingDecision:
        if snapshot.model_concurrency < 2:
            return _blocked("LIFE-BACKPRESSURE-MODEL-CONCURRENCY")
        if snapshot.unresolved_attention:
            return _blocked("LIFE-BACKPRESSURE-ATTENTION-OUTSTANDING")
        if snapshot.active_activity_ids:
            return _blocked("LIFE-BACKPRESSURE-FOCUS-HELD")
        if snapshot.model_in_flight >= snapshot.model_concurrency - 1:
            return _blocked("LIFE-BACKPRESSURE-COGNITION-CAPACITY")

        eligible: list[ActivityHeadSnapshot] = []
        next_times: list[datetime] = []
        for activity in snapshot.activities:
            if (
                activity.status in _TERMINAL
                or activity.status is ActivityStatus.CONSIDERING
            ):
                continue
            if activity.status is ActivityStatus.READY:
                eligible.append(activity)
                continue
            if activity.status in {ActivityStatus.IN_PROGRESS, ActivityStatus.RESUMING}:
                available = activity.created_at + _COOLDOWN
                if available <= snapshot.now:
                    eligible.append(activity)
                else:
                    next_times.append(available)
                continue
            if activity.status in {ActivityStatus.WAITING, ActivityStatus.PAUSED}:
                if _waiting_is_ready(activity, snapshot):
                    eligible.append(activity)
                elif activity.resume_not_before is not None:
                    next_times.append(activity.resume_not_before)

        if eligible:
            selected = min(
                eligible,
                key=lambda item: (
                    item.last_considered_at is not None,
                    item.last_considered_at or item.created_at,
                    item.created_at,
                    str(item.activity_id),
                ),
            )
            return LifeSchedulingDecision(
                LifeSchedulingDisposition.ADMIT,
                selected.revision_id,
                snapshot.now,
                None,
            )
        if next_times:
            return LifeSchedulingDecision(
                LifeSchedulingDisposition.DEFER,
                None,
                min(next_times),
                "LIFE-SCHEDULER-COOLDOWN",
            )
        return LifeSchedulingDecision(
            LifeSchedulingDisposition.IDLE,
            None,
            None,
            "LIFE-SCHEDULER-IDLE",
        )


def _waiting_is_ready(
    activity: ActivityHeadSnapshot, snapshot: LifeSchedulingSnapshot
) -> bool:
    if activity.waiting_kind in {
        ActivityWaitingKind.TIME,
        ActivityWaitingKind.SCHEDULED_REVIEW,
    }:
        return (
            activity.resume_not_before is not None
            and activity.resume_not_before <= snapshot.now
        )
    return activity.waiting_signal_available


def _blocked(code: str) -> LifeSchedulingDecision:
    return LifeSchedulingDecision(
        LifeSchedulingDisposition.BACKPRESSURE,
        None,
        None,
        code,
    )


__all__ = ("PostgreSqlFairLifeScheduler",)
