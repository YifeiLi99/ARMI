"""Read-only exact life-record and Creator memory query contracts."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol, runtime_checkable
from uuid import UUID

from armi_kernel.contracts import Instant, OpaqueCursor

LIFE_RECORD_PROJECTION_VERSION = "life-record-query.v1"
CREATOR_MEMORY_PROJECTION_VERSION = "creator-memory.v1"
_CODE = re.compile(r"^(?:CON-)?LIFE-QUERY-[A-Z0-9-]+$", re.ASCII)


class LifeRecordQueryViolation(RuntimeError):
    __slots__ = ("code",)

    def __init__(self, code: str) -> None:
        if type(code) is not str or _CODE.fullmatch(code) is None:
            raise ValueError("life-record query violation code is invalid")
        self.code = code
        super().__init__("life-record query failed")

    def __str__(self) -> str:
        return f"{self.code}: life-record query failed"


class LifeRecordActor(StrEnum):
    SUBJECT = "subject"
    CREATOR = "creator"


class LifeRecordRetrievalKind(StrEnum):
    EXACT_QUERY = "exact_query"
    CREATOR_VIEW = "creator_view"


class LifeRecordKind(StrEnum):
    ACTIVITY = "activity"
    CONVERSATION = "conversation"
    MEMORY = "memory"
    SELF_CHANGE = "self_change"


class MemoryAccessibility(StrEnum):
    AVAILABLE = "available"
    FADED = "faded"
    FORGOTTEN = "forgotten"


class MemoryRevisionKind(StrEnum):
    FORMED = "formed"
    RECALLED = "recalled"
    FADED = "faded"
    FORGOTTEN = "forgotten"
    REINTERPRETED = "reinterpreted"


class MemoryRelationKind(StrEnum):
    SUPPORTS = "supports"
    CONTRADICTS = "contradicts"
    REINTERPRETS = "reinterprets"


def _uuid7(value: object) -> bool:
    return type(value) is UUID and value.version == 7


def _text(value: object, *, maximum: int) -> bool:
    if type(value) is not str or not value.strip():
        return False
    try:
        encoded = value.encode("utf-8", errors="strict")
    except UnicodeEncodeError:
        return False
    return b"\x00" not in encoded and len(encoded) <= maximum


@dataclass(frozen=True, slots=True)
class LifeRecordQuery:
    actor: LifeRecordActor
    retrieval_kind: LifeRecordRetrievalKind
    limit: int
    record_kind: LifeRecordKind | None = None
    query_text: str | None = None
    cursor: OpaqueCursor | None = None

    def __post_init__(self) -> None:
        if (
            type(self.actor) is not LifeRecordActor
            or type(self.retrieval_kind) is not LifeRecordRetrievalKind
            or (self.actor is LifeRecordActor.SUBJECT)
            != (self.retrieval_kind is LifeRecordRetrievalKind.EXACT_QUERY)
            or type(self.limit) is not int
            or not 1 <= self.limit <= 100
            or (
                self.record_kind is not None
                and type(self.record_kind) is not LifeRecordKind
            )
            or (
                self.query_text is not None
                and not _text(self.query_text, maximum=1024)
            )
            or (self.cursor is not None and type(self.cursor) is not OpaqueCursor)
        ):
            raise LifeRecordQueryViolation("CON-LIFE-QUERY-REQUEST")


@dataclass(frozen=True, slots=True)
class LifeRecordItem:
    record_ref: UUID
    record_kind: LifeRecordKind
    summary: str
    source_kind: str
    occurred_at: Instant
    naturally_recallable: bool | None
    retrieval_kind: LifeRecordRetrievalKind

    def __post_init__(self) -> None:
        if (
            not _uuid7(self.record_ref)
            or type(self.record_kind) is not LifeRecordKind
            or not _text(self.summary, maximum=16_384)
            or not _text(self.source_kind, maximum=128)
            or type(self.occurred_at) is not Instant
            or (
                self.naturally_recallable is not None
                and type(self.naturally_recallable) is not bool
            )
            or type(self.retrieval_kind) is not LifeRecordRetrievalKind
            or (self.record_kind is LifeRecordKind.MEMORY)
            != (self.naturally_recallable is not None)
        ):
            raise LifeRecordQueryViolation("CON-LIFE-QUERY-ITEM")


@dataclass(frozen=True, slots=True)
class LifeRecordPage:
    items: tuple[LifeRecordItem, ...]
    next_cursor: OpaqueCursor | None = None
    projection_version: str = LIFE_RECORD_PROJECTION_VERSION

    def __post_init__(self) -> None:
        if (
            type(self.items) is not tuple
            or len(self.items) > 100
            or any(type(item) is not LifeRecordItem for item in self.items)
            or (
                self.next_cursor is not None
                and type(self.next_cursor) is not OpaqueCursor
            )
            or self.projection_version != LIFE_RECORD_PROJECTION_VERSION
        ):
            raise LifeRecordQueryViolation("CON-LIFE-QUERY-PAGE")


@dataclass(frozen=True, slots=True)
class CreatorMemoryItem:
    memory_id: UUID
    summary: str
    uncertainty: str | None
    source_kind: str
    source_fact_class: str
    accessibility: MemoryAccessibility
    revision_kind: MemoryRevisionKind
    revision_no: int
    head_version: int
    created_at: Instant
    updated_at: Instant

    def __post_init__(self) -> None:
        if (
            not _uuid7(self.memory_id)
            or not _text(self.summary, maximum=4096)
            or (
                self.uncertainty is not None
                and not _text(self.uncertainty, maximum=4096)
            )
            or not _text(self.source_kind, maximum=64)
            or not _text(self.source_fact_class, maximum=64)
            or type(self.accessibility) is not MemoryAccessibility
            or type(self.revision_kind) is not MemoryRevisionKind
            or type(self.revision_no) is not int
            or self.revision_no < 1
            or type(self.head_version) is not int
            or self.head_version != self.revision_no
            or type(self.created_at) is not Instant
            or type(self.updated_at) is not Instant
        ):
            raise LifeRecordQueryViolation("CON-LIFE-QUERY-MEMORY")


@dataclass(frozen=True, slots=True)
class CreatorMemoryPage:
    items: tuple[CreatorMemoryItem, ...]
    next_cursor: OpaqueCursor | None = None
    projection_version: str = CREATOR_MEMORY_PROJECTION_VERSION

    def __post_init__(self) -> None:
        if (
            type(self.items) is not tuple
            or len(self.items) > 100
            or any(type(item) is not CreatorMemoryItem for item in self.items)
            or (
                self.next_cursor is not None
                and type(self.next_cursor) is not OpaqueCursor
            )
            or self.projection_version != CREATOR_MEMORY_PROJECTION_VERSION
        ):
            raise LifeRecordQueryViolation("CON-LIFE-QUERY-PAGE")


@dataclass(frozen=True, slots=True)
class CreatorMemoryTimelineItem:
    revision_id: UUID
    revision_no: int
    revision_kind: MemoryRevisionKind
    accessibility: MemoryAccessibility
    summary: str
    uncertainty: str | None
    source_kind: str
    source_fact_class: str
    relation_kind: MemoryRelationKind | None
    related_memory_id: UUID | None
    occurred_at: Instant

    def __post_init__(self) -> None:
        if (
            not _uuid7(self.revision_id)
            or type(self.revision_no) is not int
            or self.revision_no < 1
            or type(self.revision_kind) is not MemoryRevisionKind
            or type(self.accessibility) is not MemoryAccessibility
            or not _text(self.summary, maximum=4096)
            or (
                self.uncertainty is not None
                and not _text(self.uncertainty, maximum=4096)
            )
            or not _text(self.source_kind, maximum=64)
            or not _text(self.source_fact_class, maximum=64)
            or (self.relation_kind is None) != (self.related_memory_id is None)
            or (
                self.relation_kind is not None
                and type(self.relation_kind) is not MemoryRelationKind
            )
            or (
                self.related_memory_id is not None
                and not _uuid7(self.related_memory_id)
            )
            or type(self.occurred_at) is not Instant
        ):
            raise LifeRecordQueryViolation("CON-LIFE-QUERY-MEMORY-TIMELINE")


@dataclass(frozen=True, slots=True)
class CreatorMemoryTimeline:
    memory_id: UUID
    items: tuple[CreatorMemoryTimelineItem, ...]
    next_cursor: OpaqueCursor | None = None
    projection_version: str = CREATOR_MEMORY_PROJECTION_VERSION

    def __post_init__(self) -> None:
        if (
            not _uuid7(self.memory_id)
            or type(self.items) is not tuple
            or len(self.items) > 100
            or any(
                type(item) is not CreatorMemoryTimelineItem for item in self.items
            )
            or (
                self.next_cursor is not None
                and type(self.next_cursor) is not OpaqueCursor
            )
            or self.projection_version != CREATOR_MEMORY_PROJECTION_VERSION
        ):
            raise LifeRecordQueryViolation("CON-LIFE-QUERY-PAGE")


@runtime_checkable
class LifeRecordQueryPort(Protocol):
    async def query(self, request: LifeRecordQuery) -> LifeRecordPage: ...


@runtime_checkable
class CreatorMemoryQueryPort(Protocol):
    async def list_current(
        self,
        *,
        limit: int,
        query_text: str | None = None,
        cursor: OpaqueCursor | None = None,
    ) -> CreatorMemoryPage: ...

    async def timeline(
        self,
        memory_id: UUID,
        *,
        limit: int,
        cursor: OpaqueCursor | None = None,
    ) -> CreatorMemoryTimeline: ...


__all__ = (
    "CREATOR_MEMORY_PROJECTION_VERSION",
    "LIFE_RECORD_PROJECTION_VERSION",
    "CreatorMemoryItem",
    "CreatorMemoryPage",
    "CreatorMemoryQueryPort",
    "CreatorMemoryTimeline",
    "CreatorMemoryTimelineItem",
    "LifeRecordActor",
    "LifeRecordItem",
    "LifeRecordKind",
    "LifeRecordPage",
    "LifeRecordQuery",
    "LifeRecordQueryPort",
    "LifeRecordQueryViolation",
    "LifeRecordRetrievalKind",
    "MemoryAccessibility",
    "MemoryRelationKind",
    "MemoryRevisionKind",
)
