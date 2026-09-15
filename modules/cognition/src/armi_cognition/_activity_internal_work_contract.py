"""Strict compact model contract for one bounded internal Activity work step."""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter

from ._creator_appraisal_contract import AppraisalEventSignalV2
from ._dialogue_contract import ContextRef
from ._strict_model_json import strict_model_value
from ._text_contract import Metadata, Text256, Text1024, Text2048, Text65536

ACTIVITY_INTERNAL_WORK_CANDIDATE_VERSION = "armi.activity-internal-work-candidate.v5"


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    @property
    def schema_version(self) -> str:
        return ACTIVITY_INTERNAL_WORK_CANDIDATE_VERSION


class InternalWorkMaterialCreate(_StrictModel):
    action: Literal["create"]
    material_kind: Literal["diary", "work", "collection", "draft"]
    title: Text256
    body: Text65536
    metadata: Metadata = Field(default_factory=dict, max_length=32)
    material_status: Literal["active", "archived"] = "active"


class InternalWorkMaterialUpdate(_StrictModel):
    action: Literal["update"]
    material_ref: ContextRef
    title: Text256
    body: Text65536
    metadata: Metadata = Field(default_factory=dict, max_length=32)
    material_status: Literal["active", "archived"] = "active"


InternalWorkMaterialChange = Annotated[
    InternalWorkMaterialCreate | InternalWorkMaterialUpdate,
    Field(discriminator="action"),
]


class InternalWorkProgressDecision(_StrictModel):
    kind: Literal["progress"]
    progress_summary: Text2048
    next_step: Text1024
    material_change: InternalWorkMaterialChange | None = None
    appraisal: AppraisalEventSignalV2 | None = None


class InternalWorkCompleteDecision(_StrictModel):
    kind: Literal["complete"]
    progress_summary: Text2048
    terminal_reason: Text1024
    material_change: InternalWorkMaterialChange | None = None
    appraisal: AppraisalEventSignalV2 | None = None


class InternalWorkNeedInformationDecision(_StrictModel):
    kind: Literal["need_information"]
    progress_summary: Text2048
    next_step: Text1024
    information_needed: Text2048
    resumption_cue: Text2048
    appraisal: AppraisalEventSignalV2 | None = None


class InternalWorkAbandonDecision(_StrictModel):
    kind: Literal["abandon"]
    progress_summary: Text2048
    terminal_reason: Text1024
    appraisal: AppraisalEventSignalV2 | None = None


class InternalWorkNoResultDecision(_StrictModel):
    kind: Literal["no_result"]
    reason: Text2048
    next_step: Text1024
    resumption_cue: Text2048
    review_after_seconds: int = Field(ge=60, le=86_400)
    appraisal: AppraisalEventSignalV2 | None = None


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
