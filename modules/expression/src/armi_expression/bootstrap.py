"""Intention and expression module composition entry point."""

from dataclasses import dataclass

from armi_relationship.api import RelationshipPolicyPort, RelationshipReadPort
from armi_runtime_foundation import RecoveryParticipant

from ._postgresql import PostgreSQLExpressionOwner
from ._recovery import ExpressionRecoveryParticipant
from .api import ExpressionCommitPort, ExpressionEffectRegistrationPort


@dataclass(frozen=True, slots=True)
class ExpressionModule:
    commit: ExpressionCommitPort


def bootstrap_expression(
    relationships: RelationshipReadPort,
    relationship_policy: RelationshipPolicyPort,
    effect_registration: ExpressionEffectRegistrationPort,
) -> ExpressionModule:
    return ExpressionModule(
        PostgreSQLExpressionOwner(
            relationships,
            relationship_policy,
            effect_registration,
        )
    )


def bootstrap_expression_recovery() -> RecoveryParticipant:
    return ExpressionRecoveryParticipant()


__all__ = (
    "ExpressionModule",
    "bootstrap_expression",
    "bootstrap_expression_recovery",
)
