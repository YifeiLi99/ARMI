import asyncio
from datetime import UTC, datetime, timedelta
from uuid import uuid7

from armi_live_vision.api import (
    CameraDevice,
    CameraFrame,
    ObservationStatus,
    ObservationTrigger,
    VisualObservation,
)
from armi_live_vision.service import LiveVisionService


class FakeCamera:
    def __init__(self, device: CameraDevice) -> None:
        self.device = device
        self.open_count = 0
        self.closed = 0
        self.frame_no = 0
        self.fail_next = False
        self.available = True

    def devices(self) -> tuple[CameraDevice, ...]:
        return (self.device,) if self.available else ()

    async def open(self, device, format) -> None:
        assert device == self.device
        assert (format.width, format.height, format.fps) == (1280, 720, 5)
        self.open_count += 1

    async def next_frame(self) -> CameraFrame:
        await asyncio.sleep(0.001)
        if self.fail_next:
            self.fail_next = False
            raise RuntimeError("disconnected")
        self.frame_no += 1
        return CameraFrame(
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

    async def open_session(self) -> None:
        self.open_count += 1

    async def close_session(self, *, error_code: str | None = None) -> None:
        self.closes.append(error_code)

    async def observe(self, *, trigger, frames, change_score) -> VisualObservation:
        assert 1 <= len(frames) <= 4
        self.triggers.append(trigger)
        return VisualObservation(
            uuid7(),
            trigger,
            ObservationStatus.COMPLETED,
            datetime.now(UTC),
            change_score,
            "fake scene",
        )


def _service(camera: FakeCamera, sink: FakeSink) -> LiveVisionService:
    return LiveVisionService(
        camera=camera,
        sink=sink,
        device=camera.device,
        reconnect=timedelta(milliseconds=2),
        warmup=timedelta(milliseconds=5),
        selection_interval=timedelta(milliseconds=2),
    )


def test_start_observes_once_and_manual_observation_reuses_running_capture() -> None:
    async def scenario() -> None:
        device = CameraDevice("USB Camera", "path", "location")
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
        device = CameraDevice("USB Camera", "path", "location")
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
            assert "VISION-CAMERA-DISCONNECTED" in sink.closes
        finally:
            await service.stop()

    asyncio.run(scenario())


def test_missing_configured_device_is_retried_without_switching_identity() -> None:
    async def scenario() -> None:
        device = CameraDevice("USB Camera", "path", "location")
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
