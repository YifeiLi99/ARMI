"""Relationship module composition entry point."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from ._application import RelationshipApplication
from ._postgresql import PostgreSQLRelationshipOwner
from .api import (
    RelationshipCognitionPort,
    RelationshipCommitPort,
    RelationshipDataRightsParticipant,
    RelationshipPolicyPort,
    RelationshipReadPort,
)


@dataclass(frozen=True, slots=True)
class RelationshipModule:
    read: RelationshipReadPort
    cognition: RelationshipCognitionPort
    policy: RelationshipPolicyPort
    commit: RelationshipCommitPort
    data_rights: RelationshipDataRightsParticipant
    _owner: PostgreSQLRelationshipOwner

    async def open(self) -> None:
        await self._owner.open()

    async def close(self) -> None:
        await self._owner.close()


def bootstrap_relationship_cognition() -> RelationshipCognitionPort:
    return RelationshipApplication()


def bootstrap_relationship(
    conninfo: str,
    *,
    expected_role: str,
    creator_party_id: UUID,
    pool_timeout_seconds: int,
) -> RelationshipModule:
    application = RelationshipApplication()
    owner = PostgreSQLRelationshipOwner(
        conninfo,
        expected_role=expected_role,
        creator_party_id=creator_party_id,
        pool_timeout_seconds=pool_timeout_seconds,
    )
    return RelationshipModule(
        read=owner,
        cognition=application,
        policy=application,
        commit=owner,
        data_rights=owner,
        _owner=owner,
    )


__all__ = (
    "RelationshipModule",
    "bootstrap_relationship",
    "bootstrap_relationship_cognition",
)
