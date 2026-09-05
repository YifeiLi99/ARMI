from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid7

import pytest
import serial
from armi_adapter_esp32_display import (
    DisplayExpression,
    MoodDisplayAdapter,
    MoodDisplayConfig,
    MoodDisplayViolation,
    load_mood_display_config,
    map_mood_snapshot,
    probe_device,
)
from armi_adapter_esp32_display.service import _open_serial
from armi_adapter_esp32_display.wire import (
    MAX_FRAME_BYTES,
    decode_frame,
    encode_identify,
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
    tuple((family, DisplayExpression[family.name]) for family in EmotionFamily),
)
def test_every_family_has_its_own_expression(
    family: EmotionFamily, expression: DisplayExpression
) -> None:
    assert map_mood_snapshot(_snapshot(family)).expression is expression


def test_every_family_has_its_own_fixed_color() -> None:
    colors = {
        map_mood_snapshot(_snapshot(family)).foreground for family in EmotionFamily
    }
    assert len(colors) == len(EmotionFamily) == 20


def test_neutral_and_energy_mapping() -> None:
    assert map_mood_snapshot(_snapshot()).expression == "neutral"
    assert map_mood_snapshot(_snapshot(arousal=37)).energy == 70


def test_wire_state_discloses_only_display_projection() -> None:
    state = map_mood_snapshot(_snapshot(EmotionFamily.JOY, arousal=20))
    assert state.foreground == "#FFD166"
    assert state.background == "#000000"
    frame = encode_state("state-1", state)
    assert len(frame) <= MAX_FRAME_BYTES
    value = decode_frame(frame)
    assert value["expression"] == "face_01"
    assert "joy" not in frame.decode("utf-8")
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
        self.identified = False

    def read_until(self, expected: bytes = b"\n", size: int | None = None) -> bytes:
        del expected, size
        assert self.identified, "device waits for an identity request after connection"
        return self.frame

    def write(self, data: bytes) -> int:
        self.identified = data == encode_identify()
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
                "protocol_version": "armi.mood-display.v2",
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
    assert result.protocol_version == "armi.mood-display.v2"
    assert serial_port.closed


def test_serial_open_does_not_assert_board_reset_lines(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class ControlLines:
        def __init__(self, **settings: object) -> None:
            assert settings["port"] is None
            self.dtr = True
            self.rts = True
            self.port: str | None = None

        def open(self) -> None:
            assert self.port == "COM3"
            assert not self.dtr and not self.rts

    monkeypatch.setattr(serial, "Serial", ControlLines)
    _open_serial("COM3")


def test_unchanged_state_is_renewed_before_device_expiry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = 0.0
    sent_at: list[float] = []
    snapshot = _snapshot()
    adapter = MoodDisplayAdapter(
        MoodDisplayConfig(True, "COM7", "mood-window-1"),
        lambda: asyncio.sleep(0, result=snapshot),
    )

    async def get_snapshot() -> MoodSnapshot:
        return snapshot

    async def send(*_args: object) -> None:
        sent_at.append(now)

    async def heartbeat(*_args: object) -> None:
        pass

    async def advance(_delay: float) -> None:
        nonlocal now
        now += 1
        if now > 31:
            raise asyncio.CancelledError

    adapter._snapshot = get_snapshot
    monkeypatch.setattr(
        "armi_adapter_esp32_display.service.time.monotonic", lambda: now
    )
    monkeypatch.setattr("armi_adapter_esp32_display.service.asyncio.sleep", advance)
    monkeypatch.setattr(MoodDisplayAdapter, "_send_with_ack", send)
    monkeypatch.setattr(MoodDisplayAdapter, "_heartbeat", heartbeat)
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(adapter._session(_ScriptedSerial([])))
    assert sent_at == [0, 10, 20, 30]


def test_state_ack_timeout_reuses_same_frame_once() -> None:
    ack = (
        b'{"protocol_version":"armi.mood-display.v2","state_id":"state-1",'
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
        b'"protocol_version":"armi.mood-display.v2","type":"hello"}\n'
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


def test_snapshot_failure_revokes_available_and_reconnects(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    hello = (
        b'{"boot_id":"boot-1","device_id":"mood-window-1",'
        b'"firmware_version":"0.1.0",'
        b'"protocol_version":"armi.mood-display.v2","type":"hello"}\n'
    )
    connections: list[_ScriptedSerial] = []

    def connect(_port: str) -> _ScriptedSerial:
        connection = _ScriptedSerial([hello])
        connections.append(connection)
        return connection

    async def unavailable_snapshot() -> MoodSnapshot:
        raise RuntimeError("database unavailable")

    adapter = MoodDisplayAdapter(
        MoodDisplayConfig(True, "COM7", "mood-window-1"),
        unavailable_snapshot,
        serial_factory=connect,
    )

    async def stop_after_reconnect_delay(_delay: float) -> None:
        raise asyncio.CancelledError

    monkeypatch.setattr(
        "armi_adapter_esp32_display.service.asyncio.sleep",
        stop_after_reconnect_delay,
    )
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(adapter.run())

    assert adapter.status.availability == "unavailable"
    assert adapter.status.reason_code == "snapshot_failed"
    assert connections[0].closed


def test_heartbeat_requires_matching_pong(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("armi_adapter_esp32_display.service.uuid4", lambda: "ping-1")
    pong = (
        b'{"ping_id":"ping-1","protocol_version":"armi.mood-display.v2",'
        b'"type":"pong"}\n'
    )
    serial_port = _ScriptedSerial([pong])
    adapter = MoodDisplayAdapter(
        MoodDisplayConfig(True, "COM7", "mood-window-1"),
        lambda: asyncio.sleep(0, result=_snapshot()),
    )

    asyncio.run(adapter._heartbeat(serial_port))

    assert serial_port.writes == [encode_ping("ping-1")]
