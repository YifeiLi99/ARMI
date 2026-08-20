from __future__ import annotations

import pytest
from armi_live_voice.api import (
    AudioFormat,
    FastReplyKind,
    HalfDuplexStateMachine,
    LiveVoiceSessionState,
    LiveVoiceViolation,
    parse_fast_reply,
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
