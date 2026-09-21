"""Authorized machine and Creator representations of autonomous operation."""

from typing import Literal

from pydantic import BaseModel, ConfigDict


class AutonomyResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class AutonomyPolicyResponse(AutonomyResponse):
    enabled: bool
    outlet: Literal["qq", "creator_web"]


class ConcernAttentionStatus(AutonomyResponse):
    concern_id: str
    question: str
    state: Literal["open", "waiting"]
    review_kind: Literal["review", "creator_input", "activity_result"]
    review_reason: str
    review_at: str | None
    condition_state: Literal["scheduled", "due", "consumed", "waiting_for_event"]


class MotivationAttentionStatus(AutonomyResponse):
    motivation_id: str
    object_kind: str
    assessment: dict[str, str]
    tendency: Literal["explore", "contact", "change_activity", "none"]
    level: float
    uncertain: bool
    review_at: str | None
    condition_state: Literal["scheduled", "due", "consumed", "waiting_for_event"]


class ConsiderationSignalItem(AutonomyResponse):
    owner: Literal["mind", "mood"]
    object_ref: str
    condition_version: str
    reason: Literal[
        "review_time_reached", "creator_input", "activity_result", "affective_change"
    ]
    eligible_at: str


class ConsiderationSignals(AutonomyResponse):
    schema_kind: Literal["armi.consideration-signals"]
    signals: list[ConsiderationSignalItem]
    frozen_at: str | None


class AutonomyStageUsage(AutonomyResponse):
    calls: int
    input_tokens: int
    output_tokens: int
    elapsed_ms: float
    unknown_calls: int


class AutonomyStatus(AutonomyResponse):
    phase: Literal["waiting", "check", "execute", "blocked"] | None = None
    idle_streak: int | None = None
    failure_streak: int | None = None
    last_engage: bool | None = None
    last_check_started_at: str | None = None
    blocked_reason_code: str | None = None
    stage_usage: dict[Literal["check", "execute"], AutonomyStageUsage] = {}
    consideration_signals: list[ConsiderationSignalItem] = []
    effective_consideration_at: str | None = None
    concerns: list[ConcernAttentionStatus] = []
    motivations: list[MotivationAttentionStatus] = []
    observed_at: str | None = None
    last_considered_at: str | None = None
    state: Literal[
        "not_initialized",
        "disabled",
        "runtime_stopped",
        "sleeping",
        "blocked",
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
    timezone: Literal["Asia/Shanghai"] = "Asia/Shanghai"


class AutonomyHistoryItem(AutonomyResponse):
    stage: Literal["check", "execute"]
    root_opportunity_id: str
    predecessor_opportunity_id: str | None
    consideration_signals: ConsiderationSignals | None

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
