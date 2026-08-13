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
from armi_kernel.contracts import Digest
from armi_opportunity.api import (
    CreatorOutreachPolicy,
    LifeOpportunitySourceKind,
    LifeOpportunitySourceSnapshot,
    LifeViolation,
    OpportunityAdmissionOutcome,
    OpportunityAdmissionStatus,
)


def _source(
    *,
    kind: LifeOpportunitySourceKind = (
        LifeOpportunitySourceKind.LIFE_GENERATION_AVAILABLE
    ),
    activity_id: ActivityId | None = None,
) -> LifeOpportunitySourceSnapshot:
    now = datetime.now(UTC)
    return LifeOpportunitySourceSnapshot(
        subject_id=uuid7(),
        generation_id=uuid7(),
        kind=kind,
        reference=uuid7(),
        version=1,
        digest=Digest.from_bytes(b"source"),
        available_after=now,
        expires_at=now + timedelta(minutes=5),
        activity_id=activity_id,
    )


def test_life_source_requires_normalized_identity_and_valid_expiry() -> None:
    source = _source()
    assert source.kind is LifeOpportunitySourceKind.LIFE_GENERATION_AVAILABLE
    assert source.version == 1

    with pytest.raises(LifeViolation, match="LIFE-SOURCE"):
        LifeOpportunitySourceSnapshot(
            subject_id=source.subject_id,
            generation_id=source.generation_id,
            kind=source.kind,
            reference=source.reference,
            version=0,
            digest=source.digest,
            available_after=source.available_after,
        )
    with pytest.raises(LifeViolation, match="LIFE-SOURCE"):
        LifeOpportunitySourceSnapshot(
            subject_id=source.subject_id,
            generation_id=source.generation_id,
            kind=source.kind,
            reference=source.reference,
            version=1,
            digest=source.digest,
            available_after=source.available_after,
            expires_at=source.available_after,
        )


def test_activity_revision_source_requires_activity_authority() -> None:
    with pytest.raises(LifeViolation, match="LIFE-SOURCE-ACTIVITY"):
        _source(kind=LifeOpportunitySourceKind.ACTIVITY_REVISION)
    activity_id = ActivityId(uuid7())
    source = _source(
        kind=LifeOpportunitySourceKind.ACTIVITY_REVISION,
        activity_id=activity_id,
    )
    assert source.activity_id == activity_id

    with pytest.raises(LifeViolation, match="LIFE-SOURCE-ACTIVITY"):
        _source(activity_id=activity_id)


def test_creator_outreach_policy_and_activity_source_are_explicit() -> None:
    policy = CreatorOutreachPolicy(259_200, 86_400)
    assert policy.absence_after_seconds == 259_200
    activity_id = ActivityId(uuid7())
    source = _source(
        kind=LifeOpportunitySourceKind.CREATOR_OUTREACH_ACTIVITY,
        activity_id=activity_id,
    )
    assert source.activity_id == activity_id

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
