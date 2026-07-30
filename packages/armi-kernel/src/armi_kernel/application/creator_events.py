"""Technology-neutral contracts for Creator projection invalidations."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol, runtime_checkable

from armi_kernel.contracts import Instant

from .scenes import PROJECTION_VERSION, SceneKey

_CODE = re.compile(r"^(?:CON-SSE|SSE)-[A-Z0-9-]+$", re.ASCII)


class CreatorEventViolation(RuntimeError):
    """Expose a stable event-contract code without transport detail."""

    __slots__ = ("code",)

    def __init__(self, code: str) -> None:
        if type(code) is not str or _CODE.fullmatch(code) is None:
            raise ValueError("creator event violation code is invalid")
        self.code = code
        super().__init__("creator event contract failed")

    def __str__(self) -> str:
        return f"{self.code}: creator event contract failed"


class CreatorEventResourceKind(StrEnum):
    SCENE_TIMELINE = "scene_timeline"


@dataclass(frozen=True, slots=True)
class CreatorProjectionInvalidation:
    resource_kind: CreatorEventResourceKind
    resource_ref: SceneKey
    occurred_at: Instant
    projection_version: str = PROJECTION_VERSION

    def __post_init__(self) -> None:
        if type(self.resource_kind) is not CreatorEventResourceKind:
            raise CreatorEventViolation("CON-SSE-RESOURCE")
        if type(self.resource_ref) is not SceneKey:
            raise CreatorEventViolation("CON-SSE-RESOURCE")
        if type(self.occurred_at) is not Instant:
            raise CreatorEventViolation("CON-SSE-TIME")
        if self.projection_version != PROJECTION_VERSION:
            raise CreatorEventViolation("CON-SSE-PROJECTION")


@runtime_checkable
class CreatorProjectionNotifier(Protocol):
    async def notify(self, invalidation: CreatorProjectionInvalidation) -> None:
        """Publish a best-effort invalidation after its source fact commits."""
        ...


__all__ = (
    "CreatorEventResourceKind",
    "CreatorEventViolation",
    "CreatorProjectionInvalidation",
    "CreatorProjectionNotifier",
)
