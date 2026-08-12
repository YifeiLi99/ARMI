"""Strict subset of OneBot 11 used by the NapCat channel driver."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, cast

_CODE = re.compile(r"^NAPCAT-[A-Z0-9-]+$", re.ASCII)


class NapCatViolation(RuntimeError):
    __slots__ = ("code",)

    def __init__(self, code: str) -> None:
        if type(code) is not str or _CODE.fullmatch(code) is None:
            raise ValueError("NapCat violation code is invalid")
        self.code = code
        super().__init__("NapCat channel operation failed")

    def __str__(self) -> str:
        return f"{self.code}: NapCat channel operation failed"


class NapCatRejected(NapCatViolation):
    pass


class NapCatAmbiguousDelivery(NapCatViolation):
    pass


@dataclass(frozen=True, slots=True)
class NapCatMessageSegment:
    """Validated, immutable OneBot segment data used by the QQ adapter."""

    kind: str
    data: Mapping[str, str]

    def __post_init__(self) -> None:
        if type(self.kind) is not str or not self.kind or "\x00" in self.kind:
            raise NapCatViolation("NAPCAT-SEGMENT-INVALID")
        values = dict(self.data)
        if any(
            type(key) is not str
            or not key
            or "\x00" in key
            or type(value) is not str
            or "\x00" in value
            for key, value in values.items()
        ):
            raise NapCatViolation("NAPCAT-SEGMENT-INVALID")
        object.__setattr__(self, "data", MappingProxyType(values))


@dataclass(frozen=True, slots=True)
class NapCatGroupMessageEvent:
    time: int
    self_id: int
    message_id: str
    group_id: int
    user_id: int
    sender_label: str
    segments: tuple[NapCatMessageSegment, ...]

    @property
    def mentioned_ids(self) -> frozenset[int]:
        values: set[int] = set()
        for segment in self.segments:
            if segment.kind != "at":
                continue
            value = segment.data.get("qq")
            if value is not None and value.isdecimal():
                values.add(int(value))
        return frozenset(values)

    def render_text(self) -> str | None:
        return _render_text(self.segments)


@dataclass(frozen=True, slots=True)
class NapCatPrivateMessageEvent:
    time: int
    self_id: int
    message_id: str
    user_id: int
    sender_label: str
    segments: tuple[NapCatMessageSegment, ...]

    def render_text(self) -> str | None:
        return _render_text(self.segments)


@dataclass(frozen=True, slots=True)
class NapCatActionResponse:
    status: str
    retcode: int
    message_id: str | None
    echo: str

    @property
    def succeeded(self) -> bool:
        return self.status == "ok" and self.retcode == 0 and self.message_id is not None


def parse_onebot_message(
    value: str | bytes,
) -> NapCatGroupMessageEvent | NapCatPrivateMessageEvent | NapCatActionResponse | None:
    if type(value) not in {str, bytes}:
        raise NapCatViolation("NAPCAT-FRAME-INVALID")
    try:
        document = json.loads(value)
    except UnicodeDecodeError, json.JSONDecodeError:
        raise NapCatViolation("NAPCAT-FRAME-INVALID") from None
    return parse_onebot_document(document)


def parse_onebot_document(
    document: object,
) -> NapCatGroupMessageEvent | NapCatPrivateMessageEvent | NapCatActionResponse | None:
    if type(document) is not dict:
        raise NapCatViolation("NAPCAT-FRAME-INVALID")
    document = cast(dict[str, Any], document)
    if "echo" in document:
        return _parse_action_response(document)
    if document.get("post_type") != "message":
        return None
    message_type = document.get("message_type")
    if message_type == "group":
        return _parse_group_message(document)
    if message_type == "private":
        if document.get("sub_type") != "friend":
            return None
        return _parse_private_message(document)
    return None


def _parse_group_message(document: dict[str, Any]) -> NapCatGroupMessageEvent:
    try:
        time = _positive_int(document["time"])
        self_id = _positive_int(document["self_id"])
        message_id = _external_ref(document["message_id"])
        group_id = _positive_int(document["group_id"])
        user_id = _positive_int(document["user_id"])
        raw_segments = document["message"]
        sender = document["sender"]
    except KeyError, TypeError, ValueError:
        raise NapCatViolation("NAPCAT-GROUP-EVENT-INVALID") from None
    if type(raw_segments) is not list or type(sender) is not dict:
        raise NapCatViolation("NAPCAT-GROUP-EVENT-INVALID")
    raw_segments = cast(list[object], raw_segments)
    sender = cast(dict[str, object], sender)
    segments = _segments(raw_segments, "NAPCAT-GROUP-EVENT-INVALID")
    sender_label = sender.get("card") or sender.get("nickname") or str(user_id)
    if (
        type(sender_label) is not str
        or not sender_label.strip()
        or "\x00" in sender_label
    ):
        raise NapCatViolation("NAPCAT-GROUP-EVENT-INVALID")
    return NapCatGroupMessageEvent(
        time,
        self_id,
        message_id,
        group_id,
        user_id,
        sender_label.strip(),
        tuple(segments),
    )


def _parse_private_message(document: dict[str, Any]) -> NapCatPrivateMessageEvent:
    try:
        time = _positive_int(document["time"])
        self_id = _positive_int(document["self_id"])
        message_id = _external_ref(document["message_id"])
        user_id = _positive_int(document["user_id"])
        raw_segments = document["message"]
        sender = document["sender"]
    except KeyError, TypeError, ValueError:
        raise NapCatViolation("NAPCAT-PRIVATE-EVENT-INVALID") from None
    if type(raw_segments) is not list or type(sender) is not dict:
        raise NapCatViolation("NAPCAT-PRIVATE-EVENT-INVALID")
    segments = _segments(
        cast(list[object], raw_segments), "NAPCAT-PRIVATE-EVENT-INVALID"
    )
    typed_sender = cast(dict[str, object], sender)
    sender_label = typed_sender.get("nickname") or str(user_id)
    if (
        type(sender_label) is not str
        or not sender_label.strip()
        or "\x00" in sender_label
    ):
        raise NapCatViolation("NAPCAT-PRIVATE-EVENT-INVALID")
    return NapCatPrivateMessageEvent(
        time,
        self_id,
        message_id,
        user_id,
        sender_label.strip(),
        tuple(segments),
    )


def _segments(
    raw_segments: list[object], violation_code: str
) -> list[NapCatMessageSegment]:
    segments: list[NapCatMessageSegment] = []
    for raw in raw_segments:
        if type(raw) is not dict:
            raise NapCatViolation(violation_code)
        typed = cast(dict[str, object], raw)
        kind = typed.get("type")
        data = typed.get("data")
        if type(kind) is not str or type(data) is not dict:
            raise NapCatViolation(violation_code)
        normalized = _segment_data(kind, cast(dict[object, object], data))
        segments.append(NapCatMessageSegment(kind, normalized))
    return segments


def _segment_data(kind: str, data: dict[object, object]) -> dict[str, str]:
    allowed = {
        "text": ("text",),
        "at": ("qq", "name"),
        "reply": ("id",),
        "face": ("id", "resultId", "chainCount"),
        "dice": ("result",),
        "rps": ("result",),
        "poke": ("type", "id"),
        "image": (
            "file",
            "file_id",
            "file_size",
            "mime_type",
            "summary",
            "sub_type",
            "emoji_id",
            "emoji_package_id",
        ),
        "mface": (
            "file",
            "file_id",
            "file_size",
            "mime_type",
            "summary",
            "emoji_id",
            "emoji_package_id",
        ),
        "record": ("file", "file_id", "file_size", "mime_type"),
        "video": ("file", "file_id", "file_size", "mime_type"),
        "file": ("file", "file_id", "file_size", "mime_type", "name"),
    }.get(kind)
    normalized: dict[str, str] = {}
    keys = (
        allowed
        if allowed is not None
        else tuple(key for key in ("summary", "name", "title", "label") if key in data)
    )
    for key in keys:
        item = data.get(key)
        if type(item) in {str, int}:
            value = str(item)
            if "\x00" not in value:
                normalized[key] = value
    if kind == "face":
        raw = data.get("raw")
        if type(raw) is dict:
            face_text = cast(dict[object, object], raw).get("faceText")
            if type(face_text) is str and face_text and "\x00" not in face_text:
                normalized["face_text"] = face_text
    return normalized


def _render_text(segments: tuple[NapCatMessageSegment, ...]) -> str | None:
    parts: list[str] = []
    for segment in segments:
        if segment.kind == "text":
            parts.append(segment.data.get("text", ""))
        elif segment.kind == "at":
            value = segment.data.get("qq", "")
            parts.append("@全体成员" if value == "all" else f"@QQ({value})")
        elif segment.kind == "reply":
            value = segment.data.get("id", "")
            parts.append(f"[回复消息 {value}]")
    text = "".join(parts).strip()
    return text if text else None


def _parse_action_response(document: dict[str, Any]) -> NapCatActionResponse:
    status = document.get("status")
    retcode = document.get("retcode")
    echo = document.get("echo")
    data = document.get("data")
    if (
        status not in {"ok", "failed"}
        or type(retcode) is not int
        or type(echo) is not str
        or not echo
        or (data is not None and type(data) is not dict)
    ):
        raise NapCatViolation("NAPCAT-ACTION-RESPONSE-INVALID")
    typed_data = cast(dict[str, object], data) if isinstance(data, dict) else None
    raw_message_id = typed_data.get("message_id") if typed_data is not None else None
    message_id = None if raw_message_id is None else _external_ref(raw_message_id)
    return NapCatActionResponse(status, retcode, message_id, echo)


def _positive_int(value: object) -> int:
    if type(value) is not int or value <= 0:
        if type(value) is not str or not value.isdecimal() or value.startswith("0"):
            raise ValueError("positive integer required")
        parsed = int(value)
        if parsed <= 0:
            raise ValueError("positive integer required")
        return parsed
    return value


def _external_ref(value: object) -> str:
    if type(value) is int and value > 0:
        return str(value)
    if type(value) is str and value and len(value) <= 128 and "\x00" not in value:
        return value
    raise ValueError("external reference required")
