"""Provider-neutral contracts and deterministic live-vision mechanics."""

from __future__ import annotations

import re
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Protocol, runtime_checkable
from uuid import UUID

from armi_kernel.contracts import TraceId
from armi_runtime_foundation import (
    PostgreSQLAdminTransaction,
    PostgreSQLRuntimeUnitOfWork,
)


class LiveVisionViolation(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class LiveVisionState(StrEnum):
    IDLE = "idle"
    STARTING = "starting"
    OBSERVING = "observing"
    DEGRADED = "degraded"
    UNAVAILABLE = "unavailable"
    STOPPING = "stopping"


class VisualSourceKind(StrEnum):
    CAMERA = "camera"
    SCREEN = "screen"


class ObservationOriginKind(StrEnum):
    AUTOMATIC = "automatic"
    CREATOR = "creator"
    SUBJECT = "subject"


class ObservationTrigger(StrEnum):
    INITIAL = "initial"
    SCENE_CHANGE = "scene_change"
    PERIODIC_REFRESH = "periodic_refresh"
    MANUAL = "manual"
    SUBJECT_REQUEST = "subject_request"


class ObservationStatus(StrEnum):
    CAPTURE_PENDING = "capture_pending"
    CAPTURING = "capturing"
    REGISTERED = "registered"
    RECOGNIZING = "recognizing"
    COMPLETED = "completed"
    FAILED = "failed"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class CameraSourceIdentity:
    name: str
    device_path: str
    usb_location_id: str
    backend: str = "DSHOW"

    def __post_init__(self) -> None:
        if not self.name.strip() or not self.device_path.strip():
            raise LiveVisionViolation(
                "VISION-DEVICE-IDENTITY", "camera identity is incomplete"
            )
        if not self.usb_location_id.strip() or self.backend != "DSHOW":
            raise LiveVisionViolation(
                "VISION-DEVICE-IDENTITY",
                "camera must be an exact DirectShow USB device",
            )


@dataclass(frozen=True, slots=True)
class ScreenSourceIdentity:
    source_device_name: str
    monitor_device_path: str
    edid_name: str
    width: int
    height: int

    def __post_init__(self) -> None:
        if (
            not self.source_device_name.strip()
            or not self.monitor_device_path.strip()
            or not self.edid_name.strip()
            or self.width <= 0
            or self.height <= 0
        ):
            raise LiveVisionViolation(
                "VISION-SOURCE-IDENTITY", "screen identity is incomplete"
            )


VisualSourceIdentity = CameraSourceIdentity | ScreenSourceIdentity


@dataclass(frozen=True, slots=True)
class VisualCaptureFormat:
    width: int = 1280
    height: int = 720
    fps: float = 5.0

    def __post_init__(self) -> None:
        if self.width <= 0 or self.height <= 0 or self.fps <= 0:
            raise LiveVisionViolation("VISION-CAPTURE-FORMAT", "invalid visual format")


@dataclass(frozen=True, slots=True)
class VisualFrame:
    captured_at: datetime
    jpeg: bytes
    width: int
    height: int
    grayscale_thumbnail: bytes = b""
    preview_jpeg: bytes = b""

    def __post_init__(self) -> None:
        if not self.jpeg or self.width <= 0 or self.height <= 0:
            raise LiveVisionViolation("VISION-FRAME-INVALID", "visual frame is invalid")


@dataclass(frozen=True, slots=True)
class VisualObservation:
    observation_id: UUID
    source_kind: VisualSourceKind
    origin_kind: ObservationOriginKind
    trigger: ObservationTrigger
    status: ObservationStatus
    registered_at: datetime
    change_score: float | None = None
    summary: str | None = None
    error_code: str | None = None
    origin_episode_id: UUID | None = None
    origin_scene_id: UUID | None = None


@dataclass(frozen=True, slots=True)
class VisualObservationRequestDraft:
    proposal_ref: str
    atomic_group_ref: str
    basis_ordinals: tuple[int, ...]
    source_kind: VisualSourceKind

    def __post_init__(self) -> None:
        if (
            re.fullmatch(r"proposal:[1-9][0-9]{0,2}", self.proposal_ref) is None
            or re.fullmatch(r"group:[1-9][0-9]{0,2}", self.atomic_group_ref) is None
            or not 1 <= len(self.basis_ordinals) <= 8
            or len(set(self.basis_ordinals)) != len(self.basis_ordinals)
            or any(
                type(item) is not int or not 1 <= item <= 999
                for item in self.basis_ordinals
            )
            or type(self.source_kind) is not VisualSourceKind
        ):
            raise LiveVisionViolation(
                "VISION-SUBJECT-REQUEST", "visual request is invalid"
            )


@dataclass(frozen=True, slots=True)
class VisualObservationCommitContext:
    validation_id: UUID
    episode_id: UUID
    opportunity_id: UUID
    subject_id: UUID
    scene_id: UUID | None
    creator_party_id: UUID | None
    trace_id: TraceId


@runtime_checkable
class VisualObservationCommitPort(Protocol):
    async def commit_requests(
        self,
        unit_of_work: PostgreSQLRuntimeUnitOfWork,
        *,
        context: VisualObservationCommitContext,
        commit_id: UUID,
        requests: tuple[VisualObservationRequestDraft, ...],
    ) -> None: ...


@dataclass(frozen=True, slots=True)
class LiveVisionStatus:
    source_kind: VisualSourceKind
    state: LiveVisionState
    expected_running: bool
    source: VisualSourceIdentity | None
    last_frame_at: datetime | None
    last_observation: VisualObservation | None
    observations_last_hour: int
    hourly_limit: int
    reason_code: str | None = None


class LatestFrameBuffer:
    """A volatile single-frame buffer; replaced frames are immediately released."""

    def __init__(self) -> None:
        self._frame: VisualFrame | None = None

    def put(self, frame: VisualFrame) -> None:
        self._frame = frame

    def latest(self) -> VisualFrame | None:
        return self._frame

    def clear(self) -> None:
        self._frame = None


class StableSceneChangeDetector:
    """Require consecutive samples above the threshold before a scene change."""

    def __init__(self, *, threshold: float, required_samples: int = 3) -> None:
        if not 0 < threshold <= 1 or required_samples <= 0:
            raise ValueError("invalid scene change detector settings")
        self._threshold = threshold
        self._required = required_samples
        self._consecutive = 0

    def sample(self, score: float) -> bool:
        if not 0 <= score <= 1:
            raise ValueError("change score must be between zero and one")
        self._consecutive = self._consecutive + 1 if score >= self._threshold else 0
        if self._consecutive < self._required:
            return False
        self._consecutive = 0
        return True

    @staticmethod
    def difference(previous: bytes, current: bytes) -> float:
        if not previous or len(previous) != len(current):
            raise ValueError("thumbnail shapes differ")
        return sum(
            abs(left - right) for left, right in zip(previous, current, strict=True)
        ) / (255 * len(current))


class ObservationBudget:
    """Rolling model-call budget plus the automatic-observation cooldown."""

    def __init__(
        self,
        *,
        hourly_limit: int = 12,
        automatic_cooldown: timedelta = timedelta(seconds=30),
    ) -> None:
        if hourly_limit <= 0 or automatic_cooldown.total_seconds() < 0:
            raise ValueError("invalid observation budget")
        self._limit = hourly_limit
        self._cooldown = automatic_cooldown
        self._started: deque[datetime] = deque()
        self._last_automatic: datetime | None = None

    def allow(self, trigger: ObservationTrigger, now: datetime) -> bool:
        boundary = now - timedelta(hours=1)
        while self._started and self._started[0] <= boundary:
            self._started.popleft()
        if len(self._started) >= self._limit:
            return False
        return not (
            trigger
            not in {ObservationTrigger.MANUAL, ObservationTrigger.SUBJECT_REQUEST}
            and self._last_automatic is not None
            and now - self._last_automatic < self._cooldown
        )

    def record(self, trigger: ObservationTrigger, now: datetime) -> None:
        if not self.allow(trigger, now):
            raise LiveVisionViolation(
                "VISION-OBSERVATION-BUDGET", "observation is rate limited"
            )
        self._started.append(now)
        if trigger not in {
            ObservationTrigger.MANUAL,
            ObservationTrigger.SUBJECT_REQUEST,
        }:
            self._last_automatic = now

    def used(self, now: datetime) -> int:
        self.allow(ObservationTrigger.MANUAL, now)
        return len(self._started)


class TriggerCoalescer:
    """Keep only the latest trigger while one recognition is in flight."""

    def __init__(self) -> None:
        self._in_flight = False
        self._pending: tuple[ObservationTrigger, float | None] | None = None

    def request(
        self, trigger: ObservationTrigger, change_score: float | None = None
    ) -> bool:
        if not self._in_flight:
            self._in_flight = True
            return True
        self._pending = (trigger, change_score)
        return False

    def settle(self) -> tuple[ObservationTrigger, float | None] | None:
        pending = self._pending
        self._pending = None
        self._in_flight = pending is not None
        return pending

    def discard(self) -> None:
        self._pending = None
        self._in_flight = False


@runtime_checkable
class VisualSourcePort(Protocol):
    def sources(self) -> tuple[VisualSourceIdentity, ...]: ...
    async def open(
        self, source: VisualSourceIdentity, format: VisualCaptureFormat
    ) -> None: ...
    async def next_frame(self) -> VisualFrame: ...
    async def close(self) -> None: ...


@runtime_checkable
class LiveVisionRuntimePort(Protocol):
    async def start(self) -> LiveVisionStatus: ...
    async def stop(self) -> LiveVisionStatus: ...
    async def observe(
        self,
        *,
        trigger: ObservationTrigger = ObservationTrigger.MANUAL,
        origin_kind: ObservationOriginKind = ObservationOriginKind.CREATOR,
        idempotency_key: str | None = None,
        origin_episode_id: UUID | None = None,
        origin_scene_id: UUID | None = None,
    ) -> VisualObservation: ...
    def status(self) -> LiveVisionStatus: ...
    def preview(self) -> bytes | None: ...


@runtime_checkable
class VisualObservationSinkPort(Protocol):
    async def open_session(self) -> None: ...
    async def close_session(self, *, error_code: str | None = None) -> None: ...

    async def settle_interrupted_observations(self, *, error_code: str) -> None: ...

    async def get_observation_by_key(
        self, idempotency_key: str
    ) -> VisualObservation | None: ...

    async def observe(
        self,
        *,
        trigger: ObservationTrigger,
        frames: tuple[VisualFrame, ...],
        change_score: float | None,
        origin_kind: ObservationOriginKind,
        idempotency_key: str | None = None,
        origin_episode_id: UUID | None = None,
        origin_scene_id: UUID | None = None,
    ) -> VisualObservation: ...


@runtime_checkable
class LiveVisionAdminPort(Protocol):
    def artifact_reference_count(
        self, transaction: PostgreSQLAdminTransaction, *, artifact_id: UUID
    ) -> int: ...


__all__ = (
    "CameraSourceIdentity",
    "LatestFrameBuffer",
    "LiveVisionAdminPort",
    "LiveVisionRuntimePort",
    "LiveVisionState",
    "LiveVisionStatus",
    "LiveVisionViolation",
    "ObservationBudget",
    "ObservationOriginKind",
    "ObservationStatus",
    "ObservationTrigger",
    "ScreenSourceIdentity",
    "StableSceneChangeDetector",
    "TriggerCoalescer",
    "VisualCaptureFormat",
    "VisualFrame",
    "VisualObservation",
    "VisualObservationCommitContext",
    "VisualObservationCommitPort",
    "VisualObservationRequestDraft",
    "VisualObservationSinkPort",
    "VisualSourceIdentity",
    "VisualSourceKind",
    "VisualSourcePort",
)
