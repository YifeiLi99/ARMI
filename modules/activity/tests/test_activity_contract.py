"""Activity module public contract and canonical owner-draft checks."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid7

import pytest
from armi_activity.api import (
    ActivityAttentionDecisionKind,
    ActivityHeadSnapshot,
    ActivityScheduler,
    ActivitySchedulingDisposition,
    ActivitySchedulingSnapshot,
    ActivityStatus,
    ActivityViolation,
    CandidateActivityDecisionDraft,
    CandidateActivityDraft,
    default_activity_cognition,
)
from armi_kernel.application import CandidateFactClass
from armi_kernel.contracts import ActivityId


def test_activity_create_and_decision_round_trip_as_opaque_owner_drafts() -> None:
    cognition = default_activity_cognition()
    activity_id = uuid7()
    created = CandidateActivityDraft(
        "proposal:1",
        "group:1",
        (1,),
        CandidateFactClass.INFERENCE,
        activity_id,
        "理解最近真正感兴趣的主题",
        "回看当前生活材料",
    )
    decision = CandidateActivityDecisionDraft(
        "proposal:2",
        "group:2",
        (2,),
        activity_id,
        uuid7(),
        1,
        ActivityAttentionDecisionKind.ENGAGE,
    )

    created_owner = cognition.bind_create(created)
    decision_owner = cognition.bind_decision(decision)

    assert created_owner.owner == "activity"
    assert decision_owner.owner == "activity"
    assert cognition.decode(created_owner.canonical_payload) == created
    assert cognition.decode(decision_owner.canonical_payload) == decision
    assert cognition.bind_legacy(created, decision=False) == created_owner
    assert cognition.bind_legacy(decision, decision=True) == decision_owner


def test_activity_codec_rejects_noncanonical_or_wrong_shape() -> None:
    cognition = default_activity_cognition()
    with pytest.raises(ActivityViolation, match="ACTIVITY-CODEC-PAYLOAD"):
        cognition.decode(b'{"kind": "create"}')


def test_scheduler_selects_the_oldest_ready_head() -> None:
    now = datetime(2026, 8, 13, 10, 0, tzinfo=UTC)
    older = ActivityHeadSnapshot(
        ActivityId(uuid7()),
        uuid7(),
        1,
        ActivityStatus.READY,
        now - timedelta(minutes=2),
        None,
    )
    newer = ActivityHeadSnapshot(
        ActivityId(uuid7()),
        uuid7(),
        1,
        ActivityStatus.READY,
        now - timedelta(minutes=1),
        None,
    )
    decision = ActivityScheduler().select(
        ActivitySchedulingSnapshot(now, (older, newer), (), False, 2, 0)
    )

    assert decision.disposition is ActivitySchedulingDisposition.ADMIT
    assert decision.activity_revision_id == older.revision_id
