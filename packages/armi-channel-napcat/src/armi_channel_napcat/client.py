"""Authenticated loopback HTTP client for NapCat OneBot 11 actions."""

from __future__ import annotations

import base64
import binascii
import mimetypes
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal, Protocol, cast, runtime_checkable
from urllib.parse import urlsplit

import httpx

from .contracts import (
    NapCatActionResponse,
    NapCatAmbiguousDelivery,
    NapCatRejected,
    NapCatViolation,
    parse_onebot_document,
)


@runtime_checkable
class NapCatGateway(Protocol):
    async def send_group_text(
        self, *, group_id: int, text: str, echo: str
    ) -> NapCatActionResponse: ...

    async def send_private_text(
        self, *, user_id: int, text: str, echo: str
    ) -> NapCatActionResponse: ...

    async def get_message_sender(self, *, message_id: str) -> int | None: ...

    async def fetch_media(
        self, *, locator: str, kind: str, max_bytes: int
    ) -> NapCatDownloadedFile: ...


@dataclass(frozen=True, slots=True)
class NapCatDownloadedFile:
    content: bytes
    file_name: str
    media_type: str

    def __post_init__(self) -> None:
        if (
            type(self.content) is not bytes
            or not self.content
            or type(self.file_name) is not str
            or not self.file_name
            or "\x00" in self.file_name
            or type(self.media_type) is not str
            or not self.media_type
        ):
            raise NapCatViolation("NAPCAT-MEDIA-INVALID")


type NapCatHealthState = Literal[
    "login_required",
    "ready",
    "unavailable",
    "misconfigured",
]


@dataclass(frozen=True, slots=True)
class NapCatHealthSnapshot:
    state: NapCatHealthState
    api_reachable: bool
    account_online: bool | None
    account_matches: bool | None
    observed_at: str
    reason_codes: tuple[str, ...]


class NapCatHttpClient(NapCatGateway):
    """Use NapCat's HTTP action endpoint; incoming events use a separate webhook."""

    __slots__ = ("_client", "_owns_client")

    def __init__(
        self,
        *,
        base_url: str,
        access_token: str,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        _validate_base_url(base_url)
        if (
            type(access_token) is not str
            or not access_token
            or "\x00" in access_token
            or len(access_token.encode("utf-8")) > 4096
        ):
            raise NapCatViolation("NAPCAT-TOKEN-INVALID")
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=httpx.Timeout(30, connect=10),
            trust_env=False,
        )

    async def close(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def inspect_health(self, *, expected_account_id: int) -> NapCatHealthSnapshot:
        if type(expected_account_id) is not int or expected_account_id <= 0:
            raise NapCatViolation("NAPCAT-ACCOUNT-INVALID")
        observed_at = _observed_at()
        try:
            status = await self._read_health_action("/get_status")
        except NapCatViolation as error:
            return NapCatHealthSnapshot(
                "misconfigured"
                if error.code
                in {
                    "NAPCAT-HEALTH-AUTH-REJECTED",
                    "NAPCAT-HEALTH-RESPONSE-INVALID",
                }
                else "unavailable",
                error.code != "NAPCAT-HEALTH-UNAVAILABLE",
                None,
                None,
                observed_at,
                (error.code,),
            )
        online = status.get("online")
        good = status.get("good")
        if type(online) is not bool or type(good) is not bool:
            return NapCatHealthSnapshot(
                "misconfigured",
                True,
                None,
                None,
                observed_at,
                ("NAPCAT-HEALTH-RESPONSE-INVALID",),
            )
        if not online:
            return NapCatHealthSnapshot(
                "login_required",
                True,
                False,
                None,
                observed_at,
                ("NAPCAT-LOGIN-REQUIRED",),
            )
        if not good:
            return NapCatHealthSnapshot(
                "unavailable",
                True,
                True,
                None,
                observed_at,
                ("NAPCAT-STATUS-UNHEALTHY",),
            )
        try:
            login = await self._read_health_action("/get_login_info")
        except NapCatViolation as error:
            return NapCatHealthSnapshot(
                "misconfigured"
                if error.code
                in {
                    "NAPCAT-HEALTH-AUTH-REJECTED",
                    "NAPCAT-HEALTH-RESPONSE-INVALID",
                }
                else "unavailable",
                error.code != "NAPCAT-HEALTH-UNAVAILABLE",
                True,
                None,
                observed_at,
                (error.code,),
            )
        raw_account_id = login.get("user_id")
        account_id = (
            raw_account_id
            if type(raw_account_id) is int
            else int(raw_account_id)
            if type(raw_account_id) is str and raw_account_id.isdecimal()
            else None
        )
        if account_id is None or account_id <= 0:
            return NapCatHealthSnapshot(
                "misconfigured",
                True,
                True,
                None,
                observed_at,
                ("NAPCAT-HEALTH-RESPONSE-INVALID",),
            )
        if account_id != expected_account_id:
            return NapCatHealthSnapshot(
                "misconfigured",
                True,
                True,
                False,
                observed_at,
                ("NAPCAT-ACCOUNT-MISMATCH",),
            )
        return NapCatHealthSnapshot(
            "ready",
            True,
            True,
            True,
            observed_at,
            (),
        )

    async def send_group_text(
        self, *, group_id: int, text: str, echo: str
    ) -> NapCatActionResponse:
        return await self._send(
            "/send_group_msg", {"group_id": group_id, "message": text}, echo
        )

    async def send_private_text(
        self, *, user_id: int, text: str, echo: str
    ) -> NapCatActionResponse:
        return await self._send(
            "/send_private_msg", {"user_id": user_id, "message": text}, echo
        )

    async def get_message_sender(self, *, message_id: str) -> int | None:
        document = await self._read_action("/get_msg", {"message_id": message_id})
        data = document.get("data")
        if not isinstance(data, dict):
            raise NapCatViolation("NAPCAT-MESSAGE-LOOKUP-INVALID")
        sender = cast(dict[str, Any], data).get("sender")
        if not isinstance(sender, dict):
            return None
        raw_user_id = cast(dict[str, Any], sender).get("user_id")
        if type(raw_user_id) is int and raw_user_id > 0:
            return raw_user_id
        if type(raw_user_id) is str and raw_user_id.isdecimal():
            return int(raw_user_id)
        return None

    async def fetch_media(
        self, *, locator: str, kind: str, max_bytes: int
    ) -> NapCatDownloadedFile:
        if (
            type(locator) is not str
            or not locator
            or "\x00" in locator
            or kind not in {"image", "audio", "video", "file"}
            or type(max_bytes) is not int
            or max_bytes <= 0
        ):
            raise NapCatViolation("NAPCAT-MEDIA-INVALID")
        path = {
            "image": "/get_image",
            "audio": "/get_record",
            "video": "/get_file",
            "file": "/get_file",
        }[kind]
        payload: dict[str, int | str] = {"file": locator}
        if kind == "audio":
            payload["out_format"] = "mp3"
        document = await self._read_action(path, payload)
        data_value = document.get("data")
        if not isinstance(data_value, dict):
            raise NapCatViolation("NAPCAT-MEDIA-INVALID")
        data = cast(dict[str, Any], data_value)
        content = _media_bytes(data, max_bytes=max_bytes)
        raw_name = data.get("file_name")
        raw_path = data.get("file")
        file_name = (
            raw_name
            if type(raw_name) is str and raw_name
            else Path(raw_path).name
            if type(raw_path) is str and raw_path
            else f"qq-{kind}"
        )
        media_type = (
            mimetypes.guess_type(file_name)[0]
            or {
                "image": "application/octet-stream",
                "audio": "audio/mpeg",
                "video": "application/octet-stream",
                "file": "application/octet-stream",
            }[kind]
        )
        return NapCatDownloadedFile(content, file_name, media_type)

    async def _read_action(
        self, path: str, payload: Mapping[str, int | str]
    ) -> dict[str, Any]:
        try:
            response = await self._client.post(path, json=payload)
        except httpx.TimeoutException, httpx.NetworkError:
            raise NapCatViolation("NAPCAT-ACTION-UNAVAILABLE") from None
        if response.status_code < 200 or response.status_code >= 300:
            raise NapCatViolation("NAPCAT-ACTION-UNAVAILABLE")
        try:
            document: object = response.json()
        except ValueError:
            raise NapCatViolation("NAPCAT-ACTION-RESPONSE-INVALID") from None
        if not isinstance(document, dict):
            raise NapCatViolation("NAPCAT-ACTION-REJECTED")
        response_document = cast(dict[object, object], document)
        if (
            response_document.get("status") != "ok"
            or response_document.get("retcode") != 0
        ):
            raise NapCatViolation("NAPCAT-ACTION-REJECTED")
        return cast(dict[str, Any], response_document)

    async def _read_health_action(self, path: str) -> dict[str, Any]:
        try:
            response = await self._client.post(path, json={})
        except httpx.TimeoutException, httpx.NetworkError:
            raise NapCatViolation("NAPCAT-HEALTH-UNAVAILABLE") from None
        if response.status_code in {401, 403}:
            raise NapCatViolation("NAPCAT-HEALTH-AUTH-REJECTED")
        if response.status_code < 200 or response.status_code >= 300:
            raise NapCatViolation("NAPCAT-HEALTH-UNAVAILABLE")
        try:
            document: object = response.json()
        except ValueError:
            raise NapCatViolation("NAPCAT-HEALTH-RESPONSE-INVALID") from None
        if not isinstance(document, dict):
            raise NapCatViolation("NAPCAT-HEALTH-RESPONSE-INVALID")
        response_document = cast(dict[object, object], document)
        data = response_document.get("data")
        if (
            response_document.get("status") != "ok"
            or response_document.get("retcode") != 0
            or not isinstance(data, dict)
        ):
            raise NapCatViolation("NAPCAT-HEALTH-RESPONSE-INVALID")
        return cast(dict[str, Any], data)

    async def _send(
        self, path: str, payload: dict[str, int | str], echo: str
    ) -> NapCatActionResponse:
        try:
            response = await self._client.post(path, json=payload)
        except httpx.TimeoutException, httpx.NetworkError:
            raise NapCatAmbiguousDelivery("NAPCAT-DELIVERY-AMBIGUOUS") from None
        if response.status_code < 200 or response.status_code >= 300:
            if 400 <= response.status_code < 500:
                raise NapCatRejected("NAPCAT-DELIVERY-REJECTED")
            raise NapCatAmbiguousDelivery("NAPCAT-DELIVERY-AMBIGUOUS")
        try:
            document = response.json()
        except ValueError:
            raise NapCatViolation("NAPCAT-ACTION-RESPONSE-INVALID") from None
        if isinstance(document, dict):
            document["echo"] = echo
        # OneBot's HTTP endpoint correlates by its synchronous response and does
        # not define the WebSocket-level echo field. Keep the local request ref
        # only for the normalized response contract.
        parsed = parse_onebot_document(cast(object, document))
        if not isinstance(parsed, NapCatActionResponse):
            raise NapCatViolation("NAPCAT-ACTION-RESPONSE-INVALID")
        if not parsed.succeeded:
            raise NapCatRejected("NAPCAT-DELIVERY-REJECTED")
        return parsed


def _validate_base_url(value: str) -> None:
    if type(value) is not str:
        raise NapCatViolation("NAPCAT-URI-INVALID")
    parsed = urlsplit(value)
    if (
        parsed.scheme != "http"
        or parsed.hostname != "127.0.0.1"
        or parsed.port is None
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        raise NapCatViolation("NAPCAT-URI-NOT-LOOPBACK")


def _observed_at() -> str:
    return datetime.now(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _media_bytes(data: dict[str, Any], *, max_bytes: int) -> bytes:
    base64_value = data.get("base64")
    if type(base64_value) is str and base64_value:
        try:
            content = base64.b64decode(base64_value, validate=True)
        except binascii.Error, ValueError:
            raise NapCatViolation("NAPCAT-MEDIA-INVALID") from None
        if not content or len(content) > max_bytes:
            raise NapCatViolation("NAPCAT-MEDIA-TOO-LARGE")
        return content
    path_value = data.get("file")
    if type(path_value) is not str or not path_value:
        raise NapCatViolation("NAPCAT-MEDIA-INVALID")
    path = Path(path_value)
    try:
        size = path.stat().st_size
        if size <= 0 or size > max_bytes:
            raise NapCatViolation("NAPCAT-MEDIA-TOO-LARGE")
        chunks: list[bytes] = []
        remaining = max_bytes + 1
        with path.open("rb") as source:
            while remaining > 0:
                chunk = source.read(min(64 * 1024, remaining))
                if not chunk:
                    break
                chunks.append(chunk)
                remaining -= len(chunk)
        content = b"".join(chunks)
    except NapCatViolation:
        raise
    except OSError:
        raise NapCatViolation("NAPCAT-MEDIA-UNAVAILABLE") from None
    if len(content) > max_bytes:
        raise NapCatViolation("NAPCAT-MEDIA-TOO-LARGE")
    if len(content) != size:
        raise NapCatViolation("NAPCAT-MEDIA-UNAVAILABLE")
    return content


__all__ = (
    "NapCatDownloadedFile",
    "NapCatGateway",
    "NapCatHealthSnapshot",
    "NapCatHealthState",
    "NapCatHttpClient",
)
