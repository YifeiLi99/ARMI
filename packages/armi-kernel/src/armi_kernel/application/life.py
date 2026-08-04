"""Technology-neutral autonomous opportunity and Activity contracts."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Protocol, runtime_checkable
from uuid import UUID

from armi_kernel.contracts import ActivityId, Digest

_TOKEN = re.compile(r"^[a-z][a-z0-9._-]{0,63}$", re.ASCII)
_CODE = re.compile(r"^(?:LIFE|ACTIVITY)-[A-Z0-9-]+$", re.ASCII)


class LifeViolation(RuntimeError):
    __slots__ = ("code",)

    def __init__(self, code: str) -> None:
        if type(code) is not str or _CODE.fullmatch(code) is None:
            raise ValueError("life violation code is invalid")
        self.code = code
        super().__init__("autonomous life operation failed")

    def __str__(self) -> str:
        return f"{self.code}: autonomous life operation failed"


class LifeOpportunitySourceKind(StrEnum):
    EXTERNAL_EVIDENCE = "external_evidence"
    LIFE_GENERATION_AVAILABLE = "life_generation_available"
    SUBJECT_COMPONENT_REVISION = "subject_component_revision"
    ACTIVITY_REVISION = "activity_revision"
    MAINTENANCE_WINDOW = "maintenance_window"


class OpportunityAdmissionStatus(StrEnum):
    ADMITTED = "admitted"
    DUPLICATE = "duplicate"
    REJECTED = "rejected"


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


class LifeSchedulingDisposition(StrEnum):
    ADMIT = "admit"
    DEFER = "defer"
    BACKPRESSURE = "backpressure"
    IDLE = "idle"


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
            or type(self.revision_id) is not UUID
            or self.revision_id.version != 7
            or type(self.revision_no) is not int
            or self.revision_no <= 0
            or type(self.status) is not ActivityStatus
            or type(self.created_at) is not datetime
            or self.created_at.tzinfo is None
            or (
                self.last_considered_at is not None
                and (
                    type(self.last_considered_at) is not datetime
                    or self.last_considered_at.tzinfo is None
                )
            )
            or (
                self.resume_not_before is not None
                and (
                    type(self.resume_not_before) is not datetime
                    or self.resume_not_before.tzinfo is None
                )
            )
            or type(self.waiting_signal_available) is not bool
        ):
            raise LifeViolation("LIFE-SCHEDULER-SNAPSHOT")


@dataclass(frozen=True, slots=True)
class LifeSchedulingSnapshot:
    now: datetime
    activities: tuple[ActivityHeadSnapshot, ...]
    active_activity_ids: tuple[ActivityId, ...]
    unresolved_attention: bool
    model_concurrency: int
    model_in_flight: int

    def __post_init__(self) -> None:
        if (
            type(self.now) is not datetime
            or self.now.tzinfo is None
            or type(self.activities) is not tuple
            or type(self.active_activity_ids) is not tuple
            or len(self.active_activity_ids) > 1
            or any(type(item) is not ActivityId for item in self.active_activity_ids)
            or type(self.unresolved_attention) is not bool
            or type(self.model_concurrency) is not int
            or self.model_concurrency < 1
            or type(self.model_in_flight) is not int
            or not 0 <= self.model_in_flight <= self.model_concurrency
        ):
            raise LifeViolation("LIFE-SCHEDULER-SNAPSHOT")


@dataclass(frozen=True, slots=True)
class LifeSchedulingDecision:
    disposition: LifeSchedulingDisposition
    activity_revision_id: UUID | None
    available_after: datetime | None
    reason_code: str | None

    def __post_init__(self) -> None:
        admitted = self.disposition is LifeSchedulingDisposition.ADMIT
        if admitted != (self.activity_revision_id is not None):
            raise LifeViolation("LIFE-SCHEDULER-DECISION")
        if self.activity_revision_id is not None and (
            type(self.activity_revision_id) is not UUID
            or self.activity_revision_id.version != 7
        ):
            raise LifeViolation("LIFE-SCHEDULER-DECISION")
        if self.available_after is not None and (
            type(self.available_after) is not datetime
            or self.available_after.tzinfo is None
        ):
            raise LifeViolation("LIFE-SCHEDULER-DECISION")
        if self.reason_code is not None and (
            type(self.reason_code) is not str
            or not self.reason_code.startswith("LIFE-")
        ):
            raise LifeViolation("LIFE-SCHEDULER-DECISION")


@runtime_checkable
class LifeScheduler(Protocol):
    def select(self, snapshot: LifeSchedulingSnapshot) -> LifeSchedulingDecision:
        """Select one frozen Activity head without mutating authority."""
        ...


@dataclass(frozen=True, slots=True)
class LifeOpportunitySourceSnapshot:
    subject_id: UUID
    generation_id: UUID
    kind: LifeOpportunitySourceKind
    reference: UUID
    version: int
    digest: Digest
    available_after: datetime
    expires_at: datetime | None = None
    activity_id: ActivityId | None = None

    def __post_init__(self) -> None:
        if any(
            type(value) is not UUID or value.version != 7
            for value in (self.subject_id, self.generation_id, self.reference)
        ):
            raise LifeViolation("LIFE-SOURCE-ID")
        if (
            type(self.kind) is not LifeOpportunitySourceKind
            or type(self.version) is not int
            or self.version <= 0
            or type(self.digest) is not Digest
            or type(self.available_after) is not datetime
            or self.available_after.tzinfo is None
            or (
                self.expires_at is not None
                and (
                    type(self.expires_at) is not datetime
                    or self.expires_at.tzinfo is None
                    or self.expires_at <= self.available_after
                )
            )
        ):
            raise LifeViolation("LIFE-SOURCE")
        activity_source = self.kind is LifeOpportunitySourceKind.ACTIVITY_REVISION
        if activity_source != (self.activity_id is not None):
            raise LifeViolation("LIFE-SOURCE-ACTIVITY")


@dataclass(frozen=True, slots=True)
class OpportunityAdmissionOutcome:
    status: OpportunityAdmissionStatus
    opportunity_id: UUID | None
    reason_code: str | None = None

    def __post_init__(self) -> None:
        if type(self.status) is not OpportunityAdmissionStatus:
            raise LifeViolation("LIFE-ADMISSION")
        rejected = self.status is OpportunityAdmissionStatus.REJECTED
        if rejected != (self.opportunity_id is None):
            raise LifeViolation("LIFE-ADMISSION")
        if rejected:
            if (
                type(self.reason_code) is not str
                or _CODE.fullmatch(self.reason_code) is None
            ):
                raise LifeViolation("LIFE-ADMISSION")
        elif self.reason_code is not None:
            raise LifeViolation("LIFE-ADMISSION")
        if self.opportunity_id is not None and (
            type(self.opportunity_id) is not UUID or self.opportunity_id.version != 7
        ):
            raise LifeViolation("LIFE-ADMISSION")


@runtime_checkable
class LifeOpportunitySourcePort(Protocol):
    async def admit_once(self) -> OpportunityAdmissionOutcome:
        """Admit at most one source-backed autonomous opportunity."""
        ...


def require_life_token(value: str) -> None:
    if type(value) is not str or _TOKEN.fullmatch(value) is None:
        raise LifeViolation("LIFE-TOKEN")


__all__ = (
    "ActivityAttentionDecisionKind",
    "ActivityHeadSnapshot",
    "ActivityStatus",
    "ActivityTransition",
    "ActivityWaitingKind",
    "LifeOpportunitySourceKind",
    "LifeOpportunitySourcePort",
    "LifeOpportunitySourceSnapshot",
    "LifeScheduler",
    "LifeSchedulingDecision",
    "LifeSchedulingDisposition",
    "LifeSchedulingSnapshot",
    "LifeViolation",
    "OpportunityAdmissionOutcome",
    "OpportunityAdmissionStatus",
)
