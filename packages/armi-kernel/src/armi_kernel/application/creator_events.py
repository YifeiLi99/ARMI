"""Technology-neutral contracts for Creator projection invalidations."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol, runtime_checkable

from armi_kernel.contracts import Instant

_CODE = re.compile(r"^(?:CON-SSE|SSE)-[A-Z0-9-]+$", re.ASCII)
_SCENE_KEY = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$", re.ASCII)
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


class CreatorEventResourceKind(StrEnum):
    ACTIVITY = "activity"
    MEMORY = "memory"
    MAINTENANCE = "maintenance"
    MATERIAL = "material"
    RELATIONSHIP = "relationship"
    SCENE_TIMELINE = "scene_timeline"
    CAPABILITY_REQUEST = "capability_request"
    OPERATION = "operation"
    OTHER_HUMAN_RECORD = "other_human_record"
    EFFECT = "effect"
    SUBJECT_SUMMARY = "subject_summary"
    DATA_RIGHTS = "data_rights"


_PROJECTIONS = {
    CreatorEventResourceKind.ACTIVITY: "creator-activity.v1",
    CreatorEventResourceKind.MEMORY: "creator-memory.v1",
    CreatorEventResourceKind.MAINTENANCE: "creator-maintenance.v2",
    CreatorEventResourceKind.MATERIAL: "life-record-query.v2",
    CreatorEventResourceKind.RELATIONSHIP: "creator-relationship.v2",
    CreatorEventResourceKind.SCENE_TIMELINE: "scene-timeline.v5",
    CreatorEventResourceKind.CAPABILITY_REQUEST: "capability-request.v4",
    CreatorEventResourceKind.OPERATION: "creator-operation.v2",
    CreatorEventResourceKind.OTHER_HUMAN_RECORD: "other-human-record.v1",
    CreatorEventResourceKind.EFFECT: "creator-effect.v3",
    CreatorEventResourceKind.SUBJECT_SUMMARY: "subject-summary.v1",
    CreatorEventResourceKind.DATA_RIGHTS: "data-rights-order.v2",
}


@dataclass(frozen=True, slots=True)
class CreatorProjectionInvalidation:
    resource_kind: CreatorEventResourceKind
    resource_ref: str
    occurred_at: Instant
    projection_version: str

    def __post_init__(self) -> None:
        if type(self.resource_kind) is not CreatorEventResourceKind:
            raise CreatorEventViolation("CON-SSE-RESOURCE")
        if type(self.resource_ref) is not str:
            raise CreatorEventViolation("CON-SSE-RESOURCE")
        pattern = (
            _SCENE_KEY
            if self.resource_kind is CreatorEventResourceKind.SCENE_TIMELINE
            else _UUIDV7
        )
        if pattern.fullmatch(self.resource_ref) is None:
            raise CreatorEventViolation("CON-SSE-RESOURCE")
        if type(self.occurred_at) is not Instant:
            raise CreatorEventViolation("CON-SSE-TIME")
        if self.projection_version != _PROJECTIONS[self.resource_kind]:
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
