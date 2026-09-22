"""One frozen Jev request with independently validated psychological results.

This boundary coordinates contracts, not state writes. Each state owner must
commit its own validated result; failure in one part does not invalidate the
other. Provider usage belongs to the single request, never to both parts.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol, cast

from armi_mind.api import (
    MindEvaluationTarget,
    MindEvidence,
    mind_event_questions,
    parse_mind_event_answers,
)
from armi_mood.api import (
    JEV_MODEL,
    EvaluatedAppraisal,
    MoodAssessment,
    appraisal_questions,
    parse_appraisal_response,
)


@dataclass(frozen=True, slots=True)
class EventAppraisalRequest:
    evidence_key: str
    event_id: str
    at: datetime
    situations: tuple[str, ...]
    goals: tuple[str, ...]
    mind_targets: tuple[MindEvaluationTarget, ...]

    def questions(self) -> dict[str, Any]:
        return {
            **appraisal_questions(self.situations, self.goals),
            **mind_event_questions(self.mind_targets),
        }


@dataclass(frozen=True, slots=True)
class EventAppraisalResult:
    mood: EvaluatedAppraisal | None
    mind: tuple[MindEvidence, ...] | None
    mood_failure: str | None
    mind_failure: str | None
    input_tokens: int
    output_tokens: int

    @property
    def ready_for_cognition(self) -> bool:
        return self.mood is not None and self.mind is not None


class EventAppraiserPort(Protocol):
    async def evaluate_event(
        self,
        *,
        assessment: MoodAssessment,
        context: dict[str, Any],
        targets: tuple[MindEvaluationTarget, ...],
    ) -> EventAppraisalResult: ...


def parse_event_appraisal(
    raw: dict[str, Any],
    *,
    request: EventAppraisalRequest,
) -> EventAppraisalResult:
    """Validate transport usage once and each owner's answer subset separately."""
    raw_answers, raw_usage = raw.get("answers"), raw.get("usage")
    if (
        raw.get("model") != JEV_MODEL
        or not isinstance(raw_answers, dict)
        or not isinstance(raw_usage, dict)
    ):
        raise ValueError("COGNITION-JEV-CONTRACT")
    answers, usage = cast(dict[str, Any], raw_answers), cast(dict[str, Any], raw_usage)
    if any(
        type(usage.get(key)) is not int or usage[key] < 0
        for key in ("input_tokens", "output_tokens")
    ):
        raise ValueError("COGNITION-JEV-USAGE")
    # Each owner rejects missing and extra keys in its own namespace, without
    # discarding the valid sibling. Never filter unknown answers out silently.
    if any(type(key) is not str for key in answers):
        raise ValueError("COGNITION-JEV-CONTRACT")
    mood = mind = None
    mood_failure = mind_failure = None
    try:
        mood = parse_appraisal_response(
            {
                **raw,
                "answers": {
                    key: value
                    for key, value in answers.items()
                    if not key.startswith("mind_")
                },
            },
            event_id=request.event_id,
            situations=request.situations,
            goals=request.goals,
        )
    except ValueError, TypeError, KeyError:
        mood_failure = "MOOD-JEV-CONTRACT"
    try:
        mind = parse_mind_event_answers(
            {key: value for key, value in answers.items() if key.startswith("mind_")},
            targets=request.mind_targets,
            evidence_key=request.evidence_key,
            at=request.at,
        )
    except ValueError, TypeError, KeyError:
        mind_failure = "MIND-JEV-CONTRACT"
    return EventAppraisalResult(
        mood,
        mind,
        mood_failure,
        mind_failure,
        usage["input_tokens"],
        usage["output_tokens"],
    )
