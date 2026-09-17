"""Mind-owned cognitive state shape; storage additionally retains owner records."""

from typing import Annotated, Any, Literal

from armi_kernel.contracts import NONBLANK_TEXT_PATTERN
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from ._appraisal import MIND_APPRAISAL_INSTRUCTIONS

Summary = Annotated[
    str, StringConstraints(min_length=1, max_length=512, pattern=NONBLANK_TEXT_PATTERN)
]


class _StrictModel(BaseModel, frozen=True):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class MindState(_StrictModel, frozen=True):
    schema_version: Literal["armi.mind.v4"]
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
    MIND_APPRAISAL_INSTRUCTIONS
    + "结合当前理解、兴趣、关系和实际生活变化,可以重新评价自己现在在意什么、希望什么以及为何想行动。"
    "时间经过、交流间隔、重复或新颖性只是处境依据,不自动等于任何指定情绪或任务。"
    "有新认识或愿望时通过当前合同允许的 Mind 变更保存;没有变化可以保持原状。"
    "普通牵挂、愿望或想换一种活动不必伪装成待解答问题;有具体未知问题时才形成 current_concern。"
    "current_concern 是仍在意的具体问题,可以源于兴趣、困惑或新线索,不必每轮形成关注。"
    "同一问题沿原关注更新;明确区分获得新认识和目前没有新信息,重复表达不算进展。"
    "无新信息时可以等待、换方法或放下。继续等待须给新的复查时间或事件条件;沉默不自动删除关注,也不强制修改关注。"
    "resolve 的 conclusion 要说明现有依据如何满足原解决条件;release 可以说明不再值得投入。"
    "工具失败、查询无结果和消息送达不是获得答案。关注不是活动,只有实际探索才创建或关联活动。"
    "不要为证明好奇强制行动、重复提问或无依据地重建原问题。"
)


class DialogueSummaryListReplacement(_StrictModel, frozen=True):
    values: tuple[Summary, ...] = Field(
        max_length=16, json_schema_extra={"uniqueItems": True}
    )

    @model_validator(mode="after")
    def validate_values(self) -> DialogueSummaryListReplacement:
        if len(self.values) != len(set(self.values)):
            raise ValueError("summary replacement contains duplicates")
        return self


def _nonempty_change_schema(schema: dict[str, Any]) -> None:
    """Express a nonempty update with complete object alternatives, not predicates."""
    properties = schema.pop("properties")
    schema.pop("type", None)
    schema.pop("additionalProperties", None)
    schema["anyOf"] = [
        {
            "type": "object",
            "properties": {
                **properties,
                name: {
                    "anyOf": [
                        branch
                        for branch in value["anyOf"]
                        if branch.get("type") != "null"
                    ]
                },
            },
            "required": [name],
            "additionalProperties": False,
        }
        for name, value in properties.items()
    ]


class DialogueMindChange(_StrictModel, frozen=True):
    model_config = ConfigDict(json_schema_extra=_nonempty_change_schema)
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


class GroundedMindChange(_StrictModel, frozen=True):
    change: DialogueMindChange
    basis_refs: tuple[
        Annotated[str, StringConstraints(pattern=r"^ctx:[1-9][0-9]{0,2}$")], ...
    ] = Field(min_length=1, max_length=7)


def apply_mind_text_change(payload: bytes, change: DialogueMindChange) -> MindState:
    from ._projection import mind_editable_state

    current = MindState.model_validate_json(mind_editable_state(payload), strict=True)
    updates = {
        field: replacement.values
        for field in type(change).model_fields
        if (replacement := getattr(change, field)) is not None
    }
    return MindState.model_validate({**current.model_dump(), **updates}, strict=True)
