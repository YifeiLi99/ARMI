"""Technology-neutral Runtime authority and fencing contracts."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Protocol, runtime_checkable
from uuid import UUID


class RuntimeAuthorityViolation(RuntimeError):
    """Expose only a stable authority failure code."""

    __slots__ = ("code",)

    def __init__(self, code: str) -> None:
        if type(code) is not str or not code.startswith("AUTH-"):
            raise ValueError("runtime authority violation code is invalid")
        self.code = code
        super().__init__("runtime authority operation failed")

    def __str__(self) -> str:
        return f"{self.code}: runtime authority operation failed"


def _require_uuid7(value: object, code: str = "AUTH-DECLARATION") -> None:
    if type(value) is not UUID or value.version != 7:
        raise RuntimeAuthorityViolation(code)


def _require_utc(value: object) -> None:
    if (
        type(value) is not datetime
        or value.tzinfo is None
        or value.utcoffset() is None
        or value.utcoffset() != UTC.utcoffset(None)
    ):
        raise RuntimeAuthorityViolation("AUTH-DECLARATION")


@dataclass(frozen=True, slots=True)
class RuntimeInstanceId:
    value: UUID

    def __post_init__(self) -> None:
        _require_uuid7(self.value)

    def __str__(self) -> str:
        return str(self.value)


class RuntimeAuthorityStatus(StrEnum):
    ACTIVE = "active"
    FENCED = "fenced"
    STOPPED = "stopped"


@dataclass(frozen=True, slots=True)
class RuntimeFence:
    runtime_instance_id: RuntimeInstanceId
    subject_id: UUID
    life_generation_id: UUID
    bundle_activation_id: UUID
    fence_token: int

    def __post_init__(self) -> None:
        if type(self.runtime_instance_id) is not RuntimeInstanceId:
            raise RuntimeAuthorityViolation("AUTH-DECLARATION")
        for value in (
            self.subject_id,
            self.life_generation_id,
            self.bundle_activation_id,
        ):
            _require_uuid7(value)
        if type(self.fence_token) is not int or self.fence_token <= 0:
            raise RuntimeAuthorityViolation("AUTH-DECLARATION")


@dataclass(frozen=True, slots=True)
class RuntimeAuthorityRecord:
    fence: RuntimeFence
    status: RuntimeAuthorityStatus
    started_at: datetime
    last_heartbeat_at: datetime
    lease_expires_at: datetime
    stopped_at: datetime | None = None

    def __post_init__(self) -> None:
        if type(self.fence) is not RuntimeFence:
            raise RuntimeAuthorityViolation("AUTH-DECLARATION")
        if type(self.status) is not RuntimeAuthorityStatus:
            raise RuntimeAuthorityViolation("AUTH-DECLARATION")
        for value in (
            self.started_at,
            self.last_heartbeat_at,
            self.lease_expires_at,
        ):
            _require_utc(value)
        if self.lease_expires_at <= self.last_heartbeat_at:
            raise RuntimeAuthorityViolation("AUTH-DECLARATION")
        if self.status is RuntimeAuthorityStatus.ACTIVE:
            if self.stopped_at is not None:
                raise RuntimeAuthorityViolation("AUTH-DECLARATION")
        elif self.stopped_at is None:
            raise RuntimeAuthorityViolation("AUTH-DECLARATION")
        if self.stopped_at is not None:
            _require_utc(self.stopped_at)


@runtime_checkable
class RuntimeAuthorityPort(Protocol):
    async def acquire(
        self,
        *,
        runtime_instance_id: RuntimeInstanceId,
        lease_seconds: int,
    ) -> RuntimeAuthorityRecord: ...

    async def heartbeat(
        self,
        fence: RuntimeFence,
        *,
        lease_seconds: int,
    ) -> RuntimeAuthorityRecord: ...

    async def release(self, fence: RuntimeFence) -> RuntimeAuthorityRecord: ...


__all__ = (
    "RuntimeAuthorityPort",
    "RuntimeAuthorityRecord",
    "RuntimeAuthorityStatus",
    "RuntimeAuthorityViolation",
    "RuntimeFence",
    "RuntimeInstanceId",
)
