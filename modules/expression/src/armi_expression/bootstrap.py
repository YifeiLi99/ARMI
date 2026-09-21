"""Intention and expression module composition entry point."""

from dataclasses import dataclass

from armi_data_rights.api import DataRightsParticipant
from armi_interaction.api import (
    InteractionEffectRoutePort,
    InteractionSceneTransitionPort,
)
from armi_relationship.api import RelationshipPolicyPort, RelationshipReadPort
from armi_runtime_foundation import RecoveryParticipant

from ._action_postgresql import PostgreSQLExpressionActionOwner
from ._data_rights import PostgreSQLExpressionDataRightsParticipant
from ._postgresql import PostgreSQLExpressionOwner
from ._recovery import ExpressionRecoveryParticipant
from .api import (
    ExpressionCommitPort,
    ExpressionEffectLinkPort,
    ExpressionEffectRegistrationPort,
    ExpressionIntentReadPort,
    ExpressionVoiceRoutePort,
)


@dataclass(frozen=True, slots=True)
class ExpressionModule:
    commit: ExpressionCommitPort
    intents: ExpressionIntentReadPort
    effect_links: ExpressionEffectLinkPort


@dataclass(frozen=True, slots=True)
class ExpressionActionPorts:
    intents: ExpressionIntentReadPort
    effect_links: ExpressionEffectLinkPort


def bootstrap_expression_action_ports(
    intents: ExpressionIntentReadPort,
) -> ExpressionActionPorts:
    owner = PostgreSQLExpressionActionOwner(intents)
    return ExpressionActionPorts(owner, owner)


def bootstrap_expression(
    relationships: RelationshipReadPort,
    relationship_policy: RelationshipPolicyPort,
    effect_registration: ExpressionEffectRegistrationPort,
    interaction_routes: InteractionEffectRoutePort,
    interaction_scenes: InteractionSceneTransitionPort,
    voice: ExpressionVoiceRoutePort,
    intents: ExpressionIntentReadPort,
) -> ExpressionModule:
    actions = bootstrap_expression_action_ports(intents)
    return ExpressionModule(
        commit=PostgreSQLExpressionOwner(
            relationships,
            relationship_policy,
            effect_registration,
            interaction_routes,
            interaction_scenes,
            voice,
        ),
        intents=actions.intents,
        effect_links=actions.effect_links,
    )


def bootstrap_expression_data_rights() -> DataRightsParticipant:
    return PostgreSQLExpressionDataRightsParticipant()


def bootstrap_expression_recovery() -> RecoveryParticipant:
    return ExpressionRecoveryParticipant()


__all__ = (
    "ExpressionActionPorts",
    "ExpressionModule",
    "bootstrap_expression",
    "bootstrap_expression_action_ports",
    "bootstrap_expression_data_rights",
    "bootstrap_expression_recovery",
)
