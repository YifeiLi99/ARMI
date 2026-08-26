from __future__ import annotations

import pytest
from armi_live_voice.api import (
    AudioFormat,
    HalfDuplexStateMachine,
    LiveVoiceSessionState,
    LiveVoiceViolation,
)


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
