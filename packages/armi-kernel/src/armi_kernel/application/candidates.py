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
from .life_materials import CandidateLifeMaterialDraft
from .life_records import LifeRecordKind
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
    MATERIAL = "material"
    PROMPT = "prompt"
    EXACT_LIFE_QUERY = "exact_life_query"


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
        identity = (self.source_ref, self.source_version)
        if all(value is None for value in identity):
            return
        if (
            type(self.source_ref) is not UUID
            or self.source_ref.version != 7
            or type(self.source_version) is not int
            or self.source_version < 0
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
        ):
            raise CandidateViolation("CON-CANDIDATE-COMPONENT")


@dataclass(frozen=True, slots=True)
class CandidateOwnerDraft:
    """Opaque proposal handed from a business owner to the subject pipeline."""

    proposal_ref: str
    atomic_group_ref: str
    basis_ordinals: tuple[int, ...]
    fact_class: CandidateFactClass
    owner: str
    canonical_payload: bytes

    def __post_init__(self) -> None:
        _validate_proposal(
            self.proposal_ref,
            self.atomic_group_ref,
            self.basis_ordinals,
        )
        if (
            type(self.fact_class) is not CandidateFactClass
            or type(self.owner) is not str
            or _TOKEN.fullmatch(self.owner) is None
            or type(self.canonical_payload) is not bytes
            or not self.canonical_payload
        ):
            raise CandidateViolation("CON-CANDIDATE-OWNER-DRAFT")


@dataclass(frozen=True, slots=True)
class CandidateSubjectPromptDraft:
    proposal_ref: str
    atomic_group_ref: str
    basis_ordinals: tuple[int, ...]
    fact_class: CandidateFactClass
    prompt_document_id: UUID
    current_revision_id: UUID | None
    expected_revision_no: int
    content_bytes: bytes

    def __post_init__(self) -> None:
        _validate_proposal(
            self.proposal_ref, self.atomic_group_ref, self.basis_ordinals
        )
        if (
            self.fact_class is not CandidateFactClass.SUBJECTIVE_UNDERSTANDING
            or type(self.prompt_document_id) is not UUID
            or self.prompt_document_id.version != 7
            or (
                self.current_revision_id is not None
                and (
                    type(self.current_revision_id) is not UUID
                    or self.current_revision_id.version != 7
                )
            )
            or type(self.expected_revision_no) is not int
            or self.expected_revision_no < 0
            or (self.current_revision_id is None) != (self.expected_revision_no == 0)
            or type(self.content_bytes) is not bytes
            or not self.content_bytes
            or len(self.content_bytes) > 16_384
        ):
            raise CandidateViolation("CON-CANDIDATE-SUBJECT-PROMPT")


@dataclass(frozen=True, slots=True)
class CandidateExactLifeQueryDraft:
    proposal_ref: str
    atomic_group_ref: str
    basis_ordinals: tuple[int, ...]
    fact_class: CandidateFactClass
    record_kind: LifeRecordKind
    query_text: str | None
    limit: int = 20

    def __post_init__(self) -> None:
        _validate_proposal(
            self.proposal_ref, self.atomic_group_ref, self.basis_ordinals
        )
        if (
            self.fact_class is not CandidateFactClass.SUBJECTIVE_UNDERSTANDING
            or type(self.record_kind) is not LifeRecordKind
            or not _optional_text(self.query_text, 1024)
            or type(self.limit) is not int
            or not 1 <= self.limit <= 20
        ):
            raise CandidateViolation("CON-CANDIDATE-EXACT-LIFE-QUERY")


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
    subject_id: UUID
    generation_id: UUID
    episode_id: UUID
    model_attempt_id: UUID
    base_subject_version: int
    base_state_epoch: int
    bundle_activation_id: UUID
    context_digest: Digest
    disposition: CandidateDisposition
    experiences: tuple[CandidateExperienceDraft, ...]
    components: tuple[CandidateComponentDraft, ...]
    capability_requests: tuple[CapabilityRequestDraft, ...]
    action_choices: tuple[ResponseChoiceDraft, ...]
    web_research_requests: tuple[WebResearchRequestDraft, ...]
    rejections: tuple[CandidateRejection, ...]
    codex_delegations: tuple[CodexDelegationDraft, ...] = ()
    owner_drafts: tuple[CandidateOwnerDraft, ...] = ()
    materials: tuple[CandidateLifeMaterialDraft, ...] = ()
    prompts: tuple[CandidateSubjectPromptDraft, ...] = ()
    exact_life_queries: tuple[CandidateExactLifeQueryDraft, ...] = ()

    def __post_init__(self) -> None:
        if (
            type(self.canonical_bytes) is not bytes
            or not self.canonical_bytes
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
    "CandidateBasis",
    "CandidateComponentDraft",
    "CandidateDisposition",
    "CandidateExactLifeQueryDraft",
    "CandidateExperienceDraft",
    "CandidateFactClass",
    "CandidateLifeMaterialDraft",
    "CandidateOwner",
    "CandidateOwnerDraft",
    "CandidateRejection",
    "CandidateSubjectPromptDraft",
    "CandidateValidationId",
    "CandidateValidationResult",
    "CandidateValidationStatus",
    "CandidateValidator",
    "CandidateViolation",
    "SubjectChangeSet",
)
