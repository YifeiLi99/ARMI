from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid7

import pytest
from armi_adapter_esp32_display import (
    DisplayExpression,
    MoodDisplayAdapter,
    MoodDisplayConfig,
    MoodDisplayViolation,
    load_mood_display_config,
    map_mood_snapshot,
    probe_device,
)
from armi_adapter_esp32_display.wire import (
    MAX_FRAME_BYTES,
    decode_frame,
    encode_ping,
    encode_state,
)
from armi_mood.api import VAD, EffectiveEmotion, EmotionFamily, MoodSnapshot


def _snapshot(
    family: EmotionFamily | None = None,
    *,
    valence: int = 0,
    arousal: int = 0,
    dominance: int = 0,
) -> MoodSnapshot:
    emotions = (
        () if family is None else (EffectiveEmotion(family, "private nuance", 50),)
    )
    return MoodSnapshot(
        uuid7(),
        7,
        datetime.now(UTC),
        VAD(0, 0, 0),
        VAD(valence, arousal, dominance),
        emotions,
    )


@pytest.mark.parametrize(
    ("family", "expression"),
    (
        (EmotionFamily.JOY, DisplayExpression.HAPPY),
        (EmotionFamily.AFFECTION, DisplayExpression.HAPPY),
        (EmotionFamily.GRATITUDE, DisplayExpression.HAPPY),
        (EmotionFamily.PRIDE, DisplayExpression.HAPPY),
        (EmotionFamily.INTEREST, DisplayExpression.EXCITED),
        (EmotionFamily.HOPE, DisplayExpression.EXCITED),
        (EmotionFamily.CONTENTMENT, DisplayExpression.CALM),
        (EmotionFamily.RELIEF, DisplayExpression.CALM),
        (EmotionFamily.SADNESS, DisplayExpression.SAD),
        (EmotionFamily.BOREDOM, DisplayExpression.SAD),
        (EmotionFamily.FEAR, DisplayExpression.ANXIOUS),
        (EmotionFamily.ANXIETY, DisplayExpression.ANXIOUS),
        (EmotionFamily.ANGER, DisplayExpression.ANGRY),
        (EmotionFamily.FRUSTRATION, DisplayExpression.ANGRY),
        (EmotionFamily.DISGUST, DisplayExpression.DISGUSTED),
        (EmotionFamily.SHAME, DisplayExpression.EMBARRASSED),
        (EmotionFamily.GUILT, DisplayExpression.EMBARRASSED),
        (EmotionFamily.SURPRISE, DisplayExpression.EXCITED),
        (EmotionFamily.JEALOUSY, DisplayExpression.ANGRY),
        (EmotionFamily.CONFUSION, DisplayExpression.NEUTRAL),
    ),
)
def test_family_mapping_covers_all_faces(
    family: EmotionFamily, expression: DisplayExpression
) -> None:
    assert map_mood_snapshot(_snapshot(family)).expression is expression


def test_conditional_and_vad_mapping() -> None:
    assert (
        map_mood_snapshot(_snapshot(EmotionFamily.JOY, arousal=70)).expression
        == "excited"
    )
    assert (
        map_mood_snapshot(_snapshot(EmotionFamily.SURPRISE, valence=-10)).expression
        == "anxious"
    )
    assert (
        map_mood_snapshot(_snapshot(EmotionFamily.JEALOUSY, dominance=20)).expression
        == "angry"
    )
    assert map_mood_snapshot(_snapshot()).expression == "neutral"
    assert map_mood_snapshot(_snapshot(valence=60, arousal=-40)).expression == "calm"
    assert map_mood_snapshot(_snapshot(arousal=37)).energy == 70


def test_wire_state_discloses_only_display_projection() -> None:
    state = map_mood_snapshot(_snapshot(EmotionFamily.JOY, arousal=20))
    frame = encode_state("state-1", state)
    assert len(frame) <= MAX_FRAME_BYTES
    value = decode_frame(frame)
    assert value["expression"] == "happy"
    assert "family" not in value
    assert "nuance" not in value
    assert "valence" not in value


@pytest.mark.parametrize("frame", (b"", b"{}", b"not-json\n", b"x" * 513))
def test_wire_rejects_invalid_and_oversized_frames(frame: bytes) -> None:
    with pytest.raises(MoodDisplayViolation):
        decode_frame(frame)


def test_configuration_is_optional_disabled_or_strict(tmp_path: Path) -> None:
    assert load_mood_display_config(tmp_path) is None
    devices = tmp_path / "devices"
    devices.mkdir()
    config = devices / "mood-display.yaml"
    config.write_text(
        "schema_version: armi.mood-display-config.v1\n"
        "enabled: false\n"
        "port: COM7\n"
        "expected_device_id: mood-window-1\n",
        encoding="utf-8",
        newline="\n",
    )
    loaded = load_mood_display_config(tmp_path)
    assert loaded is not None and not loaded.enabled and loaded.port == "COM7"
    config.write_text("enabled: true\n", encoding="utf-8", newline="\n")
    with pytest.raises(MoodDisplayViolation):
        load_mood_display_config(tmp_path)


class _ProbeSerial:
    def __init__(self, frame: bytes) -> None:
        self.frame = frame
        self.closed = False

    def read_until(self, expected: bytes = b"\n", size: int | None = None) -> bytes:
        del expected, size
        return self.frame

    def write(self, data: bytes) -> int:
        return len(data)

    def close(self) -> None:
        self.closed = True


class _ScriptedSerial(_ProbeSerial):
    def __init__(self, frames: list[bytes]) -> None:
        super().__init__(b"")
        self.frames = frames
        self.writes: list[bytes] = []

    def read_until(self, expected: bytes = b"\n", size: int | None = None) -> bytes:
        del expected, size
        return self.frames.pop(0) if self.frames else b""

    def write(self, data: bytes) -> int:
        self.writes.append(data)
        return len(data)


def test_probe_reads_identity_and_closes_port() -> None:
    frame = (
        json.dumps(
            {
                "type": "hello",
                "protocol_version": "armi.mood-display.v1",
                "device_id": "mood-window-1",
                "firmware_version": "0.1.0",
                "boot_id": "boot-1",
            },
            separators=(",", ":"),
        ).encode()
        + b"\n"
    )
    serial_port = _ProbeSerial(frame)
    result = probe_device("COM7", serial_factory=lambda _port: serial_port)
    assert result.device_id == "mood-window-1"
    assert result.protocol_version == "armi.mood-display.v1"
    assert serial_port.closed


def test_state_ack_timeout_reuses_same_frame_once() -> None:
    ack = (
        b'{"protocol_version":"armi.mood-display.v1","state_id":"state-1",'
        b'"status":"applied","type":"ack"}\n'
    )
    serial_port = _ScriptedSerial([b"", ack])
    adapter = MoodDisplayAdapter(
        MoodDisplayConfig(True, "COM7", "mood-window-1"),
        lambda: asyncio.sleep(0, result=_snapshot()),
    )
    frame = encode_state("state-1", map_mood_snapshot(_snapshot()))

    asyncio.run(adapter._send_with_ack(serial_port, frame, "state-1"))

    assert serial_port.writes == [frame, frame]


def test_device_identity_mismatch_is_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    hello = (
        b'{"boot_id":"boot-1","device_id":"other-device",'
        b'"firmware_version":"0.1.0",'
        b'"protocol_version":"armi.mood-display.v1","type":"hello"}\n'
    )
    serial_port = _ScriptedSerial([hello])
    adapter = MoodDisplayAdapter(
        MoodDisplayConfig(True, "COM7", "mood-window-1"),
        lambda: asyncio.sleep(0, result=_snapshot()),
        serial_factory=lambda _port: serial_port,
    )

    async def stop_after_failure(_delay: float) -> None:
        raise asyncio.CancelledError

    monkeypatch.setattr(
        "armi_adapter_esp32_display.service.asyncio.sleep", stop_after_failure
    )
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(adapter.run())

    assert adapter.status.availability == "unavailable"
    assert adapter.status.reason_code == "connection_failed"
    assert serial_port.closed


def test_reconnect_uses_bounded_backoff(monkeypatch: pytest.MonkeyPatch) -> None:
    delays: list[float] = []

    def unavailable(_port: str) -> _ScriptedSerial:
        raise OSError("not connected")

    adapter = MoodDisplayAdapter(
        MoodDisplayConfig(True, "COM7", "mood-window-1"),
        lambda: asyncio.sleep(0, result=_snapshot()),
        serial_factory=unavailable,
    )

    async def record_delay(delay: float) -> None:
        delays.append(delay)
        if len(delays) == 6:
            raise asyncio.CancelledError

    monkeypatch.setattr(
        "armi_adapter_esp32_display.service.asyncio.sleep", record_delay
    )
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(adapter.run())

    assert delays == [1, 2, 5, 10, 30, 30]


def test_heartbeat_requires_matching_pong(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("armi_adapter_esp32_display.service.uuid4", lambda: "ping-1")
    pong = (
        b'{"ping_id":"ping-1","protocol_version":"armi.mood-display.v1",'
        b'"type":"pong"}\n'
    )
    serial_port = _ScriptedSerial([pong])
    adapter = MoodDisplayAdapter(
        MoodDisplayConfig(True, "COM7", "mood-window-1"),
        lambda: asyncio.sleep(0, result=_snapshot()),
    )

    asyncio.run(adapter._heartbeat(serial_port))

    assert serial_port.writes == [encode_ping("ping-1")]
