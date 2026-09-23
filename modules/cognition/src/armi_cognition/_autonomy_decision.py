"""Jev evaluates entry into cognition; only full cognition forms an action."""

import json
import math
from typing import Any

from armi_kernel.application import AutonomyCategory, ModelViolation, record_diagnostic


def autonomy_check_questions() -> dict[str, Any]:
    return {
        "category": {
            "type": "choice",
            "instructions": "Does this existing state warrant waking cognition now? Do not reassess psychology or choose an action. Waiting, elapsed time or a registered activity alone is not a reason. Unknown values are not zero.",
            "criteria": {
                "wake": "A current motive or need warrants consideration.",
                "wait": "Keep resting or waiting.",
                "unknown": "Insufficient or conflicting state.",
            },
        }
    }


def parse_autonomy_check(response: bytes) -> AutonomyCategory:
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
            autonomy_check_questions()["category"]["criteria"]
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
        if choice not in {"wait", "unknown"}
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
