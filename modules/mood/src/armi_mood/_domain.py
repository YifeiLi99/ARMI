"""Mood invariants and deterministic affect dynamics."""

from __future__ import annotations

import json
import math
import re
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from typing import Any, cast
from uuid import UUID

import rfc8785
from armi_kernel.application import CandidateFactClass

from .api import (
    VAD,
    ActionTendency,
    ActiveAffectiveEpisode,
    AppraisalAdjustment,
    AppraisalAgency,
    AppraisalCausality,
    AppraisalCertainty,
    AppraisalCompatibility,
    AppraisalConcern,
    AppraisalConcernTarget,
    AppraisalCoping,
    AppraisalDemand,
    AppraisalDemandLevel,
    AppraisalDirection,
    AppraisalEvent,
    AppraisalEventPhase,
    AppraisalExpectedness,
    AppraisalIntentionality,
    AppraisalPowerBalance,
    AppraisalQuality,
    AppraisalResponseAccess,
    AppraisalSelfInvolvement,
    AppraisalSelfScope,
    AppraisalSignificance,
    AppraisalStandards,
    AppraisalTrajectory,
    AppraisalTransition,
    AppraisalUrgency,
    AppraisalVector,
    CandidateMoodDraft,
    EffectiveActionTendency,
    EffectiveEmotion,
    EmotionComponent,
    EmotionFamily,
    MoodCandidateKind,
    MoodState,
    MoodViolation,
    SemanticAppraisal,
    SemanticAppraisalEvent,
)

_REF = re.compile(r"^proposal:[1-9][0-9]{0,2}$", re.ASCII)
_GROUP = re.compile(r"^group:[1-9][0-9]{0,2}$", re.ASCII)
_DYNAMICS_VERSION = "recency-reappraisal.v1"
_DERIVATION_VERSION = "cpm-fuzzy.v2"
_HISTORICAL_DERIVATION_VERSION = "cpm-fuzzy.v1"
_BASE_WEIGHT = 30.0


@dataclass(frozen=True, slots=True)
class StoredEmotionComponent:
    component: EmotionComponent
    half_life_seconds: int


@dataclass(frozen=True, slots=True)
class StoredAffectiveEvent:
    occurred_at: datetime
    components: tuple[StoredEmotionComponent, ...]
    episode_id: UUID | None = None
    transition: AppraisalTransition = AppraisalTransition.NEW
    phase: AppraisalEventPhase = AppraisalEventPhase.REALIZED
    gist: str = ""


@dataclass(frozen=True, slots=True)
class DerivedAppraisal:
    target: VAD
    importance: int
    components: tuple[StoredEmotionComponent, ...]


@dataclass(frozen=True, slots=True)
class SemanticConcernFeature:
    target: AppraisalConcernTarget
    relevance: float | None
    poles: tuple[tuple[float, float], ...]


@dataclass(frozen=True, slots=True)
class SemanticFeatures:
    concerns: tuple[SemanticConcernFeature, ...]
    suddenness: float | None
    predictability: float | None
    certainty: float | None
    pleasantness_poles: tuple[tuple[float, float], ...]
    urgency: float | None
    effort: float | None
    agency: AppraisalAgency
    intentionality: float | None
    control: float | None
    power: float | None
    adjustment: float | None
    self_poles: tuple[tuple[float, float], ...]
    norm_poles: tuple[tuple[float, float], ...]
    ego: float | None
    self_scope: AppraisalSelfScope


def initial_state() -> MoodState:
    return MoodState(_DYNAMICS_VERSION, _DERIVATION_VERSION, VAD(0, 0, 0))


def state_to_wire(state: MoodState) -> dict[str, object]:
    return {
        "schema_version": "armi.mood.v3",
        "dynamics_version": state.dynamics_version,
        "derivation_version": state.derivation_version,
        "home_base": vad_to_wire(state.home_base),
    }


def state_to_bytes(state: MoodState) -> bytes:
    return rfc8785.dumps(cast(Any, state_to_wire(state)))


def parse_state(value: object) -> MoodState:
    if type(value) is not dict:
        raise MoodViolation("MOOD-STATE")
    raw = cast(dict[str, object], value)
    if (
        set(raw)
        != {"schema_version", "dynamics_version", "derivation_version", "home_base"}
        or raw["schema_version"] != "armi.mood.v3"
        or raw["dynamics_version"] != _DYNAMICS_VERSION
        or raw["derivation_version"]
        not in {_HISTORICAL_DERIVATION_VERSION, _DERIVATION_VERSION}
    ):
        raise MoodViolation("MOOD-STATE")
    return MoodState(
        _DYNAMICS_VERSION,
        cast(str, raw["derivation_version"]),
        parse_vad(raw["home_base"], step=None),
    )


def validate_state(value: dict[str, object]) -> None:
    parse_state(value)


def parse_state_bytes(value: bytes) -> MoodState:
    try:
        raw = cast(object, json.loads(value))
        if rfc8785.dumps(cast(Any, raw)) != value:
            raise ValueError
        return parse_state(raw)
    except UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError:
        raise MoodViolation("MOOD-STATE") from None


def vad_to_wire(value: VAD) -> dict[str, int]:
    return {
        "valence": value.valence,
        "arousal": value.arousal,
        "dominance": value.dominance,
    }


def parse_vad(value: object, *, step: int | None = 5) -> VAD:
    if type(value) is not dict:
        raise MoodViolation("MOOD-VAD")
    raw = cast(dict[str, object], value)
    if set(raw) != {"valence", "arousal", "dominance"}:
        raise MoodViolation("MOOD-VAD")
    coordinates = tuple(raw[key] for key in ("valence", "arousal", "dominance"))
    if any(type(item) is not int for item in coordinates):
        raise MoodViolation("MOOD-VAD")
    parsed = VAD(*cast(tuple[int, int, int], coordinates))
    if step is not None and any(cast(int, item) % step for item in coordinates):
        raise MoodViolation("MOOD-VAD")
    return parsed


def component_to_wire(
    value: EmotionComponent, *, half_life_seconds: int | None = None
) -> dict[str, object]:
    result: dict[str, object] = {
        "family": value.family.value,
        "nuance": value.nuance,
        "vad": vad_to_wire(value.vad),
        "intensity": value.intensity,
    }
    if half_life_seconds is not None:
        result["half_life_seconds"] = half_life_seconds
    return result


def parse_component(value: object) -> EmotionComponent:
    if type(value) is not dict:
        raise MoodViolation("MOOD-COMPONENT")
    raw = cast(dict[str, object], value)
    if set(raw) != {"family", "nuance", "vad", "intensity"}:
        raise MoodViolation("MOOD-COMPONENT")
    try:
        return EmotionComponent(
            EmotionFamily(cast(str, raw["family"])),
            cast(str, raw["nuance"]),
            parse_vad(raw["vad"]),
            cast(int, raw["intensity"]),
        )
    except (TypeError, ValueError):
        raise MoodViolation("MOOD-COMPONENT") from None


_APPRAISAL_UNSIGNED = (
    "suddenness",
    "predictability",
    "outcome_certainty",
    "self_relevance",
    "relationship_relevance",
    "social_order_relevance",
    "urgency",
    "effort",
    "intentionality",
    "control",
    "power",
    "adjustment",
    "ego_involvement",
)
_APPRAISAL_SIGNED = (
    "intrinsic_pleasantness",
    "goal_conduciveness",
    "self_compatibility",
    "norm_compatibility",
)


def appraisal_to_wire(value: AppraisalEvent) -> dict[str, object]:
    vector: dict[str, object] = {
        name: cast(int, getattr(value.appraisal, name))
        for name in (*_APPRAISAL_UNSIGNED, *_APPRAISAL_SIGNED)
    }
    vector.update(
        {
            "agency": value.appraisal.agency.value,
            "self_scope": value.appraisal.self_scope.value,
        }
    )
    return {
        "schema_version": "armi.mood-appraisal.v1",
        "transition": value.transition.value,
        "previous_episode_id": (
            None
            if value.previous_episode_id is None
            else str(value.previous_episode_id)
        ),
        "event_phase": value.phase.value,
        "gist": value.gist,
        "appraisal": vector,
    }


def parse_appraisal(value: object) -> AppraisalEvent:
    if type(value) is not dict:
        raise MoodViolation("MOOD-APPRAISAL")
    raw = cast(dict[str, object], value)
    expected = {
        "schema_version",
        "transition",
        "previous_episode_id",
        "event_phase",
        "gist",
        "appraisal",
    }
    vector_value = raw.get("appraisal")
    if (
        set(raw) != expected
        or raw.get("schema_version") != "armi.mood-appraisal.v1"
        or type(vector_value) is not dict
    ):
        raise MoodViolation("MOOD-APPRAISAL")
    vector = cast(dict[str, object], vector_value)
    if set(vector) != {
        *_APPRAISAL_UNSIGNED,
        *_APPRAISAL_SIGNED,
        "agency",
        "self_scope",
    }:
        raise MoodViolation("MOOD-APPRAISAL")
    previous = raw["previous_episode_id"]
    try:
        previous_id = None if previous is None else UUID(cast(str, previous))
        appraisal = AppraisalVector(
            **{name: cast(int, vector[name]) for name in _APPRAISAL_UNSIGNED},
            **{name: cast(int, vector[name]) for name in _APPRAISAL_SIGNED},
            agency=AppraisalAgency(cast(str, vector["agency"])),
            self_scope=AppraisalSelfScope(cast(str, vector["self_scope"])),
        )
        return AppraisalEvent(
            AppraisalTransition(cast(str, raw["transition"])),
            previous_id,
            AppraisalEventPhase(cast(str, raw["event_phase"])),
            cast(str, raw["gist"]),
            appraisal,
        )
    except (TypeError, ValueError):
        raise MoodViolation("MOOD-APPRAISAL") from None


def semantic_appraisal_to_wire(value: SemanticAppraisalEvent) -> dict[str, object]:
    appraisal = value.appraisal
    return {
        "schema_version": "armi.mood-appraisal.v2",
        "transition": value.transition.value,
        "previous_episode_id": (
            None if value.previous_episode_id is None else str(value.previous_episode_id)
        ),
        "event_phase": value.phase.value,
        "gist": value.gist,
        "change_from_previous": (
            None
            if value.change_from_previous is None
            else value.change_from_previous.value
        ),
        "appraisal": {
            "concerns": [
                {
                    "target": item.target.value,
                    "significance": item.significance.value,
                    "direction": item.direction.value,
                }
                for item in appraisal.concerns
            ],
            "expectedness": appraisal.expectedness.value,
            "outcome_certainty": appraisal.outcome_certainty.value,
            "intrinsic_quality": appraisal.intrinsic_quality.value,
            "self_involvement": appraisal.self_involvement.value,
            "demand": (
                None
                if appraisal.demand is None
                else {
                    "urgency": appraisal.demand.urgency.value,
                    "effort": appraisal.demand.effort.value,
                }
            ),
            "causality": (
                None
                if appraisal.causality is None
                else {
                    "agency": appraisal.causality.agency.value,
                    "intentionality": appraisal.causality.intentionality.value,
                }
            ),
            "coping": (
                None
                if appraisal.coping is None
                else {
                    "response_access": appraisal.coping.response_access.value,
                    "power_balance": appraisal.coping.power_balance.value,
                    "adjustment": appraisal.coping.adjustment.value,
                }
            ),
            "standards": (
                None
                if appraisal.standards is None
                else {
                    "self_compatibility": (
                        appraisal.standards.self_compatibility.value
                    ),
                    "norm_compatibility": (
                        appraisal.standards.norm_compatibility.value
                    ),
                    "self_scope": appraisal.standards.self_scope.value,
                }
            ),
        },
    }


def _optional_mapping(value: object, keys: set[str]) -> dict[str, object] | None:
    if value is None:
        return None
    if type(value) is not dict or set(cast(dict[str, object], value)) != keys:
        raise MoodViolation("MOOD-APPRAISAL")
    return cast(dict[str, object], value)


def parse_semantic_appraisal(value: object) -> SemanticAppraisalEvent:
    if type(value) is not dict:
        raise MoodViolation("MOOD-APPRAISAL")
    raw = cast(dict[str, object], value)
    appraisal_value = raw.get("appraisal")
    if (
        set(raw)
        != {
            "schema_version",
            "transition",
            "previous_episode_id",
            "event_phase",
            "gist",
            "change_from_previous",
            "appraisal",
        }
        or raw.get("schema_version") != "armi.mood-appraisal.v2"
        or type(appraisal_value) is not dict
    ):
        raise MoodViolation("MOOD-APPRAISAL")
    appraisal = cast(dict[str, object], appraisal_value)
    if set(appraisal) != {
        "concerns",
        "expectedness",
        "outcome_certainty",
        "intrinsic_quality",
        "self_involvement",
        "demand",
        "causality",
        "coping",
        "standards",
    }:
        raise MoodViolation("MOOD-APPRAISAL")
    concerns_value = appraisal["concerns"]
    if type(concerns_value) is not list:
        raise MoodViolation("MOOD-APPRAISAL")
    try:
        concerns = tuple(
            AppraisalConcern(
                AppraisalConcernTarget(cast(dict[str, object], item)["target"]),
                AppraisalSignificance(
                    cast(dict[str, object], item)["significance"]
                ),
                AppraisalDirection(cast(dict[str, object], item)["direction"]),
            )
            for item in cast(list[object], concerns_value)
            if type(item) is dict
            and set(cast(dict[str, object], item))
            == {"target", "significance", "direction"}
        )
        if len(concerns) != len(cast(list[object], concerns_value)):
            raise ValueError
        demand = _optional_mapping(appraisal["demand"], {"urgency", "effort"})
        causality = _optional_mapping(
            appraisal["causality"], {"agency", "intentionality"}
        )
        coping = _optional_mapping(
            appraisal["coping"],
            {"response_access", "power_balance", "adjustment"},
        )
        standards = _optional_mapping(
            appraisal["standards"],
            {"self_compatibility", "norm_compatibility", "self_scope"},
        )
        previous = raw["previous_episode_id"]
        trajectory = raw["change_from_previous"]
        return SemanticAppraisalEvent(
            AppraisalTransition(cast(str, raw["transition"])),
            None if previous is None else UUID(cast(str, previous)),
            AppraisalEventPhase(cast(str, raw["event_phase"])),
            cast(str, raw["gist"]),
            SemanticAppraisal(
                concerns,
                AppraisalExpectedness(cast(str, appraisal["expectedness"])),
                AppraisalCertainty(cast(str, appraisal["outcome_certainty"])),
                AppraisalQuality(cast(str, appraisal["intrinsic_quality"])),
                AppraisalSelfInvolvement(
                    cast(str, appraisal["self_involvement"])
                ),
                None
                if demand is None
                else AppraisalDemand(
                    AppraisalUrgency(cast(str, demand["urgency"])),
                    AppraisalDemandLevel(cast(str, demand["effort"])),
                ),
                None
                if causality is None
                else AppraisalCausality(
                    AppraisalAgency(cast(str, causality["agency"])),
                    AppraisalIntentionality(
                        cast(str, causality["intentionality"])
                    ),
                ),
                None
                if coping is None
                else AppraisalCoping(
                    AppraisalResponseAccess(
                        cast(str, coping["response_access"])
                    ),
                    AppraisalPowerBalance(cast(str, coping["power_balance"])),
                    AppraisalAdjustment(cast(str, coping["adjustment"])),
                ),
                None
                if standards is None
                else AppraisalStandards(
                    AppraisalCompatibility(
                        cast(str, standards["self_compatibility"])
                    ),
                    AppraisalCompatibility(
                        cast(str, standards["norm_compatibility"])
                    ),
                    AppraisalSelfScope(cast(str, standards["self_scope"])),
                ),
            ),
            None if trajectory is None else AppraisalTrajectory(cast(str, trajectory)),
        )
    except (KeyError, TypeError, ValueError):
        raise MoodViolation("MOOD-APPRAISAL") from None


def parse_appraisal_any(value: object) -> AppraisalEvent | SemanticAppraisalEvent:
    if type(value) is not dict:
        raise MoodViolation("MOOD-APPRAISAL")
    raw = cast(dict[str, object], value)
    version = raw.get("schema_version")
    if version == "armi.mood-appraisal.v1":
        return parse_appraisal(raw)
    if version == "armi.mood-appraisal.v2":
        return parse_semantic_appraisal(raw)
    raise MoodViolation("MOOD-APPRAISAL")


def _round_to_five(value: float) -> int:
    return max(5, min(100, int((value + 2.5) // 5) * 5))


def _normalized(value: int) -> float:
    return value / 4.0


def _positive(value: float) -> float:
    return max(0.0, value)


def _negative(value: float) -> float:
    return max(0.0, -value)


def _mid(value: float) -> float:
    return max(0.0, 1.0 - abs(2.0 * value - 1.0))


def _phase(value: AppraisalEventPhase, *allowed: AppraisalEventPhase) -> float:
    return 1.0 if value in allowed else 0.0


def _agency(value: AppraisalAgency, *allowed: AppraisalAgency) -> float:
    return 1.0 if value in allowed else 0.0


def _scope(value: AppraisalSelfScope, expected: AppraisalSelfScope) -> float:
    return 1.0 if value is expected else 0.0


def derive_appraisal(
    event: AppraisalEvent,
    *,
    previous: AppraisalEvent | None = None,
) -> DerivedAppraisal:
    value = event.appraisal
    sudden = _normalized(value.suddenness)
    predictability = _normalized(value.predictability)
    certainty = _normalized(value.outcome_certainty)
    self_relevance = _normalized(value.self_relevance)
    relationship_relevance = _normalized(value.relationship_relevance)
    social_relevance = _normalized(value.social_order_relevance)
    relevance = max(self_relevance, relationship_relevance, social_relevance)
    urgency = _normalized(value.urgency)
    effort = _normalized(value.effort)
    intentionality = _normalized(value.intentionality)
    control = _normalized(value.control)
    power = _normalized(value.power)
    adjustment = _normalized(value.adjustment)
    ego = _normalized(value.ego_involvement)
    pleasantness = _normalized(value.intrinsic_pleasantness)
    goal = _normalized(value.goal_conduciveness)
    self_compatibility = _normalized(value.self_compatibility)
    norm_compatibility = _normalized(value.norm_compatibility)
    novelty = max(sudden, 1.0 - predictability)
    activation = (
        0.20 * sudden
        + 0.15 * (1.0 - predictability)
        + 0.20 * urgency
        + 0.15 * (1.0 - certainty)
        + 0.15 * effort
        + 0.15 * relevance
    )
    target = VAD(
        max(
            -100,
            min(
                100,
                round(
                    100
                    * (
                        0.55 * goal
                        + 0.25 * pleasantness
                        + 0.10 * self_compatibility
                        + 0.10 * norm_compatibility
                    )
                ),
            ),
        ),
        max(-100, min(100, round(200 * activation - 100))),
        max(
            -100,
            min(
                100,
                round(
                    100
                    * (
                        0.45 * (2 * control - 1)
                        + 0.35 * (2 * power - 1)
                        + 0.20 * (2 * adjustment - 1)
                    )
                ),
            ),
        ),
    )
    impact = max(
        abs(goal),
        abs(pleasantness),
        abs(self_compatibility),
        abs(norm_compatibility),
    )
    importance = _round_to_five(
        100 * (0.65 * relevance + 0.25 * impact + 0.10 * urgency)
    )
    realized = _phase(event.phase, AppraisalEventPhase.REALIZED)
    prospective = _phase(
        event.phase, AppraisalEventPhase.ANTICIPATED, AppraisalEventPhase.ONGOING
    )
    ongoing = _phase(event.phase, AppraisalEventPhase.ONGOING)
    self_agent = _agency(value.agency, AppraisalAgency.SELF)
    other_agent = _agency(value.agency, AppraisalAgency.OTHER)
    social_agent = _agency(
        value.agency, AppraisalAgency.OTHER, AppraisalAgency.SHARED
    )
    low_capacity = 1.0 - max(control, power, adjustment)
    signatures: dict[EmotionFamily, tuple[float, ...]] = {
        EmotionFamily.JOY: (relevance, _positive(goal), realized, certainty),
        EmotionFamily.CONTENTMENT: (
            relevance,
            _positive(goal),
            realized,
            certainty,
            1.0 - urgency,
            1.0 - novelty,
        ),
        EmotionFamily.INTEREST: (relevance, novelty, max(control, adjustment)),
        EmotionFamily.HOPE: (
            relevance,
            _positive(goal),
            prospective,
            _mid(certainty),
        ),
        EmotionFamily.AFFECTION: (
            relationship_relevance,
            max(_positive(goal), _positive(pleasantness)),
            social_agent,
        ),
        EmotionFamily.GRATITUDE: (
            relevance,
            _positive(goal),
            other_agent,
            intentionality,
            realized,
        ),
        EmotionFamily.PRIDE: (
            relevance,
            _positive(goal),
            self_agent,
            _positive(self_compatibility),
            ego,
        ),
        EmotionFamily.SURPRISE: (relevance, novelty),
        EmotionFamily.SADNESS: (
            relevance,
            _negative(goal),
            realized,
            certainty,
            low_capacity,
        ),
        EmotionFamily.FEAR: (
            relevance,
            _negative(goal),
            prospective,
            certainty,
            1.0 - power,
            urgency,
        ),
        EmotionFamily.ANXIETY: (
            relevance,
            _negative(goal),
            prospective,
            1.0 - certainty,
            1.0 - control,
            urgency,
        ),
        EmotionFamily.ANGER: (
            relevance,
            _negative(goal),
            other_agent,
            intentionality,
            max(control, power),
        ),
        EmotionFamily.FRUSTRATION: (
            relevance,
            _negative(goal),
            effort,
            max(ongoing, float(event.transition is AppraisalTransition.REINFORCE)),
            _mid(control),
        ),
        EmotionFamily.DISGUST: (
            relevance,
            _negative(pleasantness),
            max(_negative(norm_compatibility), 1.0 - adjustment),
        ),
        EmotionFamily.SHAME: (
            relevance,
            self_agent,
            _negative(self_compatibility),
            _scope(value.self_scope, AppraisalSelfScope.GLOBAL),
            ego,
            1.0 - adjustment,
        ),
        EmotionFamily.GUILT: (
            relevance,
            self_agent,
            _negative(self_compatibility),
            _scope(value.self_scope, AppraisalSelfScope.ACTION),
            adjustment,
        ),
        EmotionFamily.JEALOUSY: (
            relationship_relevance,
            _negative(goal),
            social_agent,
            prospective,
            ego,
        ),
        EmotionFamily.BOREDOM: (
            ongoing,
            1.0 - novelty,
            1.0 - urgency,
            1.0 - effort,
            1.0 - abs(goal),
        ),
        EmotionFamily.CONFUSION: (
            relevance,
            novelty,
            1.0 - certainty,
            1.0 - max(control, power),
        ),
    }
    if event.transition is AppraisalTransition.RESOLVE and previous is not None:
        old_goal = _normalized(previous.appraisal.goal_conduciveness)
        resolution = max(
            float(event.phase is AppraisalEventPhase.AVERTED), _positive(goal)
        )
        signatures[EmotionFamily.RELIEF] = (
            _negative(old_goal),
            resolution,
            relevance,
        )
    components: list[StoredEmotionComponent] = []
    salience = 0.55 * relevance + 0.25 * impact + 0.20 * activation
    open_episode = float(
        event.phase in {AppraisalEventPhase.ANTICIPATED, AppraisalEventPhase.ONGOING}
    )
    for family, terms in signatures.items():
        score = min(terms)
        if score < 0.5:
            continue
        intensity = _round_to_five(100 * salience * score)
        normalized_importance = (importance - 5) / 95
        normalized_intensity = (intensity - 5) / 95
        persistence = (
            0.55 * normalized_importance
            + 0.25 * normalized_intensity
            + 0.20 * open_episode
        )
        half_life = round(900 * (96**persistence))
        components.append(
            StoredEmotionComponent(
                EmotionComponent(family, event.gist, target, intensity), half_life
            )
        )
    components.sort(
        key=lambda item: (-item.component.intensity, item.component.family.value)
    )
    return DerivedAppraisal(target, importance, tuple(components[:3]))


_SIGNIFICANCE = {
    AppraisalSignificance.PERIPHERAL: 0.25,
    AppraisalSignificance.DIRECT: 0.65,
    AppraisalSignificance.CORE: 1.0,
    AppraisalSignificance.UNKNOWN: None,
}
_DIRECTION = {
    AppraisalDirection.MAJOR_SETBACK: ((-1.0, 1.0),),
    AppraisalDirection.SETBACK: ((-0.65, 1.0),),
    AppraisalDirection.UNCHANGED: ((0.0, 1.0),),
    AppraisalDirection.PROGRESS: ((0.65, 1.0),),
    AppraisalDirection.FULFILLED: ((1.0, 1.0),),
    AppraisalDirection.MIXED: ((-0.5, 0.5), (0.5, 0.5)),
    AppraisalDirection.UNKNOWN: (),
}
_EXPECTEDNESS = {
    AppraisalExpectedness.EXPECTED: (0.0, 1.0),
    AppraisalExpectedness.SOMEWHAT_UNEXPECTED: (0.4, 0.6),
    AppraisalExpectedness.EXPECTATION_BROKEN: (1.0, 0.0),
    AppraisalExpectedness.UNKNOWN: (None, None),
}
_CERTAINTY = {
    AppraisalCertainty.OPEN: 0.10,
    AppraisalCertainty.UNCERTAIN: 0.35,
    AppraisalCertainty.LIKELY: 0.70,
    AppraisalCertainty.SETTLED: 1.0,
    AppraisalCertainty.UNKNOWN: None,
}
_QUALITY = {
    AppraisalQuality.STRONGLY_AVERSIVE: ((-1.0, 1.0),),
    AppraisalQuality.UNPLEASANT: ((-0.65, 1.0),),
    AppraisalQuality.NEUTRAL: ((0.0, 1.0),),
    AppraisalQuality.PLEASANT: ((0.65, 1.0),),
    AppraisalQuality.STRONGLY_PLEASANT: ((1.0, 1.0),),
    AppraisalQuality.MIXED: ((-0.5, 0.5), (0.5, 0.5)),
    AppraisalQuality.UNKNOWN: (),
}
_URGENCY = {
    AppraisalUrgency.NONE: 0.0,
    AppraisalUrgency.CAN_WAIT: 0.25,
    AppraisalUrgency.SOON: 0.65,
    AppraisalUrgency.IMMEDIATE: 1.0,
    AppraisalUrgency.UNKNOWN: None,
}
_DEMAND = {
    AppraisalDemandLevel.NONE: 0.0,
    AppraisalDemandLevel.LIGHT: 0.25,
    AppraisalDemandLevel.SUBSTANTIAL: 0.65,
    AppraisalDemandLevel.EXTREME: 1.0,
    AppraisalDemandLevel.UNKNOWN: None,
}
_INTENTIONALITY = {
    AppraisalIntentionality.ACCIDENTAL: 0.0,
    AppraisalIntentionality.UNCLEAR: 0.5,
    AppraisalIntentionality.DELIBERATE: 1.0,
    AppraisalIntentionality.NOT_APPLICABLE: None,
    AppraisalIntentionality.UNKNOWN: None,
}
_RESPONSE_ACCESS = {
    AppraisalResponseAccess.NONE: 0.0,
    AppraisalResponseAccess.INDIRECT: 0.35,
    AppraisalResponseAccess.DIRECT: 0.70,
    AppraisalResponseAccess.RESOLVED: 1.0,
    AppraisalResponseAccess.UNKNOWN: None,
}
_POWER = {
    AppraisalPowerBalance.OVERMATCHED: 0.0,
    AppraisalPowerBalance.LIMITED: 0.35,
    AppraisalPowerBalance.BALANCED: 0.65,
    AppraisalPowerBalance.ADVANTAGED: 1.0,
    AppraisalPowerBalance.UNKNOWN: None,
}
_ADJUSTMENT = {
    AppraisalAdjustment.BLOCKED: 0.0,
    AppraisalAdjustment.DIFFICULT: 0.35,
    AppraisalAdjustment.MANAGEABLE: 0.70,
    AppraisalAdjustment.EASY: 1.0,
    AppraisalAdjustment.UNKNOWN: None,
}
_COMPATIBILITY = {
    AppraisalCompatibility.VIOLATION: ((-1.0, 1.0),),
    AppraisalCompatibility.TENSION: ((-0.5, 1.0),),
    AppraisalCompatibility.ALIGNED: ((0.65, 1.0),),
    AppraisalCompatibility.MIXED: ((-0.5, 0.5), (0.5, 0.5)),
    AppraisalCompatibility.NOT_APPLICABLE: (),
    AppraisalCompatibility.UNKNOWN: (),
}
_INVOLVEMENT = {
    AppraisalSelfInvolvement.NONE: 0.0,
    AppraisalSelfInvolvement.LIMITED: 0.35,
    AppraisalSelfInvolvement.IMPORTANT: 0.70,
    AppraisalSelfInvolvement.IDENTITY_LEVEL: 1.0,
    AppraisalSelfInvolvement.UNKNOWN: None,
}


def semantic_features(value: SemanticAppraisal) -> SemanticFeatures:
    standards = value.standards
    coping = value.coping
    causality = value.causality
    demand = value.demand
    suddenness, predictability = _EXPECTEDNESS[value.expectedness]
    return SemanticFeatures(
        tuple(
            SemanticConcernFeature(
                item.target,
                _SIGNIFICANCE[item.significance],
                _DIRECTION[item.direction],
            )
            for item in value.concerns
        ),
        suddenness,
        predictability,
        _CERTAINTY[value.outcome_certainty],
        _QUALITY[value.intrinsic_quality],
        None if demand is None else _URGENCY[demand.urgency],
        None if demand is None else _DEMAND[demand.effort],
        AppraisalAgency.UNKNOWN if causality is None else causality.agency,
        None
        if causality is None
        else _INTENTIONALITY[causality.intentionality],
        None
        if coping is None
        else _RESPONSE_ACCESS[coping.response_access],
        None if coping is None else _POWER[coping.power_balance],
        None if coping is None else _ADJUSTMENT[coping.adjustment],
        ()
        if standards is None
        else _COMPATIBILITY[standards.self_compatibility],
        ()
        if standards is None
        else _COMPATIBILITY[standards.norm_compatibility],
        _INVOLVEMENT[value.self_involvement],
        AppraisalSelfScope.NONE if standards is None else standards.self_scope,
    )


def semantic_features_to_wire(value: SemanticAppraisal) -> dict[str, object]:
    features = semantic_features(value)

    def scaled(item: float | None) -> int | None:
        return None if item is None else round(item * 100)

    def poles(items: tuple[tuple[float, float], ...]) -> list[dict[str, int]]:
        return [
            {"value": round(item * 100), "weight": round(weight * 100)}
            for item, weight in items
        ]

    return {
        "schema_version": "armi.mood-derived-appraisal.v2",
        "concerns": [
            {
                "target": item.target.value,
                "relevance": scaled(item.relevance),
                "direction_poles": poles(item.poles),
            }
            for item in features.concerns
        ],
        "suddenness": scaled(features.suddenness),
        "predictability": scaled(features.predictability),
        "outcome_certainty": scaled(features.certainty),
        "pleasantness_poles": poles(features.pleasantness_poles),
        "urgency": scaled(features.urgency),
        "effort": scaled(features.effort),
        "agency": features.agency.value,
        "intentionality": scaled(features.intentionality),
        "control": scaled(features.control),
        "power": scaled(features.power),
        "adjustment": scaled(features.adjustment),
        "self_compatibility_poles": poles(features.self_poles),
        "norm_compatibility_poles": poles(features.norm_poles),
        "self_involvement": scaled(features.ego),
        "self_scope": features.self_scope.value,
    }


def _pole_mean(items: tuple[tuple[float, float], ...]) -> float:
    denominator = sum(weight for _value, weight in items)
    return (
        0.0
        if not denominator
        else sum(value * weight for value, weight in items) / denominator
    )


def _pole_impact(items: tuple[tuple[float, float], ...]) -> float:
    return max((abs(value) * weight for value, weight in items), default=0.0)


def _round_axis(value: float) -> int:
    return max(-100, min(100, round(value / 5.0) * 5))


def _semantic_target(
    goal: float,
    features: SemanticFeatures,
    *,
    pleasantness: float,
    self_compatibility: float,
    norm_compatibility: float,
    activation: float,
) -> VAD:
    coping = tuple(
        (weight, item)
        for weight, item in (
            (0.45, features.control),
            (0.35, features.power),
            (0.20, features.adjustment),
        )
        if item is not None
    )
    dominance = (
        0.0
        if not coping
        else sum(weight * (2 * item - 1) for weight, item in coping)
        / sum(weight for weight, _item in coping)
    )
    return VAD(
        _round_axis(
            100
            * (
                0.55 * goal
                + 0.25 * pleasantness
                + 0.10 * self_compatibility
                + 0.10 * norm_compatibility
            )
        ),
        _round_axis(200 * activation - 100),
        _round_axis(100 * dominance),
    )


def _previous_negative_goal(
    previous: AppraisalEvent | SemanticAppraisalEvent | None,
    target: AppraisalConcernTarget,
) -> float:
    if previous is None:
        return 0.0
    if isinstance(previous, AppraisalEvent):
        return _negative(_normalized(previous.appraisal.goal_conduciveness))
    features = semantic_features(previous.appraisal)
    return max(
        (
            _negative(value) * weight
            for concern in features.concerns
            if concern.target is target
            for value, weight in concern.poles
        ),
        default=0.0,
    )


def derive_semantic_appraisal(
    event: SemanticAppraisalEvent,
    *,
    previous: AppraisalEvent | SemanticAppraisalEvent | None = None,
) -> DerivedAppraisal:
    features = semantic_features(event.appraisal)
    relevance = max(
        (item.relevance or 0.0 for item in features.concerns), default=0.0
    )
    sudden = features.suddenness or 0.0
    unexpected = (
        0.0 if features.predictability is None else 1.0 - features.predictability
    )
    uncertainty = 0.0 if features.certainty is None else 1.0 - features.certainty
    urgency = features.urgency or 0.0
    effort = features.effort or 0.0
    activation = (
        0.20 * sudden
        + 0.15 * unexpected
        + 0.20 * urgency
        + 0.15 * uncertainty
        + 0.15 * effort
        + 0.15 * relevance
    )
    weighted_goals = [
        (value, weight * concern.relevance)
        for concern in features.concerns
        if concern.relevance is not None
        for value, weight in concern.poles
    ]
    goal_denominator = sum(weight for _value, weight in weighted_goals)
    goal = (
        0.0
        if not goal_denominator
        else sum(value * weight for value, weight in weighted_goals)
        / goal_denominator
    )
    pleasantness = _pole_mean(features.pleasantness_poles)
    self_compatibility = _pole_mean(features.self_poles)
    norm_compatibility = _pole_mean(features.norm_poles)
    target = _semantic_target(
        goal,
        features,
        pleasantness=pleasantness,
        self_compatibility=self_compatibility,
        norm_compatibility=norm_compatibility,
        activation=activation,
    )
    impact = max(
        max(
            (
                abs(value) * weight
                for concern in features.concerns
                for value, weight in concern.poles
            ),
            default=0.0,
        ),
        _pole_impact(features.pleasantness_poles),
        _pole_impact(features.self_poles),
        _pole_impact(features.norm_poles),
    )
    importance = _round_to_five(
        100 * (0.65 * relevance + 0.25 * impact + 0.10 * urgency)
    )
    realized = _phase(event.phase, AppraisalEventPhase.REALIZED)
    prospective = _phase(
        event.phase, AppraisalEventPhase.ANTICIPATED, AppraisalEventPhase.ONGOING
    )
    ongoing = _phase(event.phase, AppraisalEventPhase.ONGOING)
    certainty = features.certainty or 0.0
    novelty = max(sudden, unexpected)
    control = features.control or 0.0
    power = features.power or 0.0
    adjustment = features.adjustment or 0.0
    known_control = 0.0 if features.control is None else control
    low_control = 0.0 if features.control is None else 1.0 - control
    low_power = 0.0 if features.power is None else 1.0 - power
    low_adjustment = 0.0 if features.adjustment is None else 1.0 - adjustment
    low_capacity = max(low_control, low_power, low_adjustment)
    intentionality = features.intentionality or 0.0
    ego = features.ego or 0.0
    self_agent = _agency(features.agency, AppraisalAgency.SELF)
    other_agent = _agency(features.agency, AppraisalAgency.OTHER)
    social_agent = _agency(
        features.agency, AppraisalAgency.OTHER, AppraisalAgency.SHARED
    )
    scores: dict[EmotionFamily, tuple[float, float, float]] = {}
    registration_weight = 1.0
    registration_relevance = relevance

    def register(family: EmotionFamily, score: float, component_goal: float) -> None:
        if score < 0.5:
            return
        score *= registration_weight
        current = scores.get(family)
        if current is None or score > current[0]:
            scores[family] = (score, component_goal, registration_relevance)

    for concern in features.concerns:
        concern_relevance = concern.relevance or 0.0
        registration_relevance = concern_relevance
        for concern_goal, pole_weight in concern.poles:
            registration_weight = pole_weight
            positive = _positive(concern_goal)
            negative = _negative(concern_goal)

            def score(*terms: float) -> float:
                return min(terms)

            register(
                EmotionFamily.JOY,
                score(concern_relevance, positive, realized, certainty),
                concern_goal,
            )
            register(
                EmotionFamily.CONTENTMENT,
                score(
                    concern_relevance,
                    positive,
                    realized,
                    certainty,
                    1.0 - urgency,
                    1.0 - novelty,
                ),
                concern_goal,
            )
            register(
                EmotionFamily.HOPE,
                score(concern_relevance, positive, prospective, _mid(certainty)),
                concern_goal,
            )
            if concern.target is AppraisalConcernTarget.RELATIONSHIP:
                register(
                    EmotionFamily.AFFECTION,
                    score(concern_relevance, positive),
                    concern_goal,
                )
                register(
                    EmotionFamily.JEALOUSY,
                    score(
                        concern_relevance,
                        negative,
                        social_agent,
                        prospective,
                        ego,
                    ),
                    concern_goal,
                )
            register(
                EmotionFamily.GRATITUDE,
                score(
                    concern_relevance,
                    positive,
                    other_agent,
                    intentionality,
                    realized,
                ),
                concern_goal,
            )
            if concern.target is AppraisalConcernTarget.SELF_GOAL:
                register(
                    EmotionFamily.PRIDE,
                    score(
                        concern_relevance,
                        positive,
                        self_agent,
                        _positive(self_compatibility),
                        ego,
                    ),
                    concern_goal,
                )
            register(
                EmotionFamily.SADNESS,
                score(
                    concern_relevance,
                    negative,
                    realized,
                    certainty,
                    low_capacity,
                ),
                concern_goal,
            )
            register(
                EmotionFamily.FEAR,
                score(
                    concern_relevance,
                    negative,
                    prospective,
                    certainty,
                    low_power,
                    urgency,
                ),
                concern_goal,
            )
            register(
                EmotionFamily.ANXIETY,
                score(
                    concern_relevance,
                    negative,
                    prospective,
                    uncertainty,
                    low_control,
                    urgency,
                ),
                concern_goal,
            )
            register(
                EmotionFamily.ANGER,
                score(
                    concern_relevance,
                    negative,
                    other_agent,
                    intentionality,
                    max(known_control, power),
                ),
                concern_goal,
            )
            register(
                EmotionFamily.FRUSTRATION,
                score(
                    concern_relevance,
                    negative,
                    effort,
                    max(
                        ongoing,
                        float(event.transition is AppraisalTransition.REINFORCE),
                    ),
                    _mid(control) if features.control is not None else 0.0,
                ),
                concern_goal,
            )
            register(
                EmotionFamily.BOREDOM,
                score(
                    concern_relevance,
                    ongoing,
                    1.0 - novelty,
                    1.0 - urgency,
                    1.0 - effort,
                    1.0 - abs(concern_goal),
                ),
                concern_goal,
            )
            if (
                event.transition is AppraisalTransition.RESOLVE
                and event.change_from_previous
                in {AppraisalTrajectory.IMPROVED, AppraisalTrajectory.MIXED}
            ) or event.phase is AppraisalEventPhase.AVERTED:
                register(
                    EmotionFamily.RELIEF,
                    score(
                        _previous_negative_goal(previous, concern.target),
                        max(float(event.phase is AppraisalEventPhase.AVERTED), positive),
                        concern_relevance,
                    ),
                    concern_goal,
                )

    registration_weight = 1.0
    registration_relevance = relevance
    register(
        EmotionFamily.INTEREST,
        min(relevance, novelty, max(control, adjustment)),
        goal,
    )
    register(EmotionFamily.SURPRISE, min(relevance, novelty), goal)
    register(
        EmotionFamily.CONFUSION,
        min(relevance, novelty, uncertainty, max(low_control, low_power)),
        goal,
    )
    for pleasantness_pole, pole_weight in features.pleasantness_poles:
        registration_weight = pole_weight
        register(
            EmotionFamily.DISGUST,
            min(
                relevance,
                _negative(pleasantness_pole),
                max(_negative(norm_compatibility), low_adjustment),
            ),
            goal,
        )
    for self_pole, pole_weight in features.self_poles:
        registration_weight = pole_weight
        register(
            EmotionFamily.SHAME,
            min(
                relevance,
                self_agent,
                _negative(self_pole),
                _scope(features.self_scope, AppraisalSelfScope.GLOBAL),
                ego,
                low_adjustment,
            ),
            goal,
        )
        register(
            EmotionFamily.GUILT,
            min(
                relevance,
                self_agent,
                _negative(self_pole),
                _scope(features.self_scope, AppraisalSelfScope.ACTION),
                ego,
                adjustment,
            ),
            goal,
        )

    components: list[StoredEmotionComponent] = []
    open_episode = float(
        event.phase in {AppraisalEventPhase.ANTICIPATED, AppraisalEventPhase.ONGOING}
    )
    for family, (
        family_score,
        component_goal,
        family_relevance,
    ) in scores.items():
        component_impact = max(
            abs(component_goal),
            _pole_impact(features.pleasantness_poles),
            _pole_impact(features.self_poles),
            _pole_impact(features.norm_poles),
        )
        salience = (
            0.55 * family_relevance
            + 0.25 * component_impact
            + 0.20 * activation
        )
        intensity = _round_to_five(100 * salience * family_score)
        normalized_importance = (importance - 5) / 95
        normalized_intensity = (intensity - 5) / 95
        persistence = (
            0.55 * normalized_importance
            + 0.25 * normalized_intensity
            + 0.20 * open_episode
        )
        component_target = _semantic_target(
            component_goal,
            features,
            pleasantness=pleasantness,
            self_compatibility=self_compatibility,
            norm_compatibility=norm_compatibility,
            activation=activation,
        )
        components.append(
            StoredEmotionComponent(
                EmotionComponent(family, event.gist, component_target, intensity),
                round(900 * (96**persistence)),
            )
        )
    components.sort(
        key=lambda item: (-item.component.intensity, item.component.family.value)
    )
    return DerivedAppraisal(target, importance, tuple(components[:3]))


def half_life_seconds(*, importance: int, intensity: int) -> int:
    normalized_importance = (importance - 5) / 95
    normalized_intensity = (intensity - 5) / 95
    score = 0.75 * normalized_importance + 0.25 * normalized_intensity
    return round(900 * (96**score))


def clamp_home_base(current: VAD, target: VAD) -> VAD:
    def move(value: int, desired: int) -> int:
        return value + max(-2, min(2, desired - value))

    return VAD(
        move(current.valence, target.valence),
        move(current.arousal, target.arousal),
        move(current.dominance, target.dominance),
    )


def derive_effective_state(
    home_base: VAD,
    events: tuple[StoredAffectiveEvent, ...],
    *,
    as_of: datetime,
) -> tuple[VAD, tuple[EffectiveEmotion, ...]]:
    current, active, _episodes, _tendencies = derive_effective_snapshot(
        home_base, events, as_of=as_of
    )
    return current, active


_TENDENCY_BY_FAMILY = {
    EmotionFamily.JOY: ActionTendency.APPROACH,
    EmotionFamily.CONTENTMENT: ActionTendency.PAUSE,
    EmotionFamily.INTEREST: ActionTendency.EXPLORE,
    EmotionFamily.HOPE: ActionTendency.APPROACH,
    EmotionFamily.RELIEF: ActionTendency.PAUSE,
    EmotionFamily.AFFECTION: ActionTendency.CONNECT,
    EmotionFamily.GRATITUDE: ActionTendency.CONNECT,
    EmotionFamily.PRIDE: ActionTendency.APPROACH,
    EmotionFamily.SURPRISE: ActionTendency.PAUSE,
    EmotionFamily.SADNESS: ActionTendency.WITHDRAW,
    EmotionFamily.FEAR: ActionTendency.PROTECT,
    EmotionFamily.ANXIETY: ActionTendency.PROTECT,
    EmotionFamily.ANGER: ActionTendency.CONFRONT,
    EmotionFamily.FRUSTRATION: ActionTendency.CONFRONT,
    EmotionFamily.DISGUST: ActionTendency.REJECT,
    EmotionFamily.SHAME: ActionTendency.WITHDRAW,
    EmotionFamily.GUILT: ActionTendency.REPAIR,
    EmotionFamily.JEALOUSY: ActionTendency.PROTECT,
    EmotionFamily.BOREDOM: ActionTendency.DISENGAGE,
    EmotionFamily.CONFUSION: ActionTendency.CLARIFY,
}


def derive_effective_snapshot(
    home_base: VAD,
    events: tuple[StoredAffectiveEvent, ...],
    *,
    as_of: datetime,
) -> tuple[
    VAD,
    tuple[EffectiveEmotion, ...],
    tuple[ActiveAffectiveEpisode, ...],
    tuple[EffectiveActionTendency, ...],
]:
    ordered = tuple(sorted(events, key=lambda item: item.occurred_at))
    weighted: list[
        tuple[float, EmotionComponent, datetime, UUID | None, str, AppraisalEventPhase]
    ] = []
    for index, event in enumerate(ordered):
        elapsed = max(0.0, (as_of - event.occurred_at).total_seconds())
        for stored in event.components:
            transition = next(
                (
                    later
                    for later in ordered[index + 1 :]
                    if event.episode_id is not None
                    and later.episode_id == event.episode_id
                    and later.occurred_at <= as_of
                    and later.transition
                    in {AppraisalTransition.REAPPRAISE, AppraisalTransition.RESOLVE}
                ),
                None,
            )
            if transition is None:
                intensity = stored.component.intensity * math.pow(
                    2.0, -elapsed / stored.half_life_seconds
                )
            else:
                before = max(
                    0.0, (transition.occurred_at - event.occurred_at).total_seconds()
                )
                after = max(0.0, (as_of - transition.occurred_at).total_seconds())
                factor = (
                    0.25
                    if transition.transition is AppraisalTransition.RESOLVE
                    else 0.5
                )
                intensity = (
                    stored.component.intensity
                    * math.pow(2.0, -before / stored.half_life_seconds)
                    * math.pow(2.0, -after / (stored.half_life_seconds * factor))
                )
            if intensity >= 1.0:
                weighted.append(
                    (
                        intensity,
                        stored.component,
                        event.occurred_at,
                        event.episode_id,
                        event.gist,
                        event.phase,
                    )
                )

    def axis(name: str) -> int:
        base = cast(int, getattr(home_base, name))
        numerator = _BASE_WEIGHT * base
        denominator = _BASE_WEIGHT
        for weight, component, _occurred_at, _episode, _gist, _phase in weighted:
            numerator += weight * cast(int, getattr(component.vad, name))
            denominator += weight
        return max(-100, min(100, round(numerator / denominator)))

    current = VAD(axis("valence"), axis("arousal"), axis("dominance"))
    grouped: dict[
        EmotionFamily,
        list[
            tuple[
                float,
                EmotionComponent,
                datetime,
                UUID | None,
                str,
                AppraisalEventPhase,
            ]
        ],
    ] = defaultdict(list)
    for item in weighted:
        grouped[item[1].family].append(item)
    active: list[EffectiveEmotion] = []
    for family, items in grouped.items():
        strength = min(100, round(sum(item[0] for item in items)))
        if strength < 5:
            continue
        strongest = max(items, key=lambda item: (item[0], item[2]))
        active.append(EffectiveEmotion(family, strongest[1].nuance, strength))
    active.sort(key=lambda item: (-item.intensity, item.family.value))
    active = active[:3]
    episode_strengths: dict[UUID, list[tuple[float, datetime, str, AppraisalEventPhase]]] = (
        defaultdict(list)
    )
    for intensity, _component, occurred_at, episode_id, gist, phase in weighted:
        if episode_id is not None:
            episode_strengths[episode_id].append(
                (intensity, occurred_at, gist, phase)
            )
    episodes: list[ActiveAffectiveEpisode] = []
    for episode_id, items in episode_strengths.items():
        strength = min(100, round(sum(item[0] for item in items)))
        if strength < 5:
            continue
        latest = max(items, key=lambda item: item[1])
        episodes.append(ActiveAffectiveEpisode(episode_id, latest[2], latest[3], strength))
    episodes.sort(key=lambda item: (-item.intensity, str(item.episode_id)))
    tendency_strengths: dict[ActionTendency, int] = defaultdict(int)
    for emotion in active:
        tendency = _TENDENCY_BY_FAMILY[emotion.family]
        tendency_strengths[tendency] = min(
            100, tendency_strengths[tendency] + emotion.intensity
        )
    tendencies = [
        EffectiveActionTendency(tendency, intensity)
        for tendency, intensity in tendency_strengths.items()
    ]
    tendencies.sort(key=lambda item: (-item.intensity, item.tendency.value))
    return current, tuple(active), tuple(episodes[:5]), tuple(tendencies[:2])


def validate_candidate(value: CandidateMoodDraft) -> None:
    common_invalid = (
        _REF.fullmatch(value.proposal_ref) is None
        or _GROUP.fullmatch(value.atomic_group_ref) is None
        or type(value.basis_ordinals) is not tuple
        or not 1 <= len(value.basis_ordinals) <= 8
        or any(
            type(item) is not int or not 1 <= item <= 999
            for item in value.basis_ordinals
        )
        or len(value.basis_ordinals) != len(set(value.basis_ordinals))
        or type(value.fact_class) is not CandidateFactClass
        or type(value.expected_version) is not int
        or value.expected_version <= 0
        or type(value.kind) is not MoodCandidateKind
    )
    shape_invalid = (
        value.kind is MoodCandidateKind.APPRAISAL
        and type(value.appraisal) not in {AppraisalEvent, SemanticAppraisalEvent}
    ) or (
        value.kind is MoodCandidateKind.HOME_BASE_REFLECTION
        and value.appraisal is not None
    )
    if common_invalid or shape_invalid:
        raise MoodViolation("MOOD-CANDIDATE")


__all__ = (
    "DerivedAppraisal",
    "StoredAffectiveEvent",
    "StoredEmotionComponent",
    "appraisal_to_wire",
    "clamp_home_base",
    "component_to_wire",
    "derive_appraisal",
    "derive_effective_snapshot",
    "derive_effective_state",
    "derive_semantic_appraisal",
    "half_life_seconds",
    "initial_state",
    "parse_appraisal",
    "parse_appraisal_any",
    "parse_component",
    "parse_semantic_appraisal",
    "parse_state",
    "parse_state_bytes",
    "parse_vad",
    "semantic_appraisal_to_wire",
    "semantic_features_to_wire",
    "state_to_bytes",
    "state_to_wire",
    "vad_to_wire",
    "validate_candidate",
    "validate_state",
)
