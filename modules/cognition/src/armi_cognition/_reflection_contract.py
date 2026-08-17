"""Strict contracts for owner-specific background reflection."""

from __future__ import annotations

# ruff: noqa: RUF001
from typing import Annotated, Literal, cast

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    TypeAdapter,
    model_validator,
)

from ._dialogue_contract import ContextRef, DialogueSubjectPromptChange
from ._model_contract import MindState, SelfState
from ._strict_model_json import strict_model_value

OWNER_REFLECTION_CANDIDATE_VERSION = "armi.owner-reflection-candidate.v1"

REFLECT_SELF_INSTRUCTIONS = """\
你只负责 Self Owner 的专项反思。可报告无需变化，或基于冻结资料提交一个完整 SelfState 候选及其当前 expected_version。不得修改 Mind、Mood、Prompt、记忆、关系、活动或对外表达。只输出给定 JSON Schema。"""
REFLECT_MIND_INSTRUCTIONS = """\
你只负责 Mind Owner 的专项反思。可报告无需变化，或基于冻结资料提交一个完整 MindState 候选及其当前 expected_version。不得修改 Self、Mood、Prompt、记忆、关系、活动或对外表达。只输出给定 JSON Schema。"""
REFLECT_PROMPT_INSTRUCTIONS = """\
你只负责主体 Prompt Owner 的专项反思。可报告无需变化，或基于冻结资料提交 cognition_method、expression_method、reflection_method 三项完整候选及当前 expected_version。不得修改 Self、Mind、Mood、记忆、关系、活动或对外表达。只输出给定 JSON Schema。"""


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    @property
    def schema_version(self) -> str:
        return OWNER_REFLECTION_CANDIDATE_VERSION


class OwnerReflectionCandidate(_StrictModel):
    kind: Literal["no_change", "update"]
    target: Literal["self", "mind", "prompt"]
    summary: Annotated[str, StringConstraints(min_length=1, max_length=512)]
    basis_refs: tuple[ContextRef, ...] = Field(default=(), max_length=8)
    expected_version: int | None = Field(default=None, ge=0)
    next_state: SelfState | MindState | DialogueSubjectPromptChange | None = None

    @model_validator(mode="after")
    def validate_shape(self) -> OwnerReflectionCandidate:
        update = self.kind == "update"
        if update != (self.expected_version is not None):
            raise ValueError("reflection expected version shape is invalid")
        if update != (self.next_state is not None) or update != bool(self.basis_refs):
            raise ValueError("reflection update shape is invalid")
        if not update:
            return self
        expected_type = {
            "self": SelfState,
            "mind": MindState,
            "prompt": DialogueSubjectPromptChange,
        }[self.target]
        if not isinstance(self.next_state, expected_type):
            raise ValueError("reflection target and next state do not match")
        if self.target in {"self", "mind"} and self.expected_version == 0:
            raise ValueError("component reflection version must be positive")
        return self


_ADAPTER = TypeAdapter(OwnerReflectionCandidate)


def owner_reflection_schema() -> dict[str, object]:
    return cast(dict[str, object], _ADAPTER.json_schema())


def parse_owner_reflection(
    value: object,
    *,
    allowed_context_refs: frozenset[str],
) -> OwnerReflectionCandidate:
    candidate = _ADAPTER.validate_python(strict_model_value(value), strict=True)
    if not set(candidate.basis_refs).issubset(allowed_context_refs):
        raise ValueError("reflection references unavailable context")
    return candidate


__all__ = (
    "OWNER_REFLECTION_CANDIDATE_VERSION",
    "REFLECT_MIND_INSTRUCTIONS",
    "REFLECT_PROMPT_INSTRUCTIONS",
    "REFLECT_SELF_INSTRUCTIONS",
    "OwnerReflectionCandidate",
    "owner_reflection_schema",
    "parse_owner_reflection",
)
