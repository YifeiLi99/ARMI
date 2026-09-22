"""Focus module composition entry point."""

from dataclasses import dataclass

from armi_data_rights.api import DataRightsParticipant
from armi_runtime_foundation import RecoveryParticipant

from ._admin import PostgreSQLFocusAdmin
from ._application import FocusApplication
from ._data_rights import PostgreSQLFocusDataRightsParticipant
from ._postgresql import PostgreSQLFocusOwner
from ._recovery import FocusRecoveryParticipant
from .api import (
    FocusAdminContentPort,
    FocusAdminCorrectionPort,
    FocusAdminReadPort,
    FocusBirthPort,
    FocusCognitionPort,
    FocusCommitPort,
    FocusReadPort,
)


@dataclass(frozen=True, slots=True)
class FocusModule:
    read: FocusReadPort
    cognition: FocusCognitionPort
    commit: FocusCommitPort
    birth: FocusBirthPort
    _owner: PostgreSQLFocusOwner

    async def open(self) -> None:
        await self._owner.open()

    async def close(self) -> None:
        await self._owner.close()


def bootstrap_focus() -> FocusModule:
    application = FocusApplication()
    owner = PostgreSQLFocusOwner()
    return FocusModule(owner, application, owner, owner, owner)


def bootstrap_focus_cognition() -> FocusCognitionPort:
    return FocusApplication()


def bootstrap_focus_admin_correction() -> FocusAdminCorrectionPort:
    return PostgreSQLFocusAdmin()


def bootstrap_focus_admin_read() -> FocusAdminReadPort:
    return PostgreSQLFocusAdmin()


def bootstrap_focus_data_rights() -> DataRightsParticipant:
    return PostgreSQLFocusDataRightsParticipant()


def bootstrap_focus_recovery(read: FocusReadPort) -> RecoveryParticipant:
    return FocusRecoveryParticipant(read)


def bootstrap_focus_admin_content() -> FocusAdminContentPort:
    return PostgreSQLFocusAdmin()


__all__ = (
    "FocusModule",
    "bootstrap_focus",
    "bootstrap_focus_admin_content",
    "bootstrap_focus_admin_correction",
    "bootstrap_focus_admin_read",
    "bootstrap_focus_cognition",
    "bootstrap_focus_data_rights",
    "bootstrap_focus_recovery",
)
