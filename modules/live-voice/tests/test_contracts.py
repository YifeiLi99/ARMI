from __future__ import annotations

import pytest
from armi_live_voice.api import (
    AudioFormat,
    BoundedAudioQueue,
    FastReplyKind,
    HalfDuplexStateMachine,
    LiveVoiceSessionState,
    LiveVoiceViolation,
    parse_fast_reply,
    speech_chunks,
)


@pytest.mark.parametrize(
    ("payload", "kind", "text"),
    [
        ("SPEAK\n你好。", FastReplyKind.SPEAK, "你好。"),
        ("WAIT\n我想一下。", FastReplyKind.WAIT, "我想一下。"),
        ("SILENT\n", FastReplyKind.SILENT, ""),
    ],
)
def test_fast_reply_protocol(payload: str, kind: FastReplyKind, text: str) -> None:
    assert parse_fast_reply(payload).kind is kind
    assert parse_fast_reply(payload).text == text


@pytest.mark.parametrize(
    "payload",
    ["SPEAK", "SPEAK\n", "WAIT\n" + "等" * 25, "SILENT\n不说", "talk\n你好"],
)
def test_fast_reply_protocol_rejects_damage(payload: str) -> None:
    with pytest.raises(LiveVoiceViolation, match=r"reply|SILENT|unknown"):
        parse_fast_reply(payload)


def test_speech_chunks_prefers_punctuation_and_bounds_tail() -> None:
    chunks = speech_chunks("这是第一段自然语言\uff0c会先播出来。后面还有一句。")
    assert "".join(chunks) == "这是第一段自然语言\uff0c会先播出来。后面还有一句。"
    assert 12 <= len(chunks[0]) <= 48
    assert all(len(item) <= 48 for item in speech_chunks("字" * 120))


def test_audio_queue_has_explicit_backpressure() -> None:
    queue = BoundedAudioQueue(4)
    queue.put(b"12")
    queue.put(b"34")
    with pytest.raises(LiveVoiceViolation, match="full"):
        queue.put(b"5")
    assert queue.get() == b"12"
    assert queue.size_bytes == 2


def test_audio_format_is_twenty_millisecond_pcm16() -> None:
    assert AudioFormat().frame_bytes == 640


def test_half_duplex_pauses_microphone_during_thinking_and_speaking() -> None:
    machine = HalfDuplexStateMachine()
    machine.transition(LiveVoiceSessionState.STARTING)
    machine.transition(LiveVoiceSessionState.LISTENING)
    assert machine.microphone_open
    machine.transition(LiveVoiceSessionState.RECOGNIZING)
    machine.transition(LiveVoiceSessionState.THINKING)
    assert not machine.microphone_open
    machine.transition(LiveVoiceSessionState.SPEAKING)
    assert not machine.microphone_open
    machine.transition(LiveVoiceSessionState.LISTENING)
    assert machine.microphone_open


def test_half_duplex_rejects_skipping_recognition() -> None:
    machine = HalfDuplexStateMachine()
    with pytest.raises(LiveVoiceViolation, match="illegal transition"):
        machine.transition(LiveVoiceSessionState.SPEAKING)
