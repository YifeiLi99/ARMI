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
    CREATOR_OUTREACH_ABSENCE = "creator_outreach_absence"
    CREATOR_OUTREACH_ACTIVITY = "creator_outreach_activity"
    CREATOR_OUTREACH_RELATIONSHIP = "creator_outreach_relationship"


class OpportunityAdmissionStatus(StrEnum):
    ADMITTED = "admitted"
    DUPLICATE = "duplicate"
    REJECTED = "rejected"


@dataclass(frozen=True, slots=True)
class CreatorOutreachPolicy:
    """Frozen frequency boundaries for considering proactive Creator contact."""

    absence_after_seconds: int
    minimum_interval_seconds: int

    def __post_init__(self) -> None:
        if (
            type(self.absence_after_seconds) is not int
            or self.absence_after_seconds < 3_600
            or type(self.minimum_interval_seconds) is not int
            or self.minimum_interval_seconds < 3_600
        ):
            raise LifeViolation("LIFE-OUTREACH-POLICY")


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
        activity_source = self.kind in {
            LifeOpportunitySourceKind.ACTIVITY_REVISION,
            LifeOpportunitySourceKind.CREATOR_OUTREACH_ACTIVITY,
        }
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
    "CreatorOutreachPolicy",
    "LifeOpportunitySourceKind",
    "LifeOpportunitySourcePort",
    "LifeOpportunitySourceSnapshot",
    "LifeViolation",
    "OpportunityAdmissionOutcome",
    "OpportunityAdmissionStatus",
)
