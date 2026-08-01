"""The authenticated same-origin Creator HTTP surface."""

from __future__ import annotations

import json
import re
import secrets
from collections.abc import Awaitable, Callable
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any, Literal, Protocol, TypedDict, cast
from uuid import UUID

from armi_kernel.application import (
    CapabilityDecisionId,
    CapabilityRequestId,
    CapabilityViolation,
    CreatorGrantCommand,
    CreatorGrantDecision,
    CreatorGrantResult,
    CreatorInputAcceptance,
    CreatorInputAcceptancePort,
    CreatorInputCommand,
    CreatorInputViolation,
    CreatorOperation,
    CreatorOperationPhase,
    CreatorOperationQueryPort,
    OpportunityId,
    SceneKey,
    SceneQueryViolation,
    SceneTimelineQuery,
    SceneTimelineQueryPort,
    SubjectSummary,
)
from armi_kernel.contracts import (
    AcceptedOutcome,
    AppliedOutcome,
    CompletedOutcome,
    ContractViolation,
    ErrorCategory,
    ErrorDescriptor,
    FailedOutcome,
    IdempotencyKey,
    Instant,
    OpaqueCursor,
    RejectedOutcome,
    ResultRef,
    TraceId,
    UnavailableOutcome,
    WaitingOutcome,
)
from fastapi import FastAPI, Request
from fastapi.responses import (
    JSONResponse,
    RedirectResponse,
    Response,
    StreamingResponse,
)
from pydantic import ValidationError

from .browser_sessions import (
    BrowserSessionStore,
    BrowserSessionViolation,
    SessionMetadata,
)
from .creator_contract import (
    BootstrapCodeResponse,
    BrowserSessionCreateRequest,
    BrowserSessionCurrentResponse,
    BrowserSessionResponse,
    CapabilityRequestDecisionRequest,
    CapabilityRequestItemResponse,
    CapabilityRequestPageResponse,
    CreatorInputRequest,
    LiveResponse,
    Readiness,
    ReadyResponse,
    RuntimeStatusResponse,
    SceneTimelineItemResponse,
    SceneTimelinePageResponse,
    SubjectComponentSummaryResponse,
    SubjectSummaryResponse,
)
from .creator_events import (
    CreatorEventBroker,
    CreatorEventBrokerViolation,
    parse_last_event_id,
    stream_creator_events,
)
from .static_assets import StaticAssetStore

_BEARER = re.compile(r"^Bearer ([\x21-\x7e]{1,4096})$", re.ASCII)
_PROXY_HEADERS = frozenset(
    {
        "forwarded",
        "x-forwarded-for",
        "x-forwarded-host",
        "x-forwarded-port",
        "x-forwarded-proto",
    }
)
_SECURITY_HEADERS = {
    "Cache-Control": "no-store",
    "Content-Security-Policy": (
        "default-src 'none'; script-src 'self'; style-src 'self'; "
        "img-src 'self'; font-src 'self'; connect-src 'self'; "
        "base-uri 'none'; form-action 'self'; frame-ancestors 'none'"
    ),
    "Cross-Origin-Opener-Policy": "same-origin",
    "Permissions-Policy": (
        "camera=(), display-capture=(), geolocation=(), microphone=(), "
        "payment=(), usb=()"
    ),
    "Referrer-Policy": "no-referrer",
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
}

AsyncCallback = Callable[[], Awaitable[None]]
ReadinessProvider = Callable[[], Readiness]
RuntimeStatusProvider = Callable[[], RuntimeStatusResponse]
SubjectSummaryProvider = Callable[[], Awaitable[SubjectSummary]]
SecurityEvent = Callable[[str], None]


class CapabilityPolicyPort(Protocol):
    async def list_requests(
        self,
        *,
        creator_party_id: UUID,
        limit: int,
        cursor: str | None,
    ) -> dict[str, object]: ...

    async def decide(self, command: CreatorGrantCommand) -> CreatorGrantResult: ...


class _OutcomeArguments(TypedDict):
    trace_id: TraceId
    occurred_at: Instant


class _SessionMetadataWire(TypedDict):
    contract_version: Literal["1.0"]
    environment_id: str
    creator_party_id: str
    default_scene_key: str
    issued_at: str
    expires_at: str


def _outcome_common() -> _OutcomeArguments:
    return _OutcomeArguments(
        trace_id=TraceId(secrets.token_hex(16)),
        occurred_at=Instant(datetime.now(UTC)),
    )


def _rejected(
    code: str, message: str = "The request was rejected."
) -> dict[str, object]:
    category = (
        ErrorCategory.INPUT
        if code.startswith("INPUT_")
        else ErrorCategory.SCOPE
        if code.startswith("SCOPE_")
        else ErrorCategory.CONFLICT
        if code.startswith("CONFLICT_")
        else ErrorCategory.AUTH
    )
    return RejectedOutcome(
        **_outcome_common(),
        message=message,
        error=ErrorDescriptor(category, code),
    ).to_wire()


def _unavailable(code: str) -> dict[str, object]:
    return UnavailableOutcome(
        **_outcome_common(),
        message="The requested local Runtime capability is unavailable.",
        error=ErrorDescriptor(ErrorCategory.DEPENDENCY, code),
    ).to_wire()


def _bearer(request: Request) -> str | None:
    authorization = request.headers.get("authorization")
    if authorization is None:
        return None
    match = _BEARER.fullmatch(authorization)
    return None if match is None else match.group(1)


def _metadata_wire(metadata: SessionMetadata) -> _SessionMetadataWire:
    return {
        "contract_version": "1.0",
        "environment_id": str(metadata.environment_id),
        "creator_party_id": str(metadata.creator_party_id),
        "default_scene_key": metadata.default_scene_key,
        "issued_at": Instant(metadata.issued_at).to_wire(),
        "expires_at": Instant(metadata.expires_at).to_wire(),
    }


def _browser_boundary(request: Request, *, canonical_origin: str) -> bool:
    return (
        request.headers.get("sec-fetch-site") == "same-origin"
        and request.headers.get("sec-fetch-mode") == "cors"
        and request.headers.get("sec-fetch-dest") == "empty"
        and (
            request.method not in {"POST", "PUT", "PATCH", "DELETE"}
            or request.headers.get("origin") == canonical_origin
        )
    )


def _strict_object_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


async def _session_request(request: Request, maximum_bytes: int) -> str:
    if request.headers.get("content-type") != "application/json":
        raise BrowserSessionViolation("INPUT_CONTENT_TYPE", status_code=400)
    body = await request.body()
    if not body or len(body) > maximum_bytes:
        raise BrowserSessionViolation("INPUT_BODY", status_code=400)
    try:
        value = json.loads(
            body.decode("utf-8"),
            object_pairs_hook=_strict_object_pairs,
            parse_constant=lambda _value: (_ for _ in ()).throw(
                ValueError("non-finite JSON")
            ),
        )
        model = BrowserSessionCreateRequest.model_validate(value)
    except UnicodeDecodeError, ValueError, ValidationError:
        raise BrowserSessionViolation("INPUT_BODY", status_code=400) from None
    return model.bootstrap_code


def _single_header(request: Request, name: bytes) -> str | None:
    values = [
        value
        for header_name, value in request.scope["headers"]
        if header_name.lower() == name
    ]
    if len(values) != 1:
        return None
    try:
        return values[0].decode("ascii")
    except UnicodeDecodeError:
        return None


async def _creator_input_request(
    request: Request,
    maximum_bytes: int,
) -> CreatorInputRequest:
    if request.headers.get("content-type") != "application/json":
        raise CreatorInputViolation("INPUT-CONTENT-TYPE")
    body = await request.body()
    if not body or len(body) > maximum_bytes:
        raise CreatorInputViolation("INPUT-SIZE")
    try:
        value = json.loads(
            body.decode("utf-8", errors="strict"),
            object_pairs_hook=_strict_object_pairs,
            parse_constant=lambda _value: (_ for _ in ()).throw(
                ValueError("non-finite JSON")
            ),
        )
        return CreatorInputRequest.model_validate(value)
    except UnicodeDecodeError, ValueError, ValidationError:
        raise CreatorInputViolation("INPUT-BODY") from None


async def _capability_decision_request(
    request: Request,
    maximum_bytes: int,
) -> CapabilityRequestDecisionRequest:
    if request.headers.get("content-type") != "application/json":
        raise CapabilityViolation("CON-CAPABILITY-CONTENT-TYPE")
    body = await request.body()
    if not body or len(body) > maximum_bytes:
        raise CapabilityViolation("CON-CAPABILITY-BODY")
    try:
        value = json.loads(
            body.decode("utf-8", errors="strict"),
            object_pairs_hook=_strict_object_pairs,
            parse_constant=lambda _value: (_ for _ in ()).throw(
                ValueError("non-finite JSON")
            ),
        )
        return CapabilityRequestDecisionRequest.model_validate(value)
    except UnicodeDecodeError, ValueError, ValidationError:
        raise CapabilityViolation("CON-CAPABILITY-BODY") from None


def _accepted_wire(acceptance: CreatorInputAcceptance) -> dict[str, object]:
    return AcceptedOutcome(
        **_outcome_common(),
        message="The Creator input is durably accepted.",
        result_ref=ResultRef(acceptance.opportunity_id.value),
        custodian="runtime",
        details={
            "interaction_id": str(acceptance.interaction_id),
            "evidence_id": str(acceptance.evidence_id),
            "opportunity_id": str(acceptance.opportunity_id),
            "operation_url": f"/v1/operations/{acceptance.opportunity_id}",
        },
    ).to_wire()


def _operation_wire(operation: CreatorOperation) -> dict[str, object]:
    if operation.phase is CreatorOperationPhase.ACCEPTED:
        return _accepted_wire(operation.acceptance)
    result_ref = ResultRef(operation.acceptance.opportunity_id.value)
    if operation.phase is CreatorOperationPhase.CONTEXT_PREPARING:
        return WaitingOutcome(
            **_outcome_common(),
            message="The Context snapshot is being prepared.",
            result_ref=result_ref,
            waiting_for="context_preparation",
            resume_condition="context_prepared",
        ).to_wire()
    if operation.phase is CreatorOperationPhase.CONTEXT_PREPARED:
        return WaitingOutcome(
            **_outcome_common(),
            message="The prepared Context is waiting for a model attempt.",
            result_ref=result_ref,
            waiting_for="model_attempt",
            resume_condition="model_step_available",
        ).to_wire()
    if operation.phase is CreatorOperationPhase.MODEL_CALLING:
        return WaitingOutcome(
            **_outcome_common(),
            message="The model attempt is awaiting a provider response.",
            result_ref=result_ref,
            waiting_for="model_response",
            resume_condition="model_returned",
        ).to_wire()
    if operation.phase is CreatorOperationPhase.MODEL_RETURNED:
        return WaitingOutcome(
            **_outcome_common(),
            message="The model response is waiting for candidate validation.",
            result_ref=result_ref,
            waiting_for="candidate_validation",
            resume_condition="candidate_validation_available",
        ).to_wire()
    if operation.phase is CreatorOperationPhase.CANDIDATE_VALIDATING:
        return WaitingOutcome(
            **_outcome_common(),
            message="The cognition candidate is being validated.",
            result_ref=result_ref,
            waiting_for="candidate_validation",
            resume_condition="candidate_validated",
        ).to_wire()
    if operation.phase is CreatorOperationPhase.CANDIDATE_VALIDATED:
        return WaitingOutcome(
            **_outcome_common(),
            message="The validated candidate is waiting for subject commit.",
            result_ref=result_ref,
            waiting_for="subject_commit",
            resume_condition="subject_commit_available",
        ).to_wire()
    if operation.phase is CreatorOperationPhase.SUBJECT_COMMITTING:
        return WaitingOutcome(
            **_outcome_common(),
            message="The validated change is being committed.",
            result_ref=result_ref,
            waiting_for="subject_commit",
            resume_condition="subject_commit_available",
        ).to_wire()
    if operation.phase is CreatorOperationPhase.RESPONSE_ADMISSION:
        return WaitingOutcome(
            **_outcome_common(),
            message="The response intent is waiting for admission.",
            result_ref=result_ref,
            waiting_for="response_admission",
            resume_condition="response_admitted",
        ).to_wire()
    if operation.phase is CreatorOperationPhase.RESPONSE_ACCEPTED:
        return AcceptedOutcome(
            **_outcome_common(),
            message="The response is durably accepted but has not been sent.",
            result_ref=result_ref,
            custodian="runtime",
        ).to_wire()
    if operation.phase in {
        CreatorOperationPhase.FORMAL_DECLINED,
        CreatorOperationPhase.FORMAL_NO_ACTION,
    }:
        assert operation.completion_digest is not None
        return CompletedOutcome(
            **_outcome_common(),
            message=(
                "Cognition formally declined to respond."
                if operation.phase is CreatorOperationPhase.FORMAL_DECLINED
                else "Cognition formally chose not to act."
            ),
            result_ref=result_ref,
            completion_evidence=operation.completion_digest,
        ).to_wire()
    if operation.phase is CreatorOperationPhase.RESPONSE_UNAUTHORIZED:
        return RejectedOutcome(
            **_outcome_common(),
            message="The response is not covered by a current exact grant.",
            error=ErrorDescriptor(
                ErrorCategory.SCOPE,
                "SCOPE_RESPONSE_NOT_AUTHORIZED",
            ),
        ).to_wire()
    if operation.phase is CreatorOperationPhase.RESPONSE_UNAVAILABLE:
        return UnavailableOutcome(
            **_outcome_common(),
            message="The response capability is unavailable.",
            error=ErrorDescriptor(
                ErrorCategory.DEPENDENCY,
                "DEPENDENCY_RESPONSE_CAPABILITY_UNAVAILABLE",
            ),
        ).to_wire()
    if operation.phase is CreatorOperationPhase.RESPONSE_FAILED:
        return FailedOutcome(
            **_outcome_common(),
            message="The response admission failed.",
            error=ErrorDescriptor(
                ErrorCategory.INTEGRITY,
                "INTEGRITY_RESPONSE_ADMISSION_FAILED",
            ),
            retryable=False,
        ).to_wire()
    if operation.phase is CreatorOperationPhase.APPLIED:
        assert operation.subject_version is not None
        return AppliedOutcome(
            **_outcome_common(),
            message="The subject change is authoritatively committed.",
            result_ref=result_ref,
            state_version=operation.subject_version,
        ).to_wire()
    if operation.phase is CreatorOperationPhase.COMPLETED:
        assert operation.completion_digest is not None
        return CompletedOutcome(
            **_outcome_common(),
            message="Cognition completed without a subject change.",
            result_ref=result_ref,
            completion_evidence=operation.completion_digest,
        ).to_wire()
    if operation.phase is CreatorOperationPhase.DEFERRED:
        return WaitingOutcome(
            **_outcome_common(),
            message="Cognition deferred this opportunity.",
            result_ref=result_ref,
            waiting_for="future_opportunity",
            resume_condition="opportunity_available",
        ).to_wire()
    if operation.phase is CreatorOperationPhase.NEED_INFORMATION:
        return WaitingOutcome(
            **_outcome_common(),
            message="Cognition requires new evidence.",
            result_ref=result_ref,
            waiting_for="new_evidence",
            resume_condition="creator_evidence_accepted",
        ).to_wire()
    if operation.phase is CreatorOperationPhase.STALE_CONFLICT:
        return RejectedOutcome(
            **_outcome_common(),
            message="The subject state changed before the candidate could commit.",
            error=ErrorDescriptor(
                ErrorCategory.CONFLICT,
                "CONFLICT_SUBJECT_STATE_STALE",
            ),
        ).to_wire()
    if operation.phase is CreatorOperationPhase.CANDIDATE_REJECTED:
        return RejectedOutcome(
            **_outcome_common(),
            message="The cognition candidate was rejected.",
            error=ErrorDescriptor(
                ErrorCategory.INTEGRITY,
                "INTEGRITY_COGNITION_CANDIDATE_REJECTED",
            ),
        ).to_wire()
    return FailedOutcome(
        **_outcome_common(),
        message="Cognition preparation failed.",
        error=ErrorDescriptor(
            ErrorCategory.INTERNAL,
            "INTERNAL_COGNITION_PREPARATION_FAILED",
        ),
        retryable=False,
    ).to_wire()


def _input_failure(error: CreatorInputViolation) -> tuple[int, dict[str, object]]:
    if error.code == "IDEMPOTENCY-MISMATCH":
        return 409, _rejected("IDEMPOTENCY_MISMATCH")
    if error.code == "SCOPE-SCENE-NOT-VISIBLE":
        return 404, _rejected("SCOPE_SCENE_NOT_VISIBLE")
    if error.code == "SCOPE-OPERATION-NOT-VISIBLE":
        return 404, _rejected("SCOPE_OPERATION_NOT_VISIBLE")
    if error.code in {"CON-INPUT-SIZE", "INPUT-SIZE"}:
        return 413, _rejected("INPUT_MESSAGE_TOO_LARGE")
    if error.code.startswith(("CON-INPUT", "INPUT-")):
        return 400, _rejected("INPUT_MESSAGE_INVALID")
    return 503, _unavailable("DEPENDENCY_INPUT_ACCEPTANCE_UNAVAILABLE")


def create_runtime_app(
    *,
    readiness: ReadinessProvider,
    runtime_status: RuntimeStatusProvider,
    assets: StaticAssetStore,
    browser_sessions: BrowserSessionStore | None,
    expected_authority: str,
    request_body_max_bytes: int,
    on_started: AsyncCallback,
    on_stopping: AsyncCallback,
    scene_timeline_query: SceneTimelineQueryPort | None = None,
    creator_events: CreatorEventBroker | None = None,
    creator_input: CreatorInputAcceptancePort | None = None,
    creator_operations: CreatorOperationQueryPort | None = None,
    subject_summary: SubjectSummaryProvider | None = None,
    capability_policy: CapabilityPolicyPort | None = None,
    on_security_event: SecurityEvent | None = None,
) -> FastAPI:
    """Create the fixed Runtime app without implementation discovery."""

    canonical_origin = f"http://{expected_authority}"

    def ignore_security_event(_event: str) -> None:
        return None

    emit: SecurityEvent = (
        on_security_event if on_security_event is not None else ignore_security_event
    )

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        await on_started()
        try:
            yield
        finally:
            await on_stopping()

    app = FastAPI(
        title="ARMI Runtime",
        version="1.0",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        lifespan=lifespan,
    )

    @app.middleware("http")
    async def enforce_local_boundary(
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        if request.headers.get("host") != expected_authority or any(
            name in request.headers for name in _PROXY_HEADERS
        ):
            emit("creator.request.boundary_rejected")
            return Response(status_code=421, headers=_SECURITY_HEADERS)
        timeline_path = re.fullmatch(
            r"/v1/scenes/[^/]{1,256}/timeline",
            request.url.path,
        )
        if (
            request.url.query
            and request.url.path.startswith("/v1/")
            and timeline_path is None
            and request.url.path != "/v1/capability-requests"
        ):
            emit("creator.request.url_token_rejected")
            return Response(status_code=400, headers=_SECURITY_HEADERS)
        if request.url.path.startswith("/v1/") and "cookie" in request.headers:
            emit("creator.request.cookie_rejected")
            return Response(status_code=403, headers=_SECURITY_HEADERS)
        content_length = request.headers.get("content-length")
        if content_length is not None:
            try:
                length = int(content_length)
            except ValueError:
                return Response(status_code=400, headers=_SECURITY_HEADERS)
            if length < 0 or length > request_body_max_bytes:
                return Response(status_code=413, headers=_SECURITY_HEADERS)
        response = await call_next(request)
        for name, value in _SECURITY_HEADERS.items():
            response.headers.setdefault(name, value)
        return response

    @app.get("/health/live", response_model=LiveResponse)
    async def health_live() -> LiveResponse:
        return LiveResponse(status="alive")

    @app.get("/health/ready", response_model=ReadyResponse)
    async def health_ready() -> JSONResponse:
        current = readiness()
        return JSONResponse(
            status_code=200 if current.value == "ready" else 503,
            content={"status": current.value},
        )

    @app.post("/v1/browser-bootstrap-codes")
    async def issue_bootstrap(request: Request) -> JSONResponse:
        if browser_sessions is None:
            return JSONResponse(
                status_code=503,
                content=_unavailable("DEPENDENCY_CREATOR_SESSION_UNAVAILABLE"),
            )
        if (
            request.headers.get("origin") is not None
            or any(name.startswith("sec-fetch-") for name in request.headers)
            or request.headers.get("content-length") not in {None, "0"}
        ):
            emit("creator.bootstrap.boundary_rejected")
            return JSONResponse(
                status_code=403,
                content=_rejected("AUTH_CREATOR_REJECTED"),
            )
        token = _bearer(request)
        if token is None:
            emit("creator.bootstrap.rejected")
            return JSONResponse(
                status_code=401,
                content=_rejected("AUTH_CREATOR_REJECTED"),
            )
        try:
            issued = browser_sessions.issue(token)
        except BrowserSessionViolation as error:
            emit("creator.bootstrap.rejected")
            return JSONResponse(
                status_code=error.status_code,
                content=_rejected(error.code),
            )
        emit("creator.bootstrap.issued")
        response = BootstrapCodeResponse(
            contract_version="1.0",
            bootstrap_code=issued.code,
            expires_at=Instant(issued.expires_at).to_wire(),
        )
        return JSONResponse(content=response.model_dump(mode="json"))

    @app.post("/v1/browser-sessions")
    async def create_browser_session(request: Request) -> JSONResponse:
        if browser_sessions is None:
            return JSONResponse(
                status_code=503,
                content=_unavailable("DEPENDENCY_CREATOR_SESSION_UNAVAILABLE"),
            )
        if not _browser_boundary(request, canonical_origin=canonical_origin):
            emit("creator.session.boundary_rejected")
            return JSONResponse(
                status_code=403,
                content=_rejected("AUTH_BROWSER_BOUNDARY"),
            )
        try:
            code = await _session_request(request, request_body_max_bytes)
            established = browser_sessions.exchange(code)
        except BrowserSessionViolation as error:
            emit("creator.session.rejected")
            return JSONResponse(
                status_code=error.status_code,
                content=_rejected(error.code),
            )
        if creator_events is not None:
            await creator_events.close_active()
        emit("creator.session.established")
        response = BrowserSessionResponse(
            **_metadata_wire(established.metadata),
            browser_session_token=established.token,
        )
        return JSONResponse(content=response.model_dump(mode="json"))

    @app.get("/v1/browser-sessions/current")
    async def current_browser_session(request: Request) -> JSONResponse:
        if browser_sessions is None or not _browser_boundary(
            request, canonical_origin=canonical_origin
        ):
            return JSONResponse(
                status_code=403 if browser_sessions is not None else 503,
                content=(
                    _rejected("AUTH_BROWSER_BOUNDARY")
                    if browser_sessions is not None
                    else _unavailable("DEPENDENCY_CREATOR_SESSION_UNAVAILABLE")
                ),
            )
        token = _bearer(request)
        try:
            if token is None:
                raise BrowserSessionViolation("AUTH_SESSION_REQUIRED")
            metadata = browser_sessions.verify(token)
        except BrowserSessionViolation as error:
            emit("creator.session.rejected")
            return JSONResponse(
                status_code=error.status_code,
                content=_rejected(error.code),
            )
        response = BrowserSessionCurrentResponse(**_metadata_wire(metadata))
        return JSONResponse(content=response.model_dump(mode="json"))

    @app.delete("/v1/browser-sessions/current", status_code=204)
    async def delete_browser_session(request: Request) -> Response:
        if browser_sessions is None or not _browser_boundary(
            request, canonical_origin=canonical_origin
        ):
            return JSONResponse(
                status_code=403 if browser_sessions is not None else 503,
                content=(
                    _rejected("AUTH_BROWSER_BOUNDARY")
                    if browser_sessions is not None
                    else _unavailable("DEPENDENCY_CREATOR_SESSION_UNAVAILABLE")
                ),
            )
        token = _bearer(request)
        try:
            if token is None:
                raise BrowserSessionViolation("AUTH_SESSION_REQUIRED")
            browser_sessions.revoke(token)
        except BrowserSessionViolation as error:
            return JSONResponse(
                status_code=error.status_code,
                content=_rejected(error.code),
            )
        if creator_events is not None:
            await creator_events.close_active()
        emit("creator.session.revoked")
        return Response(status_code=204)

    @app.get("/v1/runtime/status")
    async def get_runtime_status(request: Request) -> JSONResponse:
        if browser_sessions is None or not _browser_boundary(
            request, canonical_origin=canonical_origin
        ):
            return JSONResponse(
                status_code=403 if browser_sessions is not None else 503,
                content=(
                    _rejected("AUTH_BROWSER_BOUNDARY")
                    if browser_sessions is not None
                    else _unavailable("DEPENDENCY_CREATOR_SESSION_UNAVAILABLE")
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
        return JSONResponse(content=runtime_status().model_dump(mode="json"))

    @app.get("/v1/subject/summary")
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
                subject_version=summary.subject_version,
                components=[
                    SubjectComponentSummaryResponse(
                        kind=item.kind.value,
                        version=item.version,
                        schema_version=cast(
                            Literal[
                                "armi.self.v1",
                                "armi.mind.v1",
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

    @app.get("/v1/capability-requests")
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
            if error.code == "CON-CAPABILITY-CURSOR":
                return JSONResponse(
                    status_code=400,
                    content=_rejected("INPUT_CURSOR_INVALID"),
                )
            return JSONResponse(
                status_code=503,
                content=_unavailable("DEPENDENCY_CAPABILITY_POLICY_UNAVAILABLE"),
            )
        raw_items = cast(list[dict[str, object]], page["items"])
        response = CapabilityRequestPageResponse(
            contract_version="1.0",
            projection_version="capability-request.v1",
            items=[
                CapabilityRequestItemResponse.model_validate(
                    {
                        **item,
                        "created_at": Instant(
                            cast(datetime, item["created_at"])
                        ).to_wire(),
                    }
                )
                for item in raw_items
            ],
            next_cursor=cast(str | None, page["next_cursor"]),
        )
        return JSONResponse(content=response.model_dump(mode="json", exclude_none=True))

    @app.post("/v1/capability-requests/{capability_request_id}/decision")
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
        return JSONResponse(content=applied.to_wire())

    del list_capability_requests, decide_capability_request

    @app.get("/v1/scenes/{scene_key}/timeline")
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
            projection_version="scene-timeline.v2",
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
                )
                for item in page.items
            ],
            next_cursor=(
                page.next_cursor.to_wire() if page.next_cursor is not None else None
            ),
        )
        return JSONResponse(content=response.model_dump(mode="json", exclude_none=True))

    del get_scene_timeline

    @app.post("/v1/scenes/{scene_key}/messages")
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
            metadata = browser_sessions.verify(token)
        except BrowserSessionViolation as error:
            return JSONResponse(
                status_code=error.status_code,
                content=_rejected(error.code),
            )
        if scene_key != metadata.default_scene_key:
            return JSONResponse(
                status_code=404,
                content=_rejected("SCOPE_SCENE_NOT_VISIBLE"),
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
        return JSONResponse(status_code=202, content=_accepted_wire(acceptance))

    del accept_creator_message

    @app.get("/v1/operations/{result_ref}")
    async def get_creator_operation(
        result_ref: str,
        request: Request,
    ) -> JSONResponse:
        if (
            browser_sessions is None
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
            if token is None:
                raise BrowserSessionViolation("AUTH_SESSION_REQUIRED")
            browser_sessions.verify(token)
            operation_id = OpportunityId(UUID(result_ref))
            operation = await creator_operations.get(operation_id)
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
        return JSONResponse(content=_operation_wire(operation))

    del get_creator_operation

    @app.get("/v1/scenes/{scene_key}/events")
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
            metadata = browser_sessions.verify(token)
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
        if parsed_scene_key.value != metadata.default_scene_key:
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

    @app.get("/ui", include_in_schema=False)
    async def creator_redirect() -> RedirectResponse:
        return RedirectResponse("/ui/", status_code=308)

    @app.get("/ui/", include_in_schema=False)
    async def creator_index() -> Response:
        asset = assets.get("index.html")
        assert asset is not None
        return Response(
            content=asset.content,
            media_type=asset.media_type,
            headers={"Cache-Control": asset.cache_control},
        )

    @app.get("/ui/{asset_path:path}", include_in_schema=False)
    async def creator_asset(asset_path: str) -> Response:
        asset = assets.get(asset_path)
        if asset is None:
            return Response(status_code=404)
        return Response(
            content=asset.content,
            media_type=asset.media_type,
            headers={"Cache-Control": asset.cache_control},
        )

    route_handlers = (
        enforce_local_boundary,
        health_live,
        health_ready,
        issue_bootstrap,
        create_browser_session,
        current_browser_session,
        delete_browser_session,
        get_runtime_status,
        get_subject_summary,
        creator_redirect,
        creator_index,
        creator_asset,
    )
    del route_handlers
    return app


__all__ = ("create_runtime_app",)
