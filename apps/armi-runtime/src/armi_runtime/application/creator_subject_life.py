from __future__ import annotations

from .creator_calls import CreatorCall, CreatorEventSink, CreatorUseCase, creator_result
from .creator_inputs import (
    _creator_boundary_request,
    _creator_prompt_deactivate_request,
    _creator_prompt_revision_request,
    _life_query_parameters,
)
from .creator_projection import (
    UTC,
    UUID,
    ActivityReadPort,
    ActivityViolation,
    ContractViolation,
    CreatorActivityItemResponse,
    CreatorActivityPageResponse,
    CreatorActivityTimelineItemResponse,
    CreatorActivityTimelineResponse,
    CreatorEmergencyWakePort,
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
    CreatorPromptRevisionCommand,
    CreatorPromptViolation,
    CreatorRelationshipCurrentResponse,
    CreatorRelationshipItemResponse,
    CreatorRelationshipTimelineResponse,
    CreatorResourceKind,
    IdempotencyKey,
    Instant,
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
    RelationshipReadPort,
    RelationshipViolation,
    SecurityEvent,
    SubjectComponentSummaryResponse,
    SubjectSummaryProvider,
    SubjectSummaryResponse,
    TraceId,
    _accepted_wire,
    _boundary_message,
    _creator_prompt_error,
    _creator_prompt_response,
    _input_failure,
    _rejected,
    _relationship_revision_response,
    _unavailable,
    cast,
    datetime,
    secrets,
    uuid7,
)
from .interaction import InteractionResult


def create_subject_life_use_cases(
    *,
    emit: SecurityEvent,
    creator_activity_query: ActivityReadPort | None,
    creator_emergency_wake: CreatorEmergencyWakePort | None,
    creator_events: CreatorEventSink | None,
    creator_input: CreatorInputAcceptancePort | None,
    creator_life_material_query: CreatorLifeMaterialQueryPort | None,
    creator_maintenance_query: CreatorMaintenanceQueryPort | None,
    creator_memory_query: MemoryReadPort | None,
    creator_prompt: CreatorPromptPort | None,
    creator_relationship_query: RelationshipReadPort | None,
    life_record_query: LifeRecordQueryPort | None,
    subject_summary: SubjectSummaryProvider | None,
) -> dict[str, CreatorUseCase]:

    async def get_subject_summary(call: CreatorCall) -> InteractionResult:
        if subject_summary is None:
            return creator_result(
                status_code=503,
                content=_unavailable("DEPENDENCY_SUBJECT_SUMMARY_UNAVAILABLE"),
            )
        try:
            summary = await subject_summary()
        except CreatorInputViolation:
            return creator_result(
                status_code=503,
                content=_unavailable("DEPENDENCY_SUBJECT_SUMMARY_UNAVAILABLE"),
            )
        return creator_result(
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
                                "armi.self.v1", "armi.mind.v2", "armi.life-mode.v1"
                            ],
                            item.schema_version,
                        ),
                        content_visibility="private",
                    )
                    for item in summary.components
                ],
                latest_commit_ref=str(summary.latest_commit_ref)
                if summary.latest_commit_ref is not None
                else None,
                observed_at=Instant(summary.observed_at).to_wire(),
            ).model_dump(mode="json", exclude_none=True)
        )

    async def get_creator_prompt(call: CreatorCall) -> InteractionResult:
        if creator_prompt is None:
            return creator_result(
                status_code=503,
                content=_unavailable("DEPENDENCY_CREATOR_PROMPT_UNAVAILABLE"),
            )
        try:
            view = await creator_prompt.get(PromptKind.CREATOR_GUIDANCE)
        except CreatorPromptViolation as error:
            return _creator_prompt_error(error)
        return creator_result(
            content=_creator_prompt_response(view).model_dump(mode="json")
        )

    async def revise_creator_prompt(call: CreatorCall) -> InteractionResult:
        if creator_prompt is None:
            return creator_result(
                status_code=503,
                content=_unavailable("DEPENDENCY_CREATOR_PROMPT_UNAVAILABLE"),
            )
        try:
            body = await _creator_prompt_revision_request(call)
            view = await creator_prompt.revise(
                CreatorPromptRevisionCommand(
                    prompt_kind=PromptKind.CREATOR_GUIDANCE,
                    expected_revision_id=None
                    if body.expected_revision_id is None
                    else UUID(body.expected_revision_id),
                    content=body.content,
                    trace_id=TraceId(secrets.token_hex(16)),
                    delegate_id=call.actor.delegate_id,
                )
            )
        except CreatorPromptViolation as error:
            return _creator_prompt_error(error)
        return creator_result(
            content=_creator_prompt_response(view).model_dump(mode="json")
        )

    async def deactivate_creator_prompt(call: CreatorCall) -> InteractionResult:
        if creator_prompt is None:
            return creator_result(
                status_code=503,
                content=_unavailable("DEPENDENCY_CREATOR_PROMPT_UNAVAILABLE"),
            )
        try:
            body = await _creator_prompt_deactivate_request(call)
            view = await creator_prompt.deactivate(
                CreatorPromptDeactivateCommand(
                    prompt_kind=PromptKind.CREATOR_GUIDANCE,
                    expected_revision_id=UUID(body.expected_revision_id),
                    trace_id=TraceId(secrets.token_hex(16)),
                    delegate_id=call.actor.delegate_id,
                )
            )
        except CreatorPromptViolation as error:
            return _creator_prompt_error(error)
        return creator_result(
            content=_creator_prompt_response(view).model_dump(mode="json")
        )

    async def list_creator_activities(call: CreatorCall) -> InteractionResult:
        if creator_activity_query is None:
            return creator_result(
                status_code=503,
                content=_unavailable("DEPENDENCY_ACTIVITY_QUERY_UNAVAILABLE"),
            )
        try:
            limit, _query, _kind, cursor = _life_query_parameters(
                call, allow_kind=False, allow_text=False
            )
            page = await creator_activity_query.list_current(limit=limit, cursor=cursor)
        except ContractViolation:
            return creator_result(
                status_code=400, content=_rejected("INPUT_PAGE_INVALID")
            )
        except ActivityViolation as error:
            if error.code == "ACTIVITY-CURSOR":
                return creator_result(
                    status_code=400, content=_rejected("INPUT_CURSOR_INVALID")
                )
            if error.code == "ACTIVITY-CURSOR-STALE":
                return creator_result(
                    status_code=409, content=_rejected("CONFLICT_CURSOR_STALE")
                )
            return creator_result(
                status_code=503,
                content=_unavailable("DEPENDENCY_ACTIVITY_QUERY_UNAVAILABLE"),
            )
        response = CreatorActivityPageResponse(
            contract_version="1.0",
            projection_version="creator-activity.v2",
            items=[
                CreatorActivityItemResponse(
                    activity_id=str(item.activity_id),
                    activity_kind=item.activity_kind,
                    status=item.status.value,
                    goal=item.goal,
                    progress_summary=item.progress_summary,
                    waiting_kind=None
                    if item.waiting_kind is None
                    else item.waiting_kind.value,
                    waiting_summary=item.waiting_summary,
                    resume_not_before=None
                    if item.resume_not_before is None
                    else Instant(item.resume_not_before).to_wire(),
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
            next_cursor=None
            if page.next_cursor is None
            else page.next_cursor.to_wire(),
        )
        return creator_result(content=response.model_dump(mode="json"))

    async def get_creator_activity_timeline(
        activity_id: str, call: CreatorCall
    ) -> InteractionResult:
        if creator_activity_query is None:
            return creator_result(
                status_code=503,
                content=_unavailable("DEPENDENCY_ACTIVITY_QUERY_UNAVAILABLE"),
            )
        try:
            parsed = UUID(activity_id)
            if parsed.version != 7 or str(parsed) != activity_id:
                raise ValueError
        except ValueError:
            return creator_result(
                status_code=404, content=_rejected("SCOPE_ACTIVITY_NOT_VISIBLE")
            )
        try:
            limit, _query, _kind, cursor = _life_query_parameters(
                call, allow_kind=False, allow_text=False
            )
            timeline = await creator_activity_query.timeline(
                parsed, limit=limit, cursor=cursor
            )
        except ContractViolation:
            return creator_result(
                status_code=400, content=_rejected("INPUT_PAGE_INVALID")
            )
        except ActivityViolation as error:
            if error.code == "ACTIVITY-QUERY-NOT-FOUND":
                return creator_result(
                    status_code=404, content=_rejected("SCOPE_ACTIVITY_NOT_VISIBLE")
                )
            if error.code == "ACTIVITY-CURSOR":
                return creator_result(
                    status_code=400, content=_rejected("INPUT_CURSOR_INVALID")
                )
            if error.code == "ACTIVITY-CURSOR-STALE":
                return creator_result(
                    status_code=409, content=_rejected("CONFLICT_CURSOR_STALE")
                )
            return creator_result(
                status_code=503,
                content=_unavailable("DEPENDENCY_ACTIVITY_QUERY_UNAVAILABLE"),
            )
        response = CreatorActivityTimelineResponse(
            contract_version="1.0",
            projection_version="creator-activity.v2",
            activity_id=str(timeline.activity_id),
            items=[
                CreatorActivityTimelineItemResponse(
                    event_id=str(item.event_id),
                    event_kind=item.event_kind,
                    resulting_status=None
                    if item.resulting_status is None
                    else item.resulting_status.value,
                    summary=item.summary,
                    review_not_before=None
                    if item.review_not_before is None
                    else Instant(item.review_not_before).to_wire(),
                    occurred_at=Instant(item.occurred_at).to_wire(),
                )
                for item in timeline.items
            ],
            next_cursor=None
            if timeline.next_cursor is None
            else timeline.next_cursor.to_wire(),
        )
        return creator_result(content=response.model_dump(mode="json"))

    async def get_creator_relationship_current(call: CreatorCall) -> InteractionResult:
        if creator_relationship_query is None:
            return creator_result(
                status_code=503,
                content=_unavailable("DEPENDENCY_RELATIONSHIP_QUERY_UNAVAILABLE"),
            )
        try:
            item = await creator_relationship_query.current()
        except RelationshipViolation:
            return creator_result(
                status_code=503,
                content=_unavailable("DEPENDENCY_RELATIONSHIP_QUERY_UNAVAILABLE"),
            )
        response = CreatorRelationshipCurrentResponse(
            contract_version="1.0",
            projection_version="creator-relationship.v3",
            relationship=None
            if item is None
            else CreatorRelationshipItemResponse(
                relationship_id=str(item.relationship_id),
                current_revision_id=str(item.current_revision_id),
                head_version=item.head_version,
                current=_relationship_revision_response(item.current),
                created_at=Instant(item.created_at).to_wire(),
            ),
        )
        return creator_result(content=response.model_dump(mode="json"))

    async def get_creator_relationship_timeline(
        relationship_id: str, call: CreatorCall
    ) -> InteractionResult:
        if creator_relationship_query is None:
            return creator_result(
                status_code=503,
                content=_unavailable("DEPENDENCY_RELATIONSHIP_QUERY_UNAVAILABLE"),
            )
        try:
            parsed = UUID(relationship_id)
            if parsed.version != 7 or str(parsed) != relationship_id:
                raise ValueError
        except ValueError:
            return creator_result(
                status_code=404, content=_rejected("SCOPE_RELATIONSHIP_NOT_VISIBLE")
            )
        try:
            limit, _query, _kind, cursor = _life_query_parameters(
                call, allow_kind=False, allow_text=False
            )
            timeline = await creator_relationship_query.timeline(
                parsed, limit=limit, cursor=cursor
            )
        except ContractViolation:
            return creator_result(
                status_code=400, content=_rejected("INPUT_PAGE_INVALID")
            )
        except RelationshipViolation as error:
            if error.code == "RELATIONSHIP-QUERY-NOT-FOUND":
                return creator_result(
                    status_code=404, content=_rejected("SCOPE_RELATIONSHIP_NOT_VISIBLE")
                )
            if error.code == "RELATIONSHIP-CURSOR":
                return creator_result(
                    status_code=400, content=_rejected("INPUT_CURSOR_INVALID")
                )
            if error.code == "RELATIONSHIP-CURSOR-STALE":
                return creator_result(
                    status_code=409, content=_rejected("CONFLICT_CURSOR_STALE")
                )
            return creator_result(
                status_code=503,
                content=_unavailable("DEPENDENCY_RELATIONSHIP_QUERY_UNAVAILABLE"),
            )
        response = CreatorRelationshipTimelineResponse(
            contract_version="1.0",
            projection_version="creator-relationship.v3",
            relationship_id=str(timeline.relationship_id),
            items=[_relationship_revision_response(item) for item in timeline.items],
            next_cursor=None
            if timeline.next_cursor is None
            else timeline.next_cursor.to_wire(),
        )
        return creator_result(content=response.model_dump(mode="json"))

    async def express_creator_relationship_boundary(
        call: CreatorCall,
    ) -> InteractionResult:
        if creator_input is None:
            return creator_result(
                status_code=503,
                content=_unavailable("DEPENDENCY_RELATIONSHIP_INPUT_UNAVAILABLE"),
            )
        metadata = call.actor
        idempotency_value = call.idempotency_key
        if idempotency_value is None:
            return creator_result(
                status_code=400, content=_rejected("INPUT_IDEMPOTENCY_KEY")
            )
        try:
            model = await _creator_boundary_request(call)
            acceptance = await creator_input.accept(
                CreatorInputCommand(
                    scene_key=metadata.default_scene_key,
                    message=_boundary_message(model),
                    delegate_id=call.actor.delegate_id,
                    idempotency_key=IdempotencyKey(idempotency_value),
                    trace_id=TraceId(secrets.token_hex(16)),
                )
            )
        except (ContractViolation, CreatorInputViolation) as error:
            if isinstance(error, ContractViolation):
                status, content = (400, _rejected("INPUT_IDEMPOTENCY_KEY"))
            else:
                status, content = _input_failure(error)
            emit("creator.relationship_boundary.rejected")
            return creator_result(status_code=status, content=content)
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
                        "creator-operation.v4",
                    )
                )
            except Exception:
                emit("creator.operation.notification_failed")
        return creator_result(status_code=202, content=_accepted_wire(acceptance))

    async def query_creator_life_records(call: CreatorCall) -> InteractionResult:
        if life_record_query is None:
            return creator_result(
                status_code=503,
                content=_unavailable("DEPENDENCY_LIFE_QUERY_UNAVAILABLE"),
            )
        try:
            limit, query_text, record_kind, cursor = _life_query_parameters(
                call, allow_kind=True, allow_text=True
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
            return creator_result(
                status_code=400, content=_rejected("INPUT_LIFE_QUERY_INVALID")
            )
        except LifeRecordQueryViolation as error:
            if error.code == "LIFE-QUERY-CURSOR-INVALID":
                return creator_result(
                    status_code=400, content=_rejected("INPUT_CURSOR_INVALID")
                )
            if error.code == "LIFE-QUERY-CURSOR-STALE":
                return creator_result(
                    status_code=409, content=_rejected("CONFLICT_CURSOR_STALE")
                )
            return creator_result(
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
            next_cursor=None
            if page.next_cursor is None
            else page.next_cursor.to_wire(),
        )
        return creator_result(content=response.model_dump(mode="json"))

    async def get_creator_life_material(
        material_id: str, call: CreatorCall
    ) -> InteractionResult:
        if creator_life_material_query is None:
            return creator_result(
                status_code=503,
                content=_unavailable("DEPENDENCY_LIFE_MATERIAL_QUERY_UNAVAILABLE"),
            )
        try:
            parsed = UUID(material_id)
            if parsed.version != 7 or str(parsed) != material_id:
                raise ValueError
        except ValueError:
            return creator_result(
                status_code=404, content=_rejected("SCOPE_LIFE_MATERIAL_NOT_VISIBLE")
            )
        try:
            item = await creator_life_material_query.get_creator_visible(parsed)
        except MaterialViolation:
            return creator_result(
                status_code=503,
                content=_unavailable("DEPENDENCY_LIFE_MATERIAL_QUERY_UNAVAILABLE"),
            )
        if item is None:
            return creator_result(
                status_code=404, content=_rejected("SCOPE_LIFE_MATERIAL_NOT_VISIBLE")
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
        return creator_result(content=response.model_dump(mode="json"))

    async def list_creator_memories(call: CreatorCall) -> InteractionResult:
        if creator_memory_query is None:
            return creator_result(
                status_code=503,
                content=_unavailable("DEPENDENCY_MEMORY_QUERY_UNAVAILABLE"),
            )
        try:
            limit, query_text, _kind, cursor = _life_query_parameters(
                call, allow_kind=False, allow_text=True
            )
            page = await creator_memory_query.list_current(
                limit=limit, query_text=query_text, cursor=cursor
            )
        except ContractViolation:
            return creator_result(
                status_code=400, content=_rejected("INPUT_MEMORY_QUERY_INVALID")
            )
        except LifeRecordQueryViolation as error:
            if error.code == "LIFE-QUERY-CURSOR-INVALID":
                return creator_result(
                    status_code=400, content=_rejected("INPUT_CURSOR_INVALID")
                )
            if error.code == "LIFE-QUERY-CURSOR-STALE":
                return creator_result(
                    status_code=409, content=_rejected("CONFLICT_CURSOR_STALE")
                )
            return creator_result(
                status_code=503,
                content=_unavailable("DEPENDENCY_MEMORY_QUERY_UNAVAILABLE"),
            )
        except MemoryViolation as error:
            if error.code == "MEMORY-CURSOR":
                return creator_result(
                    status_code=400, content=_rejected("INPUT_CURSOR_INVALID")
                )
            if error.code == "MEMORY-CURSOR-STALE":
                return creator_result(
                    status_code=409, content=_rejected("CONFLICT_CURSOR_STALE")
                )
            return creator_result(
                status_code=503,
                content=_unavailable("DEPENDENCY_MEMORY_QUERY_UNAVAILABLE"),
            )
        response = CreatorMemoryPageResponse(
            contract_version="1.0",
            projection_version="creator-memory.v2",
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
            next_cursor=None
            if page.next_cursor is None
            else page.next_cursor.to_wire(),
        )
        return creator_result(content=response.model_dump(mode="json"))

    async def get_creator_memory_timeline(
        memory_id: str, call: CreatorCall
    ) -> InteractionResult:
        if creator_memory_query is None:
            return creator_result(
                status_code=503,
                content=_unavailable("DEPENDENCY_MEMORY_QUERY_UNAVAILABLE"),
            )
        try:
            parsed = UUID(memory_id)
            if parsed.version != 7 or str(parsed) != memory_id:
                raise ValueError
        except ValueError:
            return creator_result(
                status_code=404, content=_rejected("SCOPE_MEMORY_NOT_VISIBLE")
            )
        try:
            limit, _query_text, _kind, cursor = _life_query_parameters(
                call, allow_kind=False, allow_text=False
            )
            timeline = await creator_memory_query.timeline(
                parsed, limit=limit, cursor=cursor
            )
        except ContractViolation:
            return creator_result(
                status_code=400, content=_rejected("INPUT_MEMORY_QUERY_INVALID")
            )
        except LifeRecordQueryViolation as error:
            if error.code == "LIFE-QUERY-NOT-FOUND":
                return creator_result(
                    status_code=404, content=_rejected("SCOPE_MEMORY_NOT_VISIBLE")
                )
            if error.code == "LIFE-QUERY-CURSOR-INVALID":
                return creator_result(
                    status_code=400, content=_rejected("INPUT_CURSOR_INVALID")
                )
            if error.code == "LIFE-QUERY-CURSOR-STALE":
                return creator_result(
                    status_code=409, content=_rejected("CONFLICT_CURSOR_STALE")
                )
            return creator_result(
                status_code=503,
                content=_unavailable("DEPENDENCY_MEMORY_QUERY_UNAVAILABLE"),
            )
        except MemoryViolation as error:
            if error.code == "MEMORY-QUERY-NOT-FOUND":
                return creator_result(
                    status_code=404, content=_rejected("SCOPE_MEMORY_NOT_VISIBLE")
                )
            if error.code == "MEMORY-CURSOR":
                return creator_result(
                    status_code=400, content=_rejected("INPUT_CURSOR_INVALID")
                )
            if error.code == "MEMORY-CURSOR-STALE":
                return creator_result(
                    status_code=409, content=_rejected("CONFLICT_CURSOR_STALE")
                )
            return creator_result(
                status_code=503,
                content=_unavailable("DEPENDENCY_MEMORY_QUERY_UNAVAILABLE"),
            )
        response = CreatorMemoryTimelineResponse(
            contract_version="1.0",
            projection_version="creator-memory.v2",
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
                    relation_kind=None
                    if item.relation_kind is None
                    else item.relation_kind.value,
                    related_memory_id=None
                    if item.related_memory_id is None
                    else str(item.related_memory_id),
                    occurred_at=item.occurred_at.to_wire(),
                )
                for item in timeline.items
            ],
            next_cursor=None
            if timeline.next_cursor is None
            else timeline.next_cursor.to_wire(),
        )
        return creator_result(content=response.model_dump(mode="json"))

    async def get_creator_maintenance_status(call: CreatorCall) -> InteractionResult:
        if creator_maintenance_query is None:
            return creator_result(
                status_code=503,
                content=_unavailable("DEPENDENCY_MAINTENANCE_QUERY_UNAVAILABLE"),
            )
        try:
            status = await creator_maintenance_query.status()
        except CreatorMaintenanceViolation:
            return creator_result(
                status_code=503,
                content=_unavailable("DEPENDENCY_MAINTENANCE_QUERY_UNAVAILABLE"),
            )
        session = status.session
        response = CreatorMaintenanceStatusResponse(
            contract_version="1.0",
            projection_version="creator-maintenance.v3",
            session=None
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
                finished_at=None
                if session.finished_at is None
                else Instant(session.finished_at).to_wire(),
            ),
            waiting_input_count=status.waiting_input_count,
        )
        return creator_result(content=response.model_dump(mode="json"))

    async def get_creator_maintenance_timeline(
        maintenance_session_id: str, call: CreatorCall
    ) -> InteractionResult:
        if creator_maintenance_query is None:
            return creator_result(
                status_code=503,
                content=_unavailable("DEPENDENCY_MAINTENANCE_QUERY_UNAVAILABLE"),
            )
        try:
            parsed = UUID(maintenance_session_id)
            if parsed.version != 7 or str(parsed) != maintenance_session_id:
                raise ValueError
        except ValueError:
            return creator_result(
                status_code=404, content=_rejected("SCOPE_MAINTENANCE_NOT_VISIBLE")
            )
        try:
            limit, _query, _kind, cursor = _life_query_parameters(
                call, allow_kind=False, allow_text=False
            )
            timeline = await creator_maintenance_query.timeline(
                parsed, limit=limit, cursor=cursor
            )
        except ContractViolation:
            return creator_result(
                status_code=400, content=_rejected("INPUT_PAGE_INVALID")
            )
        except CreatorMaintenanceViolation as error:
            if error.code == "MAINTENANCE-QUERY-NOT-FOUND":
                return creator_result(
                    status_code=404, content=_rejected("SCOPE_MAINTENANCE_NOT_VISIBLE")
                )
            if error.code == "MAINTENANCE-QUERY-CURSOR":
                return creator_result(
                    status_code=400, content=_rejected("INPUT_CURSOR_INVALID")
                )
            if error.code == "MAINTENANCE-QUERY-CURSOR-STALE":
                return creator_result(
                    status_code=409, content=_rejected("CONFLICT_CURSOR_STALE")
                )
            return creator_result(
                status_code=503,
                content=_unavailable("DEPENDENCY_MAINTENANCE_QUERY_UNAVAILABLE"),
            )
        response = CreatorMaintenanceTimelineResponse(
            contract_version="1.0",
            projection_version="creator-maintenance.v3",
            maintenance_session_id=str(timeline.session_id),
            items=[
                CreatorMaintenanceTimelineItemResponse(
                    revision_id=str(item.revision_id),
                    revision_no=item.revision_no,
                    phase=item.phase.value,
                    result_status=item.result_status.value,
                    transition_kind=item.transition_kind,
                    occurred_at=Instant(item.occurred_at).to_wire(),
                    work_outcome=None
                    if item.work_outcome is None
                    else item.work_outcome.value,
                    problem_summary=item.problem_summary,
                )
                for item in timeline.items
            ],
            next_cursor=None
            if timeline.next_cursor is None
            else timeline.next_cursor.to_wire(),
        )
        return creator_result(content=response.model_dump(mode="json"))

    async def request_creator_emergency_wake(
        maintenance_session_id: str, call: CreatorCall
    ) -> InteractionResult:
        if creator_emergency_wake is None:
            return creator_result(
                status_code=503,
                content=_unavailable("DEPENDENCY_MAINTENANCE_WAKE_UNAVAILABLE"),
            )
        try:
            parsed = UUID(maintenance_session_id)
            if parsed.version != 7 or str(parsed) != maintenance_session_id:
                raise ValueError
        except ValueError:
            return creator_result(
                status_code=404, content=_rejected("SCOPE_MAINTENANCE_NOT_VISIBLE")
            )
        try:
            await creator_emergency_wake.request_emergency_wake(parsed, uuid7())
        except LifeViolation as error:
            if error.code == "LIFE-MAINTENANCE-NOT-ACTIVE":
                return creator_result(
                    status_code=409, content=_rejected("STATE_MAINTENANCE_NOT_ACTIVE")
                )
            return creator_result(
                status_code=503,
                content=_unavailable("DEPENDENCY_MAINTENANCE_WAKE_UNAVAILABLE"),
            )
        return creator_result(status_code=204)

    return {
        "subject_summary": get_subject_summary,
        "prompt_get": get_creator_prompt,
        "prompt_revise": revise_creator_prompt,
        "prompt_deactivate": deactivate_creator_prompt,
        "activity_list": list_creator_activities,
        "activity_timeline": get_creator_activity_timeline,
        "relationship_get": get_creator_relationship_current,
        "relationship_timeline": get_creator_relationship_timeline,
        "relationship_boundary": express_creator_relationship_boundary,
        "life_record_query": query_creator_life_records,
        "material_get": get_creator_life_material,
        "memory_list": list_creator_memories,
        "memory_timeline": get_creator_memory_timeline,
        "maintenance_status": get_creator_maintenance_status,
        "maintenance_timeline": get_creator_maintenance_timeline,
        "maintenance_wake": request_creator_emergency_wake,
    }


__all__ = ("create_subject_life_use_cases",)
