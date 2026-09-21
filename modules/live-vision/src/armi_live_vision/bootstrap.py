"""Live-vision owner composition entry points."""

from armi_data_rights.api import DataRightsParticipant
from armi_runtime_foundation import RecoveryParticipant

from ._admin import PostgreSQLLiveVisionAdmin
from ._application import (
    DurableVisualObservationCoordinator,
    LiveVisionRetentionCoordinator,
    VisualCaptureRouter,
)
from ._commit import PostgreSQLVisualObservationCommit
from ._data_rights import PostgreSQLLiveVisionDataRightsParticipant
from ._origin import PostgreSQLVisualOriginRead
from ._recovery import LiveVisionRecoveryParticipant
from .api import VisualOriginReadPort
from .service import LiveVisionService

compose_live_vision = LiveVisionService
compose_visual_observation_sink = DurableVisualObservationCoordinator
compose_live_vision_retention = LiveVisionRetentionCoordinator
compose_visual_capture_router = VisualCaptureRouter


def bootstrap_visual_origin_read() -> VisualOriginReadPort:
    return PostgreSQLVisualOriginRead()


def bootstrap_live_vision_admin() -> PostgreSQLLiveVisionAdmin:
    return PostgreSQLLiveVisionAdmin()


def bootstrap_live_vision_commit() -> PostgreSQLVisualObservationCommit:
    return PostgreSQLVisualObservationCommit()


def bootstrap_live_vision_data_rights() -> DataRightsParticipant:
    return PostgreSQLLiveVisionDataRightsParticipant()


def bootstrap_live_vision_recovery() -> RecoveryParticipant:
    return LiveVisionRecoveryParticipant()


__all__ = (
    "bootstrap_live_vision_admin",
    "bootstrap_live_vision_commit",
    "bootstrap_live_vision_data_rights",
    "bootstrap_live_vision_recovery",
    "bootstrap_visual_origin_read",
    "compose_live_vision",
    "compose_live_vision_retention",
    "compose_visual_capture_router",
    "compose_visual_observation_sink",
)
