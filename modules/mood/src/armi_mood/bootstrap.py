"""Mood module composition entry point."""

from dataclasses import dataclass

from ._admin import PostgreSQLMoodAdmin
from ._application import MoodApplication
from ._postgresql import PostgreSQLMoodOwner
from .api import (
    MoodAdminCorrectionPort,
    MoodAdminReadPort,
    MoodBirthPort,
    MoodCognitionPort,
    MoodCommitPort,
    MoodReadPort,
)


@dataclass(frozen=True, slots=True)
class MoodModule:
    read: MoodReadPort
    cognition: MoodCognitionPort
    commit: MoodCommitPort
    birth: MoodBirthPort
    _owner: PostgreSQLMoodOwner

    async def open(self) -> None:
        await self._owner.open()

    async def close(self) -> None:
        await self._owner.close()


def bootstrap_mood() -> MoodModule:
    application = MoodApplication()
    owner = PostgreSQLMoodOwner(application)
    return MoodModule(owner, application, owner, owner, owner)


def bootstrap_mood_admin_correction() -> MoodAdminCorrectionPort:
    return PostgreSQLMoodAdmin()


def bootstrap_mood_admin_read(
    conninfo: str, *, expected_role: str
) -> MoodAdminReadPort:
    return PostgreSQLMoodAdmin(conninfo, expected_role=expected_role)


__all__ = (
    "MoodModule",
    "bootstrap_mood",
    "bootstrap_mood_admin_correction",
    "bootstrap_mood_admin_read",
)
