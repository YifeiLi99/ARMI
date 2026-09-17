"""Shared semantic appraisal shapes for cognitive-act contracts."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

ContextRef = Annotated[
    str, StringConstraints(pattern=r"^ctx:[1-9][0-9]{0,2}$", max_length=7)
]


class _StrictModel(BaseModel, frozen=True):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class AppraisalConcernSignal(_StrictModel, frozen=True):
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


class AppraisalDemandSignal(_StrictModel, frozen=True):
    urgency: Literal["none", "can_wait", "soon", "immediate", "unknown"]
    effort: Literal["none", "light", "substantial", "extreme", "unknown"]


class AppraisalCausalitySignal(_StrictModel, frozen=True):
    agency: Literal["self", "other", "shared", "circumstance", "unknown"]
    intentionality: Literal[
        "accidental", "unclear", "deliberate", "not_applicable", "unknown"
    ]


class AppraisalCopingSignal(_StrictModel, frozen=True):
    response_access: Literal["none", "indirect", "direct", "resolved", "unknown"]
    power_balance: Literal[
        "overmatched", "limited", "balanced", "advantaged", "unknown"
    ]
    adjustment: Literal["blocked", "difficult", "manageable", "easy", "unknown"]


class ConflictingSelfStandard(_StrictModel, frozen=True):
    compatibility: Literal["violation", "tension", "mixed"]
    scope: Literal["action", "global"]


class NonConflictingSelfStandard(_StrictModel, frozen=True):
    compatibility: Literal["aligned", "not_applicable", "unknown"]


class AppraisalStandardsSignal(_StrictModel, frozen=True):
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


class AppraisalSemanticSignal(_StrictModel, frozen=True):
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


class NewAppraisal(_StrictModel, frozen=True):
    transition: Literal["new"]


class ExistingAppraisal(_StrictModel, frozen=True):
    transition: Literal["reinforce", "reappraise", "resolve"]
    episode_ref: ContextRef
    change_from_previous: Literal[
        "improved", "unchanged", "worsened", "mixed", "unknown"
    ]


class AppraisalEventSignalV2(_StrictModel, frozen=True):
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
)

Uuid7Value = Annotated[
    str,
    StringConstraints(
        pattern=(
            r"^[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-"
            r"[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
        ),
        max_length=36,
    ),
]


class MoodVAD(_StrictModel, frozen=True):
    valence: Annotated[int, Field(ge=-100, le=100)]
    arousal: Annotated[int, Field(ge=-100, le=100)]
    dominance: Annotated[int, Field(ge=-100, le=100)]


class MoodState(_StrictModel, frozen=True):
    schema_version: Literal["armi.mood.v3"]
    dynamics_version: Literal["recency-reappraisal.v1"]
    derivation_version: Literal["cpm-fuzzy.v2"]
    home_base: MoodVAD


class MoodSemanticAppraisalCommand(_StrictModel, frozen=True):
    schema_version: Literal["armi.mood-appraisal.v2"]
    transition: Literal["new", "reinforce", "reappraise", "resolve"]
    previous_episode_id: str | None
    event_phase: Literal["anticipated", "ongoing", "realized", "averted"]
    gist: Annotated[str, StringConstraints(min_length=1, max_length=64)]
    change_from_previous: (
        Literal["improved", "unchanged", "worsened", "mixed", "unknown"] | None
    )
    appraisal: AppraisalSemanticSignal


class NewMoodAppraisalCommand(MoodSemanticAppraisalCommand, frozen=True):
    transition: Literal["new"]
    previous_episode_id: None = None
    change_from_previous: None = None


class ExistingMoodAppraisalCommand(MoodSemanticAppraisalCommand, frozen=True):
    transition: Literal["reinforce", "reappraise", "resolve"]
    previous_episode_id: Uuid7Value = Field(...)
    change_from_previous: Literal[
        "improved", "unchanged", "worsened", "mixed", "unknown"
    ] = Field(...)


type MoodAppraisalCommandWire = Annotated[
    NewMoodAppraisalCommand | ExistingMoodAppraisalCommand,
    Field(discriminator="transition"),
]


MOOD_CONTEXT_REFERENCES = (
    ("ExistingAppraisal", "episode_ref", "active_affective_episode"),
)
