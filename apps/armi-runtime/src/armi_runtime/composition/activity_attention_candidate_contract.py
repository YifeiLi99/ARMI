"""Strict compact model contract for one bounded Activity attention decision."""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    TypeAdapter,
    field_validator,
)

ACTIVITY_ATTENTION_CANDIDATE_VERSION = "armi.activity-attention-candidate.v1"


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    @property
    def schema_version(self) -> str:
        return ACTIVITY_ATTENTION_CANDIDATE_VERSION


class AttentionSimpleDecision(_StrictModel):
    kind: Literal["engage", "resume", "no_action", "defer", "need_information"]


class AttentionProgressDecision(_StrictModel):
    kind: Literal["progress"]
    progress_summary: str
    next_step: str

    @field_validator("progress_summary")
    @classmethod
    def _progress(cls, value: str) -> str:
        return _text(value, 2048)

    @field_validator("next_step")
    @classmethod
    def _next(cls, value: str) -> str:
        return _text(value, 1024)


class AttentionWaitDecision(_StrictModel):
    kind: Literal["wait"]
    progress_summary: str
    next_step: str
    waiting_summary: str
    resumption_cue: str
    condition_kind: Literal["time", "creator_input", "external_evidence"]
    delay_seconds: int | None = Field(default=None, ge=1, le=86400)

    @field_validator("progress_summary", "waiting_summary", "resumption_cue")
    @classmethod
    def _summary(cls, value: str) -> str:
        return _text(value, 2048)

    @field_validator("next_step")
    @classmethod
    def _next(cls, value: str) -> str:
        return _text(value, 1024)


class AttentionPauseDecision(_StrictModel):
    kind: Literal["pause"]
    progress_summary: str
    next_step: str
    resumption_cue: str
    review_after_seconds: int = Field(ge=1, le=86400)

    @field_validator("progress_summary", "resumption_cue")
    @classmethod
    def _summary(cls, value: str) -> str:
        return _text(value, 2048)

    @field_validator("next_step")
    @classmethod
    def _next(cls, value: str) -> str:
        return _text(value, 1024)


class AttentionTerminalDecision(_StrictModel):
    kind: Literal["complete", "abandon"]
    progress_summary: str
    terminal_reason: str

    @field_validator("progress_summary")
    @classmethod
    def _progress(cls, value: str) -> str:
        return _text(value, 2048)

    @field_validator("terminal_reason")
    @classmethod
    def _reason(cls, value: str) -> str:
        return _text(value, 1024)


ActivityAttentionCandidate = Annotated[
    AttentionSimpleDecision
    | AttentionProgressDecision
    | AttentionWaitDecision
    | AttentionPauseDecision
    | AttentionTerminalDecision,
    Field(discriminator="kind"),
]
_ADAPTER: TypeAdapter[ActivityAttentionCandidate] = TypeAdapter(
    ActivityAttentionCandidate
)


def _text(value: str, maximum: int) -> str:
    try:
        encoded = value.encode("utf-8", errors="strict")
    except UnicodeEncodeError as exc:
        raise ValueError("text must be strict UTF-8") from exc
    if not 1 <= len(encoded) <= maximum or b"\x00" in encoded or not value.strip():
        raise ValueError("text exceeds UTF-8 boundary")
    return value


def activity_attention_candidate_schema() -> dict[str, Any]:
    return _ADAPTER.json_schema()


def parse_activity_attention_candidate(value: object) -> ActivityAttentionCandidate:
    return _ADAPTER.validate_python(value, strict=True)


__all__ = (
    "ACTIVITY_ATTENTION_CANDIDATE_VERSION",
    "ActivityAttentionCandidate",
    "AttentionPauseDecision",
    "AttentionProgressDecision",
    "AttentionSimpleDecision",
    "AttentionTerminalDecision",
    "AttentionWaitDecision",
    "activity_attention_candidate_schema",
    "parse_activity_attention_candidate",
)
