"""Mind-owned cognitive state shape; storage additionally retains owner records."""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

Summary = Annotated[str, StringConstraints(min_length=1, max_length=512)]


class _StrictModel(BaseModel, frozen=True):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class MindState(_StrictModel, frozen=True):
    schema_version: Literal["armi.mind.v3"]
    understanding: tuple[Summary, ...] = Field(max_length=16)
    attention: tuple[Summary, ...] = Field(max_length=16)
    thoughts: tuple[Summary, ...] = Field(max_length=16)
    wishes: tuple[Summary, ...] = Field(max_length=16)
    motivations: tuple[Summary, ...] = Field(max_length=16)


MIND_CONTEXT_REFERENCES = (
    ("UpdateConcern", "concern_ref", "current_concern"),
    ("CloseConcern", "concern_ref", "current_concern"),
    ("ActivityReview", "activity_ref", "current_activity"),
)

MIND_COGNITIVE_INSTRUCTIONS = (
    "current_concern 是仍在意的具体问题,可以源于兴趣、困惑或新线索,不必每轮形成关注。"
    "同一问题沿原关注更新;明确区分获得新认识和目前没有新信息,重复表达不算进展。"
    "无新信息时可以等待、换方法或放下。继续等待须给新的复查时间或事件条件;沉默不自动删除关注,也不强制修改关注。"
    "resolve 的 conclusion 要说明现有依据如何满足原解决条件;release 可以说明不再值得投入。"
    "工具失败、查询无结果和消息送达不是获得答案。关注不是活动,只有实际探索才创建或关联活动。"
    "不要为证明好奇强制行动、重复提问或无依据地重建原问题。"
)


class DialogueSummaryListReplacement(_StrictModel, frozen=True):
    values: tuple[Summary, ...] = Field(max_length=16)

    @model_validator(mode="after")
    def validate_values(self) -> DialogueSummaryListReplacement:
        if any(not value.strip() or "\x00" in value for value in self.values):
            raise ValueError("summary replacement is invalid")
        if len(self.values) != len(set(self.values)):
            raise ValueError("summary replacement contains duplicates")
        return self


class DialogueMindChange(_StrictModel, frozen=True):
    understanding: DialogueSummaryListReplacement | None = None
    attention: DialogueSummaryListReplacement | None = None
    thoughts: DialogueSummaryListReplacement | None = None
    wishes: DialogueSummaryListReplacement | None = None
    motivations: DialogueSummaryListReplacement | None = None

    @model_validator(mode="after")
    def validate_change(self) -> DialogueMindChange:
        if all(getattr(self, field) is None for field in type(self).model_fields):
            raise ValueError("mind change is empty")
        return self


def apply_mind_text_change(payload: bytes, change: DialogueMindChange) -> MindState:
    from ._projection import mind_editable_state

    current = MindState.model_validate_json(mind_editable_state(payload), strict=True)
    updates = {
        field: replacement.values
        for field in type(change).model_fields
        if (replacement := getattr(change, field)) is not None
    }
    return MindState.model_validate({**current.model_dump(), **updates}, strict=True)
