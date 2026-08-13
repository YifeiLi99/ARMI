"""Technology-neutral contracts for Creator projection invalidations."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from armi_kernel.contracts import Instant

_CODE = re.compile(r"^(?:CON-SSE|SSE)-[A-Z0-9-]+$", re.ASCII)
_SCENE_KEY = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$", re.ASCII)
_RESOURCE_KIND = re.compile(r"^[a-z][a-z0-9._-]{0,63}$", re.ASCII)
_PROJECTION_VERSION = re.compile(r"^[a-z][a-z0-9._-]{0,63}$", re.ASCII)
_UUIDV7 = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-"
    r"[89ab][0-9a-f]{3}-[0-9a-f]{12}$",
    re.ASCII,
)


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


class CreatorResourceKind(str):
    """Opaque projection resource token owned by the outer Creator application."""

    def __new__(cls, value: str) -> CreatorResourceKind:
        if type(value) is not str or _RESOURCE_KIND.fullmatch(value) is None:
            raise CreatorEventViolation("CON-SSE-RESOURCE")
        return str.__new__(cls, value)


@dataclass(frozen=True, slots=True)
class CreatorProjectionInvalidation:
    resource_kind: CreatorResourceKind
    resource_ref: str
    occurred_at: Instant
    projection_version: str

    def __post_init__(self) -> None:
        if type(self.resource_kind) is not CreatorResourceKind:
            raise CreatorEventViolation("CON-SSE-RESOURCE")
        if type(self.resource_ref) is not str:
            raise CreatorEventViolation("CON-SSE-RESOURCE")
        if (
            _SCENE_KEY.fullmatch(self.resource_ref) is None
            and _UUIDV7.fullmatch(self.resource_ref) is None
        ):
            raise CreatorEventViolation("CON-SSE-RESOURCE")
        if type(self.occurred_at) is not Instant:
            raise CreatorEventViolation("CON-SSE-TIME")
        if (
            type(self.projection_version) is not str
            or _PROJECTION_VERSION.fullmatch(self.projection_version) is None
        ):
            raise CreatorEventViolation("CON-SSE-PROJECTION")


@runtime_checkable
class CreatorProjectionNotifier(Protocol):
    async def notify(self, invalidation: CreatorProjectionInvalidation) -> None:
        """Publish a best-effort invalidation after its source fact commits."""
        ...


__all__ = (
    "CreatorEventViolation",
    "CreatorProjectionInvalidation",
    "CreatorProjectionNotifier",
    "CreatorResourceKind",
)
