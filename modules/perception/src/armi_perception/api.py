"""Public contracts for deterministic and provider-backed external perception."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol, runtime_checkable
from uuid import UUID

from armi_interaction.api import (
    ExternalAccountKey,
    ExternalChannel,
    ExternalMessagePartKind,
    ExternalMessageViolation,
    ExternalVisualRole,
)
from armi_kernel.application import (
    ArtifactId,
    ArtifactRegistration,
    PublishedArtifact,
    WorkLease,
    WorkRecord,
)
from armi_kernel.contracts import Instant, TraceId
from armi_runtime_foundation import (
    PostgreSQLAdminTransaction,
    PostgreSQLRuntimeUnitOfWork,
    StopSignal,
)

_SOURCE_KIND = re.compile(r"^[a-z][a-z0-9._-]{0,63}$", re.ASCII)


@dataclass(frozen=True, slots=True)
class ExternalMediaContent:
    content: bytes
    file_name: str
    media_type: str

    def __post_init__(self) -> None:
        if (
            type(self.content) is not bytes
            or not self.content
            or type(self.file_name) is not str
            or not self.file_name
            or "\x00" in self.file_name
            or type(self.media_type) is not str
            or not self.media_type
            or "\x00" in self.media_type
        ):
            raise ExternalMessageViolation("CON-EXTERNAL-MESSAGE-MEDIA")


@runtime_checkable
class ExternalMediaFetchPort(Protocol):
    async def fetch(
        self,
        *,
        channel: ExternalChannel,
        account_key: ExternalAccountKey,
        kind: ExternalMessagePartKind,
        locator: str,
        max_bytes: int,
    ) -> ExternalMediaContent: ...


class ExternalContentRecognitionStatus(StrEnum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class ExternalContentRecognitionRequest:
    kind: ExternalMessagePartKind
    content: bytes
    file_name: str
    media_type: str
    trace_id: TraceId
    visual_role: ExternalVisualRole | None = None
    source_kind: str | None = None
    source_summary: str | None = None
    visual_inputs: tuple[ExternalMediaContent, ...] = ()

    def __post_init__(self) -> None:
        if (
            self.kind
            not in {
                ExternalMessagePartKind.IMAGE,
                ExternalMessagePartKind.AUDIO,
                ExternalMessagePartKind.VIDEO,
                ExternalMessagePartKind.FILE,
            }
            or type(self.content) is not bytes
            or not self.content
            or type(self.file_name) is not str
            or not self.file_name
            or "\x00" in self.file_name
            or type(self.media_type) is not str
            or not self.media_type
            or type(self.trace_id) is not TraceId
        ):
            raise ExternalMessageViolation("CON-EXTERNAL-MESSAGE-RECOGNITION")
        if self.kind is ExternalMessagePartKind.IMAGE:
            if (
                type(self.visual_role) is not ExternalVisualRole
                or type(self.source_kind) is not str
                or _SOURCE_KIND.fullmatch(self.source_kind) is None
                or (
                    self.source_summary is not None
                    and (
                        type(self.source_summary) is not str
                        or not self.source_summary.strip()
                        or "\x00" in self.source_summary
                        or len(self.source_summary.encode("utf-8")) > 512
                    )
                )
                or type(self.visual_inputs) is not tuple
                or not 1 <= len(self.visual_inputs) <= 4
                or any(
                    type(item) is not ExternalMediaContent
                    for item in self.visual_inputs
                )
            ):
                raise ExternalMessageViolation("CON-EXTERNAL-MESSAGE-RECOGNITION")
        elif (
            any(
                value is not None
                for value in (self.visual_role, self.source_kind, self.source_summary)
            )
            or self.visual_inputs
        ):
            raise ExternalMessageViolation("CON-EXTERNAL-MESSAGE-RECOGNITION")


@dataclass(frozen=True, slots=True)
class ExternalContentRecognitionResult:
    status: ExternalContentRecognitionStatus
    text: str | None
    provider: str
    model_id: str
    response_model_id: str | None
    provider_request_id: str | None
    input_tokens: int | None
    output_tokens: int | None
    raw_response: bytes | None
    error_code: str | None

    def __post_init__(self) -> None:
        if (
            type(self.status) is not ExternalContentRecognitionStatus
            or type(self.provider) is not str
            or not self.provider
            or type(self.model_id) is not str
            or not self.model_id
        ):
            raise ExternalMessageViolation("CON-EXTERNAL-MESSAGE-RECOGNITION")
        if self.status is ExternalContentRecognitionStatus.SUCCEEDED:
            if (
                type(self.text) is not str
                or not self.text.strip()
                or type(self.raw_response) is not bytes
                or not self.raw_response
                or self.error_code is not None
            ):
                raise ExternalMessageViolation("CON-EXTERNAL-MESSAGE-RECOGNITION")
        elif self.text is not None or not self.error_code:
            raise ExternalMessageViolation("CON-EXTERNAL-MESSAGE-RECOGNITION")
        for value in (
            self.response_model_id,
            self.provider_request_id,
            self.error_code,
        ):
            if value is not None and (
                type(value) is not str or not value or "\x00" in value
            ):
                raise ExternalMessageViolation("CON-EXTERNAL-MESSAGE-RECOGNITION")
        for value in (self.input_tokens, self.output_tokens):
            if value is not None and (type(value) is not int or value < 0):
                raise ExternalMessageViolation("CON-EXTERNAL-MESSAGE-RECOGNITION")
        if self.raw_response is not None and type(self.raw_response) is not bytes:
            raise ExternalMessageViolation("CON-EXTERNAL-MESSAGE-RECOGNITION")


@runtime_checkable
class ExternalContentRecognitionPort(Protocol):
    async def recognize(
        self, request: ExternalContentRecognitionRequest
    ) -> ExternalContentRecognitionResult: ...


@runtime_checkable
class PerceptionArtifactCatalogPort(Protocol):
    async def register(
        self,
        unit_of_work: PostgreSQLRuntimeUnitOfWork,
        artifact_id: ArtifactId,
        published: PublishedArtifact,
    ) -> ArtifactRegistration: ...


@runtime_checkable
class PerceptionDurableWorkPort(Protocol):
    async def failed_owner_refs(self, *, work_kind: str) -> tuple[UUID, ...]: ...

    async def claim(
        self,
        *,
        work_kind: str,
        lease_owner: UUID,
        lease_seconds: int,
        limit: int = 1,
    ) -> tuple[WorkRecord, ...]: ...

    async def fail(self, lease: WorkLease, *, error_code: str) -> WorkRecord: ...

    async def release(
        self,
        lease: WorkLease,
        *,
        not_before: Instant,
        error_code: str | None = None,
    ) -> WorkRecord: ...


@runtime_checkable
class PerceptionWakeupPort(Protocol):
    def version(self, channel: str) -> int: ...
    def notify(self, channel: str) -> None: ...
    async def wait(
        self,
        channel: str,
        after_version: int,
        *,
        stop: StopSignal,
        timeout_seconds: float,
    ) -> int: ...


@runtime_checkable
class PerceptionWorkerPort(Protocol):
    async def open(self) -> None: ...
    async def close(self) -> None: ...
    def stop(self) -> None: ...
    async def execute_once(self) -> bool: ...
    async def run_worker(self) -> None: ...


@runtime_checkable
class PerceptionAdminPort(Protocol):
    def artifact_reference_count(
        self, transaction: PostgreSQLAdminTransaction, *, artifact_id: UUID
    ) -> int: ...


__all__ = (
    "ExternalContentRecognitionPort",
    "ExternalContentRecognitionRequest",
    "ExternalContentRecognitionResult",
    "ExternalContentRecognitionStatus",
    "ExternalMediaContent",
    "ExternalMediaFetchPort",
    "PerceptionAdminPort",
    "PerceptionArtifactCatalogPort",
    "PerceptionDurableWorkPort",
    "PerceptionWakeupPort",
    "PerceptionWorkerPort",
)
