"""Process-local Runtime authority state and heartbeat policy."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from armi_kernel.application import (
    RuntimeAuthorityPort,
    RuntimeAuthorityRecord,
    RuntimeAuthorityViolation,
    RuntimeFence,
    RuntimeInstanceId,
)


class LocalAuthorityState(StrEnum):
    INACTIVE = "inactive"
    ACTIVE = "active"
    SUSPENDED = "suspended"
    DRAINING = "draining"
    LOST = "lost"


@dataclass(frozen=True, slots=True)
class AuthorityControlSnapshot:
    state: LocalAuthorityState
    fence: RuntimeFence | None
    consecutive_connection_errors: int

    @property
    def writable(self) -> bool:
        return self.state is LocalAuthorityState.ACTIVE and self.fence is not None


class RuntimeAuthorityController:
    """Apply the frozen first-error suspend, second-error lose policy."""

    __slots__ = (
        "_connection_errors",
        "_fence",
        "_lease_seconds",
        "_port",
        "_state",
    )

    def __init__(
        self,
        port: RuntimeAuthorityPort,
        *,
        lease_seconds: int,
    ) -> None:
        self._port = port
        self._lease_seconds = lease_seconds
        self._state = LocalAuthorityState.INACTIVE
        self._fence: RuntimeFence | None = None
        self._connection_errors = 0

    async def acquire(
        self,
        runtime_instance_id: RuntimeInstanceId,
    ) -> RuntimeAuthorityRecord:
        if self._state is not LocalAuthorityState.INACTIVE:
            raise RuntimeAuthorityViolation("AUTH-LOCAL-STATE")
        record = await self._port.acquire(
            runtime_instance_id=runtime_instance_id,
            lease_seconds=self._lease_seconds,
        )
        self._fence = record.fence
        self._state = LocalAuthorityState.ACTIVE
        self._connection_errors = 0
        return record

    async def heartbeat_once(self) -> AuthorityControlSnapshot:
        fence = self._require_fence()
        if self._state is LocalAuthorityState.LOST:
            raise RuntimeAuthorityViolation("AUTH-LOCAL-LOST")
        try:
            record = await self._port.heartbeat(
                fence,
                lease_seconds=self._lease_seconds,
            )
        except RuntimeAuthorityViolation as error:
            if error.code == "AUTH-DATABASE":
                self._connection_errors += 1
                if self._connection_errors == 1:
                    self._state = LocalAuthorityState.SUSPENDED
                    return self.snapshot()
                self._state = LocalAuthorityState.LOST
                raise RuntimeAuthorityViolation("AUTH-HEARTBEAT-LOST") from None
            self._state = LocalAuthorityState.LOST
            raise
        draining = self._state is LocalAuthorityState.DRAINING
        self._fence = record.fence
        self._connection_errors = 0
        self._state = (
            LocalAuthorityState.DRAINING if draining else LocalAuthorityState.ACTIVE
        )
        return self.snapshot()

    async def release(self) -> RuntimeAuthorityRecord:
        fence = self._require_fence()
        if self._state is LocalAuthorityState.LOST:
            raise RuntimeAuthorityViolation("AUTH-LOCAL-LOST")
        try:
            record = await self._port.release(fence)
        except RuntimeAuthorityViolation:
            self._state = LocalAuthorityState.LOST
            raise
        self._state = LocalAuthorityState.INACTIVE
        self._fence = None
        self._connection_errors = 0
        return record

    def begin_drain(self) -> AuthorityControlSnapshot:
        if self._state in {
            LocalAuthorityState.ACTIVE,
            LocalAuthorityState.SUSPENDED,
        }:
            self._state = LocalAuthorityState.DRAINING
            return self.snapshot()
        if self._state is LocalAuthorityState.DRAINING:
            return self.snapshot()
        raise RuntimeAuthorityViolation("AUTH-LOCAL-LOST")

    def require_writable(self) -> RuntimeFence:
        if self._state is LocalAuthorityState.SUSPENDED:
            raise RuntimeAuthorityViolation("AUTH-LOCAL-SUSPENDED")
        if self._state is not LocalAuthorityState.ACTIVE or self._fence is None:
            raise RuntimeAuthorityViolation("AUTH-LOCAL-LOST")
        return self._fence

    def snapshot(self) -> AuthorityControlSnapshot:
        return AuthorityControlSnapshot(
            state=self._state,
            fence=self._fence,
            consecutive_connection_errors=self._connection_errors,
        )

    def _require_fence(self) -> RuntimeFence:
        if self._fence is None:
            raise RuntimeAuthorityViolation("AUTH-LOCAL-STATE")
        return self._fence


__all__ = (
    "AuthorityControlSnapshot",
    "LocalAuthorityState",
    "RuntimeAuthorityController",
)
