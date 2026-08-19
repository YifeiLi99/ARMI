from __future__ import annotations

import asyncio
import gzip
import json
import struct
from types import SimpleNamespace

import armi_runtime.adapters.voice.volc as volc_module
import pytest
from armi_live_voice.api import LiveVoiceViolation
from armi_runtime.adapters.voice.volc import (
    VolcCredentials,
    VolcStreamingAsr,
    VolcStreamingTts,
    decode_message,
    encode_asr_audio,
    encode_asr_full_request,
    encode_event,
    json_payload,
)


def test_asr_full_request_uses_sequence_json_and_gzip() -> None:
    wire = encode_asr_full_request({"audio": {"format": "pcm"}})
    assert wire[:4] == bytes((0x11, 0x11, 0x11, 0))
    assert struct.unpack(">i", wire[4:8]) == (1,)
    size = struct.unpack(">I", wire[8:12])[0]
    assert len(wire[12:]) == size
    assert gzip.decompress(wire[12:]).startswith(b'{"audio"')


def test_asr_audio_marks_last_sequence_negative() -> None:
    wire = encode_asr_audio(b"pcm", 9, last=True)
    assert wire[:4] == bytes((0x11, 0x23, 0x01, 0))
    assert struct.unpack(">i", wire[4:8]) == (-9,)
    assert gzip.decompress(wire[12:]) == b"pcm"


def test_event_packet_round_trips_session_and_json() -> None:
    wire = encode_event(200, {"req_params": {"text": "hi"}}, session_id="session")
    message = decode_message(wire, event_has_session=True)
    assert message.event == 200
    assert message.session_id == "session"
    assert json_payload(message) == {"req_params": {"text": "hi"}}


def test_server_connection_event_carries_connection_id() -> None:
    connection_id = b"connection-1"
    payload = b"{}"
    wire = (
        bytes((0x11, 0x94, 0x10, 0x00))
        + struct.pack(">iI", 50, len(connection_id))
        + connection_id
        + struct.pack(">I", len(payload))
        + payload
    )

    message = decode_message(wire, event_has_session=True)

    assert message.event == 50
    assert message.session_id == "connection-1"
    assert message.payload == payload


def test_decoder_rejects_truncated_payload() -> None:
    with pytest.raises(LiveVoiceViolation, match="truncated"):
        decode_message(bytes((0x11, 0x90, 0x10, 0, 0, 0, 0, 5, 1)))


def _server_response(payload: dict[str, object], sequence: int = 1) -> bytes:
    body = json.dumps(payload).encode()
    return bytes((0x11, 0x91, 0x10, 0)) + struct.pack(">iI", sequence, len(body)) + body


def _server_event(event: int, payload: bytes = b"{}") -> bytes:
    session = b"provider-session"
    serialization = 0 if event == 352 else 1
    return (
        bytes((0x11, 0x94, serialization << 4, 0))
        + struct.pack(">iI", event, len(session))
        + session
        + struct.pack(">I", len(payload))
        + payload
    )


class FakeAsrSocket:
    def __init__(self) -> None:
        self.sent: list[bytes] = []
        self.responses: asyncio.Queue[bytes] = asyncio.Queue()
        self.responses.put_nowait(_server_response({}))

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_: object) -> None:
        return None

    async def send(self, wire: bytes) -> None:
        self.sent.append(wire)
        if wire[1] & 0x0F == 0x03:
            self.responses.put_nowait(
                _server_response(
                    {
                        "result": {
                            "text": "完成。",
                            "utterances": [{"definite": True}],
                        }
                    },
                    -4,
                )
            )

    async def recv(self) -> bytes:
        return await self.responses.get()


@pytest.mark.asyncio
async def test_asr_sends_audio_without_waiting_for_a_response_per_frame(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    socket = FakeAsrSocket()
    monkeypatch.setattr(
        volc_module.importlib,
        "import_module",
        lambda _: SimpleNamespace(connect=lambda *args, **kwargs: socket),
    )

    async def frames():
        for frame in (b"one", b"two", b"three"):
            yield frame

    events = [
        event
        async for event in VolcStreamingAsr(VolcCredentials("app", "token")).recognize(
            frames()
        )
    ]

    assert [event.text for event in events] == ["完成。"]
    assert len(socket.sent) == 4
    assert decode_message(socket.sent[-1]).sequence == -4


class FakeTtsSocket:
    def __init__(self) -> None:
        self.events: list[int] = []
        self.responses: asyncio.Queue[bytes] = asyncio.Queue()
        self.closed = False

    async def send(self, wire: bytes) -> None:
        event = struct.unpack(">i", wire[4:8])[0]
        self.events.append(event)
        if event == 1:
            self.responses.put_nowait(_server_event(50))
        elif event == 100:
            self.responses.put_nowait(_server_event(150))
        elif event == 200:
            self.responses.put_nowait(_server_event(352, b"pcm"))
        elif event == 102:
            self.responses.put_nowait(_server_event(152))

    async def recv(self) -> bytes:
        return await self.responses.get()

    async def close(self) -> None:
        self.closed = True


@pytest.mark.asyncio
async def test_tts_reuses_prepared_connection_for_multiple_sessions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    socket = FakeTtsSocket()
    connections = 0

    async def connect(*_: object, **__: object):
        nonlocal connections
        connections += 1
        return socket

    monkeypatch.setattr(
        volc_module.importlib,
        "import_module",
        lambda _: SimpleNamespace(connect=connect),
    )
    tts = VolcStreamingTts(VolcCredentials("app", "token"))

    async def fragment(text: str):
        yield text

    await tts.prepare()
    assert b"".join([part async for part in tts.synthesize(fragment("一"))]) == b"pcm"
    assert b"".join([part async for part in tts.synthesize(fragment("二"))]) == b"pcm"
    await tts.close()

    assert connections == 1
    assert socket.events.count(1) == 1
    assert socket.events.count(100) == 2
    assert socket.events.count(102) == 2
    assert socket.events.count(2) == 1
    assert socket.closed is True
