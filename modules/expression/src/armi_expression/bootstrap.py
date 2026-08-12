"""Intention and expression module composition entry point."""

from dataclasses import dataclass

from armi_relationship.api import RelationshipPolicyPort, RelationshipReadPort

from ._postgresql import PostgreSQLExpressionOwner
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


__all__ = ("ExpressionModule", "bootstrap_expression")
