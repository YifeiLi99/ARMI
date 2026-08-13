"""Public contracts for model execution and candidate validation."""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Protocol, runtime_checkable
from uuid import UUID

from armi_kernel.application import (
    ArtifactId,
    ArtifactRegistration,
    CandidateApplicationId,
    CandidateApplicationStatus,
    CandidateFactClass,
    CandidateViolation,
    ModelBinding,
    ModelInvocationResult,
    ModelRequest,
    PublishedArtifact,
)
from armi_kernel.contracts import Digest, TraceId
from armi_runtime_foundation import PostgreSQLRuntimeUnitOfWork, PostgreSQLTransaction

from ._contracts import (
    CandidateValidationResult,
    CandidateValidationStatus,
    CandidateValidator,
    SubjectChangeSet,
)

_TOKEN = re.compile(r"^[a-z][a-z0-9._-]{0,63}$", re.ASCII)
_PROPOSAL = re.compile(r"^proposal:[1-9][0-9]{0,2}$", re.ASCII)
_GROUP = re.compile(r"^group:[1-9][0-9]{0,2}$", re.ASCII)


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


class CognitionCandidateValue(Protocol):
    @property
    def schema_version(self) -> str: ...

    def model_dump(
        self,
        *,
        mode: str,
        exclude_none: bool = False,
    ) -> dict[str, object]: ...


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
        candidate_schema: dict[str, object],
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
    async def operation_snapshot(
        self,
        transaction: PostgreSQLTransaction,
        *,
        opportunity_id: UUID,
    ) -> CognitionOperationSnapshot: ...


@dataclass(frozen=True, slots=True)
class CognitionExperienceDraft:
    experience_id: UUID
    subject_id: UUID
    subject_commit_id: UUID
    episode_id: UUID
    proposal_ref: str
    experience_kind: str
    fact_class: CandidateFactClass
    first_person_gist: str
    scene_id: UUID | None
    occurred_at: datetime
    source_perspective: str
    uncertainty: str | None


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

    async def record_experience(
        self, transaction: PostgreSQLTransaction, draft: CognitionExperienceDraft
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


__all__ = (
    "CandidateValidationResult",
    "CandidateValidationStatus",
    "CandidateValidator",
    "CognitionAcceptedCandidate",
    "CognitionApplicationDraft",
    "CognitionApplicationSnapshot",
    "CognitionArtifactCatalogPort",
    "CognitionCandidateParser",
    "CognitionCandidateValue",
    "CognitionCommitSnapshot",
    "CognitionEpisodeStatus",
    "CognitionExactLifeQueryIntentDraft",
    "CognitionExactLifeQueryPort",
    "CognitionExactLifeQuerySnapshot",
    "CognitionExperienceDraft",
    "CognitionModelAdapterFactory",
    "CognitionModelPort",
    "CognitionOperationReadPort",
    "CognitionOperationSnapshot",
    "CognitionSubjectCommitPort",
    "CognitionWakeupPort",
    "CognitionWorkerPort",
    "SubjectChangeSet",
    "SubjectChangeSetCodec",
)
