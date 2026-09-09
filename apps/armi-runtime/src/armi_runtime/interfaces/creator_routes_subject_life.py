"""Creator subject, prompt, activity, relationship, memory, and maintenance routes."""

from __future__ import annotations

from armi_runtime.application.creator_calls import CreatorUseCase
from armi_runtime.application.creator_subject_life import create_subject_life_use_cases

from .creator_http import (
    AcceptedOutcomeResponse,
    ActivityReadPort,
    BrowserSessionStore,
    CreatorActivityPageResponse,
    CreatorActivityTimelineResponse,
    CreatorEmergencyWakePort,
    CreatorEventBroker,
    CreatorInputAcceptancePort,
    CreatorLifeMaterialQueryPort,
    CreatorLifeMaterialResponse,
    CreatorMaintenanceQueryPort,
    CreatorMaintenanceStatusResponse,
    CreatorMaintenanceTimelineResponse,
    CreatorMemoryPageResponse,
    CreatorMemoryTimelineResponse,
    CreatorPromptPort,
    CreatorPromptResponse,
    CreatorRelationshipCurrentResponse,
    CreatorRelationshipTimelineResponse,
    FastAPI,
    HTTPBearer,
    LifeRecordPageResponse,
    LifeRecordQueryPort,
    MemoryReadPort,
    Query,
    RejectedOutcomeResponse,
    RelationshipReadPort,
    Request,
    Response,
    Security,
    SecurityEvent,
    SubjectSummaryProvider,
    SubjectSummaryResponse,
    UnavailableOutcomeResponse,
)
from .creator_use_cases import invoke_creator_http


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
) -> dict[str, CreatorUseCase]:
    use_cases = create_subject_life_use_cases(
        emit=emit,
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
        subject_summary=subject_summary,
    )

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
    async def get_subject_summary(request: Request) -> Response:
        return await invoke_creator_http(
            request,
            "subject_summary",
            use_cases["subject_summary"],
            browser_sessions=browser_sessions,
            canonical_origin=canonical_origin,
            maximum_bytes=request_body_max_bytes,
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
    async def get_creator_prompt(request: Request) -> Response:
        return await invoke_creator_http(
            request,
            "prompt_get",
            use_cases["prompt_get"],
            browser_sessions=browser_sessions,
            canonical_origin=canonical_origin,
            maximum_bytes=request_body_max_bytes,
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
    async def revise_creator_prompt(request: Request) -> Response:
        return await invoke_creator_http(
            request,
            "prompt_revise",
            use_cases["prompt_revise"],
            browser_sessions=browser_sessions,
            canonical_origin=canonical_origin,
            maximum_bytes=request_body_max_bytes,
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
    async def deactivate_creator_prompt(request: Request) -> Response:
        return await invoke_creator_http(
            request,
            "prompt_deactivate",
            use_cases["prompt_deactivate"],
            browser_sessions=browser_sessions,
            canonical_origin=canonical_origin,
            maximum_bytes=request_body_max_bytes,
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
    async def list_creator_activities(
        request: Request,
        limit_parameter: str | None = Query(default=None, alias="limit"),
        cursor_parameter: str | None = Query(default=None, alias="cursor"),
    ) -> Response:
        return await invoke_creator_http(
            request,
            "activity_list",
            use_cases["activity_list"],
            browser_sessions=browser_sessions,
            canonical_origin=canonical_origin,
            maximum_bytes=request_body_max_bytes,
        )

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
        activity_id: str,
        request: Request,
        limit_parameter: str | None = Query(default=None, alias="limit"),
        cursor_parameter: str | None = Query(default=None, alias="cursor"),
    ) -> Response:
        return await invoke_creator_http(
            request,
            "activity_timeline",
            use_cases["activity_timeline"],
            browser_sessions=browser_sessions,
            canonical_origin=canonical_origin,
            maximum_bytes=request_body_max_bytes,
        )

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
    async def get_creator_relationship_current(request: Request) -> Response:
        return await invoke_creator_http(
            request,
            "relationship_get",
            use_cases["relationship_get"],
            browser_sessions=browser_sessions,
            canonical_origin=canonical_origin,
            maximum_bytes=request_body_max_bytes,
        )

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
        limit_parameter: str | None = Query(default=None, alias="limit"),
        cursor_parameter: str | None = Query(default=None, alias="cursor"),
    ) -> Response:
        return await invoke_creator_http(
            request,
            "relationship_timeline",
            use_cases["relationship_timeline"],
            browser_sessions=browser_sessions,
            canonical_origin=canonical_origin,
            maximum_bytes=request_body_max_bytes,
        )

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
    async def express_creator_relationship_boundary(request: Request) -> Response:
        return await invoke_creator_http(
            request,
            "relationship_boundary",
            use_cases["relationship_boundary"],
            browser_sessions=browser_sessions,
            canonical_origin=canonical_origin,
            maximum_bytes=request_body_max_bytes,
        )

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
    async def query_creator_life_records(request: Request) -> Response:
        return await invoke_creator_http(
            request,
            "life_record_query",
            use_cases["life_record_query"],
            browser_sessions=browser_sessions,
            canonical_origin=canonical_origin,
            maximum_bytes=request_body_max_bytes,
        )

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
    async def get_creator_life_material(material_id: str, request: Request) -> Response:
        return await invoke_creator_http(
            request,
            "material_get",
            use_cases["material_get"],
            browser_sessions=browser_sessions,
            canonical_origin=canonical_origin,
            maximum_bytes=request_body_max_bytes,
        )

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
    async def list_creator_memories(request: Request) -> Response:
        return await invoke_creator_http(
            request,
            "memory_list",
            use_cases["memory_list"],
            browser_sessions=browser_sessions,
            canonical_origin=canonical_origin,
            maximum_bytes=request_body_max_bytes,
        )

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
    async def get_creator_memory_timeline(memory_id: str, request: Request) -> Response:
        return await invoke_creator_http(
            request,
            "memory_timeline",
            use_cases["memory_timeline"],
            browser_sessions=browser_sessions,
            canonical_origin=canonical_origin,
            maximum_bytes=request_body_max_bytes,
        )

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
    async def get_creator_maintenance_status(request: Request) -> Response:
        return await invoke_creator_http(
            request,
            "maintenance_status",
            use_cases["maintenance_status"],
            browser_sessions=browser_sessions,
            canonical_origin=canonical_origin,
            maximum_bytes=request_body_max_bytes,
        )

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
        limit_parameter: str | None = Query(default=None, alias="limit"),
        cursor_parameter: str | None = Query(default=None, alias="cursor"),
    ) -> Response:
        return await invoke_creator_http(
            request,
            "maintenance_timeline",
            use_cases["maintenance_timeline"],
            browser_sessions=browser_sessions,
            canonical_origin=canonical_origin,
            maximum_bytes=request_body_max_bytes,
        )

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
        maintenance_session_id: str, request: Request
    ) -> Response:
        return await invoke_creator_http(
            request,
            "maintenance_wake",
            use_cases["maintenance_wake"],
            browser_sessions=browser_sessions,
            canonical_origin=canonical_origin,
            maximum_bytes=request_body_max_bytes,
        )

    del (
        get_creator_maintenance_status,
        get_creator_maintenance_timeline,
        request_creator_emergency_wake,
    )
    return use_cases


__all__ = ("register_subject_life_routes",)
