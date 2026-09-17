"""Mind module composition entry point."""

from dataclasses import dataclass

from armi_data_rights.api import DataRightsParticipant
from armi_runtime_foundation import RecoveryParticipant

from ._admin import PostgreSQLMindAdmin
from ._application import MindApplication
from ._data_rights import PostgreSQLMindDataRightsParticipant
from ._postgresql import PostgreSQLMindOwner
from ._recovery import MindRecoveryParticipant
from .api import (
    MindAdminContentPort,
    MindAdminCorrectionPort,
    MindAdminReadPort,
    MindBirthPort,
    MindCognitionPort,
    MindCommitPort,
    MindReadPort,
)


@dataclass(frozen=True, slots=True)
class MindModule:
    read: MindReadPort
    cognition: MindCognitionPort
    commit: MindCommitPort
    birth: MindBirthPort
    _owner: PostgreSQLMindOwner

    async def open(self) -> None:
        await self._owner.open()

    async def close(self) -> None:
        await self._owner.close()


def bootstrap_mind() -> MindModule:
    application = MindApplication()
    owner = PostgreSQLMindOwner()
    return MindModule(owner, application, owner, owner, owner)


def bootstrap_mind_cognition() -> MindCognitionPort:
    return MindApplication()


def bootstrap_mind_admin_correction() -> MindAdminCorrectionPort:
    return PostgreSQLMindAdmin()


def bootstrap_mind_admin_read() -> MindAdminReadPort:
    return PostgreSQLMindAdmin()


def bootstrap_mind_data_rights() -> DataRightsParticipant:
    return PostgreSQLMindDataRightsParticipant()


def bootstrap_mind_recovery(read: MindReadPort) -> RecoveryParticipant:
    return MindRecoveryParticipant(read)


def bootstrap_mind_admin_content() -> MindAdminContentPort:
    return PostgreSQLMindAdmin()


__all__ = (
    "MindModule",
    "bootstrap_mind",
    "bootstrap_mind_admin_content",
    "bootstrap_mind_admin_correction",
    "bootstrap_mind_admin_read",
    "bootstrap_mind_cognition",
    "bootstrap_mind_data_rights",
    "bootstrap_mind_recovery",
)
