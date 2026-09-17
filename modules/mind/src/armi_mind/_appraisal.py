"""Object-bound motivational appraisal shared by the Owner and isolated tests.

These weights are an engineering hypothesis, not a validated human psychology model.
Clock time approaches a bounded target; evaluating more often cannot add stimulation.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from math import exp2
from typing import Annotated, Literal

from armi_kernel.contracts import NONBLANK_TEXT_PATTERN
from pydantic import BaseModel, ConfigDict, Field, StringConstraints

EvidenceRef = Annotated[str, StringConstraints(pattern=r"^ctx:[1-9][0-9]{0,2}$")]


class MindAppraisalParameters(BaseModel, frozen=True):
    model_config = ConfigDict(extra="forbid", strict=True)

    desired_outcome: Literal["understand", "connect", "engage"]
    significance: Literal["none", "peripheral", "important", "central", "unknown"]
    discrepancy: Literal["none", "small", "substantial", "unknown"]
    understanding: Literal["sufficient", "partial", "unexplained", "unknown"]
    progress: Literal["advancing", "stalled", "repetitive", "unknown"]
    opportunity: Literal["available", "later", "unavailable", "unknown"]
    resolution: Literal["open", "satisfied", "released"]
    explanation: Annotated[
        str,
        StringConstraints(min_length=1, max_length=512, pattern=NONBLANK_TEXT_PATTERN),
    ]


class MindAppraisal(MindAppraisalParameters, frozen=True):
    object_ref: EvidenceRef
    basis_refs: tuple[EvidenceRef, ...] = Field(min_length=1, max_length=8)


MIND_APPRAISAL_INSTRUCTIONS = (
    "评价自身当前处境。每项对应 Context 中一个具体对象和依据。已有动机应引用 current_motivation 沿原对象更新。"
    "desired_outcome 表示希望理解、交流或投入有意义活动;不输出情绪名称、强度或增量。"
    "significance 是对象的重要性;discrepancy 是希望与现实的差距,不是经过的时间。"
    "central 需要已有核心目标或长期重要关系的依据;眼前出现一个话题不使它自动成为核心。"
    "explanation 简述愿望及差距的具体依据;信息不足时不编造目标、承诺或不满。"
    "understand 需要值得弄清的具体未知,不把所有无进展都变成理解问题;"
    "engage 是希望投入有意义活动,自愿休息或独处可以已经满足。"
    "engage 的差距特指缺少有意义投入,不是所有工作受阻;保护成果、兑现承诺、修复错误等"
    "不能仅因有困难就硬归为 engage。三类都不适用时可以不返回数值动机评价,"
    "通过本轮可用的 Mind 文字变化保留其他愿望,不制造新的枚举或强度。"
    "understanding 描述理解程度;progress 描述有效进展或重复;opportunity 描述可行机会。"
    "没有依据选 unknown,无相关愿望返回空列表;不必填满三类。"
    "未回复不等于拒绝,没聊天不等于无聊;正在投入有价值活动可以没有差距。"
    "只有依据满足原愿望才 satisfied;不再值得投入可 released;工具失败或送达不等于满足。"
    "同一对象和愿望只评价一次;重复观察不算新刺激。所有字段是当前处境判断,不是要求采取行动。"
)


@dataclass(frozen=True, slots=True)
class MotivationalState:
    object_id: str
    desired_outcome: str
    appraisal: MindAppraisalParameters
    anchor_at: datetime
    anchor_level: float
    target_level: float


@dataclass(frozen=True, slots=True)
class MotivationalProjection:
    object_id: str
    tendency: str
    level: float
    opportunity: str
    uncertain: bool
    explanation: str


def _target(value: MindAppraisalParameters) -> float | None:
    if value.resolution != "open":
        return 0.0
    importance = {"none": 0.0, "peripheral": 0.25, "important": 0.65, "central": 1.0}
    gap = {"none": 0.0, "small": 0.3, "substantial": 1.0}
    factor: float | None = 1.0
    if value.desired_outcome == "understand":
        factor = {"sufficient": 0.0, "partial": 0.5, "unexplained": 1.0}.get(
            value.understanding
        )
    elif value.desired_outcome == "engage":
        factor = {"advancing": 0.0, "stalled": 0.6, "repetitive": 1.0}.get(
            value.progress
        )
    # A known absence of need is decisive even when another dimension is unknown.
    # Otherwise an old nonzero target would keep growing after the gap disappeared.
    importance_value = importance.get(value.significance)
    gap_value = gap.get(value.discrepancy)
    if 0.0 in (importance_value, gap_value, factor):
        return 0.0
    if importance_value is None or gap_value is None or factor is None:
        return None
    return 100 * importance_value * gap_value * factor


def project_motivation(
    state: MotivationalState, *, at: datetime
) -> MotivationalProjection:
    if at.tzinfo is None or at < state.anchor_at:
        raise ValueError("MIND-APPRAISAL-TIME")
    elapsed = (at - state.anchor_at).total_seconds()
    # A fixed 30-minute response half-life is an explicit experimental policy.
    level = state.target_level + (state.anchor_level - state.target_level) * exp2(
        -elapsed / 1800
    )
    return MotivationalProjection(
        state.object_id,
        {"understand": "explore", "connect": "contact", "engage": "change_activity"}[
            state.desired_outcome
        ],
        level,
        state.appraisal.opportunity,
        _target(state.appraisal) is None,
        state.appraisal.explanation,
    )


def evaluate_motivation(
    value: MindAppraisal,
    *,
    references: dict[str, str],
    at: datetime,
    previous: MotivationalState | None = None,
) -> MotivationalState:
    """Bind supplied references, then replace assessment without cumulative scoring."""
    if at.tzinfo is None:
        raise ValueError("MIND-APPRAISAL-TIME")
    if any(ref not in references for ref in (value.object_ref, *value.basis_refs)):
        raise ValueError("MIND-APPRAISAL-REFERENCE")
    object_id = references[value.object_ref]
    return evolve_motivation(value, object_id=object_id, at=at, previous=previous)


def evolve_motivation(
    value: MindAppraisalParameters,
    *,
    object_id: str,
    at: datetime,
    previous: MotivationalState | None,
) -> MotivationalState:
    if at.tzinfo is None:
        raise ValueError("MIND-APPRAISAL-TIME")
    if previous is not None and (
        previous.object_id != object_id
        or previous.desired_outcome != value.desired_outcome
    ):
        raise ValueError("MIND-APPRAISAL-OBJECT")
    level = 0.0 if previous is None else project_motivation(previous, at=at).level
    target = _target(value)
    if value.resolution != "open":
        level = 0.0
    # Unknown is not negative evidence and cannot silently erase an existing motive.
    if target is None:
        target = level if previous is None else previous.target_level
    return MotivationalState(object_id, value.desired_outcome, value, at, level, target)
