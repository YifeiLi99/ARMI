"""Strict subset of OneBot 11 used by the NapCat channel driver."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
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
class NapCatGroupMessageEvent:
    time: int
    self_id: int
    message_id: str
    group_id: int
    user_id: int
    sender_label: str
    segments: tuple[tuple[str, dict[str, str]], ...]

    @property
    def mentioned_ids(self) -> frozenset[int]:
        values: set[int] = set()
        for kind, data in self.segments:
            if kind != "at":
                continue
            value = data.get("qq")
            if value is not None and value.isdecimal():
                values.add(int(value))
        return frozenset(values)

    def render_text(self) -> str | None:
        parts: list[str] = []
        for kind, data in self.segments:
            if kind == "text":
                parts.append(data.get("text", ""))
            elif kind == "at":
                value = data.get("qq", "")
                parts.append("@全体成员" if value == "all" else f"@QQ({value})")
            elif kind == "reply":
                value = data.get("id", "")
                parts.append(f"[回复消息 {value}]")
        text = "".join(parts).strip()
        return text if text else None


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
) -> NapCatGroupMessageEvent | NapCatActionResponse | None:
    if type(value) not in {str, bytes}:
        raise NapCatViolation("NAPCAT-FRAME-INVALID")
    try:
        document = json.loads(value)
    except UnicodeDecodeError, json.JSONDecodeError:
        raise NapCatViolation("NAPCAT-FRAME-INVALID") from None
    return parse_onebot_document(document)


def parse_onebot_document(
    document: object,
) -> NapCatGroupMessageEvent | NapCatActionResponse | None:
    if type(document) is not dict:
        raise NapCatViolation("NAPCAT-FRAME-INVALID")
    document = cast(dict[str, Any], document)
    if "echo" in document:
        return _parse_action_response(document)
    if (
        document.get("post_type") != "message"
        or document.get("message_type") != "group"
    ):
        return None
    return _parse_group_message(document)


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
    segments: list[tuple[str, dict[str, str]]] = []
    for raw in raw_segments:
        if type(raw) is not dict:
            raise NapCatViolation("NAPCAT-GROUP-EVENT-INVALID")
        raw = cast(dict[str, object], raw)
        if type(raw.get("type")) is not str:
            raise NapCatViolation("NAPCAT-GROUP-EVENT-INVALID")
        data = raw.get("data")
        if type(data) is not dict:
            raise NapCatViolation("NAPCAT-GROUP-EVENT-INVALID")
        data = cast(dict[object, object], data)
        normalized: dict[str, str] = {}
        for key, item in data.items():
            if type(key) is not str or type(item) not in {str, int}:
                continue
            normalized[key] = str(item)
        segments.append((cast(str, raw["type"]), normalized))
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
