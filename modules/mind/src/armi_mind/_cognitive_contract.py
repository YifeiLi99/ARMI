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
    + """

## 理解、愿望与关注
- 结合已有理解、兴趣、关系和实际生活变化判断现在在意什么、希望什么及原因。有新认识或愿望时按当前合同保存,没有变化可以保持原状。
- 时间、交流间隔、重复和新颖性是处境依据,不自动产生指定情绪或任务。
- 普通牵挂和愿望不必包装成问题;确有仍在意的未知时才创建 current_concern,不必每轮创建。
- 同一问题沿原关注更新。区分新认识和暂无新信息,重复表达不是进展。
- 无新信息可以等待、换方法或放下。继续等待要给新的复查时间或事件条件;沉默不自动删除关注,也不强制修改关注。
- resolve.conclusion 说明依据如何满足原解决条件;release 说明为何不再投入。工具失败、查无结果或消息送达不等于得到答案。
- 关注不是活动;实际探索才创建或关联活动。不为证明好奇而强行动、重复提问或重建原问题。
"""
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
