"""Shared Web and machine projection of governed effect results."""

from typing import Any, Literal, cast

from armi_effect.api import EffectView

from .creator_contract import EffectResponse


def effect_wire(view: EffectView) -> dict[str, Any]:
    return EffectResponse(
        contract_version="1.0",
        projection_version="creator-effect.v4",
        effect_id=str(view.effect_id.value),
        action_intent_ref=str(view.action_intent_ref),
        action_intent_revision_ref=str(view.action_intent_revision_ref),
        policy_decision_ref=None
        if view.policy_decision_ref is None
        else str(view.policy_decision_ref),
        capability_request_ref=str(view.capability_request_ref),
        permission_grant_ref=str(view.permission_grant_ref),
        capability_kind=view.capability_kind,
        effect_kind=view.effect_kind,
        status=view.status.value,
        verification_status=view.verification_status.value,
        registered_at=view.registered_at.to_wire(),
        cancelled_at=view.cancelled_at.to_wire()
        if view.cancelled_at is not None
        else None,
        attempt_count=view.attempt_count,
        current_attempt_ref=None
        if view.current_attempt_ref is None
        else str(view.current_attempt_ref),
        current_attempt_no=view.current_attempt_no,
        current_dispatch_state=cast(
            Literal["prepared", "dispatching", "settled"] | None,
            view.current_dispatch_state,
        ),
        current_observation_ref=None
        if view.current_observation_ref is None
        else str(view.current_observation_ref),
        observation_conclusion=cast(
            Literal["completed", "failed", "unknown", "cancelled"] | None,
            view.observation_conclusion,
        ),
        observation_reason=view.observation_reason,
        observation_evidence_kind=view.observation_evidence_kind,
        last_observation_kind=view.last_observation_kind.value
        if view.last_observation_kind is not None
        else None,
        last_observation_reliability=view.last_observation_reliability.value
        if view.last_observation_reliability is not None
        else None,
        verification_action=view.verification_action,
        settled_at=view.settled_at.to_wire() if view.settled_at is not None else None,
        response_text=view.response_text,
    ).model_dump(exclude_none=True)
