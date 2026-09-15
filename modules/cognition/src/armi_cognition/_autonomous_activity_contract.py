"""Compact model output contract for one autonomous Activity choice."""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    TypeAdapter,
)

from ._creator_appraisal_contract import AppraisalEventSignalV2
from ._strict_model_json import strict_model_value
from ._text_contract import Text1024, Text2048

AUTONOMOUS_ACTIVITY_CANDIDATE_VERSION = "armi.autonomous-activity-candidate.v6"


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    @property
    def schema_version(self) -> str:
        return AUTONOMOUS_ACTIVITY_CANDIDATE_VERSION


class StartActivityDecision(_StrictModel):
    kind: Literal["start_activity"]
    goal: Text2048
    next_step: Text1024
    appraisal: AppraisalEventSignalV2 | None = None


class AutonomousTerminalDecision(_StrictModel):
    kind: Literal["no_activity", "defer", "need_information"]
    appraisal: AppraisalEventSignalV2 | None = None


class AutonomousVisualObservationDecision(_StrictModel):
    kind: Literal["visual_observation"]
    source_kind: Literal["camera", "screen"]
    appraisal: AppraisalEventSignalV2 | None = None


AutonomousActivityCandidate = Annotated[
    StartActivityDecision
    | AutonomousTerminalDecision
    | AutonomousVisualObservationDecision,
    Field(discriminator="kind"),
]
_ADAPTER: TypeAdapter[AutonomousActivityCandidate] = TypeAdapter(
    AutonomousActivityCandidate
)


def autonomous_activity_candidate_schema() -> dict[str, Any]:
    return _ADAPTER.json_schema()


def parse_autonomous_activity_candidate(value: object) -> AutonomousActivityCandidate:
    return _ADAPTER.validate_python(strict_model_value(value), strict=True)


__all__ = (
    "AUTONOMOUS_ACTIVITY_CANDIDATE_VERSION",
    "AutonomousActivityCandidate",
    "AutonomousTerminalDecision",
    "AutonomousVisualObservationDecision",
    "StartActivityDecision",
    "autonomous_activity_candidate_schema",
    "parse_autonomous_activity_candidate",
)
