"""Technology-neutral cognition candidate validation contracts."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol, runtime_checkable
from uuid import UUID

from armi_kernel.contracts import Digest

from .capability import CapabilityRequestDraft
from .codex_delegation import CodexDelegationDraft
from .life import (
    ActivityAttentionDecisionKind,
    ActivityStatus,
    ActivityWaitingKind,
)
from .maintenance import SleepDecisionKind
from .response import ResponseChoiceDraft
from .web_evidence import WebResearchRequestDraft

_CODE = re.compile(r"^(?:CON|CANDIDATE)-[A-Z0-9-]+$", re.ASCII)
_REF = re.compile(r"^proposal:[1-9][0-9]{0,2}$", re.ASCII)
_GROUP = re.compile(r"^group:[1-9][0-9]{0,2}$", re.ASCII)
_TOKEN = re.compile(r"^[a-z][a-z0-9._-]{0,127}$", re.ASCII)


class CandidateDisposition(StrEnum):
    CHANGE = "change"
    NO_CHANGE = "no_change"
    DEFER = "defer"
    DECLINE = "decline"
    NO_ACTION = "no_action"
    NEED_INFORMATION = "need_information"


class CandidateFactClass(StrEnum):
    OBJECTIVE_FACT = "objective_fact"
    EXTERNAL_CLAIM = "external_claim"
    SUBJECTIVE_UNDERSTANDING = "subjective_understanding"
    INFERENCE = "inference"
    UNKNOWN = "unknown"


class CandidateOwner(StrEnum):
    EXPERIENCE = "experience"
    SELF = "self"
    MIND = "mind"
    LIFE_MODE = "life_mode"
    MEMORY = "memory"
    RELATIONSHIP = "relationship"
    ACTIVITY = "activity"
    CAPABILITY = "capability"
    ACTION = "action"
    WEB_RESEARCH = "web_research"
    CODEX_DELEGATION = "codex_delegation"
    SLEEP = "sleep"


class CandidateValidationStatus(StrEnum):
    ACCEPTED = "accepted"
    PARTIALLY_ACCEPTED = "partially_accepted"
    REJECTED = "rejected"


class CandidateViolation(RuntimeError):
    """Expose a stable candidate failure without candidate content."""

    __slots__ = ("code",)

    def __init__(self, code: str) -> None:
        if type(code) is not str or _CODE.fullmatch(code) is None:
            raise ValueError("candidate violation code is invalid")
        self.code = code
        super().__init__("cognition candidate validation failed")

    def __str__(self) -> str:
        return f"{self.code}: cognition candidate validation failed"


@dataclass(frozen=True, slots=True)
class CandidateValidationId:
    value: UUID

    def __post_init__(self) -> None:
        if type(self.value) is not UUID or self.value.version != 7:
            raise CandidateViolation("CON-CANDIDATE-VALIDATION-ID")

    def __str__(self) -> str:
        return str(self.value)


@dataclass(frozen=True, slots=True)
class CandidateBasis:
    ordinal: int
    section: str
    item_kind: str
    source_ref: UUID | None
    source_version: int | None
    source_digest: Digest | None
    trust_class: str
    privacy_scope: str

    def __post_init__(self) -> None:
        if (
            type(self.ordinal) is not int
            or not 1 <= self.ordinal <= 999
            or type(self.section) is not str
            or _TOKEN.fullmatch(self.section) is None
            or type(self.item_kind) is not str
            or _TOKEN.fullmatch(self.item_kind) is None
            or type(self.trust_class) is not str
            or self.trust_class
            not in {"runtime_authority", "subjective_state", "external_claim", "policy"}
            or type(self.privacy_scope) is not str
            or self.privacy_scope not in {"internal", "private", "restricted"}
        ):
            raise CandidateViolation("CON-CANDIDATE-BASIS")
        identity = (self.source_ref, self.source_version, self.source_digest)
        if all(value is None for value in identity):
            return
        if (
            type(self.source_ref) is not UUID
            or self.source_ref.version != 7
            or type(self.source_version) is not int
            or self.source_version < 0
            or type(self.source_digest) is not Digest
        ):
            raise CandidateViolation("CON-CANDIDATE-BASIS")


@dataclass(frozen=True, slots=True)
class CandidateExperienceDraft:
    proposal_ref: str
    atomic_group_ref: str
    basis_ordinals: tuple[int, ...]
    fact_class: CandidateFactClass
    first_person_gist: str
    uncertainty: str | None
    privacy_scope: str

    def __post_init__(self) -> None:
        _validate_proposal(
            self.proposal_ref, self.atomic_group_ref, self.basis_ordinals
        )
        if (
            type(self.fact_class) is not CandidateFactClass
            or type(self.first_person_gist) is not str
            or not 1 <= len(self.first_person_gist) <= 1024
            or (
                self.uncertainty is not None
                and (
                    type(self.uncertainty) is not str
                    or not 1 <= len(self.uncertainty) <= 512
                )
            )
            or self.privacy_scope != "private"
        ):
            raise CandidateViolation("CON-CANDIDATE-EXPERIENCE")


@dataclass(frozen=True, slots=True)
class CandidateComponentDraft:
    proposal_ref: str
    atomic_group_ref: str
    basis_ordinals: tuple[int, ...]
    fact_class: CandidateFactClass
    owner: CandidateOwner
    expected_version: int
    canonical_next_state: bytes
    next_state_digest: Digest

    def __post_init__(self) -> None:
        _validate_proposal(
            self.proposal_ref, self.atomic_group_ref, self.basis_ordinals
        )
        if (
            type(self.fact_class) is not CandidateFactClass
            or self.owner
            not in {CandidateOwner.SELF, CandidateOwner.MIND, CandidateOwner.LIFE_MODE}
            or type(self.expected_version) is not int
            or self.expected_version <= 0
            or type(self.canonical_next_state) is not bytes
            or not self.canonical_next_state
            or type(self.next_state_digest) is not Digest
            or Digest.from_bytes(self.canonical_next_state) != self.next_state_digest
        ):
            raise CandidateViolation("CON-CANDIDATE-COMPONENT")


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
        _validate_proposal(
            self.proposal_ref, self.atomic_group_ref, self.basis_ordinals
        )
        if (
            type(self.fact_class) is not CandidateFactClass
            or type(self.activity_id) is not UUID
            or self.activity_id.version != 7
            or type(self.goal) is not str
            or not 1 <= len(self.goal) <= 2048
            or type(self.next_safe_step) is not str
            or not 1 <= len(self.next_safe_step) <= 1024
            or self.status is not ActivityStatus.READY
            or self.activity_kind != "self_directed"
            or self.privacy_scope != "private"
        ):
            raise CandidateViolation("CON-CANDIDATE-ACTIVITY")


@dataclass(frozen=True, slots=True)
class CandidateActivityDecisionDraft:
    proposal_ref: str
    atomic_group_ref: str
    basis_ordinals: tuple[int, ...]
    activity_id: UUID
    current_revision_id: UUID
    expected_head_version: int
    resource_snapshot_digest: Digest
    decision_kind: ActivityAttentionDecisionKind
    progress_summary: str | None = None
    next_safe_step: str | None = None
    waiting_summary: str | None = None
    resumption_cue: str | None = None
    waiting_kind: ActivityWaitingKind | None = None
    delay_seconds: int | None = None
    terminal_reason: str | None = None

    def __post_init__(self) -> None:
        _validate_proposal(
            self.proposal_ref, self.atomic_group_ref, self.basis_ordinals
        )
        if (
            any(
                type(value) is not UUID or value.version != 7
                for value in (self.activity_id, self.current_revision_id)
            )
            or type(self.expected_head_version) is not int
            or self.expected_head_version <= 0
            or type(self.resource_snapshot_digest) is not Digest
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
            raise CandidateViolation("CON-CANDIDATE-ACTIVITY-DECISION")
        kind = self.decision_kind
        simple = {
            ActivityAttentionDecisionKind.ENGAGE,
            ActivityAttentionDecisionKind.RESUME,
            ActivityAttentionDecisionKind.NO_ACTION,
            ActivityAttentionDecisionKind.DEFER,
            ActivityAttentionDecisionKind.NEED_INFORMATION,
        }
        if kind in simple and any(
            value is not None
            for value in (
                self.progress_summary,
                self.next_safe_step,
                self.waiting_summary,
                self.resumption_cue,
                self.waiting_kind,
                self.delay_seconds,
                self.terminal_reason,
            )
        ):
            raise CandidateViolation("CON-CANDIDATE-ACTIVITY-DECISION-SHAPE")
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
            raise CandidateViolation("CON-CANDIDATE-ACTIVITY-DECISION-SHAPE")
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
            raise CandidateViolation("CON-CANDIDATE-ACTIVITY-DECISION-SHAPE")
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
            raise CandidateViolation("CON-CANDIDATE-ACTIVITY-DECISION-SHAPE")
        if kind is ActivityAttentionDecisionKind.PAUSE and (
            self.waiting_kind is not ActivityWaitingKind.SCHEDULED_REVIEW
            or self.delay_seconds is None
        ):
            raise CandidateViolation("CON-CANDIDATE-ACTIVITY-DECISION-SHAPE")
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
            raise CandidateViolation("CON-CANDIDATE-ACTIVITY-DECISION-SHAPE")


@dataclass(frozen=True, slots=True)
class CandidateSleepDecisionDraft:
    proposal_ref: str
    atomic_group_ref: str
    basis_ordinals: tuple[int, ...]
    decision_kind: SleepDecisionKind
    cycle_anchor_ref: UUID
    source_digest: Digest

    def __post_init__(self) -> None:
        _validate_proposal(
            self.proposal_ref, self.atomic_group_ref, self.basis_ordinals
        )
        if (
            type(self.decision_kind) is not SleepDecisionKind
            or type(self.cycle_anchor_ref) is not UUID
            or self.cycle_anchor_ref.version != 7
            or type(self.source_digest) is not Digest
        ):
            raise CandidateViolation("CON-CANDIDATE-SLEEP")


@dataclass(frozen=True, slots=True)
class CandidateRejection:
    proposal_ref: str
    atomic_group_ref: str
    basis_ordinals: tuple[int, ...]
    fact_class: CandidateFactClass
    owner: CandidateOwner
    code: str

    def __post_init__(self) -> None:
        if (
            _REF.fullmatch(self.proposal_ref) is None
            or _GROUP.fullmatch(self.atomic_group_ref) is None
            or type(self.fact_class) is not CandidateFactClass
            or type(self.owner) is not CandidateOwner
            or _CODE.fullmatch(self.code) is None
        ):
            raise CandidateViolation("CON-CANDIDATE-REJECTION")
        _validate_proposal(
            self.proposal_ref,
            self.atomic_group_ref,
            self.basis_ordinals,
        )


@dataclass(frozen=True, slots=True)
class SubjectChangeSet:
    canonical_bytes: bytes
    digest: Digest
    subject_id: UUID
    generation_id: UUID
    episode_id: UUID
    model_attempt_id: UUID
    base_subject_version: int
    base_state_epoch: int
    bundle_activation_id: UUID
    context_digest: Digest
    candidate_digest: Digest
    disposition: CandidateDisposition
    experiences: tuple[CandidateExperienceDraft, ...]
    components: tuple[CandidateComponentDraft, ...]
    capability_requests: tuple[CapabilityRequestDraft, ...]
    action_choices: tuple[ResponseChoiceDraft, ...]
    web_research_requests: tuple[WebResearchRequestDraft, ...]
    rejections: tuple[CandidateRejection, ...]
    codex_delegations: tuple[CodexDelegationDraft, ...] = ()
    activities: tuple[CandidateActivityDraft, ...] = ()
    activity_decisions: tuple[CandidateActivityDecisionDraft, ...] = ()
    sleep_decisions: tuple[CandidateSleepDecisionDraft, ...] = ()

    def __post_init__(self) -> None:
        if (
            type(self.canonical_bytes) is not bytes
            or not self.canonical_bytes
            or type(self.digest) is not Digest
            or Digest.from_bytes(self.canonical_bytes) != self.digest
            or any(
                type(value) is not UUID or value.version != 7
                for value in (
                    self.subject_id,
                    self.generation_id,
                    self.episode_id,
                    self.model_attempt_id,
                    self.bundle_activation_id,
                )
            )
            or type(self.base_subject_version) is not int
            or self.base_subject_version < 0
            or type(self.base_state_epoch) is not int
            or self.base_state_epoch < 0
            or type(self.context_digest) is not Digest
            or type(self.candidate_digest) is not Digest
            or type(self.disposition) is not CandidateDisposition
        ):
            raise CandidateViolation("CON-CANDIDATE-CHANGE-SET")


@dataclass(frozen=True, slots=True)
class CandidateValidationResult:
    validation_id: CandidateValidationId
    status: CandidateValidationStatus
    change_set: SubjectChangeSet | None
    accepted_count: int
    rejected_count: int
    error_code: str | None

    def __post_init__(self) -> None:
        if (
            type(self.validation_id) is not CandidateValidationId
            or type(self.status) is not CandidateValidationStatus
            or type(self.accepted_count) is not int
            or self.accepted_count < 0
            or type(self.rejected_count) is not int
            or self.rejected_count < 0
        ):
            raise CandidateViolation("CON-CANDIDATE-RESULT")
        rejected = self.status is CandidateValidationStatus.REJECTED
        if rejected != (self.change_set is None):
            raise CandidateViolation("CON-CANDIDATE-RESULT")
        if rejected:
            if (
                type(self.error_code) is not str
                or _CODE.fullmatch(self.error_code) is None
            ):
                raise CandidateViolation("CON-CANDIDATE-RESULT")
        elif self.error_code is not None:
            raise CandidateViolation("CON-CANDIDATE-RESULT")


@runtime_checkable
class CandidateValidator(Protocol):
    def validate(
        self,
        candidate_bytes: bytes,
        *,
        bases: tuple[CandidateBasis, ...],
    ) -> CandidateValidationResult:
        """Validate untrusted model material without applying subject state."""
        ...


def _validate_proposal(
    proposal_ref: str,
    atomic_group_ref: str,
    basis_ordinals: tuple[int, ...],
) -> None:
    if (
        type(proposal_ref) is not str
        or _REF.fullmatch(proposal_ref) is None
        or type(atomic_group_ref) is not str
        or _GROUP.fullmatch(atomic_group_ref) is None
        or type(basis_ordinals) is not tuple
        or not 1 <= len(basis_ordinals) <= 8
        or any(
            type(value) is not int or not 1 <= value <= 999 for value in basis_ordinals
        )
        or len(set(basis_ordinals)) != len(basis_ordinals)
    ):
        raise CandidateViolation("CON-CANDIDATE-PROPOSAL")


def _optional_text(value: str | None, maximum: int) -> bool:
    if value is None:
        return True
    if type(value) is not str or not value.strip() or "\x00" in value:
        return False
    try:
        return 1 <= len(value.encode("utf-8", errors="strict")) <= maximum
    except UnicodeEncodeError:
        return False


__all__ = (
    "CandidateActivityDecisionDraft",
    "CandidateActivityDraft",
    "CandidateBasis",
    "CandidateComponentDraft",
    "CandidateDisposition",
    "CandidateExperienceDraft",
    "CandidateFactClass",
    "CandidateOwner",
    "CandidateRejection",
    "CandidateSleepDecisionDraft",
    "CandidateValidationId",
    "CandidateValidationResult",
    "CandidateValidationStatus",
    "CandidateValidator",
    "CandidateViolation",
    "SubjectChangeSet",
)
