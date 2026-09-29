"""Jev evaluates entry into cognition; only full cognition forms an action."""

import json
import math
from typing import Any

from armi_kernel.application import AutonomyCategory, ModelViolation, record_diagnostic


def autonomy_check_questions(available: list[str] | None = None) -> dict[str, Any]:
    criteria = {
        "rest": "Continue resting; no thought or action is currently wanted.",
        "reflect": "Think privately about oneself, an experience or an open question.",
        "continue": "Continue an existing actionable activity.",
        "explore": "Explore an interest or develop a new idea using available capabilities.",
        "connect": "Consider communicating with an available person.",
        "unknown": "Insufficient or conflicting state to choose a direction.",
    }
    return {
        "category": {
            "type": "choice",
            "instructions": "An internal opportunity to choose has arrived. Select the preferred direction now, not a concrete action. Reflection or exploration can begin without an existing motive. Rest is valid; do not force productivity or conversation. Do not reassess psychology. Unknown values are not zero.",
            "criteria": {
                key: value
                for key, value in criteria.items()
                if available is None or key in available or key == "unknown"
            },
        }
    }


def parse_autonomy_check(
    response: bytes, available: list[str] | None = None
) -> AutonomyCategory:
    try:
        raw = json.loads(response)
        answers = raw["answers"]
        if set(answers) != {"category"}:
            raise ValueError
        answer = answers["category"]
        if set(answer) != {"type", "choice", "confidence", "probabilities"}:
            raise ValueError
        probabilities = answer["probabilities"]
        if answer["type"] != "choice" or set(probabilities) != set(
            autonomy_check_questions(available)["category"]["criteria"]
        ):
            raise ValueError
        values = (*probabilities.values(), answer["confidence"])
        if any(
            type(p) not in (int, float) or not math.isfinite(p) or not 0 <= p <= 1
            for p in values
        ):
            raise ValueError
        if not math.isclose(
            sum(probabilities.values()), 1, abs_tol=0.005 * len(probabilities) + 1e-9
        ):
            raise ValueError
        choice = answer["choice"]
        if choice not in probabilities:
            raise ValueError
    except ValueError, TypeError, KeyError, AttributeError:
        raise ModelViolation("MODEL-JEV-CHECK-CONTRACT") from None
    record_diagnostic(
        "autonomy.check.evaluated",
        component="cognition",
        outcome="eligible"
        if choice not in {"rest", "unknown"}
        else "undetermined"
        if choice == "unknown"
        else "not_scheduled",
        reason="jev_" + choice,
        category=choice,
        confidence=answer["confidence"],
        probabilities=probabilities,
    )
    if choice == "unknown":
        raise ModelViolation("MODEL-JEV-CHECK-UNDETERMINED")
    return AutonomyCategory(choice)
