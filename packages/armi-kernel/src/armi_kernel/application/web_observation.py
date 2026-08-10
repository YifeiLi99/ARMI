"""Technology-neutral read-only web observation custody contracts."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol, runtime_checkable
from uuid import UUID

from armi_kernel.contracts import Digest, IdempotencyKey, SubjectId, TraceId

from .artifacts import ArtifactId
from .durable_work import WorkId
from .runtime_authority import RuntimeFence

_CODE = re.compile(r"^WEB-[A-Z0-9-]+$", re.ASCII)
_MAX_QUERY_BYTES = 16 * 1024


class WebObservationRequestStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    UNKNOWN = "unknown"
    CANCELLED = "cancelled"


class WebObservationAttemptState(StrEnum):
    PREPARED = "prepared"
    DISPATCHED = "dispatched"
    SETTLED = "settled"


class WebObservationResultStatus(StrEnum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    OUTCOME_UNKNOWN = "outcome_unknown"
    CANCELLED = "cancelled"


class WebObservationToolAction(StrEnum):
    SEARCH = "search"
    OPEN_PAGE = "open_page"
    FIND_IN_PAGE = "find_in_page"


class WebObservationViolation(RuntimeError):
    """Expose one stable failure code without query, URL or provider content."""

    __slots__ = ("code", "outcome_unknown", "retryable")

    def __init__(
        self,
        code: str,
        *,
        retryable: bool = False,
        outcome_unknown: bool = False,
    ) -> None:
        if type(code) is not str or _CODE.fullmatch(code) is None:
            raise ValueError("web observation violation code is invalid")
        if type(retryable) is not bool or type(outcome_unknown) is not bool:
            raise ValueError("web observation violation flags are invalid")
        self.code = code
        self.retryable = retryable
        self.outcome_unknown = outcome_unknown
        super().__init__("web observation operation failed")

    def __str__(self) -> str:
        return f"{self.code}: web observation operation failed"


@dataclass(frozen=True, slots=True)
class WebObservationRequestId:
    value: UUID

    def __post_init__(self) -> None:
        _uuid7(self.value, "WEB-REQUEST-ID")


@dataclass(frozen=True, slots=True)
class WebObservationAttemptId:
    value: UUID

    def __post_init__(self) -> None:
        _uuid7(self.value, "WEB-ATTEMPT-ID")


@dataclass(frozen=True, slots=True)
class WebObservationToolCallId:
    value: UUID

    def __post_init__(self) -> None:
        _uuid7(self.value, "WEB-TOOL-CALL-ID")


@dataclass(frozen=True, slots=True)
class WebObservationDraft:
    request_id: WebObservationRequestId
    subject_id: SubjectId
    runtime_fence: RuntimeFence
    idempotency_key: IdempotencyKey
    query_bytes: bytes
    trace_id: TraceId
    purpose: str = "public_web_research"
    operation_class: str = "search_read_public"

    def __post_init__(self) -> None:
        if (
            type(self.request_id) is not WebObservationRequestId
            or type(self.subject_id) is not SubjectId
            or type(self.runtime_fence) is not RuntimeFence
            or self.runtime_fence.subject_id != self.subject_id.value
            or type(self.idempotency_key) is not IdempotencyKey
            or type(self.trace_id) is not TraceId
            or self.purpose != "public_web_research"
            or self.operation_class != "search_read_public"
        ):
            raise WebObservationViolation("WEB-REQUEST")
        _query(self.query_bytes)


@dataclass(frozen=True, slots=True)
class WebObservationRecord:
    request_id: WebObservationRequestId
    subject_id: SubjectId
    status: WebObservationRequestStatus
    request_digest: Digest
    request_artifact_id: ArtifactId
    work_id: WorkId
    attempt_count: int
    result_artifact_id: ArtifactId | None = None
    error_code: str | None = None

    def __post_init__(self) -> None:
        if (
            type(self.request_id) is not WebObservationRequestId
            or type(self.subject_id) is not SubjectId
            or type(self.status) is not WebObservationRequestStatus
            or type(self.request_digest) is not Digest
            or type(self.request_artifact_id) is not ArtifactId
            or type(self.work_id) is not WorkId
            or type(self.attempt_count) is not int
            or not 0 <= self.attempt_count <= 2
        ):
            raise WebObservationViolation("WEB-RECORD")
        success = self.status is WebObservationRequestStatus.SUCCEEDED
        if success != (type(self.result_artifact_id) is ArtifactId):
            raise WebObservationViolation("WEB-RECORD")
        if self.error_code is not None and _CODE.fullmatch(self.error_code) is None:
            raise WebObservationViolation("WEB-RECORD")
        if (
            self.status
            in {
                WebObservationRequestStatus.FAILED,
                WebObservationRequestStatus.UNKNOWN,
            }
            and self.error_code is None
        ):
            raise WebObservationViolation("WEB-RECORD")


@dataclass(frozen=True, slots=True)
class WebObservationUsage:
    input_tokens: int
    output_tokens: int
    web_search_calls: int
    citation_count: int
    estimated_cost_microyuan: int

    def __post_init__(self) -> None:
        for value in (
            self.input_tokens,
            self.output_tokens,
            self.web_search_calls,
            self.citation_count,
            self.estimated_cost_microyuan,
        ):
            if type(value) is not int or value < 0:
                raise WebObservationViolation("WEB-USAGE")
        if not 1 <= self.web_search_calls <= 8 or not 1 <= self.citation_count <= 128:
            raise WebObservationViolation("WEB-USAGE")
        if self.estimated_cost_microyuan > 1_000_000:
            raise WebObservationViolation("WEB-BUDGET")


@dataclass(frozen=True, slots=True)
class WebObservationInvocationResult:
    status: WebObservationResultStatus
    provider_model_id: str | None
    canonical_result_bytes: bytes | None
    tool_actions: tuple[WebObservationToolAction, ...]
    usage: WebObservationUsage | None
    error_code: str | None = None

    def __post_init__(self) -> None:
        if type(self.status) is not WebObservationResultStatus:
            raise WebObservationViolation("WEB-RESULT")
        success = self.status is WebObservationResultStatus.SUCCEEDED
        if success:
            if (
                type(self.provider_model_id) is not str
                or not self.provider_model_id.startswith("doubao-seed-evolving")
                or type(self.canonical_result_bytes) is not bytes
                or not self.canonical_result_bytes
                or len(self.canonical_result_bytes) > 1024 * 1024
                or not 1 <= len(self.tool_actions) <= 8
                or any(
                    type(item) is not WebObservationToolAction
                    for item in self.tool_actions
                )
                or type(self.usage) is not WebObservationUsage
                or self.error_code is not None
            ):
                raise WebObservationViolation("WEB-RESULT")
        elif self.error_code is None or _CODE.fullmatch(self.error_code) is None:
            raise WebObservationViolation("WEB-RESULT")


@runtime_checkable
class WebObservationAdmissionPort(Protocol):
    async def admit(self, draft: WebObservationDraft) -> WebObservationRecord: ...


@runtime_checkable
class WebObservationCustodyPort(Protocol):
    async def invoke_once(self) -> bool:
        """Settle at most one durable web observation responsibility."""
        ...


def _uuid7(value: object, code: str) -> None:
    if type(value) is not UUID or value.version != 7:
        raise WebObservationViolation(code)


def _query(value: object) -> None:
    if type(value) is not bytes or not value or len(value) > _MAX_QUERY_BYTES:
        raise WebObservationViolation("WEB-QUERY")
    try:
        text = value.decode("utf-8", errors="strict")
    except UnicodeDecodeError:
        raise WebObservationViolation("WEB-QUERY") from None
    if "\x00" in text or not text.strip():
        raise WebObservationViolation("WEB-QUERY")


__all__ = (
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
    "WebObservationToolAction",
    "WebObservationToolCallId",
    "WebObservationUsage",
    "WebObservationViolation",
)
