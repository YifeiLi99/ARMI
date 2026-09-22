"""Object-scoped psychological state; engineering hypotheses, not a human scale.

The event coordinator supplies grounded objects and evidence. This module never
creates goals, relationships, experiences or effects. Reading a projection cannot
change either a need or the eligibility of a consideration.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from enum import StrEnum
from math import isfinite


class MindVariable(StrEnum):
    AUTONOMY_SATISFACTION = "autonomy_satisfaction"
    AUTONOMY_FRUSTRATION = "autonomy_frustration"
    COMPETENCE_SATISFACTION = "competence_satisfaction"
    COMPETENCE_FRUSTRATION = "competence_frustration"
    RELATEDNESS_SATISFACTION = "relatedness_satisfaction"
    RELATEDNESS_FRUSTRATION = "relatedness_frustration"
    CONTACT_GAP = "contact_gap"
    NOVELTY = "novelty"
    INFORMATION_GAP = "information_gap"
    INFORMATION_VALUE = "information_value"
    COMPREHENSIBILITY = "comprehensibility"
    LEARNING_PROGRESS = "learning_progress"
    MEANING = "meaning"
    UNDERSTIMULATION = "understimulation"
    OVERLOAD = "overload"
    IMPORTANCE = "importance"


class MindChoice(StrEnum):
    NONE = "level_0"
    LOW = "level_1"
    MODERATE = "level_2"
    HIGH = "level_3"
    FULL = "level_4"
    UNKNOWN = "unknown"
    NOT_APPLICABLE = "not_applicable"


class Association(StrEnum):
    ACTIVE = "active"
    SATISFIED = "satisfied"
    RELEASED = "released"
    INVALID = "invalid"
    UNKNOWN = "unknown"


class Opportunity(StrEnum):
    AVAILABLE = "available"
    LATER = "later"
    UNAVAILABLE = "unavailable"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class MindParameters:
    """Central, uncalibrated engineering parameters; revise against counterexamples."""

    levels: tuple[float, ...] = (0.0, 0.25, 0.5, 0.75, 1.0)
    novelty_weight: float = 0.5
    activation_threshold: float = 0.6
    rearm_threshold: float = 0.4
    material_change: float = 0.25
    salience_half_life_seconds: float = 1800.0
    objects_per_event: int = 4
    questions_per_event: int = 72

    def __post_init__(self) -> None:
        unit_values = (
            *self.levels,
            self.novelty_weight,
            self.activation_threshold,
            self.rearm_threshold,
            self.material_change,
        )
        if (
            len(self.levels) != 5
            or any(not isfinite(v) or not 0 <= v <= 1 for v in unit_values)
            or tuple(sorted(set(self.levels))) != self.levels
            or not self.rearm_threshold < self.activation_threshold
            or self.material_change <= 0
            or not isfinite(self.salience_half_life_seconds)
            or self.salience_half_life_seconds <= 0
            or not 1 <= self.objects_per_event <= 4
            or not 1 <= self.questions_per_event <= 72
        ):
            raise ValueError("invalid Mind engineering parameters")


MIND_PARAMETERS = MindParameters()
_KNOWN_CHOICES = tuple(MindChoice)[:5]


@dataclass(frozen=True, slots=True)
class GroundedObject:
    source_kind: str
    source_ref: str

    def __post_init__(self) -> None:
        if not self.source_kind or not self.source_ref:
            raise ValueError("Mind object requires a formal source")


@dataclass(frozen=True, slots=True)
class MindEvidence:
    object: GroundedObject
    evidence_key: str
    basis_refs: tuple[str, ...]
    at: datetime
    ratings: tuple[tuple[MindVariable, MindChoice], ...]
    association: Association
    opportunity: Opportunity

    def __post_init__(self) -> None:
        if (
            not self.evidence_key
            or not self.basis_refs
            or any(not ref for ref in self.basis_refs)
            or self.at.tzinfo is None
            or len(dict(self.ratings)) != len(self.ratings)
            or any(
                type(k) is not MindVariable or type(v) is not MindChoice
                for k, v in self.ratings
            )
            or type(self.association) is not Association
            or type(self.opportunity) is not Opportunity
        ):
            raise ValueError("invalid grounded Mind evidence")


@dataclass(frozen=True, slots=True)
class VariableState:
    variable: MindVariable
    value: float | None
    quality: MindChoice
    known_at: datetime | None
    basis_refs: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class DerivedMindState:
    exploration: float | None
    engagement_fit: float | None
    engagement_adjustment: float | None
    contact_need: float | None
    priority: float | None
    motives: tuple[tuple[str, float], ...]


@dataclass(frozen=True, slots=True)
class MindObjectState:
    object: GroundedObject
    evidence_key: str
    evaluated_at: datetime
    salient_at: datetime
    variables: tuple[VariableState, ...]
    association: Association
    opportunity: Opportunity
    condition_version: int = 0
    armed: bool = True
    condition_motives: tuple[tuple[str, float], ...] = ()
    last_review_key: str | None = None
    condition_reason: str | None = None


def derive_mind(
    states: tuple[VariableState, ...],
    *,
    parameters: MindParameters = MIND_PARAMETERS,
) -> DerivedMindState:
    """Unknown values remain visible in state but cannot create a new signal."""
    known = {
        s.variable.value: s.value
        for s in states
        if s.quality in _KNOWN_CHOICES and s.value is not None
    }

    def complete(*keys: str) -> bool:
        return all(known.get(key) is not None for key in keys)

    exploration = None
    if complete(
        "information_gap",
        "comprehensibility",
        "information_value",
        "learning_progress",
        "novelty",
    ):
        exploration = (
            known["information_gap"]
            * known["comprehensibility"]
            * max(
                known["information_value"],
                known["learning_progress"],
                parameters.novelty_weight * known["novelty"],
            )
        )
    fit = adjustment = None
    if complete("meaning", "understimulation", "overload"):
        fit = known["meaning"] * (1 - max(known["understimulation"], known["overload"]))
        adjustment = max(
            1 - known["meaning"], known["understimulation"], known["overload"]
        )
    motives = {
        "exploration": exploration,
        "engagement_adjustment": adjustment,
        "autonomy_frustration": known.get("autonomy_frustration"),
        "competence_frustration": known.get("competence_frustration"),
        "relatedness_frustration": known.get("relatedness_frustration"),
        "contact_need": known.get("contact_gap"),
    }
    available = tuple(
        (key, value) for key, value in motives.items() if value is not None
    )
    importance = known.get("importance")
    priority = (
        importance * max(v for _, v in available)
        if available and importance is not None
        else None
    )
    return DerivedMindState(
        exploration, fit, adjustment, known.get("contact_gap"), priority, available
    )


def update_mind_object(
    evidence: MindEvidence,
    *,
    previous: MindObjectState | None = None,
    due_review_key: str | None = None,
    parameters: MindParameters = MIND_PARAMETERS,
) -> MindObjectState:
    if previous is not None:
        if previous.object != evidence.object:
            raise ValueError("Mind evidence cannot update another object")
        if previous.evidence_key == evidence.evidence_key:
            return previous
        if evidence.at < previous.evaluated_at:
            raise ValueError("stale Mind evidence")
    old = {item.variable: item for item in previous.variables} if previous else {}
    for variable, choice in evidence.ratings:
        prior = old.get(variable)
        if choice == MindChoice.UNKNOWN:
            old[variable] = VariableState(
                variable,
                prior.value if prior else None,
                choice,
                prior.known_at if prior else None,
                prior.basis_refs if prior else (),
            )
        elif choice == MindChoice.NOT_APPLICABLE:
            old[variable] = VariableState(
                variable, None, choice, None, evidence.basis_refs
            )
        else:
            value = parameters.levels[_KNOWN_CHOICES.index(choice)]
            old[variable] = VariableState(
                variable, value, choice, evidence.at, evidence.basis_refs
            )
    variables = tuple(old[key] for key in MindVariable if key in old)
    derived = derive_mind(variables, parameters=parameters)
    before = (
        derive_mind(previous.variables, parameters=parameters) if previous else None
    )
    # New timestamps and source versions alone do not renew attention or eligibility.
    semantic_change = previous is None or (
        tuple((v.variable, v.value, v.quality) for v in variables)
        != tuple((v.variable, v.value, v.quality) for v in previous.variables)
        or evidence.association != previous.association
        or evidence.opportunity != previous.opportunity
    )
    state = MindObjectState(
        evidence.object,
        evidence.evidence_key,
        evidence.at,
        evidence.at if semantic_change or previous is None else previous.salient_at,
        variables,
        evidence.association,
        evidence.opportunity,
        previous.condition_version if previous else 0,
        previous.armed if previous else True,
        previous.condition_motives if previous else (),
        previous.last_review_key if previous else None,
        previous.condition_reason if previous else None,
    )
    unresolved_trigger_evidence = any(
        variable.quality == MindChoice.UNKNOWN
        and variable.variable
        not in {
            MindVariable.AUTONOMY_SATISFACTION,
            MindVariable.COMPETENCE_SATISFACTION,
            MindVariable.RELATEDNESS_SATISFACTION,
        }
        for variable in variables
    )
    if (
        derived.priority is not None
        and derived.priority <= parameters.rearm_threshold
        and not unresolved_trigger_evidence
    ):
        state = replace(state, armed=True)
    if (
        evidence.association != Association.ACTIVE
        or evidence.opportunity != Opportunity.AVAILABLE
        or derived.priority is None
        or derived.priority < parameters.activation_threshold
    ):
        return state
    last_motives = dict(state.condition_motives)
    prior_motives = dict(before.motives) if before else {}
    material = any(
        key in last_motives
        and key in prior_motives
        and abs(value - last_motives[key]) >= parameters.material_change
        and value != prior_motives[key]
        for key, value in derived.motives
    )
    restored = previous is not None and previous.opportunity in {
        Opportunity.LATER,
        Opportunity.UNAVAILABLE,
    }
    review_due = due_review_key is not None and due_review_key != state.last_review_key
    if state.armed or material or restored or review_due:
        reason = (
            "review_time_reached"
            if review_due
            else (
                "opportunity_restored"
                if restored
                else "material_change"
                if material
                else "threshold_reached"
            )
        )
        state = replace(
            state,
            condition_version=state.condition_version + 1,
            armed=False,
            condition_motives=derived.motives,
            last_review_key=due_review_key if review_due else state.last_review_key,
            condition_reason=reason,
        )
    return state


def mind_attention_weight(
    state: MindObjectState,
    *,
    at: datetime,
    parameters: MindParameters = MIND_PARAMETERS,
) -> float:
    if at.tzinfo is None or at < state.evaluated_at:
        raise ValueError("projection requires an aware time after assessment")
    priority = derive_mind(state.variables, parameters=parameters).priority
    if priority is None or state.association != Association.ACTIVE:
        return 0.0
    return priority * 2 ** (
        -(at - state.salient_at).total_seconds() / parameters.salience_half_life_seconds
    )


def mind_condition_eligible(
    state: MindObjectState,
    *,
    consumed_versions: frozenset[int],
    parameters: MindParameters = MIND_PARAMETERS,
) -> bool:
    priority = derive_mind(state.variables, parameters=parameters).priority
    return (
        state.condition_version > 0
        and state.condition_version not in consumed_versions
        and state.association == Association.ACTIVE
        and state.opportunity == Opportunity.AVAILABLE
        and priority is not None
        and priority >= parameters.activation_threshold
    )
