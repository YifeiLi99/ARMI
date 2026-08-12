"""Compact model output contract for one autonomous Activity choice."""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    TypeAdapter,
    field_validator,
)

AUTONOMOUS_ACTIVITY_CANDIDATE_VERSION = "armi.autonomous-activity-candidate.v1"


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    @property
    def schema_version(self) -> str:
        return AUTONOMOUS_ACTIVITY_CANDIDATE_VERSION


class StartActivityDecision(_StrictModel):
    kind: Literal["start_activity"]
    goal: Annotated[str, StringConstraints(min_length=1, max_length=2048)]
    next_step: Annotated[str, StringConstraints(min_length=1, max_length=1024)]

    @field_validator("goal")
    @classmethod
    def _validate_goal_bytes(cls, value: str) -> str:
        return _bounded_utf8(value, 2048)

    @field_validator("next_step")
    @classmethod
    def _validate_next_step_bytes(cls, value: str) -> str:
        return _bounded_utf8(value, 1024)


class AutonomousTerminalDecision(_StrictModel):
    kind: Literal["no_activity", "defer", "need_information"]


AutonomousActivityCandidate = Annotated[
    StartActivityDecision | AutonomousTerminalDecision,
    Field(discriminator="kind"),
]
_ADAPTER: TypeAdapter[AutonomousActivityCandidate] = TypeAdapter(
    AutonomousActivityCandidate
)


def _bounded_utf8(value: str, maximum: int) -> str:
    try:
        encoded = value.encode("utf-8", errors="strict")
    except UnicodeEncodeError as exc:
        raise ValueError("text must be strict UTF-8") from exc
    if not 1 <= len(encoded) <= maximum:
        raise ValueError("text exceeds UTF-8 byte boundary")
    return value


def autonomous_activity_candidate_schema() -> dict[str, Any]:
    return _ADAPTER.json_schema()


def parse_autonomous_activity_candidate(value: object) -> AutonomousActivityCandidate:
    return _ADAPTER.validate_python(value, strict=True)


__all__ = (
    "AUTONOMOUS_ACTIVITY_CANDIDATE_VERSION",
    "AutonomousActivityCandidate",
    "AutonomousTerminalDecision",
    "StartActivityDecision",
    "autonomous_activity_candidate_schema",
    "parse_autonomous_activity_candidate",
)
