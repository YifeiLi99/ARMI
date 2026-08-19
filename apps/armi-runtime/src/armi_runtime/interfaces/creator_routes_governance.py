"""Creator capability, export, and data-rights routes."""

from __future__ import annotations

from .creator_http import (
    UTC,
    UUID,
    AppliedOutcome,
    AppliedOutcomeResponse,
    BrowserSessionStore,
    BrowserSessionViolation,
    CapabilityDecisionId,
    CapabilityPolicyPort,
    CapabilityRequestId,
    CapabilityRequestItemResponse,
    CapabilityRequestPageResponse,
    CapabilityViolation,
    ContractViolation,
    CreatorEventBroker,
    CreatorExportCommand,
    CreatorExportPort,
    CreatorExportResponse,
    CreatorExportViolation,
    CreatorGrantCommand,
    CreatorGrantDecision,
    CreatorProjectionInvalidation,
    CreatorResourceKind,
    DataRightsOrderCollectionResponse,
    DataRightsOrderCommand,
    DataRightsOrderDetailResponse,
    DataRightsOrderKind,
    DataRightsOrderPort,
    DataRightsOrderResponse,
    DataRightsViolation,
    FastAPI,
    HTTPBearer,
    IdempotencyKey,
    Instant,
    JSONResponse,
    RejectedOutcomeResponse,
    Request,
    ResultRef,
    Security,
    SecurityEvent,
    TraceId,
    UnavailableOutcomeResponse,
    _bearer,
    _browser_boundary,
    _capability_decision_request,
    _creator_export_error,
    _creator_export_request,
    _creator_export_response,
    _data_rights_detail_response,
    _data_rights_error,
    _data_rights_request,
    _data_rights_response,
    _outcome_common,
    _rejected,
    _unavailable,
    datetime,
    secrets,
)


def register_governance_routes(
    *,
    app: FastAPI,
    bearer: HTTPBearer,
    canonical_origin: str,
    emit: SecurityEvent,
    browser_sessions: BrowserSessionStore | None,
    capability_policy: CapabilityPolicyPort | None,
    creator_events: CreatorEventBroker | None,
    creator_export: CreatorExportPort | None,
    data_rights: DataRightsOrderPort | None,
    request_body_max_bytes: int,
) -> None:
    @app.post(
        "/v1/exports",
        operation_id="createCreatorExport",
        status_code=201,
        response_model=CreatorExportResponse,
        responses={
            200: {"model": CreatorExportResponse},
            400: {"model": RejectedOutcomeResponse},
            401: {"model": RejectedOutcomeResponse},
            403: {"model": RejectedOutcomeResponse},
            409: {"model": RejectedOutcomeResponse},
            413: {"model": RejectedOutcomeResponse},
            503: {"model": UnavailableOutcomeResponse},
        },
        dependencies=[Security(bearer)],
    )
    async def create_creator_export(request: Request) -> JSONResponse:
        if (
            browser_sessions is None
            or creator_export is None
            or not _browser_boundary(request, canonical_origin=canonical_origin)
        ):
            status = (
                403
                if browser_sessions is not None and creator_export is not None
                else 503
            )
            return JSONResponse(
                status_code=status,
                content=(
                    _rejected("AUTH_BROWSER_BOUNDARY")
                    if status == 403
                    else _unavailable("DEPENDENCY_CREATOR_EXPORT_UNAVAILABLE")
                ),
            )
        token = _bearer(request)
        try:
            if token is None:
                raise BrowserSessionViolation("AUTH_SESSION_REQUIRED")
            browser_sessions.verify(token)
            idempotency_value = request.headers.get("idempotency-key")
            if idempotency_value is None:
                raise CreatorExportViolation("CREATOR-EXPORT-COMMAND")
            try:
                idempotency_key = IdempotencyKey.from_wire(idempotency_value)
            except ContractViolation:
                raise CreatorExportViolation("CREATOR-EXPORT-COMMAND") from None
            body = await _creator_export_request(request, request_body_max_bytes)
            result = await creator_export.export(
                CreatorExportCommand(
                    directory_name=body.directory_name,
                    idempotency_key=idempotency_key,
                    trace_id=TraceId(secrets.token_hex(16)),
                )
            )
        except BrowserSessionViolation as error:
            return JSONResponse(
                status_code=error.status_code,
                content=_rejected(error.code),
            )
        except CreatorExportViolation as error:
            return _creator_export_error(error)
        return JSONResponse(
            status_code=201 if result.newly_created else 200,
            content=_creator_export_response(result).model_dump(mode="json"),
        )

    @app.get(
        "/v1/exports/{export_id}",
        operation_id="getCreatorExport",
        response_model=CreatorExportResponse,
        responses={
            400: {"model": RejectedOutcomeResponse},
            401: {"model": RejectedOutcomeResponse},
            403: {"model": RejectedOutcomeResponse},
            404: {"model": RejectedOutcomeResponse},
            503: {"model": UnavailableOutcomeResponse},
        },
        dependencies=[Security(bearer)],
    )
    async def get_creator_export(request: Request, export_id: str) -> JSONResponse:
        if (
            browser_sessions is None
            or creator_export is None
            or not _browser_boundary(request, canonical_origin=canonical_origin)
        ):
            status = (
                403
                if browser_sessions is not None and creator_export is not None
                else 503
            )
            return JSONResponse(
                status_code=status,
                content=(
                    _rejected("AUTH_BROWSER_BOUNDARY")
                    if status == 403
                    else _unavailable("DEPENDENCY_CREATOR_EXPORT_UNAVAILABLE")
                ),
            )
        token = _bearer(request)
        try:
            if token is None:
                raise BrowserSessionViolation("AUTH_SESSION_REQUIRED")
            browser_sessions.verify(token)
            try:
                export_uuid = UUID(export_id)
            except ValueError:
                raise CreatorExportViolation("CREATOR-EXPORT-ID") from None
            result = await creator_export.get(export_uuid)
        except BrowserSessionViolation as error:
            return JSONResponse(
                status_code=error.status_code,
                content=_rejected(error.code),
            )
        except CreatorExportViolation as error:
            return _creator_export_error(error)
        if result is None:
            return JSONResponse(
                status_code=404,
                content=_rejected("CREATOR_EXPORT_NOT_FOUND"),
            )
        return JSONResponse(
            content=_creator_export_response(result).model_dump(mode="json")
        )

    del create_creator_export, get_creator_export

    @app.get(
        "/v1/data-rights/orders",
        operation_id="listDataRightsOrders",
        response_model=DataRightsOrderCollectionResponse,
        responses={
            401: {"model": RejectedOutcomeResponse},
            403: {"model": RejectedOutcomeResponse},
            503: {"model": UnavailableOutcomeResponse},
        },
        dependencies=[Security(bearer)],
    )
    async def list_creator_data_rights_orders(request: Request) -> JSONResponse:
        if (
            browser_sessions is None
            or data_rights is None
            or not _browser_boundary(request, canonical_origin=canonical_origin)
        ):
            status = (
                403 if browser_sessions is not None and data_rights is not None else 503
            )
            return JSONResponse(
                status_code=status,
                content=_rejected("AUTH_BROWSER_BOUNDARY")
                if status == 403
                else _unavailable("DEPENDENCY_DATA_RIGHTS_UNAVAILABLE"),
            )
        try:
            token = _bearer(request)
            if token is None:
                raise BrowserSessionViolation("AUTH_SESSION_REQUIRED")
            browser_sessions.verify(token)
            details = await data_rights.list_creator()
        except BrowserSessionViolation as error:
            return JSONResponse(
                status_code=error.status_code, content=_rejected(error.code)
            )
        except DataRightsViolation as error:
            return _data_rights_error(error)
        return JSONResponse(
            content=DataRightsOrderCollectionResponse(
                contract_version="1.0",
                projection_version="data-rights-order.v2",
                orders=[_data_rights_detail_response(detail) for detail in details],
            ).model_dump(mode="json")
        )

    @app.post(
        "/v1/data-rights/orders",
        operation_id="createDataRightsOrder",
        status_code=201,
        response_model=DataRightsOrderResponse,
        responses={
            200: {"model": DataRightsOrderResponse},
            400: {"model": RejectedOutcomeResponse},
            401: {"model": RejectedOutcomeResponse},
            403: {"model": RejectedOutcomeResponse},
            409: {"model": RejectedOutcomeResponse},
            413: {"model": RejectedOutcomeResponse},
            503: {"model": UnavailableOutcomeResponse},
        },
        dependencies=[Security(bearer)],
    )
    async def create_creator_data_rights_order(request: Request) -> JSONResponse:
        if (
            browser_sessions is None
            or data_rights is None
            or not _browser_boundary(request, canonical_origin=canonical_origin)
        ):
            status = (
                403 if browser_sessions is not None and data_rights is not None else 503
            )
            return JSONResponse(
                status_code=status,
                content=(
                    _rejected("AUTH_BROWSER_BOUNDARY")
                    if status == 403
                    else _unavailable("DEPENDENCY_DATA_RIGHTS_UNAVAILABLE")
                ),
            )
        token = _bearer(request)
        try:
            if token is None:
                raise BrowserSessionViolation("AUTH_SESSION_REQUIRED")
            browser_sessions.verify(token)
            idempotency_value = request.headers.get("idempotency-key")
            if idempotency_value is None:
                raise DataRightsViolation("DATA-RIGHTS-COMMAND")
            try:
                idempotency_key = IdempotencyKey.from_wire(idempotency_value)
            except ContractViolation:
                raise DataRightsViolation("DATA-RIGHTS-COMMAND") from None
            body = await _data_rights_request(request, request_body_max_bytes)
            result = await data_rights.request_creator(
                DataRightsOrderCommand(
                    DataRightsOrderKind(body.order_kind),
                    idempotency_key,
                    TraceId(secrets.token_hex(16)),
                )
            )
        except BrowserSessionViolation as error:
            return JSONResponse(
                status_code=error.status_code,
                content=_rejected(error.code),
            )
        except DataRightsViolation as error:
            return _data_rights_error(error)
        return JSONResponse(
            status_code=201 if result.newly_created else 200,
            content=_data_rights_response(result).model_dump(mode="json"),
        )

    @app.get(
        "/v1/data-rights/orders/{order_id}",
        operation_id="getDataRightsOrder",
        response_model=DataRightsOrderDetailResponse,
        responses={
            400: {"model": RejectedOutcomeResponse},
            401: {"model": RejectedOutcomeResponse},
            403: {"model": RejectedOutcomeResponse},
            404: {"model": RejectedOutcomeResponse},
            503: {"model": UnavailableOutcomeResponse},
        },
        dependencies=[Security(bearer)],
    )
    async def get_creator_data_rights_order(
        request: Request, order_id: str
    ) -> JSONResponse:
        if (
            browser_sessions is None
            or data_rights is None
            or not _browser_boundary(request, canonical_origin=canonical_origin)
        ):
            status = (
                403 if browser_sessions is not None and data_rights is not None else 503
            )
            return JSONResponse(
                status_code=status,
                content=(
                    _rejected("AUTH_BROWSER_BOUNDARY")
                    if status == 403
                    else _unavailable("DEPENDENCY_DATA_RIGHTS_UNAVAILABLE")
                ),
            )
        token = _bearer(request)
        try:
            if token is None:
                raise BrowserSessionViolation("AUTH_SESSION_REQUIRED")
            browser_sessions.verify(token)
            try:
                order_uuid = UUID(order_id)
            except ValueError:
                raise DataRightsViolation("DATA-RIGHTS-ORDER-ID") from None
            result = await data_rights.detail_creator(order_uuid)
        except BrowserSessionViolation as error:
            return JSONResponse(
                status_code=error.status_code,
                content=_rejected(error.code),
            )
        except DataRightsViolation as error:
            return _data_rights_error(error)
        if result is None:
            return JSONResponse(
                status_code=404,
                content=_rejected("SCOPE_DATA_RIGHTS_ORDER_NOT_FOUND"),
            )
        return JSONResponse(
            content=_data_rights_detail_response(result).model_dump(mode="json")
        )

    del list_creator_data_rights_orders, create_creator_data_rights_order
    del get_creator_data_rights_order

    @app.get(
        "/v1/capability-requests",
        operation_id="listCapabilityRequests",
        response_model=CapabilityRequestPageResponse,
        responses={
            400: {"model": RejectedOutcomeResponse},
            401: {"model": RejectedOutcomeResponse},
            403: {"model": RejectedOutcomeResponse},
            409: {"model": RejectedOutcomeResponse},
            503: {"model": UnavailableOutcomeResponse},
        },
        dependencies=[Security(bearer)],
    )
    async def list_capability_requests(request: Request) -> JSONResponse:
        if (
            browser_sessions is None
            or capability_policy is None
            or not _browser_boundary(request, canonical_origin=canonical_origin)
        ):
            status = 403 if browser_sessions is not None else 503
            return JSONResponse(
                status_code=status,
                content=(
                    _rejected("AUTH_BROWSER_BOUNDARY")
                    if status == 403
                    else _unavailable("DEPENDENCY_CAPABILITY_POLICY_UNAVAILABLE")
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
        pairs = list(request.query_params.multi_items())
        names = [name for name, _value in pairs]
        if set(names) - {"limit", "cursor"} or any(
            names.count(name) > 1 for name in {"limit", "cursor"}
        ):
            return JSONResponse(
                status_code=400,
                content=_rejected("INPUT_PAGE_LIMIT"),
            )
        values = dict(pairs)
        limit_text = values.get("limit", "50")
        if not limit_text.isascii() or not limit_text.isdecimal():
            return JSONResponse(
                status_code=400,
                content=_rejected("INPUT_PAGE_LIMIT"),
            )
        limit = int(limit_text)
        if not 1 <= limit <= 100:
            return JSONResponse(
                status_code=400,
                content=_rejected("INPUT_PAGE_LIMIT"),
            )
        try:
            page = await capability_policy.list_requests(
                creator_party_id=metadata.creator_party_id,
                limit=limit,
                cursor=values.get("cursor"),
            )
        except CapabilityViolation as error:
            if error.code == "CONFLICT-CAPABILITY-CURSOR-STALE":
                return JSONResponse(
                    status_code=409,
                    content=_rejected("CONFLICT_CURSOR_STALE"),
                )
            if error.code == "CON-CAPABILITY-CURSOR":
                return JSONResponse(
                    status_code=400,
                    content=_rejected("INPUT_CURSOR_INVALID"),
                )
            return JSONResponse(
                status_code=503,
                content=_unavailable("DEPENDENCY_CAPABILITY_POLICY_UNAVAILABLE"),
            )
        response = CapabilityRequestPageResponse(
            contract_version="1.0",
            projection_version="capability-request.v4",
            items=[
                CapabilityRequestItemResponse.model_validate(
                    {
                        "capability_request_id": str(item.capability_request_id),
                        "capability_kind": item.capability_kind,
                        "operation": item.operation,
                        "subject_id": str(item.subject_id),
                        "scene_id": str(item.scene_id),
                        "audience_scope": item.audience_scope,
                        "data_scope": item.data_scope,
                        "purpose": item.purpose,
                        "workspace_scope": item.workspace_scope,
                        "artifact_scope": item.artifact_scope,
                        "network_access": item.network_access,
                        "valid_for_seconds": item.valid_for_seconds,
                        "max_uses": item.max_uses,
                        "max_payload_bytes": item.max_payload_bytes,
                        "status": item.status,
                        "request_version": item.request_version,
                        "capability_availability": item.capability_availability,
                        "resolution_reason_code": item.resolution_reason_code,
                        "created_at": Instant(item.created_at).to_wire(),
                        "status_changed_at": Instant(item.status_changed_at).to_wire(),
                        **(
                            {
                                "effective_grant": {
                                    "scope_kind": item.effective_grant.scope_kind,
                                    "grant_ref": str(item.effective_grant.grant_ref),
                                    "status": item.effective_grant.status,
                                    "max_uses": item.effective_grant.max_uses,
                                    "consumed_uses": item.effective_grant.consumed_uses,
                                    "remaining_uses": item.effective_grant.remaining_uses,
                                    "max_payload_bytes": item.effective_grant.max_payload_bytes,
                                    "workspace_scope": item.effective_grant.workspace_scope,
                                    "artifact_scope": item.effective_grant.artifact_scope,
                                    "network_access": item.effective_grant.network_access,
                                    "valid_from": Instant(
                                        item.effective_grant.valid_from
                                    ).to_wire(),
                                    "valid_until": Instant(
                                        item.effective_grant.valid_until
                                    ).to_wire(),
                                    **(
                                        {
                                            "ended_at": Instant(
                                                item.effective_grant.ended_at
                                            ).to_wire()
                                        }
                                        if item.effective_grant.ended_at is not None
                                        else {}
                                    ),
                                }
                            }
                            if item.effective_grant is not None
                            else {}
                        ),
                    }
                )
                for item in page.items
            ],
            next_cursor=page.next_cursor,
        )
        return JSONResponse(content=response.model_dump(mode="json", exclude_none=True))

    @app.post(
        "/v1/capability-requests/{capability_request_id}/decision",
        operation_id="decideCapabilityRequest",
        response_model=AppliedOutcomeResponse,
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
    async def decide_capability_request(
        capability_request_id: str,
        request: Request,
    ) -> JSONResponse:
        if (
            browser_sessions is None
            or capability_policy is None
            or not _browser_boundary(request, canonical_origin=canonical_origin)
        ):
            status = 403 if browser_sessions is not None else 503
            return JSONResponse(
                status_code=status,
                content=(
                    _rejected("AUTH_BROWSER_BOUNDARY")
                    if status == 403
                    else _unavailable("DEPENDENCY_CAPABILITY_POLICY_UNAVAILABLE")
                ),
            )
        token = _bearer(request)
        try:
            if token is None:
                raise BrowserSessionViolation("AUTH_SESSION_REQUIRED")
            browser_sessions.verify(token)
            body = await _capability_decision_request(
                request,
                request_body_max_bytes,
            )
            command = CreatorGrantCommand(
                CapabilityDecisionId(UUID(body.decision_id)),
                CapabilityRequestId(UUID(capability_request_id)),
                body.expected_request_version,
                CreatorGrantDecision(body.decision),
                body.valid_for_seconds,
                body.max_uses,
                body.max_payload_bytes,
                body.reason_code,
            )
            result = await capability_policy.decide(command)
        except BrowserSessionViolation as error:
            return JSONResponse(
                status_code=error.status_code,
                content=_rejected(error.code),
            )
        except (CapabilityViolation, ValueError) as error:
            code = (
                error.code
                if isinstance(error, CapabilityViolation)
                else "CON-CAPABILITY-REQUEST-ID"
            )
            if code == "SCOPE-CAPABILITY-REQUEST":
                return JSONResponse(
                    status_code=404,
                    content=_rejected("SCOPE_CAPABILITY_REQUEST_NOT_VISIBLE"),
                )
            if code.startswith(("CONFLICT-", "POLICY-", "CAPABILITY-")):
                return JSONResponse(
                    status_code=409,
                    content=_rejected("CONFLICT_CAPABILITY_DECISION"),
                )
            if code.startswith("CON-CAPABILITY"):
                return JSONResponse(
                    status_code=400,
                    content=_rejected("INPUT_CAPABILITY_DECISION_INVALID"),
                )
            return JSONResponse(
                status_code=503,
                content=_unavailable("DEPENDENCY_CAPABILITY_POLICY_UNAVAILABLE"),
            )
        applied = AppliedOutcome(
            **_outcome_common(),
            message="The Creator capability decision was applied.",
            result_ref=ResultRef(result.request_id.value),
            state_version=result.request_version,
        )
        if creator_events is not None:
            try:
                await creator_events.notify(
                    CreatorProjectionInvalidation(
                        CreatorResourceKind("capability_request"),
                        str(result.request_id.value),
                        Instant(datetime.now(UTC)),
                        "capability-request.v4",
                    )
                )
            except Exception:
                emit("creator.capability.notification_failed")
        return JSONResponse(content=applied.to_wire())

    del list_capability_requests, decide_capability_request


__all__ = ("register_governance_routes",)
