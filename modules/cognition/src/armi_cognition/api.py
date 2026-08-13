"""Public contracts for model execution and candidate validation."""

from __future__ import annotations

import asyncio
from typing import Protocol, runtime_checkable

from armi_kernel.application import (
    ArtifactId,
    ArtifactRegistration,
    ModelBinding,
    ModelInvocationResult,
    ModelRequest,
    PublishedArtifact,
)
from armi_runtime_foundation import PostgreSQLRuntimeUnitOfWork

from ._contracts import (
    CandidateValidationResult,
    CandidateValidationStatus,
    CandidateValidator,
    SubjectChangeSet,
)


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


__all__ = (
    "CandidateValidationResult",
    "CandidateValidationStatus",
    "CandidateValidator",
    "CognitionArtifactCatalogPort",
    "CognitionCandidateParser",
    "CognitionCandidateValue",
    "CognitionModelAdapterFactory",
    "CognitionModelPort",
    "CognitionWakeupPort",
    "CognitionWorkerPort",
    "SubjectChangeSet",
)
