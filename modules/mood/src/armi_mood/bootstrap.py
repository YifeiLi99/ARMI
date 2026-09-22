"""Mood module composition entry point."""

from dataclasses import dataclass

from armi_data_rights.api import DataRightsParticipant
from armi_runtime_foundation import RecoveryParticipant

from ._admin import PostgreSQLMoodAdmin
from ._data_rights import PostgreSQLMoodDataRightsParticipant
from ._event_owner import MoodEventOwner
from ._psychology import DynamicsParameters
from ._read_owner import MoodReadOwner
from ._recovery import MoodRecoveryParticipant
from .api import (
    MoodAdminContentPort,
    MoodAdminCorrectionPort,
    MoodAdminReadPort,
    MoodAssessmentReadPort,
    MoodBirthPort,
    MoodReadPort,
)


@dataclass(frozen=True, slots=True)
class MoodModule:
    read: MoodReadPort
    birth: MoodBirthPort
    _owner: MoodReadOwner
    events: MoodEventOwner

    async def open(self) -> None:
        await self._owner.open()

    async def close(self) -> None:
        await self._owner.close()


def bootstrap_mood(
    parameters: DynamicsParameters | None = None, *, assessments: MoodAssessmentReadPort
) -> MoodModule:
    read = MoodReadOwner(parameters or DynamicsParameters(), assessments)
    return MoodModule(read, read, read, MoodEventOwner())


def bootstrap_mood_admin_correction() -> MoodAdminCorrectionPort:
    return PostgreSQLMoodAdmin()


def bootstrap_mood_admin_read(assessments: MoodAssessmentReadPort) -> MoodAdminReadPort:
    return PostgreSQLMoodAdmin(assessments)


def bootstrap_mood_data_rights() -> DataRightsParticipant:
    return PostgreSQLMoodDataRightsParticipant()


def bootstrap_mood_recovery(read: MoodReadPort) -> RecoveryParticipant:
    return MoodRecoveryParticipant(read)


def bootstrap_mood_admin_content() -> MoodAdminContentPort:
    return PostgreSQLMoodAdmin()


__all__ = (
    "MoodModule",
    "bootstrap_mood",
    "bootstrap_mood_admin_content",
    "bootstrap_mood_admin_correction",
    "bootstrap_mood_admin_read",
    "bootstrap_mood_data_rights",
    "bootstrap_mood_recovery",
)
