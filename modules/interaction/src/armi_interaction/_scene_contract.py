"""Technology-neutral contracts for the authoritative Creator scene timeline."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol, runtime_checkable
from uuid import UUID

from armi_kernel.application import AuditResultStatus
from armi_kernel.contracts import Instant, OpaqueCursor, TraceId

PROJECTION_VERSION = "scene-timeline.v5"
SCENE_COLLECTION_PROJECTION_VERSION = "creator-scenes.v1"
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


class SceneStatus(StrEnum):
    OPEN = "open"
    CLOSED = "closed"


@dataclass(frozen=True, slots=True)
class SceneKey:
    value: str

    def __post_init__(self) -> None:
        if type(self.value) is not str or _KEY.fullmatch(self.value) is None:
            raise SceneQueryViolation("CON-SCENE-KEY")

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True, slots=True)
class CreatorSceneView:
    scene_id: UUID
    scene_key: SceneKey
    status: SceneStatus
    opened_at: Instant
    closed_at: Instant | None
    recent_context_boundary: UUID | None
    is_default: bool

    def __post_init__(self) -> None:
        _require_uuid7(self.scene_id, "CON-SCENE-ID")
        if (
            type(self.scene_key) is not SceneKey
            or type(self.status) is not SceneStatus
            or type(self.opened_at) is not Instant
            or type(self.is_default) is not bool
        ):
            raise SceneQueryViolation("CON-SCENE-VIEW")
        if self.closed_at is not None and type(self.closed_at) is not Instant:
            raise SceneQueryViolation("CON-SCENE-VIEW")
        if self.recent_context_boundary is not None:
            _require_uuid7(
                self.recent_context_boundary,
                "CON-SCENE-BOUNDARY",
            )
        if (self.status is SceneStatus.OPEN) != (self.closed_at is None):
            raise SceneQueryViolation("CON-SCENE-VIEW")
        if self.is_default != (self.scene_key.value == "default"):
            raise SceneQueryViolation("CON-SCENE-VIEW")


@dataclass(frozen=True, slots=True)
class CreatorSceneCollection:
    scenes: tuple[CreatorSceneView, ...]
    projection_version: str = SCENE_COLLECTION_PROJECTION_VERSION

    def __post_init__(self) -> None:
        if (
            type(self.scenes) is not tuple
            or not self.scenes
            or any(type(scene) is not CreatorSceneView for scene in self.scenes)
            or self.projection_version != SCENE_COLLECTION_PROJECTION_VERSION
            or sum(scene.is_default for scene in self.scenes) != 1
            or tuple(scene.scene_key.value for scene in self.scenes)
            != tuple(
                sorted(
                    (scene.scene_key.value for scene in self.scenes),
                    key=lambda value: (value != "default", value),
                )
            )
        ):
            raise SceneQueryViolation("CON-SCENE-COLLECTION")


@dataclass(frozen=True, slots=True)
class CreatorSceneCreateCommand:
    scene_key: SceneKey
    trace_id: TraceId

    def __post_init__(self) -> None:
        if (
            type(self.scene_key) is not SceneKey
            or self.scene_key.value == "default"
            or type(self.trace_id) is not TraceId
        ):
            raise SceneQueryViolation("CON-SCENE-COMMAND")


@dataclass(frozen=True, slots=True)
class CreatorSceneStatusCommand:
    scene_key: SceneKey
    target_status: SceneStatus
    trace_id: TraceId

    def __post_init__(self) -> None:
        if (
            type(self.scene_key) is not SceneKey
            or self.scene_key.value == "default"
            or type(self.target_status) is not SceneStatus
            or type(self.trace_id) is not TraceId
        ):
            raise SceneQueryViolation("CON-SCENE-COMMAND")


@runtime_checkable
class CreatorScenePort(Protocol):
    async def list(self) -> CreatorSceneCollection: ...

    async def create(self, command: CreatorSceneCreateCommand) -> CreatorSceneView: ...

    async def set_status(
        self,
        command: CreatorSceneStatusCommand,
    ) -> CreatorSceneView: ...


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
    message: str | None = None

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
        if (self.source_kind == "creator_input") != (self.message is not None):
            raise SceneQueryViolation("CON-SCENE-MESSAGE")
        if self.message is not None:
            try:
                encoded = self.message.encode("utf-8", errors="strict")
            except UnicodeEncodeError:
                raise SceneQueryViolation("CON-SCENE-MESSAGE") from None
            if (
                not encoded
                or len(encoded) > 65536
                or "\x00" in self.message
                or not any(not character.isspace() for character in self.message)
            ):
                raise SceneQueryViolation("CON-SCENE-MESSAGE")


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
    "SCENE_COLLECTION_PROJECTION_VERSION",
    "CreatorSceneCollection",
    "CreatorSceneCreateCommand",
    "CreatorScenePort",
    "CreatorSceneStatusCommand",
    "CreatorSceneView",
    "SceneKey",
    "SceneQueryViolation",
    "SceneStatus",
    "SceneTimelineItem",
    "SceneTimelinePage",
    "SceneTimelineQuery",
    "SceneTimelineQueryPort",
    "TimelineItemId",
)
