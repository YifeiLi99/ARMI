"""Creator Activity projection contract tests."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid7

import pytest
from armi_kernel.application import (
    ActivityStatus,
    ActivityTransition,
    ActivityWaitingKind,
    CreatorActivityItem,
    CreatorActivityPage,
    CreatorActivityTimelineItem,
    CreatorActivityViolation,
)


def test_waiting_activity_exposes_only_formal_creator_projection() -> None:
    now = datetime(2026, 8, 4, 10, 0, tzinfo=UTC)
    item = CreatorActivityItem(
        activity_id=uuid7(),
        activity_kind="self_directed",
        status=ActivityStatus.WAITING,
        goal="继续阅读",
        progress_summary="读完第一章",
        waiting_kind=ActivityWaitingKind.TIME,
        waiting_summary="下午再继续",
        resume_not_before=now,
        terminal_reason=None,
        revision_no=2,
        head_version=2,
        transition_kind=ActivityTransition.WAIT,
        is_focused=False,
        created_at=now,
        updated_at=now,
    )
    assert item.waiting_summary == "下午再继续"


def test_activity_page_is_bounded_and_marks_truncation() -> None:
    assert CreatorActivityPage((), False).items == ()
    with pytest.raises(CreatorActivityViolation, match="ACTIVITY-QUERY-PAGE"):
        CreatorActivityPage(tuple(object() for _ in range(101)), True)  # type: ignore[arg-type]


def test_decision_only_timeline_shape_is_strict() -> None:
    now = datetime(2026, 8, 4, 10, 0, tzinfo=UTC)
    item = CreatorActivityTimelineItem(
        event_id=uuid7(),
        event_kind="defer",
        resulting_status=None,
        summary=None,
        review_not_before=now,
        occurred_at=now,
    )
    assert item.event_kind == "defer"
    with pytest.raises(CreatorActivityViolation, match="ACTIVITY-QUERY-TIMELINE"):
        CreatorActivityTimelineItem(
            event_id=uuid7(),
            event_kind="no_action",
            resulting_status=ActivityStatus.READY,
            summary=None,
            review_not_before=None,
            occurred_at=now,
        )
