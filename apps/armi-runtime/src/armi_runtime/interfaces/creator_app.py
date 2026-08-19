"""The authenticated same-origin Creator HTTP application shell."""

from __future__ import annotations

from .creator_http import (
    _PROXY_HEADERS,
    _SECURITY_HEADERS,
    ActivityReadPort,
    AsyncCallback,
    Awaitable,
    BrowserSessionStore,
    Callable,
    CapabilityPolicyPort,
    CreatorCodexTaskAdmissionPort,
    CreatorEmergencyWakePort,
    CreatorEventBroker,
    CreatorExportPort,
    CreatorInputAcceptance,
    CreatorInputAcceptancePort,
    CreatorLifeMaterialQueryPort,
    CreatorMaintenanceQueryPort,
    CreatorOperationQueryPort,
    CreatorPromptPort,
    CreatorScenePort,
    DataRightsOrderPort,
    EffectLedgerPort,
    FastAPI,
    HTTPBearer,
    LifeRecordQueryPort,
    LiveVisionControlProvider,
    LiveVisionPreviewProvider,
    LiveVoiceControlProvider,
    MemoryReadPort,
    OtherHumanInputPort,
    OtherHumanRecordQueryPort,
    QQChannelHealthProvider,
    ReadinessProvider,
    RedirectResponse,
    RelationshipReadPort,
    Request,
    Response,
    RuntimeStatusProvider,
    SceneTimelineQueryPort,
    SecurityEvent,
    StaticAsset,
    StaticAssetStore,
    SubjectSummaryProvider,
    asynccontextmanager,
    cast,
    re,
)
from .creator_routes_governance import register_governance_routes
from .creator_routes_local_other_humans import register_local_other_human_routes
from .creator_routes_operations import register_operation_routes
from .creator_routes_scenes import register_scene_routes
from .creator_routes_subject_life import register_subject_life_routes
from .creator_routes_system import register_system_routes


def create_runtime_app(
    *,
    readiness: ReadinessProvider,
    runtime_status: RuntimeStatusProvider,
    qq_channel_health: QQChannelHealthProvider,
    assets: StaticAssetStore,
    browser_sessions: BrowserSessionStore | None,
    expected_authority: str,
    request_body_max_bytes: int,
    on_started: AsyncCallback,
    on_stopping: AsyncCallback,
    creator_scenes: CreatorScenePort | None = None,
    scene_timeline_query: SceneTimelineQueryPort | None = None,
    creator_activity_query: ActivityReadPort | None = None,
    life_record_query: LifeRecordQueryPort | None = None,
    creator_life_material_query: CreatorLifeMaterialQueryPort | None = None,
    creator_memory_query: MemoryReadPort | None = None,
    creator_maintenance_query: CreatorMaintenanceQueryPort | None = None,
    creator_relationship_query: RelationshipReadPort | None = None,
    other_human_record_query: OtherHumanRecordQueryPort | None = None,
    creator_emergency_wake: CreatorEmergencyWakePort | None = None,
    creator_events: CreatorEventBroker | None = None,
    creator_input: CreatorInputAcceptancePort | None = None,
    other_human_input: OtherHumanInputPort | None = None,
    creator_operations: CreatorOperationQueryPort | None = None,
    subject_summary: SubjectSummaryProvider | None = None,
    creator_prompt: CreatorPromptPort | None = None,
    creator_export: CreatorExportPort | None = None,
    data_rights: DataRightsOrderPort | None = None,
    capability_policy: CapabilityPolicyPort | None = None,
    effect_ledger: EffectLedgerPort | None = None,
    codex_task_admission: CreatorCodexTaskAdmissionPort[CreatorInputAcceptance]
    | None = None,
    on_security_event: SecurityEvent | None = None,
    live_voice_control: LiveVoiceControlProvider | None = None,
    live_vision_control: LiveVisionControlProvider | None = None,
    live_vision_preview: LiveVisionPreviewProvider | None = None,
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
    bearer = HTTPBearer(scheme_name="browserSessionBearer", auto_error=False)

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
        timeline_path = re.fullmatch(
            r"/v1/scenes/[^/]{1,256}/timeline",
            request.url.path,
        )
        paged_query_path = (
            request.url.path
            in {"/v1/life-records", "/v1/memories", "/v1/other-human-records"}
            or re.fullmatch(
                r"/v1/(?:memories/[^/]{1,64}/timeline|other-human-records/[^/]{1,64}/scenes(?:/[^/]{1,64}/timeline)?)",
                request.url.path,
            )
            is not None
        )
        if (
            request.url.query
            and request.url.path.startswith("/v1/")
            and timeline_path is None
            and request.url.path != "/v1/capability-requests"
            and not paged_query_path
        ):
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

    register_system_routes(
        app=app,
        bearer=bearer,
        canonical_origin=canonical_origin,
        emit=emit,
        browser_sessions=browser_sessions,
        creator_events=creator_events,
        live_vision_control=live_vision_control,
        live_vision_preview=live_vision_preview,
        live_voice_control=live_voice_control,
        qq_channel_health=qq_channel_health,
        readiness=readiness,
        runtime_status=runtime_status,
    )
    register_subject_life_routes(
        app=app,
        bearer=bearer,
        canonical_origin=canonical_origin,
        emit=emit,
        browser_sessions=browser_sessions,
        creator_activity_query=creator_activity_query,
        creator_emergency_wake=creator_emergency_wake,
        creator_events=creator_events,
        creator_input=creator_input,
        creator_life_material_query=creator_life_material_query,
        creator_maintenance_query=creator_maintenance_query,
        creator_memory_query=creator_memory_query,
        creator_prompt=creator_prompt,
        creator_relationship_query=creator_relationship_query,
        life_record_query=life_record_query,
        request_body_max_bytes=request_body_max_bytes,
        subject_summary=subject_summary,
    )
    register_governance_routes(
        app=app,
        bearer=bearer,
        canonical_origin=canonical_origin,
        emit=emit,
        browser_sessions=browser_sessions,
        capability_policy=capability_policy,
        creator_events=creator_events,
        creator_export=creator_export,
        data_rights=data_rights,
        request_body_max_bytes=request_body_max_bytes,
    )
    register_scene_routes(
        app=app,
        bearer=bearer,
        canonical_origin=canonical_origin,
        emit=emit,
        browser_sessions=browser_sessions,
        creator_events=creator_events,
        creator_input=creator_input,
        creator_scenes=creator_scenes,
        other_human_record_query=other_human_record_query,
        request_body_max_bytes=request_body_max_bytes,
        scene_timeline_query=scene_timeline_query,
    )
    register_operation_routes(
        app=app,
        bearer=bearer,
        canonical_origin=canonical_origin,
        emit=emit,
        browser_sessions=browser_sessions,
        codex_task_admission=codex_task_admission,
        creator_operations=creator_operations,
        effect_ledger=effect_ledger,
        request_body_max_bytes=request_body_max_bytes,
    )
    register_local_other_human_routes(
        app=app,
        data_rights=data_rights,
        other_human_input=other_human_input,
        request_body_max_bytes=request_body_max_bytes,
    )

    @app.get("/ui", include_in_schema=False)
    async def creator_redirect() -> RedirectResponse:
        return RedirectResponse("/ui/", status_code=308)

    @app.get("/ui/", include_in_schema=False)
    async def creator_index() -> Response:
        asset = cast(StaticAsset, assets.get("index.html"))
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
        creator_redirect,
        creator_index,
        creator_asset,
    )
    del route_handlers
    return app


__all__ = ("create_runtime_app",)
