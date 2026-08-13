"""Memory module composition entry point."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from armi_runtime_foundation import PostgreSQLRuntimeUnitOfWorkFactory

from ._application import MemoryApplication
from ._postgresql import PostgreSQLMemoryOwner
from .api import (
    MemoryCognitionPort,
    MemoryCommitPort,
    MemoryDataRightsParticipant,
    MemoryProjectionPort,
    MemoryReadPort,
)


@dataclass(frozen=True, slots=True)
class MemoryModule:
    read: MemoryReadPort
    cognition: MemoryCognitionPort
    commit: MemoryCommitPort
    projection: MemoryProjectionPort
    data_rights: MemoryDataRightsParticipant
    _owner: PostgreSQLMemoryOwner

    async def open(self) -> None:
        await self._owner.open()

    async def close(self) -> None:
        await self._owner.close()


def bootstrap_memory(
    factory: PostgreSQLRuntimeUnitOfWorkFactory,
    *,
    environment_id: UUID,
    creator_party_id: UUID,
    subject_id: UUID,
    cursor_key: bytes,
) -> MemoryModule:
    application = MemoryApplication()
    owner = PostgreSQLMemoryOwner(
        factory,
        environment_id=environment_id,
        creator_party_id=creator_party_id,
        subject_id=subject_id,
        cursor_key=cursor_key,
    )
    return MemoryModule(owner, application, owner, owner, owner, owner)


def bootstrap_memory_cognition() -> MemoryCognitionPort:
    return MemoryApplication()


__all__ = ("MemoryModule", "bootstrap_memory", "bootstrap_memory_cognition")
