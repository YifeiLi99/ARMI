# ruff: noqa: RUF001

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from uuid import UUID, uuid7

import pytest
from armi_live_voice.api import (
    AcceptedVoiceInput,
    AudioDevice,
    LiveVoiceBinding,
    LiveVoiceViolation,
    PlaybackExtent,
    RecognitionEvent,
    VoiceProviderBinding,
    VoiceProviderService,
    VoiceTurnSnapshot,
)
from armi_live_voice.service import LiveVoiceService


class FakeAudio:
    def __init__(self, log: list[str]) -> None:
        self.log = log

    def devices(self) -> tuple[AudioDevice, ...]:
        return ()

    async def capture(self) -> AsyncIterator[bytes]:
        yield b"audio"

    async def play(self, frames: AsyncIterator[bytes], *, on_frame_written=None) -> int:
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


class FailingAudio(FakeAudio):
    def __init__(self, log: list[str], *, write_first_frame: bool) -> None:
        super().__init__(log)
        self._write_first_frame = write_first_frame

    async def play(self, frames: AsyncIterator[bytes], *, on_frame_written=None) -> int:
        assert await anext(frames) == b"pcm"
        if self._write_first_frame:
            self.log.append("played")
            if on_frame_written is not None:
                await on_frame_written()
        raise RuntimeError("speaker failed")


class FakeAsr:
    async def recognize(
        self, frames: AsyncIterator[bytes]
    ) -> AsyncIterator[RecognitionEvent]:
        assert await anext(frames) == b"audio"
        yield RecognitionEvent("现在几点？", True, True)


class FakeModelCompatibility:
    def __init__(self, log: list[str]) -> None:
        self.log = log

    async def prepare(self) -> None:
        self.log.append("model_ready")


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


class FakeInputs:
    def __init__(self) -> None:
        self.accepted = asyncio.Event()

    async def accept_once(self, **_: object) -> AcceptedVoiceInput:
        self.accepted.set()
        digest = "sha256:" + "a" * 64
        return AcceptedVoiceInput(uuid7(), uuid7(), uuid7(), digest, digest, True)


class FakeExpression:
    def __init__(self, log: list[str]) -> None:
        self.log = log

    async def register_fragment(self, **_: object) -> None:
        self.log.append("registered")

    async def seal(self, **_: object) -> None:
        self.log.append("sealed")


class FailingExpression(FakeExpression):
    async def seal(self, **_: object) -> None:
        raise RuntimeError("timeline failed")


class FakeJournal:
    def __init__(self) -> None:
        self.turn_id: UUID | None = None
        self.frames = 0

    async def recent_turn(self):
        if self.turn_id is None:
            return None
        return VoiceTurnSnapshot(
            self.turn_id, "speaking", PlaybackExtent.COMPLETE, self.frames, None
        )

    async def open_session(self, **_: object) -> None:
        pass

    async def set_session_state(self, **_: object) -> None:
        pass

    async def close_session(self, **_: object) -> None:
        pass

    async def begin_turn(self, *, turn_id: UUID, **_: object) -> None:
        self.turn_id = turn_id

    async def record_transcript(self, **_: object) -> None:
        pass

    async def settle_turn(self, **_: object) -> None:
        pass

    async def begin_provider_attempt(self, **_: object):
        return uuid7()

    async def mark_provider_dispatched(self, **_: object) -> None:
        pass

    async def mark_provider_first_result(self, **_: object) -> None:
        pass

    async def settle_provider_attempt(self, **_: object) -> None:
        pass

    async def begin_playback(self, **_: object):
        return uuid7()

    async def mark_playback_dispatched(self, **_: object) -> None:
        pass

    async def mark_playback_first_frame(self, **_: object) -> None:
        pass

    async def settle_playback(self, *, frames_written: int, **_: object) -> None:
        self.frames = frames_written


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
async def test_committed_effect_is_registered_before_audio_and_only_then_completes() -> (
    None
):
    log: list[str] = []
    inputs = FakeInputs()
    journal = FakeJournal()
    service = LiveVoiceService(
        audio=FakeAudio(log),
        asr=FakeAsr(),
        model=FakeModelCompatibility(log),
        tts=FakeTts(log),
        inputs=inputs,
        expression=FakeExpression(log),
        journal=journal,
        binding=_binding(),
    )
    await service.start()
    await asyncio.wait_for(inputs.accepted.wait(), timeout=1)
    assert journal.turn_id is not None
    frames = await service.play_effect(turn_id=journal.turn_id, text="现在是下午三点。")
    await service.stop()

    assert frames == 1
    assert set(log[:2]) == {"model_ready", "tts_ready"}
    assert log[2:] == ["registered", "synthesized", "played", "sealed"]


@pytest.mark.asyncio
async def test_silence_completes_without_fabricated_audio() -> None:
    log: list[str] = []
    inputs = FakeInputs()
    journal = FakeJournal()
    service = LiveVoiceService(
        audio=FakeAudio(log),
        asr=FakeAsr(),
        model=FakeModelCompatibility(log),
        tts=FakeTts(log),
        inputs=inputs,
        expression=FakeExpression(log),
        journal=journal,
        binding=_binding(),
    )
    await service.start()
    await asyncio.wait_for(inputs.accepted.wait(), timeout=1)
    assert journal.turn_id is not None
    await service.complete_silently(turn_id=journal.turn_id)
    await service.stop()
    assert "played" not in log


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("write_first_frame", "expected_code"),
    (
        (False, "VOICE-PLAYBACK-NOT-DELIVERED"),
        (True, "VOICE-PLAYBACK-RESULT-UNKNOWN"),
    ),
)
async def test_failed_playback_distinguishes_no_delivery_from_unknown_result(
    write_first_frame: bool, expected_code: str
) -> None:
    log: list[str] = []
    inputs = FakeInputs()
    journal = FakeJournal()
    service = LiveVoiceService(
        audio=FailingAudio(log, write_first_frame=write_first_frame),
        asr=FakeAsr(),
        model=FakeModelCompatibility(log),
        tts=FakeTts(log),
        inputs=inputs,
        expression=FakeExpression(log),
        journal=journal,
        binding=_binding(),
    )
    await service.start()
    await asyncio.wait_for(inputs.accepted.wait(), timeout=1)
    assert journal.turn_id is not None

    with pytest.raises(LiveVoiceViolation) as error:
        await service.play_effect(turn_id=journal.turn_id, text="现在是下午三点。")

    assert error.value.code == expected_code
    await service.stop()


@pytest.mark.asyncio
async def test_failure_after_full_playback_is_unknown_and_never_safe_to_replay() -> (
    None
):
    log: list[str] = []
    inputs = FakeInputs()
    journal = FakeJournal()
    service = LiveVoiceService(
        audio=FakeAudio(log),
        asr=FakeAsr(),
        model=FakeModelCompatibility(log),
        tts=FakeTts(log),
        inputs=inputs,
        expression=FailingExpression(log),
        journal=journal,
        binding=_binding(),
    )
    await service.start()
    await asyncio.wait_for(inputs.accepted.wait(), timeout=1)
    assert journal.turn_id is not None

    with pytest.raises(LiveVoiceViolation) as error:
        await service.play_effect(turn_id=journal.turn_id, text="现在是下午三点。")

    assert error.value.code == "VOICE-PLAYBACK-RESULT-UNKNOWN"
    assert "played" in log
    await service.stop()
