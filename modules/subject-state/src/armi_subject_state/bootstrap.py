"""Subject-state module composition entry point."""

from dataclasses import dataclass

from armi_runtime_foundation import RecoveryParticipant

from ._admin import PostgreSQLSubjectStateAdmin
from ._application import SubjectStateApplication
from ._postgresql import PostgreSQLSubjectStateOwner, probe_subject_state_counts
from ._recovery import SubjectStateRecoveryParticipant
from .api import (
    SubjectStateAdminCorrectionPort,
    SubjectStateAdminReadPort,
    SubjectStateBirthPort,
    SubjectStateCognitionPort,
    SubjectStateCommitPort,
    SubjectStateReadPort,
)


@dataclass(frozen=True, slots=True)
class SubjectStateModule:
    read: SubjectStateReadPort
    cognition: SubjectStateCognitionPort
    commit: SubjectStateCommitPort
    birth: SubjectStateBirthPort
    _owner: PostgreSQLSubjectStateOwner

    async def open(self) -> None:
        await self._owner.open()

    async def close(self) -> None:
        await self._owner.close()


def bootstrap_subject_state() -> SubjectStateModule:
    application = SubjectStateApplication()
    owner = PostgreSQLSubjectStateOwner(application)
    return SubjectStateModule(owner, application, owner, owner, owner)


def bootstrap_subject_state_cognition() -> SubjectStateCognitionPort:
    return SubjectStateApplication()


def bootstrap_subject_state_admin_correction() -> SubjectStateAdminCorrectionPort:
    return PostgreSQLSubjectStateAdmin()


def bootstrap_subject_state_admin_read() -> SubjectStateAdminReadPort:
    return PostgreSQLSubjectStateAdmin()


def bootstrap_subject_state_recovery(read: SubjectStateReadPort) -> RecoveryParticipant:
    return SubjectStateRecoveryParticipant(read)


__all__ = (
    "SubjectStateModule",
    "bootstrap_subject_state",
    "bootstrap_subject_state_admin_correction",
    "bootstrap_subject_state_admin_read",
    "bootstrap_subject_state_cognition",
    "bootstrap_subject_state_recovery",
    "probe_subject_state_counts",
)
