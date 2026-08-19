"""Live-vision owner composition entry points."""

from armi_data_rights.api import DataRightsParticipant
from armi_runtime_foundation import RecoveryParticipant

from ._admin import PostgreSQLLiveVisionAdmin
from ._application import DurableVisualObservationCoordinator
from ._data_rights import PostgreSQLLiveVisionDataRightsParticipant
from ._recovery import LiveVisionRecoveryParticipant
from .service import LiveVisionService

compose_live_vision = LiveVisionService
compose_visual_observation_sink = DurableVisualObservationCoordinator


def bootstrap_live_vision_admin() -> PostgreSQLLiveVisionAdmin:
    return PostgreSQLLiveVisionAdmin()


def bootstrap_live_vision_data_rights() -> DataRightsParticipant:
    return PostgreSQLLiveVisionDataRightsParticipant()


def bootstrap_live_vision_recovery() -> RecoveryParticipant:
    return LiveVisionRecoveryParticipant()


__all__ = (
    "bootstrap_live_vision_admin",
    "bootstrap_live_vision_data_rights",
    "bootstrap_live_vision_recovery",
    "compose_live_vision",
    "compose_visual_observation_sink",
)
