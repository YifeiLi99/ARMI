"""Public contracts for governed public-web observation and evidence custody."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable
from uuid import UUID

from armi_kernel.application import (
    ArtifactId,
    ArtifactPort,
    ArtifactRef,
    ArtifactRegistration,
    PublishedArtifact,
)
from armi_kernel.contracts import TraceId
from armi_runtime_foundation import (
    PostgreSQLAdminTransaction,
    PostgreSQLRuntimeUnitOfWork,
    PostgreSQLTransaction,
)

from ._observation_contract import (
    WebObservationAdmissionPort,
    WebObservationAttemptId,
    WebObservationAttemptState,
    WebObservationCustodyPort,
    WebObservationDraft,
    WebObservationInvocationResult,
    WebObservationRecord,
    WebObservationRequestId,
    WebObservationRequestStatus,
    WebObservationResultStatus,
    WebObservationToolAction,
    WebObservationToolCallId,
    WebObservationUsage,
    WebObservationViolation,
)
from ._research_contract import (
    WebEvidenceAcceptancePort,
    WebEvidenceAcceptanceResult,
    WebEvidenceBundle,
    WebEvidenceKind,
    WebEvidenceSourceId,
    WebResearchIntentDraft,
    WebResearchIntentId,
    WebResearchIntentPort,
    WebResearchIntentStatus,
    WebResearchRequestDraft,
    WebResearchViolation,
    WebSourceReference,
)


@dataclass(frozen=True, slots=True)
class WebResearchCommitContext:
    validation_id: UUID
    episode_id: UUID
    opportunity_id: UUID
    subject_id: UUID
    scene_id: UUID | None
    creator_party_id: UUID | None
    trace_id: TraceId

    def __post_init__(self) -> None:
        for value in (
            self.validation_id,
            self.episode_id,
            self.opportunity_id,
            self.subject_id,
        ):
            if type(value) is not UUID or value.version != 7:
                raise WebResearchViolation("WEB-RESEARCH-COMMIT-CONTEXT")
        for value in (self.scene_id, self.creator_party_id):
            if value is not None and (type(value) is not UUID or value.version != 7):
                raise WebResearchViolation("WEB-RESEARCH-COMMIT-CONTEXT")
        if type(self.trace_id) is not TraceId:
            raise WebResearchViolation("WEB-RESEARCH-COMMIT-CONTEXT")


@runtime_checkable
class WebResearchCommitPort(Protocol):
    async def commit_requests(
        self,
        unit_of_work: PostgreSQLRuntimeUnitOfWork,
        *,
        context: WebResearchCommitContext,
        commit_id: UUID,
        requests: tuple[WebResearchRequestDraft, ...],
        query_artifact: ArtifactRef | None,
    ) -> None: ...


@runtime_checkable
class WebObservationRuntimePort(
    WebObservationAdmissionPort,
    WebObservationCustodyPort,
    Protocol,
):
    async def open(self) -> None: ...
    async def close(self) -> None: ...
    def stop(self) -> None: ...
    async def run_worker(self) -> None: ...


@runtime_checkable
class WebResearchRuntimePort(WebResearchIntentPort, Protocol):
    async def open(self) -> None: ...
    async def close(self) -> None: ...
    def stop(self) -> None: ...
    async def run_worker(self) -> None: ...


@runtime_checkable
class WebContextReadPort(Protocol):
    async def request_trace(
        self,
        transaction: PostgreSQLTransaction,
        *,
        request_id: UUID,
    ) -> TraceId: ...


@runtime_checkable
class WebArtifactStorePort(ArtifactPort, Protocol):
    async def prepare(self) -> None: ...


@runtime_checkable
class WebArtifactCatalogPort(Protocol):
    async def register(
        self,
        unit_of_work: PostgreSQLRuntimeUnitOfWork,
        artifact_id: ArtifactId,
        published: PublishedArtifact,
    ) -> ArtifactRegistration: ...


@runtime_checkable
class WebObservationAdminPort(Protocol):
    def opportunity_consumed(
        self, transaction: PostgreSQLAdminTransaction, *, opportunity_id: UUID
    ) -> bool: ...
    def artifact_reference_count(
        self, transaction: PostgreSQLAdminTransaction, *, artifact_id: UUID
    ) -> int: ...


__all__ = (
    "WebArtifactCatalogPort",
    "WebArtifactStorePort",
    "WebContextReadPort",
    "WebEvidenceAcceptancePort",
    "WebEvidenceAcceptanceResult",
    "WebEvidenceBundle",
    "WebEvidenceKind",
    "WebEvidenceSourceId",
    "WebObservationAdminPort",
    "WebObservationAdmissionPort",
    "WebObservationAttemptId",
    "WebObservationAttemptState",
    "WebObservationCustodyPort",
    "WebObservationDraft",
    "WebObservationInvocationResult",
    "WebObservationRecord",
    "WebObservationRequestId",
    "WebObservationRequestStatus",
    "WebObservationResultStatus",
    "WebObservationRuntimePort",
    "WebObservationToolAction",
    "WebObservationToolCallId",
    "WebObservationUsage",
    "WebObservationViolation",
    "WebResearchCommitContext",
    "WebResearchCommitPort",
    "WebResearchIntentDraft",
    "WebResearchIntentId",
    "WebResearchIntentPort",
    "WebResearchIntentStatus",
    "WebResearchRequestDraft",
    "WebResearchRuntimePort",
    "WebResearchViolation",
    "WebSourceReference",
)
