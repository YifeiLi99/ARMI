"""Authorized machine and Creator representations of autonomous operation."""

from typing import Literal

from pydantic import BaseModel, ConfigDict


class AutonomyResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class AutonomyPolicyResponse(AutonomyResponse):
    enabled: bool
    daily_request_limit: int
    minimum_consideration_seconds: int
    maximum_consideration_seconds: int
    outlet: Literal["qq", "creator_web"]


class ConcernAttentionStatus(AutonomyResponse):
    concern_id: str
    question: str
    state: Literal["open", "waiting"]
    review_kind: Literal["review", "creator_input", "activity_result"]
    review_reason: str
    review_at: str | None
    condition_state: Literal["scheduled", "due", "consumed", "waiting_for_event"]


class AutonomyStatus(AutonomyResponse):
    concerns: list[ConcernAttentionStatus] = []
    observed_at: str | None = None
    last_considered_at: str | None = None
    state: Literal[
        "not_initialized",
        "disabled",
        "runtime_stopped",
        "sleeping",
        "quota_exhausted",
        "thinking",
        "resource_busy",
        "scheduled",
        "ready",
    ]
    plan_version: int | None = None
    next_consideration_at: str | None = None
    source_episode_id: str | None = None
    opportunity_id: str | None = None
    policy: AutonomyPolicyResponse | None = None
    outlet_state: Literal["ready", "disabled", "unbound", "unavailable"] | None = None
    outlet_reason_code: str | None = None
    outlet_observed_at: str | None = None
    used_requests: int | None = None
    remaining_requests: int | None = None
    quota_resets_at: str | None = None
    timezone: Literal["Asia/Shanghai"] = "Asia/Shanghai"


class AutonomyHistoryItem(AutonomyResponse):
    operation_id: str
    available_after: str
    current_disposition: str
    resolution_reason_code: str | None
    episode_id: str | None
    cognition_status: str | None
    final_disposition: str | None
    failure_code: str | None
    effect_id: str | None
    effect_status: str | None


class AutonomyHistory(AutonomyResponse):
    items: list[AutonomyHistoryItem]
    total: int
    limit: int
    offset: int


__all__ = ("AutonomyHistory", "AutonomyStatus")
