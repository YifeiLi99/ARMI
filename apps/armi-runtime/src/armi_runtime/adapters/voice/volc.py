"""Volcengine V3 streaming ASR and bidirectional TTS adapters."""

from __future__ import annotations

import asyncio
import contextlib
import gzip
import importlib
import json
import struct
from collections.abc import AsyncIterator, Mapping
from dataclasses import dataclass
from typing import Any, cast
from uuid import uuid4

from armi_live_voice.api import LiveVoiceViolation, RecognitionEvent

ASR_ENDPOINT = "wss://openspeech.bytedance.com/api/v3/sauc/bigmodel"
TTS_ENDPOINT = "wss://openspeech.bytedance.com/api/v3/tts/bidirection"

_FULL_CLIENT_REQUEST = 0x1
_AUDIO_ONLY_REQUEST = 0x2
_FULL_SERVER_RESPONSE = 0x9
_AUDIO_ONLY_RESPONSE = 0xB
_ERROR_RESPONSE = 0xF
_FLAG_SEQUENCE = 0x1
_FLAG_LAST = 0x2
_FLAG_EVENT = 0x4
_SERIAL_NONE = 0x0
_SERIAL_JSON = 0x1
_COMPRESS_NONE = 0x0
_COMPRESS_GZIP = 0x1

_START_CONNECTION = 1
_FINISH_CONNECTION = 2
_CONNECTION_STARTED = 50
_CONNECTION_FAILED = 51
_CONNECTION_FINISHED = 52
_START_SESSION = 100
_FINISH_SESSION = 102
_SESSION_STARTED = 150
_SESSION_FINISHED = 152
_SESSION_FAILED = 153
_TASK_REQUEST = 200
_TTS_RESPONSE = 352


@dataclass(frozen=True, slots=True)
class VolcCredentials:
    app_id: str
    access_token: str

    def __post_init__(self) -> None:
        if not self.app_id or not self.access_token:
            raise LiveVoiceViolation(
                "VOICE-VOLC-CREDENTIAL", "Volcengine speech credential is incomplete"
            )


def decode_volc_credentials(secret: bytes | bytearray) -> VolcCredentials:
    """Decode the exact approved speech credential document."""

    try:
        decoded: object = json.loads(bytes(secret).decode("utf-8", errors="strict"))
    except UnicodeDecodeError, json.JSONDecodeError:
        raise LiveVoiceViolation(
            "VOICE-VOLC-CREDENTIAL", "Volcengine speech credential is invalid"
        ) from None
    if type(decoded) is not dict:
        raise LiveVoiceViolation(
            "VOICE-VOLC-CREDENTIAL", "Volcengine speech credential is invalid"
        )
    document = cast(dict[str, object], decoded)
    if set(document) != {"app_id", "access_token"}:
        raise LiveVoiceViolation(
            "VOICE-VOLC-CREDENTIAL", "Volcengine speech credential is invalid"
        )
    app_id = document["app_id"]
    access_token = document["access_token"]
    if type(app_id) is not str or type(access_token) is not str:
        raise LiveVoiceViolation(
            "VOICE-VOLC-CREDENTIAL", "Volcengine speech credential is invalid"
        )
    return VolcCredentials(app_id.strip(), access_token.strip())


@dataclass(frozen=True, slots=True)
class BinaryMessage:
    message_type: int
    flags: int
    serialization: int
    compression: int
    sequence: int | None
    event: int | None
    session_id: str | None
    payload: bytes


def encode_asr_full_request(payload: Mapping[str, object], sequence: int = 1) -> bytes:
    body = gzip.compress(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()
    )
    return (
        _header(_FULL_CLIENT_REQUEST, _FLAG_SEQUENCE, _SERIAL_JSON, _COMPRESS_GZIP)
        + struct.pack(">iI", sequence, len(body))
        + body
    )


def encode_asr_audio(audio: bytes, sequence: int, *, last: bool = False) -> bytes:
    if not audio:
        raise LiveVoiceViolation("VOICE-ASR-AUDIO", "ASR audio frame is empty")
    body = gzip.compress(audio)
    wire_sequence = -abs(sequence) if last else abs(sequence)
    flags = _FLAG_SEQUENCE | (_FLAG_LAST if last else 0)
    return (
        _header(_AUDIO_ONLY_REQUEST, flags, _SERIAL_NONE, _COMPRESS_GZIP)
        + struct.pack(">iI", wire_sequence, len(body))
        + body
    )


def encode_event(
    event: int,
    payload: Mapping[str, object] | bytes,
    *,
    session_id: str | None = None,
) -> bytes:
    if isinstance(payload, bytes):
        serialization = _SERIAL_NONE
        body = payload
    else:
        serialization = _SERIAL_JSON
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()
    fields = bytearray(struct.pack(">i", event))
    if session_id is not None:
        session = session_id.encode()
        fields.extend(struct.pack(">I", len(session)))
        fields.extend(session)
    fields.extend(struct.pack(">I", len(body)))
    fields.extend(body)
    return (
        _header(_FULL_CLIENT_REQUEST, _FLAG_EVENT, serialization, _COMPRESS_NONE)
        + fields
    )


def decode_message(data: bytes, *, event_has_session: bool = False) -> BinaryMessage:
    if len(data) < 4:
        raise LiveVoiceViolation("VOICE-VOLC-FRAME", "provider frame is truncated")
    version = data[0] >> 4
    header_words = data[0] & 0x0F
    if version != 1 or header_words < 1 or len(data) < header_words * 4:
        raise LiveVoiceViolation("VOICE-VOLC-FRAME", "provider frame header is invalid")
    message_type = data[1] >> 4
    flags = data[1] & 0x0F
    serialization = data[2] >> 4
    compression = data[2] & 0x0F
    offset = header_words * 4
    sequence = None
    event = None
    session_id = None
    if flags & _FLAG_SEQUENCE:
        sequence, offset = _read_i32(data, offset)
    if flags & _FLAG_EVENT:
        event, offset = _read_i32(data, offset)
        if event_has_session:
            session_size, offset = _read_u32(data, offset)
            session_raw, offset = _read_bytes(data, offset, session_size)
            session_id = session_raw.decode("utf-8", errors="strict")
    payload_size, offset = _read_u32(data, offset)
    payload, offset = _read_bytes(data, offset, payload_size)
    if offset != len(data):
        raise LiveVoiceViolation("VOICE-VOLC-FRAME", "provider frame has trailing data")
    if compression == _COMPRESS_GZIP:
        try:
            payload = gzip.decompress(payload)
        except (OSError, EOFError) as error:
            raise LiveVoiceViolation(
                "VOICE-VOLC-FRAME", "provider gzip payload is invalid"
            ) from error
    return BinaryMessage(
        message_type,
        flags,
        serialization,
        compression,
        sequence,
        event,
        session_id,
        payload,
    )


def json_payload(message: BinaryMessage) -> dict[str, Any]:
    if message.serialization != _SERIAL_JSON:
        raise LiveVoiceViolation("VOICE-VOLC-FRAME", "expected JSON provider payload")
    try:
        decoded = json.loads(message.payload)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise LiveVoiceViolation(
            "VOICE-VOLC-FRAME", "provider JSON payload is invalid"
        ) from error
    if not isinstance(decoded, dict):
        raise LiveVoiceViolation("VOICE-VOLC-FRAME", "provider JSON must be an object")
    return cast(dict[str, Any], decoded)


class VolcStreamingAsr:
    def __init__(
        self,
        credentials: VolcCredentials,
        *,
        resource_id: str = "volc.bigasr.sauc.duration",
        endpoint_silence_ms: int = 350,
        endpoint: str = ASR_ENDPOINT,
    ) -> None:
        self._credentials = credentials
        self._resource_id = resource_id
        self._endpoint_silence_ms = endpoint_silence_ms
        self._endpoint = endpoint

    async def recognize(
        self, frames: AsyncIterator[bytes]
    ) -> AsyncIterator[RecognitionEvent]:
        connect = importlib.import_module("websockets.asyncio.client").connect

        headers = {
            "X-Api-App-Key": self._credentials.app_id,
            "X-Api-Access-Key": self._credentials.access_token,
            "X-Api-Resource-Id": self._resource_id,
            "X-Api-Request-Id": str(uuid4()),
        }
        request = {
            "user": {"uid": "armi-live-voice"},
            "audio": {"format": "pcm", "rate": 16000, "bits": 16, "channel": 1},
            "request": {
                "model_name": "bigmodel",
                "enable_itn": True,
                "enable_punc": True,
                "show_utterances": True,
                "result_type": "full",
                "stream_mode": 2,
                "enable_nonstream": False,
                "end_window_size": self._endpoint_silence_ms,
            },
        }
        try:
            async with connect(
                self._endpoint,
                additional_headers=headers,
                max_size=2**22,
                open_timeout=5,
            ) as socket:
                await socket.send(encode_asr_full_request(request))
                first = decode_message(await socket.recv())
                _raise_provider_error(first, "ASR")

                async def send_audio() -> None:
                    iterator = frames.__aiter__()
                    try:
                        current = await anext(iterator)
                    except StopAsyncIteration:
                        raise LiveVoiceViolation(
                            "VOICE-ASR-AUDIO", "ASR audio stream is empty"
                        ) from None
                    sequence = 2
                    while True:
                        try:
                            following = await anext(iterator)
                        except StopAsyncIteration:
                            await socket.send(
                                encode_asr_audio(current, sequence, last=True)
                            )
                            return
                        await socket.send(encode_asr_audio(current, sequence))
                        current = following
                        sequence += 1

                # Sending microphone frames and receiving partials are independent
                # directions of the same WebSocket stream. Serial round trips here
                # turn a 20 ms audio cadence into provider-network latency per frame.
                sender = asyncio.create_task(send_audio())
                try:
                    while True:
                        receiver = asyncio.create_task(socket.recv())
                        waiting = {receiver}
                        if not sender.done():
                            waiting.add(sender)
                        done, _ = await asyncio.wait(
                            waiting, return_when=asyncio.FIRST_COMPLETED
                        )
                        if sender in done and not sender.cancelled():
                            sender_error = sender.exception()
                            if sender_error is not None:
                                receiver.cancel()
                                with contextlib.suppress(asyncio.CancelledError):
                                    await receiver
                                raise sender_error
                        response = decode_message(await receiver)
                        _raise_provider_error(response, "ASR")
                        event = _recognition_event(json_payload(response))
                        if event is not None:
                            yield event
                            if event.utterance_ended:
                                return
                finally:
                    sender.cancel()
                    with contextlib.suppress(asyncio.CancelledError):
                        await sender
        except LiveVoiceViolation:
            raise
        except Exception as error:
            raise LiveVoiceViolation(
                "VOICE-ASR-FAILED", "streaming ASR failed"
            ) from error


class VolcStreamingTts:
    def __init__(
        self,
        credentials: VolcCredentials,
        *,
        resource_id: str = "seed-tts-2.0",
        voice_type: str = "zh_female_vv_uranus_bigtts",
        endpoint: str = TTS_ENDPOINT,
    ) -> None:
        self._credentials = credentials
        self._resource_id = resource_id
        self._voice_type = voice_type
        self._endpoint = endpoint
        self._socket: Any | None = None
        self._connection_lock = asyncio.Lock()

    async def prepare(self) -> None:
        async with self._connection_lock:
            await self._ensure_connection()

    async def close(self) -> None:
        async with self._connection_lock:
            await self._close_connection()

    async def synthesize(self, fragments: AsyncIterator[str]) -> AsyncIterator[bytes]:
        session_id = str(uuid4())
        try:
            async with self._connection_lock:
                socket = await self._ensure_connection()
                start = {
                    "event": _START_SESSION,
                    "req_params": {
                        "speaker": self._voice_type,
                        "audio_params": {
                            "format": "pcm",
                            "sample_rate": 16000,
                        },
                    },
                }
                await socket.send(
                    encode_event(_START_SESSION, start, session_id=session_id)
                )
                await _expect_event(socket, _SESSION_STARTED, session=True)

                async def feed_text() -> None:
                    sent = False
                    async for fragment in fragments:
                        text = fragment.strip()
                        if not text:
                            continue
                        sent = True
                        task = {"event": _TASK_REQUEST, "req_params": {"text": text}}
                        await socket.send(
                            encode_event(_TASK_REQUEST, task, session_id=session_id)
                        )
                    if not sent:
                        raise LiveVoiceViolation("VOICE-TTS-TEXT", "TTS text is empty")
                    finish = {"event": _FINISH_SESSION}
                    await socket.send(
                        encode_event(_FINISH_SESSION, finish, session_id=session_id)
                    )

                feeder = asyncio.create_task(feed_text())
                try:
                    while True:
                        receiver = asyncio.create_task(socket.recv())
                        waiting = {receiver}
                        if not feeder.done():
                            waiting.add(feeder)
                        done, _ = await asyncio.wait(
                            waiting, return_when=asyncio.FIRST_COMPLETED
                        )
                        if feeder in done and not feeder.cancelled():
                            feeder_error = feeder.exception()
                            if feeder_error is not None:
                                receiver.cancel()
                                with contextlib.suppress(asyncio.CancelledError):
                                    await receiver
                                raise feeder_error
                        response = decode_message(
                            await receiver, event_has_session=True
                        )
                        _raise_provider_error(response, "TTS")
                        if response.event == _TTS_RESPONSE:
                            if response.payload:
                                yield response.payload
                        elif response.event == _SESSION_FINISHED:
                            await feeder
                            break
                        elif response.event == _SESSION_FAILED:
                            raise LiveVoiceViolation(
                                "VOICE-TTS-FAILED", "TTS session failed"
                            )
                finally:
                    feeder.cancel()
                    with contextlib.suppress(asyncio.CancelledError):
                        await feeder
        except LiveVoiceViolation:
            await self._invalidate_connection()
            raise
        except Exception as error:
            await self._invalidate_connection()
            raise LiveVoiceViolation(
                "VOICE-TTS-FAILED", "streaming TTS failed"
            ) from error

    async def _ensure_connection(self) -> Any:
        if self._socket is not None:
            return self._socket
        connect = importlib.import_module("websockets.asyncio.client").connect
        headers = {
            "X-Api-App-Key": self._credentials.app_id,
            "X-Api-Access-Key": self._credentials.access_token,
            "X-Api-Resource-Id": self._resource_id,
            "X-Api-Connect-Id": str(uuid4()),
        }
        socket = await connect(
            self._endpoint,
            additional_headers=headers,
            max_size=2**22,
            open_timeout=5,
        )
        try:
            await socket.send(encode_event(_START_CONNECTION, {}))
            await _expect_event(socket, _CONNECTION_STARTED, session=True)
        except BaseException:
            await socket.close()
            raise
        self._socket = socket
        return socket

    async def _invalidate_connection(self) -> None:
        async with self._connection_lock:
            await self._close_connection()

    async def _close_connection(self) -> None:
        socket, self._socket = self._socket, None
        if socket is None:
            return
        with contextlib.suppress(Exception):
            await socket.send(encode_event(_FINISH_CONNECTION, {}))
        await socket.close()


async def _expect_event(socket: Any, expected: int, *, session: bool) -> None:
    message = decode_message(await socket.recv(), event_has_session=session)
    _raise_provider_error(message, "TTS")
    if message.event != expected:
        raise LiveVoiceViolation("VOICE-TTS-PROTOCOL", "unexpected TTS event")


def _recognition_event(payload: Mapping[str, Any]) -> RecognitionEvent | None:
    result = payload.get("result")
    if not isinstance(result, Mapping):
        return None
    typed_result = cast(Mapping[str, object], result)
    text = typed_result.get("text")
    if not isinstance(text, str) or not text.strip():
        return None
    utterances = typed_result.get("utterances")
    ended = False
    if isinstance(utterances, list):
        typed_utterances = cast(list[object], utterances)
        ended = any(
            isinstance(item, Mapping)
            and cast(Mapping[str, object], item).get("definite") is True
            for item in typed_utterances
        )
    return RecognitionEvent(text=text.strip(), is_final=ended, utterance_ended=ended)


def _raise_provider_error(message: BinaryMessage, service: str) -> None:
    if message.message_type != _ERROR_RESPONSE:
        return
    raise LiveVoiceViolation(f"VOICE-{service}-PROVIDER", "provider returned an error")


def _header(
    message_type: int, flags: int, serialization: int, compression: int
) -> bytes:
    return bytes(
        (0x11, (message_type << 4) | flags, (serialization << 4) | compression, 0)
    )


def _read_i32(data: bytes, offset: int) -> tuple[int, int]:
    raw, offset = _read_bytes(data, offset, 4)
    return struct.unpack(">i", raw)[0], offset


def _read_u32(data: bytes, offset: int) -> tuple[int, int]:
    raw, offset = _read_bytes(data, offset, 4)
    return struct.unpack(">I", raw)[0], offset


def _read_bytes(data: bytes, offset: int, size: int) -> tuple[bytes, int]:
    end = offset + size
    if size < 0 or end > len(data):
        raise LiveVoiceViolation("VOICE-VOLC-FRAME", "provider frame is truncated")
    return data[offset:end], end


__all__ = (
    "ASR_ENDPOINT",
    "TTS_ENDPOINT",
    "BinaryMessage",
    "VolcCredentials",
    "VolcStreamingAsr",
    "VolcStreamingTts",
    "decode_message",
    "decode_volc_credentials",
    "encode_asr_audio",
    "encode_asr_full_request",
    "encode_event",
    "json_payload",
)
