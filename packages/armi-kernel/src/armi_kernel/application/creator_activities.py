"""Creator-visible, read-only projections of autonomous Activities."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Final, Literal, Protocol, runtime_checkable
from uuid import UUID

from .life import ActivityStatus, ActivityTransition, ActivityWaitingKind

ACTIVITY_PROJECTION_VERSION: Final = "creator-activity.v1"
type ActivityTimelineKind = Literal[
    "created",
    "engage",
    "progress",
    "wait",
    "pause",
    "resume",
    "complete",
    "abandon",
    "system_fail",
    "no_action",
    "defer",
    "need_information",
]
_EVENT_KINDS = frozenset(
    {
        *(item.value for item in ActivityTransition),
        "no_action",
        "defer",
        "need_information",
    }
)


class CreatorActivityViolation(RuntimeError):
    __slots__ = ("code",)

    def __init__(self, code: str) -> None:
        if type(code) is not str or not code.startswith("ACTIVITY-QUERY-"):
            raise ValueError("activity query violation code is invalid")
        self.code = code
        super().__init__("Creator Activity query failed")

    def __str__(self) -> str:
        return f"{self.code}: Creator Activity query failed"


def _uuid7(value: object) -> bool:
    return type(value) is UUID and value.version == 7


def _instant(value: object) -> bool:
    return type(value) is datetime and value.tzinfo is not None


@dataclass(frozen=True, slots=True)
class CreatorActivityItem:
    activity_id: UUID
    activity_kind: Literal["self_directed"]
    status: ActivityStatus
    goal: str
    progress_summary: str | None
    waiting_kind: ActivityWaitingKind | None
    waiting_summary: str | None
    resume_not_before: datetime | None
    terminal_reason: str | None
    revision_no: int
    head_version: int
    transition_kind: ActivityTransition
    is_focused: bool
    created_at: datetime
    updated_at: datetime

    def __post_init__(self) -> None:
        if (
            not _uuid7(self.activity_id)
            or self.activity_kind != "self_directed"
            or type(self.status) is not ActivityStatus
            or type(self.goal) is not str
            or not self.goal
            or type(self.revision_no) is not int
            or self.revision_no < 1
            or type(self.head_version) is not int
            or self.head_version < 1
            or type(self.transition_kind) is not ActivityTransition
            or type(self.is_focused) is not bool
            or not _instant(self.created_at)
            or not _instant(self.updated_at)
        ):
            raise CreatorActivityViolation("ACTIVITY-QUERY-ITEM")
        for value in (
            self.progress_summary,
            self.waiting_summary,
            self.terminal_reason,
        ):
            if value is not None and (type(value) is not str or not value):
                raise CreatorActivityViolation("ACTIVITY-QUERY-ITEM")
        waiting = self.status in {ActivityStatus.WAITING, ActivityStatus.PAUSED}
        terminal = self.status in {
            ActivityStatus.COMPLETED,
            ActivityStatus.ABANDONED,
            ActivityStatus.FAILED,
        }
        if waiting != (
            self.waiting_kind is not None and self.waiting_summary is not None
        ):
            raise CreatorActivityViolation("ACTIVITY-QUERY-WAITING")
        if terminal != (self.terminal_reason is not None):
            raise CreatorActivityViolation("ACTIVITY-QUERY-TERMINAL")


@dataclass(frozen=True, slots=True)
class CreatorActivityTimelineItem:
    event_id: UUID
    event_kind: ActivityTimelineKind
    resulting_status: ActivityStatus | None
    summary: str | None
    review_not_before: datetime | None
    occurred_at: datetime

    def __post_init__(self) -> None:
        if (
            not _uuid7(self.event_id)
            or type(self.event_kind) is not str
            or self.event_kind not in _EVENT_KINDS
            or (
                self.resulting_status is not None
                and type(self.resulting_status) is not ActivityStatus
            )
            or (
                self.summary is not None
                and (type(self.summary) is not str or not self.summary)
            )
            or (
                self.review_not_before is not None
                and not _instant(self.review_not_before)
            )
            or not _instant(self.occurred_at)
        ):
            raise CreatorActivityViolation("ACTIVITY-QUERY-TIMELINE")
        decision_only = self.event_kind in {
            "no_action",
            "defer",
            "need_information",
        }
        if decision_only == (self.resulting_status is not None):
            raise CreatorActivityViolation("ACTIVITY-QUERY-TIMELINE")
        if (self.event_kind == "defer") != (self.review_not_before is not None):
            raise CreatorActivityViolation("ACTIVITY-QUERY-TIMELINE")


@dataclass(frozen=True, slots=True)
class CreatorActivityPage:
    items: tuple[CreatorActivityItem, ...]
    truncated: bool

    def __post_init__(self) -> None:
        if (
            type(self.items) is not tuple
            or len(self.items) > 100
            or any(type(item) is not CreatorActivityItem for item in self.items)
            or type(self.truncated) is not bool
        ):
            raise CreatorActivityViolation("ACTIVITY-QUERY-PAGE")


@dataclass(frozen=True, slots=True)
class CreatorActivityTimeline:
    activity_id: UUID
    items: tuple[CreatorActivityTimelineItem, ...]
    truncated: bool

    def __post_init__(self) -> None:
        if (
            not _uuid7(self.activity_id)
            or type(self.items) is not tuple
            or len(self.items) > 100
            or any(type(item) is not CreatorActivityTimelineItem for item in self.items)
            or type(self.truncated) is not bool
        ):
            raise CreatorActivityViolation("ACTIVITY-QUERY-PAGE")


@runtime_checkable
class CreatorActivityQueryPort(Protocol):
    async def list_current(self) -> CreatorActivityPage: ...

    async def timeline(self, activity_id: UUID) -> CreatorActivityTimeline: ...


__all__: tuple[str, ...] = (
    "ACTIVITY_PROJECTION_VERSION",
    "ActivityTimelineKind",
    "CreatorActivityItem",
    "CreatorActivityPage",
    "CreatorActivityQueryPort",
    "CreatorActivityTimeline",
    "CreatorActivityTimelineItem",
    "CreatorActivityViolation",
)
