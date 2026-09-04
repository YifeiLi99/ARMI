"""Creator health, session, Runtime, channel, voice, and vision routes."""

from __future__ import annotations

import re
from uuid import UUID

from armi_live_vision.api import LiveVisionViolation

from .creator_http import (
    BrowserSessionCurrentResponse,
    BrowserSessionResponse,
    BrowserSessionStore,
    BrowserSessionViolation,
    CreatorEventBroker,
    FastAPI,
    HTTPBearer,
    JSONResponse,
    LiveResponse,
    LiveVisionControlProvider,
    LiveVisionObservationProvider,
    LiveVisionObservationQueryProvider,
    LiveVisionObservationRequest,
    LiveVisionObservationResponse,
    LiveVisionPreviewProvider,
    LiveVisionStatusResponse,
    LiveVoiceControlProvider,
    LiveVoiceStatusResponse,
    QQChannelControlProvider,
    QQChannelHealthProvider,
    QQChannelHealthResponse,
    ReadinessProvider,
    ReadyResponse,
    RejectedOutcomeResponse,
    Request,
    Response,
    RuntimeStatusProvider,
    RuntimeStatusResponse,
    Security,
    SecurityEvent,
    UnavailableOutcomeResponse,
    _bearer,
    _browser_boundary,
    _metadata_wire,
    _rejected,
    _unavailable,
)


def register_system_routes(
    *,
    app: FastAPI,
    bearer: HTTPBearer,
    canonical_origin: str,
    emit: SecurityEvent,
    browser_sessions: BrowserSessionStore | None,
    creator_events: CreatorEventBroker | None,
    live_vision_control: LiveVisionControlProvider | None,
    live_vision_observe: LiveVisionObservationProvider | None,
    live_vision_observation: LiveVisionObservationQueryProvider | None,
    live_vision_preview: LiveVisionPreviewProvider | None,
    live_voice_control: LiveVoiceControlProvider | None,
    qq_channel_control: QQChannelControlProvider | None,
    qq_channel_health: QQChannelHealthProvider,
    readiness: ReadinessProvider,
    runtime_status: RuntimeStatusProvider,
) -> None:
    @app.get(
        "/health/live",
        operation_id="getHealthLive",
        response_model=LiveResponse,
    )
    async def health_live() -> LiveResponse:
        return LiveResponse(status="alive")

    @app.get(
        "/health/ready",
        operation_id="getHealthReady",
        response_model=ReadyResponse,
        responses={503: {"model": ReadyResponse}},
    )
    async def health_ready() -> JSONResponse:
        current = readiness()
        return JSONResponse(
            status_code=200 if current.value == "ready" else 503,
            content={"status": current.value},
        )

    @app.post(
        "/v1/browser-sessions",
        operation_id="createBrowserSession",
        response_model=BrowserSessionResponse,
        responses={
            403: {"model": RejectedOutcomeResponse},
            503: {"model": UnavailableOutcomeResponse},
        },
    )
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
        established = browser_sessions.establish()
        if creator_events is not None:
            await creator_events.close_active()
        emit("creator.session.established")
        response = BrowserSessionResponse(
            **_metadata_wire(established.metadata),
            browser_session_token=established.token,
        )
        return JSONResponse(content=response.model_dump(mode="json"))

    @app.get(
        "/v1/browser-sessions/current",
        operation_id="getCurrentBrowserSession",
        response_model=BrowserSessionCurrentResponse,
        responses={
            401: {"model": RejectedOutcomeResponse},
            403: {"model": RejectedOutcomeResponse},
        },
        dependencies=[Security(bearer)],
    )
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

    @app.get(
        "/v1/runtime/status",
        operation_id="getRuntimeStatus",
        response_model=RuntimeStatusResponse,
        responses={
            401: {"model": RejectedOutcomeResponse},
            403: {"model": RejectedOutcomeResponse},
            503: {"model": UnavailableOutcomeResponse},
        },
        dependencies=[Security(bearer)],
    )
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

    @app.get(
        "/v1/channels/qq/status",
        operation_id="getQQChannelHealth",
        response_model=QQChannelHealthResponse,
        responses={
            401: {"model": RejectedOutcomeResponse},
            403: {"model": RejectedOutcomeResponse},
            503: {"model": UnavailableOutcomeResponse},
        },
        dependencies=[Security(bearer)],
    )
    async def get_qq_channel_health(request: Request) -> JSONResponse:
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
        return JSONResponse(content=(await qq_channel_health()).model_dump(mode="json"))

    async def _qq_control(request: Request, action: str) -> JSONResponse:
        if (
            browser_sessions is None
            or qq_channel_control is None
            or not _browser_boundary(request, canonical_origin=canonical_origin)
        ):
            return JSONResponse(
                status_code=503,
                content=_unavailable("DEPENDENCY_QQ_CHANNEL_CONTROL_UNAVAILABLE"),
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
        return JSONResponse(
            content=(await qq_channel_control(action)).model_dump(mode="json")
        )

    @app.post(
        "/v1/channels/qq/start",
        operation_id="startQQChannel",
        response_model=QQChannelHealthResponse,
        dependencies=[Security(bearer)],
    )
    async def start_qq_channel(request: Request) -> JSONResponse:
        return await _qq_control(request, "start")

    @app.post(
        "/v1/channels/qq/stop",
        operation_id="stopQQChannel",
        response_model=QQChannelHealthResponse,
        dependencies=[Security(bearer)],
    )
    async def stop_qq_channel(request: Request) -> JSONResponse:
        return await _qq_control(request, "stop")

    async def _voice_control(request: Request, action: str) -> JSONResponse:
        if (
            browser_sessions is None
            or live_voice_control is None
            or not _browser_boundary(request, canonical_origin=canonical_origin)
        ):
            return JSONResponse(
                status_code=403 if browser_sessions is not None else 503,
                content=(
                    _rejected("AUTH_BROWSER_BOUNDARY")
                    if browser_sessions is not None and live_voice_control is not None
                    else _unavailable("DEPENDENCY_LIVE_VOICE_UNAVAILABLE")
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
        return JSONResponse(
            content=(await live_voice_control(action)).model_dump(mode="json")
        )

    @app.get(
        "/v1/voice/status",
        operation_id="getLiveVoiceStatus",
        response_model=LiveVoiceStatusResponse,
        dependencies=[Security(bearer)],
    )
    async def get_live_voice_status(request: Request) -> JSONResponse:
        return await _voice_control(request, "status")

    @app.post(
        "/v1/voice/start",
        operation_id="startLiveVoice",
        response_model=LiveVoiceStatusResponse,
        dependencies=[Security(bearer)],
    )
    async def start_live_voice(request: Request) -> JSONResponse:
        return await _voice_control(request, "start")

    @app.post(
        "/v1/voice/stop",
        operation_id="stopLiveVoice",
        response_model=LiveVoiceStatusResponse,
        dependencies=[Security(bearer)],
    )
    async def stop_live_voice(request: Request) -> JSONResponse:
        return await _voice_control(request, "stop")

    async def _vision_control(
        request: Request, action: str, source_kind: str | None = None
    ) -> JSONResponse:
        if (
            browser_sessions is None
            or live_vision_control is None
            or not _browser_boundary(request, canonical_origin=canonical_origin)
        ):
            return JSONResponse(
                status_code=503,
                content=_unavailable("DEPENDENCY_LIVE_VISION_UNAVAILABLE"),
            )
        token = _bearer(request)
        try:
            if token is None:
                raise BrowserSessionViolation("AUTH_SESSION_REQUIRED")
            browser_sessions.verify(token)
        except BrowserSessionViolation as error:
            return JSONResponse(
                status_code=error.status_code, content=_rejected(error.code)
            )
        try:
            result = await live_vision_control(action, source_kind)
        except LiveVisionViolation as error:
            return JSONResponse(
                status_code=400 if error.code == "VISION-SOURCE-KIND" else 503,
                content=_rejected(error.code.replace("-", "_")),
            )
        return JSONResponse(content=result.model_dump(mode="json"))

    @app.get(
        "/v1/vision/status",
        operation_id="getLiveVisionStatus",
        response_model=LiveVisionStatusResponse,
        dependencies=[Security(bearer)],
    )
    async def get_live_vision_status(  # pyright: ignore[reportUnusedFunction]
        request: Request,
    ) -> JSONResponse:
        return await _vision_control(request, "status", None)

    @app.post(
        "/v1/vision/sources/{source_kind}/start",
        operation_id="startLiveVisionSource",
        response_model=LiveVisionStatusResponse,
        dependencies=[Security(bearer)],
    )
    async def start_live_vision(  # pyright: ignore[reportUnusedFunction]
        request: Request,
        source_kind: str,
    ) -> JSONResponse:
        return await _vision_control(request, "start", source_kind)

    @app.post(
        "/v1/vision/sources/{source_kind}/stop",
        operation_id="stopLiveVisionSource",
        response_model=LiveVisionStatusResponse,
        dependencies=[Security(bearer)],
    )
    async def stop_live_vision(  # pyright: ignore[reportUnusedFunction]
        request: Request,
        source_kind: str,
    ) -> JSONResponse:
        return await _vision_control(request, "stop", source_kind)

    @app.post(
        "/v1/vision/observe",
        operation_id="observeLiveVision",
        response_model=LiveVisionObservationResponse,
        dependencies=[Security(bearer)],
        responses={202: {"model": LiveVisionObservationResponse}, 409: {}},
    )
    async def observe_live_vision(  # pyright: ignore[reportUnusedFunction]
        request: Request,
    ) -> JSONResponse:
        try:
            body = LiveVisionObservationRequest.model_validate(await request.json())
        except ValueError:
            return JSONResponse(
                status_code=400, content=_rejected("CON_VISION_REQUEST")
            )
        authorized = await _vision_control(
            request, "authorize_observe", body.source_kind
        )
        if authorized.status_code != 200:
            return authorized
        if live_vision_observe is None:
            return JSONResponse(
                status_code=503,
                content=_unavailable("DEPENDENCY_LIVE_VISION_UNAVAILABLE"),
            )
        key = request.headers.get("idempotency-key")
        if (
            key is None
            or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}", key) is None
        ):
            return JSONResponse(
                status_code=400, content=_rejected("CON_IDEMPOTENCY_KEY")
            )
        try:
            result = await live_vision_observe(body.source_kind, key)
        except LiveVisionViolation as error:
            return JSONResponse(
                status_code=409 if error.code == "VISION-IDEMPOTENCY-CONFLICT" else 503,
                content=_rejected(error.code.replace("-", "_")),
            )
        except ValueError:
            return JSONResponse(
                status_code=400, content=_rejected("CON_VISION_REQUEST")
            )
        return JSONResponse(
            status_code=202
            if result.status
            in {"capture_pending", "capturing", "registered", "recognizing"}
            else 200,
            content=result.model_dump(mode="json"),
        )

    @app.get(
        "/v1/vision/observations/{observation_id}",
        operation_id="getLiveVisionObservation",
        response_model=LiveVisionObservationResponse,
        dependencies=[Security(bearer)],
        responses={404: {}},
    )
    async def get_live_vision_observation(  # pyright: ignore[reportUnusedFunction]
        request: Request, observation_id: str
    ) -> JSONResponse:
        authorized = await _vision_control(request, "authorize_observation")
        if authorized.status_code != 200:
            return authorized
        try:
            parsed = UUID(observation_id)
            if parsed.version != 7 or str(parsed) != observation_id:
                raise ValueError
        except ValueError:
            return JSONResponse(status_code=404, content=_rejected("VISION_NOT_FOUND"))
        result = (
            None
            if live_vision_observation is None
            else await live_vision_observation(parsed)
        )
        if result is None:
            return JSONResponse(status_code=404, content=_rejected("VISION_NOT_FOUND"))
        return JSONResponse(content=result.model_dump(mode="json"))

    @app.get(
        "/v1/vision/sources/{source_kind}/preview",
        operation_id="getLiveVisionSourcePreview",
        response_class=Response,
        responses={200: {"content": {"image/jpeg": {}}}, 404: {}},
        dependencies=[Security(bearer)],
    )
    async def get_live_vision_preview(  # pyright: ignore[reportUnusedFunction]
        request: Request,
        source_kind: str,
    ) -> Response:
        denied = await _vision_control(request, "authorize_preview", source_kind)
        if denied.status_code != 200:
            return denied
        jpeg = None if live_vision_preview is None else live_vision_preview(source_kind)
        if jpeg is None:
            return Response(status_code=404, headers={"Cache-Control": "no-store"})
        return Response(
            content=jpeg,
            media_type="image/jpeg",
            headers={"Cache-Control": "no-store"},
        )

    route_handlers = (
        health_live,
        health_ready,
        create_browser_session,
        current_browser_session,
        get_runtime_status,
        get_qq_channel_health,
        start_qq_channel,
        stop_qq_channel,
        get_live_voice_status,
        start_live_voice,
        stop_live_voice,
    )
    del route_handlers


__all__ = ("register_system_routes",)
