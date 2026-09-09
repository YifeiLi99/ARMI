"""Creator media intake contracts, independent of local upload transport."""

from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from armi_kernel.contracts import Digest, IdempotencyKey, TraceId

from ._creator_contract import CreatorInputCommand, CreatorInputViolation
from ._scene_contract import SceneKey


@dataclass(frozen=True, slots=True)
class CreatorMediaAttachment:
    artifact_id: UUID
    file_name: str
    media_type: str
    byte_size: int
    content_digest: Digest
    kind: str

    def __post_init__(self) -> None:
        if (
            self.artifact_id.version != 7
            or self.kind not in {"image", "audio", "video", "file"}
            or not self.file_name
            or len(self.file_name) > 255
            or any(char in self.file_name for char in "\\/\x00")
            or not 1 <= self.byte_size <= 45 * 1024 * 1024
        ):
            raise CreatorInputViolation("CON-INPUT-ATTACHMENT")


@dataclass(frozen=True, slots=True)
class CreatorMediaCommand:
    scene_key: str
    message: str
    attachments: tuple[CreatorMediaAttachment, ...]
    idempotency_key: IdempotencyKey
    trace_id: TraceId
    delegate_id: UUID

    def __post_init__(self) -> None:
        SceneKey(self.scene_key)
        if not 1 <= len(self.attachments) <= 8 or self.delegate_id.version != 7:
            raise CreatorInputViolation("CON-INPUT-ATTACHMENT")
        if self.message:
            CreatorInputCommand(
                self.scene_key,
                self.message,
                self.idempotency_key,
                self.trace_id,
                self.delegate_id,
            )


@dataclass(frozen=True, slots=True)
class CreatorAttachmentStatus:
    ordinal: int
    file_name: str
    status: str
    error_code: str | None


@dataclass(frozen=True, slots=True)
class CreatorMediaStatus:
    interaction_id: UUID
    recognition_status: str
    opportunity_id: UUID | None
    attachments: tuple[CreatorAttachmentStatus, ...]
    processing_failure: str | None = None


class CreatorMediaPort(Protocol):
    async def accept_media(self, command: CreatorMediaCommand) -> UUID: ...
    async def media_status(self, interaction_id: UUID) -> CreatorMediaStatus | None: ...


__all__ = (
    "CreatorAttachmentStatus",
    "CreatorMediaAttachment",
    "CreatorMediaCommand",
    "CreatorMediaPort",
    "CreatorMediaStatus",
)
