"""Exact-name Windows WASAPI raw PCM capture and playback."""

from __future__ import annotations

import asyncio
import importlib
from collections.abc import AsyncIterator
from typing import Any, cast

from armi_live_voice.api import AudioDevice, AudioFormat, LiveVoiceViolation


class WasapiRawAudio:
    def __init__(
        self,
        *,
        input_host_api: str,
        input_name: str,
        output_host_api: str,
        output_name: str,
        audio_format: AudioFormat | None = None,
        queue_max_frames: int = 100,
    ) -> None:
        self._input_identity = (input_host_api, input_name)
        self._output_identity = (output_host_api, output_name)
        self._format = audio_format or AudioFormat()
        self._queue_max_frames = queue_max_frames
        self._capture_stop: asyncio.Event | None = None
        self._capture_stream: Any = None
        self._playback_stream: Any = None

    @staticmethod
    def devices() -> tuple[AudioDevice, ...]:
        sd = _sounddevice()
        host_apis = sd.query_hostapis()
        devices: list[AudioDevice] = []
        for raw in sd.query_devices():
            host_api = host_apis[int(raw["hostapi"])]
            if str(host_api["name"]) != "Windows WASAPI":
                continue
            devices.append(
                AudioDevice(
                    host_api=str(host_api["name"]),
                    name=str(raw["name"]),
                    input_channels=int(raw["max_input_channels"]),
                    output_channels=int(raw["max_output_channels"]),
                    default_sample_rate=float(raw["default_samplerate"]),
                )
            )
        return tuple(devices)

    @staticmethod
    def _resolve(host_api_name: str, device_name: str, *, input_: bool) -> int:
        sd = _sounddevice()
        host_apis = sd.query_hostapis()
        matches: list[int] = []
        for index, raw in enumerate(sd.query_devices()):
            host_api = host_apis[int(raw["hostapi"])]
            channels = raw["max_input_channels" if input_ else "max_output_channels"]
            if (
                str(host_api["name"]) == host_api_name
                and str(raw["name"]) == device_name
                and int(channels) > 0
            ):
                matches.append(index)
        if len(matches) != 1:
            raise LiveVoiceViolation(
                "VOICE-DEVICE-NOT-UNIQUE",
                "configured audio device is absent or ambiguous",
            )
        return matches[0]

    async def capture(self) -> AsyncIterator[bytes]:
        sd = _sounddevice()
        loop = asyncio.get_running_loop()
        queue: asyncio.Queue[bytes | Exception] = asyncio.Queue(self._queue_max_frames)
        stop = asyncio.Event()
        self._capture_stop = stop

        def callback(indata: Any, frames: int, time: Any, status: Any) -> None:
            del frames, time
            if status:
                loop.call_soon_threadsafe(
                    _put_capture_error,
                    queue,
                    LiveVoiceViolation("VOICE-CAPTURE-FAILED", str(status)),
                )
                return
            loop.call_soon_threadsafe(_put_capture_frame, queue, bytes(indata))

        device = self._resolve(*self._input_identity, input_=True)
        stream = sd.RawInputStream(
            samplerate=self._format.sample_rate_hz,
            blocksize=self._format.frame_bytes // self._format.sample_width_bytes,
            device=device,
            channels=self._format.channels,
            dtype="int16",
            callback=callback,
        )
        self._capture_stream = stream
        stream.start()
        try:
            while not stop.is_set():
                item = await queue.get()
                if isinstance(item, Exception):
                    raise item
                yield item
        finally:
            stream.stop()
            stream.close()
            self._capture_stream = None
            self._capture_stop = None

    async def play(self, frames: AsyncIterator[bytes]) -> None:
        sd = _sounddevice()
        device = self._resolve(*self._output_identity, input_=False)
        stream = sd.RawOutputStream(
            samplerate=self._format.sample_rate_hz,
            device=device,
            channels=self._format.channels,
            dtype="int16",
        )
        self._playback_stream = stream
        stream.start()
        try:
            async for frame in frames:
                if frame:
                    await asyncio.to_thread(stream.write, frame)
        finally:
            stream.stop()
            stream.close()
            self._playback_stream = None

    async def close(self) -> None:
        if self._capture_stop is not None:
            self._capture_stop.set()
        for stream in (self._capture_stream, self._playback_stream):
            if stream is not None:
                await asyncio.to_thread(stream.abort)


def _put_capture_frame(queue: asyncio.Queue[bytes | Exception], frame: bytes) -> None:
    try:
        queue.put_nowait(frame)
    except asyncio.QueueFull:
        _put_capture_error(
            queue,
            LiveVoiceViolation("VOICE-AUDIO-BACKPRESSURE", "capture queue is full"),
        )


def _put_capture_error(
    queue: asyncio.Queue[bytes | Exception], error: Exception
) -> None:
    if queue.full():
        queue.get_nowait()
    queue.put_nowait(error)


def _sounddevice() -> Any:
    try:
        sounddevice = importlib.import_module("sounddevice")
    except (ImportError, OSError) as error:
        raise LiveVoiceViolation(
            "VOICE-AUDIO-UNAVAILABLE", "sounddevice/PortAudio is unavailable"
        ) from error
    return cast(Any, sounddevice)
