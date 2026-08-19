"""Public contracts for autonomous opportunities and attention."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Protocol, runtime_checkable
from uuid import UUID

from armi_activity.api import ActivityId
from armi_kernel.contracts import Digest
from armi_runtime_foundation import (
    PostgreSQLAdminTransaction,
    PostgreSQLRuntimeUnitOfWork,
    PostgreSQLTransaction,
)

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


class OpportunityPurpose(StrEnum):
    CONSIDER_CREATOR_INPUT = "consider_creator_input"
    CONSIDER_OTHER_HUMAN_INPUT = "consider_other_human_input"
    CONSIDER_WEB_EVIDENCE = "consider_web_evidence"
    CONSIDER_CODEX_TASK = "consider_codex_task"
    CONSIDER_CODEX_RESULT = "consider_codex_result"
    CONSIDER_VISUAL_OBSERVATION = "consider_visual_observation"


@dataclass(frozen=True, slots=True)
class ExternalEvidenceOpportunityDraft:
    evidence_id: UUID
    subject_id: UUID
    scene_id: UUID | None
    context_party_id: UUID | None
    purpose: OpportunityPurpose

    def __post_init__(self) -> None:
        required = [self.evidence_id, self.subject_id]
        optional = [self.scene_id, self.context_party_id]
        if any(
            type(value) is not UUID or value.version != 7 for value in required
        ) or any(
            value is not None and (type(value) is not UUID or value.version != 7)
            for value in optional
        ):
            raise LifeViolation("LIFE-ADMISSION-ID")
        if type(self.purpose) is not OpportunityPurpose:
            raise LifeViolation("LIFE-ADMISSION-PURPOSE")
        visual = self.purpose is OpportunityPurpose.CONSIDER_VISUAL_OBSERVATION
        if visual != (self.scene_id is None and self.context_party_id is None):
            raise LifeViolation("LIFE-ADMISSION-PURPOSE")


@dataclass(frozen=True, slots=True)
class LifeQueryResultOpportunityDraft:
    opportunity_id: UUID
    intent_id: UUID
    subject_id: UUID
    scene_id: UUID
    creator_party_id: UUID
    source_opportunity_id: UUID

    def __post_init__(self) -> None:
        if any(
            type(value) is not UUID or value.version != 7
            for value in (
                self.opportunity_id,
                self.intent_id,
                self.subject_id,
                self.scene_id,
                self.creator_party_id,
                self.source_opportunity_id,
            )
        ):
            raise LifeViolation("LIFE-ADMISSION-ID")


@dataclass(frozen=True, slots=True)
class OpportunityId:
    value: UUID

    def __post_init__(self) -> None:
        if type(self.value) is not UUID or self.value.version != 7:
            raise LifeViolation("LIFE-OPPORTUNITY-ID")

    def __str__(self) -> str:
        return str(self.value)


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
class LifeGenerationFacts:
    generation_no: int
    activation_reason: str
    created_at: datetime


@dataclass(frozen=True, slots=True)
class AttentionRetryFacts:
    failed_ready: bool
    need_information_at: datetime | None
    creator_input_after_need: bool


@dataclass(frozen=True, slots=True)
class CreatorOutreachFacts:
    scene_id: UUID
    creator_party_id: UUID
    latest_input_id: UUID | None
    latest_input_at: datetime | None
    generation_id: UUID
    generation_no: int
    generation_created_at: datetime
    now: datetime
    awaiting_creator: bool
    last_cognition_at: datetime | None
    last_timeline_at: datetime | None


@runtime_checkable
class LifeOpportunityFactsPort(Protocol):
    async def generation(
        self, unit_of_work: PostgreSQLRuntimeUnitOfWork
    ) -> LifeGenerationFacts: ...

    async def active_cognition_count(
        self, transaction: PostgreSQLTransaction, *, subject_id: UUID
    ) -> int: ...

    async def attention_retry(
        self,
        transaction: PostgreSQLTransaction,
        *,
        subject_id: UUID,
        root_opportunity_id: UUID,
        resolved_at: datetime | None,
    ) -> AttentionRetryFacts: ...

    async def outreach(
        self,
        unit_of_work: PostgreSQLRuntimeUnitOfWork,
    ) -> CreatorOutreachFacts | None: ...


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


@dataclass(frozen=True, slots=True)
class OpportunityCommitSnapshot:
    opportunity_id: UUID
    root_opportunity_id: UUID
    reconsideration_no: int
    evidence_id: UUID | None
    subject_id: UUID
    scene_id: UUID | None
    context_party_id: UUID | None
    purpose: str
    source_kind: str
    source_ref: UUID
    source_version: int
    activity_id: UUID | None
    available_after: datetime
    expires_at: datetime | None


@dataclass(frozen=True, slots=True)
class OpportunityOperationSnapshot:
    root_opportunity_id: UUID
    current_opportunity_id: UUID
    evidence_id: UUID
    subject_id: UUID
    scene_id: UUID
    context_party_id: UUID
    purpose: str
    disposition: str
    reconsideration_no: int


@dataclass(frozen=True, slots=True)
class OpportunitySelectionCursor:
    available_after: datetime
    opportunity_id: UUID


@dataclass(frozen=True, slots=True)
class OpportunityCognitionSelectionScope:
    subject_id: UUID
    maintenance_source_ref: UUID | None = None
    maintenance_source_version: int | None = None
    maintenance_purpose: str | None = None


@dataclass(frozen=True, slots=True)
class OpportunityCognitionCandidate:
    opportunity_id: UUID
    root_opportunity_id: UUID
    evidence_id: UUID | None
    subject_id: UUID
    scene_id: UUID | None
    context_party_id: UUID | None
    purpose: str
    source_kind: str
    source_ref: UUID
    source_version: int
    available_after: datetime
    expires_at: datetime | None
    activity_id: UUID | None


@runtime_checkable
class OpportunityCognitionSelectionPort(Protocol):
    async def next_candidate(
        self,
        transaction: PostgreSQLTransaction,
        *,
        scope: OpportunityCognitionSelectionScope,
        after: OpportunitySelectionCursor | None = None,
    ) -> OpportunityCognitionCandidate | None: ...

    async def select_for_cognition(
        self,
        transaction: PostgreSQLTransaction,
        *,
        opportunity_id: UUID,
    ) -> bool: ...

    async def resolve_cognition_failure(
        self,
        transaction: PostgreSQLTransaction,
        *,
        opportunity_id: UUID,
    ) -> bool: ...


@runtime_checkable
class OpportunityContextReadPort(Protocol):
    async def context_snapshot(
        self,
        transaction: PostgreSQLTransaction,
        *,
        opportunity_id: UUID,
    ) -> OpportunityCognitionCandidate: ...


@runtime_checkable
class OpportunityCognitionPort(
    OpportunityCognitionSelectionPort,
    OpportunityContextReadPort,
    Protocol,
): ...


@runtime_checkable
class OpportunityOperationReadPort(Protocol):
    async def operation_snapshot(
        self,
        transaction: PostgreSQLTransaction,
        *,
        root_opportunity_id: UUID,
        context_party_id: UUID,
    ) -> OpportunityOperationSnapshot | None: ...


@runtime_checkable
class OpportunityWakeupPort(Protocol):
    def notify(self, channel: str) -> None: ...


@runtime_checkable
class LifeOpportunitySourcePort(Protocol):
    async def admit_once(self) -> OpportunityAdmissionOutcome:
        """Admit at most one source-backed autonomous opportunity."""
        ...


@runtime_checkable
class OpportunityAdmissionPort(Protocol):
    async def admit_life_query_result(
        self,
        transaction: PostgreSQLTransaction,
        draft: LifeQueryResultOpportunityDraft,
    ) -> OpportunityId: ...

    async def admit_external_evidence(
        self,
        transaction: PostgreSQLTransaction,
        draft: ExternalEvidenceOpportunityDraft,
    ) -> OpportunityAdmissionOutcome: ...

    async def find_external_evidence(
        self,
        transaction: PostgreSQLTransaction,
        *,
        evidence_id: UUID,
        purpose: OpportunityPurpose,
    ) -> OpportunityId | None: ...


@runtime_checkable
class OpportunityTransitionPort(Protocol):
    async def subject_commit_snapshot(
        self, transaction: PostgreSQLTransaction, *, opportunity_id: UUID
    ) -> OpportunityCommitSnapshot: ...

    async def resolve_subject_commit(
        self,
        transaction: PostgreSQLTransaction,
        *,
        opportunity_id: UUID,
        disposition: str = "resolved",
    ) -> None: ...

    async def supersede_subject_commit(
        self, transaction: PostgreSQLTransaction, *, opportunity_id: UUID
    ) -> OpportunityId | None: ...

    async def reconsider_activity(
        self,
        transaction: PostgreSQLTransaction,
        *,
        subject_id: UUID,
        root_opportunity_id: UUID,
        predecessor_opportunity_id: UUID,
        source_ref: UUID,
        source_version: int,
        activity_id: UUID,
    ) -> OpportunityId | None: ...

    async def reconsider_sleep(
        self,
        transaction: PostgreSQLTransaction,
        *,
        predecessor_opportunity_id: UUID,
    ) -> OpportunityId | None: ...


@runtime_checkable
class OpportunityOwnerPort(
    OpportunityAdmissionPort,
    OpportunityCognitionPort,
    OpportunityOperationReadPort,
    OpportunityTransitionPort,
    Protocol,
):
    """Complete owner surface implemented by the single active repository."""


@runtime_checkable
@runtime_checkable
class OpportunityRuntimePort(LifeOpportunitySourcePort, Protocol):
    async def open(self) -> None: ...

    async def close(self) -> None: ...

    def stop(self) -> None: ...

    async def run(self) -> None: ...

    async def maintain_sleep_once(self) -> OpportunityAdmissionOutcome: ...

    async def admit_life_material_once(self) -> OpportunityAdmissionOutcome: ...

    async def admit_creator_outreach_once(self) -> OpportunityAdmissionOutcome: ...

    async def admit_attention_once(self) -> OpportunityAdmissionOutcome: ...

    async def admit_internal_work_once(self) -> OpportunityAdmissionOutcome: ...

    async def request_emergency_wake(
        self,
        session_id: UUID,
        request_id: UUID,
    ) -> UUID: ...


def require_life_token(value: str) -> None:
    if type(value) is not str or _TOKEN.fullmatch(value) is None:
        raise LifeViolation("LIFE-TOKEN")


@dataclass(frozen=True, slots=True)
class OpportunityAdminSnapshot:
    opportunity_id: UUID
    evidence_id: UUID
    disposition: str


@runtime_checkable
class OpportunityAdminPort(Protocol):
    def snapshot_for_evidence(
        self, transaction: PostgreSQLAdminTransaction, *, evidence_id: UUID
    ) -> OpportunityAdminSnapshot | None: ...

    def delete_open(
        self, transaction: PostgreSQLAdminTransaction, *, opportunity_id: UUID
    ) -> bool: ...

    def inspect_ids(
        self, transaction: PostgreSQLAdminTransaction, *, object_ids: tuple[UUID, ...]
    ) -> tuple[UUID, ...]: ...


__all__ = (
    "AttentionRetryFacts",
    "CreatorOutreachFacts",
    "CreatorOutreachPolicy",
    "ExternalEvidenceOpportunityDraft",
    "LifeGenerationFacts",
    "LifeOpportunityFactsPort",
    "LifeOpportunitySourceKind",
    "LifeOpportunitySourcePort",
    "LifeOpportunitySourceSnapshot",
    "LifeQueryResultOpportunityDraft",
    "LifeViolation",
    "OpportunityAdminPort",
    "OpportunityAdminSnapshot",
    "OpportunityAdmissionOutcome",
    "OpportunityAdmissionPort",
    "OpportunityAdmissionStatus",
    "OpportunityCognitionCandidate",
    "OpportunityCognitionPort",
    "OpportunityCognitionSelectionPort",
    "OpportunityCognitionSelectionScope",
    "OpportunityCommitSnapshot",
    "OpportunityContextReadPort",
    "OpportunityId",
    "OpportunityOperationReadPort",
    "OpportunityOperationSnapshot",
    "OpportunityOwnerPort",
    "OpportunityPurpose",
    "OpportunityRuntimePort",
    "OpportunitySelectionCursor",
    "OpportunityTransitionPort",
    "OpportunityWakeupPort",
)
