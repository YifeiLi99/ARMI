"""The authenticated same-origin Creator HTTP surface."""

from __future__ import annotations

import json
import re
import secrets
from collections.abc import Awaitable, Callable
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any, Literal, TypedDict

from armi_kernel.contracts import (
    ErrorCategory,
    ErrorDescriptor,
    Instant,
    RejectedOutcome,
    TraceId,
    UnavailableOutcome,
)
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, RedirectResponse, Response
from pydantic import ValidationError

from .browser_sessions import (
    BrowserSessionStore,
    BrowserSessionViolation,
    SessionMetadata,
)
from .creator_contract import (
    BootstrapCodeResponse,
    BrowserSessionCreateRequest,
    BrowserSessionCurrentResponse,
    BrowserSessionResponse,
    LiveResponse,
    Readiness,
    ReadyResponse,
    RuntimeStatusResponse,
)
from .static_assets import StaticAssetStore

_BEARER = re.compile(r"^Bearer ([\x21-\x7e]{1,4096})$", re.ASCII)
_PROXY_HEADERS = frozenset(
    {
        "forwarded",
        "x-forwarded-for",
        "x-forwarded-host",
        "x-forwarded-port",
        "x-forwarded-proto",
    }
)
_SECURITY_HEADERS = {
    "Cache-Control": "no-store",
    "Content-Security-Policy": (
        "default-src 'none'; script-src 'self'; style-src 'self'; "
        "img-src 'self'; font-src 'self'; connect-src 'self'; "
        "base-uri 'none'; form-action 'self'; frame-ancestors 'none'"
    ),
    "Cross-Origin-Opener-Policy": "same-origin",
    "Permissions-Policy": (
        "camera=(), display-capture=(), geolocation=(), microphone=(), "
        "payment=(), usb=()"
    ),
    "Referrer-Policy": "no-referrer",
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
}

AsyncCallback = Callable[[], Awaitable[None]]
ReadinessProvider = Callable[[], Readiness]
RuntimeStatusProvider = Callable[[], RuntimeStatusResponse]
SecurityEvent = Callable[[str], None]


class _OutcomeArguments(TypedDict):
    trace_id: TraceId
    occurred_at: Instant


class _SessionMetadataWire(TypedDict):
    contract_version: Literal["1.0"]
    environment_id: str
    creator_party_id: str
    issued_at: str
    expires_at: str


def _outcome_common() -> _OutcomeArguments:
    return _OutcomeArguments(
        trace_id=TraceId(secrets.token_hex(16)),
        occurred_at=Instant(datetime.now(UTC)),
    )


def _rejected(
    code: str, message: str = "The request was rejected."
) -> dict[str, object]:
    category = ErrorCategory.INPUT if code.startswith("INPUT_") else ErrorCategory.AUTH
    return RejectedOutcome(
        **_outcome_common(),
        message=message,
        error=ErrorDescriptor(category, code),
    ).to_wire()


def _unavailable(code: str) -> dict[str, object]:
    return UnavailableOutcome(
        **_outcome_common(),
        message="The Creator session capability is unavailable.",
        error=ErrorDescriptor(ErrorCategory.DEPENDENCY, code),
    ).to_wire()


def _bearer(request: Request) -> str | None:
    authorization = request.headers.get("authorization")
    if authorization is None:
        return None
    match = _BEARER.fullmatch(authorization)
    return None if match is None else match.group(1)


def _metadata_wire(metadata: SessionMetadata) -> _SessionMetadataWire:
    return {
        "contract_version": "1.0",
        "environment_id": str(metadata.environment_id),
        "creator_party_id": str(metadata.creator_party_id),
        "issued_at": Instant(metadata.issued_at).to_wire(),
        "expires_at": Instant(metadata.expires_at).to_wire(),
    }


def _browser_boundary(request: Request, *, canonical_origin: str) -> bool:
    return (
        request.headers.get("sec-fetch-site") == "same-origin"
        and request.headers.get("sec-fetch-mode") == "cors"
        and request.headers.get("sec-fetch-dest") == "empty"
        and (
            request.method not in {"POST", "PUT", "PATCH", "DELETE"}
            or request.headers.get("origin") == canonical_origin
        )
    )


def _strict_object_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


async def _session_request(request: Request, maximum_bytes: int) -> str:
    if request.headers.get("content-type") != "application/json":
        raise BrowserSessionViolation("INPUT_CONTENT_TYPE", status_code=400)
    body = await request.body()
    if not body or len(body) > maximum_bytes:
        raise BrowserSessionViolation("INPUT_BODY", status_code=400)
    try:
        value = json.loads(
            body.decode("utf-8"),
            object_pairs_hook=_strict_object_pairs,
            parse_constant=lambda _value: (_ for _ in ()).throw(
                ValueError("non-finite JSON")
            ),
        )
        model = BrowserSessionCreateRequest.model_validate(value)
    except UnicodeDecodeError, ValueError, ValidationError:
        raise BrowserSessionViolation("INPUT_BODY", status_code=400) from None
    return model.bootstrap_code


def create_runtime_app(
    *,
    readiness: ReadinessProvider,
    runtime_status: RuntimeStatusProvider,
    assets: StaticAssetStore,
    browser_sessions: BrowserSessionStore | None,
    expected_authority: str,
    request_body_max_bytes: int,
    on_started: AsyncCallback,
    on_stopping: AsyncCallback,
    on_security_event: SecurityEvent | None = None,
) -> FastAPI:
    """Create the fixed Runtime app without implementation discovery."""

    canonical_origin = f"http://{expected_authority}"

    def ignore_security_event(_event: str) -> None:
        return None

    emit: SecurityEvent = (
        on_security_event if on_security_event is not None else ignore_security_event
    )

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        await on_started()
        try:
            yield
        finally:
            await on_stopping()

    app = FastAPI(
        title="ARMI Runtime",
        version="1.0",
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
        if request.headers.get("host") != expected_authority or any(
            name in request.headers for name in _PROXY_HEADERS
        ):
            emit("creator.request.boundary_rejected")
            return Response(status_code=421, headers=_SECURITY_HEADERS)
        if request.url.query and request.url.path.startswith("/v1/"):
            emit("creator.request.url_token_rejected")
            return Response(status_code=400, headers=_SECURITY_HEADERS)
        if request.url.path.startswith("/v1/") and "cookie" in request.headers:
            emit("creator.request.cookie_rejected")
            return Response(status_code=403, headers=_SECURITY_HEADERS)
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

    @app.post("/v1/browser-bootstrap-codes")
    async def issue_bootstrap(request: Request) -> JSONResponse:
        if browser_sessions is None:
            return JSONResponse(
                status_code=503,
                content=_unavailable("DEPENDENCY_CREATOR_SESSION_UNAVAILABLE"),
            )
        if (
            request.headers.get("origin") is not None
            or any(name.startswith("sec-fetch-") for name in request.headers)
            or request.headers.get("content-length") not in {None, "0"}
        ):
            emit("creator.bootstrap.boundary_rejected")
            return JSONResponse(
                status_code=403,
                content=_rejected("AUTH_CREATOR_REJECTED"),
            )
        token = _bearer(request)
        if token is None:
            emit("creator.bootstrap.rejected")
            return JSONResponse(
                status_code=401,
                content=_rejected("AUTH_CREATOR_REJECTED"),
            )
        try:
            issued = browser_sessions.issue(token)
        except BrowserSessionViolation as error:
            emit("creator.bootstrap.rejected")
            return JSONResponse(
                status_code=error.status_code,
                content=_rejected(error.code),
            )
        emit("creator.bootstrap.issued")
        response = BootstrapCodeResponse(
            contract_version="1.0",
            bootstrap_code=issued.code,
            expires_at=Instant(issued.expires_at).to_wire(),
        )
        return JSONResponse(content=response.model_dump(mode="json"))

    @app.post("/v1/browser-sessions")
    async def create_browser_session(request: Request) -> JSONResponse:
        if browser_sessions is None:
            return JSONResponse(
                status_code=503,
                content=_unavailable("DEPENDENCY_CREATOR_SESSION_UNAVAILABLE"),
            )
        if not _browser_boundary(request, canonical_origin=canonical_origin):
            emit("creator.session.boundary_rejected")
            return JSONResponse(
                status_code=403,
                content=_rejected("AUTH_BROWSER_BOUNDARY"),
            )
        try:
            code = await _session_request(request, request_body_max_bytes)
            established = browser_sessions.exchange(code)
        except BrowserSessionViolation as error:
            emit("creator.session.rejected")
            return JSONResponse(
                status_code=error.status_code,
                content=_rejected(error.code),
            )
        emit("creator.session.established")
        response = BrowserSessionResponse(
            **_metadata_wire(established.metadata),
            browser_session_token=established.token,
        )
        return JSONResponse(content=response.model_dump(mode="json"))

    @app.get("/v1/browser-sessions/current")
    async def current_browser_session(request: Request) -> JSONResponse:
        if browser_sessions is None or not _browser_boundary(
            request, canonical_origin=canonical_origin
        ):
            return JSONResponse(
                status_code=403 if browser_sessions is not None else 503,
                content=(
                    _rejected("AUTH_BROWSER_BOUNDARY")
                    if browser_sessions is not None
                    else _unavailable("DEPENDENCY_CREATOR_SESSION_UNAVAILABLE")
                ),
            )
        token = _bearer(request)
        try:
            if token is None:
                raise BrowserSessionViolation("AUTH_SESSION_REQUIRED")
            metadata = browser_sessions.verify(token)
        except BrowserSessionViolation as error:
            emit("creator.session.rejected")
            return JSONResponse(
                status_code=error.status_code,
                content=_rejected(error.code),
            )
        response = BrowserSessionCurrentResponse(**_metadata_wire(metadata))
        return JSONResponse(content=response.model_dump(mode="json"))

    @app.delete("/v1/browser-sessions/current", status_code=204)
    async def delete_browser_session(request: Request) -> Response:
        if browser_sessions is None or not _browser_boundary(
            request, canonical_origin=canonical_origin
        ):
            return JSONResponse(
                status_code=403 if browser_sessions is not None else 503,
                content=(
                    _rejected("AUTH_BROWSER_BOUNDARY")
                    if browser_sessions is not None
                    else _unavailable("DEPENDENCY_CREATOR_SESSION_UNAVAILABLE")
                ),
            )
        token = _bearer(request)
        try:
            if token is None:
                raise BrowserSessionViolation("AUTH_SESSION_REQUIRED")
            browser_sessions.revoke(token)
        except BrowserSessionViolation as error:
            return JSONResponse(
                status_code=error.status_code,
                content=_rejected(error.code),
            )
        emit("creator.session.revoked")
        return Response(status_code=204)

    @app.get("/v1/runtime/status")
    async def get_runtime_status(request: Request) -> JSONResponse:
        if browser_sessions is None or not _browser_boundary(
            request, canonical_origin=canonical_origin
        ):
            return JSONResponse(
                status_code=403 if browser_sessions is not None else 503,
                content=(
                    _rejected("AUTH_BROWSER_BOUNDARY")
                    if browser_sessions is not None
                    else _unavailable("DEPENDENCY_CREATOR_SESSION_UNAVAILABLE")
                ),
            )
        token = _bearer(request)
        try:
            if token is None:
                raise BrowserSessionViolation("AUTH_SESSION_REQUIRED")
            browser_sessions.verify(token)
        except BrowserSessionViolation as error:
            return JSONResponse(
                status_code=error.status_code,
                content=_rejected(error.code),
            )
        return JSONResponse(content=runtime_status().model_dump(mode="json"))

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

    route_handlers = (
        enforce_local_boundary,
        health_live,
        health_ready,
        issue_bootstrap,
        create_browser_session,
        current_browser_session,
        delete_browser_session,
        get_runtime_status,
        creator_redirect,
        creator_index,
        creator_asset,
    )
    del route_handlers
    return app


__all__ = ("create_runtime_app",)
