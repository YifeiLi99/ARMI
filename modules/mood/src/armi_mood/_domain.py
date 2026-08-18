"""Mood invariants and deterministic affect dynamics."""

from __future__ import annotations

import json
import math
import re
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from typing import Any, cast

import rfc8785
from armi_kernel.application import CandidateFactClass

from .api import (
    VAD,
    AffectiveEvent,
    CandidateMoodDraft,
    EffectiveEmotion,
    EmotionComponent,
    EmotionFamily,
    MoodCandidateKind,
    MoodState,
    MoodViolation,
)

_REF = re.compile(r"^proposal:[1-9][0-9]{0,2}$", re.ASCII)
_GROUP = re.compile(r"^group:[1-9][0-9]{0,2}$", re.ASCII)
_DYNAMICS_VERSION = "exponential.v1"
_BASE_WEIGHT = 30.0


@dataclass(frozen=True, slots=True)
class StoredEmotionComponent:
    component: EmotionComponent
    half_life_seconds: int


@dataclass(frozen=True, slots=True)
class StoredAffectiveEvent:
    occurred_at: datetime
    components: tuple[StoredEmotionComponent, ...]


def initial_state() -> MoodState:
    return MoodState(_DYNAMICS_VERSION, VAD(0, 0, 0))


def state_to_wire(state: MoodState) -> dict[str, object]:
    return {
        "schema_version": "armi.mood.v2",
        "dynamics_version": state.dynamics_version,
        "home_base": vad_to_wire(state.home_base),
    }


def state_to_bytes(state: MoodState) -> bytes:
    return rfc8785.dumps(cast(Any, state_to_wire(state)))


def parse_state(value: object) -> MoodState:
    if type(value) is not dict:
        raise MoodViolation("MOOD-STATE")
    raw = cast(dict[str, object], value)
    if (
        set(raw) != {"schema_version", "dynamics_version", "home_base"}
        or raw["schema_version"] != "armi.mood.v2"
        or raw["dynamics_version"] != _DYNAMICS_VERSION
    ):
        raise MoodViolation("MOOD-STATE")
    return MoodState(_DYNAMICS_VERSION, parse_vad(raw["home_base"], step=None))


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
    weighted: list[tuple[float, EmotionComponent, datetime]] = []
    for event in events:
        elapsed = max(0.0, (as_of - event.occurred_at).total_seconds())
        for stored in event.components:
            intensity = stored.component.intensity * math.pow(
                2.0, -elapsed / stored.half_life_seconds
            )
            if intensity >= 1.0:
                weighted.append((intensity, stored.component, event.occurred_at))

    def axis(name: str) -> int:
        base = cast(int, getattr(home_base, name))
        numerator = _BASE_WEIGHT * base
        denominator = _BASE_WEIGHT
        for weight, component, _occurred_at in weighted:
            numerator += weight * cast(int, getattr(component.vad, name))
            denominator += weight
        return max(-100, min(100, round(numerator / denominator)))

    current = VAD(axis("valence"), axis("arousal"), axis("dominance"))
    grouped: dict[EmotionFamily, list[tuple[float, EmotionComponent, datetime]]] = (
        defaultdict(list)
    )
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
    return current, tuple(active[:3])


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
        value.kind is MoodCandidateKind.EVENT
        and (
            type(value.event) is not AffectiveEvent
            or value.target_home_base is not None
        )
    ) or (
        value.kind is MoodCandidateKind.HOME_BASE_REFLECTION
        and (value.event is not None or type(value.target_home_base) is not VAD)
    )
    if common_invalid or shape_invalid:
        raise MoodViolation("MOOD-CANDIDATE")


__all__ = (
    "StoredAffectiveEvent",
    "StoredEmotionComponent",
    "clamp_home_base",
    "component_to_wire",
    "derive_effective_state",
    "half_life_seconds",
    "initial_state",
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
