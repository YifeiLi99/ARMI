"""Relationship module composition entry point."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from armi_data_rights.api import DataRightsParticipant, DataRightsVisibilityPort
from armi_runtime_foundation import (
    EmptyRecoveryParticipant,
    PostgreSQLRuntimeUnitOfWorkFactory,
    RecoveryParticipant,
)

from ._application import RelationshipApplication
from ._data_rights import PostgreSQLRelationshipDataRightsParticipant
from ._postgresql import PostgreSQLRelationshipOwner
from .api import (
    RelationshipCognitionPort,
    RelationshipCommitPort,
    RelationshipPolicyPort,
    RelationshipReadPort,
)


@dataclass(frozen=True, slots=True)
class RelationshipModule:
    read: RelationshipReadPort
    cognition: RelationshipCognitionPort
    policy: RelationshipPolicyPort
    commit: RelationshipCommitPort
    data_rights: DataRightsParticipant
    _owner: PostgreSQLRelationshipOwner

    async def open(self) -> None:
        await self._owner.open()

    async def close(self) -> None:
        await self._owner.close()


def bootstrap_relationship_cognition() -> RelationshipCognitionPort:
    return RelationshipApplication()


def bootstrap_relationship_data_rights() -> DataRightsParticipant:
    return PostgreSQLRelationshipDataRightsParticipant()


def bootstrap_relationship_recovery() -> RecoveryParticipant:
    return EmptyRecoveryParticipant("relationship")


def bootstrap_relationship(
    factory: PostgreSQLRuntimeUnitOfWorkFactory,
    *,
    creator_party_id: UUID,
    visibility: DataRightsVisibilityPort,
) -> RelationshipModule:
    application = RelationshipApplication()
    owner = PostgreSQLRelationshipOwner(
        factory,
        creator_party_id=creator_party_id,
        visibility=visibility,
    )
    return RelationshipModule(
        read=owner,
        cognition=application,
        policy=application,
        commit=owner,
        data_rights=PostgreSQLRelationshipDataRightsParticipant(),
        _owner=owner,
    )


__all__ = (
    "RelationshipModule",
    "bootstrap_relationship",
    "bootstrap_relationship_cognition",
    "bootstrap_relationship_data_rights",
    "bootstrap_relationship_recovery",
)
