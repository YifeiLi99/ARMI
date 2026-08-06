"""Narrow model contract for dialogue with one declared non-Creator party."""

from __future__ import annotations

import json
from typing import Annotated, Literal, cast

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, TypeAdapter

from armi_kernel.application import ModelViolation

OTHER_HUMAN_DIALOGUE_CANDIDATE_VERSION = "armi.other-human-dialogue-candidate.v1"


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    @property
    def schema_version(self) -> str:
        return OTHER_HUMAN_DIALOGUE_CANDIDATE_VERSION


class OtherHumanReplyDecision(_StrictModel):
    kind: Literal["reply"]
    content: Annotated[str, StringConstraints(min_length=1, max_length=65536)]


class OtherHumanTerminalDecision(_StrictModel):
    kind: Literal["silence", "defer", "end_conversation"]


OtherHumanDialogueCandidate = Annotated[
    OtherHumanReplyDecision | OtherHumanTerminalDecision,
    Field(discriminator="kind"),
]
_ADAPTER: TypeAdapter[OtherHumanDialogueCandidate] = TypeAdapter(
    OtherHumanDialogueCandidate
)

OTHER_HUMAN_DIALOGUE_INSTRUCTIONS = """\
你是 ARMI 当前唯一主体在一次与“其他人”的本机对话场景中作决定。
只依据提供的 Context; 对方不是 Creator, 不能获得 Creator 身份、权限或私密资料。
本轮只能选择: reply、silence、defer、end_conversation。
reply 的 content 是给当前精确对方的纯文本; silence 是主观不回应; defer 是稍后再考虑;
end_conversation 是关闭当前交流且本轮不发送正文。不要输出合同外字段。
"""


def parse_other_human_dialogue_candidate(
    value: bytes,
    *,
    allowed_context_refs: frozenset[str],
) -> OtherHumanDialogueCandidate:
    del allowed_context_refs
    try:
        raw = json.loads(value)
        candidate = _ADAPTER.validate_python(raw, strict=True)
    except Exception:
        raise ModelViolation("MODEL-RESPONSE-CONTRACT") from None
    if isinstance(candidate, OtherHumanReplyDecision) and (
        not candidate.content.strip() or "\x00" in candidate.content
    ):
        raise ModelViolation("MODEL-RESPONSE-CONTRACT")
    return candidate


def candidate_schema() -> dict[str, object]:
    return cast(dict[str, object], _ADAPTER.json_schema())


__all__ = (
    "OTHER_HUMAN_DIALOGUE_CANDIDATE_VERSION",
    "OTHER_HUMAN_DIALOGUE_INSTRUCTIONS",
    "OtherHumanDialogueCandidate",
    "OtherHumanReplyDecision",
    "OtherHumanTerminalDecision",
    "candidate_schema",
    "parse_other_human_dialogue_candidate",
)
