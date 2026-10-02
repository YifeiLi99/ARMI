from __future__ import annotations

from collections.abc import AsyncGenerator
from types import SimpleNamespace
from typing import cast

import armi_runtime.adapters.voice.wasapi as wasapi_module
import pytest
from armi_runtime.adapters.voice.wasapi import WasapiRawAudio


@pytest.mark.asyncio
@pytest.mark.parametrize("direction", ("capture", "playback"))
async def test_audio_start_failure_closes_the_opened_stream(
    monkeypatch: pytest.MonkeyPatch, direction: str
) -> None:
    opened: list[Stream] = []

    class Stream:
        def __init__(self, **_options: object) -> None:
            self.closed = False
            self.stopped = False
            opened.append(self)

        def start(self) -> None:
            raise RuntimeError("audio device became unavailable after stream opened")

        def stop(self) -> None:
            self.stopped = True

        def close(self) -> None:
            self.closed = True

    sounddevice = SimpleNamespace(
        query_hostapis=lambda: [{"name": "Windows WASAPI"}],
        query_devices=lambda: [
            {
                "hostapi": 0,
                "name": "test-device",
                "max_input_channels": 1,
                "max_output_channels": 1,
            }
        ],
        RawInputStream=Stream,
        RawOutputStream=Stream,
    )
    monkeypatch.setattr(wasapi_module, "_sounddevice", lambda: sounddevice)
    audio = WasapiRawAudio(
        input_host_api="Windows WASAPI",
        input_name="test-device",
        output_host_api="Windows WASAPI",
        output_name="test-device",
    )

    async def frames() -> AsyncGenerator[bytes]:
        yield b"pcm"

    capture = cast(AsyncGenerator[bytes], audio.capture())
    output = frames()
    try:
        with pytest.raises(RuntimeError, match="audio device became unavailable"):
            if direction == "capture":
                await anext(capture)
            else:
                await audio.play(output)
        assert len(opened) == 1
        assert opened[0].closed, "failed start leaked the opened PortAudio stream"
        assert opened[0].stopped
        assert audio._capture_stream is None
        assert audio._playback_stream is None
        assert audio._capture_stop is None
    finally:
        await capture.aclose()
        await output.aclose()
