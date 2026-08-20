"""P0-S001 autonomous opportunity source contract checks."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid7

import pytest
from armi_activity.api import (
    ActivityHeadSnapshot,
    ActivityId,
    ActivityScheduler,
    ActivitySchedulingDisposition,
    ActivitySchedulingSnapshot,
    ActivityStatus,
    ActivityWaitingKind,
)
from armi_attention.api import (
    CreatorOutreachPolicy,
    LifeViolation,
    OpportunityAdmissionOutcome,
    OpportunityAdmissionStatus,
)


def test_creator_outreach_policy_and_activity_source_are_explicit() -> None:
    policy = CreatorOutreachPolicy(259_200, 86_400)
    assert policy.absence_after_seconds == 259_200
    with pytest.raises(LifeViolation, match="LIFE-OUTREACH-POLICY"):
        CreatorOutreachPolicy(3_599, 86_400)


def test_admission_outcome_preserves_duplicate_identity_and_rejection_reason() -> None:
    opportunity_id = uuid7()
    duplicate = OpportunityAdmissionOutcome(
        OpportunityAdmissionStatus.DUPLICATE,
        opportunity_id,
    )
    rejected = OpportunityAdmissionOutcome(
        OpportunityAdmissionStatus.REJECTED,
        None,
        "LIFE-SOURCE-STALE",
    )
    assert duplicate.opportunity_id == opportunity_id
    assert rejected.reason_code == "LIFE-SOURCE-STALE"

    with pytest.raises(LifeViolation, match="LIFE-ADMISSION"):
        OpportunityAdmissionOutcome(
            OpportunityAdmissionStatus.REJECTED,
            opportunity_id,
            "LIFE-SOURCE-STALE",
        )


def _head(
    *,
    status: ActivityStatus,
    created_at: datetime,
    last_considered_at: datetime | None = None,
    waiting_kind: ActivityWaitingKind | None = None,
    resume_not_before: datetime | None = None,
    waiting_signal_available: bool = False,
) -> ActivityHeadSnapshot:
    return ActivityHeadSnapshot(
        activity_id=ActivityId(uuid7()),
        revision_id=uuid7(),
        revision_no=1,
        status=status,
        created_at=created_at,
        last_considered_at=last_considered_at,
        waiting_kind=waiting_kind,
        resume_not_before=resume_not_before,
        waiting_signal_available=waiting_signal_available,
    )


def test_scheduler_preserves_one_cognition_slot_and_single_focus() -> None:
    now = datetime.now(UTC)
    scheduler = ActivityScheduler()
    ready = _head(status=ActivityStatus.READY, created_at=now)
    snapshot = ActivitySchedulingSnapshot(now, (ready,), (), False, 2, 0)
    assert scheduler.select(snapshot).activity_revision_id == ready.revision_id

    for constrained, code in (
        (
            ActivitySchedulingSnapshot(now, (ready,), (), False, 1, 0),
            "MODEL-CONCURRENCY",
        ),
        (
            ActivitySchedulingSnapshot(now, (ready,), (), True, 2, 0),
            "ATTENTION-OUTSTANDING",
        ),
        (
            ActivitySchedulingSnapshot(
                now, (ready,), (ready.activity_id,), False, 2, 0
            ),
            "FOCUS-HELD",
        ),
        (
            ActivitySchedulingSnapshot(now, (ready,), (), False, 2, 1),
            "COGNITION-CAPACITY",
        ),
        (
            ActivitySchedulingSnapshot(now, (ready,), (), False, 2, 3),
            "COGNITION-CAPACITY",
        ),
    ):
        decision = scheduler.select(constrained)
        assert decision.disposition is ActivitySchedulingDisposition.BACKPRESSURE
        assert decision.reason_code is not None and code in decision.reason_code


def test_scheduler_applies_cooldown_wait_signals_terminal_filter_and_fairness() -> None:
    now = datetime.now(UTC)
    scheduler = ActivityScheduler()
    cooling = _head(status=ActivityStatus.IN_PROGRESS, created_at=now)
    timed = _head(
        status=ActivityStatus.WAITING,
        created_at=now - timedelta(minutes=5),
        waiting_kind=ActivityWaitingKind.TIME,
        resume_not_before=now - timedelta(seconds=1),
    )
    signalled = _head(
        status=ActivityStatus.PAUSED,
        created_at=now - timedelta(minutes=4),
        waiting_kind=ActivityWaitingKind.SCHEDULED_REVIEW,
        resume_not_before=now - timedelta(seconds=1),
    )
    terminal = _head(
        status=ActivityStatus.COMPLETED,
        created_at=now - timedelta(days=1),
    )
    decision = scheduler.select(
        ActivitySchedulingSnapshot(
            now,
            (cooling, signalled, terminal, timed),
            (),
            False,
            2,
            0,
        )
    )
    assert decision.activity_revision_id == timed.revision_id

    deferred = scheduler.select(
        ActivitySchedulingSnapshot(now, (cooling,), (), False, 2, 0)
    )
    assert deferred.disposition is ActivitySchedulingDisposition.DEFER
    assert deferred.available_after == now + timedelta(seconds=60)
