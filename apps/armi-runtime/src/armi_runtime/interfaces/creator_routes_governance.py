"""Creator capability, export, and data-rights routes."""

from __future__ import annotations

from fastapi.responses import Response

from armi_runtime.application.creator_calls import CreatorUseCase
from armi_runtime.application.creator_governance import create_governance_use_cases

from .creator_http import (
    BrowserSessionStore,
    CreatorEventBroker,
    CreatorExportPort,
    CreatorExportResponse,
    DataRightsOrderCollectionResponse,
    DataRightsOrderDetailResponse,
    DataRightsOrderPort,
    DataRightsOrderResponse,
    FastAPI,
    HTTPBearer,
    RejectedOutcomeResponse,
    Request,
    Security,
    SecurityEvent,
    UnavailableOutcomeResponse,
)
from .creator_use_cases import invoke_creator_http


def register_governance_routes(
    *,
    app: FastAPI,
    bearer: HTTPBearer,
    canonical_origin: str,
    emit: SecurityEvent,
    browser_sessions: BrowserSessionStore | None,
    creator_events: CreatorEventBroker | None,
    creator_export: CreatorExportPort | None,
    data_rights: DataRightsOrderPort | None,
    request_body_max_bytes: int,
) -> dict[str, CreatorUseCase]:
    use_cases = create_governance_use_cases(
        emit=emit,
        creator_events=creator_events,
        creator_export=creator_export,
        data_rights=data_rights,
    )

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
    async def create_creator_export(request: Request) -> Response:
        return await invoke_creator_http(
            request,
            "export_create",
            use_cases["export_create"],
            browser_sessions=browser_sessions,
            canonical_origin=canonical_origin,
            maximum_bytes=request_body_max_bytes,
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
    async def get_creator_export(request: Request, export_id: str) -> Response:
        return await invoke_creator_http(
            request,
            "export_get",
            use_cases["export_get"],
            browser_sessions=browser_sessions,
            canonical_origin=canonical_origin,
            maximum_bytes=request_body_max_bytes,
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
    async def list_creator_data_rights_orders(request: Request) -> Response:
        return await invoke_creator_http(
            request,
            "data_rights_list",
            use_cases["data_rights_list"],
            browser_sessions=browser_sessions,
            canonical_origin=canonical_origin,
            maximum_bytes=request_body_max_bytes,
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
    async def create_creator_data_rights_order(request: Request) -> Response:
        return await invoke_creator_http(
            request,
            "data_rights_request",
            use_cases["data_rights_request"],
            browser_sessions=browser_sessions,
            canonical_origin=canonical_origin,
            maximum_bytes=request_body_max_bytes,
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
    ) -> Response:
        return await invoke_creator_http(
            request,
            "data_rights_get",
            use_cases["data_rights_get"],
            browser_sessions=browser_sessions,
            canonical_origin=canonical_origin,
            maximum_bytes=request_body_max_bytes,
        )

    @app.post(
        "/v1/data-rights/orders/{order_id}/retry",
        operation_id="retryDataRightsOrder",
        response_model=DataRightsOrderResponse,
        dependencies=[Security(bearer)],
    )
    async def retry_creator_data_rights_order(
        request: Request, order_id: str
    ) -> Response:
        return await invoke_creator_http(
            request,
            "data_rights_retry",
            use_cases["data_rights_retry"],
            browser_sessions=browser_sessions,
            canonical_origin=canonical_origin,
            maximum_bytes=request_body_max_bytes,
        )

    del list_creator_data_rights_orders, create_creator_data_rights_order
    del get_creator_data_rights_order
    del retry_creator_data_rights_order

    return use_cases


__all__ = ("register_governance_routes",)
