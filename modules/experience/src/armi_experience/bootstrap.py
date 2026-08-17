"""Experience module composition entry point."""

from armi_data_rights.api import DataRightsParticipant
from armi_runtime_foundation import EmptyRecoveryParticipant, RecoveryParticipant

from ._data_rights import PostgreSQLExperienceDataRightsParticipant
from ._postgresql import PostgreSQLExperienceOwner
from .api import ExperienceOwnerPort


def bootstrap_experience_owner() -> ExperienceOwnerPort:
    return PostgreSQLExperienceOwner()


def bootstrap_experience_data_rights() -> DataRightsParticipant:
    return PostgreSQLExperienceDataRightsParticipant()


def bootstrap_experience_recovery() -> RecoveryParticipant:
    return EmptyRecoveryParticipant("experience")


__all__ = (
    "bootstrap_experience_data_rights",
    "bootstrap_experience_owner",
    "bootstrap_experience_recovery",
)
