"""Stable public contract of the Prompt owner."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol, runtime_checkable
from uuid import UUID

from armi_kernel.application import ArtifactRef, CandidateFactClass, CandidateOwnerDraft
from armi_kernel.contracts import Digest, Instant, TraceId
from armi_runtime_foundation import PostgreSQLTransaction

CREATOR_PROMPT_PROJECTION_VERSION = "creator-prompt.v1"
MAX_CREATOR_PROMPT_BYTES = 65_536
_CREATOR_CODE = re.compile(
    r"^(?:ART|CON|CONFLICT|DB|SCOPE)-PROMPT-[A-Z0-9-]+$", re.ASCII
)


class PromptKind(StrEnum):
    PERSONALITY_ANCHOR = "personality_anchor"
    CREATOR_GUIDANCE = "creator_guidance"
    SUBJECT_GUIDANCE = "subject_guidance"


class PromptDocumentStatus(StrEnum):
    ACTIVE = "active"
    INACTIVE = "inactive"


class PromptRevisionKind(StrEnum):
    CREATED = "created"
    REVISED = "revised"
    DEACTIVATED = "deactivated"


class PromptViolation(RuntimeError):
    __slots__ = ("code",)

    def __init__(self, code: str) -> None:
        if type(code) is not str or not code.startswith("PROMPT-"):
            raise ValueError("Prompt violation code is invalid")
        self.code = code
        super().__init__("Prompt operation failed")

    def __str__(self) -> str:
        return f"{self.code}: Prompt operation failed"


class CreatorPromptViolation(RuntimeError):
    __slots__ = ("code",)

    def __init__(self, code: str) -> None:
        if type(code) is not str or _CREATOR_CODE.fullmatch(code) is None:
            raise ValueError("Creator Prompt violation code is invalid")
        self.code = code
        super().__init__("Creator Prompt operation failed")

    def __str__(self) -> str:
        return f"{self.code}: Creator Prompt operation failed"


@dataclass(frozen=True, slots=True)
class CandidatePromptDraft:
    proposal_ref: str
    atomic_group_ref: str
    basis_ordinals: tuple[int, ...]
    fact_class: CandidateFactClass
    prompt_document_id: UUID
    current_revision_id: UUID | None
    expected_revision_no: int
    content_bytes: bytes

    def __post_init__(self) -> None:
        from ._domain import validate_candidate

        validate_candidate(self)


@dataclass(frozen=True, slots=True)
class SubjectPromptHead:
    prompt_document_id: UUID
    current_revision_id: UUID | None
    revision_no: int


@dataclass(frozen=True, slots=True)
class PromptContextSource:
    source_id: UUID
    source_version: int
    artifact_id: UUID


@dataclass(frozen=True, slots=True)
class PromptContextSources:
    fixed: PromptContextSource
    creator: PromptContextSource | None
    subject: PromptContextSource | None


@dataclass(frozen=True, slots=True)
class PromptRecoveryState:
    fixed_artifact_id: UUID
    document_count: int
    fixed_revision_count: int


@dataclass(frozen=True, slots=True)
class PromptContinuityCounts:
    document_count: int
    revision_count: int


@dataclass(frozen=True, slots=True)
class CreatorPromptRevisionCommand:
    prompt_kind: PromptKind
    expected_revision_id: UUID | None
    content: str
    trace_id: TraceId

    def __post_init__(self) -> None:
        if type(self.content) is not str:
            raise CreatorPromptViolation("CON-PROMPT-CONTENT")
        try:
            content_bytes = self.content.encode("utf-8", errors="strict")
        except UnicodeError:
            raise CreatorPromptViolation("CON-PROMPT-CONTENT") from None
        if (
            type(self.prompt_kind) is not PromptKind
            or (
                self.expected_revision_id is not None
                and (
                    type(self.expected_revision_id) is not UUID
                    or self.expected_revision_id.version != 7
                )
            )
            or not self.content.strip()
            or "\x00" in self.content
            or not 1 <= len(content_bytes) <= MAX_CREATOR_PROMPT_BYTES
            or type(self.trace_id) is not TraceId
        ):
            raise CreatorPromptViolation("CON-PROMPT-CONTENT")

    @property
    def content_bytes(self) -> bytes:
        return self.content.encode("utf-8")


@dataclass(frozen=True, slots=True)
class CreatorPromptDeactivateCommand:
    prompt_kind: PromptKind
    expected_revision_id: UUID
    trace_id: TraceId

    def __post_init__(self) -> None:
        if (
            type(self.prompt_kind) is not PromptKind
            or type(self.expected_revision_id) is not UUID
            or self.expected_revision_id.version != 7
            or type(self.trace_id) is not TraceId
        ):
            raise CreatorPromptViolation("CON-PROMPT-COMMAND")


@dataclass(frozen=True, slots=True)
class CreatorPromptView:
    prompt_document_id: UUID
    prompt_kind: PromptKind
    status: PromptDocumentStatus
    current_revision_id: UUID | None
    revision_no: int | None
    previous_revision_id: UUID | None
    revision_kind: PromptRevisionKind | None
    content: str | None
    activated_at: Instant | None

    def __post_init__(self) -> None:
        from ._domain import validate_creator_view

        validate_creator_view(self)


@runtime_checkable
class PromptReadPort(Protocol):
    async def context_sources(
        self, transaction: PostgreSQLTransaction, *, subject_id: UUID
    ) -> PromptContextSources: ...

    async def candidate_subject(
        self,
        transaction: PostgreSQLTransaction,
        *,
        subject_id: UUID,
        expected_revision_id: UUID | None,
        expected_revision_no: int | None,
    ) -> SubjectPromptHead: ...

    async def recovery_state(
        self, transaction: PostgreSQLTransaction, *, subject_id: UUID
    ) -> PromptRecoveryState: ...


@runtime_checkable
class PromptCognitionPort(Protocol):
    def bind(self, value: CandidatePromptDraft) -> CandidateOwnerDraft: ...
    def decode(self, payload: bytes) -> CandidatePromptDraft: ...


@runtime_checkable
class PromptCommitPort(Protocol):
    async def heads_match(
        self,
        transaction: PostgreSQLTransaction,
        *,
        subject_id: UUID,
        drafts: tuple[CandidateOwnerDraft, ...],
    ) -> bool: ...

    async def commit(
        self,
        transaction: PostgreSQLTransaction,
        *,
        validation_id: UUID,
        subject_id: UUID,
        commit_id: UUID,
        drafts: tuple[CandidateOwnerDraft, ...],
        artifacts: dict[str, ArtifactRef],
    ) -> tuple[UUID, ...]: ...


@runtime_checkable
class PromptBirthPort(Protocol):
    async def initialize(
        self,
        transaction: PostgreSQLTransaction,
        *,
        subject_id: UUID,
        creator_party_id: UUID,
        anchor_artifact_id: UUID,
        anchor_content_digest: Digest,
    ) -> None: ...


@runtime_checkable
class CreatorPromptPort(Protocol):
    async def get(self, prompt_kind: PromptKind) -> CreatorPromptView: ...
    async def revise(
        self, command: CreatorPromptRevisionCommand
    ) -> CreatorPromptView: ...
    async def deactivate(
        self, command: CreatorPromptDeactivateCommand
    ) -> CreatorPromptView: ...


@runtime_checkable
class PromptAdminReferencePort(Protocol):
    def references_artifact(
        self, transaction: PostgreSQLTransaction, *, artifact_id: str
    ) -> bool: ...


def probe_prompt_continuity(
    conninfo: str, *, subject_id: UUID | None
) -> PromptContinuityCounts:
    from ._sync_postgresql import probe_prompt_continuity as probe

    return probe(conninfo, subject_id=subject_id)


__all__ = (
    "CREATOR_PROMPT_PROJECTION_VERSION",
    "MAX_CREATOR_PROMPT_BYTES",
    "CandidatePromptDraft",
    "CreatorPromptDeactivateCommand",
    "CreatorPromptPort",
    "CreatorPromptRevisionCommand",
    "CreatorPromptView",
    "CreatorPromptViolation",
    "PromptAdminReferencePort",
    "PromptBirthPort",
    "PromptCognitionPort",
    "PromptCommitPort",
    "PromptContextSource",
    "PromptContextSources",
    "PromptContinuityCounts",
    "PromptDocumentStatus",
    "PromptKind",
    "PromptReadPort",
    "PromptRecoveryState",
    "PromptRevisionKind",
    "PromptViolation",
    "SubjectPromptHead",
    "probe_prompt_continuity",
)
