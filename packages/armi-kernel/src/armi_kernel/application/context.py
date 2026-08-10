"""Technology-neutral Context snapshot and compilation contracts."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol, runtime_checkable
from uuid import UUID

from armi_kernel.contracts import Instant, Purpose

_TOKEN = re.compile(r"^[a-z][a-z0-9._-]{0,63}$", re.ASCII)
_CODE = re.compile(r"^CTX-[A-Z0-9-]+$", re.ASCII)


class ContextViolation(RuntimeError):
    """Expose one stable Context failure without source content or adapter detail."""

    __slots__ = ("code",)

    def __init__(self, code: str) -> None:
        if type(code) is not str or _CODE.fullmatch(code) is None:
            raise ValueError("context violation code is invalid")
        self.code = code
        super().__init__("context operation failed")

    def __str__(self) -> str:
        return f"{self.code}: context operation failed"


class CognitiveEpisodeStatus(StrEnum):
    PREPARING = "preparing"
    PREPARED = "prepared"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ContextSection(StrEnum):
    RUNTIME_TRUTH = "runtime_truth"
    PURPOSE = "purpose"
    SELF = "self"
    MIND = "mind"
    LIFE_MODE = "life_mode"
    SCENE = "scene"
    RELATIONSHIP = "relationship"
    MEMORY = "memory"
    ACTIVITY = "activity"
    MATERIAL = "material"
    EVIDENCE = "evidence"
    CAPABILITY = "capability"
    PROMPT = "prompt"


class ContextItemDisposition(StrEnum):
    INCLUDED = "included"
    EXCLUDED_POLICY = "excluded_policy"
    EXCLUDED_BUDGET = "excluded_budget"
    UNAVAILABLE = "unavailable"
    READ_FAILED = "read_failed"


class ContextTrustClass(StrEnum):
    RUNTIME_AUTHORITY = "runtime_authority"
    SUBJECTIVE_STATE = "subjective_state"
    EXTERNAL_CLAIM = "external_claim"
    POLICY = "policy"


@dataclass(frozen=True, slots=True)
class CognitiveEpisodeId:
    value: UUID

    def __post_init__(self) -> None:
        _require_uuid7(self.value)

    def __str__(self) -> str:
        return str(self.value)


@dataclass(frozen=True, slots=True)
class ContextSourceIdentity:
    kind: str
    reference: UUID | None
    version: int | None

    def __post_init__(self) -> None:
        _require_token(self.kind)
        present = (self.reference is not None, self.version is not None)
        if any(present) and not all(present):
            raise ContextViolation("CTX-SOURCE-IDENTITY")
        if self.reference is not None:
            _require_uuid7(self.reference)
            if type(self.version) is not int or self.version < 0:
                raise ContextViolation("CTX-SOURCE-IDENTITY")


@dataclass(frozen=True, slots=True)
class ContextItemCandidate:
    section: ContextSection
    item_kind: str
    source: ContextSourceIdentity
    trust_class: ContextTrustClass
    privacy_scope: str
    content: str | None
    required: bool
    relevance: int
    business_time: Instant | None = None
    unavailable_reason: str | None = None

    def __post_init__(self) -> None:
        if (
            type(self.section) is not ContextSection
            or type(self.source) is not ContextSourceIdentity
            or type(self.trust_class) is not ContextTrustClass
        ):
            raise ContextViolation("CTX-ITEM")
        _require_token(self.item_kind)
        _require_token(self.privacy_scope)
        if type(self.required) is not bool:
            raise ContextViolation("CTX-ITEM")
        if type(self.relevance) is not int or not 0 <= self.relevance <= 100:
            raise ContextViolation("CTX-ITEM")
        if self.business_time is not None and type(self.business_time) is not Instant:
            raise ContextViolation("CTX-ITEM")
        if self.content is None:
            if self.source.reference is not None or self.required:
                raise ContextViolation("CTX-ITEM")
            if (
                type(self.unavailable_reason) is not str
                or _CODE.fullmatch(self.unavailable_reason) is None
            ):
                raise ContextViolation("CTX-ITEM")
        elif self.unavailable_reason is not None:
            raise ContextViolation("CTX-ITEM")
        try:
            self.content.encode("utf-8", errors="strict") if self.content else b""
        except UnicodeEncodeError:
            raise ContextViolation("CTX-UNICODE") from None


@dataclass(frozen=True, slots=True)
class ContextRequest:
    purpose: Purpose
    subject_id: UUID
    scene_id: UUID | None
    base_subject_version: int
    base_state_epoch: int
    bundle_activation_id: UUID
    policy_version: str
    mechanism_identity: str
    max_items: int
    max_item_bytes: int
    max_compiled_bytes: int
    items: tuple[ContextItemCandidate, ...]

    def __post_init__(self) -> None:
        if type(self.purpose) is not Purpose:
            raise ContextViolation("CTX-REQUEST")
        for value in (self.subject_id, self.bundle_activation_id):
            _require_uuid7(value)
        if self.scene_id is not None:
            _require_uuid7(self.scene_id)
        for value in (self.base_subject_version, self.base_state_epoch):
            if type(value) is not int or value < 0:
                raise ContextViolation("CTX-REQUEST")
        _require_token(self.policy_version)
        _require_token(self.mechanism_identity)
        if (
            type(self.max_items) is not int
            or not 1 <= self.max_items <= 1024
            or type(self.max_item_bytes) is not int
            or self.max_item_bytes <= 0
            or type(self.max_compiled_bytes) is not int
            or self.max_compiled_bytes <= 0
        ):
            raise ContextViolation("CTX-BUDGET")
        if type(self.items) is not tuple or any(
            type(item) is not ContextItemCandidate for item in self.items
        ):
            raise ContextViolation("CTX-REQUEST")


@dataclass(frozen=True, slots=True)
class ContextItemResult:
    candidate: ContextItemCandidate
    ordinal: int
    disposition: ContextItemDisposition
    content_bytes: int
    reason_code: str | None = None

    def __post_init__(self) -> None:
        if (
            type(self.candidate) is not ContextItemCandidate
            or type(self.ordinal) is not int
            or self.ordinal <= 0
            or type(self.disposition) is not ContextItemDisposition
            or type(self.content_bytes) is not int
            or self.content_bytes < 0
        ):
            raise ContextViolation("CTX-RESULT")
        if self.reason_code is not None and _CODE.fullmatch(self.reason_code) is None:
            raise ContextViolation("CTX-RESULT")


@dataclass(frozen=True, slots=True)
class CompiledContext:
    canonical_bytes: bytes

    def __post_init__(self) -> None:
        if type(self.canonical_bytes) is not bytes or not self.canonical_bytes:
            raise ContextViolation("CTX-COMPILED")


@dataclass(frozen=True, slots=True)
class ContextResult:
    manifest_bytes: bytes
    compiled: CompiledContext
    items: tuple[ContextItemResult, ...]

    def __post_init__(self) -> None:
        if (
            type(self.manifest_bytes) is not bytes
            or not self.manifest_bytes
            or type(self.compiled) is not CompiledContext
            or type(self.items) is not tuple
            or any(type(item) is not ContextItemResult for item in self.items)
        ):
            raise ContextViolation("CTX-RESULT")


@runtime_checkable
class ContextCompiler(Protocol):
    def compile(self, request: ContextRequest) -> ContextResult:
        """Compile only the supplied immutable snapshot."""
        ...


@runtime_checkable
class OpportunitySelector(Protocol):
    async def select_once(self) -> CognitiveEpisodeId | None:
        """Select at most one durable opportunity through the authoritative owner."""
        ...


def _require_uuid7(value: object) -> None:
    if type(value) is not UUID or value.version != 7:
        raise ContextViolation("CTX-ID")


def _require_token(value: object) -> None:
    if type(value) is not str or _TOKEN.fullmatch(value) is None:
        raise ContextViolation("CTX-TOKEN")


__all__ = (
    "CognitiveEpisodeId",
    "CognitiveEpisodeStatus",
    "CompiledContext",
    "ContextCompiler",
    "ContextItemCandidate",
    "ContextItemDisposition",
    "ContextItemResult",
    "ContextRequest",
    "ContextResult",
    "ContextSection",
    "ContextSourceIdentity",
    "ContextTrustClass",
    "ContextViolation",
    "OpportunitySelector",
)
