import asyncio
from datetime import UTC, datetime, timedelta
from uuid import uuid7

from armi_live_vision.api import (
    CameraSourceIdentity,
    ObservationStatus,
    ObservationTrigger,
    VisualFrame,
    VisualObservation,
    VisualSourceKind,
)
from armi_live_vision.service import LiveVisionService


class FakeCamera:
    def __init__(self, device: CameraSourceIdentity) -> None:
        self.device = device
        self.open_count = 0
        self.closed = 0
        self.frame_no = 0
        self.fail_next = False
        self.available = True

    def sources(self):
        return (self.device,) if self.available else ()

    async def open(self, source, format) -> None:
        assert source == self.device
        assert (format.width, format.height, format.fps) == (1280, 720, 5)
        self.open_count += 1

    async def next_frame(self) -> VisualFrame:
        await asyncio.sleep(0.001)
        if self.fail_next:
            self.fail_next = False
            raise RuntimeError("disconnected")
        self.frame_no += 1
        return VisualFrame(
            datetime.now(UTC),
            f"jpeg-{self.frame_no}".encode(),
            1280,
            720,
            bytes(160 * 90),
            b"preview",
        )

    async def close(self) -> None:
        self.closed += 1


class FakeSink:
    def __init__(self) -> None:
        self.open_count = 0
        self.closes: list[str | None] = []
        self.triggers: list[ObservationTrigger] = []
        self.interruptions: list[str] = []
        self.fail_observation = False
        self.by_key: dict[str, VisualObservation] = {}

    async def open_session(self) -> None:
        self.open_count += 1

    async def close_session(self, *, error_code: str | None = None) -> None:
        self.closes.append(error_code)

    async def settle_interrupted_observations(self, *, error_code: str) -> None:
        self.interruptions.append(error_code)

    async def get_observation_by_key(
        self, idempotency_key: str
    ) -> VisualObservation | None:
        return self.by_key.get(idempotency_key)

    async def observe(
        self,
        *,
        trigger,
        frames,
        change_score,
        origin_kind,
        idempotency_key=None,
        origin_episode_id=None,
        origin_scene_id=None,
    ) -> VisualObservation:
        assert frames == ()
        self.triggers.append(trigger)
        if self.fail_observation:
            self.fail_observation = False
            raise RuntimeError("database unavailable")
        result = VisualObservation(
            uuid7(),
            VisualSourceKind.CAMERA,
            origin_kind,
            trigger,
            ObservationStatus.CAPTURE_PENDING,
            datetime.now(UTC),
            change_score,
            None,
        )
        if idempotency_key is not None:
            self.by_key[idempotency_key] = result
        return result


def _service(camera: FakeCamera, sink: FakeSink) -> LiveVisionService:
    return LiveVisionService(
        source_kind=VisualSourceKind.CAMERA,
        source=camera,
        sink=sink,
        identity=camera.device,
        reconnect=timedelta(milliseconds=2),
        warmup=timedelta(milliseconds=5),
        selection_interval=timedelta(milliseconds=2),
    )


def test_start_observes_once_and_manual_observation_reuses_running_capture() -> None:
    async def scenario() -> None:
        device = CameraSourceIdentity("USB Camera", "path", "location")
        camera, sink = FakeCamera(device), FakeSink()
        service = _service(camera, sink)
        try:
            assert (await service.start()).state.value == "observing"
            assert sink.triggers == [ObservationTrigger.INITIAL]
            observed = await service.observe()
            assert observed.trigger is ObservationTrigger.MANUAL
            assert camera.open_count == 1
        finally:
            await service.stop()

    asyncio.run(scenario())


def test_disconnect_closes_old_session_and_reopens_only_configured_device() -> None:
    async def scenario() -> None:
        device = CameraSourceIdentity("USB Camera", "path", "location")
        camera, sink = FakeCamera(device), FakeSink()
        service = _service(camera, sink)
        try:
            await service.start()
            camera.fail_next = True
            deadline = asyncio.get_running_loop().time() + 0.2
            while (
                camera.open_count < 2 and asyncio.get_running_loop().time() < deadline
            ):
                await asyncio.sleep(0.002)
            assert camera.open_count == 2
            assert sink.open_count == 2
            assert "VISION-SOURCE-DISCONNECTED" in sink.closes
        finally:
            await service.stop()

    asyncio.run(scenario())


def test_missing_configured_device_is_retried_without_switching_identity() -> None:
    async def scenario() -> None:
        device = CameraSourceIdentity("USB Camera", "path", "location")
        camera, sink = FakeCamera(device), FakeSink()
        camera.available = False
        service = _service(camera, sink)
        try:
            status = await service.start()
            assert status.state.value == "unavailable"
            assert status.expected_running is True
            assert camera.open_count == 0
            camera.available = True
            deadline = asyncio.get_running_loop().time() + 0.2
            while (
                camera.open_count < 1 and asyncio.get_running_loop().time() < deadline
            ):
                await asyncio.sleep(0.002)
            assert camera.open_count == 1
            assert sink.open_count == 1
            assert service.status().state.value == "observing"
        finally:
            await service.stop()

    asyncio.run(scenario())


def test_scheduled_observation_failure_is_consumed_and_degrades_service() -> None:
    async def scenario() -> None:
        device = CameraSourceIdentity("USB Camera", "path", "location")
        camera, sink = FakeCamera(device), FakeSink()
        service = _service(camera, sink)
        try:
            await service.start()
            sink.fail_observation = True
            service._schedule(ObservationTrigger.MANUAL)
            task = service._observation_task
            assert task is not None
            await task
            assert service.status().state.value == "degraded"
            assert service.status().reason_code == "VISION-OBSERVATION-FAILED"
            assert sink.interruptions[-1] == "VISION-OBSERVATION-FAILED"
        finally:
            await service.stop()

    asyncio.run(scenario())
