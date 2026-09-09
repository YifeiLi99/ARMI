"""Creator attachment admission and its stable operation reference."""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from dataclasses import asdict
from pathlib import Path
from typing import Any, Literal, Self, cast
from uuid import UUID, uuid7

from armi_interaction.api import (
    CreatorInputViolation,
    CreatorMediaAttachment,
    CreatorMediaCommand,
    CreatorMediaPort,
    CreatorOperation,
)
from armi_kernel.contracts import Digest, IdempotencyKey, TraceId
from pydantic import BaseModel, ConfigDict, Field, RootModel, model_validator

from .creator_contract import (
    AcceptedOutcomeResponse,
    OperationOutcomeResponse,
    RejectedOutcomeResponse,
    UnavailableOutcomeResponse,
)
from .media_uploads import MediaUploads, UploadViolation


class MediaMessageRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    scene_key: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]{0,63}$")
    idempotency_key: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
    message: str = Field(default="", max_length=262144)
    attachments: list[UUID] = Field(default_factory=list[UUID], max_length=8)

    @model_validator(mode="after")
    def content_required(self) -> Self:
        if not self.message.strip() and not self.attachments:
            raise ValueError("INPUT-CONTENT-REQUIRED")
        return self


class MediaAttachmentResult(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    ordinal: int = Field(ge=1)
    file_name: str
    status: Literal["pending", "succeeded", "failed", "unknown", "skipped"]
    error_code: str | None


class MediaProgress(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    stage: str


class MediaOperationResult(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    status: Literal[
        "accepted",
        "waiting",
        "applied",
        "completed",
        "failed",
        "unknown",
        "partial",
        "rejected",
        "unavailable",
    ]
    result_ref: UUID
    interaction_id: UUID
    recognition_status: Literal["pending", "succeeded", "failed", "unknown", "skipped"]
    attachments: list[MediaAttachmentResult]
    details: MediaProgress
    cognition: OperationOutcomeResponse | None = None


class MediaMessageResult(
    RootModel[
        AcceptedOutcomeResponse
        | MediaOperationResult
        | RejectedOutcomeResponse
        | UnavailableOutcomeResponse
    ]
):
    pass


class MediaOrOperationResult(
    RootModel[OperationOutcomeResponse | MediaOperationResult]
):
    pass


class CreatorMedia:
    def __init__(self, uploads: MediaUploads, inputs: CreatorMediaPort) -> None:
        self.uploads = uploads
        self.inputs = inputs

    async def send(
        self, arguments: dict[str, Any], creator: UUID, delegate: UUID
    ) -> UUID:
        request = MediaMessageRequest.model_validate_json(json.dumps(arguments))
        attachments: list[CreatorMediaAttachment] = []
        for upload_id in request.attachments:
            record = await self.uploads.get(upload_id, creator, delegate)
            if record.state != "completed" or record.artifact_id is None:
                raise UploadViolation("UPLOAD-NOT-COMPLETE")
            declaration = record.declaration
            suffix = Path(declaration.file_name).suffix.lower()
            kind = (
                "image"
                if suffix in {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"}
                else "audio"
                if suffix == ".mp3"
                else "video"
                if suffix == ".mp4"
                else "file"
            )
            attachments.append(
                CreatorMediaAttachment(
                    record.artifact_id,
                    declaration.file_name,
                    declaration.media_type,
                    declaration.byte_size,
                    Digest(declaration.content_digest),
                    kind,
                )
            )
        if not attachments:
            raise CreatorInputViolation("CON-INPUT-ATTACHMENT")
        return await self.inputs.accept_media(
            CreatorMediaCommand(
                request.scene_key,
                request.message,
                tuple(attachments),
                IdempotencyKey(request.idempotency_key),
                TraceId(uuid7().hex),
                delegate,
            )
        )

    async def operation(
        self,
        reference: str,
        get_operation: Callable[[str], Awaitable[CreatorOperation]],
    ) -> dict[str, Any] | None:
        from .creator_projection import operation_wire

        status = await self.inputs.media_status(UUID(reference))
        if status is None:
            return None
        cognition: dict[str, Any] | None = (
            None
            if status.opportunity_id is None
            else cast(
                dict[str, Any],
                operation_wire(await get_operation(str(status.opportunity_id))),
            )
        )
        result_status = "accepted" if cognition is None else cognition["status"]
        if cognition is None and status.processing_failure is not None:
            result_status = status.processing_failure
        stage = (
            "media_recognition"
            if cognition is None
            else cognition.get("details", {}).get("stage", "cognition")
        )
        failures = {item.status for item in status.attachments} & {
            "failed",
            "unknown",
            "skipped",
        }
        if (
            cognition is not None
            and result_status in {"completed", "applied"}
            and failures
        ):
            result_status = "partial"
        return MediaOperationResult.model_validate_json(
            json.dumps(
                {
                    "status": result_status,
                    "result_ref": reference,
                    "interaction_id": str(status.interaction_id),
                    "recognition_status": status.recognition_status,
                    "attachments": [asdict(item) for item in status.attachments],
                    "details": {"stage": stage},
                    "cognition": cognition,
                }
            )
        ).model_dump(mode="json")


__all__ = (
    "CreatorMedia",
    "MediaMessageRequest",
    "MediaMessageResult",
    "MediaOperationResult",
    "MediaOrOperationResult",
)
