"""Public contracts for model execution and candidate validation."""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Protocol, runtime_checkable
from uuid import UUID

from armi_capability.api import CapabilityRequestDraft
from armi_codex.api import CodexDelegationDraft
from armi_expression.api import ResponseChoiceDraft
from armi_kernel.application import (
    ArtifactId,
    ArtifactRef,
    ArtifactRegistration,
    CandidateApplicationId,
    CandidateApplicationStatus,
    CandidateBasis,
    CandidateDisposition,
    CandidateExperienceDraft,
    CandidateFactClass,
    CandidateOwnerDraft,
    CandidateRejection,
    CandidateValidationId,
    CandidateViolation,
    LifeRecordKind,
    ModelBinding,
    ModelInvocationResult,
    ModelRequest,
    PublishedArtifact,
)
from armi_kernel.contracts import Digest, TraceId
from armi_runtime_foundation import (
    PostgreSQLAdminTransaction,
    PostgreSQLRuntimeUnitOfWork,
    PostgreSQLTransaction,
)
from armi_web_observation.api import WebResearchRequestDraft

_TOKEN = re.compile(r"^[a-z][a-z0-9._-]{0,63}$", re.ASCII)
_PROPOSAL = re.compile(r"^proposal:[1-9][0-9]{0,2}$", re.ASCII)
_GROUP = re.compile(r"^group:[1-9][0-9]{0,2}$", re.ASCII)
_RESULT_CODE = re.compile(r"^(?:CON|CANDIDATE)-[A-Z0-9-]+$", re.ASCII)


class CandidateValidationStatus(StrEnum):
    ACCEPTED = "accepted"
    PARTIALLY_ACCEPTED = "partially_accepted"
    REJECTED = "rejected"


class CognitiveBranchRole(StrEnum):
    PRIMARY = "primary"
    RESPONSE_ACTION = "response_action"
    EPISODE_APPRAISAL = "episode_appraisal"


class HotDialogueAggregateOutcome(StrEnum):
    COMPLETE = "complete"
    RESPONSE_ONLY = "response_only"
    INTERNAL_ONLY = "internal_only"
    FAILED = "failed"


class MaintenanceIssueTarget(StrEnum):
    SELF = "self"
    MIND = "mind"
    PROMPT = "prompt"


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
        if (
            _PROPOSAL.fullmatch(self.proposal_ref) is None
            or _GROUP.fullmatch(self.atomic_group_ref) is None
            or type(self.basis_ordinals) is not tuple
            or not self.basis_ordinals
            or any(type(item) is not int or item < 0 for item in self.basis_ordinals)
            or tuple(sorted(set(self.basis_ordinals))) != self.basis_ordinals
            or self.fact_class is not CandidateFactClass.SUBJECTIVE_UNDERSTANDING
            or type(self.record_kind) is not LifeRecordKind
            or (
                self.query_text is not None
                and (type(self.query_text) is not str or not self.query_text.strip())
            )
            or type(self.limit) is not int
            or not 1 <= self.limit <= 20
        ):
            raise CandidateViolation("CON-CANDIDATE-EXACT-LIFE-QUERY")


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
    capability_requests: tuple[CapabilityRequestDraft, ...]
    action_choices: tuple[ResponseChoiceDraft, ...]
    web_research_requests: tuple[WebResearchRequestDraft, ...]
    rejections: tuple[CandidateRejection, ...]
    codex_delegations: tuple[CodexDelegationDraft, ...] = ()
    owner_drafts: tuple[CandidateOwnerDraft, ...] = ()
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
        rejected = self.status is CandidateValidationStatus.REJECTED
        if (
            type(self.validation_id) is not CandidateValidationId
            or type(self.status) is not CandidateValidationStatus
            or type(self.accepted_count) is not int
            or self.accepted_count < 0
            or type(self.rejected_count) is not int
            or self.rejected_count < 0
            or rejected != (self.change_set is None)
            or (
                rejected
                and (
                    type(self.error_code) is not str
                    or _RESULT_CODE.fullmatch(self.error_code) is None
                )
            )
            or (not rejected and self.error_code is not None)
        ):
            raise CandidateViolation("CON-CANDIDATE-RESULT")


@runtime_checkable
class CandidateValidator(Protocol):
    def validate(
        self, candidate_bytes: bytes, *, bases: tuple[CandidateBasis, ...]
    ) -> CandidateValidationResult: ...


def _require_uuid7(value: object) -> None:
    if type(value) is not UUID or value.version != 7:
        raise CandidateViolation("CON-CANDIDATE-SUBJECT-COMMIT")


@runtime_checkable
class CognitionArtifactCatalogPort(Protocol):
    async def register(
        self,
        unit_of_work: PostgreSQLRuntimeUnitOfWork,
        artifact_id: ArtifactId,
        published: PublishedArtifact,
    ) -> ArtifactRegistration: ...

    async def retained_ref(
        self,
        unit_of_work: PostgreSQLRuntimeUnitOfWork,
        artifact_id: ArtifactId,
    ) -> ArtifactRef | None: ...


@dataclass(frozen=True, slots=True)
class CognitionRuntimeStateSnapshot:
    subject_id: UUID
    subject_version: int
    state_epoch: int
    generation_id: UUID
    bundle_activation_id: UUID


@runtime_checkable
class CognitionRuntimeStatePort(Protocol):
    async def current_state(
        self,
        transaction: PostgreSQLTransaction,
        *,
        subject_id: UUID,
    ) -> CognitionRuntimeStateSnapshot: ...


@dataclass(frozen=True, slots=True)
class CognitionContextEpisodeDraft:
    episode_id: UUID
    opportunity_id: UUID
    subject_id: UUID
    generation_id: UUID
    scene_id: UUID | None
    context_party_id: UUID | None
    purpose: str
    base_subject_version: int
    base_state_epoch: int
    bundle_activation_id: UUID
    mechanism_identity: str
    trace_id: TraceId
    maintenance_trigger_kind: str | None = None


@dataclass(frozen=True, slots=True)
class CognitionExperienceContextItem:
    experience_id: UUID
    ordinal: int
    fact_class: str
    first_person_gist: str
    occurred_at: datetime
    accepted_at: datetime
    source_perspective: str
    uncertainty: str | None
    maintenance_source: bool


@dataclass(frozen=True, slots=True)
class CognitionContextEpisodeSnapshot:
    episode_id: UUID
    opportunity_id: UUID
    subject_id: UUID
    scene_id: UUID | None
    context_party_id: UUID | None
    purpose: str
    base_subject_version: int
    base_state_epoch: int
    bundle_activation_id: UUID
    mechanism_identity: str
    trace_id: TraceId
    life_query_intent_id: UUID | None = None
    life_query_result_artifact_id: UUID | None = None
    experience_context: tuple[CognitionExperienceContextItem, ...] = ()


@runtime_checkable
class CognitionContextLifecyclePort(Protocol):
    async def create_context_episode(
        self,
        transaction: PostgreSQLTransaction,
        draft: CognitionContextEpisodeDraft,
    ) -> bool: ...

    async def context_episode(
        self,
        transaction: PostgreSQLTransaction,
        *,
        episode_id: UUID,
    ) -> CognitionContextEpisodeSnapshot: ...

    async def mark_context_prepared(
        self,
        transaction: PostgreSQLTransaction,
        *,
        episode_id: UUID,
        manifest_artifact_id: UUID,
        compiled_artifact_id: UUID,
        context_digest: Digest,
    ) -> CognitionContextEpisodeSnapshot: ...

    async def fail_context(
        self,
        transaction: PostgreSQLTransaction,
        *,
        episode_id: UUID,
        error_code: str,
    ) -> CognitionContextEpisodeSnapshot: ...


class CognitionCandidateValue(Protocol):
    @property
    def schema_version(self) -> str: ...

    def model_dump_json(
        self,
        *,
        exclude_none: bool = False,
    ) -> str: ...


@dataclass(frozen=True, slots=True)
class CognitionSchemaDocument:
    canonical_bytes: bytes

    def __post_init__(self) -> None:
        if not self.canonical_bytes or len(self.canonical_bytes) > 1_048_576:
            raise ValueError("cognition schema document is invalid")


class CognitionCandidateParser(Protocol):
    def __call__(
        self,
        value: bytes,
        *,
        allowed_context_refs: frozenset[str],
    ) -> CognitionCandidateValue: ...


@runtime_checkable
class CognitionModelPort(Protocol):
    @property
    def binding(self) -> ModelBinding: ...

    async def tokenize(self, canonical_request: bytes) -> int: ...

    async def invoke(self, request: ModelRequest) -> ModelInvocationResult: ...


class CognitionModelAdapterFactory(Protocol):
    def __call__(
        self,
        *,
        binding: ModelBinding,
        candidate_schema: CognitionSchemaDocument,
        candidate_parser: CognitionCandidateParser,
        instructions: str | None = None,
        schema_name: str | None = None,
    ) -> CognitionModelPort: ...


@runtime_checkable
class CognitionWakeupPort(Protocol):
    def notify(self, channel: str) -> None: ...

    def version(self, channel: str) -> int: ...

    async def wait(
        self,
        channel: str,
        after_version: int,
        *,
        stop: asyncio.Event,
        timeout_seconds: float,
    ) -> int: ...


@runtime_checkable
class CognitionWorkerPort(Protocol):
    async def open(self) -> None: ...

    async def close(self) -> None: ...

    def stop(self) -> None: ...

    async def run_worker(self) -> None: ...


@dataclass(frozen=True, slots=True)
class CognitionExactLifeQuerySnapshot:
    intent_id: UUID
    subject_id: UUID
    source_opportunity_id: UUID
    scene_id: UUID
    creator_party_id: UUID
    record_kind: str
    query_text: str | None
    limit: int
    query_digest: Digest
    trace_id: TraceId


class CognitionEpisodeStatus(StrEnum):
    COMPLETED = "completed"
    STALE = "stale"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class CognitionAcceptedCandidate:
    proposal_ref: str
    atomic_group_ref: str
    owner_identity: str
    fact_class: CandidateFactClass
    ordinal: int
    basis_context_ids: tuple[UUID, ...]
    canonical_payload: bytes | None = None
    payload_digest: Digest | None = None

    def __post_init__(self) -> None:
        if (
            type(self.proposal_ref) is not str
            or _PROPOSAL.fullmatch(self.proposal_ref) is None
            or type(self.atomic_group_ref) is not str
            or _GROUP.fullmatch(self.atomic_group_ref) is None
            or type(self.owner_identity) is not str
            or _TOKEN.fullmatch(self.owner_identity) is None
            or type(self.fact_class) is not CandidateFactClass
            or type(self.ordinal) is not int
            or not 1 <= self.ordinal <= 16
            or type(self.basis_context_ids) is not tuple
            or len(set(self.basis_context_ids)) != len(self.basis_context_ids)
            or ((self.canonical_payload is None) != (self.payload_digest is None))
        ):
            raise CandidateViolation("CON-CANDIDATE-SUBJECT-COMMIT")
        for value in self.basis_context_ids:
            _require_uuid7(value)
        if self.canonical_payload is not None and (
            type(self.canonical_payload) is not bytes
            or not self.canonical_payload
            or self.payload_digest != Digest.from_bytes(self.canonical_payload)
        ):
            raise CandidateViolation("CON-CANDIDATE-SUBJECT-COMMIT")


@dataclass(frozen=True, slots=True)
class CognitionCommitSnapshot:
    validation_id: UUID
    episode_id: UUID
    opportunity_id: UUID
    subject_id: UUID
    generation_id: UUID
    activation_id: UUID
    change_set_artifact_id: ArtifactId
    base_subject_version: int
    base_state_epoch: int
    context_digest: Digest
    trace_id: TraceId
    accepted_candidates: tuple[CognitionAcceptedCandidate, ...]

    def __post_init__(self) -> None:
        for value in (
            self.validation_id,
            self.episode_id,
            self.opportunity_id,
            self.subject_id,
            self.generation_id,
            self.activation_id,
        ):
            _require_uuid7(value)
        if (
            type(self.change_set_artifact_id) is not ArtifactId
            or type(self.base_subject_version) is not int
            or self.base_subject_version < 0
            or type(self.base_state_epoch) is not int
            or self.base_state_epoch < 0
            or type(self.context_digest) is not Digest
            or type(self.trace_id) is not TraceId
            or type(self.accepted_candidates) is not tuple
            or tuple(item.ordinal for item in self.accepted_candidates)
            != tuple(sorted(item.ordinal for item in self.accepted_candidates))
            or len({item.proposal_ref for item in self.accepted_candidates})
            != len(self.accepted_candidates)
        ):
            raise CandidateViolation("CON-CANDIDATE-SUBJECT-COMMIT")


@dataclass(frozen=True, slots=True)
class CognitionApplicationSnapshot:
    application_id: CandidateApplicationId
    status: CandidateApplicationStatus
    subject_commit_id: UUID | None
    observed_subject_version: int
    successor_opportunity_id: UUID | None

    def __post_init__(self) -> None:
        if (
            type(self.application_id) is not CandidateApplicationId
            or type(self.status) is not CandidateApplicationStatus
            or type(self.observed_subject_version) is not int
            or self.observed_subject_version < 0
        ):
            raise CandidateViolation("CON-CANDIDATE-APPLICATION")
        if self.subject_commit_id is not None:
            _require_uuid7(self.subject_commit_id)
        if self.successor_opportunity_id is not None:
            _require_uuid7(self.successor_opportunity_id)


@dataclass(frozen=True, slots=True)
class CognitionOperationSnapshot:
    episode_status: str | None
    failure_code: str | None
    application_resolution: str | None
    observed_subject_version: int | None


@runtime_checkable
class CognitionOperationReadPort(Protocol):
    async def opportunity_episode_states(
        self, transaction: PostgreSQLTransaction, *, opportunity_id: UUID
    ) -> tuple[tuple[UUID, str], ...]: ...

    async def last_purpose_created_at(
        self, transaction: PostgreSQLTransaction, *, subject_id: UUID, purpose: str
    ) -> datetime | None: ...

    async def active_count(
        self, transaction: PostgreSQLTransaction, *, subject_id: UUID
    ) -> int: ...

    async def operation_snapshot(
        self,
        transaction: PostgreSQLTransaction,
        *,
        opportunity_id: UUID,
    ) -> CognitionOperationSnapshot: ...

    async def opportunity_for_episode(
        self,
        transaction: PostgreSQLTransaction,
        *,
        episode_id: UUID,
    ) -> UUID | None: ...


@dataclass(frozen=True, slots=True)
class CognitionApplicationDraft:
    application_id: CandidateApplicationId
    validation_id: UUID
    episode_id: UUID
    work_id: UUID
    status: CandidateApplicationStatus
    subject_commit_id: UUID | None
    successor_opportunity_id: UUID | None
    base_subject_version: int
    observed_subject_version: int
    runtime_instance_id: UUID
    fence_token: int
    purpose: str | None = None
    generation_id: UUID | None = None


@dataclass(frozen=True, slots=True)
class CognitionExactLifeQueryIntentDraft:
    intent_id: UUID
    subject_commit_id: UUID
    source_opportunity_id: UUID
    subject_id: UUID
    scene_id: UUID
    creator_party_id: UUID
    proposal_ref: str
    record_kind: str
    query_text: str | None
    result_limit: int
    query_digest: Digest
    execution_work_id: UUID
    trace_id: TraceId


@runtime_checkable
class CognitionSubjectCommitPort(Protocol):
    async def snapshot(
        self, transaction: PostgreSQLTransaction, *, episode_id: UUID
    ) -> CognitionCommitSnapshot: ...

    async def existing_application(
        self, transaction: PostgreSQLTransaction, *, validation_id: UUID
    ) -> CognitionApplicationSnapshot | None: ...

    async def note_accepted_experience(
        self,
        transaction: PostgreSQLTransaction,
        *,
        subject_id: UUID,
        generation_id: UUID,
        experience_id: UUID,
    ) -> None: ...

    async def record_application(
        self, transaction: PostgreSQLTransaction, draft: CognitionApplicationDraft
    ) -> None: ...

    async def record_exact_life_query(
        self,
        transaction: PostgreSQLTransaction,
        draft: CognitionExactLifeQueryIntentDraft,
    ) -> None: ...

    async def finish_episode(
        self,
        transaction: PostgreSQLTransaction,
        *,
        episode_id: UUID,
        status: CognitionEpisodeStatus,
        application_status: CandidateApplicationStatus | None,
        failure_code: str | None = None,
    ) -> None: ...


@runtime_checkable
class CognitionOwnerPort(
    CognitionSubjectCommitPort,
    CognitionOperationReadPort,
    Protocol,
):
    """Complete shared read/commit surface of the active Cognition repository."""


@runtime_checkable
class CognitionExactLifeQueryPort(Protocol):
    async def snapshot(
        self,
        transaction: PostgreSQLTransaction,
        *,
        intent_id: UUID,
        subject_id: UUID,
    ) -> CognitionExactLifeQuerySnapshot: ...

    async def settle(
        self,
        transaction: PostgreSQLTransaction,
        *,
        intent_id: UUID,
        status: str,
        result_artifact_id: UUID,
        result_count: int,
        failure_code: str | None,
        result_opportunity_id: UUID,
    ) -> None: ...

    async def fail(
        self,
        transaction: PostgreSQLTransaction,
        *,
        intent_id: UUID,
        code: str,
    ) -> None: ...


@runtime_checkable
class SubjectChangeSetCodec(Protocol):
    """Decode a frozen cognition change set through explicitly bound owner codecs."""

    def decode(self, value: bytes) -> SubjectChangeSet: ...


@dataclass(frozen=True, slots=True)
class CognitionAdminEpisodeSnapshot:
    episode_id: UUID
    opportunity_id: UUID
    status: str
    trace_id: str
    prepared_at: datetime | None


@runtime_checkable
class CognitionAdminPort(Protocol):
    def opportunity_consumed(
        self, transaction: PostgreSQLAdminTransaction, *, opportunity_id: UUID
    ) -> bool: ...

    def episode(
        self, transaction: PostgreSQLAdminTransaction, *, episode_id: UUID
    ) -> CognitionAdminEpisodeSnapshot | None: ...

    def inspect_ids(
        self, transaction: PostgreSQLAdminTransaction, *, object_ids: tuple[UUID, ...]
    ) -> tuple[UUID, ...]: ...

    def artifact_reference_count(
        self, transaction: PostgreSQLAdminTransaction, *, artifact_id: UUID
    ) -> int: ...


__all__ = (
    "CandidateExactLifeQueryDraft",
    "CandidateValidationResult",
    "CandidateValidationStatus",
    "CandidateValidator",
    "CognitionAcceptedCandidate",
    "CognitionAdminEpisodeSnapshot",
    "CognitionAdminPort",
    "CognitionApplicationDraft",
    "CognitionApplicationSnapshot",
    "CognitionArtifactCatalogPort",
    "CognitionCandidateParser",
    "CognitionCandidateValue",
    "CognitionCommitSnapshot",
    "CognitionContextEpisodeDraft",
    "CognitionContextEpisodeSnapshot",
    "CognitionContextLifecyclePort",
    "CognitionEpisodeStatus",
    "CognitionExactLifeQueryIntentDraft",
    "CognitionExactLifeQueryPort",
    "CognitionExactLifeQuerySnapshot",
    "CognitionExperienceContextItem",
    "CognitionModelAdapterFactory",
    "CognitionModelPort",
    "CognitionOperationReadPort",
    "CognitionOperationSnapshot",
    "CognitionOwnerPort",
    "CognitionRuntimeStatePort",
    "CognitionRuntimeStateSnapshot",
    "CognitionSchemaDocument",
    "CognitionSubjectCommitPort",
    "CognitionWakeupPort",
    "CognitionWorkerPort",
    "CognitiveBranchRole",
    "HotDialogueAggregateOutcome",
    "MaintenanceIssueTarget",
    "SubjectChangeSet",
    "SubjectChangeSetCodec",
)
