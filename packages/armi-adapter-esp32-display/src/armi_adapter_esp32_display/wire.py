"""Strict JSON Lines codec for ``armi.mood-display.v2``."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any, cast

from .api import DisplayState, MoodDisplayViolation, ProbeResult

PROTOCOL_VERSION = "armi.mood-display.v2"
MAX_FRAME_BYTES = 512


def encode_state(state_id: str, state: DisplayState) -> bytes:
    return _encode(
        {
            "type": "state",
            "protocol_version": PROTOCOL_VERSION,
            "state_id": state_id,
            "mood_version": state.mood_version,
            "expression": state.expression.value,
            "foreground": state.foreground,
            "background": state.background,
            "energy": state.energy,
            "valid_for_seconds": 30,
        }
    )


def encode_ping(ping_id: str) -> bytes:
    return _encode(
        {"type": "ping", "protocol_version": PROTOCOL_VERSION, "ping_id": ping_id}
    )


def encode_pong(ping_id: str) -> bytes:
    return _encode(
        {"type": "pong", "protocol_version": PROTOCOL_VERSION, "ping_id": ping_id}
    )


def _encode(value: Mapping[str, object]) -> bytes:
    frame = (
        json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        + b"\n"
    )
    if len(frame) > MAX_FRAME_BYTES:
        raise MoodDisplayViolation("MOOD-DISPLAY-FRAME-LENGTH")
    return frame


def decode_frame(frame: bytes) -> dict[str, Any]:
    if not frame or len(frame) > MAX_FRAME_BYTES or not frame.endswith(b"\n"):
        raise MoodDisplayViolation("MOOD-DISPLAY-FRAME")
    try:
        value = cast(object, json.loads(frame.decode("utf-8", errors="strict")))
    except (UnicodeError, json.JSONDecodeError) as error:
        raise MoodDisplayViolation("MOOD-DISPLAY-FRAME") from error
    if not isinstance(value, dict):
        raise MoodDisplayViolation("MOOD-DISPLAY-PROTOCOL")
    document = cast(dict[str, Any], value)
    if document.get("protocol_version") != PROTOCOL_VERSION:
        raise MoodDisplayViolation("MOOD-DISPLAY-PROTOCOL")
    return document


def parse_hello(frame: bytes) -> ProbeResult:
    value = decode_frame(frame)
    if (
        set(value)
        != {
            "type",
            "protocol_version",
            "device_id",
            "firmware_version",
            "boot_id",
        }
        or value.get("type") != "hello"
    ):
        raise MoodDisplayViolation("MOOD-DISPLAY-HELLO")
    fields = tuple(value[key] for key in ("device_id", "firmware_version", "boot_id"))
    if any(not isinstance(item, str) or not item or len(item) > 64 for item in fields):
        raise MoodDisplayViolation("MOOD-DISPLAY-HELLO")
    return ProbeResult(fields[0], fields[1], PROTOCOL_VERSION, fields[2])


__all__ = (
    "MAX_FRAME_BYTES",
    "PROTOCOL_VERSION",
    "decode_frame",
    "encode_ping",
    "encode_pong",
    "encode_state",
    "parse_hello",
)
