"""Activity module composition entry point."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from ._application import ActivityApplication
from ._commit import PostgreSQLActivityCommit
from ._postgresql import PostgreSQLActivityRead
from .api import (
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
    conninfo: str,
    *,
    expected_role: str,
    creator_party_id: UUID,
    pool_timeout_seconds: int,
    focus: ActivityFocusReadPort,
) -> ActivityModule:
    query = PostgreSQLActivityRead(
        conninfo,
        expected_role=expected_role,
        creator_party_id=creator_party_id,
        pool_timeout_seconds=pool_timeout_seconds,
        focus=focus,
    )
    cognition = ActivityApplication()
    return ActivityModule(query, cognition, PostgreSQLActivityCommit(cognition), query)


def bootstrap_activity_cognition() -> ActivityCognitionPort:
    return ActivityApplication()


__all__ = ("ActivityModule", "bootstrap_activity", "bootstrap_activity_cognition")
