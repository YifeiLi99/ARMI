"""Compact model output contract for one autonomous Activity choice."""

from __future__ import annotations

import json
from typing import Annotated, Any, Literal, cast

from armi_kernel.application import ModelViolation
from armi_mind.api import ConcernChange, GroundedMindChange, MindAppraisal
from armi_mood.api import AppraisalEventSignalV3
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    TypeAdapter,
)

from ._activity_internal_work_contract import (
    InternalWorkAbandonDecision,
    InternalWorkCompleteDecision,
    InternalWorkNoResultDecision,
    InternalWorkProgressDecision,
)
from ._creator_cognitive_act_contract import RecordKind
from ._strict_model_json import strict_model_value
from ._text_contract import Text1024, Text2048, Text65536

AUTONOMOUS_ACTIVITY_CANDIDATE_VERSION = "armi.autonomous-activity-candidate"


class _StrictModel(BaseModel):
    mind_appraisals: tuple[MindAppraisal, ...] = Field(default=(), max_length=4)
    mind_change: GroundedMindChange | None = None
    concern_changes: tuple[ConcernChange, ...] = Field(default=(), max_length=4)
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)
    expression: Text65536 | None = None

    @property
    def schema_kind(self) -> str:
        return AUTONOMOUS_ACTIVITY_CANDIDATE_VERSION


class StartActivityDecision(_StrictModel):
    kind: Literal["start_activity"]
    goal: Text2048
    next_step: Text1024
    appraisal: AppraisalEventSignalV3 | None = None


class AutonomousTerminalDecision(_StrictModel):
    kind: Literal["no_activity", "defer", "need_information"]
    appraisal: AppraisalEventSignalV3 | None = None


class AutonomousVisualObservationDecision(_StrictModel):
    kind: Literal["visual_observation"]
    source_kind: Literal["camera", "screen"]
    appraisal: AppraisalEventSignalV3 | None = None


class AutonomousLifeQueryDecision(_StrictModel):
    kind: Literal["exact_life_query"]
    record_kind: RecordKind
    query: Text1024 | None = None
    appraisal: AppraisalEventSignalV3 | None = None


class AutonomousCodexDecision(_StrictModel):
    kind: Literal["codex_delegation"]
    objective: Text2048
    model_id: Literal["gpt-5.6-luna"] = "gpt-5.6-luna"
    reasoning_effort: Literal["medium"] = "medium"
    web_search: bool = False
    appraisal: AppraisalEventSignalV3 | None = None


class AutonomousWaitDecision(_StrictModel):
    kind: Literal["wait"]
    progress_summary: Text2048
    next_step: Text1024
    information_needed: Text2048
    resumption_cue: Text2048
    appraisal: AppraisalEventSignalV3 | None = None


class AutonomousProgressDecision(_StrictModel, InternalWorkProgressDecision):
    pass


class AutonomousCompleteDecision(_StrictModel, InternalWorkCompleteDecision):
    pass


class AutonomousAbandonDecision(_StrictModel, InternalWorkAbandonDecision):
    pass


class AutonomousNoResultDecision(_StrictModel, InternalWorkNoResultDecision):
    review_after_seconds: int = Field(ge=60, le=21_600)


AutonomousActivityCandidate = Annotated[
    StartActivityDecision
    | AutonomousTerminalDecision
    | AutonomousVisualObservationDecision
    | AutonomousLifeQueryDecision
    | AutonomousWaitDecision
    | AutonomousCodexDecision
    | AutonomousProgressDecision
    | AutonomousCompleteDecision
    | AutonomousAbandonDecision
    | AutonomousNoResultDecision,
    Field(discriminator="kind"),
]
_ADAPTER: TypeAdapter[AutonomousActivityCandidate] = TypeAdapter(
    AutonomousActivityCandidate
)


def autonomous_activity_candidate_schema() -> dict[str, Any]:
    return _ADAPTER.json_schema()


def autonomous_schema_for_context(compiled_context: bytes) -> dict[str, Any]:
    """Expose only enabled tools from the same frozen catalog shown to cognition."""
    try:
        compiled = json.loads(compiled_context)
        items = [item for layer in compiled["layers"] for item in layer["items"]]
        catalog = json.loads(
            next(
                item["content"]
                for item in items
                if item["item_kind"] == "capability_catalog"
            )
        )
        opportunity = json.loads(
            next(
                item["content"]
                for item in items
                if item["item_kind"] == "current_life_opportunity"
            )
        )
        enabled = {
            entry["capability_kind"]
            for entry in catalog["capabilities"]
            if entry["enabled"]
        }
    except KeyError, TypeError, ValueError, StopIteration:
        raise ModelViolation("MODEL-AUTONOMY-CONTEXT") from None
    schema = autonomous_activity_candidate_schema()
    definitions = cast(dict[str, Any], schema["$defs"])
    blocked: set[str] = set()
    if not any(item["item_kind"] == "current_activity" for item in items):
        blocked.update(
            {
                "AutonomousWaitDecision",
                "AutonomousProgressDecision",
                "AutonomousCompleteDecision",
                "AutonomousAbandonDecision",
                "AutonomousNoResultDecision",
            }
        )
    if "codex.delegated-work" not in enabled:
        blocked.add("AutonomousCodexDecision")
    if "life.query" not in enabled:
        blocked.add("AutonomousLifeQueryDecision")
    sources = [
        source for source in ("camera", "screen") if f"vision.{source}" in enabled
    ]
    if not sources:
        blocked.add("AutonomousVisualObservationDecision")
    else:
        definitions["AutonomousVisualObservationDecision"]["properties"][
            "source_kind"
        ] = {"type": "string", "enum": sources}
    for definition in definitions.values():
        properties = definition.get("properties", {})
        if "expression" in properties and (
            not opportunity["autonomy"]["outlet_bound"]
            or opportunity["autonomy"]["outlet_state"] != "ready"
        ):
            properties["expression"] = {"type": "null", "default": None}
    schema["oneOf"] = [
        branch
        for branch in schema["oneOf"]
        if branch["$ref"].rsplit("/", 1)[1] not in blocked
    ]
    schema["discriminator"]["mapping"] = {
        kind: ref
        for kind, ref in schema["discriminator"]["mapping"].items()
        if ref.rsplit("/", 1)[1] not in blocked
    }
    for name in blocked:
        del definitions[name]
    return schema


def parse_autonomous_activity_candidate(value: object) -> AutonomousActivityCandidate:
    return _ADAPTER.validate_python(strict_model_value(value), strict=True)


__all__ = (
    "AUTONOMOUS_ACTIVITY_CANDIDATE_VERSION",
    "AutonomousAbandonDecision",
    "AutonomousActivityCandidate",
    "AutonomousCodexDecision",
    "AutonomousCompleteDecision",
    "AutonomousLifeQueryDecision",
    "AutonomousNoResultDecision",
    "AutonomousProgressDecision",
    "AutonomousTerminalDecision",
    "AutonomousVisualObservationDecision",
    "AutonomousWaitDecision",
    "StartActivityDecision",
    "autonomous_activity_candidate_schema",
    "autonomous_schema_for_context",
    "parse_autonomous_activity_candidate",
)
