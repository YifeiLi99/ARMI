"""Authenticated loopback HTTP ingress for NapCat OneBot event reports."""

from __future__ import annotations

import hashlib
import hmac

from armi_channel_napcat import (
    NapCatGroupMessageEvent,
    NapCatPrivateMessageEvent,
    NapCatViolation,
    parse_onebot_message,
)
from armi_interaction.api import ExternalMessageViolation
from fastapi import FastAPI, Request, Response

from .adapter import QQAdapterConfig, QQIngressAdapter


def create_qq_event_app(
    *,
    config: QQAdapterConfig,
    ingress: QQIngressAdapter,
    signing_secret: bytes,
    request_body_max_bytes: int,
) -> FastAPI:
    if type(signing_secret) is not bytes or not signing_secret:
        raise ValueError("QQ event signing secret is required")
    if not 1024 <= request_body_max_bytes <= 1_048_576:
        raise ValueError("QQ event body limit is invalid")
    app = FastAPI(
        title="ARMI QQ event ingress",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )

    async def accept_event(request: Request) -> Response:
        content_type = request.headers.get("content-type", "").split(";", 1)[0]
        if content_type.strip().lower() != "application/json":
            return Response(status_code=415)
        self_id = request.headers.get("x-self-id")
        if self_id is not None and self_id != str(config.account_id):
            return Response(status_code=403)
        body = bytearray()
        async for chunk in request.stream():
            body.extend(chunk)
            if len(body) > request_body_max_bytes:
                return Response(status_code=413)
        signature = request.headers.get("x-signature", "")
        expected = (
            "sha1=" + hmac.new(signing_secret, bytes(body), hashlib.sha1).hexdigest()
        )
        if not hmac.compare_digest(signature, expected):
            return Response(status_code=401)
        try:
            event = parse_onebot_message(bytes(body))
        except NapCatViolation:
            return Response(status_code=400)
        try:
            if isinstance(event, (NapCatGroupMessageEvent, NapCatPrivateMessageEvent)):
                await ingress.accept_event(event)
        except ExternalMessageViolation as error:
            if error.code.startswith("CON-"):
                return Response(status_code=400)
            if error.code.startswith("SCOPE-"):
                return Response(status_code=403)
            return Response(status_code=503)
        return Response(status_code=204)

    app.add_api_route("/", accept_event, methods=["POST"])
    return app


__all__ = ("create_qq_event_app",)
