"""Runtime-local other-human intake and data-rights routes."""

from __future__ import annotations

from .creator_http import (
    UUID,
    ContractViolation,
    DataRightsOrderCollectionResponse,
    DataRightsOrderCommand,
    DataRightsOrderKind,
    DataRightsOrderPort,
    DataRightsViolation,
    FastAPI,
    IdempotencyKey,
    JSONResponse,
    OtherHumanInputCommand,
    OtherHumanInputPort,
    OtherHumanInputViolation,
    OtherHumanPartyKey,
    OtherHumanSceneCommand,
    RegisterOtherHumanPartyCommand,
    Request,
    SceneKey,
    SceneStatus,
    TraceId,
    _data_rights_detail_response,
    _data_rights_error,
    _data_rights_response,
    _local_json_object,
    _rejected,
    _single_header,
    _unavailable,
    secrets,
)


def register_local_other_human_routes(
    *,
    app: FastAPI,
    data_rights: DataRightsOrderPort | None,
    other_human_input: OtherHumanInputPort | None,
    request_body_max_bytes: int,
) -> None:
    def other_human_failure(error: OtherHumanInputViolation) -> JSONResponse:
        if error.code == "SCOPE-DATA-RIGHTS-BLOCKED":
            return JSONResponse(
                status_code=403,
                content=_rejected("SCOPE_DATA_RIGHTS_BLOCKED"),
            )
        if error.code.startswith("SCOPE-"):
            return JSONResponse(
                status_code=404, content=_rejected("SCOPE_OTHER_HUMAN_NOT_VISIBLE")
            )
        if error.code.startswith("IDEMPOTENCY-"):
            return JSONResponse(
                status_code=409, content=_rejected("CONFLICT_OTHER_HUMAN_IDEMPOTENCY")
            )
        if error.code.startswith(("CON-", "OTHER-HUMAN-INPUT-")):
            return JSONResponse(
                status_code=400, content=_rejected("INPUT_OTHER_HUMAN_REQUEST")
            )
        return JSONResponse(
            status_code=503,
            content=_unavailable("DEPENDENCY_OTHER_HUMAN_INPUT_UNAVAILABLE"),
        )

    @app.post("/v1/local/other-humans/parties", include_in_schema=False)
    async def register_other_human_party(request: Request) -> JSONResponse:
        if other_human_input is None:
            return JSONResponse(
                status_code=503,
                content=_unavailable("DEPENDENCY_OTHER_HUMAN_INPUT_UNAVAILABLE"),
            )
        try:
            value = await _local_json_object(request, request_body_max_bytes)
            if set(value) != {"party_key", "display_label", "role"}:
                raise OtherHumanInputViolation("OTHER-HUMAN-INPUT-BODY")
            view = await other_human_input.register_party(
                RegisterOtherHumanPartyCommand(
                    OtherHumanPartyKey(value["party_key"]),
                    value["display_label"],
                    value["role"],
                    TraceId(secrets.token_hex(16)),
                )
            )
        except (ContractViolation, OtherHumanInputViolation) as error:
            if isinstance(error, OtherHumanInputViolation):
                return other_human_failure(error)
            return JSONResponse(
                status_code=400, content=_rejected("INPUT_OTHER_HUMAN_PARTY")
            )
        return JSONResponse(
            status_code=201,
            content={
                "contract_version": "1.0",
                "party_id": str(view.party_id),
                "party_key": view.party_key.value,
                "display_label": view.display_label,
                "role": "other_human",
                "identity_assurance": view.identity_assurance,
            },
        )

    @app.put(
        "/v1/local/other-humans/{party_key}/scenes/{scene_key}",
        include_in_schema=False,
    )
    async def set_other_human_scene(
        party_key: str, scene_key: str, request: Request
    ) -> JSONResponse:
        if other_human_input is None:
            return JSONResponse(
                status_code=503,
                content=_unavailable("DEPENDENCY_OTHER_HUMAN_INPUT_UNAVAILABLE"),
            )
        try:
            value = await _local_json_object(request, request_body_max_bytes)
            if set(value) != {"status"}:
                raise OtherHumanInputViolation("OTHER-HUMAN-INPUT-BODY")
            view = await other_human_input.set_scene(
                OtherHumanSceneCommand(
                    OtherHumanPartyKey(party_key),
                    SceneKey(scene_key),
                    SceneStatus(value["status"]),
                    TraceId(secrets.token_hex(16)),
                )
            )
        except (ValueError, ContractViolation, OtherHumanInputViolation) as error:
            if isinstance(error, OtherHumanInputViolation):
                return other_human_failure(error)
            return JSONResponse(
                status_code=400, content=_rejected("INPUT_OTHER_HUMAN_SCENE")
            )
        return JSONResponse(
            content={
                "contract_version": "1.0",
                "scene_id": str(view.scene_id),
                "party_id": str(view.party_id),
                "scene_key": view.scene_key.value,
                "status": view.status.value,
            }
        )

    @app.post(
        "/v1/local/other-humans/{party_key}/scenes/{scene_key}/messages",
        include_in_schema=False,
    )
    async def accept_other_human_message(
        party_key: str, scene_key: str, request: Request
    ) -> JSONResponse:
        if other_human_input is None:
            return JSONResponse(
                status_code=503,
                content=_unavailable("DEPENDENCY_OTHER_HUMAN_INPUT_UNAVAILABLE"),
            )
        idempotency_value = _single_header(request, b"idempotency-key")
        if idempotency_value is None:
            return JSONResponse(
                status_code=400, content=_rejected("INPUT_IDEMPOTENCY_KEY")
            )
        try:
            value = await _local_json_object(request, request_body_max_bytes)
            if set(value) != {"message"}:
                raise OtherHumanInputViolation("OTHER-HUMAN-INPUT-BODY")
            accepted = await other_human_input.accept(
                OtherHumanInputCommand(
                    OtherHumanPartyKey(party_key),
                    SceneKey(scene_key),
                    value["message"],
                    IdempotencyKey(idempotency_value),
                    TraceId(secrets.token_hex(16)),
                )
            )
        except (ContractViolation, OtherHumanInputViolation) as error:
            if isinstance(error, OtherHumanInputViolation):
                return other_human_failure(error)
            return JSONResponse(
                status_code=400, content=_rejected("INPUT_OTHER_HUMAN_MESSAGE")
            )
        return JSONResponse(
            status_code=202,
            content={
                "contract_version": "1.0",
                "party_id": str(accepted.party_id),
                "scene_id": str(accepted.scene_id),
                "interaction_id": str(accepted.interaction_id.value),
                "evidence_id": str(accepted.evidence_id),
                "opportunity_id": str(accepted.opportunity_id),
                "newly_accepted": accepted.newly_accepted,
            },
        )

    @app.post(
        "/v1/local/other-humans/{party_key}/data-rights/orders",
        include_in_schema=False,
    )
    async def create_other_human_data_rights_order(
        party_key: str, request: Request
    ) -> JSONResponse:
        if data_rights is None:
            return JSONResponse(
                status_code=503,
                content=_unavailable("DEPENDENCY_DATA_RIGHTS_UNAVAILABLE"),
            )
        idempotency_value = _single_header(request, b"idempotency-key")
        if idempotency_value is None:
            return JSONResponse(
                status_code=400, content=_rejected("INPUT_IDEMPOTENCY_KEY")
            )
        try:
            value = await _local_json_object(request, request_body_max_bytes)
            if set(value) != {"order_kind"}:
                raise DataRightsViolation("DATA-RIGHTS-COMMAND")
            result = await data_rights.request_other_human(
                OtherHumanPartyKey(party_key),
                DataRightsOrderCommand(
                    DataRightsOrderKind(value["order_kind"]),
                    IdempotencyKey(idempotency_value),
                    TraceId(secrets.token_hex(16)),
                ),
            )
        except (ValueError, ContractViolation, DataRightsViolation) as error:
            if isinstance(error, DataRightsViolation):
                return _data_rights_error(error)
            return JSONResponse(
                status_code=400,
                content=_rejected("INPUT_DATA_RIGHTS_INVALID"),
            )
        return JSONResponse(
            status_code=201 if result.newly_created else 200,
            content=_data_rights_response(result).model_dump(mode="json"),
        )

    @app.get(
        "/v1/local/other-humans/{party_key}/data-rights/orders",
        include_in_schema=False,
    )
    async def list_other_human_data_rights_orders(party_key: str) -> JSONResponse:
        if data_rights is None:
            return JSONResponse(
                status_code=503,
                content=_unavailable("DEPENDENCY_DATA_RIGHTS_UNAVAILABLE"),
            )
        try:
            details = await data_rights.list_other_human(OtherHumanPartyKey(party_key))
        except (ValueError, DataRightsViolation) as error:
            if isinstance(error, DataRightsViolation):
                return _data_rights_error(error)
            return JSONResponse(
                status_code=400, content=_rejected("INPUT_DATA_RIGHTS_INVALID")
            )
        return JSONResponse(
            content=DataRightsOrderCollectionResponse(
                contract_version="1.0",
                projection_version="data-rights-order.v2",
                orders=[_data_rights_detail_response(detail) for detail in details],
            ).model_dump(mode="json")
        )

    @app.get(
        "/v1/local/other-humans/{party_key}/data-rights/orders/{order_id}",
        include_in_schema=False,
    )
    async def get_other_human_data_rights_order(
        party_key: str, order_id: str
    ) -> JSONResponse:
        if data_rights is None:
            return JSONResponse(
                status_code=503,
                content=_unavailable("DEPENDENCY_DATA_RIGHTS_UNAVAILABLE"),
            )
        try:
            result = await data_rights.detail_other_human(
                OtherHumanPartyKey(party_key), UUID(order_id)
            )
        except (ValueError, ContractViolation, DataRightsViolation) as error:
            if isinstance(error, DataRightsViolation):
                return _data_rights_error(error)
            return JSONResponse(
                status_code=400,
                content=_rejected("INPUT_DATA_RIGHTS_INVALID"),
            )
        if result is None:
            return JSONResponse(
                status_code=404,
                content=_rejected("SCOPE_DATA_RIGHTS_ORDER_NOT_FOUND"),
            )
        return JSONResponse(
            content=_data_rights_detail_response(result).model_dump(mode="json")
        )

    del register_other_human_party, set_other_human_scene, accept_other_human_message
    del create_other_human_data_rights_order, list_other_human_data_rights_orders
    del get_other_human_data_rights_order


__all__ = ("register_local_other_human_routes",)
