"""Shared activity payloads embedded in the current autonomous contract."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from ._creator_appraisal_contract import AppraisalEventSignalV2
from ._dialogue_contract import ContextRef
from ._text_contract import Metadata, Text256, Text1024, Text2048, Text65536


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


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
    appraisal: AppraisalEventSignalV2 | None = None


__all__ = (
    "InternalWorkAbandonDecision",
    "InternalWorkCompleteDecision",
    "InternalWorkMaterialChange",
    "InternalWorkMaterialCreate",
    "InternalWorkMaterialUpdate",
    "InternalWorkNoResultDecision",
    "InternalWorkProgressDecision",
)
