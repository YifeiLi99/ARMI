"""Persistent dimensions and pure dynamics. See DESIGN, Mind continuous needs."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from math import isfinite
from types import MappingProxyType
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator


class _Strict(BaseModel):
    model_config = ConfigDict(
        extra="forbid", strict=True, frozen=True, allow_inf_nan=False
    )


class DynamicsParameters(_Strict):
    half_life_seconds: float = Field(default=14_400.0, gt=0)
    contact_base_relief: float = Field(default=0.05, ge=0, le=0.5)
    cue_gain: float = Field(default=0.1, ge=0, le=1)


DEFAULT_DYNAMICS_PARAMETERS = DynamicsParameters()


class DimensionState(_Strict):
    dimension: str
    target_ref: str | None
    value: float = Field(ge=0, le=1)
    equilibrium: float = Field(ge=0, le=1)
    active_seconds: float = Field(ge=0)
    half_life_seconds: float = Field(gt=0)
    basis_refs: tuple[str, ...]
    last_event_key: str | None

    @property
    def identity(self) -> tuple[str, str | None]:
        return self.dimension, self.target_ref


class SocialEvidence(_Strict):
    person_ref: str | None
    received_contact: bool
    quality: Literal[
        "level_0",
        "level_1",
        "level_2",
        "level_3",
        "level_4",
        "unknown",
        "not_applicable",
        "rejecting",
    ]
    importance: Literal[
        "level_0",
        "level_1",
        "level_2",
        "level_3",
        "level_4",
        "unknown",
        "not_applicable",
    ]
    cue: Literal[
        "level_0",
        "level_1",
        "level_2",
        "level_3",
        "level_4",
        "unknown",
        "not_applicable",
    ]

    @model_validator(mode="after")
    def contact_has_person(self) -> Self:
        if self.received_contact and self.person_ref is None:
            raise ValueError("MIND-CONTACT-PERSON")
        return self


def _level(choice: str) -> float | None:
    return int(choice[-1]) / 4 if choice.startswith("level_") else None


@dataclass(frozen=True, slots=True)
class DimensionEvent:
    """Owner-frozen event evidence shared by registered numeric dimensions."""

    choices: tuple[tuple[str, str], ...] = ()
    social: SocialEvidence | None = None

    @property
    def person_ref(self) -> str | None:
        return None if self.social is None else self.social.person_ref


def exponential_value(state: DimensionState, active_seconds: float) -> float:
    if not isfinite(active_seconds) or active_seconds < state.active_seconds:
        raise ValueError("MIND-ACTIVE-TIME")
    return state.equilibrium + (state.value - state.equilibrium) * 2 ** (
        -(active_seconds - state.active_seconds) / state.half_life_seconds
    )


def _social_update(
    state: DimensionState, evidence: DimensionEvent, parameters: DynamicsParameters
) -> tuple[float, float]:
    value, equilibrium = state.value, state.equilibrium
    event = evidence.social
    if event is None:
        return value, equilibrium
    personal = state.target_ref is not None
    if personal and event.person_ref != state.target_ref:
        return value, equilibrium
    importance = _level(event.importance)
    if personal and importance is not None:
        equilibrium = importance
    if event.received_contact:
        # The base term is grounded in authenticated interaction, not an unknown
        # semantic answer being treated as known. Explicit rejection gives none.
        relief = (
            0.0
            if event.quality in {"rejecting", "not_applicable", "level_0"}
            else parameters.contact_base_relief
            if event.quality == "unknown"
            else (0.0, 0.1, 0.25, 0.4, 0.5)[int(event.quality[-1])]
        )
        value *= 1 - relief
    elif personal:
        cue = _level(event.cue)
        if cue is not None:
            value += parameters.cue_gain * cue * (1 - value)
    return value, equilibrium


@dataclass(frozen=True, slots=True)
class DimensionDefinition:
    name: str
    scope: Literal["subject", "person"]
    initial_equilibrium: float
    evolve: Callable[[DimensionState, float], float]
    reduce: Callable[
        [DimensionState, DimensionEvent, DynamicsParameters], tuple[float, float]
    ]
    motive: Callable[[float], float]
    establish: Callable[[DimensionEvent], bool]
    initial_value: float = 0.0


def _intensity(value: float) -> float:
    return value


def _grounded_person(evidence: DimensionEvent) -> bool:
    event = evidence.social
    return (
        event is not None
        and event.person_ref is not None
        and (
            _level(event.importance) is not None or _level(event.cue) not in {None, 0.0}
        )
    )


DIMENSIONS: Mapping[str, DimensionDefinition] = MappingProxyType(
    {
        item.name: item
        for item in (
            DimensionDefinition(
                "companionship",
                "subject",
                1.0,
                exponential_value,
                _social_update,
                _intensity,
                lambda _event: True,
            ),
            DimensionDefinition(
                "longing",
                "person",
                0.0,
                exponential_value,
                _social_update,
                _intensity,
                _grounded_person,
            ),
        )
    }
)


def initial_dimensions(
    parameters: DynamicsParameters,
    *,
    registry: Mapping[str, DimensionDefinition] = DIMENSIONS,
) -> tuple[DimensionState, ...]:
    return tuple(
        new_dimension(definition, None, 0.0, parameters)
        for definition in registry.values()
        if definition.scope == "subject"
    )


def new_dimension(
    definition: DimensionDefinition,
    target_ref: str | None,
    active_seconds: float,
    parameters: DynamicsParameters,
) -> DimensionState:
    if (definition.scope == "person") != (target_ref is not None):
        raise ValueError("MIND-DIMENSION-SCOPE")
    return DimensionState(
        dimension=definition.name,
        target_ref=target_ref,
        value=definition.initial_value,
        equilibrium=definition.initial_equilibrium,
        active_seconds=active_seconds,
        half_life_seconds=parameters.half_life_seconds,
        basis_refs=(),
        last_event_key=None,
    )


def update_dimensions(
    states: tuple[DimensionState, ...],
    *,
    evidence: DimensionEvent,
    event_key: str,
    basis_refs: tuple[str, ...],
    active_seconds: float,
    parameters: DynamicsParameters,
    registry: Mapping[str, DimensionDefinition] = DIMENSIONS,
) -> tuple[DimensionState, ...]:
    by_id = {state.identity: state for state in states}
    if evidence.person_ref is not None:
        for definition in registry.values():
            if definition.scope == "person" and definition.establish(evidence):
                key = definition.name, evidence.person_ref
                if key not in by_id:
                    by_id[key] = new_dimension(
                        definition, evidence.person_ref, active_seconds, parameters
                    )
    result: list[DimensionState] = []
    for state in by_id.values():
        definition = registry[state.dimension]
        if state.last_event_key == event_key:
            result.append(state)
            continue
        if definition.scope == "person" and state.target_ref != evidence.person_ref:
            result.append(state)
            continue
        current = state.model_copy(
            update={
                "value": definition.evolve(state, active_seconds),
                "active_seconds": active_seconds,
            }
        )
        value, equilibrium = definition.reduce(current, evidence, parameters)
        result.append(
            DimensionState(
                dimension=state.dimension,
                target_ref=state.target_ref,
                value=value,
                equilibrium=equilibrium,
                active_seconds=active_seconds,
                half_life_seconds=state.half_life_seconds,
                basis_refs=basis_refs,
                last_event_key=event_key,
            )
        )
    return tuple(result)


def dimensions_projection(
    states: tuple[DimensionState, ...],
    *,
    active_seconds: float,
    registry: Mapping[str, DimensionDefinition] = DIMENSIONS,
) -> list[dict[str, object]]:
    return [
        {
            "dimension": state.dimension,
            "target_ref": state.target_ref,
            "value": 100 * registry[state.dimension].evolve(state, active_seconds),
            "equilibrium": 100 * state.equilibrium,
            "active_seconds": active_seconds,
            "anchor_active_seconds": state.active_seconds,
            "half_life_seconds": state.half_life_seconds,
            "basis_refs": list(state.basis_refs),
        }
        for state in states
    ]


def contact_drive(
    states: tuple[DimensionState, ...], *, person_ref: str, active_seconds: float
) -> float:
    return max(
        (
            DIMENSIONS[state.dimension].motive(
                DIMENSIONS[state.dimension].evolve(state, active_seconds)
            )
            for state in states
            if state.target_ref in {None, person_ref}
        ),
        default=0.0,
    )
