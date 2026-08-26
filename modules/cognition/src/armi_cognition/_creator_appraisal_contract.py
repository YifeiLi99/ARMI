"""Shared semantic appraisal shapes for cognitive-act contracts."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from ._dialogue_contract import ContextRef, Summary


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class CreatorAppraisalExperience(_StrictModel):
    first_person_gist: Annotated[str, StringConstraints(min_length=1, max_length=1024)]
    uncertainty: Summary | None = None
    remember: bool
    memory_summary: Summary | None = None

    @model_validator(mode="after")
    def validate_memory(self) -> CreatorAppraisalExperience:
        if self.remember != (self.memory_summary is not None):
            raise ValueError("explicit memory shape is invalid")
        return self


class AppraisalConcernSignal(_StrictModel):
    target: Literal["self_goal", "relationship", "social_order"]
    significance: Literal["peripheral", "direct", "core", "unknown"]
    direction: Literal[
        "major_setback",
        "setback",
        "unchanged",
        "progress",
        "fulfilled",
        "mixed",
        "unknown",
    ]


class AppraisalDemandSignal(_StrictModel):
    urgency: Literal["none", "can_wait", "soon", "immediate", "unknown"]
    effort: Literal["none", "light", "substantial", "extreme", "unknown"]


class AppraisalCausalitySignal(_StrictModel):
    agency: Literal["self", "other", "shared", "circumstance", "unknown"]
    intentionality: Literal[
        "accidental", "unclear", "deliberate", "not_applicable", "unknown"
    ]


class AppraisalCopingSignal(_StrictModel):
    response_access: Literal["none", "indirect", "direct", "resolved", "unknown"]
    power_balance: Literal[
        "overmatched", "limited", "balanced", "advantaged", "unknown"
    ]
    adjustment: Literal["blocked", "difficult", "manageable", "easy", "unknown"]


class AppraisalStandardsSignal(_StrictModel):
    self_compatibility: Literal[
        "violation", "tension", "aligned", "mixed", "not_applicable", "unknown"
    ]
    norm_compatibility: Literal[
        "violation", "tension", "aligned", "mixed", "not_applicable", "unknown"
    ]
    self_scope: Literal["none", "action", "global"]

    @model_validator(mode="after")
    def validate_scope(self) -> AppraisalStandardsSignal:
        conflict = self.self_compatibility in {"violation", "tension", "mixed"}
        if conflict != (self.self_scope != "none"):
            raise ValueError("self compatibility and scope do not match")
        return self


class AppraisalSemanticSignal(_StrictModel):
    concerns: tuple[AppraisalConcernSignal, ...] = Field(min_length=1, max_length=3)
    expectedness: Literal[
        "expected", "somewhat_unexpected", "expectation_broken", "unknown"
    ]
    outcome_certainty: Literal["open", "uncertain", "likely", "settled", "unknown"]
    intrinsic_quality: Literal[
        "strongly_aversive",
        "unpleasant",
        "neutral",
        "pleasant",
        "strongly_pleasant",
        "mixed",
        "unknown",
    ]
    self_involvement: Literal[
        "none", "limited", "important", "identity_level", "unknown"
    ]
    demand: AppraisalDemandSignal | None = None
    causality: AppraisalCausalitySignal | None = None
    coping: AppraisalCopingSignal | None = None
    standards: AppraisalStandardsSignal | None = None

    @model_validator(mode="after")
    def validate_concerns(self) -> AppraisalSemanticSignal:
        if len({item.target for item in self.concerns}) != len(self.concerns):
            raise ValueError("appraisal concern targets must be unique")
        return self


class AppraisalEventSignalV2(_StrictModel):
    transition: Literal["new", "reinforce", "reappraise", "resolve"]
    episode_ref: ContextRef | None = None
    event_phase: Literal["anticipated", "ongoing", "realized", "averted"]
    gist: Annotated[str, StringConstraints(min_length=1, max_length=64)]
    change_from_previous: (
        Literal["improved", "unchanged", "worsened", "mixed", "unknown"] | None
    ) = None
    appraisal: AppraisalSemanticSignal
    basis_refs: tuple[ContextRef, ...] = Field(min_length=1, max_length=8)

    @model_validator(mode="after")
    def validate_signal(self) -> AppraisalEventSignalV2:
        is_new = self.transition == "new"
        if is_new != (self.episode_ref is None):
            raise ValueError("appraisal transition and episode reference do not match")
        if is_new != (self.change_from_previous is None):
            raise ValueError("appraisal transition and trajectory do not match")
        return self


__all__ = (
    "AppraisalEventSignalV2",
    "AppraisalSemanticSignal",
    "CreatorAppraisalExperience",
)
