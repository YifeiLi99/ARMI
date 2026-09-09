from __future__ import annotations

from .creator_calls import CreatorCall, CreatorEventSink, CreatorUseCase, creator_result
from .creator_inputs import (
    _creator_export_request,
    _data_rights_request,
)
from .creator_projection import (
    UUID,
    ContractViolation,
    CreatorExportCommand,
    CreatorExportPort,
    CreatorExportViolation,
    DataRightsOrderCollectionResponse,
    DataRightsOrderCommand,
    DataRightsOrderKind,
    DataRightsOrderPort,
    DataRightsRetryCommand,
    DataRightsViolation,
    IdempotencyKey,
    SecurityEvent,
    TraceId,
    _creator_export_error,
    _creator_export_response,
    _data_rights_detail_response,
    _data_rights_error,
    _data_rights_response,
    _rejected,
    _unavailable,
    secrets,
)
from .interaction import InteractionResult


def create_governance_use_cases(
    *,
    emit: SecurityEvent,
    creator_events: CreatorEventSink | None,
    creator_export: CreatorExportPort | None,
    data_rights: DataRightsOrderPort | None,
) -> dict[str, CreatorUseCase]:

    async def create_creator_export(call: CreatorCall) -> InteractionResult:
        if creator_export is None:
            return creator_result(
                status_code=503,
                content=_unavailable("DEPENDENCY_CREATOR_EXPORT_UNAVAILABLE"),
            )
        try:
            idempotency_value = call.idempotency_key
            if idempotency_value is None:
                raise CreatorExportViolation("CREATOR-EXPORT-COMMAND")
            try:
                idempotency_key = IdempotencyKey.from_wire(idempotency_value)
            except ContractViolation:
                raise CreatorExportViolation("CREATOR-EXPORT-COMMAND") from None
            body = await _creator_export_request(call)
            result = await creator_export.export(
                CreatorExportCommand(
                    directory_name=body.directory_name,
                    idempotency_key=idempotency_key,
                    trace_id=TraceId(secrets.token_hex(16)),
                    delegate_id=call.actor.delegate_id,
                )
            )
        except CreatorExportViolation as error:
            return _creator_export_error(error)
        return creator_result(
            status_code=201 if result.newly_created else 200,
            content=_creator_export_response(result).model_dump(mode="json"),
        )

    async def get_creator_export(
        call: CreatorCall, export_id: str
    ) -> InteractionResult:
        if creator_export is None:
            return creator_result(
                status_code=503,
                content=_unavailable("DEPENDENCY_CREATOR_EXPORT_UNAVAILABLE"),
            )
        try:
            try:
                export_uuid = UUID(export_id)
            except ValueError:
                raise CreatorExportViolation("CREATOR-EXPORT-ID") from None
            result = await creator_export.get(export_uuid)
        except CreatorExportViolation as error:
            return _creator_export_error(error)
        if result is None:
            return creator_result(
                status_code=404, content=_rejected("SCOPE_CREATOR_EXPORT_NOT_FOUND")
            )
        return creator_result(
            content=_creator_export_response(result).model_dump(mode="json")
        )

    async def list_creator_data_rights_orders(call: CreatorCall) -> InteractionResult:
        if data_rights is None:
            return creator_result(
                status_code=503,
                content=_unavailable("DEPENDENCY_DATA_RIGHTS_UNAVAILABLE"),
            )
        try:
            details = await data_rights.list_creator()
        except DataRightsViolation as error:
            return _data_rights_error(error)
        return creator_result(
            content=DataRightsOrderCollectionResponse(
                contract_version="1.0",
                projection_version="data-rights-order-collection.v3",
                orders=[_data_rights_detail_response(detail) for detail in details],
            ).model_dump(mode="json")
        )

    async def create_creator_data_rights_order(call: CreatorCall) -> InteractionResult:
        if data_rights is None:
            return creator_result(
                status_code=503,
                content=_unavailable("DEPENDENCY_DATA_RIGHTS_UNAVAILABLE"),
            )
        try:
            idempotency_value = call.idempotency_key
            if idempotency_value is None:
                raise DataRightsViolation("DATA-RIGHTS-COMMAND")
            try:
                idempotency_key = IdempotencyKey.from_wire(idempotency_value)
            except ContractViolation:
                raise DataRightsViolation("DATA-RIGHTS-COMMAND") from None
            body = await _data_rights_request(call)
            if (
                body.order_kind == "delete_related"
                and call.actor.delegate_id is not None
            ):
                return creator_result(
                    status_code=403,
                    content=_rejected("AUTH_DELETION_APPROVAL_REQUIRED"),
                )
            result = await data_rights.request_creator(
                DataRightsOrderCommand(
                    DataRightsOrderKind(body.order_kind),
                    idempotency_key,
                    TraceId(secrets.token_hex(16)),
                    delegate_id=call.actor.delegate_id,
                )
            )
        except DataRightsViolation as error:
            return _data_rights_error(error)
        return creator_result(
            status_code=201 if result.newly_created else 200,
            content=_data_rights_response(result).model_dump(mode="json"),
        )

    async def get_creator_data_rights_order(
        call: CreatorCall, order_id: str
    ) -> InteractionResult:
        if data_rights is None:
            return creator_result(
                status_code=503,
                content=_unavailable("DEPENDENCY_DATA_RIGHTS_UNAVAILABLE"),
            )
        try:
            try:
                order_uuid = UUID(order_id)
            except ValueError:
                raise DataRightsViolation("DATA-RIGHTS-ORDER-ID") from None
            result = await data_rights.detail_creator(order_uuid)
        except DataRightsViolation as error:
            return _data_rights_error(error)
        if result is None:
            return creator_result(
                status_code=404, content=_rejected("SCOPE_DATA_RIGHTS_ORDER_NOT_FOUND")
            )
        return creator_result(
            content=_data_rights_detail_response(result).model_dump(mode="json")
        )

    async def retry_creator_data_rights_order(
        call: CreatorCall, order_id: str
    ) -> InteractionResult:
        if data_rights is None:
            return creator_result(
                status_code=503,
                content=_unavailable("DEPENDENCY_DATA_RIGHTS_UNAVAILABLE"),
            )
        try:
            key = call.idempotency_key
            if key is None:
                raise DataRightsViolation("DATA-RIGHTS-RETRY-COMMAND")
            result = await data_rights.retry_creator(
                UUID(order_id),
                DataRightsRetryCommand(
                    IdempotencyKey.from_wire(key), TraceId(secrets.token_hex(16))
                ),
            )
        except ValueError, ContractViolation:
            return creator_result(
                status_code=400, content=_rejected("INPUT_DATA_RIGHTS_INVALID")
            )
        except DataRightsViolation as error:
            return _data_rights_error(error)
        return creator_result(
            content=_data_rights_response(result).model_dump(mode="json")
        )

    return {
        "export_create": create_creator_export,
        "export_get": get_creator_export,
        "data_rights_list": list_creator_data_rights_orders,
        "data_rights_request": create_creator_data_rights_order,
        "data_rights_get": get_creator_data_rights_order,
        "data_rights_retry": retry_creator_data_rights_order,
    }


__all__ = ("create_governance_use_cases",)
