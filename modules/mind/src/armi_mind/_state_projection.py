"""Read-only domain projections for the numeric Mind contract."""

from datetime import datetime

from ._state_algorithm import (
    MIND_PARAMETERS,
    MindChoice,
    MindObjectState,
    MindParameters,
    derive_mind,
    mind_attention_weight,
    mind_condition_eligible,
)


def project_mind_object(
    state: MindObjectState,
    *,
    at: datetime,
    consumed_versions: frozenset[int],
    parameters: MindParameters = MIND_PARAMETERS,
) -> dict[str, object]:
    derived = derive_mind(state.variables, parameters=parameters)
    values: dict[str, object] = {
        item.variable.value: {
            "value": None if item.value is None else 100 * item.value,
            "quality": item.quality.value
            if item.quality
            in {
                MindChoice.UNKNOWN,
                MindChoice.NOT_APPLICABLE,
            }
            else "known",
            "choice": item.quality.value,
            "known_at": None if item.known_at is None else item.known_at.isoformat(),
            "basis_refs": list(item.basis_refs),
        }
        for item in state.variables
    }

    def score(value: float | None) -> float | None:
        return None if value is None else 100 * value

    def domain(*names: str) -> dict[str, object]:
        return {name: values.get(name) for name in names}

    return {
        "object": {
            "source_kind": state.object.source_kind,
            "source_ref": state.object.source_ref,
        },
        "evaluated_at": state.evaluated_at.isoformat(),
        "as_of": at.isoformat(),
        "association": state.association.value,
        "opportunity": state.opportunity.value,
        "domains": {
            "autonomy": domain("autonomy_satisfaction", "autonomy_frustration"),
            "competence": domain("competence_satisfaction", "competence_frustration"),
            "relatedness": {
                **domain(
                    "relatedness_satisfaction", "relatedness_frustration", "contact_gap"
                ),
                "contact_need": score(derived.contact_need),
            },
            "exploration": {
                **domain(
                    "novelty",
                    "information_gap",
                    "information_value",
                    "comprehensibility",
                    "learning_progress",
                ),
                "motivation": score(derived.exploration),
            },
            "engagement": {
                **domain("meaning", "understimulation", "overload"),
                "fit": score(derived.engagement_fit),
                "adjustment": score(derived.engagement_adjustment),
            },
        },
        "consideration": {
            "importance": values.get("importance"),
            "priority": score(derived.priority),
            "attention_weight": 100
            * mind_attention_weight(state, at=at, parameters=parameters),
            "condition_version": state.condition_version,
            "reason": state.condition_reason,
            "eligible": mind_condition_eligible(
                state, consumed_versions=consumed_versions, parameters=parameters
            ),
        },
    }
