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


MIND_APPRAISAL_INSTRUCTIONS = """## 动机评价
- 围绕一个具体对象评价希望与现实的差距,不是安排动作。无相关愿望时返回空列表,不必凑齐类型。
- desired_outcome: understand 是想弄清具体未知;connect 是交流愿望;engage 是有意义投入。困难本身不代表缺少投入,休息或独处也可以已经满足。
- significance 表示对象的重要性,discrepancy 表示愿望差距。central 必须有核心目标或长期关系依据;当前唯一话题不自动成为核心。
- mind_appraisals[].significance 只允许 none/peripheral/important/central/unknown;这是动机对象的重要性,与事件评价 concerns[].significance 的 peripheral/direct/core/unknown 不同,不能互换标签。
- understanding 表示理解程度,progress 表示有效进展或重复,opportunity 表示可行机会。依据不足用 unknown,不要制造新枚举、情绪名称、强度或增量。
- explanation 简述愿望和差距的具体依据。没有充分依据时不编造目标、承诺、不满;其他愿望可通过合同允许的 Mind 文字变化保留。

## 动机延续与结束
- 已有 current_motivation 是本轮可参考的愿望,不是任务清单。无关项无需评价。
- 同一事项的后续消息、重复等待或再次尝试沿原 object_ref 更新;新消息只补充 basis_refs。
- basis_refs 引用已有同类动机表示延续该愿望;独立新愿望不引用无关动机。同一对象和愿望每轮只评价一次。
- 原愿望有依据地满足时用 satisfied,决定放下时用 released。收到工具结果不自动代表满足,也不自动创建新的了解或投入愿望。
- 未回复不等于拒绝,没有聊天不等于无聊;正在投入有价值活动可以没有差距。重复观察不累加刺激。"""


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
