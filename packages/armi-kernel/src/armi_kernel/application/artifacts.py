"""Technology-neutral content-addressed artifact contracts."""

from __future__ import annotations

import re
from collections.abc import AsyncIterable
from dataclasses import dataclass
from enum import StrEnum
from types import TracebackType
from typing import Protocol, Self, runtime_checkable
from uuid import UUID

from armi_kernel.contracts import Digest, TraceId

_TOKEN = re.compile(r"^[a-z][a-z0-9._-]{0,63}$", re.ASCII)
_MEDIA_TYPE = re.compile(
    r"^[a-z0-9][a-z0-9!#$&^_.+-]{0,62}/"
    r"[a-z0-9][a-z0-9!#$&^_.+-]{0,62}$",
    re.ASCII,
)


class ArtifactPrivacyScope(StrEnum):
    CREATOR_VISIBLE = "creator_visible"
    PRIVATE = "private"
    SHARED = "shared"
    RESTRICTED = "restricted"


class ArtifactIntegrityStatus(StrEnum):
    VERIFIED = "verified"
    MISSING = "missing"
    CORRUPT = "corrupt"


@dataclass(frozen=True, slots=True)
class ArtifactId:
    value: UUID

    def __post_init__(self) -> None:
        if type(self.value) is not UUID or self.value.version != 7:
            raise ArtifactViolation("ART-DECLARATION")

    def __str__(self) -> str:
        return str(self.value)


@dataclass(frozen=True, slots=True)
class ArtifactPolicy:
    media_type: str
    logical_kind: str
    producer_kind: str
    producer_trace_id: TraceId
    privacy_scope: ArtifactPrivacyScope
    schema_version: int = 1

    def __post_init__(self) -> None:
        _validate_media_type(self.media_type)
        _validate_token(self.logical_kind)
        _validate_token(self.producer_kind)
        if type(self.producer_trace_id) is not TraceId:
            raise ArtifactViolation("ART-DECLARATION")
        if type(self.privacy_scope) is not ArtifactPrivacyScope:
            raise ArtifactViolation("ART-DECLARATION")
        if type(self.schema_version) is not int or self.schema_version != 1:
            raise ArtifactViolation("ART-DECLARATION")


@dataclass(frozen=True, slots=True)
class StagedArtifact:
    stage_id: ArtifactId
    content_digest: Digest
    byte_size: int
    policy: ArtifactPolicy

    def __post_init__(self) -> None:
        _validate_content_descriptor(
            self.stage_id,
            self.content_digest,
            self.byte_size,
            self.policy,
        )


@dataclass(frozen=True, slots=True)
class PublishedArtifact:
    stage_id: ArtifactId
    content_digest: Digest
    byte_size: int
    policy: ArtifactPolicy

    def __post_init__(self) -> None:
        _validate_content_descriptor(
            self.stage_id,
            self.content_digest,
            self.byte_size,
            self.policy,
        )


@dataclass(frozen=True, slots=True)
class ArtifactRef:
    artifact_id: ArtifactId
    content_digest: Digest
    byte_size: int
    media_type: str
    logical_kind: str
    privacy_scope: ArtifactPrivacyScope
    integrity_status: ArtifactIntegrityStatus
    schema_version: int

    def __post_init__(self) -> None:
        _validate_media_type(self.media_type)
        _validate_token(self.logical_kind)
        if type(self.artifact_id) is not ArtifactId:
            raise ArtifactViolation("ART-DECLARATION")
        if type(self.content_digest) is not Digest:
            raise ArtifactViolation("ART-DECLARATION")
        if type(self.byte_size) is not int or self.byte_size <= 0:
            raise ArtifactViolation("ART-SIZE-LIMIT")
        if type(self.integrity_status) is not ArtifactIntegrityStatus:
            raise ArtifactViolation("ART-STATE")
        if type(self.privacy_scope) is not ArtifactPrivacyScope:
            raise ArtifactViolation("ART-DECLARATION")
        if type(self.schema_version) is not int or self.schema_version != 1:
            raise ArtifactViolation("ART-DECLARATION")


class ArtifactViolation(RuntimeError):
    __slots__ = ("code",)

    def __init__(self, code: str) -> None:
        if type(code) is not str or not code.startswith("ART-"):
            raise ValueError("artifact violation code is invalid")
        self.code = code
        super().__init__("artifact operation failed")

    def __str__(self) -> str:
        return f"{self.code}: artifact operation failed"


@runtime_checkable
class VerifiedByteStream(Protocol):
    async def read(self, size: int = -1) -> bytes:
        """Read verified bytes from the already checked handle."""
        ...

    async def close(self) -> None:
        """Close the underlying handle."""
        ...

    async def __aenter__(self) -> Self: ...

    async def __aexit__(
        self,
        exception_type: type[BaseException] | None,
        exception: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool: ...


@runtime_checkable
class ArtifactPort(Protocol):
    async def stage(
        self,
        source: AsyncIterable[bytes],
        policy: ArtifactPolicy,
    ) -> StagedArtifact: ...

    async def publish(self, staged: StagedArtifact) -> PublishedArtifact: ...

    async def discard(self, staged: StagedArtifact) -> None: ...

    async def open_verified(self, ref: ArtifactRef) -> VerifiedByteStream: ...


def _validate_content_descriptor(
    stage_id: object,
    content_digest: object,
    byte_size: object,
    policy: object,
) -> None:
    if type(stage_id) is not ArtifactId or type(content_digest) is not Digest:
        raise ArtifactViolation("ART-DECLARATION")
    if type(byte_size) is not int or byte_size <= 0:
        raise ArtifactViolation("ART-SIZE-LIMIT")
    if type(policy) is not ArtifactPolicy:
        raise ArtifactViolation("ART-DECLARATION")


def _validate_media_type(value: object) -> None:
    if (
        type(value) is not str
        or len(value) > 127
        or _MEDIA_TYPE.fullmatch(value) is None
    ):
        raise ArtifactViolation("ART-MEDIA-TYPE")


def _validate_token(value: object) -> None:
    if type(value) is not str or _TOKEN.fullmatch(value) is None:
        raise ArtifactViolation("ART-DECLARATION")


__all__ = (
    "ArtifactId",
    "ArtifactIntegrityStatus",
    "ArtifactPolicy",
    "ArtifactPort",
    "ArtifactPrivacyScope",
    "ArtifactRef",
    "ArtifactViolation",
    "PublishedArtifact",
    "StagedArtifact",
    "VerifiedByteStream",
)
