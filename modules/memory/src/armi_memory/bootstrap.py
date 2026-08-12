"""Memory module composition entry point."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

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
    conninfo: str,
    *,
    expected_role: str,
    environment_id: UUID,
    creator_party_id: UUID,
    cursor_key: bytes,
    pool_timeout_seconds: int,
) -> MemoryModule:
    application = MemoryApplication()
    owner = PostgreSQLMemoryOwner(
        conninfo,
        expected_role=expected_role,
        environment_id=environment_id,
        creator_party_id=creator_party_id,
        cursor_key=cursor_key,
        pool_timeout_seconds=pool_timeout_seconds,
    )
    return MemoryModule(owner, application, owner, owner, owner, owner)


__all__ = ("MemoryModule", "bootstrap_memory")
