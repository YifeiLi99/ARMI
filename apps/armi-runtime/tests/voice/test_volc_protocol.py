from __future__ import annotations

import gzip
import struct

import pytest
from armi_live_voice.api import LiveVoiceViolation
from armi_runtime.adapters.voice.volc import (
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
