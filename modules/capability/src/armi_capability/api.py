"""Capability catalog and current Runtime availability contracts."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable
from uuid import UUID

type CapabilityContextStatePayload = tuple[UUID, int, bytes, str]


@dataclass(frozen=True, slots=True)
class CapabilityAvailability:
    enabled: bool
    available: bool
    reason_code: str | None

    def __post_init__(self) -> None:
        if self.available and (not self.enabled or self.reason_code is not None):
            raise ValueError("available capability must be enabled without a failure")
        if not self.available and self.reason_code is None:
            raise ValueError("unavailable capability needs a reason")


@runtime_checkable
class CapabilityReadPort(Protocol):
    def context_state_payloads(self) -> tuple[CapabilityContextStatePayload, ...]: ...


__all__ = (
    "CapabilityAvailability",
    "CapabilityContextStatePayload",
    "CapabilityReadPort",
)
