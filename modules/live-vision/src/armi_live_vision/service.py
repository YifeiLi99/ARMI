"""The process-local camera lifecycle; durable observation belongs to the sink."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

from .api import (
    CameraDevice,
    CameraDevicePort,
    CameraFormat,
    CameraFrame,
    LatestFrameBuffer,
    LiveVisionState,
    LiveVisionStatus,
    LiveVisionViolation,
    ObservationBudget,
    ObservationTrigger,
    StableSceneChangeDetector,
    TriggerCoalescer,
    VisualObservation,
    VisualObservationSinkPort,
)


class LiveVisionService:
    """Capture continuously in memory and serialize visual-model observations."""

    def __init__(
        self,
        *,
        camera: CameraDevicePort,
        sink: VisualObservationSinkPort,
        device: CameraDevice,
        format: CameraFormat | None = None,
        hourly_limit: int = 12,
        automatic_cooldown: timedelta = timedelta(seconds=30),
        periodic_refresh: timedelta = timedelta(minutes=30),
        reconnect: timedelta = timedelta(seconds=30),
        change_threshold: float = 0.18,
        stable_change_samples: int = 3,
        warmup: timedelta = timedelta(seconds=2),
        selection_interval: timedelta = timedelta(milliseconds=500),
    ) -> None:
        self._camera = camera
        self._sink = sink
        self._device = device
        self._format = CameraFormat() if format is None else format
        self._periodic_refresh = periodic_refresh
        self._reconnect = reconnect
        self._hourly_limit = hourly_limit
        self._warmup = warmup
        self._selection_interval = selection_interval
        self._budget = ObservationBudget(
            hourly_limit=hourly_limit,
            automatic_cooldown=automatic_cooldown,
        )
        self._coalescer = TriggerCoalescer()
        self._buffer = LatestFrameBuffer()
        self._state = LiveVisionState.IDLE
        self._expected = False
        self._session_open = False
        self._capture_task: asyncio.Task[None] | None = None
        self._last_observation: VisualObservation | None = None
        self._reason: str | None = None
        self._detector = StableSceneChangeDetector(
            threshold=change_threshold,
            required_samples=stable_change_samples,
        )
        self._baseline_thumbnail: bytes | None = None
        self._last_sample_at: datetime | None = None
        self._last_auto_at: datetime | None = None
        self._observation_task: asyncio.Task[VisualObservation | None] | None = None
        self._observation_baseline: CameraFrame | None = None

    async def start(self) -> LiveVisionStatus:
        if self._expected:
            return self.status()
        self._expected = True
        self._state = LiveVisionState.STARTING
        try:
            await self._connect_exact()
            self._state = LiveVisionState.OBSERVING
            self._reason = None
            self._capture_task = asyncio.create_task(self._capture_loop())
            await asyncio.sleep(self._warmup.total_seconds())
            if self._buffer.latest() is not None:
                await self._request(ObservationTrigger.INITIAL)
        except Exception as error:
            task, self._capture_task = self._capture_task, None
            if task is not None:
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
            await self._camera.close()
            if self._session_open:
                await self._sink.close_session(
                    error_code=getattr(error, "code", "VISION-CAMERA-UNAVAILABLE")
                )
                self._session_open = False
            self._state = LiveVisionState.UNAVAILABLE
            self._reason = getattr(error, "code", "VISION-CAMERA-UNAVAILABLE")
            if self._expected:
                self._capture_task = asyncio.create_task(self._capture_loop())
        return self.status()

    async def stop(self) -> LiveVisionStatus:
        self._expected = False
        self._state = LiveVisionState.STOPPING
        task, self._capture_task = self._capture_task, None
        if task is not None:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        await self._camera.close()
        if self._session_open:
            await self._sink.close_session()
            self._session_open = False
        if self._observation_task is not None:
            self._observation_task.cancel()
            await asyncio.gather(self._observation_task, return_exceptions=True)
            self._observation_task = None
        self._buffer.clear()
        self._state = LiveVisionState.IDLE
        return self.status()

    async def observe(self) -> VisualObservation:
        result = await self._request(ObservationTrigger.MANUAL)
        if result is None:
            raise LiveVisionViolation(
                "VISION-OBSERVATION-PENDING", "manual observation was coalesced"
            )
        return result

    async def _capture_loop(self) -> None:
        while self._expected:
            if not self._session_open:
                await asyncio.sleep(self._reconnect.total_seconds())
                try:
                    await self._connect_exact()
                    self._state = LiveVisionState.OBSERVING
                    self._reason = None
                except asyncio.CancelledError:
                    raise
                except Exception as error:
                    self._state = LiveVisionState.UNAVAILABLE
                    self._reason = getattr(error, "code", "VISION-DEVICE-UNAVAILABLE")
                    await self._camera.close()
                    continue
            try:
                frame = await self._camera.next_frame()
                self._buffer.put(frame)
                self._state = LiveVisionState.OBSERVING
                self._reason = None
                self._consider_automatic(frame)
            except asyncio.CancelledError:
                raise
            except Exception as error:
                self._state = LiveVisionState.DEGRADED
                self._reason = getattr(error, "code", "VISION-CAMERA-DISCONNECTED")
                await self._camera.close()
                if self._session_open:
                    await self._sink.close_session(error_code=self._reason)
                    self._session_open = False

    async def _connect_exact(self) -> None:
        exact = tuple(
            item
            for item in self._camera.devices()
            if item.device_path == self._device.device_path
            and item.usb_location_id == self._device.usb_location_id
        )
        if len(exact) != 1:
            raise LiveVisionViolation(
                "VISION-DEVICE-UNAVAILABLE", "configured camera is not present"
            )
        await self._camera.open(exact[0], self._format)
        try:
            await self._sink.open_session()
        except BaseException:
            await self._camera.close()
            raise
        self._session_open = True

    def _consider_automatic(self, frame: CameraFrame) -> None:
        now = frame.captured_at
        if (
            self._last_auto_at is not None
            and now - self._last_auto_at >= self._periodic_refresh
        ):
            self._schedule(ObservationTrigger.PERIODIC_REFRESH)
            return
        if not frame.grayscale_thumbnail:
            return
        if self._last_sample_at is not None and now - self._last_sample_at < timedelta(
            seconds=0.5
        ):
            return
        self._last_sample_at = now
        if self._baseline_thumbnail is None:
            self._baseline_thumbnail = frame.grayscale_thumbnail
            return
        score = StableSceneChangeDetector.difference(
            self._baseline_thumbnail, frame.grayscale_thumbnail
        )
        if self._detector.sample(score):
            self._baseline_thumbnail = frame.grayscale_thumbnail
            self._schedule(ObservationTrigger.SCENE_CHANGE, score)

    def _schedule(
        self, trigger: ObservationTrigger, score: float | None = None
    ) -> None:
        if self._observation_task is None or self._observation_task.done():
            self._observation_task = asyncio.create_task(
                self._run_scheduled(trigger, score)
            )
        else:
            self._coalescer.request(trigger, score)

    async def _run_scheduled(
        self, trigger: ObservationTrigger, score: float | None
    ) -> VisualObservation | None:
        try:
            return await self._request(trigger, score)
        except LiveVisionViolation as error:
            self._reason = error.code
            return None

    async def _request(
        self, trigger: ObservationTrigger, change_score: float | None = None
    ) -> VisualObservation | None:
        now = datetime.now(UTC)
        if not self._budget.allow(trigger, now):
            raise LiveVisionViolation(
                "VISION-OBSERVATION-BUDGET", "observation is rate limited"
            )
        if not self._coalescer.request(trigger, change_score):
            return None
        current_trigger, current_score = trigger, change_score
        result: VisualObservation | None = None
        try:
            while True:
                self._budget.record(current_trigger, datetime.now(UTC))
                frames = await self._select_frames()
                result = await self._sink.observe(
                    trigger=current_trigger, frames=frames, change_score=current_score
                )
                self._last_observation = result
                if frames:
                    self._observation_baseline = frames[-1]
                if current_trigger is not ObservationTrigger.MANUAL:
                    self._last_auto_at = datetime.now(UTC)
                pending = self._coalescer.settle()
                if pending is None:
                    return result
                current_trigger, current_score = pending
        except BaseException:
            self._coalescer.discard()
            raise

    async def _select_frames(self) -> tuple[CameraFrame, ...]:
        frames: list[CameraFrame] = []
        for index in range(3):
            frame = self._buffer.latest()
            if frame is None:
                raise LiveVisionViolation(
                    "VISION-FRAME-UNAVAILABLE", "no current frame"
                )
            if not frames or frame.captured_at != frames[-1].captured_at:
                frames.append(frame)
            if index < 2:
                await asyncio.sleep(self._selection_interval.total_seconds())
        baseline = self._observation_baseline
        if baseline is not None and all(
            item.captured_at != baseline.captured_at for item in frames
        ):
            frames.append(baseline)
        return tuple(frames[:4])

    def status(self) -> LiveVisionStatus:
        frame = self._buffer.latest()
        return LiveVisionStatus(
            state=self._state,
            expected_running=self._expected,
            device=self._device,
            last_frame_at=None if frame is None else frame.captured_at,
            last_observation=self._last_observation,
            observations_last_hour=self._budget.used(datetime.now(UTC)),
            hourly_limit=self._hourly_limit,
            reason_code=self._reason,
        )

    def preview(self) -> bytes | None:
        frame = self._buffer.latest()
        if frame is None:
            return None
        return frame.preview_jpeg or frame.jpeg


__all__ = ("LiveVisionService",)
