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
    AppraisalAgency,
    AppraisalEvent,
    AppraisalEventPhase,
    AppraisalSelfScope,
    AppraisalTransition,
    AppraisalVector,
    CandidateMoodDraft,
    EffectiveActionTendency,
    EffectiveEmotion,
    EmotionComponent,
    EmotionFamily,
    MoodCandidateKind,
    MoodState,
    MoodViolation,
)

_REF = re.compile(r"^proposal:[1-9][0-9]{0,2}$", re.ASCII)
_GROUP = re.compile(r"^group:[1-9][0-9]{0,2}$", re.ASCII)
_DYNAMICS_VERSION = "recency-reappraisal.v1"
_DERIVATION_VERSION = "cpm-fuzzy.v1"
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
        or raw["derivation_version"] != _DERIVATION_VERSION
    ):
        raise MoodViolation("MOOD-STATE")
    return MoodState(
        _DYNAMICS_VERSION,
        _DERIVATION_VERSION,
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
    vector = {
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
        and type(value.appraisal) is not AppraisalEvent
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
    "half_life_seconds",
    "initial_state",
    "parse_appraisal",
    "parse_component",
    "parse_state",
    "parse_state_bytes",
    "parse_vad",
    "state_to_bytes",
    "state_to_wire",
    "vad_to_wire",
    "validate_candidate",
    "validate_state",
)
