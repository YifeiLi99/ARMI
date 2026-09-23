"""Read-only wake decisions, not psychological events or actions."""

from enum import StrEnum


class AutonomyCategory(StrEnum):
    WAKE = "wake"
    WAIT = "wait"
