"""Creator-visible, read-only records of communication with other humans."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Final, Protocol, runtime_checkable
from uuid import UUID

from armi_kernel.contracts import OpaqueCursor

OTHER_HUMAN_RECORD_PROJECTION_VERSION: Final = "other-human-record.v1"


class OtherHumanRecordViolation(RuntimeError):
    __slots__ = ("code",)

    def __init__(self, code: str) -> None:
        if type(code) is not str or not code.startswith("OTHER-HUMAN-RECORD-"):
            raise ValueError("other-human record violation code is invalid")
        self.code = code
        super().__init__("other-human record query failed")


def _uuid7(value: object) -> bool:
    return type(value) is UUID and value.version == 7


def _instant(value: object) -> bool:
    return type(value) is datetime and value.tzinfo is not None


class OtherHumanRecordDirection(StrEnum):
    RECEIVED = "received"
    SENT = "sent"


@dataclass(frozen=True, slots=True)
class OtherHumanPartyRecord:
    party_id: UUID
    party_key: str
    display_label: str
    scene_count: int
    record_count: int
    last_record_at: datetime | None

    def __post_init__(self) -> None:
        if (
            not _uuid7(self.party_id)
            or type(self.party_key) is not str
            or not self.party_key
            or type(self.display_label) is not str
            or not self.display_label.strip()
            or type(self.scene_count) is not int
            or self.scene_count < 0
            or type(self.record_count) is not int
            or self.record_count < 0
            or (self.last_record_at is not None and not _instant(self.last_record_at))
        ):
            raise OtherHumanRecordViolation("OTHER-HUMAN-RECORD-PARTY")


@dataclass(frozen=True, slots=True)
class OtherHumanPartyRecordPage:
    items: tuple[OtherHumanPartyRecord, ...]
    next_cursor: OpaqueCursor | None


@dataclass(frozen=True, slots=True)
class OtherHumanSceneRecord:
    scene_id: UUID
    scene_key: str
    status: str
    record_count: int
    last_record_at: datetime | None

    def __post_init__(self) -> None:
        if (
            not _uuid7(self.scene_id)
            or type(self.scene_key) is not str
            or not self.scene_key
            or self.status not in {"open", "closed"}
            or type(self.record_count) is not int
            or self.record_count < 0
            or (self.last_record_at is not None and not _instant(self.last_record_at))
        ):
            raise OtherHumanRecordViolation("OTHER-HUMAN-RECORD-SCENE")


@dataclass(frozen=True, slots=True)
class OtherHumanSceneRecordPage:
    party: OtherHumanPartyRecord
    items: tuple[OtherHumanSceneRecord, ...]
    next_cursor: OpaqueCursor | None


@dataclass(frozen=True, slots=True)
class OtherHumanTimelineRecord:
    timeline_item_id: UUID
    source_ref: UUID
    direction: OtherHumanRecordDirection
    result_status: str
    text: str
    occurred_at: datetime

    def __post_init__(self) -> None:
        if (
            not _uuid7(self.timeline_item_id)
            or not _uuid7(self.source_ref)
            or type(self.direction) is not OtherHumanRecordDirection
            or self.result_status not in {"accepted", "completed", "failed", "unknown"}
            or type(self.text) is not str
            or not self.text
            or not _instant(self.occurred_at)
        ):
            raise OtherHumanRecordViolation("OTHER-HUMAN-RECORD-ITEM")


@dataclass(frozen=True, slots=True)
class OtherHumanTimelineRecordPage:
    party_id: UUID
    scene_id: UUID
    items: tuple[OtherHumanTimelineRecord, ...]
    next_cursor: OpaqueCursor | None


@runtime_checkable
class OtherHumanRecordQueryPort(Protocol):
    async def list_parties(
        self, *, limit: int, cursor: OpaqueCursor | None = None
    ) -> OtherHumanPartyRecordPage: ...

    async def list_scenes(
        self, party_id: UUID, *, limit: int, cursor: OpaqueCursor | None = None
    ) -> OtherHumanSceneRecordPage: ...

    async def timeline(
        self,
        party_id: UUID,
        scene_id: UUID,
        *,
        limit: int,
        cursor: OpaqueCursor | None = None,
    ) -> OtherHumanTimelineRecordPage: ...


__all__ = (
    "OTHER_HUMAN_RECORD_PROJECTION_VERSION",
    "OtherHumanPartyRecord",
    "OtherHumanPartyRecordPage",
    "OtherHumanRecordDirection",
    "OtherHumanRecordQueryPort",
    "OtherHumanRecordViolation",
    "OtherHumanSceneRecord",
    "OtherHumanSceneRecordPage",
    "OtherHumanTimelineRecord",
    "OtherHumanTimelineRecordPage",
)
