"""Strict contracts for owner-specific background reflection."""

from __future__ import annotations

# ruff: noqa: RUF001
from typing import Annotated, Literal, cast

from armi_mind.api import MIND_APPRAISAL_INSTRUCTIONS, MindAppraisal
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    TypeAdapter,
)

from ._dialogue_contract import ContextRef, DialogueSubjectPromptChange
from ._model_contract import MindState, SelfState
from ._strict_model_json import strict_model_value

OWNER_REFLECTION_CANDIDATE_VERSION = "armi.owner-reflection-candidate.v4"

REFLECT_SELF_INSTRUCTIONS = """\
你只负责 Self Owner 的专项反思。可报告无需变化，或基于冻结资料提交一个完整 SelfState 候选及其当前 expected_version。不得修改 Mind、Mood、Prompt、记忆、关系、活动或对外表达。只输出给定 JSON Schema。"""
REFLECT_MIND_INSTRUCTIONS = (
    "你只负责 Mind Owner 的专项反思。可报告无需变化，或基于冻结资料提交一个完整 MindState 候选及其当前 expected_version，"
    "同时可提交 mind_appraisals。不得修改 Self、Mood、Prompt、记忆、关系、活动或对外表达。只输出给定 JSON Schema。"
    + MIND_APPRAISAL_INSTRUCTIONS
)
REFLECT_MOOD_INSTRUCTIONS = """\
你只负责请求 Mood Owner 执行长期基线反思，不能填写 home_base、情绪、VAD 或任何动力学参数。冻结资料存在心情状态时可提交空的 MoodReflectionRequest 及当前 expected_version；证据门槛、时间采样、目标和每轴调整全部由 Mood Owner 确定。不得删除事件，或修改 Self、Mind、Prompt、记忆、关系、活动和对外表达。只输出给定 JSON Schema。"""
REFLECT_PROMPT_INSTRUCTIONS = """\
你只负责主体 Prompt Owner 的专项反思。可报告无需变化，或基于冻结资料提交 cognition_method、expression_method、reflection_method 三项完整候选及当前 expected_version。不得修改 Self、Mind、Mood、记忆、关系、活动或对外表达。只输出给定 JSON Schema。"""


class _StrictModel(BaseModel, frozen=True):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    @property
    def schema_version(self) -> str:
        return OWNER_REFLECTION_CANDIDATE_VERSION


class MoodReflectionRequest(_StrictModel, frozen=True):
    pass


class OwnerReflectionCandidate(_StrictModel, frozen=True):
    kind: Literal["no_change", "update"]
    target: Literal["self", "mind", "mood", "prompt"]
    summary: Annotated[str, StringConstraints(min_length=1, max_length=512)]
    basis_refs: tuple[ContextRef, ...] = Field(max_length=8)
    expected_version: int | None
    next_state: (
        SelfState
        | MindState
        | MoodReflectionRequest
        | DialogueSubjectPromptChange
        | None
    )


class NoReflectionChange(OwnerReflectionCandidate, frozen=True):
    kind: Literal["no_change"]
    basis_refs: tuple[ContextRef, ...] = Field(default=(), max_length=8)
    expected_version: None = None
    next_state: None = None


class _ReflectionUpdate(OwnerReflectionCandidate, frozen=True):
    kind: Literal["update"]
    basis_refs: tuple[ContextRef, ...] = Field(..., min_length=1, max_length=8)
    expected_version: int = Field(..., ge=1)


class SelfReflectionUpdate(_ReflectionUpdate, frozen=True):
    target: Literal["self"]
    next_state: SelfState = Field(...)


class MindReflectionUpdate(_ReflectionUpdate, frozen=True):
    mind_appraisals: tuple[MindAppraisal, ...] = Field(default=(), max_length=4)
    target: Literal["mind"]
    next_state: MindState = Field(...)


class MoodReflectionUpdate(_ReflectionUpdate, frozen=True):
    target: Literal["mood"]
    next_state: MoodReflectionRequest = Field(...)


class PromptReflectionUpdate(_ReflectionUpdate, frozen=True):
    target: Literal["prompt"]
    expected_version: int = Field(..., ge=0)
    next_state: DialogueSubjectPromptChange = Field(...)


ReflectionWire = Annotated[
    NoReflectionChange
    | Annotated[
        SelfReflectionUpdate
        | MindReflectionUpdate
        | MoodReflectionUpdate
        | PromptReflectionUpdate,
        Field(discriminator="target"),
    ],
    Field(discriminator="kind"),
]
_ADAPTER: TypeAdapter[OwnerReflectionCandidate] = TypeAdapter(ReflectionWire)


class NoSelfChange(NoReflectionChange, frozen=True):
    target: Literal["self"]


class NoMindChange(NoReflectionChange, frozen=True):
    target: Literal["mind"]


class NoMoodChange(NoReflectionChange, frozen=True):
    target: Literal["mood"]


class NoPromptChange(NoReflectionChange, frozen=True):
    target: Literal["prompt"]


_TARGET_ADAPTERS: dict[str, TypeAdapter[OwnerReflectionCandidate]] = {
    "self": TypeAdapter(
        Annotated[NoSelfChange | SelfReflectionUpdate, Field(discriminator="kind")]
    ),
    "mind": TypeAdapter(
        Annotated[NoMindChange | MindReflectionUpdate, Field(discriminator="kind")]
    ),
    "mood": TypeAdapter(
        Annotated[NoMoodChange | MoodReflectionUpdate, Field(discriminator="kind")]
    ),
    "prompt": TypeAdapter(
        Annotated[NoPromptChange | PromptReflectionUpdate, Field(discriminator="kind")]
    ),
}


def owner_reflection_schema(*, target: str | None = None) -> dict[str, object]:
    adapter = _ADAPTER if target is None else _TARGET_ADAPTERS[target]
    return cast(dict[str, object], adapter.json_schema())


def parse_owner_reflection(
    value: object,
    *,
    allowed_context_refs: frozenset[str],
    target: str | None = None,
) -> OwnerReflectionCandidate:
    adapter = _ADAPTER if target is None else _TARGET_ADAPTERS[target]
    candidate = adapter.validate_python(strict_model_value(value), strict=True)
    if not set(candidate.basis_refs).issubset(allowed_context_refs):
        raise ValueError("reflection references unavailable context")
    return candidate


__all__ = (
    "OWNER_REFLECTION_CANDIDATE_VERSION",
    "REFLECT_MIND_INSTRUCTIONS",
    "REFLECT_MOOD_INSTRUCTIONS",
    "REFLECT_PROMPT_INSTRUCTIONS",
    "REFLECT_SELF_INSTRUCTIONS",
    "MoodReflectionRequest",
    "OwnerReflectionCandidate",
    "owner_reflection_schema",
    "parse_owner_reflection",
)
