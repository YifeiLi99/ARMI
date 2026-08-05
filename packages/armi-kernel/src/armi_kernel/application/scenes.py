"""Technology-neutral contracts for the authoritative Creator scene timeline."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Protocol, runtime_checkable
from uuid import UUID

from armi_kernel.contracts import Instant, OpaqueCursor

from .auditing import AuditResultStatus

PROJECTION_VERSION = "scene-timeline.v4"
_KEY = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$", re.ASCII)
_KIND = re.compile(r"^[a-z][a-z0-9._-]{0,63}$", re.ASCII)
_CODE = re.compile(r"^(?:CON-SCENE|CON-QUERY|SCENE)-[A-Z0-9-]+$", re.ASCII)


class SceneQueryViolation(RuntimeError):
    """Expose a stable scene-query code without persistence detail."""

    __slots__ = ("code",)

    def __init__(self, code: str) -> None:
        if type(code) is not str or _CODE.fullmatch(code) is None:
            raise ValueError("scene query violation code is invalid")
        self.code = code
        super().__init__("scene query failed")

    def __str__(self) -> str:
        return f"{self.code}: scene query failed"


def _require_uuid7(value: object, code: str) -> None:
    if type(value) is not UUID or value.version != 7:
        raise SceneQueryViolation(code)


@dataclass(frozen=True, slots=True)
class SceneKey:
    value: str

    def __post_init__(self) -> None:
        if type(self.value) is not str or _KEY.fullmatch(self.value) is None:
            raise SceneQueryViolation("CON-SCENE-KEY")

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True, slots=True)
class TimelineItemId:
    value: UUID

    def __post_init__(self) -> None:
        _require_uuid7(self.value, "CON-SCENE-ITEM-ID")

    def __str__(self) -> str:
        return str(self.value)


@dataclass(frozen=True, slots=True)
class SceneTimelineItem:
    timeline_item_id: TimelineItemId
    source_kind: str
    source_ref: UUID
    status: AuditResultStatus
    occurred_at: Instant
    operation_ref: UUID | None = None
    effect_ref: UUID | None = None

    def __post_init__(self) -> None:
        if type(self.timeline_item_id) is not TimelineItemId:
            raise SceneQueryViolation("CON-SCENE-ITEM")
        if (
            type(self.source_kind) is not str
            or _KIND.fullmatch(self.source_kind) is None
        ):
            raise SceneQueryViolation("CON-SCENE-SOURCE")
        _require_uuid7(self.source_ref, "CON-SCENE-SOURCE")
        if type(self.status) is not AuditResultStatus:
            raise SceneQueryViolation("CON-SCENE-STATUS")
        if type(self.occurred_at) is not Instant:
            raise SceneQueryViolation("CON-SCENE-TIME")
        if self.operation_ref is not None:
            _require_uuid7(self.operation_ref, "CON-SCENE-OPERATION")
        if self.effect_ref is not None:
            _require_uuid7(self.effect_ref, "CON-SCENE-EFFECT")
        if (self.source_kind in {"creator_input", "subject_commit"}) != (
            self.operation_ref is not None
        ):
            raise SceneQueryViolation("CON-SCENE-OPERATION")
        if (self.source_kind == "creator_response") != (self.effect_ref is not None):
            raise SceneQueryViolation("CON-SCENE-EFFECT")


@dataclass(frozen=True, slots=True)
class SceneTimelineQuery:
    scene_key: SceneKey
    limit: int
    cursor: OpaqueCursor | None = None

    def __post_init__(self) -> None:
        if type(self.scene_key) is not SceneKey:
            raise SceneQueryViolation("CON-QUERY-SCENE")
        if type(self.limit) is not int or not 1 <= self.limit <= 100:
            raise SceneQueryViolation("CON-QUERY-LIMIT")
        if self.cursor is not None and type(self.cursor) is not OpaqueCursor:
            raise SceneQueryViolation("CON-QUERY-CURSOR")


@dataclass(frozen=True, slots=True)
class SceneTimelinePage:
    scene_key: SceneKey
    items: tuple[SceneTimelineItem, ...]
    next_cursor: OpaqueCursor | None = None
    projection_version: str = PROJECTION_VERSION

    def __post_init__(self) -> None:
        if type(self.scene_key) is not SceneKey:
            raise SceneQueryViolation("CON-QUERY-PAGE")
        if type(self.items) is not tuple or any(
            type(item) is not SceneTimelineItem for item in self.items
        ):
            raise SceneQueryViolation("CON-QUERY-PAGE")
        if self.next_cursor is not None and type(self.next_cursor) is not OpaqueCursor:
            raise SceneQueryViolation("CON-QUERY-PAGE")
        if self.projection_version != PROJECTION_VERSION:
            raise SceneQueryViolation("CON-QUERY-PROJECTION")
        order = tuple(
            (item.occurred_at.value, item.timeline_item_id.value.bytes)
            for item in self.items
        )
        if order != tuple(sorted(order)):
            raise SceneQueryViolation("CON-QUERY-ORDER")


@runtime_checkable
class SceneTimelineQueryPort(Protocol):
    async def query(self, request: SceneTimelineQuery) -> SceneTimelinePage:
        """Return an authoritative Creator-visible timeline page."""
        ...


__all__ = (
    "PROJECTION_VERSION",
    "SceneKey",
    "SceneQueryViolation",
    "SceneTimelineItem",
    "SceneTimelinePage",
    "SceneTimelineQuery",
    "SceneTimelineQueryPort",
    "TimelineItemId",
)
