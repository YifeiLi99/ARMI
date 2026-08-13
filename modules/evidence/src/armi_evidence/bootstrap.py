"""Evidence-module composition entry point."""

from __future__ import annotations

from dataclasses import dataclass

from armi_data_rights.api import DataRightsParticipant
from armi_runtime_foundation import RecoveryParticipant

from ._admin import PostgreSQLEvidenceAdmin
from ._data_rights import PostgreSQLEvidenceDataRightsParticipant
from ._postgresql import PostgreSQLEvidenceWriter
from ._recovery import EvidenceRecoveryParticipant
from .api import EvidenceAdminPort, EvidenceReadPort, EvidenceWritePort


@dataclass(frozen=True, slots=True)
class EvidenceModule:
    read: EvidenceReadPort
    write: EvidenceWritePort

    async def open(self) -> None:
        return None

    async def close(self) -> None:
        return None


def bootstrap_evidence() -> EvidenceModule:
    owner = PostgreSQLEvidenceWriter()
    return EvidenceModule(read=owner, write=owner)


def bootstrap_evidence_data_rights() -> DataRightsParticipant:
    return PostgreSQLEvidenceDataRightsParticipant()


def bootstrap_evidence_recovery() -> RecoveryParticipant:
    return EvidenceRecoveryParticipant()


def bootstrap_evidence_admin() -> EvidenceAdminPort:
    return PostgreSQLEvidenceAdmin()


__all__ = (
    "EvidenceModule",
    "bootstrap_evidence",
    "bootstrap_evidence_admin",
    "bootstrap_evidence_data_rights",
    "bootstrap_evidence_recovery",
)
