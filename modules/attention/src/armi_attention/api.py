"""Public contracts for autonomous opportunities and attention."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Protocol, runtime_checkable
from uuid import UUID

from armi_kernel.application import COGNITION_PURPOSES, CognitionPurpose
from armi_runtime_foundation import (
    PostgreSQLAdminTransaction,
    PostgreSQLRuntimeUnitOfWork,
    PostgreSQLTransaction,
)

from ._autonomy_policy import AutonomyPolicy, quota_day, quota_reset_at

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


@dataclass(frozen=True, slots=True)
class AutonomyPlan:
    subject_id: UUID
    version: int
    next_consideration_at: datetime
    source_episode_id: UUID | None
    opportunity_id: UUID | None


@runtime_checkable
class AutonomyPort(Protocol):
    async def consider_psychological_attention(
        self,
        transaction: PostgreSQLTransaction,
        *,
        subject_id: UUID,
        policy: AutonomyPolicy,
        facts: LifeOpportunityFactsPort,
    ) -> None: ...

    async def admit_due(
        self,
        transaction: PostgreSQLTransaction,
        *,
        subject_id: UUID,
        policy: AutonomyPolicy,
        scene_id: UUID | None = None,
        creator_party_id: UUID | None = None,
        activity_id: UUID | None = None,
    ) -> OpportunityAdmissionOutcome: ...

    async def ensure_plan(
        self,
        transaction: PostgreSQLTransaction,
        *,
        subject_id: UUID,
        policy: AutonomyPolicy,
        state_epoch: int | None = None,
    ) -> AutonomyPlan: ...

    async def commit_plan(
        self,
        transaction: PostgreSQLTransaction,
        *,
        subject_id: UUID,
        expected_version: int,
        episode_id: UUID,
        opportunity_id: UUID,
        delay_seconds: int,
        policy: AutonomyPolicy,
    ) -> None: ...

    async def register_request(
        self,
        transaction: PostgreSQLTransaction,
        *,
        subject_id: UUID,
        root_opportunity_id: UUID | None,
        call_id: str,
        policy: AutonomyPolicy,
    ) -> bool: ...


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


OpportunityPurpose = CognitionPurpose


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
        definition = COGNITION_PURPOSES[self.purpose]
        scene_required = definition.scene_requirement == "required"
        if definition.scene_requirement != "optional" and scene_required != (
            self.scene_id is not None
        ):
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
class CreatorOutreachFacts:
    scene_id: UUID
    creator_party_id: UUID


@runtime_checkable
class LifeOpportunityFactsPort(Protocol):
    async def concern_review_since(
        self,
        transaction: PostgreSQLTransaction,
        *,
        subject_id: UUID,
        after: datetime | None,
    ) -> datetime | None: ...

    async def psychological_attention_since(
        self,
        transaction: PostgreSQLTransaction,
        *,
        subject_id: UUID,
        after: datetime | None,
    ) -> datetime | None: ...

    async def outlet_health(self, outlet: str) -> tuple[str, str | None]: ...

    async def state_epoch(
        self, transaction: PostgreSQLTransaction, *, subject_id: UUID
    ) -> int: ...

    async def active_cognition_count(
        self, transaction: PostgreSQLTransaction, *, subject_id: UUID
    ) -> int: ...

    async def outreach(
        self,
        unit_of_work: PostgreSQLRuntimeUnitOfWork,
        *,
        outlet: str | None = None,
    ) -> CreatorOutreachFacts | None: ...


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
    evidence_id: UUID | None
    subject_id: UUID
    scene_id: UUID | None
    context_party_id: UUID | None
    purpose: str
    disposition: str
    reconsideration_no: int


@dataclass(frozen=True, slots=True)
class OpportunitySelectionCursor:
    available_after: datetime
    opportunity_id: UUID
    priority: int


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
    autonomy_context: bytes | None = None

    @property
    def selection_priority(self) -> int:
        return (
            0
            if self.purpose
            in {
                "consider_creator_input",
                "consider_creator_voice_input",
                "consider_other_human_input",
                "consider_codex_task",
            }
            else 1
        )


@runtime_checkable
class OpportunityCognitionSelectionPort(Protocol):
    async def can_consider_autonomy(
        self, transaction: PostgreSQLTransaction, *, subject_id: UUID
    ) -> bool: ...

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
):
    async def interrupt_conversations(
        self, transaction: PostgreSQLTransaction, *, subject_id: UUID
    ) -> tuple[UUID, ...]: ...

    async def interrupt_cognition(
        self, transaction: PostgreSQLTransaction, *, opportunity_ids: tuple[UUID, ...]
    ) -> None: ...


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
    async def origin_snapshot(
        self, transaction: PostgreSQLTransaction, *, opportunity_id: UUID
    ) -> tuple[UUID, UUID | None, str]: ...

    async def subject_commit_snapshot(
        self, transaction: PostgreSQLTransaction, *, opportunity_id: UUID
    ) -> OpportunityCommitSnapshot: ...

    async def resolve_subject_commit(
        self,
        transaction: PostgreSQLTransaction,
        *,
        opportunity_id: UUID,
        disposition: str = "resolved",
        next_consideration_seconds: int | None = None,
        source_episode_id: UUID | None = None,
    ) -> None: ...

    async def supersede_subject_commit(
        self, transaction: PostgreSQLTransaction, *, opportunity_id: UUID
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
class OpportunityRuntimePort(LifeOpportunitySourcePort, Protocol):
    async def open(self) -> None: ...

    async def close(self) -> None: ...

    def stop(self) -> None: ...

    async def run(self) -> None: ...

    async def maintain_sleep_once(self) -> OpportunityAdmissionOutcome: ...

    async def request_emergency_wake(
        self,
        session_id: UUID,
        request_id: UUID,
    ) -> UUID: ...


@dataclass(frozen=True, slots=True)
class OpportunityAdminSnapshot:
    opportunity_id: UUID
    evidence_id: UUID
    disposition: str


@runtime_checkable
class OpportunityAdminPort(Protocol):
    def snapshot(
        self, transaction: PostgreSQLAdminTransaction, *, opportunity_id: UUID
    ) -> OpportunityAdminSnapshot | None: ...

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
    "AutonomyPlan",
    "AutonomyPolicy",
    "AutonomyPort",
    "CreatorOutreachFacts",
    "ExternalEvidenceOpportunityDraft",
    "LifeOpportunityFactsPort",
    "LifeOpportunitySourceKind",
    "LifeOpportunitySourcePort",
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
    "quota_day",
    "quota_reset_at",
)
