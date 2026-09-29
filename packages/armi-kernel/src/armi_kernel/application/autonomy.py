"""Read-only wake decisions, not psychological events or actions."""

from enum import StrEnum


class AutonomyCategory(StrEnum):
    REST = "rest"
    REFLECT = "reflect"
    CONTINUE = "continue"
    EXPLORE = "explore"
    CONNECT = "connect"
    UNDETERMINED = "undetermined"
