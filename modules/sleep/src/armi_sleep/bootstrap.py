"""Sleep module composition entry point."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from ._application import SleepApplication
from ._commit import PostgreSQLSleepCommit
from ._maintenance import PostgreSQLMaintenanceRepository
from ._postgresql import PostgreSQLSleepRead
from .api import (
    SleepCognitionPort,
    SleepCommitPort,
    SleepMaintenancePort,
    SleepReadPort,
)


@dataclass(frozen=True, slots=True)
class SleepModule:
    read: SleepReadPort
    cognition: SleepCognitionPort
    commit: SleepCommitPort
    maintenance: SleepMaintenancePort
    _query: PostgreSQLSleepRead

    async def open(self) -> None:
        await self._query.open()

    async def close(self) -> None:
        await self._query.close()


def bootstrap_sleep(
    conninfo: str,
    *,
    expected_role: str,
    creator_party_id: UUID,
    pool_timeout_seconds: int,
) -> SleepModule:
    cognition = SleepApplication()
    query = PostgreSQLSleepRead(
        conninfo,
        expected_role=expected_role,
        creator_party_id=creator_party_id,
        pool_timeout_seconds=pool_timeout_seconds,
    )
    return SleepModule(
        query,
        cognition,
        PostgreSQLSleepCommit(cognition),
        PostgreSQLMaintenanceRepository(),
        query,
    )


def bootstrap_sleep_cognition() -> SleepCognitionPort:
    return SleepApplication()


__all__ = ("SleepModule", "bootstrap_sleep", "bootstrap_sleep_cognition")
