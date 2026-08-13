"""Sleep module composition entry point."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from armi_data_rights.api import DataRightsParticipant
from armi_runtime_foundation import (
    EmptyRecoveryParticipant,
    PostgreSQLRuntimeUnitOfWorkFactory,
    RecoveryParticipant,
)

from ._application import SleepApplication
from ._commit import PostgreSQLSleepCommit
from ._data_rights import PostgreSQLSleepDataRightsParticipant
from ._maintenance import PostgreSQLMaintenanceRepository
from ._postgresql import PostgreSQLSleepRead
from .api import (
    SleepCognitionPort,
    SleepCommitPort,
    SleepMaintenancePort,
    SleepOpportunityPort,
    SleepReadPort,
    SleepRuntimeFactsPort,
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
    factory: PostgreSQLRuntimeUnitOfWorkFactory,
    *,
    subject_id: UUID,
    creator_party_id: UUID,
    runtime_facts: SleepRuntimeFactsPort,
    opportunities: SleepOpportunityPort,
) -> SleepModule:
    cognition = SleepApplication()
    query = PostgreSQLSleepRead(
        factory,
        subject_id=subject_id,
        creator_party_id=creator_party_id,
    )
    return SleepModule(
        query,
        cognition,
        PostgreSQLSleepCommit(cognition),
        PostgreSQLMaintenanceRepository(runtime_facts, opportunities),
        query,
    )


def bootstrap_sleep_cognition() -> SleepCognitionPort:
    return SleepApplication()


def bootstrap_sleep_data_rights() -> DataRightsParticipant:
    return PostgreSQLSleepDataRightsParticipant()


def bootstrap_sleep_recovery() -> RecoveryParticipant:
    return EmptyRecoveryParticipant("sleep")


__all__ = (
    "SleepModule",
    "bootstrap_sleep",
    "bootstrap_sleep_cognition",
    "bootstrap_sleep_data_rights",
    "bootstrap_sleep_recovery",
)
