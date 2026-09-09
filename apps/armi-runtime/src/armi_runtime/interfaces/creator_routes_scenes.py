"""Creator scene, message, event-stream, and social-record routes."""

from __future__ import annotations

from armi_runtime.application.creator_calls import CreatorUseCase
from armi_runtime.application.creator_commands import CreatorCommands
from armi_runtime.application.creator_records import create_record_use_cases

from .creator_http import (
    AcceptedOutcomeResponse,
    BrowserSessionStore,
    BrowserSessionViolation,
    ContractViolation,
    CreatorEventBroker,
    CreatorEventBrokerViolation,
    CreatorInputAcceptancePort,
    CreatorInputViolation,
    CreatorSceneCollectionResponse,
    CreatorScenePort,
    CreatorSceneResponse,
    FastAPI,
    HTTPBearer,
    JSONResponse,
    OtherHumanPartyRecordPageResponse,
    OtherHumanRecordQueryPort,
    OtherHumanSceneRecordPageResponse,
    OtherHumanTimelineRecordPageResponse,
    RejectedOutcomeResponse,
    Request,
    Response,
    SceneKey,
    SceneQueryViolation,
    SceneStatus,
    SceneTimelinePageResponse,
    SceneTimelineQuery,
    SceneTimelineQueryPort,
    Security,
    SecurityEvent,
    StreamingResponse,
    UnavailableOutcomeResponse,
    _accepted_wire,
    _bearer,
    _browser_boundary,
    _creator_input_request,
    _creator_scene_create_request,
    _input_failure,
    _rejected,
    _scene_wire,
    _single_header,
    _unavailable,
    parse_last_event_id,
    stream_creator_events,
)
from .creator_use_cases import invoke_creator_http
from .interaction_authority import (
    verify_interaction,
)


def register_scene_routes(
    *,
    app: FastAPI,
    commands: CreatorCommands,
    bearer: HTTPBearer,
    canonical_origin: str,
    emit: SecurityEvent,
    browser_sessions: BrowserSessionStore | None,
    creator_events: CreatorEventBroker | None,
    creator_input: CreatorInputAcceptancePort | None,
    creator_scenes: CreatorScenePort | None,
    other_human_record_query: OtherHumanRecordQueryPort | None,
    request_body_max_bytes: int,
    scene_timeline_query: SceneTimelineQueryPort | None,
) -> dict[str, CreatorUseCase]:
    use_cases = create_record_use_cases(
        scene_timeline_query=scene_timeline_query,
        other_human_record_query=other_human_record_query,
    )

    @app.get(
        "/v1/scenes",
        operation_id="listCreatorScenes",
        response_model=CreatorSceneCollectionResponse,
        responses={
            401: {"model": RejectedOutcomeResponse},
            403: {"model": RejectedOutcomeResponse},
            503: {"model": UnavailableOutcomeResponse},
        },
        dependencies=[Security(bearer)],
    )
    async def list_creator_scenes(request: Request) -> JSONResponse:
        if (
            (browser_sessions is None)
            or creator_scenes is None
            or (not _browser_boundary(request, canonical_origin=canonical_origin))
        ):
            status = (
                403
                if browser_sessions is not None and creator_scenes is not None
                else 503
            )
            return JSONResponse(
                status_code=status,
                content=_rejected("AUTH_BROWSER_BOUNDARY")
                if status == 403
                else _unavailable("DEPENDENCY_SCENE_QUERY_UNAVAILABLE"),
            )
        try:
            token = _bearer(request)
            if token is None:
                raise BrowserSessionViolation("AUTH_SESSION_REQUIRED")
            verify_interaction(request, browser_sessions, token)
            collection = await commands.list_scenes()
        except BrowserSessionViolation as error:
            return JSONResponse(
                status_code=error.status_code, content=_rejected(error.code)
            )
        except SceneQueryViolation:
            return JSONResponse(
                status_code=503,
                content=_unavailable("DEPENDENCY_SCENE_QUERY_UNAVAILABLE"),
            )
        response = CreatorSceneCollectionResponse(
            contract_version="1.0",
            projection_version="creator-scenes.v1",
            scenes=[_scene_wire(scene) for scene in collection.scenes],
        )
        return JSONResponse(content=response.model_dump(mode="json", exclude_none=True))

    @app.post(
        "/v1/scenes",
        operation_id="createCreatorScene",
        status_code=201,
        response_model=CreatorSceneResponse,
        responses={
            400: {"model": RejectedOutcomeResponse},
            401: {"model": RejectedOutcomeResponse},
            403: {"model": RejectedOutcomeResponse},
            409: {"model": RejectedOutcomeResponse},
            503: {"model": UnavailableOutcomeResponse},
        },
        dependencies=[Security(bearer)],
    )
    async def create_creator_scene(request: Request) -> JSONResponse:
        if (
            (browser_sessions is None)
            or creator_scenes is None
            or (not _browser_boundary(request, canonical_origin=canonical_origin))
        ):
            status = (
                403
                if browser_sessions is not None and creator_scenes is not None
                else 503
            )
            return JSONResponse(
                status_code=status,
                content=_rejected("AUTH_BROWSER_BOUNDARY")
                if status == 403
                else _unavailable("DEPENDENCY_SCENE_COMMAND_UNAVAILABLE"),
            )
        try:
            token = _bearer(request)
            if token is None:
                raise BrowserSessionViolation("AUTH_SESSION_REQUIRED")
            verify_interaction(request, browser_sessions, token)
            model = await _creator_scene_create_request(request, request_body_max_bytes)
            created = await commands.create_scene(model.scene_key)
        except BrowserSessionViolation as error:
            return JSONResponse(
                status_code=error.status_code, content=_rejected(error.code)
            )
        except SceneQueryViolation as error:
            if error.code == "SCENE-KEY-CONFLICT":
                return JSONResponse(
                    status_code=409, content=_rejected("CONFLICT_SCENE_KEY")
                )
            if error.code.startswith("CON-SCENE"):
                return JSONResponse(
                    status_code=400, content=_rejected("INPUT_SCENE_KEY")
                )
            return JSONResponse(
                status_code=503,
                content=_unavailable("DEPENDENCY_SCENE_COMMAND_UNAVAILABLE"),
            )
        return JSONResponse(
            status_code=201,
            content=_scene_wire(created).model_dump(mode="json", exclude_none=True),
        )

    async def transition_creator_scene(
        scene_key: str, request: Request, target_status: SceneStatus
    ) -> JSONResponse:
        if (
            (browser_sessions is None)
            or creator_scenes is None
            or (not _browser_boundary(request, canonical_origin=canonical_origin))
        ):
            status = (
                403
                if browser_sessions is not None and creator_scenes is not None
                else 503
            )
            return JSONResponse(
                status_code=status,
                content=_rejected("AUTH_BROWSER_BOUNDARY")
                if status == 403
                else _unavailable("DEPENDENCY_SCENE_COMMAND_UNAVAILABLE"),
            )
        try:
            token = _bearer(request)
            if token is None:
                raise BrowserSessionViolation("AUTH_SESSION_REQUIRED")
            verify_interaction(request, browser_sessions, token)
            changed = await commands.transition_scene(scene_key, target_status)
        except BrowserSessionViolation as error:
            return JSONResponse(
                status_code=error.status_code, content=_rejected(error.code)
            )
        except SceneQueryViolation as error:
            if error.code == "SCENE-NOT-VISIBLE":
                return JSONResponse(
                    status_code=404, content=_rejected("SCOPE_SCENE_NOT_VISIBLE")
                )
            if error.code.startswith("CON-SCENE"):
                return JSONResponse(
                    status_code=400, content=_rejected("INPUT_SCENE_KEY")
                )
            return JSONResponse(
                status_code=503,
                content=_unavailable("DEPENDENCY_SCENE_COMMAND_UNAVAILABLE"),
            )
        return JSONResponse(
            content=_scene_wire(changed).model_dump(mode="json", exclude_none=True)
        )

    @app.post(
        "/v1/scenes/{scene_key}/close",
        operation_id="closeCreatorScene",
        response_model=CreatorSceneResponse,
        responses={
            400: {"model": RejectedOutcomeResponse},
            401: {"model": RejectedOutcomeResponse},
            403: {"model": RejectedOutcomeResponse},
            404: {"model": RejectedOutcomeResponse},
            503: {"model": UnavailableOutcomeResponse},
        },
        dependencies=[Security(bearer)],
    )
    async def close_creator_scene(scene_key: str, request: Request) -> JSONResponse:
        return await transition_creator_scene(scene_key, request, SceneStatus.CLOSED)

    @app.post(
        "/v1/scenes/{scene_key}/reopen",
        operation_id="reopenCreatorScene",
        response_model=CreatorSceneResponse,
        responses={
            400: {"model": RejectedOutcomeResponse},
            401: {"model": RejectedOutcomeResponse},
            403: {"model": RejectedOutcomeResponse},
            404: {"model": RejectedOutcomeResponse},
            503: {"model": UnavailableOutcomeResponse},
        },
        dependencies=[Security(bearer)],
    )
    async def reopen_creator_scene(scene_key: str, request: Request) -> JSONResponse:
        return await transition_creator_scene(scene_key, request, SceneStatus.OPEN)

    del list_creator_scenes, create_creator_scene
    del close_creator_scene, reopen_creator_scene

    @app.get(
        "/v1/scenes/{scene_key}/timeline",
        operation_id="getSceneTimeline",
        response_model=SceneTimelinePageResponse,
        responses={
            400: {"model": RejectedOutcomeResponse},
            401: {"model": RejectedOutcomeResponse},
            403: {"model": RejectedOutcomeResponse},
            404: {"model": RejectedOutcomeResponse},
            409: {"model": RejectedOutcomeResponse},
            503: {"model": UnavailableOutcomeResponse},
        },
        dependencies=[Security(bearer)],
    )
    async def get_scene_timeline(scene_key: str, request: Request) -> Response:
        return await invoke_creator_http(
            request,
            "scene_timeline",
            use_cases["scene_timeline"],
            browser_sessions=browser_sessions,
            canonical_origin=canonical_origin,
            maximum_bytes=request_body_max_bytes,
        )

    del get_scene_timeline

    @app.get(
        "/v1/other-human-records",
        operation_id="listOtherHumanRecordParties",
        response_model=OtherHumanPartyRecordPageResponse,
        responses={
            400: {"model": RejectedOutcomeResponse},
            401: {"model": RejectedOutcomeResponse},
            403: {"model": RejectedOutcomeResponse},
            503: {"model": UnavailableOutcomeResponse},
        },
        dependencies=[Security(bearer)],
    )
    async def list_other_human_record_parties(request: Request) -> Response:
        return await invoke_creator_http(
            request,
            "other_human_list",
            use_cases["other_human_list"],
            browser_sessions=browser_sessions,
            canonical_origin=canonical_origin,
            maximum_bytes=request_body_max_bytes,
        )

    @app.get(
        "/v1/other-human-records/{party_id}/scenes",
        operation_id="listOtherHumanRecordScenes",
        response_model=OtherHumanSceneRecordPageResponse,
        responses={
            400: {"model": RejectedOutcomeResponse},
            401: {"model": RejectedOutcomeResponse},
            403: {"model": RejectedOutcomeResponse},
            404: {"model": RejectedOutcomeResponse},
            503: {"model": UnavailableOutcomeResponse},
        },
        dependencies=[Security(bearer)],
    )
    async def list_other_human_record_scenes(
        party_id: str, request: Request
    ) -> Response:
        return await invoke_creator_http(
            request,
            "other_human_scenes",
            use_cases["other_human_scenes"],
            browser_sessions=browser_sessions,
            canonical_origin=canonical_origin,
            maximum_bytes=request_body_max_bytes,
        )

    @app.get(
        "/v1/other-human-records/{party_id}/scenes/{scene_id}/timeline",
        operation_id="getOtherHumanRecordTimeline",
        response_model=OtherHumanTimelineRecordPageResponse,
        responses={
            400: {"model": RejectedOutcomeResponse},
            401: {"model": RejectedOutcomeResponse},
            403: {"model": RejectedOutcomeResponse},
            404: {"model": RejectedOutcomeResponse},
            503: {"model": UnavailableOutcomeResponse},
        },
        dependencies=[Security(bearer)],
    )
    async def get_other_human_record_timeline(
        party_id: str, scene_id: str, request: Request
    ) -> Response:
        return await invoke_creator_http(
            request,
            "other_human_timeline",
            use_cases["other_human_timeline"],
            browser_sessions=browser_sessions,
            canonical_origin=canonical_origin,
            maximum_bytes=request_body_max_bytes,
        )

    del list_other_human_record_parties, list_other_human_record_scenes
    del get_other_human_record_timeline

    @app.post(
        "/v1/scenes/{scene_key}/messages",
        operation_id="acceptCreatorMessage",
        status_code=202,
        response_model=AcceptedOutcomeResponse,
        responses={
            400: {"model": RejectedOutcomeResponse},
            401: {"model": RejectedOutcomeResponse},
            403: {"model": RejectedOutcomeResponse},
            404: {"model": RejectedOutcomeResponse},
            409: {"model": RejectedOutcomeResponse},
            413: {"model": RejectedOutcomeResponse},
            503: {"model": UnavailableOutcomeResponse},
        },
        dependencies=[Security(bearer)],
    )
    async def accept_creator_message(scene_key: str, request: Request) -> JSONResponse:
        if (
            (browser_sessions is None)
            or creator_input is None
            or (not _browser_boundary(request, canonical_origin=canonical_origin))
        ):
            status = 403 if browser_sessions is not None else 503
            return JSONResponse(
                status_code=status,
                content=_rejected("AUTH_BROWSER_BOUNDARY")
                if status == 403
                else _unavailable("DEPENDENCY_INPUT_ACCEPTANCE_UNAVAILABLE"),
            )
        token = _bearer(request)
        try:
            if token is None:
                raise BrowserSessionViolation("AUTH_SESSION_REQUIRED")
            verify_interaction(request, browser_sessions, token)
        except BrowserSessionViolation as error:
            return JSONResponse(
                status_code=error.status_code, content=_rejected(error.code)
            )
        idempotency_value = _single_header(request, b"idempotency-key")
        if idempotency_value is None:
            return JSONResponse(
                status_code=400, content=_rejected("INPUT_IDEMPOTENCY_KEY")
            )
        try:
            model = await _creator_input_request(request, request_body_max_bytes)
            acceptance = await commands.message(
                scene_key=scene_key,
                message=model.message,
                delegate_id=None,
                idempotency_key=idempotency_value,
            )
        except (ContractViolation, CreatorInputViolation) as error:
            if isinstance(error, ContractViolation):
                status, content = (400, _rejected("INPUT_IDEMPOTENCY_KEY"))
            else:
                status, content = _input_failure(error)
            emit("creator.input.rejected")
            return JSONResponse(status_code=status, content=content)
        return JSONResponse(status_code=202, content=_accepted_wire(acceptance))

    del accept_creator_message

    @app.get(
        "/v1/scenes/{scene_key}/events",
        operation_id="streamSceneEvents",
        response_class=StreamingResponse,
        responses={
            200: {
                "description": "Authenticated Creator projection invalidations.",
                "content": {
                    "text/event-stream": {
                        "schema": {
                            "type": "string",
                            "x-event-data-schema": {
                                "$ref": "#/components/schemas/CreatorProjectionEventResponse"
                            },
                        }
                    }
                },
            },
            400: {"model": RejectedOutcomeResponse},
            401: {"model": RejectedOutcomeResponse},
            403: {"model": RejectedOutcomeResponse},
            404: {"model": RejectedOutcomeResponse},
            409: {"model": RejectedOutcomeResponse},
            429: {"model": RejectedOutcomeResponse},
            503: {"model": UnavailableOutcomeResponse},
        },
        dependencies=[Security(bearer)],
    )
    async def get_scene_events(scene_key: str, request: Request) -> Response:
        if (
            (browser_sessions is None)
            or scene_timeline_query is None
            or creator_events is None
        ):
            return JSONResponse(
                status_code=503,
                content=_unavailable("DEPENDENCY_EVENT_STREAM_UNAVAILABLE"),
            )
        if not _browser_boundary(request, canonical_origin=canonical_origin):
            return JSONResponse(
                status_code=403, content=_rejected("AUTH_BROWSER_BOUNDARY")
            )
        if request.headers.get("accept") != "text/event-stream":
            return JSONResponse(
                status_code=400, content=_rejected("INPUT_EVENT_STREAM_ACCEPT")
            )
        try:
            last_event_id = parse_last_event_id(request.scope["headers"])
        except CreatorEventBrokerViolation as error:
            emit("creator.event_stream.parser_failure")
            return JSONResponse(
                status_code=error.status_code, content=_rejected(error.code)
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
            parsed_scene_key = SceneKey(scene_key)
        except SceneQueryViolation:
            return JSONResponse(
                status_code=404, content=_rejected("SCOPE_SCENE_NOT_VISIBLE")
            )
        try:
            await scene_timeline_query.query(
                SceneTimelineQuery(scene_key=parsed_scene_key, limit=1)
            )
        except SceneQueryViolation as error:
            if error.code == "SCENE-NOT-VISIBLE":
                return JSONResponse(
                    status_code=404, content=_rejected("SCOPE_SCENE_NOT_VISIBLE")
                )
            return JSONResponse(
                status_code=503,
                content=_unavailable("DEPENDENCY_EVENT_STREAM_UNAVAILABLE"),
            )
        try:
            subscription = await creator_events.subscribe(last_event_id)
        except CreatorEventBrokerViolation as error:
            emit(
                "creator.event_stream.gap"
                if error.status_code == 409
                else "creator.event_stream.parser_failure"
            )
            return JSONResponse(
                status_code=error.status_code, content=_rejected(error.code)
            )
        return StreamingResponse(
            stream_creator_events(
                subscription, sessions=browser_sessions, token=token, diagnostic=emit
            ),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
        )

    del get_scene_events
    return use_cases


__all__ = ("register_scene_routes",)
