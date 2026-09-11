"""Activity module composition entry point."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from armi_data_rights.api import DataRightsParticipant
from armi_runtime_foundation import (
    EmptyRecoveryParticipant,
    PostgreSQLRuntimeUnitOfWorkFactory,
    RecoveryParticipant,
)

from ._admin import PostgreSQLActivityAdmin
from ._application import ActivityApplication
from ._commit import PostgreSQLActivityCommit
from ._data_rights import PostgreSQLActivityDataRightsParticipant
from ._postgresql import PostgreSQLActivityRead
from .api import (
    ActivityAdminContentPort,
    ActivityCognitionPort,
    ActivityCommitPort,
    ActivityFocusReadPort,
    ActivityReadPort,
)


@dataclass(frozen=True, slots=True)
class ActivityModule:
    read: ActivityReadPort
    cognition: ActivityCognitionPort
    commit: ActivityCommitPort
    _query: PostgreSQLActivityRead

    async def open(self) -> None:
        await self._query.open()

    async def close(self) -> None:
        await self._query.close()


def bootstrap_activity(
    factory: PostgreSQLRuntimeUnitOfWorkFactory,
    *,
    subject_id: UUID,
    creator_party_id: UUID,
    environment_id: UUID,
    cursor_key: bytes,
    focus: ActivityFocusReadPort,
) -> ActivityModule:
    query = PostgreSQLActivityRead(
        factory,
        subject_id=subject_id,
        creator_party_id=creator_party_id,
        environment_id=environment_id,
        cursor_key=cursor_key,
        focus=focus,
    )
    cognition = ActivityApplication()
    return ActivityModule(query, cognition, PostgreSQLActivityCommit(cognition), query)


def bootstrap_activity_cognition() -> ActivityCognitionPort:
    return ActivityApplication()


def bootstrap_activity_data_rights() -> DataRightsParticipant:
    return PostgreSQLActivityDataRightsParticipant()


def bootstrap_activity_recovery() -> RecoveryParticipant:
    return EmptyRecoveryParticipant("activity")


def bootstrap_activity_admin_content() -> ActivityAdminContentPort:
    return PostgreSQLActivityAdmin()


__all__ = (
    "ActivityModule",
    "bootstrap_activity",
    "bootstrap_activity_admin_content",
    "bootstrap_activity_cognition",
    "bootstrap_activity_data_rights",
    "bootstrap_activity_recovery",
)
