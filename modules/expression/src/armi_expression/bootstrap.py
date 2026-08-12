"""Intention and expression module composition entry point."""

from dataclasses import dataclass

from armi_relationship.api import RelationshipPolicyPort, RelationshipReadPort

from ._postgresql import PostgreSQLExpressionOwner
from .api import ExpressionCommitPort


@dataclass(frozen=True, slots=True)
class ExpressionModule:
    commit: ExpressionCommitPort


def bootstrap_expression(
    relationships: RelationshipReadPort,
    relationship_policy: RelationshipPolicyPort,
) -> ExpressionModule:
    return ExpressionModule(
        PostgreSQLExpressionOwner(relationships, relationship_policy)
    )


__all__ = ("ExpressionModule", "bootstrap_expression")
