"""Authorized machine and Creator representations of autonomous operation."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


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


class MindDimension(AutonomyResponse):
    value: float | None = Field(ge=0, le=100)
    quality: Literal["known", "unknown", "not_applicable"]
    choice: Literal[
        "level_0",
        "level_1",
        "level_2",
        "level_3",
        "level_4",
        "unknown",
        "not_applicable",
    ]
    known_at: str | None
    basis_refs: list[str]


class MindObjectSource(AutonomyResponse):
    source_kind: str
    source_ref: str


class MindConsideration(AutonomyResponse):
    importance: MindDimension | None
    priority: float | None = Field(ge=0, le=100)
    attention_weight: float = Field(ge=0, le=100)
    condition_version: int = Field(ge=0)
    reason: str | None
    eligible: bool


class MotivationAttentionStatus(AutonomyResponse):
    object: MindObjectSource
    evaluated_at: str
    as_of: str
    association: Literal["active", "satisfied", "released", "invalid", "unknown"]
    opportunity: Literal["available", "later", "unavailable", "unknown"]
    domains: dict[
        Literal["autonomy", "competence", "relatedness", "exploration", "engagement"],
        dict[str, MindDimension | float | None],
    ]
    consideration: MindConsideration


class ConsiderationSignalItem(AutonomyResponse):
    owner: Literal["mind", "mood", "focus"]
    object_ref: str
    condition_version: str
    reason: Literal[
        "review_time_reached",
        "creator_input",
        "activity_result",
        "affective_change",
        "threshold_reached",
        "material_change",
        "opportunity_restored",
    ]
    eligible_at: str
    priority: float = Field(ge=0, le=1)
    basis_refs: list[str]


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
    autonomy_category: Literal["wake", "wait"] | None
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
