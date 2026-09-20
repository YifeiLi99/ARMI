"""A scheduling decision, with no subject changes or outward expression."""

from __future__ import annotations

# ruff: noqa: RUF001 -- Chinese model instructions use Chinese punctuation.
from typing import Any

from armi_kernel.application import ModelViolation
from pydantic import BaseModel, ConfigDict, ValidationError

AUTONOMY_CHECK_VERSION = "armi.autonomy-check-candidate.v1"

AUTONOMY_CHECK_INSTRUCTIONS = """根据当前处境，判断现在是否值得进入完整自主思考。
兴趣、愿望、关切、可推进的活动都可以成为理由，不要求一定有外部任务。
刚答完的问题或招呼不需要再次表达；单纯经过一分钟也不是行动理由。
等待中的工具未返回时，不重复启动同一任务，但可以考虑其他事情。
摘要可能省略内容，未展示不等于不存在；需要进一步了解时可以进入完整思考。
只输出 {"engage":true} 或 {"engage":false}。true 仅表示值得进一步思考，
不代表已经执行、必须说话或改变状态。不要输出理由、回复或行动参数。"""


class AutonomyCheckCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)
    engage: bool


def autonomy_check_schema() -> dict[str, Any]:
    return AutonomyCheckCandidate.model_json_schema()


def parse_autonomy_check(value: object) -> AutonomyCheckCandidate:
    try:
        return AutonomyCheckCandidate.model_validate(value, strict=True)
    except ValidationError as error:
        raise ModelViolation("MODEL-RESPONSE-SCHEMA") from error
