"""Shared semantic appraisal shapes for cognitive-act contracts."""

from __future__ import annotations

import re
from typing import Annotated, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
)

MOOD_APPRAISAL_INSTRUCTIONS = (
    "评价事件对当前目标、关系及自我标准的意义,不直接选择情绪或填写分数。"
    "standards 只评价 Context 中有依据的个人准则或社会规范;偏好没有满足、暂时没进展、"
    "休息或选择独处本身不构成准则冲突。没有相关准则时用 not_applicable,资料不足用 unknown。"
    "自我标准冲突的 action 指具体行为违背已有准则;global 仅在明确出现整体自我否定时使用,"
    "不能从一次失误推断。causality 描述事件的责任与控制来源,不因事情发生在自己身上就归因 self。"
    "intentionality 指是否有意造成当前被评价的后果,不是仅指动作是否有意识;"
    "无法确定对该后果的意图时用 unclear 或 unknown,不从正常设定边界推断有意伤害。"
    "intrinsic_quality 评价内容或体验本身的吸引或排斥,不等于目标受挫程度;"
    "strongly_aversive 需要强烈排斥的依据,损失严重不自动代表该项。"
    "关系暂未联系不等于关系受损;回应缺失不等于明确拒绝。significance 和 self_involvement "
    "依据已有目标、关系与身份,不因某事是当前唯一话题就判为 core 或 identity_level。"
    "engagement 评价当前活动是否提供所需投入:重复且想投入却无收获可为 understimulated;"
    "自愿休息、安静等待或正在持续取得进展不因此归为 understimulated。"
    "各维度可以不同:有未满足愿望也可能感受愉快,事情不愉快也不必归咎自己。"
    "concerns.target=relationship 评价信任、亲近或关系延续本身;暂时不能聊天可影响 self_goal 的"
    "当下交流愿望,但对方合理独处、忙碌或设定边界不自动意味着关系受损。"
    "self_evaluation=aligned 只说明符合准则,不是值得自豪的成就;若没有相关准则用 not_applicable。"
    "anticipated 事件的 direction 评价所预期后果对目标的方向,outcome_certainty 单独评价是否会发生。"
    "已知若发生会损害目标但尚不确定发生时,不要把已知负向影响写成 unknown;"
    "只有连影响方向也不清楚时才选 unknown。"
)

Gist = Annotated[
    str,
    StringConstraints(
        min_length=1,
        max_length=64,
        # A bare dollar also matches before a final newline in ECMA/Python regexes.
        pattern=re.compile(
            r"^[^\s\x00\x1c-\x1f](?:[^\x00]*[^\s\x00\x1c-\x1f])?$(?![\s\S])"
        ),
    ),
]

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
    engagement: Literal[
        "satisfying", "understimulated", "overloaded", "not_applicable", "unknown"
    ] = Field(
        default="unknown",
        description="Assess meaningful engagement. Quiet waiting alone is not understimulation; describe the situation, not an emotion label.",
    )
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


class AppraisalEventSignalV3(_StrictModel, frozen=True):
    trajectory: Annotated[
        NewAppraisal | ExistingAppraisal, Field(discriminator="transition")
    ]
    event_phase: Literal["anticipated", "ongoing", "realized", "averted"]
    gist: Gist
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
    "AppraisalEventSignalV3",
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
    schema_version: Literal["armi.mood.v4"]
    dynamics_version: Literal["recency-reappraisal.v1"]
    derivation_version: Literal["cpm-fuzzy.v3"]
    home_base: MoodVAD


class MoodSemanticAppraisalCommand(_StrictModel, frozen=True):
    schema_version: Literal["armi.mood-appraisal.v3"]
    transition: Literal["new", "reinforce", "reappraise", "resolve"]
    previous_episode_id: str | None
    event_phase: Literal["anticipated", "ongoing", "realized", "averted"]
    gist: Gist
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
