"""Autonomous attention directions, not permissions or executable actions."""

from enum import StrEnum


class AutonomyCategory(StrEnum):
    CONTINUE_ACTIVITY = "continue_activity"
    EXPLORE = "explore"
    COMMUNICATE = "communicate"
    REFLECT = "reflect"
    WAIT = "wait"
