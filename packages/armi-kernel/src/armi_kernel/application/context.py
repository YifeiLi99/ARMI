"""Stable cognition episode identity shared until cognition is extracted."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from uuid import UUID


class CognitiveEpisodeStatus(StrEnum):
    PREPARING = "preparing"
    PREPARED = "prepared"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass(frozen=True, slots=True)
class CognitiveEpisodeId:
    value: UUID

    def __post_init__(self) -> None:
        if type(self.value) is not UUID or self.value.version != 7:
            raise ValueError("cognitive episode identity must be UUIDv7")

    def __str__(self) -> str:
        return str(self.value)


__all__ = ("CognitiveEpisodeId", "CognitiveEpisodeStatus")
