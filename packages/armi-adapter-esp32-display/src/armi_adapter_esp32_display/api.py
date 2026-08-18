"""Stable host-side mood display contracts."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class MoodDisplayViolation(ValueError):
    """The display configuration, identity, or wire contract is invalid."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class DisplayExpression(StrEnum):
    HAPPY = "happy"
    EXCITED = "excited"
    CALM = "calm"
    SAD = "sad"
    ANXIOUS = "anxious"
    ANGRY = "angry"
    DISGUSTED = "disgusted"
    EMBARRASSED = "embarrassed"
    NEUTRAL = "neutral"
    OFFLINE = "offline"


@dataclass(frozen=True, slots=True)
class MoodDisplayConfig:
    enabled: bool
    port: str
    expected_device_id: str


@dataclass(frozen=True, slots=True)
class DisplayState:
    mood_version: int
    expression: DisplayExpression
    foreground: str
    background: str
    energy: int


@dataclass(frozen=True, slots=True)
class ProbeResult:
    device_id: str
    firmware_version: str
    protocol_version: str
    boot_id: str


@dataclass(frozen=True, slots=True)
class MoodDisplayStatus:
    availability: str
    device_id: str | None = None
    reason_code: str | None = None


__all__ = (
    "DisplayExpression",
    "DisplayState",
    "MoodDisplayConfig",
    "MoodDisplayStatus",
    "MoodDisplayViolation",
    "ProbeResult",
)
