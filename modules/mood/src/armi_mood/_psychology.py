"""Deterministic appraisal dynamics; research and parameters: docs/02-系统设计/05.

The appraisal structure is research inspired. Anchors, gains and time constants
are engineering parameters, not measured universal human coefficients.
"""

from __future__ import annotations

import math
from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class MoodRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)


class Affect(MoodRecord):
    valence: float = Field(ge=-1, le=1)
    arousal: float = Field(ge=-1, le=1)


class EmotionKind(StrEnum):
    JOY = "joy"
    SADNESS = "sadness"
    HOPE = "hope"
    FEAR = "fear"
    ANGER = "anger"
    GUILT = "guilt"
    PRIDE = "pride"
    SHAME = "shame"
    GRATITUDE = "gratitude"
    SURPRISE = "surprise"
    RELIEF = "relief"
    DISAPPOINTMENT = "disappointment"


class GoalAppraisal(MoodRecord):
    reference: str
    relevance: float | None = Field(ge=0, le=1)
    gain: float | None = Field(ge=0, le=1)
    loss: float | None = Field(ge=0, le=1)
    likelihood: float | None = Field(ge=0, le=1)
    phase: Literal["anticipated", "ongoing", "realized", "averted", "unknown"]
    not_applicable: tuple[str, ...] = ()


class Appraisal(MoodRecord):
    """Evidence-grounded evaluations, never an emotion or a state delta."""

    suddenness: float | None = Field(ge=0, le=1)
    familiarity: float | None = Field(ge=0, le=1)
    predictability: float | None = Field(ge=0, le=1)
    pleasantness: float | None = Field(ge=0, le=1)
    unpleasantness: float | None = Field(ge=0, le=1)
    relevance: float | None = Field(ge=0, le=1)
    gain: float | None = Field(ge=0, le=1)
    loss: float | None = Field(ge=0, le=1)
    likelihood: float | None = Field(ge=0, le=1)
    discrepancy: float | None = Field(ge=0, le=1)
    urgency: float | None = Field(ge=0, le=1)
    control: float | None = Field(ge=0, le=1)
    resources: float | None = Field(ge=0, le=1)
    adjustment: float | None = Field(ge=0, le=1)
    self_alignment: float | None = Field(ge=0, le=1)
    self_violation: float | None = Field(ge=0, le=1)
    social_alignment: float | None = Field(ge=0, le=1)
    social_violation: float | None = Field(ge=0, le=1)
    agency: Literal["self", "other", "shared", "circumstance", "unknown"]
    intent: Literal["deliberate", "accidental", "unknown", "not_applicable"]
    phase: Literal["anticipated", "ongoing", "realized", "averted", "unknown"]
    epistemic: Literal["confirmed", "reported", "imagined", "unknown"]
    self_scope: Literal["action", "global", "none", "unknown"]
    outcome_change: Literal["unchanged", "threat_averted", "benefit_lost", "unknown"]
    not_applicable: tuple[str, ...] = ()
    goals: tuple[GoalAppraisal, ...] = ()


class Emotion(MoodRecord):
    kind: EmotionKind
    intensity: float = Field(ge=0, le=1)
    basis: tuple[str, ...]


class Response(MoodRecord):
    affect: Affect
    emotions: tuple[Emotion, ...]
    unknown: tuple[str, ...]


class DynamicsParameters(MoodRecord):
    fast_half_life_seconds: float = Field(default=300, gt=0)
    slow_half_life_seconds: float = Field(default=3600, gt=0)
    fast_weight: float = Field(default=0.7, ge=0, le=1)


class AffectiveEpisode(MoodRecord):
    event_id: str
    situation_id: str
    observed_at: datetime
    summary: str
    appraisal: Appraisal
    response: Response


class MoodDynamics(MoodRecord):
    schema_kind: Literal["armi.mood"] = "armi.mood"
    as_of: datetime
    baseline: Affect
    slow_valence: float
    slow_arousal: float
    episodes: tuple[AffectiveEpisode, ...]
    parameters: DynamicsParameters

    @model_validator(mode="after")
    def validate_clock_and_identity(self) -> MoodDynamics:
        if self.as_of.tzinfo is None:
            raise ValueError("Mood timestamps must be timezone aware")
        identities = [episode.situation_id for episode in self.episodes]
        if len(identities) != len(set(identities)):
            raise ValueError("each situation has one current appraisal")
        if any(
            episode.observed_at.tzinfo is None or episode.observed_at > self.as_of
            for episode in self.episodes
        ):
            raise ValueError("invalid appraisal timestamp")
        return self


def initial_dynamics(at: datetime, parameters: DynamicsParameters) -> MoodDynamics:
    return MoodDynamics(
        as_of=at,
        baseline=Affect(valence=0, arousal=0),
        slow_valence=0,
        slow_arousal=0,
        episodes=(),
        parameters=parameters,
    )


def _known_max(*values: float | None) -> float:
    """Only supported contributions drive state; missing values stay in appraisal."""
    return max((value for value in values if value is not None), default=0.0)


def _supported_min(*values: float | None) -> float:
    known = tuple(value for value in values if value is not None)
    return min(known) if len(known) == len(values) and known else 0.0


def derive_response(value: Appraisal, previous: Appraisal | None = None) -> Response:
    if value.goals:
        # Keep goal phases separate: a realized loss and anticipated gain cannot
        # borrow each other's certainty or become a fabricated realized benefit.
        base = value.model_copy(
            update={"goals": (), "gain": None, "loss": None, "relevance": None}
        )
        responses = [("event", derive_response(base))]
        previous_goals = (
            {}
            if previous is None
            else {goal.reference: goal for goal in previous.goals}
        )
        for goal in value.goals:
            scoped = value.model_copy(
                update={
                    **goal.model_dump(exclude={"reference"}),
                    "goals": (),
                    "pleasantness": None,
                    "unpleasantness": None,
                    "suddenness": None,
                    "discrepancy": None,
                    "familiarity": None,
                    "predictability": None,
                    "urgency": None,
                }
            )
            old = previous_goals.get(goal.reference)
            prior = (
                None
                if old is None or previous is None
                else previous.model_copy(
                    update={**old.model_dump(exclude={"reference"}), "goals": ()}
                )
            )
            responses.append((goal.reference, derive_response(scoped, prior)))
        return Response(
            affect=Affect(
                valence=max(
                    -1.0,
                    min(1.0, sum(response.affect.valence for _, response in responses)),
                ),
                arousal=max(
                    0.0, *(response.affect.arousal for _, response in responses)
                )
                + min(0.0, *(response.affect.arousal for _, response in responses)),
            ),
            emotions=tuple(
                emotion.model_copy(
                    update={"basis": (f"goal:{reference}", *emotion.basis)}
                )
                for reference, response in responses
                for emotion in response.emotions
            ),
            unknown=tuple(
                name
                for name, answer in value.model_dump().items()
                if (answer is None or answer == "unknown")
                and name not in value.not_applicable
            )
            + tuple(
                f"goal:{goal.reference}.{name}"
                for goal in value.goals
                for name, answer in goal.model_dump().items()
                if (answer is None or answer == "unknown")
                and name not in goal.not_applicable
            ),
        )
    positive = max(_supported_min(value.relevance, value.gain), value.pleasantness or 0)
    negative = max(
        _supported_min(value.relevance, value.loss), value.unpleasantness or 0
    )
    novelty = _known_max(
        value.suddenness,
        value.discrepancy,
        _supported_min(
            None if value.familiarity is None else 1 - value.familiarity,
            None if value.predictability is None else 1 - value.predictability,
        ),
    )
    realized = value.phase == "realized" and value.epistemic == "confirmed"
    prospective = value.phase in {"anticipated", "ongoing"} or (
        value.phase == "realized" and value.epistemic in {"reported", "imagined"}
    )
    threat = _supported_min(negative, value.likelihood) if prospective else 0.0
    helplessness = (
        _supported_min(
            negative,
            1 - value.control,
            1 - value.adjustment,
            None if value.resources is None else 1 - value.resources,
        )
        if realized and value.control is not None and value.adjustment is not None
        else 0.0
    )
    relief = (
        _supported_min(previous.relevance, previous.loss, previous.likelihood)
        if previous is not None
        and value.epistemic == "confirmed"
        and value.phase == "averted"
        and value.outcome_change == "threat_averted"
        else 0.0
    )
    disappointment = (
        _supported_min(previous.relevance, previous.gain, previous.likelihood)
        if previous is not None
        and value.epistemic == "confirmed"
        and value.outcome_change == "benefit_lost"
        else 0.0
    )
    components: list[Emotion] = []

    def add(kind: EmotionKind, strength: float, *basis: str) -> None:
        if strength > 0:
            components.append(Emotion(kind=kind, intensity=strength, basis=basis))

    if realized:
        add(EmotionKind.JOY, positive, "gain", "pleasantness", "phase")
        add(EmotionKind.SADNESS, negative, "loss", "unpleasantness", "phase")
    if prospective:
        add(
            EmotionKind.HOPE,
            _supported_min(positive, value.likelihood),
            "gain",
            "likelihood",
            "phase",
        )
        add(EmotionKind.FEAR, threat, "loss", "likelihood", "phase")
    if value.agency == "other" and value.intent == "deliberate":
        add(
            EmotionKind.ANGER,
            _supported_min(negative, value.social_violation),
            "agency",
            "intent",
            "loss",
            "social_violation",
        )
        if realized:
            add(
                EmotionKind.GRATITUDE,
                _supported_min(positive, value.social_alignment),
                "agency",
                "gain",
                "social_alignment",
            )
    if value.agency in {"self", "shared"} and realized:
        add(
            EmotionKind.PRIDE,
            _supported_min(value.relevance, value.gain, value.self_alignment),
            "agency",
            "gain",
            "self_alignment",
        )
        if value.self_scope == "action":
            add(
                EmotionKind.GUILT,
                _supported_min(value.relevance, value.self_violation),
                "agency",
                "self_scope",
                "self_violation",
            )
        elif value.self_scope == "global":
            add(
                EmotionKind.SHAME,
                _supported_min(value.relevance, value.self_violation),
                "agency",
                "self_scope",
                "self_violation",
            )
    add(EmotionKind.SURPRISE, novelty, "suddenness", "discrepancy")
    add(EmotionKind.RELIEF, relief, "previous.loss", "phase", "outcome_change")
    add(EmotionKind.DISAPPOINTMENT, disappointment, "previous.gain", "outcome_change")
    return Response(
        affect=Affect(
            valence=max(-1.0, min(1.0, positive - negative + relief - disappointment)),
            arousal=max(
                -1.0,
                min(
                    1.0,
                    max(novelty, value.urgency or 0, threat)
                    - max(helplessness, relief),
                ),
            ),
        ),
        emotions=tuple(components),
        unknown=tuple(
            name
            for name, answer in value.model_dump().items()
            if (answer is None or answer == "unknown")
            and name not in value.not_applicable
        ),
    )


def _fast(state: MoodDynamics, at: datetime) -> tuple[float, float]:
    rate = math.log(2) / state.parameters.fast_half_life_seconds

    def axis_value(axis: str) -> float:
        return sum(
            getattr(episode.response.affect, axis)
            * math.exp(-rate * (at - episode.observed_at).total_seconds())
            for episode in state.episodes
        )

    return axis_value("valence"), axis_value("arousal")


def advance(state: MoodDynamics, at: datetime) -> MoodDynamics:
    """Analytic solution of dF=-aF dt; dM=(-bM+aF) dt.

    Queries only project this solution: their frequency cannot inject stimuli.
    """
    elapsed = (at - state.as_of).total_seconds()
    if elapsed < 0:
        raise ValueError("Mood time cannot move backwards")
    a = math.log(2) / state.parameters.fast_half_life_seconds
    b = math.log(2) / state.parameters.slow_half_life_seconds
    es = math.exp(-b * elapsed)
    if a == b:
        transfer = a * elapsed * es
    elif a > b:
        transfer = a * es * -math.expm1(-(a - b) * elapsed) / (a - b)
    else:
        transfer = a * math.exp(-a * elapsed) * math.expm1((a - b) * elapsed) / (a - b)
    fv, fa = _fast(state, state.as_of)
    return state.model_copy(
        update={
            "as_of": at,
            "slow_valence": state.slow_valence * es + fv * transfer,
            "slow_arousal": state.slow_arousal * es + fa * transfer,
        }
    )


def current_affect(state: MoodDynamics, at: datetime) -> Affect:
    projected = advance(state, at)
    fv, fa = _fast(projected, at)
    weight = state.parameters.fast_weight
    return Affect(
        valence=math.tanh(
            state.baseline.valence + weight * fv + (1 - weight) * projected.slow_valence
        ),
        arousal=math.tanh(
            state.baseline.arousal + weight * fa + (1 - weight) * projected.slow_arousal
        ),
    )


def apply_appraisal(
    state: MoodDynamics,
    *,
    event_id: str,
    situation_id: str,
    appraisal: Appraisal,
    at: datetime,
    summary: str = "",
) -> MoodDynamics:
    if any(
        episode.event_id == event_id and episode.situation_id == situation_id
        for episode in state.episodes
    ):
        return state
    projected = advance(state, at)
    previous = next(
        (
            episode
            for episode in projected.episodes
            if episode.situation_id == situation_id
        ),
        None,
    )
    # Same unchanged interpretation must not recharge a fading emotional episode.
    if previous is not None and previous.appraisal == appraisal:
        return projected
    episode = AffectiveEpisode(
        event_id=event_id,
        situation_id=situation_id,
        observed_at=at,
        summary=summary,
        appraisal=appraisal,
        response=derive_response(
            appraisal, None if previous is None else previous.appraisal
        ),
    )
    return projected.model_copy(
        update={
            "episodes": (
                *(
                    item
                    for item in projected.episodes
                    if item.situation_id != situation_id
                ),
                episode,
            ),
        }
    )
