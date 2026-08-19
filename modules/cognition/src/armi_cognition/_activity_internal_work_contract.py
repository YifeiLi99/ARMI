"""Strict compact model contract for one bounded internal Activity work step."""

from __future__ import annotations

import re
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, field_validator

from ._creator_branch_contract import AppraisalEventSignalV2
from ._strict_model_json import strict_model_value

ACTIVITY_INTERNAL_WORK_CANDIDATE_VERSION = "armi.activity-internal-work-candidate.v3"

_METADATA_KEY = re.compile(r"^[a-z][a-z0-9._-]{0,63}$", re.ASCII)
_CONTEXT_REF = re.compile(r"^ctx:[1-9][0-9]{0,2}$", re.ASCII)


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    @property
    def schema_version(self) -> str:
        return ACTIVITY_INTERNAL_WORK_CANDIDATE_VERSION


class InternalWorkMaterialCreate(_StrictModel):
    action: Literal["create"]
    material_kind: Literal["diary", "work", "collection", "draft"]
    title: str
    body: str
    metadata: dict[str, str] = Field(default_factory=dict, max_length=32)
    material_status: Literal["active", "archived"] = "active"

    @field_validator("title")
    @classmethod
    def _title(cls, value: str) -> str:
        return _text(value, 256)

    @field_validator("body")
    @classmethod
    def _body(cls, value: str) -> str:
        return _text(value, 65_536)

    @field_validator("metadata")
    @classmethod
    def _metadata(cls, value: dict[str, str]) -> dict[str, str]:
        return _valid_metadata(value)


class InternalWorkMaterialUpdate(_StrictModel):
    action: Literal["update"]
    material_ref: str
    title: str
    body: str
    metadata: dict[str, str] = Field(default_factory=dict, max_length=32)
    material_status: Literal["active", "archived"] = "active"

    @field_validator("material_ref")
    @classmethod
    def _ref(cls, value: str) -> str:
        if _CONTEXT_REF.fullmatch(value) is None:
            raise ValueError("material_ref must reference frozen Context")
        return value

    @field_validator("title")
    @classmethod
    def _title(cls, value: str) -> str:
        return _text(value, 256)

    @field_validator("body")
    @classmethod
    def _body(cls, value: str) -> str:
        return _text(value, 65_536)

    @field_validator("metadata")
    @classmethod
    def _metadata(cls, value: dict[str, str]) -> dict[str, str]:
        return _valid_metadata(value)


InternalWorkMaterialChange = Annotated[
    InternalWorkMaterialCreate | InternalWorkMaterialUpdate,
    Field(discriminator="action"),
]


class InternalWorkProgressDecision(_StrictModel):
    kind: Literal["progress"]
    progress_summary: str
    next_step: str
    material_change: InternalWorkMaterialChange | None = None
    appraisal: AppraisalEventSignalV2 | None = None

    @field_validator("progress_summary")
    @classmethod
    def _progress(cls, value: str) -> str:
        return _text(value, 2048)

    @field_validator("next_step")
    @classmethod
    def _next(cls, value: str) -> str:
        return _text(value, 1024)


class InternalWorkCompleteDecision(_StrictModel):
    kind: Literal["complete"]
    progress_summary: str
    terminal_reason: str
    material_change: InternalWorkMaterialChange | None = None
    appraisal: AppraisalEventSignalV2 | None = None

    @field_validator("progress_summary")
    @classmethod
    def _progress(cls, value: str) -> str:
        return _text(value, 2048)

    @field_validator("terminal_reason")
    @classmethod
    def _reason(cls, value: str) -> str:
        return _text(value, 1024)


class InternalWorkNeedInformationDecision(_StrictModel):
    kind: Literal["need_information"]
    progress_summary: str
    next_step: str
    information_needed: str
    resumption_cue: str
    appraisal: AppraisalEventSignalV2 | None = None

    @field_validator("progress_summary", "information_needed", "resumption_cue")
    @classmethod
    def _summary(cls, value: str) -> str:
        return _text(value, 2048)

    @field_validator("next_step")
    @classmethod
    def _next(cls, value: str) -> str:
        return _text(value, 1024)


class InternalWorkAbandonDecision(_StrictModel):
    kind: Literal["abandon"]
    progress_summary: str
    terminal_reason: str
    appraisal: AppraisalEventSignalV2 | None = None

    @field_validator("progress_summary")
    @classmethod
    def _progress(cls, value: str) -> str:
        return _text(value, 2048)

    @field_validator("terminal_reason")
    @classmethod
    def _reason(cls, value: str) -> str:
        return _text(value, 1024)


class InternalWorkNoResultDecision(_StrictModel):
    kind: Literal["no_result"]
    reason: str
    next_step: str
    resumption_cue: str
    review_after_seconds: int = Field(ge=60, le=86_400)
    appraisal: AppraisalEventSignalV2 | None = None

    @field_validator("reason", "resumption_cue")
    @classmethod
    def _summary(cls, value: str) -> str:
        return _text(value, 2048)

    @field_validator("next_step")
    @classmethod
    def _next(cls, value: str) -> str:
        return _text(value, 1024)


ActivityInternalWorkCandidate = Annotated[
    InternalWorkProgressDecision
    | InternalWorkCompleteDecision
    | InternalWorkNeedInformationDecision
    | InternalWorkAbandonDecision
    | InternalWorkNoResultDecision,
    Field(discriminator="kind"),
]
_ADAPTER: TypeAdapter[ActivityInternalWorkCandidate] = TypeAdapter(
    ActivityInternalWorkCandidate
)


def _text(value: str, maximum: int) -> str:
    try:
        encoded = value.encode("utf-8", errors="strict")
    except UnicodeEncodeError as exc:
        raise ValueError("text must be strict UTF-8") from exc
    if not 1 <= len(encoded) <= maximum or b"\x00" in encoded or not value.strip():
        raise ValueError("text exceeds UTF-8 boundary")
    return value


def _valid_metadata(value: dict[str, str]) -> dict[str, str]:
    if any(
        _METADATA_KEY.fullmatch(key) is None or len(item) > 512 or "\x00" in item
        for key, item in value.items()
    ):
        raise ValueError("metadata is invalid")
    return value


def activity_internal_work_candidate_schema() -> dict[str, Any]:
    return _ADAPTER.json_schema()


def parse_activity_internal_work_candidate(
    value: object,
) -> ActivityInternalWorkCandidate:
    return _ADAPTER.validate_python(strict_model_value(value), strict=True)


__all__ = (
    "ACTIVITY_INTERNAL_WORK_CANDIDATE_VERSION",
    "ActivityInternalWorkCandidate",
    "InternalWorkAbandonDecision",
    "InternalWorkCompleteDecision",
    "InternalWorkMaterialChange",
    "InternalWorkMaterialCreate",
    "InternalWorkMaterialUpdate",
    "InternalWorkNeedInformationDecision",
    "InternalWorkNoResultDecision",
    "InternalWorkProgressDecision",
    "activity_internal_work_candidate_schema",
    "parse_activity_internal_work_candidate",
)
