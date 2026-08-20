from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator, AsyncIterator
from typing import cast
from uuid import uuid7

import pytest
from armi_live_voice.api import (
    AcceptedVoiceInput,
    AudioDevice,
    FastReplyDecision,
    LiveVoiceBinding,
    RecognitionEvent,
    VoiceContext,
    VoiceProviderBinding,
    VoiceProviderService,
)
from armi_live_voice.service import LiveVoiceService, _stream_speak_fragments


class FakeAudio:
    def __init__(self, log: list[str]) -> None:
        self.log = log

    def devices(self) -> tuple[AudioDevice, ...]:
        return ()

    async def capture(self) -> AsyncIterator[bytes]:
        yield b"audio"

    async def play(
        self, frames: AsyncIterator[bytes], *, on_frame_written=None
    ) -> int:
        count = 0
        async for frame in frames:
            assert frame == b"pcm"
            self.log.append("played")
            count += 1
            if on_frame_written is not None:
                await on_frame_written()
        return count

    async def close(self) -> None:
        return None


class FakeAsr:
    async def recognize(
        self, frames: AsyncIterator[bytes]
    ) -> AsyncIterator[RecognitionEvent]:
        assert await anext(frames) == b"audio"
        yield RecognitionEvent("现在几点\uff1f", True, True)


class FakeModel:
    def __init__(self, log: list[str]) -> None:
        self.log = log

    async def prepare(self) -> None:
        self.log.append("model_ready")

    async def generate(
        self, context: VoiceContext, transcript: str
    ) -> AsyncIterator[str]:
        assert context.version == "1"
        assert transcript == "现在几点\uff1f"
        yield "SPEAK\n现在是"
        yield "下午三点。"


class FakeTts:
    def __init__(self, log: list[str]) -> None:
        self.log = log

    async def prepare(self) -> None:
        self.log.append("tts_ready")

    async def close(self) -> None:
        return None

    async def synthesize(self, fragments: AsyncIterator[str]) -> AsyncIterator[bytes]:
        assert "".join([item async for item in fragments]) == "现在是下午三点。"
        self.log.append("synthesized")
        yield b"pcm"


class FakeContext:
    async def compile(self) -> VoiceContext:
        return VoiceContext("1", "context")


class FakeInputs:
    async def accept_once(self, **_: object) -> AcceptedVoiceInput:
        digest = "sha256:" + "a" * 64
        return AcceptedVoiceInput(uuid7(), uuid7(), digest, digest, True)


class FakeExpression:
    def __init__(self, log: list[str]) -> None:
        self.log = log

    async def register_fragment(self, **_: object) -> None:
        self.log.append("registered")

    async def seal(self, **_: object) -> None:
        self.log.append("sealed")


class FakeSuccessors:
    def __init__(self) -> None:
        self.appraised = asyncio.Event()

    async def enqueue_appraisal(self, accepted: AcceptedVoiceInput) -> None:
        del accepted
        self.appraised.set()

    async def run_slow(self, accepted: AcceptedVoiceInput) -> None:
        del accepted


class FakeJournal:
    async def open_session(self, **_: object) -> None:
        return None

    async def set_session_state(self, **_: object) -> None:
        return None

    async def close_session(self, **_: object) -> None:
        return None

    async def begin_turn(self, **_: object) -> None:
        return None

    async def record_transcript(self, **_: object) -> None:
        return None

    async def record_decision(
        self, *, turn_id: object, decision: FastReplyDecision
    ) -> None:
        del turn_id, decision

    async def settle_turn(self, **_: object) -> None:
        return None

    async def begin_provider_attempt(self, **_: object):
        return uuid7()

    async def mark_provider_first_result(self, **_: object) -> None:
        return None

    async def settle_provider_attempt(self, **_: object) -> None:
        return None

    async def begin_playback(self, **_: object):
        return uuid7()

    async def mark_playback_first_frame(self, **_: object) -> None:
        return None

    async def settle_playback(self, **_: object) -> None:
        return None


def _binding() -> LiveVoiceBinding:
    return LiveVoiceBinding(
        "Windows WASAPI",
        "microphone",
        "Windows WASAPI",
        "speaker",
        VoiceProviderBinding(VoiceProviderService.ASR, "volcengine", "asr"),
        VoiceProviderBinding(VoiceProviderService.LLM, "ark", "model", "model"),
        VoiceProviderBinding(VoiceProviderService.TTS, "volcengine", "tts", "voice"),
    )


@pytest.mark.asyncio
async def test_fast_speech_is_registered_before_audio_and_appraisal_is_async() -> None:
    log: list[str] = []
    successors = FakeSuccessors()
    service = LiveVoiceService(
        audio=FakeAudio(log),
        asr=FakeAsr(),
        model=FakeModel(log),
        tts=FakeTts(log),
        context=FakeContext(),
        inputs=FakeInputs(),
        expression=FakeExpression(log),
        successors=successors,
        journal=FakeJournal(),
        binding=_binding(),
    )
    await service.start()
    await asyncio.wait_for(successors.appraised.wait(), timeout=1)
    await service.stop()
    assert set(log[:2]) == {"model_ready", "tts_ready"}
    synthesized = log.index("synthesized")
    assert log[2:synthesized] == ["registered", "registered"]
    assert log[synthesized : synthesized + 2] == ["synthesized", "played"]
    assert log.count("sealed") == 1


@pytest.mark.asyncio
async def test_streaming_speech_accepts_only_trailing_whitespace_after_body() -> None:
    async def remaining() -> AsyncIterator[str]:
        yield "协力。\n"
        yield " "

    fragments = [
        fragment async for fragment in _stream_speak_fragments("齐心", remaining())
    ]

    assert "".join(fragments) == "齐心协力。"


@pytest.mark.asyncio
async def test_streaming_speech_emits_first_model_delta_without_chunk_wait() -> None:
    release = asyncio.Event()

    async def remaining() -> AsyncIterator[str]:
        yield "齐"
        await release.wait()

    fragments = cast(AsyncGenerator[str], _stream_speak_fragments("", remaining()))

    assert await asyncio.wait_for(anext(fragments), timeout=0.02) == "齐"
    await fragments.aclose()
