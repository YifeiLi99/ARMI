"""Creator scene, message, event-stream, and social-record routes."""

from __future__ import annotations

from .creator_http import (
    UTC,
    UUID,
    AcceptedOutcomeResponse,
    Any,
    BrowserSessionStore,
    BrowserSessionViolation,
    ContractViolation,
    CreatorEventBroker,
    CreatorEventBrokerViolation,
    CreatorInputAcceptancePort,
    CreatorInputCommand,
    CreatorInputViolation,
    CreatorProjectionInvalidation,
    CreatorResourceKind,
    CreatorSceneCollectionResponse,
    CreatorSceneCreateCommand,
    CreatorScenePort,
    CreatorSceneResponse,
    CreatorSceneStatusCommand,
    FastAPI,
    HTTPBearer,
    IdempotencyKey,
    Instant,
    JSONResponse,
    Literal,
    OpaqueCursor,
    OtherHumanPartyRecordPageResponse,
    OtherHumanPartyRecordResponse,
    OtherHumanRecordQueryPort,
    OtherHumanRecordViolation,
    OtherHumanSceneRecordPageResponse,
    OtherHumanSceneRecordResponse,
    OtherHumanTimelineRecordPageResponse,
    OtherHumanTimelineRecordResponse,
    RejectedOutcomeResponse,
    Request,
    Response,
    SceneKey,
    SceneQueryViolation,
    SceneStatus,
    SceneTimelineItemResponse,
    SceneTimelinePageResponse,
    SceneTimelineQuery,
    SceneTimelineQueryPort,
    Security,
    SecurityEvent,
    StreamingResponse,
    TraceId,
    UnavailableOutcomeResponse,
    _accepted_wire,
    _bearer,
    _browser_boundary,
    _creator_input_request,
    _creator_scene_create_request,
    _input_failure,
    _life_query_parameters,
    _rejected,
    _scene_wire,
    _single_header,
    _unavailable,
    cast,
    datetime,
    parse_last_event_id,
    secrets,
    stream_creator_events,
)


def register_scene_routes(
    *,
    app: FastAPI,
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
) -> None:
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
            browser_sessions is None
            or creator_scenes is None
            or not _browser_boundary(request, canonical_origin=canonical_origin)
        ):
            status = (
                403
                if browser_sessions is not None and creator_scenes is not None
                else 503
            )
            return JSONResponse(
                status_code=status,
                content=(
                    _rejected("AUTH_BROWSER_BOUNDARY")
                    if status == 403
                    else _unavailable("DEPENDENCY_SCENE_QUERY_UNAVAILABLE")
                ),
            )
        try:
            token = _bearer(request)
            if token is None:
                raise BrowserSessionViolation("AUTH_SESSION_REQUIRED")
            browser_sessions.verify(token)
            collection = await creator_scenes.list()
        except BrowserSessionViolation as error:
            return JSONResponse(
                status_code=error.status_code,
                content=_rejected(error.code),
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
            browser_sessions is None
            or creator_scenes is None
            or not _browser_boundary(request, canonical_origin=canonical_origin)
        ):
            status = (
                403
                if browser_sessions is not None and creator_scenes is not None
                else 503
            )
            return JSONResponse(
                status_code=status,
                content=(
                    _rejected("AUTH_BROWSER_BOUNDARY")
                    if status == 403
                    else _unavailable("DEPENDENCY_SCENE_COMMAND_UNAVAILABLE")
                ),
            )
        try:
            token = _bearer(request)
            if token is None:
                raise BrowserSessionViolation("AUTH_SESSION_REQUIRED")
            browser_sessions.verify(token)
            model = await _creator_scene_create_request(
                request,
                request_body_max_bytes,
            )
            created = await creator_scenes.create(
                CreatorSceneCreateCommand(
                    SceneKey(model.scene_key),
                    TraceId(secrets.token_hex(16)),
                )
            )
        except BrowserSessionViolation as error:
            return JSONResponse(
                status_code=error.status_code,
                content=_rejected(error.code),
            )
        except SceneQueryViolation as error:
            if error.code == "SCENE-KEY-CONFLICT":
                return JSONResponse(
                    status_code=409,
                    content=_rejected("CONFLICT_SCENE_KEY"),
                )
            if error.code.startswith("CON-SCENE"):
                return JSONResponse(
                    status_code=400,
                    content=_rejected("INPUT_SCENE_KEY"),
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
        scene_key: str,
        request: Request,
        target_status: SceneStatus,
    ) -> JSONResponse:
        if (
            browser_sessions is None
            or creator_scenes is None
            or not _browser_boundary(request, canonical_origin=canonical_origin)
        ):
            status = (
                403
                if browser_sessions is not None and creator_scenes is not None
                else 503
            )
            return JSONResponse(
                status_code=status,
                content=(
                    _rejected("AUTH_BROWSER_BOUNDARY")
                    if status == 403
                    else _unavailable("DEPENDENCY_SCENE_COMMAND_UNAVAILABLE")
                ),
            )
        try:
            token = _bearer(request)
            if token is None:
                raise BrowserSessionViolation("AUTH_SESSION_REQUIRED")
            browser_sessions.verify(token)
            changed = await creator_scenes.set_status(
                CreatorSceneStatusCommand(
                    SceneKey(scene_key),
                    target_status,
                    TraceId(secrets.token_hex(16)),
                )
            )
        except BrowserSessionViolation as error:
            return JSONResponse(
                status_code=error.status_code,
                content=_rejected(error.code),
            )
        except SceneQueryViolation as error:
            if error.code == "SCENE-NOT-VISIBLE":
                return JSONResponse(
                    status_code=404,
                    content=_rejected("SCOPE_SCENE_NOT_VISIBLE"),
                )
            if error.code.startswith("CON-SCENE"):
                return JSONResponse(
                    status_code=400,
                    content=_rejected("INPUT_SCENE_KEY"),
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
    async def get_scene_timeline(scene_key: str, request: Request) -> JSONResponse:
        if (
            browser_sessions is None
            or scene_timeline_query is None
            or not _browser_boundary(request, canonical_origin=canonical_origin)
        ):
            status = (
                403
                if browser_sessions is not None and scene_timeline_query is not None
                else 503
            )
            return JSONResponse(
                status_code=status,
                content=(
                    _rejected("AUTH_BROWSER_BOUNDARY")
                    if status == 403
                    else _unavailable("DEPENDENCY_SCENE_QUERY_UNAVAILABLE")
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
        pairs = list(request.query_params.multi_items())
        names = [name for name, _value in pairs]
        if (
            set(names) - {"limit", "cursor"}
            or names.count("limit") != 1
            or names.count("cursor") > 1
        ):
            return JSONResponse(
                status_code=400,
                content=_rejected("INPUT_PAGE_LIMIT"),
            )
        values = dict(pairs)
        limit_text = values["limit"]
        if not limit_text.isascii() or not limit_text.isdecimal():
            return JSONResponse(
                status_code=400,
                content=_rejected("INPUT_PAGE_LIMIT"),
            )
        try:
            parsed_scene_key = SceneKey(scene_key)
        except SceneQueryViolation:
            return JSONResponse(
                status_code=404,
                content=_rejected("SCOPE_SCENE_NOT_VISIBLE"),
            )
        try:
            query = SceneTimelineQuery(
                scene_key=parsed_scene_key,
                limit=int(limit_text),
                cursor=(
                    OpaqueCursor.from_wire(values["cursor"])
                    if "cursor" in values
                    else None
                ),
            )
        except ContractViolation, SceneQueryViolation:
            code = "INPUT_CURSOR_INVALID" if "cursor" in values else "INPUT_PAGE_LIMIT"
            return JSONResponse(status_code=400, content=_rejected(code))
        try:
            page = await scene_timeline_query.query(query)
        except SceneQueryViolation as error:
            if error.code == "SCENE-NOT-VISIBLE":
                return JSONResponse(
                    status_code=404,
                    content=_rejected("SCOPE_SCENE_NOT_VISIBLE"),
                )
            if error.code == "SCENE-CURSOR-STALE":
                return JSONResponse(
                    status_code=409,
                    content=_rejected("CONFLICT_CURSOR_STALE"),
                )
            if error.code == "SCENE-CURSOR-INVALID":
                return JSONResponse(
                    status_code=400,
                    content=_rejected("INPUT_CURSOR_INVALID"),
                )
            return JSONResponse(
                status_code=503,
                content=_unavailable("DEPENDENCY_SCENE_QUERY_UNAVAILABLE"),
            )
        response = SceneTimelinePageResponse(
            contract_version="1.0",
            projection_version="scene-timeline.v5",
            scene_key=page.scene_key.value,
            items=[
                SceneTimelineItemResponse(
                    timeline_item_id=str(item.timeline_item_id),
                    source_kind=item.source_kind,
                    source_ref=str(item.source_ref),
                    status=item.status.value,
                    occurred_at=item.occurred_at.to_wire(),
                    operation_ref=(
                        str(item.operation_ref)
                        if item.operation_ref is not None
                        else None
                    ),
                    effect_ref=(
                        str(item.effect_ref) if item.effect_ref is not None else None
                    ),
                    message=item.message,
                    modality=cast(
                        Literal["text", "media_file", "live_voice"], item.modality
                    ),
                )
                for item in page.items
            ],
            next_cursor=(
                page.next_cursor.to_wire() if page.next_cursor is not None else None
            ),
        )
        return JSONResponse(content=response.model_dump(mode="json", exclude_none=True))

    del get_scene_timeline

    def _other_human_party_wire(item: Any) -> OtherHumanPartyRecordResponse:
        return OtherHumanPartyRecordResponse(
            party_id=str(item.party_id),
            party_key=item.party_key,
            display_label=item.display_label,
            scene_count=item.scene_count,
            record_count=item.record_count,
            last_record_at=(
                None
                if item.last_record_at is None
                else Instant(item.last_record_at).to_wire()
            ),
        )

    async def _other_human_record_scope(
        request: Request,
    ) -> tuple[int, OpaqueCursor | None] | JSONResponse:
        if (
            browser_sessions is None
            or other_human_record_query is None
            or not _browser_boundary(request, canonical_origin=canonical_origin)
        ):
            status = (
                403
                if browser_sessions is not None and other_human_record_query is not None
                else 503
            )
            return JSONResponse(
                status_code=status,
                content=(
                    _rejected("AUTH_BROWSER_BOUNDARY")
                    if status == 403
                    else _unavailable("DEPENDENCY_OTHER_HUMAN_RECORD_UNAVAILABLE")
                ),
            )
        try:
            token = _bearer(request)
            if token is None:
                raise BrowserSessionViolation("AUTH_SESSION_REQUIRED")
            browser_sessions.verify(token)
            limit, _query, _kind, cursor = _life_query_parameters(
                request, allow_kind=False, allow_text=False
            )
            return limit, cursor
        except BrowserSessionViolation as error:
            return JSONResponse(
                status_code=error.status_code, content=_rejected(error.code)
            )
        except ContractViolation:
            return JSONResponse(status_code=400, content=_rejected("INPUT_PAGE"))

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
    async def list_other_human_record_parties(request: Request) -> JSONResponse:
        scope = await _other_human_record_scope(request)
        if isinstance(scope, JSONResponse):
            return scope
        try:
            query = cast(OtherHumanRecordQueryPort, other_human_record_query)
            page = await query.list_parties(limit=scope[0], cursor=scope[1])
        except OtherHumanRecordViolation as error:
            status = 400 if error.code.endswith(("CURSOR", "LIMIT")) else 503
            return JSONResponse(
                status_code=status,
                content=(
                    _rejected("INPUT_PAGE")
                    if status == 400
                    else _unavailable("DEPENDENCY_OTHER_HUMAN_RECORD_UNAVAILABLE")
                ),
            )
        response = OtherHumanPartyRecordPageResponse(
            contract_version="1.0",
            projection_version="other-human-record.v1",
            items=[_other_human_party_wire(item) for item in page.items],
            next_cursor=None if page.next_cursor is None else page.next_cursor.value,
        )
        return JSONResponse(content=response.model_dump(mode="json", exclude_none=True))

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
    ) -> JSONResponse:
        scope = await _other_human_record_scope(request)
        if isinstance(scope, JSONResponse):
            return scope
        try:
            query = cast(OtherHumanRecordQueryPort, other_human_record_query)
            page = await query.list_scenes(
                UUID(party_id), limit=scope[0], cursor=scope[1]
            )
        except ValueError:
            return JSONResponse(
                status_code=400, content=_rejected("INPUT_OTHER_HUMAN_PARTY")
            )
        except OtherHumanRecordViolation as error:
            if error.code.endswith("NOT-VISIBLE"):
                return JSONResponse(
                    status_code=404,
                    content=_rejected("SCOPE_OTHER_HUMAN_RECORD_NOT_VISIBLE"),
                )
            status = 400 if error.code.endswith(("CURSOR", "LIMIT", "SCOPE")) else 503
            return JSONResponse(
                status_code=status,
                content=(
                    _rejected("INPUT_PAGE")
                    if status == 400
                    else _unavailable("DEPENDENCY_OTHER_HUMAN_RECORD_UNAVAILABLE")
                ),
            )
        response = OtherHumanSceneRecordPageResponse(
            contract_version="1.0",
            projection_version="other-human-record.v1",
            party=_other_human_party_wire(page.party),
            items=[
                OtherHumanSceneRecordResponse(
                    scene_id=str(item.scene_id),
                    scene_key=item.scene_key,
                    status=cast(Literal["open", "closed"], item.status),
                    record_count=item.record_count,
                    last_record_at=(
                        None
                        if item.last_record_at is None
                        else Instant(item.last_record_at).to_wire()
                    ),
                )
                for item in page.items
            ],
            next_cursor=None if page.next_cursor is None else page.next_cursor.value,
        )
        return JSONResponse(content=response.model_dump(mode="json", exclude_none=True))

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
    ) -> JSONResponse:
        scope = await _other_human_record_scope(request)
        if isinstance(scope, JSONResponse):
            return scope
        try:
            query = cast(OtherHumanRecordQueryPort, other_human_record_query)
            page = await query.timeline(
                UUID(party_id),
                UUID(scene_id),
                limit=scope[0],
                cursor=scope[1],
            )
        except ValueError:
            return JSONResponse(
                status_code=400,
                content=_rejected("INPUT_OTHER_HUMAN_RECORD_SCOPE"),
            )
        except OtherHumanRecordViolation as error:
            if error.code.endswith("NOT-VISIBLE"):
                return JSONResponse(
                    status_code=404,
                    content=_rejected("SCOPE_OTHER_HUMAN_RECORD_NOT_VISIBLE"),
                )
            status = 400 if error.code.endswith(("CURSOR", "LIMIT", "SCOPE")) else 503
            return JSONResponse(
                status_code=status,
                content=(
                    _rejected("INPUT_PAGE")
                    if status == 400
                    else _unavailable("DEPENDENCY_OTHER_HUMAN_RECORD_UNAVAILABLE")
                ),
            )
        response = OtherHumanTimelineRecordPageResponse(
            contract_version="1.0",
            projection_version="other-human-record.v1",
            party_id=str(page.party_id),
            scene_id=str(page.scene_id),
            items=[
                OtherHumanTimelineRecordResponse(
                    timeline_item_id=str(item.timeline_item_id),
                    source_ref=str(item.source_ref),
                    direction=item.direction.value,
                    status=cast(
                        Literal["accepted", "completed", "failed", "unknown"],
                        item.result_status,
                    ),
                    text=item.text,
                    occurred_at=Instant(item.occurred_at).to_wire(),
                )
                for item in page.items
            ],
            next_cursor=None if page.next_cursor is None else page.next_cursor.value,
        )
        return JSONResponse(content=response.model_dump(mode="json", exclude_none=True))

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
    async def accept_creator_message(
        scene_key: str,
        request: Request,
    ) -> JSONResponse:
        if (
            browser_sessions is None
            or creator_input is None
            or not _browser_boundary(request, canonical_origin=canonical_origin)
        ):
            status = 403 if browser_sessions is not None else 503
            return JSONResponse(
                status_code=status,
                content=(
                    _rejected("AUTH_BROWSER_BOUNDARY")
                    if status == 403
                    else _unavailable("DEPENDENCY_INPUT_ACCEPTANCE_UNAVAILABLE")
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
        idempotency_value = _single_header(request, b"idempotency-key")
        if idempotency_value is None:
            return JSONResponse(
                status_code=400,
                content=_rejected("INPUT_IDEMPOTENCY_KEY"),
            )
        try:
            model = await _creator_input_request(request, request_body_max_bytes)
            command = CreatorInputCommand(
                scene_key=scene_key,
                message=model.message,
                idempotency_key=IdempotencyKey(idempotency_value),
                trace_id=TraceId(secrets.token_hex(16)),
            )
            acceptance = await creator_input.accept(command)
        except (ContractViolation, CreatorInputViolation) as error:
            if isinstance(error, ContractViolation):
                status, content = 400, _rejected("INPUT_IDEMPOTENCY_KEY")
            else:
                status, content = _input_failure(error)
            emit("creator.input.rejected")
            return JSONResponse(status_code=status, content=content)
        emit(
            "creator.input.accepted"
            if acceptance.newly_accepted
            else "creator.input.idempotent"
        )
        if creator_events is not None and acceptance.newly_accepted:
            try:
                await creator_events.notify(
                    CreatorProjectionInvalidation(
                        CreatorResourceKind("operation"),
                        str(acceptance.opportunity_id),
                        Instant(datetime.now(UTC)),
                        "creator-operation.v2",
                    )
                )
            except Exception:
                emit("creator.operation.notification_failed")
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
                                "$ref": (
                                    "#/components/schemas/"
                                    "CreatorProjectionEventResponse"
                                )
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
    async def get_scene_events(
        scene_key: str,
        request: Request,
    ) -> Response:
        if (
            browser_sessions is None
            or scene_timeline_query is None
            or creator_events is None
        ):
            return JSONResponse(
                status_code=503,
                content=_unavailable("DEPENDENCY_EVENT_STREAM_UNAVAILABLE"),
            )
        if not _browser_boundary(request, canonical_origin=canonical_origin):
            return JSONResponse(
                status_code=403,
                content=_rejected("AUTH_BROWSER_BOUNDARY"),
            )
        if request.headers.get("accept") != "text/event-stream":
            return JSONResponse(
                status_code=400,
                content=_rejected("INPUT_EVENT_STREAM_ACCEPT"),
            )
        try:
            last_event_id = parse_last_event_id(request.scope["headers"])
        except CreatorEventBrokerViolation as error:
            emit("creator.event_stream.parser_failure")
            return JSONResponse(
                status_code=error.status_code,
                content=_rejected(error.code),
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
        try:
            parsed_scene_key = SceneKey(scene_key)
        except SceneQueryViolation:
            return JSONResponse(
                status_code=404,
                content=_rejected("SCOPE_SCENE_NOT_VISIBLE"),
            )
        try:
            await scene_timeline_query.query(
                SceneTimelineQuery(scene_key=parsed_scene_key, limit=1)
            )
        except SceneQueryViolation as error:
            if error.code == "SCENE-NOT-VISIBLE":
                return JSONResponse(
                    status_code=404,
                    content=_rejected("SCOPE_SCENE_NOT_VISIBLE"),
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
                status_code=error.status_code,
                content=_rejected(error.code),
            )
        return StreamingResponse(
            stream_creator_events(
                subscription,
                sessions=browser_sessions,
                token=token,
                diagnostic=emit,
            ),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-store",
                "X-Accel-Buffering": "no",
            },
        )

    del get_scene_events


__all__ = ("register_scene_routes",)
