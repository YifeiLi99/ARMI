"""Compact untrusted model output for one sleep decision."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, TypeAdapter

from ._decision_basis import DecisionBasis
from ._strict_model_json import strict_model_value

SLEEP_DECISION_CANDIDATE_VERSION = "armi.sleep-decision-candidate"


class SleepDecisionCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)
    kind: Literal["sleep", "stay_awake", "defer", "need_information"]
    decision_basis: DecisionBasis | None = None

    @property
    def schema_kind(self) -> str:
        return SLEEP_DECISION_CANDIDATE_VERSION


_ADAPTER = TypeAdapter(SleepDecisionCandidate)


def sleep_decision_candidate_schema() -> dict[str, Any]:
    return _ADAPTER.json_schema()


def parse_sleep_decision_candidate(value: object) -> SleepDecisionCandidate:
    return _ADAPTER.validate_python(strict_model_value(value), strict=True)


__all__ = (
    "SLEEP_DECISION_CANDIDATE_VERSION",
    "SleepDecisionCandidate",
    "parse_sleep_decision_candidate",
    "sleep_decision_candidate_schema",
)
