from __future__ import annotations

import asyncio
import gzip
import json
import struct
from collections.abc import AsyncGenerator
from types import SimpleNamespace
from typing import cast

import armi_runtime.adapters.voice.volc as volc_module
import pytest
from armi_kernel.application import (
    PriceCatalog,
    ProviderMeterScope,
    provider_meter_scope,
)
from armi_live_voice.api import LiveVoiceViolation
from armi_runtime.adapters.voice.volc import (
    VolcCredentials,
    VolcStreamingAsr,
    VolcStreamingTts,
    decode_message,
    decode_volc_credentials,
    encode_asr_audio,
    encode_asr_full_request,
    encode_event,
    json_payload,
)


@pytest.fixture(autouse=True)
def fake_provider_receipts():
    """These adapter tests use fake transports and an inspectable receipt sink."""
    receipts = []

    async def save(receipt):
        receipts.append(receipt)

    with provider_meter_scope(
        ProviderMeterScope(save, PriceCatalog(()), "adapter_test")
    ):
        yield receipts


def test_voice_credentials_decode_from_scoped_api_key() -> None:
    value = bytearray(b" test-speech-key ")

    credentials = decode_volc_credentials(value)

    assert credentials == VolcCredentials("test-speech-key")


@pytest.mark.parametrize(
    "value",
    (
        bytearray(b"{}"),
        bytearray(b'{"app_id":"app","access_token":""}'),
        bytearray(b'{"app_id":"app","access_token":"token","extra":1}'),
        bytearray(b""),
        bytearray(b"key\r\ninjected-header"),
        bytearray(b"\xff"),
    ),
)
def test_voice_credentials_reject_old_documents_and_invalid_keys(
    value: bytearray,
) -> None:
    with pytest.raises(LiveVoiceViolation, match="credential"):
        decode_volc_credentials(value)


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


def _gzip_server_frame(payload: bytes, *, serialization: int = 1) -> bytes:
    return (
        bytes((0x11, 0x90, (serialization << 4) | 1, 0))
        + struct.pack(">I", len(payload))
        + payload
    )


def test_decoder_rejects_gzip_members_trailing_data_and_expansion() -> None:
    for payload in (
        gzip.compress(b"{}") + gzip.compress(b"{}"),
        gzip.compress(b"{}") + b"trailing",
    ):
        with pytest.raises(LiveVoiceViolation, match="gzip"):
            decode_message(_gzip_server_frame(payload))

    bomb = gzip.compress(b"x" * (256 * 1024 + 1))
    with pytest.raises(LiveVoiceViolation, match="budget"):
        decode_message(_gzip_server_frame(bomb))


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

    def connect(*args, **kwargs):
        headers = kwargs["additional_headers"]
        assert headers["X-Api-Key"] == "test-speech-key"
        assert "X-Api-App-Key" not in headers
        assert "X-Api-Access-Key" not in headers
        return socket

    monkeypatch.setattr(
        volc_module.importlib,
        "import_module",
        lambda _: SimpleNamespace(connect=connect),
    )

    async def frames():
        for frame in (b"one", b"two", b"three"):
            yield frame

    events = [
        event
        async for event in VolcStreamingAsr(
            VolcCredentials("test-speech-key")
        ).recognize(frames())
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
@pytest.mark.parametrize("adapter", ("asr", "tts"))
async def test_cancelled_stream_releases_pending_receiver(
    adapter: str,
    monkeypatch: pytest.MonkeyPatch,
    fake_provider_receipts,
) -> None:
    class WaitingSocket:
        def __init__(self) -> None:
            self.responses: asyncio.Queue[bytes] = asyncio.Queue()
            self.waiting = asyncio.Event()
            self.finished = asyncio.Event()
            self.receiver = None
            self.closed = False
            self.sent = 0

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_: object) -> None:
            await self.close()

        async def send(self, wire: bytes) -> None:
            self.sent += 1
            if adapter == "asr":
                if self.sent == 1:
                    self.responses.put_nowait(_server_response({}))
            else:
                event = struct.unpack(">i", wire[4:8])[0]
                if event in {1, 100}:
                    self.responses.put_nowait(_server_event(50 if event == 1 else 150))

        async def recv(self) -> bytes:
            pending = self.responses.empty()
            if pending:
                self.receiver = asyncio.current_task()
                self.waiting.set()
            try:
                return await self.responses.get()
            finally:
                if pending:
                    self.finished.set()

        async def close(self) -> None:
            self.closed = True

    socket = WaitingSocket()

    def connect_asr(*_: object, **__: object):
        return socket

    async def connect_tts(*_: object, **__: object):
        return socket

    monkeypatch.setattr(
        volc_module.importlib,
        "import_module",
        lambda _: SimpleNamespace(
            connect=connect_asr if adapter == "asr" else connect_tts
        ),
    )
    source_closed = asyncio.Event()

    async def source[T](value: T) -> AsyncGenerator[T]:
        try:
            yield value
            await asyncio.Event().wait()
        finally:
            source_closed.set()

    tts = VolcStreamingTts(VolcCredentials("test-speech-key"))

    async def consume() -> None:
        stream = (
            VolcStreamingAsr(VolcCredentials("test-speech-key")).recognize(
                source(b"audio")
            )
            if adapter == "asr"
            else tts.synthesize(source("local text"))
        )
        async for _ in stream:
            pass

    consuming = asyncio.create_task(consume())
    try:
        await asyncio.wait_for(socket.waiting.wait(), timeout=1)
        consuming.cancel()
        with pytest.raises(asyncio.CancelledError):
            await consuming
        assert source_closed.is_set()
        assert socket.finished.is_set()
        assert socket.closed is True
        assert fake_provider_receipts[-1].outcome == "unknown"
    finally:
        consuming.cancel()
        await asyncio.gather(consuming, return_exceptions=True)
        if socket.receiver is not None:
            socket.receiver.cancel()
            await asyncio.gather(socket.receiver, return_exceptions=True)
        await tts.close()


@pytest.mark.asyncio
async def test_tts_reuses_prepared_connection_for_multiple_sessions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    socket = FakeTtsSocket()
    connections = 0

    async def connect(*_: object, **__: object):
        nonlocal connections
        headers = __["additional_headers"]
        assert isinstance(headers, dict)
        assert headers["X-Api-Key"] == "test-speech-key"
        assert "X-Api-App-Key" not in headers
        assert "X-Api-Access-Key" not in headers
        connections += 1
        return socket

    monkeypatch.setattr(
        volc_module.importlib,
        "import_module",
        lambda _: SimpleNamespace(connect=connect),
    )
    tts = VolcStreamingTts(VolcCredentials("test-speech-key"))

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


@pytest.mark.asyncio
async def test_closing_tts_stream_after_audio_invalidates_connection(
    monkeypatch: pytest.MonkeyPatch,
    fake_provider_receipts,
) -> None:
    socket = FakeTtsSocket()

    async def connect(*_: object, **__: object):
        return socket

    monkeypatch.setattr(
        volc_module.importlib,
        "import_module",
        lambda _: SimpleNamespace(connect=connect),
    )
    tts = VolcStreamingTts(VolcCredentials("test-speech-key"))

    async def fragment():
        yield "local text"

    stream = cast(AsyncGenerator[bytes], tts.synthesize(fragment()))
    try:
        assert await anext(stream) == b"pcm"
        await stream.aclose()
        assert socket.closed is True
        assert fake_provider_receipts[-1].outcome == "unknown"
    finally:
        await stream.aclose()
        await tts.close()


@pytest.mark.asyncio
async def test_tts_propagates_text_stream_failure_without_waiting_for_session_end(
    monkeypatch: pytest.MonkeyPatch,
    fake_provider_receipts,
) -> None:
    socket = FakeTtsSocket()

    async def connect(*_: object, **__: object):
        return socket

    monkeypatch.setattr(
        volc_module.importlib,
        "import_module",
        lambda _: SimpleNamespace(connect=connect),
    )
    tts = VolcStreamingTts(VolcCredentials("test-speech-key"))

    async def failing_fragments():
        yield "已经发出的片段"
        raise LiveVoiceViolation("VOICE-TEXT-STREAM", "bad trailing output")

    async def consume() -> None:
        async for _ in tts.synthesize(failing_fragments()):
            pass

    with pytest.raises(LiveVoiceViolation, match="bad trailing output"):
        await asyncio.wait_for(consume(), timeout=1)
    receipt = fake_provider_receipts[-1]
    assert receipt.outcome == "unknown"
    assert receipt.quantities[0].quantity == len("已经发出的片段")
    assert receipt.quantities[0].source.value == "local_measurement"
