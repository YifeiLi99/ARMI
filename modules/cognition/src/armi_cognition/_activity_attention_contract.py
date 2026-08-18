"""Strict compact model contract for one bounded Activity attention decision."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    TypeAdapter,
)

from ._creator_branch_contract import AppraisalEventSignalV1
from ._strict_model_json import strict_model_value

ACTIVITY_ATTENTION_CANDIDATE_VERSION = "armi.activity-attention-candidate.v3"


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    @property
    def schema_version(self) -> str:
        return ACTIVITY_ATTENTION_CANDIDATE_VERSION


class AttentionSimpleDecision(_StrictModel):
    kind: Literal["engage", "resume", "no_action", "defer", "need_information"]
    appraisal: AppraisalEventSignalV1 | None = None


ActivityAttentionCandidate = AttentionSimpleDecision
_ADAPTER: TypeAdapter[AttentionSimpleDecision] = TypeAdapter(AttentionSimpleDecision)


def activity_attention_candidate_schema() -> dict[str, Any]:
    return _ADAPTER.json_schema()


def parse_activity_attention_candidate(value: object) -> ActivityAttentionCandidate:
    return _ADAPTER.validate_python(strict_model_value(value), strict=True)


__all__ = (
    "ACTIVITY_ATTENTION_CANDIDATE_VERSION",
    "ActivityAttentionCandidate",
    "AttentionSimpleDecision",
    "activity_attention_candidate_schema",
    "parse_activity_attention_candidate",
)
