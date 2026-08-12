"""Activity-owned lifecycle and scheduling rules."""

from __future__ import annotations

from datetime import datetime, timedelta
from enum import StrEnum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .api import (
        ActivityHeadSnapshot,
        ActivitySchedulingDecision,
        ActivitySchedulingSnapshot,
    )


class ActivityStatus(StrEnum):
    CONSIDERING = "considering"
    READY = "ready"
    IN_PROGRESS = "in_progress"
    WAITING = "waiting"
    PAUSED = "paused"
    RESUMING = "resuming"
    COMPLETED = "completed"
    ABANDONED = "abandoned"
    FAILED = "failed"


class ActivityTransition(StrEnum):
    CREATED = "created"
    ENGAGE = "engage"
    PROGRESS = "progress"
    WAIT = "wait"
    PAUSE = "pause"
    RESUME = "resume"
    COMPLETE = "complete"
    ABANDON = "abandon"
    SYSTEM_FAIL = "system_fail"


class ActivityWaitingKind(StrEnum):
    TIME = "time"
    CREATOR_INPUT = "creator_input"
    EXTERNAL_EVIDENCE = "external_evidence"
    SCHEDULED_REVIEW = "scheduled_review"


class ActivityAttentionDecisionKind(StrEnum):
    ENGAGE = "engage"
    PROGRESS = "progress"
    WAIT = "wait"
    PAUSE = "pause"
    RESUME = "resume"
    COMPLETE = "complete"
    ABANDON = "abandon"
    NO_ACTION = "no_action"
    DEFER = "defer"
    NEED_INFORMATION = "need_information"


class ActivitySchedulingDisposition(StrEnum):
    ADMIT = "admit"
    DEFER = "defer"
    BACKPRESSURE = "backpressure"
    IDLE = "idle"


_COOLDOWN = timedelta(seconds=60)
_TERMINAL = {
    ActivityStatus.COMPLETED,
    ActivityStatus.ABANDONED,
    ActivityStatus.FAILED,
}


def select_activity(snapshot: ActivitySchedulingSnapshot) -> ActivitySchedulingDecision:
    """Select one immutable Activity head without mutating authority."""

    from .api import ActivitySchedulingDecision, ActivitySchedulingSnapshot

    if type(snapshot) is not ActivitySchedulingSnapshot:
        raise TypeError("snapshot must be ActivitySchedulingSnapshot")
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
            ready = (
                activity.resume_not_before is not None
                and activity.resume_not_before <= snapshot.now
                if activity.waiting_kind
                in {ActivityWaitingKind.TIME, ActivityWaitingKind.SCHEDULED_REVIEW}
                else activity.waiting_signal_available
            )
            if ready:
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
        return ActivitySchedulingDecision(
            ActivitySchedulingDisposition.ADMIT,
            selected.revision_id,
            snapshot.now,
            None,
        )
    if next_times:
        return ActivitySchedulingDecision(
            ActivitySchedulingDisposition.DEFER,
            None,
            min(next_times),
            "LIFE-SCHEDULER-COOLDOWN",
        )
    return ActivitySchedulingDecision(
        ActivitySchedulingDisposition.IDLE,
        None,
        None,
        "LIFE-SCHEDULER-IDLE",
    )


def _blocked(code: str) -> ActivitySchedulingDecision:
    from .api import ActivitySchedulingDecision

    return ActivitySchedulingDecision(
        ActivitySchedulingDisposition.BACKPRESSURE,
        None,
        None,
        code,
    )


__all__ = (
    "ActivityAttentionDecisionKind",
    "ActivitySchedulingDisposition",
    "ActivityStatus",
    "ActivityTransition",
    "ActivityWaitingKind",
    "select_activity",
)
