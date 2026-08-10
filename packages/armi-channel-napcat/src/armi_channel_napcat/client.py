"""Authenticated loopback HTTP client for NapCat OneBot 11 actions."""

from __future__ import annotations

import json
from typing import Protocol, runtime_checkable
from urllib.parse import urlsplit

import httpx

from .contracts import (
    NapCatActionResponse,
    NapCatAmbiguousDelivery,
    NapCatRejected,
    NapCatViolation,
    parse_onebot_message,
)


@runtime_checkable
class NapCatGateway(Protocol):
    async def send_group_text(
        self, *, group_id: int, text: str, echo: str
    ) -> NapCatActionResponse: ...


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

    async def send_group_text(
        self, *, group_id: int, text: str, echo: str
    ) -> NapCatActionResponse:
        if type(group_id) is not int or group_id <= 0:
            raise NapCatViolation("NAPCAT-GROUP-ID-INVALID")
        if (
            type(text) is not str
            or not text.strip()
            or "\x00" in text
            or len(text.encode("utf-8")) > 65536
        ):
            raise NapCatViolation("NAPCAT-MESSAGE-INVALID")
        if type(echo) is not str or not echo or len(echo) > 191 or "\x00" in echo:
            raise NapCatViolation("NAPCAT-ECHO-INVALID")
        try:
            response = await self._client.post(
                "/send_group_msg",
                json={"group_id": group_id, "message": text},
            )
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
        if type(document) is not dict:
            raise NapCatViolation("NAPCAT-ACTION-RESPONSE-INVALID")
        # OneBot's HTTP endpoint correlates by its synchronous response and does
        # not define the WebSocket-level echo field. Keep the local request ref
        # only for the normalized response contract.
        document["echo"] = echo
        parsed = parse_onebot_message(json.dumps(document, separators=(",", ":")))
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


__all__ = ("NapCatGateway", "NapCatHttpClient")
