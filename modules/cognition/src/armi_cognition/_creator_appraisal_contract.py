"""Shared semantic appraisal shapes for cognitive-act contracts."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from ._dialogue_contract import ContextRef, Summary


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class CreatorAppraisalExperience(_StrictModel):
    first_person_gist: Annotated[str, StringConstraints(min_length=1, max_length=1024)]
    uncertainty: Summary | None = None
    memory_summary: Summary | None = None

    @property
    def remember(self) -> bool:
        return self.memory_summary is not None


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


class ConflictingSelfStandard(_StrictModel):
    compatibility: Literal["violation", "tension", "mixed"]
    scope: Literal["action", "global"]


class NonConflictingSelfStandard(_StrictModel):
    compatibility: Literal["aligned", "not_applicable", "unknown"]


class AppraisalStandardsSignal(_StrictModel):
    self_evaluation: Annotated[
        ConflictingSelfStandard | NonConflictingSelfStandard,
        Field(discriminator="compatibility"),
    ]
    norm_compatibility: Literal[
        "violation", "tension", "aligned", "mixed", "not_applicable", "unknown"
    ]

    @property
    def self_compatibility(self):
        return self.self_evaluation.compatibility

    @property
    def self_scope(self) -> Literal["none", "action", "global"]:
        return (
            self.self_evaluation.scope
            if isinstance(self.self_evaluation, ConflictingSelfStandard)
            else "none"
        )


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


class NewAppraisal(_StrictModel):
    transition: Literal["new"]


class ExistingAppraisal(_StrictModel):
    transition: Literal["reinforce", "reappraise", "resolve"]
    episode_ref: ContextRef
    change_from_previous: Literal[
        "improved", "unchanged", "worsened", "mixed", "unknown"
    ]


class AppraisalEventSignalV2(_StrictModel):
    trajectory: Annotated[
        NewAppraisal | ExistingAppraisal, Field(discriminator="transition")
    ]
    event_phase: Literal["anticipated", "ongoing", "realized", "averted"]
    gist: Annotated[str, StringConstraints(min_length=1, max_length=64)]
    appraisal: AppraisalSemanticSignal
    basis_refs: tuple[ContextRef, ...] = Field(min_length=1, max_length=8)

    @property
    def transition(self):
        return self.trajectory.transition

    @property
    def episode_ref(self) -> ContextRef | None:
        return (
            self.trajectory.episode_ref
            if isinstance(self.trajectory, ExistingAppraisal)
            else None
        )

    @property
    def change_from_previous(self):
        return (
            self.trajectory.change_from_previous
            if isinstance(self.trajectory, ExistingAppraisal)
            else None
        )


__all__ = (
    "AppraisalEventSignalV2",
    "AppraisalSemanticSignal",
    "CreatorAppraisalExperience",
)
