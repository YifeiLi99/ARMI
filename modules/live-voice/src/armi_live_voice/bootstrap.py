"""Local real-time voice owner composition entry points."""

from armi_data_rights.api import DataRightsParticipant
from armi_runtime_foundation import RecoveryParticipant

from ._application import PostgreSQLLiveVoiceContextRead, PostgreSQLLiveVoiceJournal
from ._data_rights import PostgreSQLLiveVoiceDataRightsParticipant
from ._recovery import LiveVoiceRecoveryParticipant
from .service import LiveVoiceService

compose_live_voice = LiveVoiceService
compose_live_voice_journal = PostgreSQLLiveVoiceJournal


def bootstrap_live_voice_context_read() -> PostgreSQLLiveVoiceContextRead:
    return PostgreSQLLiveVoiceContextRead()


def bootstrap_live_voice_data_rights() -> DataRightsParticipant:
    return PostgreSQLLiveVoiceDataRightsParticipant()


def bootstrap_live_voice_recovery() -> RecoveryParticipant:
    return LiveVoiceRecoveryParticipant()


__all__ = (
    "bootstrap_live_voice_context_read",
    "bootstrap_live_voice_data_rights",
    "bootstrap_live_voice_recovery",
    "compose_live_voice",
    "compose_live_voice_journal",
)
