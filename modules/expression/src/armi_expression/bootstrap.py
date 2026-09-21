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
    DialogueDecisionRecordPort,
    ExpressionCommitPort,
    ExpressionEffectRegistrationPort,
    ExpressionIntentReadPort,
    ExpressionVoiceRoutePort,
)


@dataclass(frozen=True, slots=True)
class ExpressionModule:
    commit: ExpressionCommitPort
    intents: ExpressionIntentReadPort


@dataclass(frozen=True, slots=True)
class ExpressionActionPorts:
    intents: ExpressionIntentReadPort


def bootstrap_expression_action_ports(
    intents: ExpressionIntentReadPort,
    decisions: DialogueDecisionRecordPort,
) -> ExpressionActionPorts:
    owner = PostgreSQLExpressionActionOwner(intents, decisions)
    return ExpressionActionPorts(owner)


def bootstrap_expression(
    relationships: RelationshipReadPort,
    relationship_policy: RelationshipPolicyPort,
    effect_registration: ExpressionEffectRegistrationPort,
    interaction_routes: InteractionEffectRoutePort,
    interaction_scenes: InteractionSceneTransitionPort,
    voice: ExpressionVoiceRoutePort,
    intents: ExpressionIntentReadPort,
    decisions: DialogueDecisionRecordPort,
) -> ExpressionModule:
    actions = bootstrap_expression_action_ports(intents, decisions)
    return ExpressionModule(
        commit=PostgreSQLExpressionOwner(
            relationships,
            relationship_policy,
            effect_registration,
            interaction_routes,
            interaction_scenes,
            voice,
            decisions,
        ),
        intents=actions.intents,
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
