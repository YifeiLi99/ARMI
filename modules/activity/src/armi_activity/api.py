"""Public contracts for the autonomous Activity owner."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Final, Literal, Protocol, runtime_checkable
from uuid import UUID

from armi_kernel.application import CandidateFactClass, CandidateOwnerDraft
from armi_runtime_foundation import PostgreSQLTransaction

from ._domain import (
    ActivityAttentionDecisionKind,
    ActivitySchedulingDisposition,
    ActivityStatus,
    ActivityTransition,
    ActivityWaitingKind,
    select_activity,
)

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
_REF = re.compile(r"^proposal:[1-9][0-9]{0,2}$", re.ASCII)
_GROUP = re.compile(r"^group:[1-9][0-9]{0,2}$", re.ASCII)


class ActivityViolation(RuntimeError):
    __slots__ = ("code",)

    def __init__(self, code: str) -> None:
        if type(code) is not str or not code.startswith("ACTIVITY-"):
            raise ValueError("Activity violation code is invalid")
        self.code = code
        super().__init__("Activity operation failed")

    def __str__(self) -> str:
        return f"{self.code}: Activity operation failed"


def _uuid7(value: object) -> bool:
    return type(value) is UUID and value.version == 7


@dataclass(frozen=True, slots=True)
class ActivityId:
    value: UUID

    def __post_init__(self) -> None:
        if not _uuid7(self.value):
            raise ActivityViolation("ACTIVITY-ID")


def _instant(value: object) -> bool:
    return type(value) is datetime and value.tzinfo is not None


def _optional_text(value: str | None, maximum: int) -> bool:
    return value is None or (type(value) is str and 1 <= len(value) <= maximum)


def _proposal(
    proposal_ref: str, atomic_group_ref: str, basis_ordinals: tuple[int, ...]
) -> None:
    if (
        type(proposal_ref) is not str
        or _REF.fullmatch(proposal_ref) is None
        or type(atomic_group_ref) is not str
        or _GROUP.fullmatch(atomic_group_ref) is None
        or type(basis_ordinals) is not tuple
        or not basis_ordinals
        or len(basis_ordinals) > 8
        or any(
            type(value) is not int or not 1 <= value <= 999 for value in basis_ordinals
        )
        or len(set(basis_ordinals)) != len(basis_ordinals)
    ):
        raise ActivityViolation("ACTIVITY-CANDIDATE-PROPOSAL")


@dataclass(frozen=True, slots=True)
class CandidateActivityDraft:
    proposal_ref: str
    atomic_group_ref: str
    basis_ordinals: tuple[int, ...]
    fact_class: CandidateFactClass
    activity_id: UUID
    goal: str
    next_safe_step: str
    status: ActivityStatus = ActivityStatus.READY
    activity_kind: str = "self_directed"
    privacy_scope: str = "private"

    def __post_init__(self) -> None:
        _proposal(self.proposal_ref, self.atomic_group_ref, self.basis_ordinals)
        if (
            type(self.fact_class) is not CandidateFactClass
            or not _uuid7(self.activity_id)
            or type(self.goal) is not str
            or not 1 <= len(self.goal) <= 2048
            or type(self.next_safe_step) is not str
            or not 1 <= len(self.next_safe_step) <= 1024
            or self.status is not ActivityStatus.READY
            or self.activity_kind != "self_directed"
            or self.privacy_scope != "private"
        ):
            raise ActivityViolation("ACTIVITY-CANDIDATE-CREATE")


@dataclass(frozen=True, slots=True)
class CandidateActivityDecisionDraft:
    proposal_ref: str
    atomic_group_ref: str
    basis_ordinals: tuple[int, ...]
    activity_id: UUID
    current_revision_id: UUID
    expected_head_version: int
    decision_kind: ActivityAttentionDecisionKind
    progress_summary: str | None = None
    next_safe_step: str | None = None
    waiting_summary: str | None = None
    resumption_cue: str | None = None
    waiting_kind: ActivityWaitingKind | None = None
    delay_seconds: int | None = None
    terminal_reason: str | None = None

    def __post_init__(self) -> None:
        _proposal(self.proposal_ref, self.atomic_group_ref, self.basis_ordinals)
        if (
            not _uuid7(self.activity_id)
            or not _uuid7(self.current_revision_id)
            or type(self.expected_head_version) is not int
            or self.expected_head_version <= 0
            or type(self.decision_kind) is not ActivityAttentionDecisionKind
            or not _optional_text(self.progress_summary, 2048)
            or not _optional_text(self.next_safe_step, 1024)
            or not _optional_text(self.waiting_summary, 2048)
            or not _optional_text(self.resumption_cue, 2048)
            or not _optional_text(self.terminal_reason, 1024)
            or (
                self.delay_seconds is not None
                and (
                    type(self.delay_seconds) is not int
                    or not 1 <= self.delay_seconds <= 86400
                )
            )
        ):
            raise ActivityViolation("ACTIVITY-CANDIDATE-DECISION")
        kind = self.decision_kind
        simple = {
            ActivityAttentionDecisionKind.ENGAGE,
            ActivityAttentionDecisionKind.RESUME,
            ActivityAttentionDecisionKind.NO_ACTION,
            ActivityAttentionDecisionKind.DEFER,
            ActivityAttentionDecisionKind.NEED_INFORMATION,
        }
        optional = (
            self.progress_summary,
            self.next_safe_step,
            self.waiting_summary,
            self.resumption_cue,
            self.waiting_kind,
            self.delay_seconds,
            self.terminal_reason,
        )
        if kind in simple and any(value is not None for value in optional):
            raise ActivityViolation("ACTIVITY-CANDIDATE-DECISION-SHAPE")
        if kind is ActivityAttentionDecisionKind.PROGRESS and not (
            self.progress_summary is not None
            and self.next_safe_step is not None
            and all(
                value is None
                for value in (
                    self.waiting_summary,
                    self.resumption_cue,
                    self.waiting_kind,
                    self.delay_seconds,
                    self.terminal_reason,
                )
            )
        ):
            raise ActivityViolation("ACTIVITY-CANDIDATE-DECISION-SHAPE")
        if kind in {
            ActivityAttentionDecisionKind.WAIT,
            ActivityAttentionDecisionKind.PAUSE,
        } and not (
            self.progress_summary is not None
            and self.next_safe_step is not None
            and self.waiting_summary is not None
            and self.resumption_cue is not None
            and self.waiting_kind is not None
            and self.terminal_reason is None
        ):
            raise ActivityViolation("ACTIVITY-CANDIDATE-DECISION-SHAPE")
        if kind is ActivityAttentionDecisionKind.WAIT and (
            self.waiting_kind
            not in {
                ActivityWaitingKind.TIME,
                ActivityWaitingKind.CREATOR_INPUT,
                ActivityWaitingKind.EXTERNAL_EVIDENCE,
            }
            or (
                (self.waiting_kind is ActivityWaitingKind.TIME)
                != (self.delay_seconds is not None)
            )
        ):
            raise ActivityViolation("ACTIVITY-CANDIDATE-DECISION-SHAPE")
        if kind is ActivityAttentionDecisionKind.PAUSE and (
            self.waiting_kind is not ActivityWaitingKind.SCHEDULED_REVIEW
            or self.delay_seconds is None
        ):
            raise ActivityViolation("ACTIVITY-CANDIDATE-DECISION-SHAPE")
        if kind in {
            ActivityAttentionDecisionKind.COMPLETE,
            ActivityAttentionDecisionKind.ABANDON,
        } and not (
            self.progress_summary is not None
            and self.terminal_reason is not None
            and all(
                value is None
                for value in (
                    self.next_safe_step,
                    self.waiting_summary,
                    self.resumption_cue,
                    self.waiting_kind,
                    self.delay_seconds,
                )
            )
        ):
            raise ActivityViolation("ACTIVITY-CANDIDATE-DECISION-SHAPE")


@dataclass(frozen=True, slots=True)
class ActivityCandidateSnapshot:
    activity_id: UUID
    current_revision_id: UUID
    head_version: int
    status: ActivityStatus


@dataclass(frozen=True, slots=True)
class ActivityWorkHead:
    activity_id: UUID
    revision_id: UUID
    revision_no: int


@dataclass(frozen=True, slots=True)
class ActivityOutreachSource:
    revision_id: UUID
    head_version: int
    activity_id: UUID
    occurred_at: datetime


@dataclass(frozen=True, slots=True)
class ActivityLifeRecordItem:
    activity_id: UUID
    summary: str
    occurred_at: datetime


@dataclass(frozen=True, slots=True)
class ActivityAttentionRootState:
    opportunity_id: UUID
    disposition: str
    retry_ready: bool
    successor_id: UUID | None


@dataclass(frozen=True, slots=True)
class ActivityCommitContext:
    validation_id: UUID
    episode_id: UUID
    opportunity_id: UUID
    root_opportunity_id: UUID
    reconsideration_no: int
    subject_id: UUID
    scene_id: UUID | None
    opportunity_purpose: str
    source_ref: UUID
    source_version: int
    source_activity_id: UUID | None


@dataclass(frozen=True, slots=True)
class ActivityCommitResult:
    result_revision_id: UUID | None
    focus_activity_id: UUID | None
    focus_proposal_ref: str | None
    update_focus: bool


@dataclass(frozen=True, slots=True)
class ActivityHeadSnapshot:
    activity_id: ActivityId
    revision_id: UUID
    revision_no: int
    status: ActivityStatus
    created_at: datetime
    last_considered_at: datetime | None
    waiting_kind: ActivityWaitingKind | None = None
    resume_not_before: datetime | None = None
    waiting_signal_available: bool = False

    def __post_init__(self) -> None:
        if (
            type(self.activity_id) is not ActivityId
            or not _uuid7(self.revision_id)
            or type(self.revision_no) is not int
            or self.revision_no <= 0
            or type(self.status) is not ActivityStatus
            or not _instant(self.created_at)
            or (
                self.last_considered_at is not None
                and not _instant(self.last_considered_at)
            )
            or (
                self.resume_not_before is not None
                and not _instant(self.resume_not_before)
            )
            or type(self.waiting_signal_available) is not bool
        ):
            raise ActivityViolation("ACTIVITY-SCHEDULER-SNAPSHOT")


@dataclass(frozen=True, slots=True)
class ActivitySchedulingSnapshot:
    now: datetime
    activities: tuple[ActivityHeadSnapshot, ...]
    active_activity_ids: tuple[ActivityId, ...]
    unresolved_attention: bool
    model_concurrency: int
    model_in_flight: int

    def __post_init__(self) -> None:
        if (
            not _instant(self.now)
            or type(self.activities) is not tuple
            or any(type(item) is not ActivityHeadSnapshot for item in self.activities)
            or type(self.active_activity_ids) is not tuple
            or len(self.active_activity_ids) > 1
            or any(type(item) is not ActivityId for item in self.active_activity_ids)
            or type(self.unresolved_attention) is not bool
            or type(self.model_concurrency) is not int
            or self.model_concurrency < 1
            or type(self.model_in_flight) is not int
            or self.model_in_flight < 0
        ):
            raise ActivityViolation("ACTIVITY-SCHEDULER-SNAPSHOT")


@dataclass(frozen=True, slots=True)
class ActivitySchedulingDecision:
    disposition: ActivitySchedulingDisposition
    activity_revision_id: UUID | None
    available_after: datetime | None
    reason_code: str | None

    def __post_init__(self) -> None:
        admitted = self.disposition is ActivitySchedulingDisposition.ADMIT
        if admitted != (self.activity_revision_id is not None):
            raise ActivityViolation("ACTIVITY-SCHEDULER-DECISION")
        if self.activity_revision_id is not None and not _uuid7(
            self.activity_revision_id
        ):
            raise ActivityViolation("ACTIVITY-SCHEDULER-DECISION")
        if self.available_after is not None and not _instant(self.available_after):
            raise ActivityViolation("ACTIVITY-SCHEDULER-DECISION")
        if self.reason_code is not None and (
            type(self.reason_code) is not str
            or not self.reason_code.startswith("LIFE-")
        ):
            raise ActivityViolation("ACTIVITY-SCHEDULER-DECISION")


class ActivityScheduler:
    __slots__ = ()

    def select(
        self, snapshot: ActivitySchedulingSnapshot
    ) -> ActivitySchedulingDecision:
        return select_activity(snapshot)  # type: ignore[return-value]


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
            raise ActivityViolation("ACTIVITY-QUERY-ITEM")
        for value in (
            self.progress_summary,
            self.waiting_summary,
            self.terminal_reason,
        ):
            if value is not None and (type(value) is not str or not value):
                raise ActivityViolation("ACTIVITY-QUERY-ITEM")
        waiting = self.status in {ActivityStatus.WAITING, ActivityStatus.PAUSED}
        terminal = self.status in {
            ActivityStatus.COMPLETED,
            ActivityStatus.ABANDONED,
            ActivityStatus.FAILED,
        }
        if waiting != (
            self.waiting_kind is not None and self.waiting_summary is not None
        ):
            raise ActivityViolation("ACTIVITY-QUERY-WAITING")
        if terminal != (self.terminal_reason is not None):
            raise ActivityViolation("ACTIVITY-QUERY-TERMINAL")


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
            raise ActivityViolation("ACTIVITY-QUERY-TIMELINE")
        decision_only = self.event_kind in {"no_action", "defer", "need_information"}
        if decision_only == (self.resulting_status is not None) or (
            (self.event_kind == "defer") != (self.review_not_before is not None)
        ):
            raise ActivityViolation("ACTIVITY-QUERY-TIMELINE")


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
            raise ActivityViolation("ACTIVITY-QUERY-PAGE")


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
            raise ActivityViolation("ACTIVITY-QUERY-PAGE")


@runtime_checkable
class ActivityFocusReadPort(Protocol):
    async def active_activity_ids(
        self, transaction: PostgreSQLTransaction, *, subject_id: UUID
    ) -> tuple[UUID, ...]: ...


@runtime_checkable
class ActivityReadPort(Protocol):
    async def list_current(self) -> CreatorActivityPage: ...
    async def timeline(self, activity_id: UUID) -> CreatorActivityTimeline: ...
    async def candidate_head(
        self, transaction: PostgreSQLTransaction, *, episode_id: UUID
    ) -> ActivityCandidateSnapshot | None: ...
    async def context_summary(
        self, transaction: PostgreSQLTransaction, *, subject_id: UUID, enabled: bool
    ) -> bytes: ...
    async def scheduling_heads(
        self, transaction: PostgreSQLTransaction, *, subject_id: UUID
    ) -> tuple[ActivityHeadSnapshot, ...]: ...
    async def focused_work_head(
        self, transaction: PostgreSQLTransaction, *, subject_id: UUID, activity_id: UUID
    ) -> ActivityWorkHead | None: ...
    async def completed_outreach_source(
        self, transaction: PostgreSQLTransaction, *, subject_id: UUID, after: datetime
    ) -> ActivityOutreachSource | None: ...
    async def life_record_branch(
        self,
        transaction: PostgreSQLTransaction,
        *,
        subject_id: UUID,
        query_text: str | None,
        before: tuple[datetime, str, UUID] | None,
        limit: int,
    ) -> tuple[ActivityLifeRecordItem, ...]: ...
    async def attention_root_state(
        self,
        transaction: PostgreSQLTransaction,
        *,
        subject_id: UUID,
        revision_id: UUID,
        revision_no: int,
    ) -> ActivityAttentionRootState | None: ...


@runtime_checkable
class ActivityCognitionPort(Protocol):
    def bind_create(self, value: CandidateActivityDraft) -> CandidateOwnerDraft: ...
    def bind_decision(
        self, value: CandidateActivityDecisionDraft
    ) -> CandidateOwnerDraft: ...
    def decode(
        self, payload: bytes
    ) -> CandidateActivityDraft | CandidateActivityDecisionDraft: ...
    def bind_wire(self, value: object, *, decision: bool) -> CandidateOwnerDraft: ...


@runtime_checkable
class ActivityCommitPort(Protocol):
    async def heads_match(
        self,
        transaction: PostgreSQLTransaction,
        *,
        context: ActivityCommitContext,
        drafts: tuple[CandidateOwnerDraft, ...],
    ) -> bool: ...

    def requests_reconsideration(
        self,
        *,
        context: ActivityCommitContext,
        drafts: tuple[CandidateOwnerDraft, ...],
    ) -> bool: ...

    async def commit(
        self,
        transaction: PostgreSQLTransaction,
        *,
        context: ActivityCommitContext,
        commit_id: UUID,
        drafts: tuple[CandidateOwnerDraft, ...],
    ) -> ActivityCommitResult: ...

    async def record_decision(
        self,
        transaction: PostgreSQLTransaction,
        *,
        context: ActivityCommitContext,
        application_id: UUID,
        drafts: tuple[CandidateOwnerDraft, ...],
        result_revision_id: UUID | None,
        output_material_ids: tuple[UUID, ...] = (),
    ) -> None: ...

    async def affected_activity_ids(
        self, transaction: PostgreSQLTransaction, validation_id: UUID
    ) -> tuple[UUID, ...]: ...


__all__ = (
    "ACTIVITY_PROJECTION_VERSION",
    "ActivityAttentionDecisionKind",
    "ActivityAttentionRootState",
    "ActivityCandidateSnapshot",
    "ActivityCognitionPort",
    "ActivityCommitContext",
    "ActivityCommitPort",
    "ActivityCommitResult",
    "ActivityFocusReadPort",
    "ActivityHeadSnapshot",
    "ActivityId",
    "ActivityLifeRecordItem",
    "ActivityOutreachSource",
    "ActivityReadPort",
    "ActivityScheduler",
    "ActivitySchedulingDecision",
    "ActivitySchedulingDisposition",
    "ActivitySchedulingSnapshot",
    "ActivityStatus",
    "ActivityTimelineKind",
    "ActivityTransition",
    "ActivityViolation",
    "ActivityWaitingKind",
    "ActivityWorkHead",
    "CandidateActivityDecisionDraft",
    "CandidateActivityDraft",
    "CreatorActivityItem",
    "CreatorActivityPage",
    "CreatorActivityTimeline",
    "CreatorActivityTimelineItem",
)
