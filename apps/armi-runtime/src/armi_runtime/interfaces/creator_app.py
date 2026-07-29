"""The deliberately narrow HTTP surface of the S008 Runtime steel frame."""

from __future__ import annotations

import re
import secrets
from collections.abc import Awaitable, Callable
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import TypedDict

from armi_kernel.contracts import (
    CONTRACT_VERSION,
    ErrorCategory,
    ErrorDescriptor,
    Instant,
    RejectedOutcome,
    TraceId,
    UnavailableOutcome,
)
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, RedirectResponse, Response

from .creator_contract import LiveResponse, Readiness, ReadyResponse
from .static_assets import StaticAssetStore

_BEARER = re.compile(r"^Bearer ([\x21-\x7e]{1,4096})$", re.ASCII)
_SECURITY_HEADERS = {
    "Cache-Control": "no-store",
    "Content-Security-Policy": (
        "default-src 'none'; script-src 'self'; style-src 'self'; "
        "img-src 'self'; font-src 'self'; connect-src 'none'; "
        "base-uri 'none'; form-action 'none'; frame-ancestors 'none'"
    ),
    "Cross-Origin-Opener-Policy": "same-origin",
    "Referrer-Policy": "no-referrer",
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
}

AsyncCallback = Callable[[], Awaitable[None]]
ReadinessProvider = Callable[[], Readiness]


class _OutcomeArguments(TypedDict):
    trace_id: TraceId
    occurred_at: Instant


def _outcome_common() -> _OutcomeArguments:
    return _OutcomeArguments(
        trace_id=TraceId(secrets.token_hex(16)),
        occurred_at=Instant(datetime.now(UTC)),
    )


def _authentication_required() -> dict[str, object]:
    outcome = RejectedOutcome(
        **_outcome_common(),
        message="A browser session bearer is required.",
        error=ErrorDescriptor(ErrorCategory.AUTH, "AUTH_SESSION_REQUIRED"),
    )
    return outcome.to_wire()


def _session_verifier_unavailable() -> dict[str, object]:
    outcome = UnavailableOutcome(
        **_outcome_common(),
        message="The browser session verifier is not available.",
        error=ErrorDescriptor(
            ErrorCategory.DEPENDENCY,
            "DEPENDENCY_SESSION_VERIFIER_UNAVAILABLE",
        ),
        recovery_hint="Complete M0-S018 before using the protected Runtime status.",
    )
    return outcome.to_wire()


def create_runtime_app(
    *,
    readiness: ReadinessProvider,
    assets: StaticAssetStore,
    expected_authority: str,
    request_body_max_bytes: int,
    on_started: AsyncCallback,
    on_stopping: AsyncCallback,
) -> FastAPI:
    """Create the fixed S008 app without implementation discovery."""

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        await on_started()
        try:
            yield
        finally:
            await on_stopping()

    app = FastAPI(
        title="ARMI Runtime steel frame",
        version=CONTRACT_VERSION,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        lifespan=lifespan,
    )

    @app.middleware("http")
    async def enforce_local_boundary(
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        if request.headers.get("host") != expected_authority:
            return Response(status_code=421, headers=_SECURITY_HEADERS)
        content_length = request.headers.get("content-length")
        if content_length is not None:
            try:
                length = int(content_length)
            except ValueError:
                return Response(status_code=400, headers=_SECURITY_HEADERS)
            if length < 0 or length > request_body_max_bytes:
                return Response(status_code=413, headers=_SECURITY_HEADERS)
        response = await call_next(request)
        for name, value in _SECURITY_HEADERS.items():
            response.headers.setdefault(name, value)
        return response

    @app.get("/health/live", response_model=LiveResponse)
    async def health_live() -> LiveResponse:
        return LiveResponse(status="alive")

    @app.get("/health/ready", response_model=ReadyResponse)
    async def health_ready() -> JSONResponse:
        current = readiness()
        return JSONResponse(
            status_code=200 if current.value == "ready" else 503,
            content={"status": current.value},
        )

    @app.get("/v1/runtime/status")
    async def runtime_status(request: Request) -> JSONResponse:
        authorization = request.headers.get("authorization")
        if authorization is None or _BEARER.fullmatch(authorization) is None:
            return JSONResponse(status_code=401, content=_authentication_required())
        return JSONResponse(
            status_code=503,
            content=_session_verifier_unavailable(),
        )

    @app.get("/ui", include_in_schema=False)
    async def creator_redirect() -> RedirectResponse:
        return RedirectResponse("/ui/", status_code=308)

    @app.get("/ui/", include_in_schema=False)
    async def creator_index() -> Response:
        asset = assets.get("index.html")
        assert asset is not None
        return Response(
            content=asset.content,
            media_type=asset.media_type,
            headers={"Cache-Control": asset.cache_control},
        )

    @app.get("/ui/{asset_path:path}", include_in_schema=False)
    async def creator_asset(asset_path: str) -> Response:
        asset = assets.get(asset_path)
        if asset is None:
            return Response(status_code=404)
        return Response(
            content=asset.content,
            media_type=asset.media_type,
            headers={"Cache-Control": asset.cache_control},
        )

    registered_handlers = (
        enforce_local_boundary,
        health_live,
        health_ready,
        runtime_status,
        creator_redirect,
        creator_index,
        creator_asset,
    )
    del registered_handlers
    return app


__all__ = ("create_runtime_app",)
