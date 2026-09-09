"""Creator health, session, Runtime, channel, voice, and vision routes."""

from __future__ import annotations

from armi_runtime.application.creator_system import CreatorSystem
from armi_runtime.application.interaction import InteractionResult

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
    LiveVisionObservationRequest,
    LiveVisionObservationResponse,
    LiveVisionStatusResponse,
    LiveVoiceStatusResponse,
    QQChannelHealthResponse,
    ReadyResponse,
    RejectedOutcomeResponse,
    Request,
    Response,
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
from .interaction_authority import verify_interaction
from .system_commands import invoke_system


def _system_authorize(
    request: Request, sessions: BrowserSessionStore | None, origin: str
) -> JSONResponse | None:
    if sessions is None:
        return JSONResponse(
            status_code=503,
            content=_unavailable("DEPENDENCY_CREATOR_SESSION_UNAVAILABLE"),
        )
    if not _browser_boundary(request, canonical_origin=origin):
        return JSONResponse(status_code=403, content=_rejected("AUTH_BROWSER_BOUNDARY"))
    try:
        verify_interaction(request, sessions, _bearer(request))
    except BrowserSessionViolation as error:
        return JSONResponse(
            status_code=error.status_code, content=_rejected(error.code)
        )
    return None


def _system_response(result: InteractionResult) -> Response:
    if result.content is not None:
        return Response(
            content=result.content,
            status_code=result.status_code,
            media_type=result.media_type,
            headers={"Cache-Control": "no-store"},
        )
    return JSONResponse(content=dict(result.payload), status_code=result.status_code)


def register_system_routes(
    *,
    app: FastAPI,
    bearer: HTTPBearer,
    canonical_origin: str,
    emit: SecurityEvent,
    browser_sessions: BrowserSessionStore | None,
    creator_events: CreatorEventBroker | None,
    system: CreatorSystem,
) -> None:

    @app.get("/health/live", operation_id="getHealthLive", response_model=LiveResponse)
    async def health_live() -> Response:
        return _system_response(await invoke_system(system, "health_live", {}))

    @app.get(
        "/health/ready",
        operation_id="getHealthReady",
        response_model=ReadyResponse,
        responses={503: {"model": ReadyResponse}},
    )
    async def health_ready() -> Response:
        return _system_response(await invoke_system(system, "health_ready", {}))

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
                status_code=403, content=_rejected("AUTH_BROWSER_BOUNDARY")
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
                content=_rejected("AUTH_BROWSER_BOUNDARY")
                if browser_sessions is not None
                else _unavailable("DEPENDENCY_CREATOR_SESSION_UNAVAILABLE"),
            )
        token = _bearer(request)
        try:
            if token is None:
                raise BrowserSessionViolation("AUTH_SESSION_REQUIRED")
            metadata = browser_sessions.verify(token)
        except BrowserSessionViolation as error:
            emit("creator.session.rejected")
            return JSONResponse(
                status_code=error.status_code, content=_rejected(error.code)
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
    async def get_runtime_status(request: Request) -> Response:
        denied = _system_authorize(request, browser_sessions, canonical_origin)
        if denied is not None:
            return denied
        return _system_response(await invoke_system(system, "runtime_status", {}))

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
    async def get_qq_channel_health(request: Request) -> Response:
        denied = _system_authorize(request, browser_sessions, canonical_origin)
        if denied is not None:
            return denied
        return _system_response(await invoke_system(system, "channel_status", {}))

    @app.post(
        "/v1/channels/qq/start",
        operation_id="startQQChannel",
        response_model=QQChannelHealthResponse,
        dependencies=[Security(bearer)],
    )
    async def start_qq_channel(request: Request) -> Response:
        denied = _system_authorize(request, browser_sessions, canonical_origin)
        if denied is not None:
            return denied
        return _system_response(await invoke_system(system, "channel_start", {}))

    @app.post(
        "/v1/channels/qq/stop",
        operation_id="stopQQChannel",
        response_model=QQChannelHealthResponse,
        dependencies=[Security(bearer)],
    )
    async def stop_qq_channel(request: Request) -> Response:
        denied = _system_authorize(request, browser_sessions, canonical_origin)
        if denied is not None:
            return denied
        return _system_response(await invoke_system(system, "channel_stop", {}))

    @app.get(
        "/v1/voice/status",
        operation_id="getLiveVoiceStatus",
        response_model=LiveVoiceStatusResponse,
        dependencies=[Security(bearer)],
    )
    async def get_live_voice_status(request: Request) -> Response:
        denied = _system_authorize(request, browser_sessions, canonical_origin)
        if denied is not None:
            return denied
        return _system_response(await invoke_system(system, "voice_status", {}))

    @app.post(
        "/v1/voice/start",
        operation_id="startLiveVoice",
        response_model=LiveVoiceStatusResponse,
        dependencies=[Security(bearer)],
    )
    async def start_live_voice(request: Request) -> Response:
        denied = _system_authorize(request, browser_sessions, canonical_origin)
        if denied is not None:
            return denied
        return _system_response(await invoke_system(system, "voice_start", {}))

    @app.post(
        "/v1/voice/stop",
        operation_id="stopLiveVoice",
        response_model=LiveVoiceStatusResponse,
        dependencies=[Security(bearer)],
    )
    async def stop_live_voice(request: Request) -> Response:
        denied = _system_authorize(request, browser_sessions, canonical_origin)
        if denied is not None:
            return denied
        return _system_response(await invoke_system(system, "voice_stop", {}))

    @app.get(
        "/v1/vision/status",
        operation_id="getLiveVisionStatus",
        response_model=LiveVisionStatusResponse,
        dependencies=[Security(bearer)],
    )
    async def get_live_vision_status(request: Request) -> Response:
        denied = _system_authorize(request, browser_sessions, canonical_origin)
        if denied is not None:
            return denied
        return _system_response(await invoke_system(system, "vision_status", {}))

    @app.post(
        "/v1/vision/sources/{source_kind}/start",
        operation_id="startLiveVisionSource",
        response_model=LiveVisionStatusResponse,
        dependencies=[Security(bearer)],
    )
    async def start_live_vision(request: Request, source_kind: str) -> Response:
        denied = _system_authorize(request, browser_sessions, canonical_origin)
        if denied is not None:
            return denied
        return _system_response(
            await invoke_system(system, "vision_start", {"source_kind": source_kind})
        )

    @app.post(
        "/v1/vision/sources/{source_kind}/stop",
        operation_id="stopLiveVisionSource",
        response_model=LiveVisionStatusResponse,
        dependencies=[Security(bearer)],
    )
    async def stop_live_vision(request: Request, source_kind: str) -> Response:
        denied = _system_authorize(request, browser_sessions, canonical_origin)
        if denied is not None:
            return denied
        return _system_response(
            await invoke_system(system, "vision_stop", {"source_kind": source_kind})
        )

    @app.post(
        "/v1/vision/observe",
        operation_id="observeLiveVision",
        response_model=LiveVisionObservationResponse,
        dependencies=[Security(bearer)],
        responses={202: {"model": LiveVisionObservationResponse}, 409: {}},
    )
    async def observe_live_vision(request: Request) -> Response:
        denied = _system_authorize(request, browser_sessions, canonical_origin)
        if denied is not None:
            return denied
        try:
            body = LiveVisionObservationRequest.model_validate(await request.json())
        except ValueError:
            return JSONResponse(
                status_code=400, content=_rejected("CON_VISION_REQUEST")
            )
        return _system_response(
            await invoke_system(
                system,
                "vision_observe",
                {
                    "source_kind": body.source_kind,
                    "idempotency_key": request.headers.get("idempotency-key", ""),
                },
            )
        )

    @app.get(
        "/v1/vision/observations/{observation_id}",
        operation_id="getLiveVisionObservation",
        response_model=LiveVisionObservationResponse,
        dependencies=[Security(bearer)],
        responses={404: {}},
    )
    async def get_live_vision_observation(
        request: Request, observation_id: str
    ) -> Response:
        denied = _system_authorize(request, browser_sessions, canonical_origin)
        if denied is not None:
            return denied
        return _system_response(
            await invoke_system(
                system, "vision_observation", {"observation_id": observation_id}
            )
        )

    @app.get(
        "/v1/vision/sources/{source_kind}/preview",
        operation_id="getLiveVisionSourcePreview",
        response_class=Response,
        responses={200: {"content": {"image/jpeg": {}}}, 404: {}},
        dependencies=[Security(bearer)],
    )
    async def get_live_vision_preview(request: Request, source_kind: str) -> Response:
        denied = _system_authorize(request, browser_sessions, canonical_origin)
        if denied is not None:
            return denied
        return _system_response(
            await invoke_system(system, "vision_preview", {"source_kind": source_kind})
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
        get_live_vision_status,
        start_live_vision,
        stop_live_vision,
        observe_live_vision,
        get_live_vision_observation,
        get_live_vision_preview,
    )
    del route_handlers


__all__ = ("register_system_routes",)
