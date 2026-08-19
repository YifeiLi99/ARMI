"""Creator subject, prompt, activity, relationship, memory, and maintenance routes."""

from __future__ import annotations

from .creator_http import (
    UTC,
    UUID,
    AcceptedOutcomeResponse,
    ActivityReadPort,
    ActivityViolation,
    BrowserSessionStore,
    BrowserSessionViolation,
    ContractViolation,
    CreatorActivityItemResponse,
    CreatorActivityPageResponse,
    CreatorActivityTimelineItemResponse,
    CreatorActivityTimelineResponse,
    CreatorEmergencyWakePort,
    CreatorEventBroker,
    CreatorInputAcceptancePort,
    CreatorInputCommand,
    CreatorInputViolation,
    CreatorLifeMaterialQueryPort,
    CreatorLifeMaterialResponse,
    CreatorMaintenanceQueryPort,
    CreatorMaintenanceSessionResponse,
    CreatorMaintenanceStatusResponse,
    CreatorMaintenanceTimelineItemResponse,
    CreatorMaintenanceTimelineResponse,
    CreatorMaintenanceViolation,
    CreatorMemoryItemResponse,
    CreatorMemoryPageResponse,
    CreatorMemoryTimelineItemResponse,
    CreatorMemoryTimelineResponse,
    CreatorProjectionInvalidation,
    CreatorPromptDeactivateCommand,
    CreatorPromptPort,
    CreatorPromptResponse,
    CreatorPromptRevisionCommand,
    CreatorPromptViolation,
    CreatorRelationshipCurrentResponse,
    CreatorRelationshipItemResponse,
    CreatorRelationshipTimelineResponse,
    CreatorResourceKind,
    FastAPI,
    HTTPBearer,
    IdempotencyKey,
    Instant,
    JSONResponse,
    LifeRecordActor,
    LifeRecordItemResponse,
    LifeRecordKindValue,
    LifeRecordPageResponse,
    LifeRecordQuery,
    LifeRecordQueryPort,
    LifeRecordQueryViolation,
    LifeRecordRetrievalKind,
    LifeViolation,
    Literal,
    MaterialViolation,
    MemoryReadPort,
    MemoryViolation,
    PromptKind,
    RejectedOutcomeResponse,
    RelationshipReadPort,
    RelationshipViolation,
    Request,
    Response,
    Security,
    SecurityEvent,
    SubjectComponentSummaryResponse,
    SubjectSummaryProvider,
    SubjectSummaryResponse,
    TraceId,
    UnavailableOutcomeResponse,
    _accepted_wire,
    _bearer,
    _boundary_message,
    _browser_boundary,
    _creator_boundary_request,
    _creator_prompt_deactivate_request,
    _creator_prompt_error,
    _creator_prompt_response,
    _creator_prompt_revision_request,
    _input_failure,
    _life_query_parameters,
    _rejected,
    _relationship_revision_response,
    _single_header,
    _unavailable,
    cast,
    datetime,
    secrets,
    uuid7,
)


def register_subject_life_routes(
    *,
    app: FastAPI,
    bearer: HTTPBearer,
    canonical_origin: str,
    emit: SecurityEvent,
    browser_sessions: BrowserSessionStore | None,
    creator_activity_query: ActivityReadPort | None,
    creator_emergency_wake: CreatorEmergencyWakePort | None,
    creator_events: CreatorEventBroker | None,
    creator_input: CreatorInputAcceptancePort | None,
    creator_life_material_query: CreatorLifeMaterialQueryPort | None,
    creator_maintenance_query: CreatorMaintenanceQueryPort | None,
    creator_memory_query: MemoryReadPort | None,
    creator_prompt: CreatorPromptPort | None,
    creator_relationship_query: RelationshipReadPort | None,
    life_record_query: LifeRecordQueryPort | None,
    request_body_max_bytes: int,
    subject_summary: SubjectSummaryProvider | None,
) -> None:
    @app.get(
        "/v1/subject/summary",
        operation_id="getSubjectSummary",
        response_model=SubjectSummaryResponse,
        responses={
            401: {"model": RejectedOutcomeResponse},
            403: {"model": RejectedOutcomeResponse},
            503: {"model": UnavailableOutcomeResponse},
        },
        dependencies=[Security(bearer)],
    )
    async def get_subject_summary(request: Request) -> JSONResponse:
        if (
            browser_sessions is None
            or subject_summary is None
            or not _browser_boundary(request, canonical_origin=canonical_origin)
        ):
            return JSONResponse(
                status_code=403 if browser_sessions is not None else 503,
                content=(
                    _rejected("AUTH_BROWSER_BOUNDARY")
                    if browser_sessions is not None
                    else _unavailable("DEPENDENCY_SUBJECT_SUMMARY_UNAVAILABLE")
                ),
            )
        token = _bearer(request)
        try:
            if token is None:
                raise BrowserSessionViolation("AUTH_SESSION_REQUIRED")
            browser_sessions.verify(token)
            summary = await subject_summary()
        except BrowserSessionViolation as error:
            return JSONResponse(
                status_code=error.status_code, content=_rejected(error.code)
            )
        except CreatorInputViolation:
            return JSONResponse(
                status_code=503,
                content=_unavailable("DEPENDENCY_SUBJECT_SUMMARY_UNAVAILABLE"),
            )
        return JSONResponse(
            content=SubjectSummaryResponse(
                contract_version="1.0",
                projection_version="subject-summary.v1",
                subject_version=summary.subject_version,
                components=[
                    SubjectComponentSummaryResponse(
                        kind=item.kind.value,
                        version=item.version,
                        schema_version=cast(
                            Literal[
                                "armi.self.v1",
                                "armi.mind.v2",
                                "armi.life-mode.v1",
                            ],
                            item.schema_version,
                        ),
                        content_visibility="private",
                    )
                    for item in summary.components
                ],
                latest_commit_ref=(
                    str(summary.latest_commit_ref)
                    if summary.latest_commit_ref is not None
                    else None
                ),
                observed_at=Instant(summary.observed_at).to_wire(),
            ).model_dump(mode="json", exclude_none=True)
        )

    _ = get_subject_summary

    @app.get(
        "/v1/prompts/creator-guidance",
        operation_id="getCreatorPrompt",
        response_model=CreatorPromptResponse,
        responses={
            401: {"model": RejectedOutcomeResponse},
            403: {"model": RejectedOutcomeResponse},
            503: {"model": UnavailableOutcomeResponse},
        },
        dependencies=[Security(bearer)],
    )
    async def get_creator_prompt(request: Request) -> JSONResponse:
        if (
            browser_sessions is None
            or creator_prompt is None
            or not _browser_boundary(request, canonical_origin=canonical_origin)
        ):
            status = (
                403
                if browser_sessions is not None and creator_prompt is not None
                else 503
            )
            return JSONResponse(
                status_code=status,
                content=(
                    _rejected("AUTH_BROWSER_BOUNDARY")
                    if status == 403
                    else _unavailable("DEPENDENCY_CREATOR_PROMPT_UNAVAILABLE")
                ),
            )
        token = _bearer(request)
        try:
            if token is None:
                raise BrowserSessionViolation("AUTH_SESSION_REQUIRED")
            browser_sessions.verify(token)
            view = await creator_prompt.get(PromptKind.CREATOR_GUIDANCE)
        except BrowserSessionViolation as error:
            return JSONResponse(
                status_code=error.status_code,
                content=_rejected(error.code),
            )
        except CreatorPromptViolation as error:
            return _creator_prompt_error(error)
        return JSONResponse(
            content=_creator_prompt_response(view).model_dump(mode="json")
        )

    @app.put(
        "/v1/prompts/creator-guidance",
        operation_id="reviseCreatorPrompt",
        response_model=CreatorPromptResponse,
        responses={
            400: {"model": RejectedOutcomeResponse},
            401: {"model": RejectedOutcomeResponse},
            403: {"model": RejectedOutcomeResponse},
            409: {"model": RejectedOutcomeResponse},
            413: {"model": RejectedOutcomeResponse},
            503: {"model": UnavailableOutcomeResponse},
        },
        dependencies=[Security(bearer)],
    )
    async def revise_creator_prompt(request: Request) -> JSONResponse:
        if (
            browser_sessions is None
            or creator_prompt is None
            or not _browser_boundary(request, canonical_origin=canonical_origin)
        ):
            status = (
                403
                if browser_sessions is not None and creator_prompt is not None
                else 503
            )
            return JSONResponse(
                status_code=status,
                content=(
                    _rejected("AUTH_BROWSER_BOUNDARY")
                    if status == 403
                    else _unavailable("DEPENDENCY_CREATOR_PROMPT_UNAVAILABLE")
                ),
            )
        token = _bearer(request)
        try:
            if token is None:
                raise BrowserSessionViolation("AUTH_SESSION_REQUIRED")
            browser_sessions.verify(token)
            body = await _creator_prompt_revision_request(
                request,
                request_body_max_bytes,
            )
            view = await creator_prompt.revise(
                CreatorPromptRevisionCommand(
                    prompt_kind=PromptKind.CREATOR_GUIDANCE,
                    expected_revision_id=(
                        None
                        if body.expected_revision_id is None
                        else UUID(body.expected_revision_id)
                    ),
                    content=body.content,
                    trace_id=TraceId(secrets.token_hex(16)),
                )
            )
        except BrowserSessionViolation as error:
            return JSONResponse(
                status_code=error.status_code,
                content=_rejected(error.code),
            )
        except CreatorPromptViolation as error:
            return _creator_prompt_error(error)
        return JSONResponse(
            content=_creator_prompt_response(view).model_dump(mode="json")
        )

    @app.post(
        "/v1/prompts/creator-guidance/deactivation",
        operation_id="deactivateCreatorPrompt",
        response_model=CreatorPromptResponse,
        responses={
            400: {"model": RejectedOutcomeResponse},
            401: {"model": RejectedOutcomeResponse},
            403: {"model": RejectedOutcomeResponse},
            409: {"model": RejectedOutcomeResponse},
            413: {"model": RejectedOutcomeResponse},
            503: {"model": UnavailableOutcomeResponse},
        },
        dependencies=[Security(bearer)],
    )
    async def deactivate_creator_prompt(request: Request) -> JSONResponse:
        if (
            browser_sessions is None
            or creator_prompt is None
            or not _browser_boundary(request, canonical_origin=canonical_origin)
        ):
            status = (
                403
                if browser_sessions is not None and creator_prompt is not None
                else 503
            )
            return JSONResponse(
                status_code=status,
                content=(
                    _rejected("AUTH_BROWSER_BOUNDARY")
                    if status == 403
                    else _unavailable("DEPENDENCY_CREATOR_PROMPT_UNAVAILABLE")
                ),
            )
        token = _bearer(request)
        try:
            if token is None:
                raise BrowserSessionViolation("AUTH_SESSION_REQUIRED")
            browser_sessions.verify(token)
            body = await _creator_prompt_deactivate_request(
                request,
                request_body_max_bytes,
            )
            view = await creator_prompt.deactivate(
                CreatorPromptDeactivateCommand(
                    prompt_kind=PromptKind.CREATOR_GUIDANCE,
                    expected_revision_id=UUID(body.expected_revision_id),
                    trace_id=TraceId(secrets.token_hex(16)),
                )
            )
        except BrowserSessionViolation as error:
            return JSONResponse(
                status_code=error.status_code,
                content=_rejected(error.code),
            )
        except CreatorPromptViolation as error:
            return _creator_prompt_error(error)
        return JSONResponse(
            content=_creator_prompt_response(view).model_dump(mode="json")
        )

    del get_creator_prompt, revise_creator_prompt, deactivate_creator_prompt

    @app.get(
        "/v1/activities",
        operation_id="listCreatorActivities",
        response_model=CreatorActivityPageResponse,
        responses={
            401: {"model": RejectedOutcomeResponse},
            403: {"model": RejectedOutcomeResponse},
            503: {"model": UnavailableOutcomeResponse},
        },
        dependencies=[Security(bearer)],
    )
    async def list_creator_activities(request: Request) -> JSONResponse:
        if (
            browser_sessions is None
            or creator_activity_query is None
            or not _browser_boundary(request, canonical_origin=canonical_origin)
        ):
            status = (
                403
                if browser_sessions is not None and creator_activity_query is not None
                else 503
            )
            return JSONResponse(
                status_code=status,
                content=(
                    _rejected("AUTH_BROWSER_BOUNDARY")
                    if status == 403
                    else _unavailable("DEPENDENCY_ACTIVITY_QUERY_UNAVAILABLE")
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
        try:
            page = await creator_activity_query.list_current()
        except ActivityViolation:
            return JSONResponse(
                status_code=503,
                content=_unavailable("DEPENDENCY_ACTIVITY_QUERY_UNAVAILABLE"),
            )
        response = CreatorActivityPageResponse(
            contract_version="1.0",
            projection_version="creator-activity.v1",
            items=[
                CreatorActivityItemResponse(
                    activity_id=str(item.activity_id),
                    activity_kind=item.activity_kind,
                    status=item.status.value,
                    goal=item.goal,
                    progress_summary=item.progress_summary,
                    waiting_kind=(
                        None if item.waiting_kind is None else item.waiting_kind.value
                    ),
                    waiting_summary=item.waiting_summary,
                    resume_not_before=(
                        None
                        if item.resume_not_before is None
                        else Instant(item.resume_not_before).to_wire()
                    ),
                    terminal_reason=item.terminal_reason,
                    revision_no=item.revision_no,
                    head_version=item.head_version,
                    transition_kind=item.transition_kind.value,
                    is_focused=item.is_focused,
                    created_at=Instant(item.created_at).to_wire(),
                    updated_at=Instant(item.updated_at).to_wire(),
                )
                for item in page.items
            ],
            truncated=page.truncated,
        )
        return JSONResponse(content=response.model_dump(mode="json"))

    @app.get(
        "/v1/activities/{activity_id}/timeline",
        operation_id="getCreatorActivityTimeline",
        response_model=CreatorActivityTimelineResponse,
        responses={
            400: {"model": RejectedOutcomeResponse},
            401: {"model": RejectedOutcomeResponse},
            403: {"model": RejectedOutcomeResponse},
            404: {"model": RejectedOutcomeResponse},
            503: {"model": UnavailableOutcomeResponse},
        },
        dependencies=[Security(bearer)],
    )
    async def get_creator_activity_timeline(
        activity_id: str, request: Request
    ) -> JSONResponse:
        if (
            browser_sessions is None
            or creator_activity_query is None
            or not _browser_boundary(request, canonical_origin=canonical_origin)
        ):
            status = (
                403
                if browser_sessions is not None and creator_activity_query is not None
                else 503
            )
            return JSONResponse(
                status_code=status,
                content=(
                    _rejected("AUTH_BROWSER_BOUNDARY")
                    if status == 403
                    else _unavailable("DEPENDENCY_ACTIVITY_QUERY_UNAVAILABLE")
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
        try:
            parsed = UUID(activity_id)
            if parsed.version != 7 or str(parsed) != activity_id:
                raise ValueError
        except ValueError:
            return JSONResponse(
                status_code=404,
                content=_rejected("SCOPE_ACTIVITY_NOT_VISIBLE"),
            )
        try:
            timeline = await creator_activity_query.timeline(parsed)
        except ActivityViolation as error:
            if error.code == "ACTIVITY-QUERY-NOT-FOUND":
                return JSONResponse(
                    status_code=404,
                    content=_rejected("SCOPE_ACTIVITY_NOT_VISIBLE"),
                )
            return JSONResponse(
                status_code=503,
                content=_unavailable("DEPENDENCY_ACTIVITY_QUERY_UNAVAILABLE"),
            )
        response = CreatorActivityTimelineResponse(
            contract_version="1.0",
            projection_version="creator-activity.v1",
            activity_id=str(timeline.activity_id),
            items=[
                CreatorActivityTimelineItemResponse(
                    event_id=str(item.event_id),
                    event_kind=item.event_kind,
                    resulting_status=(
                        None
                        if item.resulting_status is None
                        else item.resulting_status.value
                    ),
                    summary=item.summary,
                    review_not_before=(
                        None
                        if item.review_not_before is None
                        else Instant(item.review_not_before).to_wire()
                    ),
                    occurred_at=Instant(item.occurred_at).to_wire(),
                )
                for item in timeline.items
            ],
            truncated=timeline.truncated,
        )
        return JSONResponse(content=response.model_dump(mode="json"))

    del list_creator_activities, get_creator_activity_timeline

    @app.get(
        "/v1/relationships/current",
        operation_id="getCreatorRelationshipCurrent",
        response_model=CreatorRelationshipCurrentResponse,
        responses={
            401: {"model": RejectedOutcomeResponse},
            403: {"model": RejectedOutcomeResponse},
            503: {"model": UnavailableOutcomeResponse},
        },
        dependencies=[Security(bearer)],
    )
    async def get_creator_relationship_current(request: Request) -> JSONResponse:
        if (
            browser_sessions is None
            or creator_relationship_query is None
            or not _browser_boundary(request, canonical_origin=canonical_origin)
        ):
            status = (
                403
                if browser_sessions is not None
                and creator_relationship_query is not None
                else 503
            )
            return JSONResponse(
                status_code=status,
                content=(
                    _rejected("AUTH_BROWSER_BOUNDARY")
                    if status == 403
                    else _unavailable("DEPENDENCY_RELATIONSHIP_QUERY_UNAVAILABLE")
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
        try:
            item = await creator_relationship_query.current()
        except RelationshipViolation:
            return JSONResponse(
                status_code=503,
                content=_unavailable("DEPENDENCY_RELATIONSHIP_QUERY_UNAVAILABLE"),
            )
        response = CreatorRelationshipCurrentResponse(
            contract_version="1.0",
            projection_version="creator-relationship.v2",
            relationship=(
                None
                if item is None
                else CreatorRelationshipItemResponse(
                    relationship_id=str(item.relationship_id),
                    current_revision_id=str(item.current_revision_id),
                    head_version=item.head_version,
                    current=_relationship_revision_response(item.current),
                    created_at=Instant(item.created_at).to_wire(),
                )
            ),
        )
        return JSONResponse(content=response.model_dump(mode="json"))

    @app.get(
        "/v1/relationships/{relationship_id}/timeline",
        operation_id="getCreatorRelationshipTimeline",
        response_model=CreatorRelationshipTimelineResponse,
        responses={
            400: {"model": RejectedOutcomeResponse},
            401: {"model": RejectedOutcomeResponse},
            403: {"model": RejectedOutcomeResponse},
            404: {"model": RejectedOutcomeResponse},
            503: {"model": UnavailableOutcomeResponse},
        },
        dependencies=[Security(bearer)],
    )
    async def get_creator_relationship_timeline(
        relationship_id: str,
        request: Request,
    ) -> JSONResponse:
        if (
            browser_sessions is None
            or creator_relationship_query is None
            or not _browser_boundary(request, canonical_origin=canonical_origin)
        ):
            status = (
                403
                if browser_sessions is not None
                and creator_relationship_query is not None
                else 503
            )
            return JSONResponse(
                status_code=status,
                content=(
                    _rejected("AUTH_BROWSER_BOUNDARY")
                    if status == 403
                    else _unavailable("DEPENDENCY_RELATIONSHIP_QUERY_UNAVAILABLE")
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
        try:
            parsed = UUID(relationship_id)
            if parsed.version != 7 or str(parsed) != relationship_id:
                raise ValueError
        except ValueError:
            return JSONResponse(
                status_code=404,
                content=_rejected("SCOPE_RELATIONSHIP_NOT_VISIBLE"),
            )
        try:
            timeline = await creator_relationship_query.timeline(parsed)
        except RelationshipViolation as error:
            if error.code == "RELATIONSHIP-QUERY-NOT-FOUND":
                return JSONResponse(
                    status_code=404,
                    content=_rejected("SCOPE_RELATIONSHIP_NOT_VISIBLE"),
                )
            return JSONResponse(
                status_code=503,
                content=_unavailable("DEPENDENCY_RELATIONSHIP_QUERY_UNAVAILABLE"),
            )
        response = CreatorRelationshipTimelineResponse(
            contract_version="1.0",
            projection_version="creator-relationship.v2",
            relationship_id=str(timeline.relationship_id),
            items=[_relationship_revision_response(item) for item in timeline.items],
            truncated=timeline.truncated,
        )
        return JSONResponse(content=response.model_dump(mode="json"))

    @app.post(
        "/v1/relationships/current/boundaries",
        operation_id="expressCreatorRelationshipBoundary",
        status_code=202,
        response_model=AcceptedOutcomeResponse,
        responses={
            400: {"model": RejectedOutcomeResponse},
            401: {"model": RejectedOutcomeResponse},
            403: {"model": RejectedOutcomeResponse},
            409: {"model": RejectedOutcomeResponse},
            413: {"model": RejectedOutcomeResponse},
            503: {"model": UnavailableOutcomeResponse},
        },
        dependencies=[Security(bearer)],
    )
    async def express_creator_relationship_boundary(
        request: Request,
    ) -> JSONResponse:
        if (
            browser_sessions is None
            or creator_input is None
            or not _browser_boundary(request, canonical_origin=canonical_origin)
        ):
            status = (
                403
                if browser_sessions is not None and creator_input is not None
                else 503
            )
            return JSONResponse(
                status_code=status,
                content=(
                    _rejected("AUTH_BROWSER_BOUNDARY")
                    if status == 403
                    else _unavailable("DEPENDENCY_RELATIONSHIP_INPUT_UNAVAILABLE")
                ),
            )
        token = _bearer(request)
        try:
            if token is None:
                raise BrowserSessionViolation("AUTH_SESSION_REQUIRED")
            metadata = browser_sessions.verify(token)
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
            model = await _creator_boundary_request(request, request_body_max_bytes)
            acceptance = await creator_input.accept(
                CreatorInputCommand(
                    scene_key=metadata.default_scene_key,
                    message=_boundary_message(model),
                    idempotency_key=IdempotencyKey(idempotency_value),
                    trace_id=TraceId(secrets.token_hex(16)),
                )
            )
        except (ContractViolation, CreatorInputViolation) as error:
            if isinstance(error, ContractViolation):
                status, content = 400, _rejected("INPUT_IDEMPOTENCY_KEY")
            else:
                status, content = _input_failure(error)
            emit("creator.relationship_boundary.rejected")
            return JSONResponse(status_code=status, content=content)
        emit(
            "creator.relationship_boundary.accepted"
            if acceptance.newly_accepted
            else "creator.relationship_boundary.idempotent"
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

    del (
        express_creator_relationship_boundary,
        get_creator_relationship_current,
        get_creator_relationship_timeline,
    )

    @app.get(
        "/v1/life-records",
        operation_id="queryCreatorLifeRecords",
        response_model=LifeRecordPageResponse,
        responses={
            400: {"model": RejectedOutcomeResponse},
            401: {"model": RejectedOutcomeResponse},
            403: {"model": RejectedOutcomeResponse},
            409: {"model": RejectedOutcomeResponse},
            503: {"model": UnavailableOutcomeResponse},
        },
        dependencies=[Security(bearer)],
    )
    async def query_creator_life_records(request: Request) -> JSONResponse:
        if (
            browser_sessions is None
            or life_record_query is None
            or not _browser_boundary(request, canonical_origin=canonical_origin)
        ):
            status = (
                403
                if browser_sessions is not None and life_record_query is not None
                else 503
            )
            return JSONResponse(
                status_code=status,
                content=(
                    _rejected("AUTH_BROWSER_BOUNDARY")
                    if status == 403
                    else _unavailable("DEPENDENCY_LIFE_QUERY_UNAVAILABLE")
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
        try:
            limit, query_text, record_kind, cursor = _life_query_parameters(
                request,
                allow_kind=True,
                allow_text=True,
            )
            page = await life_record_query.query(
                LifeRecordQuery(
                    actor=LifeRecordActor.CREATOR,
                    retrieval_kind=LifeRecordRetrievalKind.CREATOR_VIEW,
                    limit=limit,
                    record_kind=record_kind,
                    query_text=query_text,
                    cursor=cursor,
                )
            )
        except ContractViolation:
            return JSONResponse(
                status_code=400,
                content=_rejected("INPUT_LIFE_QUERY_INVALID"),
            )
        except LifeRecordQueryViolation as error:
            if error.code == "LIFE-QUERY-CURSOR-INVALID":
                return JSONResponse(
                    status_code=400,
                    content=_rejected("INPUT_CURSOR_INVALID"),
                )
            if error.code == "LIFE-QUERY-CURSOR-STALE":
                return JSONResponse(
                    status_code=409,
                    content=_rejected("CONFLICT_CURSOR_STALE"),
                )
            return JSONResponse(
                status_code=503,
                content=_unavailable("DEPENDENCY_LIFE_QUERY_UNAVAILABLE"),
            )
        response = LifeRecordPageResponse(
            contract_version="1.0",
            projection_version="life-record-query.v2",
            retrieval_kind="creator_view",
            items=[
                LifeRecordItemResponse(
                    record_ref=str(item.record_ref),
                    record_kind=cast(LifeRecordKindValue, str(item.record_kind)),
                    summary=item.summary,
                    source_kind=item.source_kind,
                    occurred_at=item.occurred_at.to_wire(),
                    naturally_recallable=item.naturally_recallable,
                    retrieval_kind=item.retrieval_kind.value,
                )
                for item in page.items
            ],
            next_cursor=(
                None if page.next_cursor is None else page.next_cursor.to_wire()
            ),
        )
        return JSONResponse(content=response.model_dump(mode="json"))

    @app.get(
        "/v1/materials/{material_id}",
        operation_id="getCreatorLifeMaterial",
        response_model=CreatorLifeMaterialResponse,
        responses={
            400: {"model": RejectedOutcomeResponse},
            401: {"model": RejectedOutcomeResponse},
            403: {"model": RejectedOutcomeResponse},
            404: {"model": RejectedOutcomeResponse},
            503: {"model": UnavailableOutcomeResponse},
        },
        dependencies=[Security(bearer)],
    )
    async def get_creator_life_material(
        material_id: str,
        request: Request,
    ) -> JSONResponse:
        if (
            browser_sessions is None
            or creator_life_material_query is None
            or not _browser_boundary(request, canonical_origin=canonical_origin)
        ):
            status = (
                403
                if browser_sessions is not None
                and creator_life_material_query is not None
                else 503
            )
            return JSONResponse(
                status_code=status,
                content=(
                    _rejected("AUTH_BROWSER_BOUNDARY")
                    if status == 403
                    else _unavailable("DEPENDENCY_LIFE_MATERIAL_QUERY_UNAVAILABLE")
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
        try:
            parsed = UUID(material_id)
            if parsed.version != 7 or str(parsed) != material_id:
                raise ValueError
        except ValueError:
            return JSONResponse(
                status_code=404,
                content=_rejected("SCOPE_LIFE_MATERIAL_NOT_VISIBLE"),
            )
        try:
            item = await creator_life_material_query.get_creator_visible(parsed)
        except MaterialViolation:
            return JSONResponse(
                status_code=503,
                content=_unavailable("DEPENDENCY_LIFE_MATERIAL_QUERY_UNAVAILABLE"),
            )
        if item is None:
            return JSONResponse(
                status_code=404,
                content=_rejected("SCOPE_LIFE_MATERIAL_NOT_VISIBLE"),
            )
        response = CreatorLifeMaterialResponse(
            contract_version="1.0",
            projection_version="creator-life-material.v1",
            material_id=str(item.material_id),
            material_kind=item.material_kind.value,
            revision_no=item.revision_no,
            title=item.title,
            body=item.body,
            metadata=dict(item.metadata),
            material_status=item.material_status.value,
            privacy_status="creator_visible",
            created_at=item.created_at.to_wire(),
            updated_at=item.updated_at.to_wire(),
        )
        return JSONResponse(content=response.model_dump(mode="json"))

    @app.get(
        "/v1/memories",
        operation_id="listCreatorMemories",
        response_model=CreatorMemoryPageResponse,
        responses={
            400: {"model": RejectedOutcomeResponse},
            401: {"model": RejectedOutcomeResponse},
            403: {"model": RejectedOutcomeResponse},
            409: {"model": RejectedOutcomeResponse},
            503: {"model": UnavailableOutcomeResponse},
        },
        dependencies=[Security(bearer)],
    )
    async def list_creator_memories(request: Request) -> JSONResponse:
        if (
            browser_sessions is None
            or creator_memory_query is None
            or not _browser_boundary(request, canonical_origin=canonical_origin)
        ):
            status = (
                403
                if browser_sessions is not None and creator_memory_query is not None
                else 503
            )
            return JSONResponse(
                status_code=status,
                content=(
                    _rejected("AUTH_BROWSER_BOUNDARY")
                    if status == 403
                    else _unavailable("DEPENDENCY_MEMORY_QUERY_UNAVAILABLE")
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
        try:
            limit, query_text, _kind, cursor = _life_query_parameters(
                request,
                allow_kind=False,
                allow_text=True,
            )
            page = await creator_memory_query.list_current(
                limit=limit,
                query_text=query_text,
                cursor=cursor,
            )
        except ContractViolation:
            return JSONResponse(
                status_code=400,
                content=_rejected("INPUT_MEMORY_QUERY_INVALID"),
            )
        except LifeRecordQueryViolation as error:
            if error.code == "LIFE-QUERY-CURSOR-INVALID":
                return JSONResponse(
                    status_code=400,
                    content=_rejected("INPUT_CURSOR_INVALID"),
                )
            if error.code == "LIFE-QUERY-CURSOR-STALE":
                return JSONResponse(
                    status_code=409,
                    content=_rejected("CONFLICT_CURSOR_STALE"),
                )
            return JSONResponse(
                status_code=503,
                content=_unavailable("DEPENDENCY_MEMORY_QUERY_UNAVAILABLE"),
            )
        except MemoryViolation as error:
            if error.code == "MEMORY-CURSOR":
                return JSONResponse(
                    status_code=400,
                    content=_rejected("INPUT_CURSOR_INVALID"),
                )
            return JSONResponse(
                status_code=503,
                content=_unavailable("DEPENDENCY_MEMORY_QUERY_UNAVAILABLE"),
            )
        response = CreatorMemoryPageResponse(
            contract_version="1.0",
            projection_version="creator-memory.v1",
            retrieval_kind="creator_view",
            items=[
                CreatorMemoryItemResponse(
                    memory_id=str(item.memory_id),
                    summary=item.summary,
                    uncertainty=item.uncertainty,
                    source_kind=item.source_kind,
                    source_fact_class=item.source_fact_class,
                    accessibility=item.accessibility.value,
                    revision_kind=item.revision_kind.value,
                    revision_no=item.revision_no,
                    head_version=item.head_version,
                    created_at=item.created_at.to_wire(),
                    updated_at=item.updated_at.to_wire(),
                )
                for item in page.items
            ],
            next_cursor=(
                None if page.next_cursor is None else page.next_cursor.to_wire()
            ),
        )
        return JSONResponse(content=response.model_dump(mode="json"))

    @app.get(
        "/v1/memories/{memory_id}/timeline",
        operation_id="getCreatorMemoryTimeline",
        response_model=CreatorMemoryTimelineResponse,
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
    async def get_creator_memory_timeline(
        memory_id: str,
        request: Request,
    ) -> JSONResponse:
        if (
            browser_sessions is None
            or creator_memory_query is None
            or not _browser_boundary(request, canonical_origin=canonical_origin)
        ):
            status = (
                403
                if browser_sessions is not None and creator_memory_query is not None
                else 503
            )
            return JSONResponse(
                status_code=status,
                content=(
                    _rejected("AUTH_BROWSER_BOUNDARY")
                    if status == 403
                    else _unavailable("DEPENDENCY_MEMORY_QUERY_UNAVAILABLE")
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
        try:
            parsed = UUID(memory_id)
            if parsed.version != 7 or str(parsed) != memory_id:
                raise ValueError
        except ValueError:
            return JSONResponse(
                status_code=404,
                content=_rejected("SCOPE_MEMORY_NOT_VISIBLE"),
            )
        try:
            limit, _query_text, _kind, cursor = _life_query_parameters(
                request,
                allow_kind=False,
                allow_text=False,
            )
            timeline = await creator_memory_query.timeline(
                parsed,
                limit=limit,
                cursor=cursor,
            )
        except ContractViolation:
            return JSONResponse(
                status_code=400,
                content=_rejected("INPUT_MEMORY_QUERY_INVALID"),
            )
        except LifeRecordQueryViolation as error:
            if error.code == "LIFE-QUERY-NOT-FOUND":
                return JSONResponse(
                    status_code=404,
                    content=_rejected("SCOPE_MEMORY_NOT_VISIBLE"),
                )
            if error.code == "LIFE-QUERY-CURSOR-INVALID":
                return JSONResponse(
                    status_code=400,
                    content=_rejected("INPUT_CURSOR_INVALID"),
                )
            if error.code == "LIFE-QUERY-CURSOR-STALE":
                return JSONResponse(
                    status_code=409,
                    content=_rejected("CONFLICT_CURSOR_STALE"),
                )
            return JSONResponse(
                status_code=503,
                content=_unavailable("DEPENDENCY_MEMORY_QUERY_UNAVAILABLE"),
            )
        except MemoryViolation as error:
            if error.code == "MEMORY-QUERY-NOT-FOUND":
                return JSONResponse(
                    status_code=404,
                    content=_rejected("SCOPE_MEMORY_NOT_VISIBLE"),
                )
            if error.code == "MEMORY-CURSOR":
                return JSONResponse(
                    status_code=400,
                    content=_rejected("INPUT_CURSOR_INVALID"),
                )
            return JSONResponse(
                status_code=503,
                content=_unavailable("DEPENDENCY_MEMORY_QUERY_UNAVAILABLE"),
            )
        response = CreatorMemoryTimelineResponse(
            contract_version="1.0",
            projection_version="creator-memory.v1",
            retrieval_kind="creator_view",
            memory_id=str(timeline.memory_id),
            items=[
                CreatorMemoryTimelineItemResponse(
                    revision_id=str(item.revision_id),
                    revision_no=item.revision_no,
                    revision_kind=item.revision_kind.value,
                    accessibility=item.accessibility.value,
                    summary=item.summary,
                    uncertainty=item.uncertainty,
                    source_kind=item.source_kind,
                    source_fact_class=item.source_fact_class,
                    relation_kind=(
                        None if item.relation_kind is None else item.relation_kind.value
                    ),
                    related_memory_id=(
                        None
                        if item.related_memory_id is None
                        else str(item.related_memory_id)
                    ),
                    occurred_at=item.occurred_at.to_wire(),
                )
                for item in timeline.items
            ],
            next_cursor=(
                None if timeline.next_cursor is None else timeline.next_cursor.to_wire()
            ),
        )
        return JSONResponse(content=response.model_dump(mode="json"))

    del get_creator_life_material, query_creator_life_records, list_creator_memories
    del get_creator_memory_timeline

    @app.get(
        "/v1/maintenance/status",
        operation_id="getCreatorMaintenanceStatus",
        response_model=CreatorMaintenanceStatusResponse,
        responses={
            401: {"model": RejectedOutcomeResponse},
            403: {"model": RejectedOutcomeResponse},
            503: {"model": UnavailableOutcomeResponse},
        },
        dependencies=[Security(bearer)],
    )
    async def get_creator_maintenance_status(request: Request) -> JSONResponse:
        if (
            browser_sessions is None
            or creator_maintenance_query is None
            or not _browser_boundary(request, canonical_origin=canonical_origin)
        ):
            status = (
                403
                if browser_sessions is not None
                and creator_maintenance_query is not None
                else 503
            )
            return JSONResponse(
                status_code=status,
                content=(
                    _rejected("AUTH_BROWSER_BOUNDARY")
                    if status == 403
                    else _unavailable("DEPENDENCY_MAINTENANCE_QUERY_UNAVAILABLE")
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
        try:
            status = await creator_maintenance_query.status()
        except CreatorMaintenanceViolation:
            return JSONResponse(
                status_code=503,
                content=_unavailable("DEPENDENCY_MAINTENANCE_QUERY_UNAVAILABLE"),
            )
        session = status.session
        response = CreatorMaintenanceStatusResponse(
            contract_version="1.0",
            projection_version="creator-maintenance.v2",
            session=(
                None
                if session is None
                else CreatorMaintenanceSessionResponse(
                    maintenance_session_id=str(session.session_id),
                    trigger_kind=session.trigger_kind.value,
                    phase=session.phase.value,
                    result_status=session.result_status.value,
                    revision_no=session.revision_no,
                    head_version=session.head_version,
                    wake_requested=session.wake_requested,
                    started_at=Instant(session.started_at).to_wire(),
                    updated_at=Instant(session.updated_at).to_wire(),
                    finished_at=(
                        None
                        if session.finished_at is None
                        else Instant(session.finished_at).to_wire()
                    ),
                )
            ),
            waiting_input_count=status.waiting_input_count,
        )
        return JSONResponse(content=response.model_dump(mode="json"))

    @app.get(
        "/v1/maintenance/{maintenance_session_id}/timeline",
        operation_id="getCreatorMaintenanceTimeline",
        response_model=CreatorMaintenanceTimelineResponse,
        responses={
            400: {"model": RejectedOutcomeResponse},
            401: {"model": RejectedOutcomeResponse},
            403: {"model": RejectedOutcomeResponse},
            404: {"model": RejectedOutcomeResponse},
            503: {"model": UnavailableOutcomeResponse},
        },
        dependencies=[Security(bearer)],
    )
    async def get_creator_maintenance_timeline(
        maintenance_session_id: str,
        request: Request,
    ) -> JSONResponse:
        if (
            browser_sessions is None
            or creator_maintenance_query is None
            or not _browser_boundary(request, canonical_origin=canonical_origin)
        ):
            status = (
                403
                if browser_sessions is not None
                and creator_maintenance_query is not None
                else 503
            )
            return JSONResponse(
                status_code=status,
                content=(
                    _rejected("AUTH_BROWSER_BOUNDARY")
                    if status == 403
                    else _unavailable("DEPENDENCY_MAINTENANCE_QUERY_UNAVAILABLE")
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
        try:
            parsed = UUID(maintenance_session_id)
            if parsed.version != 7 or str(parsed) != maintenance_session_id:
                raise ValueError
        except ValueError:
            return JSONResponse(
                status_code=404,
                content=_rejected("SCOPE_MAINTENANCE_NOT_VISIBLE"),
            )
        try:
            timeline = await creator_maintenance_query.timeline(parsed)
        except CreatorMaintenanceViolation as error:
            if error.code == "MAINTENANCE-QUERY-NOT-FOUND":
                return JSONResponse(
                    status_code=404,
                    content=_rejected("SCOPE_MAINTENANCE_NOT_VISIBLE"),
                )
            return JSONResponse(
                status_code=503,
                content=_unavailable("DEPENDENCY_MAINTENANCE_QUERY_UNAVAILABLE"),
            )
        response = CreatorMaintenanceTimelineResponse(
            contract_version="1.0",
            projection_version="creator-maintenance.v2",
            maintenance_session_id=str(timeline.session_id),
            items=[
                CreatorMaintenanceTimelineItemResponse(
                    revision_id=str(item.revision_id),
                    revision_no=item.revision_no,
                    phase=item.phase.value,
                    result_status=item.result_status.value,
                    transition_kind=item.transition_kind,
                    occurred_at=Instant(item.occurred_at).to_wire(),
                    work_outcome=(
                        None if item.work_outcome is None else item.work_outcome.value
                    ),
                    problem_summary=item.problem_summary,
                )
                for item in timeline.items
            ],
            truncated=timeline.truncated,
        )
        return JSONResponse(content=response.model_dump(mode="json"))

    @app.post(
        "/v1/maintenance/{maintenance_session_id}/wake",
        operation_id="requestCreatorEmergencyWake",
        status_code=204,
        response_class=Response,
        responses={
            401: {"model": RejectedOutcomeResponse},
            403: {"model": RejectedOutcomeResponse},
            404: {"model": RejectedOutcomeResponse},
            409: {"model": RejectedOutcomeResponse},
            503: {"model": UnavailableOutcomeResponse},
        },
        dependencies=[Security(bearer)],
    )
    async def request_creator_emergency_wake(
        maintenance_session_id: str,
        request: Request,
    ) -> Response:
        if (
            browser_sessions is None
            or creator_emergency_wake is None
            or not _browser_boundary(request, canonical_origin=canonical_origin)
        ):
            status = (
                403
                if browser_sessions is not None and creator_emergency_wake is not None
                else 503
            )
            return JSONResponse(
                status_code=status,
                content=(
                    _rejected("AUTH_BROWSER_BOUNDARY")
                    if status == 403
                    else _unavailable("DEPENDENCY_MAINTENANCE_WAKE_UNAVAILABLE")
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
        try:
            parsed = UUID(maintenance_session_id)
            if parsed.version != 7 or str(parsed) != maintenance_session_id:
                raise ValueError
        except ValueError:
            return JSONResponse(
                status_code=404,
                content=_rejected("SCOPE_MAINTENANCE_NOT_VISIBLE"),
            )
        try:
            await creator_emergency_wake.request_emergency_wake(parsed, uuid7())
        except LifeViolation as error:
            if error.code == "LIFE-MAINTENANCE-NOT-ACTIVE":
                return JSONResponse(
                    status_code=409,
                    content=_rejected("STATE_MAINTENANCE_NOT_ACTIVE"),
                )
            return JSONResponse(
                status_code=503,
                content=_unavailable("DEPENDENCY_MAINTENANCE_WAKE_UNAVAILABLE"),
            )
        return Response(status_code=204)

    del (
        get_creator_maintenance_status,
        get_creator_maintenance_timeline,
        request_creator_emergency_wake,
    )


__all__ = ("register_subject_life_routes",)
