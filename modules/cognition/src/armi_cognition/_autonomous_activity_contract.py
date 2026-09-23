"""Compact model output contract for one autonomous Activity choice."""

# ruff: noqa: RUF001 -- Chinese directions for the cognition provider.

from __future__ import annotations

import json
from typing import Annotated, Any, Literal, cast

from armi_kernel.application import AutonomyCategory, ModelViolation
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
from ._focus.api import (
    ConcernChange,
)
from ._prompt_instructions import AUTONOMOUS_ACTIVITY_INSTRUCTIONS
from ._strict_model_json import strict_model_value
from ._text_contract import Text1024, Text2048, Text65536

AUTONOMOUS_ACTIVITY_CANDIDATE_VERSION = "armi.autonomous-activity-candidate"

_CATEGORY_TASKS = {
    AutonomyCategory.CONTINUE_ACTIVITY: "本轮方向是继续活动。围绕已有正式活动选择当前可推进、核验或调整的一步，不重复启动等待中的任务。",
    AutonomyCategory.EXPLORE: "本轮方向是探索与思考。围绕已有兴趣、疑问或关注进行有界的理解、构思或研究，再决定具体下一步。",
    AutonomyCategory.COMMUNICATE: "本轮方向是主动交流。先确定有意义的分享、问题或表达及现有合法接收目标，再形成 expression；不为联系而编造话题。",
    AutonomyCategory.REFLECT: "本轮方向是回顾与整理。基于可见经历和认识梳理关注、形成反思，必要时通过已有生活查询补充依据；不直接触发睡眠维护或越过记忆写入条件。",
}


def autonomous_instructions_for_context(compiled_context: bytes) -> str:
    try:
        document = json.loads(compiled_context)
        opportunity = next(
            item
            for layer in document["layers"]
            for item in layer["items"]
            if item["item_kind"] == "current_life_opportunity"
        )
        raw = json.loads(opportunity["content"])["autonomy"]["category"]
        # Non-plan autonomous opportunities have no preceding Jev classification.
        if raw is None:
            return AUTONOMOUS_ACTIVITY_INSTRUCTIONS
        category = AutonomyCategory(raw)
        task = _CATEGORY_TASKS[category]
    except ValueError, KeyError, TypeError, StopIteration:
        raise ModelViolation("MODEL-AUTONOMY-CATEGORY") from None
    return (
        AUTONOMOUS_ACTIVITY_INSTRUCTIONS
        + "\n\n# Jev 前置分类\n\n"
        + task
        + (
            "\n沿此方向细化具体内容，而不是重新自由选择另一大类。分类不构成行动许可或事实；"
            "若当前依据或条件不足，可明确不行动、延期或需要信息，不强行执行或悄悄换任务。"
        )
    )


class _StrictModel(BaseModel):
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


class AutonomousTerminalDecision(_StrictModel):
    kind: Literal["no_activity", "defer", "need_information"]


class AutonomousVisualObservationDecision(_StrictModel):
    kind: Literal["visual_observation"]
    source_kind: Literal["camera", "screen"]


class AutonomousLifeQueryDecision(_StrictModel):
    kind: Literal["exact_life_query"]
    record_kind: RecordKind
    query: Text1024 | None = None


class AutonomousCodexDecision(_StrictModel):
    kind: Literal["codex_delegation"]
    objective: Text2048
    model_id: Literal["gpt-5.6-luna"] = "gpt-5.6-luna"
    reasoning_effort: Literal["medium"] = "medium"
    web_search: bool = False


class AutonomousWaitDecision(_StrictModel):
    kind: Literal["wait"]
    progress_summary: Text2048
    next_step: Text1024
    information_needed: Text2048
    resumption_cue: Text2048


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
