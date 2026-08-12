"""Read-only exact life-record and Creator memory query contracts."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol, runtime_checkable
from uuid import UUID

from armi_kernel.contracts import Instant, OpaqueCursor

LIFE_RECORD_PROJECTION_VERSION = "life-record-query.v2"
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
    MATERIAL = "material"
    MEMORY = "memory"
    RELATIONSHIP = "relationship"
    SELF_CHANGE = "self_change"


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
                self.query_text is not None and not _text(self.query_text, maximum=1024)
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


@runtime_checkable
class LifeRecordQueryPort(Protocol):
    async def query(self, request: LifeRecordQuery) -> LifeRecordPage: ...


__all__ = (
    "LIFE_RECORD_PROJECTION_VERSION",
    "LifeRecordActor",
    "LifeRecordItem",
    "LifeRecordKind",
    "LifeRecordPage",
    "LifeRecordQuery",
    "LifeRecordQueryPort",
    "LifeRecordQueryViolation",
    "LifeRecordRetrievalKind",
)
