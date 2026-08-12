"""Technology-neutral contracts for typed web research and evidence custody."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol, runtime_checkable
from uuid import UUID

from armi_kernel.application import ArtifactId
from armi_kernel.contracts import Digest, IdempotencyKey, SubjectId, TraceId

from ._observation_contract import WebObservationAttemptId, WebObservationRequestId

_CODE = re.compile(r"^WEB-(?:RESEARCH|EVIDENCE)-[A-Z0-9-]+$", re.ASCII)
_REF = re.compile(r"^proposal:[1-9][0-9]{0,2}$", re.ASCII)
_GROUP = re.compile(r"^group:[1-9][0-9]{0,2}$", re.ASCII)
_MAX_QUERY_BYTES = 16 * 1024


class WebResearchIntentStatus(StrEnum):
    PENDING = "pending"
    ADMITTED = "admitted"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    UNKNOWN = "unknown"
    CANCELLED = "cancelled"


class WebEvidenceKind(StrEnum):
    PROVIDER_SYNTHESIS = "provider_synthesis"


class WebResearchViolation(RuntimeError):
    """Expose a stable failure without query, URL, or page content."""

    __slots__ = ("code",)

    def __init__(self, code: str) -> None:
        if type(code) is not str or _CODE.fullmatch(code) is None:
            raise ValueError("web research violation code is invalid")
        self.code = code
        super().__init__("web research evidence operation failed")

    def __str__(self) -> str:
        return f"{self.code}: web research evidence operation failed"


@dataclass(frozen=True, slots=True)
class WebResearchIntentId:
    value: UUID

    def __post_init__(self) -> None:
        _uuid7(self.value, "WEB-RESEARCH-INTENT-ID")


@dataclass(frozen=True, slots=True)
class WebEvidenceSourceId:
    value: UUID

    def __post_init__(self) -> None:
        _uuid7(self.value, "WEB-EVIDENCE-SOURCE-ID")


@dataclass(frozen=True, slots=True)
class WebResearchRequestDraft:
    proposal_ref: str
    atomic_group_ref: str
    basis_ordinals: tuple[int, ...]
    query_bytes: bytes
    purpose: str = "public_web_research"
    operation_class: str = "search_read_public"

    def __post_init__(self) -> None:
        if (
            type(self.proposal_ref) is not str
            or _REF.fullmatch(self.proposal_ref) is None
            or type(self.atomic_group_ref) is not str
            or _GROUP.fullmatch(self.atomic_group_ref) is None
            or type(self.basis_ordinals) is not tuple
            or not 1 <= len(self.basis_ordinals) <= 8
            or len(set(self.basis_ordinals)) != len(self.basis_ordinals)
            or any(
                type(value) is not int or not 1 <= value <= 999
                for value in self.basis_ordinals
            )
            or self.purpose != "public_web_research"
            or self.operation_class != "search_read_public"
        ):
            raise WebResearchViolation("WEB-RESEARCH-REQUEST")
        _query(self.query_bytes)


@dataclass(frozen=True, slots=True)
class WebResearchIntentDraft:
    intent_id: WebResearchIntentId
    subject_id: SubjectId
    source_opportunity_id: UUID
    subject_commit_id: UUID
    query: WebResearchRequestDraft
    query_artifact_id: ArtifactId
    idempotency_key: IdempotencyKey
    trace_id: TraceId

    def __post_init__(self) -> None:
        if (
            type(self.intent_id) is not WebResearchIntentId
            or type(self.subject_id) is not SubjectId
            or type(self.query) is not WebResearchRequestDraft
            or type(self.query_artifact_id) is not ArtifactId
            or type(self.idempotency_key) is not IdempotencyKey
            or type(self.trace_id) is not TraceId
        ):
            raise WebResearchViolation("WEB-RESEARCH-INTENT")
        _uuid7(self.source_opportunity_id, "WEB-RESEARCH-INTENT")
        _uuid7(self.subject_commit_id, "WEB-RESEARCH-INTENT")


@dataclass(frozen=True, slots=True)
class WebSourceReference:
    source_id: WebEvidenceSourceId
    ordinal: int
    canonical_url_digest: Digest
    source_artifact_id: ArtifactId

    def __post_init__(self) -> None:
        if (
            type(self.source_id) is not WebEvidenceSourceId
            or type(self.ordinal) is not int
            or not 1 <= self.ordinal <= 128
            or type(self.canonical_url_digest) is not Digest
            or type(self.source_artifact_id) is not ArtifactId
        ):
            raise WebResearchViolation("WEB-EVIDENCE-SOURCE")


@dataclass(frozen=True, slots=True)
class WebEvidenceBundle:
    evidence_artifact_id: ArtifactId
    result_artifact_id: ArtifactId
    request_id: WebObservationRequestId
    attempt_id: WebObservationAttemptId
    kind: WebEvidenceKind
    sources: tuple[WebSourceReference, ...]

    def __post_init__(self) -> None:
        if (
            type(self.evidence_artifact_id) is not ArtifactId
            or type(self.result_artifact_id) is not ArtifactId
            or type(self.request_id) is not WebObservationRequestId
            or type(self.attempt_id) is not WebObservationAttemptId
            or self.kind is not WebEvidenceKind.PROVIDER_SYNTHESIS
            or type(self.sources) is not tuple
            or not 1 <= len(self.sources) <= 128
            or tuple(source.ordinal for source in self.sources)
            != tuple(range(1, len(self.sources) + 1))
        ):
            raise WebResearchViolation("WEB-EVIDENCE-BUNDLE")


@dataclass(frozen=True, slots=True)
class WebEvidenceAcceptanceResult:
    intent_id: WebResearchIntentId
    request_id: WebObservationRequestId
    evidence_id: UUID
    opportunity_id: UUID

    def __post_init__(self) -> None:
        if (
            type(self.intent_id) is not WebResearchIntentId
            or type(self.request_id) is not WebObservationRequestId
        ):
            raise WebResearchViolation("WEB-EVIDENCE-ACCEPTANCE")
        _uuid7(self.evidence_id, "WEB-EVIDENCE-ACCEPTANCE")
        _uuid7(self.opportunity_id, "WEB-EVIDENCE-ACCEPTANCE")


@runtime_checkable
class WebResearchIntentPort(Protocol):
    async def admit_once(self) -> bool:
        """Admit at most one durable, already committed research intent."""
        ...


@runtime_checkable
class WebEvidenceAcceptancePort(Protocol):
    async def accept(
        self,
        *,
        intent_id: WebResearchIntentId,
        bundle: WebEvidenceBundle,
    ) -> WebEvidenceAcceptanceResult: ...


def _query(value: object) -> None:
    if type(value) is not bytes or not value or len(value) > _MAX_QUERY_BYTES:
        raise WebResearchViolation("WEB-RESEARCH-QUERY")
    try:
        text = value.decode("utf-8", errors="strict")
    except UnicodeDecodeError:
        raise WebResearchViolation("WEB-RESEARCH-QUERY") from None
    if "\x00" in text or not text.strip():
        raise WebResearchViolation("WEB-RESEARCH-QUERY")


def _uuid7(value: object, code: str) -> None:
    if type(value) is not UUID or value.version != 7:
        raise WebResearchViolation(code)


__all__ = (
    "WebEvidenceAcceptancePort",
    "WebEvidenceAcceptanceResult",
    "WebEvidenceBundle",
    "WebEvidenceKind",
    "WebEvidenceSourceId",
    "WebResearchIntentDraft",
    "WebResearchIntentId",
    "WebResearchIntentPort",
    "WebResearchIntentStatus",
    "WebResearchRequestDraft",
    "WebResearchViolation",
    "WebSourceReference",
)
