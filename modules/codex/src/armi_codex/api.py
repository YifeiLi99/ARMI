"""Public contracts for governed Codex delegation and isolated execution."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable
from uuid import UUID

from armi_interaction.api import CreatorInputAcceptance
from armi_kernel.application import (
    ArtifactId,
    ArtifactPort,
    ArtifactRegistration,
    PublishedArtifact,
)
from armi_kernel.contracts import TraceId
from armi_runtime_foundation import PostgreSQLRuntimeUnitOfWork

from ._delegation_contract import (
    CodexCleanupStatus,
    CodexDelegationDraft,
    CodexDelegationPort,
    CodexDelegationViolation,
    CodexResultEvidence,
    CodexResultEvidenceKind,
    CodexResultSourceId,
    CodexTaskSourceAdmissionPort,
    CodexTaskSourceDraft,
    CodexTaskSourceId,
    CodexVerificationId,
    CodexVerificationResult,
    CodexVerificationStatus,
    CreatorCodexTaskAdmissionPort,
    CreatorCodexTaskCommand,
)
from ._runner_contract import (
    CodexExecutionId,
    CodexModel,
    CodexReasoningEffort,
    CodexRunnerPort,
    CodexRunnerViolation,
    CodexRunResult,
    CodexRunStatus,
    CodexTaskManifest,
    CodexUsage,
)


@dataclass(frozen=True, slots=True)
class CodexCommitContext:
    validation_id: UUID
    episode_id: UUID
    root_opportunity_id: UUID
    subject_id: UUID
    scene_id: UUID | None
    creator_party_id: UUID | None
    trace_id: TraceId

    def __post_init__(self) -> None:
        for value in (
            self.validation_id,
            self.episode_id,
            self.root_opportunity_id,
            self.subject_id,
        ):
            if type(value) is not UUID or value.version != 7:
                raise CodexDelegationViolation("CODEX-DELEGATION-COMMIT-CONTEXT")
        for value in (self.scene_id, self.creator_party_id):
            if value is not None and (type(value) is not UUID or value.version != 7):
                raise CodexDelegationViolation("CODEX-DELEGATION-COMMIT-CONTEXT")
        if type(self.trace_id) is not TraceId:
            raise CodexDelegationViolation("CODEX-DELEGATION-COMMIT-CONTEXT")


@runtime_checkable
class CodexCommitPort(Protocol):
    async def commit_delegations(
        self,
        unit_of_work: PostgreSQLRuntimeUnitOfWork,
        *,
        context: CodexCommitContext,
        commit_id: UUID,
        delegations: tuple[CodexDelegationDraft, ...],
    ) -> None: ...


@runtime_checkable
class CodexArtifactStorePort(ArtifactPort, Protocol):
    async def prepare(self) -> None: ...


@runtime_checkable
class CodexArtifactCatalogPort(Protocol):
    async def register(
        self,
        unit_of_work: PostgreSQLRuntimeUnitOfWork,
        artifact_id: ArtifactId,
        published: PublishedArtifact,
    ) -> ArtifactRegistration: ...


@runtime_checkable
class CodexTaskSourceRuntimePort(
    CodexTaskSourceAdmissionPort,
    CreatorCodexTaskAdmissionPort[CreatorInputAcceptance],
    Protocol,
): ...


@runtime_checkable
class CodexRuntimePort(CodexDelegationPort, Protocol):
    @property
    def task_sources(self) -> CodexTaskSourceRuntimePort: ...

    async def open(self) -> None: ...
    async def close(self) -> None: ...
    def stop(self) -> None: ...
    async def run_worker(self) -> None: ...


__all__ = (
    "CodexArtifactCatalogPort",
    "CodexArtifactStorePort",
    "CodexCleanupStatus",
    "CodexCommitContext",
    "CodexCommitPort",
    "CodexDelegationDraft",
    "CodexDelegationPort",
    "CodexDelegationViolation",
    "CodexExecutionId",
    "CodexModel",
    "CodexReasoningEffort",
    "CodexResultEvidence",
    "CodexResultEvidenceKind",
    "CodexResultSourceId",
    "CodexRunResult",
    "CodexRunStatus",
    "CodexRunnerPort",
    "CodexRunnerViolation",
    "CodexRuntimePort",
    "CodexTaskManifest",
    "CodexTaskSourceAdmissionPort",
    "CodexTaskSourceDraft",
    "CodexTaskSourceId",
    "CodexTaskSourceRuntimePort",
    "CodexUsage",
    "CodexVerificationId",
    "CodexVerificationResult",
    "CodexVerificationStatus",
    "CreatorCodexTaskAdmissionPort",
    "CreatorCodexTaskCommand",
)
