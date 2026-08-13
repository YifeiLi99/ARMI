"""Intention and expression module composition entry point."""

from dataclasses import dataclass

from armi_interaction.api import (
    InteractionEffectRoutePort,
    InteractionSceneTransitionPort,
)
from armi_relationship.api import RelationshipPolicyPort, RelationshipReadPort
from armi_runtime_foundation import RecoveryParticipant

from ._action_postgresql import PostgreSQLExpressionActionOwner
from ._admin import PostgreSQLExpressionAdmin
from ._postgresql import PostgreSQLExpressionOwner
from ._recovery import ExpressionRecoveryParticipant
from .api import (
    ExpressionAdminPort,
    ExpressionCommitPort,
    ExpressionEffectLinkPort,
    ExpressionEffectRegistrationPort,
    ExpressionIntentReadPort,
    ExpressionResponseAdmissionPort,
)


def bootstrap_expression_admin() -> ExpressionAdminPort:
    return PostgreSQLExpressionAdmin()


@dataclass(frozen=True, slots=True)
class ExpressionModule:
    commit: ExpressionCommitPort
    admission: ExpressionResponseAdmissionPort
    intents: ExpressionIntentReadPort
    effect_links: ExpressionEffectLinkPort


@dataclass(frozen=True, slots=True)
class ExpressionActionPorts:
    admission: ExpressionResponseAdmissionPort
    intents: ExpressionIntentReadPort
    effect_links: ExpressionEffectLinkPort


def bootstrap_expression_action_ports() -> ExpressionActionPorts:
    owner = PostgreSQLExpressionActionOwner()
    return ExpressionActionPorts(owner, owner, owner)


def bootstrap_expression(
    relationships: RelationshipReadPort,
    relationship_policy: RelationshipPolicyPort,
    effect_registration: ExpressionEffectRegistrationPort,
    interaction_routes: InteractionEffectRoutePort,
    interaction_scenes: InteractionSceneTransitionPort,
) -> ExpressionModule:
    actions = bootstrap_expression_action_ports()
    return ExpressionModule(
        commit=PostgreSQLExpressionOwner(
            relationships,
            relationship_policy,
            effect_registration,
            interaction_routes,
            interaction_scenes,
        ),
        admission=actions.admission,
        intents=actions.intents,
        effect_links=actions.effect_links,
    )


def bootstrap_expression_recovery() -> RecoveryParticipant:
    return ExpressionRecoveryParticipant()


__all__ = (
    "ExpressionActionPorts",
    "ExpressionModule",
    "bootstrap_expression",
    "bootstrap_expression_action_ports",
    "bootstrap_expression_admin",
    "bootstrap_expression_recovery",
)
