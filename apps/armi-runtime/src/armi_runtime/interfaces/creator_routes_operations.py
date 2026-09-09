"""Creator Codex delegation, operation, effect, and artifact routes."""

from __future__ import annotations

from armi_runtime.application.creator_commands import CreatorCommands

from .creator_effect_wire import effect_wire
from .creator_http import (
    AcceptedOutcomeResponse,
    BrowserSessionStore,
    BrowserSessionViolation,
    CodexDelegationViolation,
    CodexModel,
    CodexReasoningEffort,
    ContractViolation,
    CreatorCodexTaskAdmissionPort,
    CreatorInputAcceptance,
    CreatorInputViolation,
    CreatorOperationQueryPort,
    EffectArtifactKind,
    EffectLedgerPort,
    EffectResponse,
    EffectViolation,
    FastAPI,
    HTTPBearer,
    JSONResponse,
    OperationOutcomeResponse,
    RejectedOutcomeResponse,
    Request,
    Response,
    Security,
    SecurityEvent,
    UnavailableOutcomeResponse,
    _accepted_wire,
    _bearer,
    _browser_boundary,
    _creator_codex_task_request,
    _input_failure,
    _rejected,
    _single_header,
    _unavailable,
    creator_visible_codex_artifact,
    operation_wire,
)
from .interaction_authority import (
    authenticated_delegate,
    delegate_id,
    verify_interaction,
)


def register_operation_routes(
    *,
    app: FastAPI,
    commands: CreatorCommands,
    bearer: HTTPBearer,
    canonical_origin: str,
    emit: SecurityEvent,
    browser_sessions: BrowserSessionStore | None,
    codex_task_admission: CreatorCodexTaskAdmissionPort[CreatorInputAcceptance] | None,
    creator_operations: CreatorOperationQueryPort | None,
    effect_ledger: EffectLedgerPort | None,
    request_body_max_bytes: int,
) -> None:
    @app.post(
        "/v1/scenes/{scene_key}/codex-tasks",
        operation_id="acceptCreatorCodexTask",
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
    async def accept_creator_codex_task(
        scene_key: str,
        request: Request,
    ) -> JSONResponse:
        if (
            browser_sessions is None and authenticated_delegate(request) is None
        ) or codex_task_admission is None:
            return JSONResponse(
                status_code=503,
                content=_unavailable("DEPENDENCY_CODEX_TASK_UNAVAILABLE"),
            )
        if not _browser_boundary(request, canonical_origin=canonical_origin):
            return JSONResponse(
                status_code=403,
                content=_rejected("AUTH_BROWSER_BOUNDARY"),
            )
        token = _bearer(request)
        try:
            if token is None and authenticated_delegate(request) is None:
                raise BrowserSessionViolation("AUTH_SESSION_REQUIRED")
            verify_interaction(request, browser_sessions, token)
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
            model = await _creator_codex_task_request(request, request_body_max_bytes)
            acceptance = await commands.submit_codex(
                scene_key=scene_key,
                objective=model.objective,
                idempotency_key=idempotency_value,
                model=CodexModel(model.model_id),
                reasoning=CodexReasoningEffort(model.reasoning_effort),
                web_search=model.web_search,
                delegate_id=delegate_id(request),
            )
        except (ContractViolation, CodexDelegationViolation) as error:
            if isinstance(error, ContractViolation):
                status, content = 400, _rejected("INPUT_IDEMPOTENCY_KEY")
                emit("creator.codex_task.rejected")
                return JSONResponse(status_code=status, content=content)
            code = getattr(error, "code", "CODEX-TASK-REQUEST")
            if code == "CODEX-TASK-IDEMPOTENCY":
                status, content = 409, _rejected("IDEMPOTENCY_MISMATCH")
            elif code == "CODEX-TASK-REQUEST-SIZE":
                status, content = 413, _rejected("INPUT_MESSAGE_TOO_LARGE")
            elif code == "CODEX-TASK-REQUEST":
                status, content = 400, _rejected("INPUT_MESSAGE_INVALID")
            elif code == "CODEX-TASK-SUBJECT":
                status, content = 404, _rejected("SCOPE_SCENE_NOT_VISIBLE")
            else:
                status, content = 503, _unavailable("DEPENDENCY_CODEX_TASK_UNAVAILABLE")
            emit("creator.codex_task.rejected")
            return JSONResponse(status_code=status, content=content)
        emit(
            "creator.codex_task.accepted"
            if acceptance.newly_accepted
            else "creator.codex_task.idempotent"
        )
        return JSONResponse(status_code=202, content=_accepted_wire(acceptance))

    del accept_creator_codex_task

    @app.get(
        "/v1/operations/{result_ref}",
        operation_id="getCreatorOperation",
        response_model=OperationOutcomeResponse,
        responses={
            400: {"model": RejectedOutcomeResponse},
            401: {"model": RejectedOutcomeResponse},
            403: {"model": RejectedOutcomeResponse},
            404: {"model": RejectedOutcomeResponse},
            503: {"model": UnavailableOutcomeResponse},
        },
        dependencies=[Security(bearer)],
    )
    async def get_creator_operation(
        result_ref: str,
        request: Request,
    ) -> JSONResponse:
        if (
            (browser_sessions is None and authenticated_delegate(request) is None)
            or creator_operations is None
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
            if token is None and authenticated_delegate(request) is None:
                raise BrowserSessionViolation("AUTH_SESSION_REQUIRED")
            verify_interaction(request, browser_sessions, token)
            operation = await commands.operation(result_ref)
        except BrowserSessionViolation as error:
            return JSONResponse(
                status_code=error.status_code,
                content=_rejected(error.code),
            )
        except (ValueError, CreatorInputViolation) as error:
            if isinstance(error, CreatorInputViolation):
                status, content = _input_failure(error)
            else:
                status, content = 404, _rejected("SCOPE_OPERATION_NOT_VISIBLE")
            return JSONResponse(status_code=status, content=content)
        return JSONResponse(content=operation_wire(operation))

    del get_creator_operation

    @app.get(
        "/v1/effects/{effect_id}",
        operation_id="getEffect",
        response_model=EffectResponse,
        responses={
            400: {"model": RejectedOutcomeResponse},
            401: {"model": RejectedOutcomeResponse},
            403: {"model": RejectedOutcomeResponse},
            404: {"model": RejectedOutcomeResponse},
            503: {"model": UnavailableOutcomeResponse},
        },
        dependencies=[Security(bearer)],
    )
    async def get_effect(effect_id: str, request: Request) -> JSONResponse:
        if (
            (browser_sessions is None and authenticated_delegate(request) is None)
            or effect_ledger is None
            or not _browser_boundary(request, canonical_origin=canonical_origin)
        ):
            status = 403 if browser_sessions is not None else 503
            return JSONResponse(
                status_code=status,
                content=(
                    _rejected("AUTH_BROWSER_BOUNDARY")
                    if status == 403
                    else _unavailable("DEPENDENCY_EFFECT_QUERY_UNAVAILABLE")
                ),
            )
        token = _bearer(request)
        try:
            if token is None and authenticated_delegate(request) is None:
                raise BrowserSessionViolation("AUTH_SESSION_REQUIRED")
            metadata = verify_interaction(request, browser_sessions, token)
            view = await commands.effect(effect_id, metadata.creator_party_id)
        except BrowserSessionViolation as error:
            return JSONResponse(
                status_code=error.status_code, content=_rejected(error.code)
            )
        except (ValueError, EffectViolation) as error:
            if (
                isinstance(error, EffectViolation)
                and error.code != "SCOPE-EFFECT-NOT-VISIBLE"
            ):
                return JSONResponse(
                    status_code=503,
                    content=_unavailable("DEPENDENCY_EFFECT_QUERY_UNAVAILABLE"),
                )
            return JSONResponse(
                status_code=404, content=_rejected("SCOPE_EFFECT_NOT_VISIBLE")
            )
        return JSONResponse(content=effect_wire(view))

    del get_effect

    @app.get(
        "/v1/effects/{effect_id}/artifacts/{artifact_kind}",
        operation_id="getEffectArtifact",
        response_class=Response,
        responses={
            200: {
                "description": "Explicit verified Codex result artifact.",
                "content": {
                    "text/plain": {"schema": {"type": "string"}},
                    "application/json": {"schema": {"type": "string"}},
                },
            },
            400: {"model": RejectedOutcomeResponse},
            401: {"model": RejectedOutcomeResponse},
            403: {"model": RejectedOutcomeResponse},
            404: {"model": RejectedOutcomeResponse},
            503: {"model": UnavailableOutcomeResponse},
        },
        dependencies=[Security(bearer)],
    )
    async def get_effect_artifact(
        effect_id: str, artifact_kind: str, request: Request
    ) -> Response:
        if (
            (browser_sessions is None and authenticated_delegate(request) is None)
            or effect_ledger is None
            or not _browser_boundary(request, canonical_origin=canonical_origin)
        ):
            status = 403 if browser_sessions is not None else 503
            return JSONResponse(
                status_code=status,
                content=(
                    _rejected("AUTH_BROWSER_BOUNDARY")
                    if status == 403
                    else _unavailable("DEPENDENCY_EFFECT_QUERY_UNAVAILABLE")
                ),
            )
        token = _bearer(request)
        try:
            if token is None and authenticated_delegate(request) is None:
                raise BrowserSessionViolation("AUTH_SESSION_REQUIRED")
            metadata = verify_interaction(request, browser_sessions, token)
            kind = EffectArtifactKind(artifact_kind)
            artifact = await commands.artifact(
                effect_id, metadata.creator_party_id, kind
            )
            content, media_type = creator_visible_codex_artifact(
                kind,
                artifact.content,
                artifact.media_type,
            )
        except BrowserSessionViolation as error:
            return JSONResponse(
                status_code=error.status_code, content=_rejected(error.code)
            )
        except UnicodeDecodeError:
            return JSONResponse(
                status_code=503,
                content=_unavailable("DEPENDENCY_EFFECT_QUERY_UNAVAILABLE"),
            )
        except (ValueError, EffectViolation) as error:
            if isinstance(error, EffectViolation) and error.code not in {
                "SCOPE-EFFECT-NOT-VISIBLE",
                "EFFECT-ARTIFACT-KIND",
            }:
                return JSONResponse(
                    status_code=503,
                    content=_unavailable("DEPENDENCY_EFFECT_QUERY_UNAVAILABLE"),
                )
            return JSONResponse(
                status_code=404, content=_rejected("SCOPE_EFFECT_NOT_VISIBLE")
            )
        return Response(content=content, media_type=media_type)

    del get_effect_artifact


__all__ = ("register_operation_routes",)
