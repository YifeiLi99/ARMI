"""Resumable local transport buffers; completed bytes enter the artifact owner."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Literal, Self
from uuid import UUID, uuid7

from armi_local_control.configuration.paths import has_reparse_point
from armi_local_control.runtime_process import LocalProcessLock
from pydantic import BaseModel, ConfigDict, Field, model_validator

from .interaction import InteractionInvocation, InteractionOperation, InteractionResult


class UploadViolation(ValueError):
    pass


class UploadDeclaration(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)
    file_name: str = Field(min_length=1, max_length=255, pattern=r"^[^\\/\x00]+$")
    media_type: str = Field(
        pattern=r"^[a-z0-9][a-z0-9!#$&^_.+-]*/[a-z0-9][a-z0-9!#$&^_.+-]*$",
        max_length=127,
    )
    byte_size: int = Field(ge=1, le=45 * 1024 * 1024)
    content_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")


class UploadRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    schema_version: Literal["armi.local-upload.v1"] = "armi.local-upload.v1"
    upload_id: UUID
    environment_id: UUID
    generation_id: UUID
    creator_party_id: UUID
    delegate_id: UUID
    declaration: UploadDeclaration
    request_identity: str = Field(pattern=r"^[0-9a-f]{64}$")
    received_bytes: int = Field(ge=0)
    state: Literal["receiving", "publishing", "completed", "cancelled"]
    artifact_id: UUID | None = None

    @model_validator(mode="after")
    def progress_shape(self) -> Self:
        if self.received_bytes > self.declaration.byte_size:
            raise ValueError("UPLOAD-RECORD")
        if (
            self.state in {"publishing", "completed"}
            and self.received_bytes != self.declaration.byte_size
        ):
            raise ValueError("UPLOAD-RECORD")
        if (self.state == "completed") != (self.artifact_id == self.upload_id):
            raise ValueError("UPLOAD-RECORD")
        if self.state != "completed" and self.artifact_id is not None:
            raise ValueError("UPLOAD-RECORD")
        return self


PublishUpload = Callable[[UploadRecord, Path], Awaitable[UUID]]


class UploadBegin(UploadDeclaration):
    idempotency_key: str = Field(pattern=r"^[A-Za-z0-9._:-]{1,128}$")


class UploadSelect(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    upload_id: UUID


class UploadChunk(UploadSelect):
    offset: int = Field(ge=0)
    content: str = Field(min_length=1, max_length=174764)


UPLOAD_REQUESTS: dict[str, type[BaseModel]] = {
    "upload_begin": UploadBegin,
    "upload_get": UploadSelect,
    "upload_append": UploadChunk,
    "upload_complete": UploadSelect,
    "upload_cancel": UploadSelect,
}


def upload_operations() -> tuple[InteractionOperation, ...]:
    record_schema = UploadRecord.model_json_schema()
    definitions = record_schema.pop("$defs", {})
    return tuple(
        InteractionOperation(
            name,
            "upload",
            name.removeprefix("upload_"),
            name != "upload_get",
            request.model_json_schema(),
            {
                "type": "object",
                "$defs": definitions,
                "properties": {
                    "environment_id": {"type": "string", "format": "uuid"},
                    "status": {"enum": ["returned", "rejected", "unavailable"]},
                    "transport_status": {"type": "integer"},
                    "error_code": {"type": "string"},
                    "result": {
                        "anyOf": [
                            record_schema,
                            {
                                "type": "object",
                                "properties": {"error_code": {"type": "string"}},
                                "required": ["error_code"],
                                "additionalProperties": False,
                            },
                        ]
                    },
                },
                "required": ["status"],
                "oneOf": [
                    {"required": ["environment_id", "result"]},
                    {
                        "required": ["error_code", "transport_status"],
                        "not": {"required": ["result"]},
                    },
                ],
                "additionalProperties": False,
            },
        )
        for name, request in UPLOAD_REQUESTS.items()
    )


async def invoke_upload(
    uploads: MediaUploads | None, call: InteractionInvocation
) -> InteractionResult:
    import base64

    from armi_kernel.application import ArtifactViolation
    from armi_runtime_foundation import RuntimeTransactionFailure
    from pydantic import ValidationError

    if uploads is None:
        return InteractionResult(
            "unavailable", {"error_code": "UPLOAD-UNAVAILABLE"}, 503
        )
    try:
        request = UPLOAD_REQUESTS[call.operation].model_validate_json(
            json.dumps(dict(call.arguments))
        )
        caller = call.caller
        if isinstance(request, UploadBegin):
            result = await uploads.begin(
                caller.creator_party_id,
                caller.delegate_id,
                request.idempotency_key,
                UploadDeclaration.model_validate(
                    request.model_dump(exclude={"idempotency_key"})
                ),
            )
        else:
            assert isinstance(request, UploadSelect)
            arguments = (request.upload_id, caller.creator_party_id, caller.delegate_id)
            if isinstance(request, UploadChunk):
                result = await uploads.append(
                    *arguments,
                    request.offset,
                    base64.b64decode(request.content, validate=True),
                )
            elif call.operation == "upload_get":
                result = await uploads.get(*arguments)
            elif call.operation == "upload_cancel":
                result = await uploads.cancel(*arguments)
            else:
                result = await uploads.complete(*arguments)
        return InteractionResult("returned", result.model_dump(mode="json"))
    except UploadViolation as error:
        return InteractionResult("rejected", {"error_code": str(error)}, 409)
    except ValidationError, ValueError:
        return InteractionResult("rejected", {"error_code": "UPLOAD-ARGUMENTS"}, 400)
    except ArtifactViolation, RuntimeTransactionFailure, OSError:
        return InteractionResult(
            "unavailable", {"error_code": "UPLOAD-UNAVAILABLE"}, 503
        )


class MediaUploads:
    """Only upload protocol state lives here; artifact facts remain owner governed."""

    chunk_bytes = 128 * 1024

    def __init__(
        self,
        root: Path,
        environment_id: UUID,
        generation_id: UUID,
        publish: PublishUpload,
    ) -> None:
        self.root = root
        self.environment_id = environment_id
        self.generation_id = generation_id
        self.publish = publish
        self._locks: dict[UUID, asyncio.Lock] = {}

    def _path(self, upload_id: UUID, suffix: str) -> Path:
        if upload_id.version != 7:
            raise UploadViolation("UPLOAD-ID")
        path = self.root / (str(upload_id) + suffix)
        if has_reparse_point(path, root=self.root.parent):
            raise UploadViolation("UPLOAD-PATH")
        return path

    def _read(self, upload_id: UUID, creator: UUID, delegate: UUID) -> UploadRecord:
        path = self._path(upload_id, ".json")
        try:
            if path.stat().st_size > 8192:
                raise UploadViolation("UPLOAD-RECORD")
            record = UploadRecord.model_validate_json(path.read_bytes())
        except FileNotFoundError:
            raise UploadViolation("UPLOAD-NOT-FOUND") from None
        if (
            record.upload_id,
            record.environment_id,
            record.generation_id,
            record.creator_party_id,
            record.delegate_id,
        ) != (upload_id, self.environment_id, self.generation_id, creator, delegate):
            raise UploadViolation("UPLOAD-SCOPE")
        return record

    def _save(self, record: UploadRecord) -> None:
        path = self._path(record.upload_id, ".json")
        temporary = self._path(record.upload_id, ".next")
        with temporary.open("wb") as stream:
            stream.write(record.model_dump_json().encode("utf-8"))
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(path)

    async def begin(
        self, creator: UUID, delegate: UUID, key: str, declaration: UploadDeclaration
    ) -> UploadRecord:
        if not key or len(key) > 128:
            raise UploadViolation("UPLOAD-IDEMPOTENCY")
        return await asyncio.to_thread(self._begin, creator, delegate, key, declaration)

    def _begin(
        self, creator: UUID, delegate: UUID, key: str, declaration: UploadDeclaration
    ) -> UploadRecord:
        if has_reparse_point(self.root, root=self.root.parent):
            raise UploadViolation("UPLOAD-PATH")
        self.root.mkdir(parents=True, exist_ok=True)
        identity = hashlib.sha256(
            json.dumps(
                [
                    str(self.environment_id),
                    str(self.generation_id),
                    str(creator),
                    str(delegate),
                    key,
                ]
            ).encode()
        ).hexdigest()
        index = self.root / (identity + ".key")
        if has_reparse_point(index, root=self.root.parent):
            raise UploadViolation("UPLOAD-PATH")
        with LocalProcessLock(self.root / "intake.lock"):
            if index.exists():
                if index.stat().st_size != 36:
                    raise UploadViolation("UPLOAD-RECORD")
                record = self._read(
                    UUID(index.read_text(encoding="ascii")), creator, delegate
                )
                if record.declaration != declaration:
                    raise UploadViolation("UPLOAD-IDEMPOTENCY-MISMATCH")
                return record
            # Reserve declared capacity before receiving any bytes.
            reserved = 0
            count = 0
            for path in self.root.glob("*.json"):
                safe_path = self._path(UUID(path.stem), ".json")
                if safe_path.stat().st_size > 8192:
                    raise UploadViolation("UPLOAD-RECORD")
                record = UploadRecord.model_validate_json(safe_path.read_bytes())
                if record.request_identity == identity:
                    if record.declaration != declaration:
                        raise UploadViolation("UPLOAD-IDEMPOTENCY-MISMATCH")
                    self._index(index, record.upload_id)
                    return record
                if record.state in {"receiving", "publishing"}:
                    reserved += record.declaration.byte_size
                    count += 1
            if count >= 16 or reserved + declaration.byte_size > 180 * 1024 * 1024:
                raise UploadViolation("UPLOAD-CAPACITY")
            record = UploadRecord(
                upload_id=uuid7(),
                environment_id=self.environment_id,
                generation_id=self.generation_id,
                creator_party_id=creator,
                delegate_id=delegate,
                declaration=declaration,
                request_identity=identity,
                received_bytes=0,
                state="receiving",
            )
            self._save(record)
            self._index(index, record.upload_id)
            return record

    def _index(self, index: Path, upload_id: UUID) -> None:
        temporary = index.with_suffix(".key.next")
        if has_reparse_point(temporary, root=self.root.parent):
            raise UploadViolation("UPLOAD-PATH")
        with temporary.open("w", encoding="ascii") as stream:
            stream.write(str(upload_id))
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(index)

    async def get(self, upload_id: UUID, creator: UUID, delegate: UUID) -> UploadRecord:
        return await asyncio.to_thread(self._read, upload_id, creator, delegate)

    async def append(
        self,
        upload_id: UUID,
        creator: UUID,
        delegate: UUID,
        offset: int,
        content: bytes,
    ) -> UploadRecord:
        if offset < 0 or not 1 <= len(content) <= self.chunk_bytes:
            raise UploadViolation("UPLOAD-CHUNK")
        return await asyncio.to_thread(
            self._append, upload_id, creator, delegate, offset, content
        )

    def _append(
        self,
        upload_id: UUID,
        creator: UUID,
        delegate: UUID,
        offset: int,
        content: bytes,
    ) -> UploadRecord:
        with LocalProcessLock(self._path(upload_id, ".lock")):
            record = self._read(upload_id, creator, delegate)
            if record.state != "receiving":
                raise UploadViolation("UPLOAD-STATE")
            if (
                offset > record.received_bytes
                or offset + len(content) > record.declaration.byte_size
            ):
                raise UploadViolation("UPLOAD-OFFSET")
            path = self._path(upload_id, ".part")
            if record.received_bytes and not path.exists():
                raise UploadViolation("UPLOAD-CONTENT-MISSING")
            with path.open("r+b" if path.exists() else "w+b") as stream:
                if offset < record.received_bytes:
                    stream.seek(offset)
                    if (
                        offset + len(content) > record.received_bytes
                        or stream.read(len(content)) != content
                    ):
                        raise UploadViolation("UPLOAD-CHUNK-MISMATCH")
                    return record
                stream.seek(offset)
                stream.write(content)
                stream.truncate()
                stream.flush()
                os.fsync(stream.fileno())
            record.received_bytes += len(content)
            self._save(record)
            return record

    async def complete(
        self, upload_id: UUID, creator: UUID, delegate: UUID
    ) -> UploadRecord:
        async with self._locks.setdefault(upload_id, asyncio.Lock()):
            record = await asyncio.to_thread(
                self._prepare_publication, upload_id, creator, delegate
            )
            if record.state == "completed":
                return record
            artifact_id = await self.publish(record, self._path(upload_id, ".part"))
            record.artifact_id = artifact_id
            record.state = "completed"
            await asyncio.to_thread(self._finish, record)
            return record

    def _prepare_publication(
        self, upload_id: UUID, creator: UUID, delegate: UUID
    ) -> UploadRecord:
        with LocalProcessLock(self._path(upload_id, ".lock")):
            record = self._read(upload_id, creator, delegate)
            if record.state == "completed":
                return record
            if (
                record.state == "cancelled"
                or record.received_bytes != record.declaration.byte_size
            ):
                raise UploadViolation("UPLOAD-INCOMPLETE")
            with self._path(upload_id, ".part").open("rb") as stream:
                actual = "sha256:" + hashlib.file_digest(stream, "sha256").hexdigest()
            if actual != record.declaration.content_digest:
                raise UploadViolation("UPLOAD-DIGEST")
            record.state = "publishing"
            self._save(record)
            return record

    def _finish(self, record: UploadRecord) -> None:
        with LocalProcessLock(self._path(record.upload_id, ".lock")):
            self._save(record)
            self._path(record.upload_id, ".part").unlink(missing_ok=True)

    async def cancel(
        self, upload_id: UUID, creator: UUID, delegate: UUID
    ) -> UploadRecord:
        async with self._locks.setdefault(upload_id, asyncio.Lock()):
            return await asyncio.to_thread(self._cancel, upload_id, creator, delegate)

    def _cancel(self, upload_id: UUID, creator: UUID, delegate: UUID) -> UploadRecord:
        with LocalProcessLock(self._path(upload_id, ".lock")):
            record = self._read(upload_id, creator, delegate)
            if record.state in {"completed", "publishing"}:
                raise UploadViolation("UPLOAD-STATE")
            record.state = "cancelled"
            self._save(record)
            self._path(upload_id, ".part").unlink(missing_ok=True)
            return record


__all__ = ("MediaUploads", "UploadDeclaration", "UploadRecord", "UploadViolation")
