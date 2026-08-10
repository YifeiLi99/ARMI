"""Creator-owned Prompt command and query contracts."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol, runtime_checkable
from uuid import UUID

from armi_kernel.contracts import Instant, TraceId

CREATOR_PROMPT_PROJECTION_VERSION = "creator-prompt.v1"
MAX_CREATOR_PROMPT_BYTES = 65_536
_CODE = re.compile(
    r"^(?:ART|CON|CONFLICT|DB|SCOPE)-PROMPT-[A-Z0-9-]+$",
    re.ASCII,
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


class CreatorPromptViolation(RuntimeError):
    __slots__ = ("code",)

    def __init__(self, code: str) -> None:
        if type(code) is not str or _CODE.fullmatch(code) is None:
            raise ValueError("Creator Prompt violation code is invalid")
        self.code = code
        super().__init__("Creator Prompt operation failed")

    def __str__(self) -> str:
        return f"{self.code}: Creator Prompt operation failed"


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
        revision_values = (
            self.current_revision_id,
            self.revision_no,
            self.revision_kind,
            self.content,
            self.activated_at,
        )
        has_revision = self.current_revision_id is not None
        if (
            type(self.prompt_document_id) is not UUID
            or self.prompt_document_id.version != 7
            or self.prompt_kind is not PromptKind.CREATOR_GUIDANCE
            or type(self.status) is not PromptDocumentStatus
            or has_revision != all(value is not None for value in revision_values)
            or (not has_revision and self.status is not PromptDocumentStatus.ACTIVE)
            or (
                self.revision_kind is PromptRevisionKind.DEACTIVATED
                and self.status is not PromptDocumentStatus.INACTIVE
            )
            or (
                self.revision_kind
                in (
                    PromptRevisionKind.CREATED,
                    PromptRevisionKind.REVISED,
                )
                and self.status is not PromptDocumentStatus.ACTIVE
            )
            or (
                self.current_revision_id is not None
                and (
                    type(self.current_revision_id) is not UUID
                    or self.current_revision_id.version != 7
                )
            )
            or (
                self.previous_revision_id is not None
                and (
                    type(self.previous_revision_id) is not UUID
                    or self.previous_revision_id.version != 7
                )
            )
            or (
                self.revision_no is not None
                and (type(self.revision_no) is not int or self.revision_no < 1)
            )
            or (self.revision_no == 1 and self.previous_revision_id is not None)
            or (
                self.revision_no is not None
                and self.revision_no > 1
                and self.previous_revision_id is None
            )
        ):
            raise CreatorPromptViolation("CON-PROMPT-VIEW")
        if self.content is not None:
            try:
                encoded = self.content.encode("utf-8", errors="strict")
            except UnicodeError:
                raise CreatorPromptViolation("CON-PROMPT-VIEW") from None
            if (
                not self.content.strip()
                or "\x00" in self.content
                or not 1 <= len(encoded) <= MAX_CREATOR_PROMPT_BYTES
            ):
                raise CreatorPromptViolation("CON-PROMPT-VIEW")


@runtime_checkable
class CreatorPromptPort(Protocol):
    async def get(self, prompt_kind: PromptKind) -> CreatorPromptView: ...

    async def revise(
        self,
        command: CreatorPromptRevisionCommand,
    ) -> CreatorPromptView: ...

    async def deactivate(
        self,
        command: CreatorPromptDeactivateCommand,
    ) -> CreatorPromptView: ...


__all__ = (
    "CREATOR_PROMPT_PROJECTION_VERSION",
    "MAX_CREATOR_PROMPT_BYTES",
    "CreatorPromptDeactivateCommand",
    "CreatorPromptPort",
    "CreatorPromptRevisionCommand",
    "CreatorPromptView",
    "CreatorPromptViolation",
    "PromptDocumentStatus",
    "PromptKind",
    "PromptRevisionKind",
)
