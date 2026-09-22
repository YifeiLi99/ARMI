"""Strict contracts for owner-specific background reflection."""

from __future__ import annotations

# ruff: noqa: RUF001
from typing import Annotated, Literal, cast

from armi_kernel.contracts import NONBLANK_TEXT_PATTERN
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    TypeAdapter,
)

from ._dialogue_contract import ContextRef, DialogueSubjectPromptChange
from ._focus.api import FOCUS_COGNITIVE_INSTRUCTIONS, ConcernChange
from ._model_contract import SelfState
from ._strict_model_json import strict_model_value

OWNER_REFLECTION_CANDIDATE_VERSION = "armi.owner-reflection-candidate"

REFLECT_SELF_INSTRUCTIONS = """\
# 本轮自我反思任务与边界

你只负责 Self Owner 的专项反思。可报告无需变化，或基于冻结资料提交一个完整 SelfState 候选及其当前 expected_version。不得修改 Mind、Mood、Prompt、记忆、关系、活动或对外表达。只输出给定 JSON Schema。"""
REFLECT_FOCUS_INSTRUCTIONS = FOCUS_COGNITIVE_INSTRUCTIONS
REFLECT_PROMPT_INSTRUCTIONS = """\
# 本轮方法反思任务与边界

你只负责主体 Prompt Owner 的专项反思。可报告无需变化，或基于冻结资料提交 cognition_method、expression_method、reflection_method 三项完整候选及当前 expected_version。不得修改 Self、Mind、Mood、记忆、关系、活动或对外表达。只输出给定 JSON Schema。"""


class _StrictModel(BaseModel, frozen=True):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    @property
    def schema_kind(self) -> str:
        return OWNER_REFLECTION_CANDIDATE_VERSION


class OwnerReflectionCandidate(_StrictModel, frozen=True):
    kind: Literal["no_change", "update"]
    target: Literal["self", "focus", "prompt"]
    summary: Annotated[
        str,
        StringConstraints(min_length=1, max_length=512, pattern=NONBLANK_TEXT_PATTERN),
    ]
    basis_refs: tuple[ContextRef, ...] = Field(max_length=8)
    expected_version: int | None
    next_state: SelfState | DialogueSubjectPromptChange | None


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


class FocusReflectionUpdate(_ReflectionUpdate, frozen=True):
    concern_changes: tuple[ConcernChange, ...] = Field(min_length=1, max_length=4)
    target: Literal["focus"]
    next_state: None = None


class PromptReflectionUpdate(_ReflectionUpdate, frozen=True):
    target: Literal["prompt"]
    expected_version: int = Field(..., ge=0)
    next_state: DialogueSubjectPromptChange = Field(...)


ReflectionWire = Annotated[
    NoReflectionChange
    | Annotated[
        SelfReflectionUpdate | FocusReflectionUpdate | PromptReflectionUpdate,
        Field(discriminator="target"),
    ],
    Field(discriminator="kind"),
]
_ADAPTER: TypeAdapter[OwnerReflectionCandidate] = TypeAdapter(ReflectionWire)


class NoSelfChange(NoReflectionChange, frozen=True):
    target: Literal["self"]


class NoFocusChange(NoReflectionChange, frozen=True):
    target: Literal["focus"]


class NoPromptChange(NoReflectionChange, frozen=True):
    target: Literal["prompt"]


_TARGET_ADAPTERS: dict[str, TypeAdapter[OwnerReflectionCandidate]] = {
    "self": TypeAdapter(
        Annotated[NoSelfChange | SelfReflectionUpdate, Field(discriminator="kind")]
    ),
    "focus": TypeAdapter(
        Annotated[NoFocusChange | FocusReflectionUpdate, Field(discriminator="kind")]
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
    "REFLECT_FOCUS_INSTRUCTIONS",
    "REFLECT_PROMPT_INSTRUCTIONS",
    "REFLECT_SELF_INSTRUCTIONS",
    "OwnerReflectionCandidate",
    "owner_reflection_schema",
    "parse_owner_reflection",
)
