"""Subject-state module composition entry point."""

from dataclasses import dataclass

from ._admin import PostgreSQLSubjectStateAdmin
from ._application import SubjectStateApplication
from ._postgresql import PostgreSQLSubjectStateOwner, probe_subject_state_counts
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


def bootstrap_subject_state_admin_correction() -> SubjectStateAdminCorrectionPort:
    return PostgreSQLSubjectStateAdmin()


def bootstrap_subject_state_admin_read(
    conninfo: str, *, expected_role: str
) -> SubjectStateAdminReadPort:
    return PostgreSQLSubjectStateAdmin(conninfo, expected_role=expected_role)


__all__ = (
    "SubjectStateModule",
    "bootstrap_subject_state",
    "bootstrap_subject_state_admin_correction",
    "bootstrap_subject_state_admin_read",
    "probe_subject_state_counts",
)
