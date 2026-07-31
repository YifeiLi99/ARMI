"""Strict Creator wire models and deterministic schema-only OpenAPI export."""

from __future__ import annotations

import re
from enum import StrEnum
from typing import Annotated, Literal
from uuid import UUID

from armi_kernel.contracts import (
    CONTRACT_VERSION,
    AcceptedOutcome,
    AppliedOutcome,
    CompletedOutcome,
    ErrorDescriptor,
    ErrorInstanceId,
    FailedOutcome,
    Instant,
    RejectedOutcome,
    TraceId,
    UnavailableOutcome,
    WaitingOutcome,
)
from fastapi import FastAPI, Header, Query, Security
from fastapi.responses import StreamingResponse
from fastapi.security import HTTPBearer
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    field_validator,
    model_validator,
)

_REASON_CODE_PATTERN = re.compile(r"[A-Z][A-Z0-9_]{2,127}", flags=re.ASCII)
_UUIDV7_PATTERN = (
    r"[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-"
    r"[89ab][0-9a-f]{3}-[0-9a-f]{12}"
)
_TRACE_PATTERN = r"[0-9a-f]{32}"
_INSTANT_PATTERN = r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:[0-5]\d\.\d{6}Z"
_ERROR_CODE_PATTERN = r"[A-Z][A-Z0-9_]{2,127}"
_BOOTSTRAP_CODE_PATTERN = r"bootstrap-v1\.[A-Za-z0-9_-]{22}"
_SESSION_TOKEN_PATTERN = r"browser-v1\.[A-Za-z0-9_-]{43}"
_SCENE_KEY_PATTERN = r"[a-z0-9][a-z0-9._-]{0,63}"
_CURSOR_PATTERN = r"v1\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+"
_EVENT_ID_PATTERN = r"sse-v1\.[A-Za-z0-9_-]{22}\.[1-9][0-9]*"
_IDEMPOTENCY_KEY_PATTERN = r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}"
type ReasonCode = Annotated[str, Field(pattern=_ERROR_CODE_PATTERN)]
type ErrorCategoryValue = Literal[
    "input",
    "auth",
    "scope",
    "state",
    "conflict",
    "idempotency",
    "policy",
    "capability",
    "dependency",
    "effect",
    "integrity",
    "admin",
    "internal",
]


class _StrictWireModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class RuntimeState(StrEnum):
    UNBORN = "unborn"
    STARTING = "starting"
    RECOVERING = "recovering"
    READY = "ready"
    DEGRADED = "degraded"
    DRAINING = "draining"
    STOPPED = "stopped"
    BLOCKED = "blocked"


class Readiness(StrEnum):
    READY = "ready"
    NOT_READY = "not_ready"


class LiveResponse(_StrictWireModel):
    status: Literal["alive"]


class ReadyResponse(_StrictWireModel):
    status: Readiness


class BootstrapCodeResponse(_StrictWireModel):
    contract_version: Literal["1.0"]
    bootstrap_code: Annotated[str, Field(pattern=_BOOTSTRAP_CODE_PATTERN)]
    expires_at: Annotated[str, Field(pattern=_INSTANT_PATTERN)]

    @field_validator("expires_at")
    @classmethod
    def validate_expires_at(cls, value: str) -> str:
        if Instant.from_wire(value).to_wire() != value:
            raise ValueError("CON-CREATOR-TIME: expires_at must be canonical")
        return value


class BrowserSessionCreateRequest(_StrictWireModel):
    bootstrap_code: Annotated[str, Field(pattern=_BOOTSTRAP_CODE_PATTERN)]


class _BrowserSessionMetadataResponse(_StrictWireModel):
    contract_version: Literal["1.0"]
    environment_id: Annotated[str, Field(pattern=_UUIDV7_PATTERN)]
    creator_party_id: Annotated[str, Field(pattern=_UUIDV7_PATTERN)]
    default_scene_key: Annotated[str, Field(pattern=_SCENE_KEY_PATTERN)]
    issued_at: Annotated[str, Field(pattern=_INSTANT_PATTERN)]
    expires_at: Annotated[str, Field(pattern=_INSTANT_PATTERN)]

    @field_validator("environment_id", "creator_party_id")
    @classmethod
    def validate_uuid7(cls, value: str) -> str:
        parsed = UUID(value)
        if str(parsed) != value or parsed.version != 7:
            raise ValueError("CON-CREATOR-ID: identity must be canonical UUIDv7")
        return value

    @field_validator("issued_at", "expires_at")
    @classmethod
    def validate_instant(cls, value: str) -> str:
        if Instant.from_wire(value).to_wire() != value:
            raise ValueError("CON-CREATOR-TIME: instant must be canonical")
        return value

    @model_validator(mode="after")
    def validate_time_order(self) -> _BrowserSessionMetadataResponse:
        issued = Instant.from_wire(self.issued_at).value
        expires = Instant.from_wire(self.expires_at).value
        if expires <= issued:
            raise ValueError("CON-CREATOR-TIME: session expiry must follow issue")
        return self


class BrowserSessionResponse(_BrowserSessionMetadataResponse):
    browser_session_token: Annotated[str, Field(pattern=_SESSION_TOKEN_PATTERN)]


class BrowserSessionCurrentResponse(_BrowserSessionMetadataResponse):
    pass


type TimelineStatus = Literal[
    "accepted",
    "applied",
    "waiting",
    "rejected",
    "unavailable",
    "failed",
    "unknown",
    "completed",
]


class SceneTimelineItemResponse(_StrictWireModel):
    timeline_item_id: Annotated[str, Field(pattern=_UUIDV7_PATTERN)]
    source_kind: Annotated[
        str,
        Field(pattern=r"[a-z][a-z0-9._-]{0,63}"),
    ]
    source_ref: Annotated[str, Field(pattern=_UUIDV7_PATTERN)]
    status: TimelineStatus
    occurred_at: Annotated[str, Field(pattern=_INSTANT_PATTERN)]
    operation_ref: Annotated[str, Field(pattern=_UUIDV7_PATTERN)] | None = None

    @field_validator("timeline_item_id", "source_ref", "operation_ref")
    @classmethod
    def validate_uuid7(cls, value: str | None) -> str | None:
        if value is None:
            return None
        parsed = UUID(value)
        if parsed.version != 7 or str(parsed) != value:
            raise ValueError("CON-SCENE-ID: identity must be canonical UUIDv7")
        return value

    @model_validator(mode="after")
    def validate_operation_ref(self) -> SceneTimelineItemResponse:
        if (self.source_kind in {"creator_input", "subject_commit"}) != (
            self.operation_ref is not None
        ):
            raise ValueError(
                "CON-SCENE-OPERATION: operation-backed item must expose its operation"
            )
        return self

    @field_validator("occurred_at")
    @classmethod
    def validate_occurred_at(cls, value: str) -> str:
        if Instant.from_wire(value).to_wire() != value:
            raise ValueError("CON-SCENE-TIME: instant must be canonical")
        return value


class SceneTimelinePageResponse(_StrictWireModel):
    contract_version: Literal["1.0"]
    projection_version: Literal["scene-timeline.v2"]
    scene_key: Annotated[str, Field(pattern=_SCENE_KEY_PATTERN)]
    items: Annotated[list[SceneTimelineItemResponse], Field(max_length=100)]
    next_cursor: (
        Annotated[str, Field(pattern=_CURSOR_PATTERN, max_length=2048)] | None
    ) = None


class CreatorProjectionEventResponse(_StrictWireModel):
    contract_version: Literal["1.0"]
    event_id: Annotated[str, Field(pattern=_EVENT_ID_PATTERN, max_length=128)]
    event_kind: Literal["scene.timeline.invalidated"]
    resource_kind: Literal["scene_timeline"]
    resource_ref: Annotated[str, Field(pattern=_SCENE_KEY_PATTERN)]
    projection_version: Literal["scene-timeline.v2"]
    occurred_at: Annotated[str, Field(pattern=_INSTANT_PATTERN)]

    @field_validator("occurred_at")
    @classmethod
    def validate_occurred_at(cls, value: str) -> str:
        if Instant.from_wire(value).to_wire() != value:
            raise ValueError("CON-SSE-TIME: instant must be canonical")
        return value


class CreatorInputRequest(_StrictWireModel):
    contract_version: Literal["1.0"]
    message: Annotated[str, Field(min_length=1, max_length=262144)]


class RuntimeStatusResponse(_StrictWireModel):
    contract_version: Literal["1.0"]
    environment_id: Annotated[str, Field(pattern=_UUIDV7_PATTERN)]
    runtime_state: RuntimeState
    readiness: Readiness
    reason_codes: Annotated[list[ReasonCode], Field(max_length=32)]
    observed_at: Annotated[str, Field(pattern=_INSTANT_PATTERN)]

    @field_validator("environment_id")
    @classmethod
    def validate_environment_id(cls, value: str) -> str:
        parsed = UUID(value)
        if str(parsed) != value or parsed.version != 7:
            raise ValueError("CON-OPENAPI-ID: environment_id must be canonical UUIDv7")
        return value

    @field_validator("reason_codes")
    @classmethod
    def validate_reason_codes(cls, value: list[str]) -> list[str]:
        if len(value) != len(set(value)):
            raise ValueError("CON-OPENAPI-REASON: reason codes must be unique")
        if any(_REASON_CODE_PATTERN.fullmatch(code) is None for code in value):
            raise ValueError("CON-OPENAPI-REASON: invalid reason code")
        return value

    @field_validator("observed_at")
    @classmethod
    def validate_observed_at(cls, value: str) -> str:
        normalized = Instant.from_wire(value).to_wire()
        if value != normalized:
            raise ValueError("CON-OPENAPI-TIME: observed_at must be canonical")
        return value


class ErrorDescriptorResponse(_StrictWireModel):
    category: ErrorCategoryValue
    code: Annotated[str, Field(pattern=_ERROR_CODE_PATTERN)]
    details: dict[str, JsonValue] | None = None
    error_instance_id: Annotated[str, Field(pattern=_UUIDV7_PATTERN)] | None = None

    @field_validator("error_instance_id")
    @classmethod
    def validate_error_instance_id(cls, value: str | None) -> str | None:
        if value is not None:
            ErrorInstanceId.from_wire(value)
        return value

    @model_validator(mode="after")
    def validate_descriptor(self) -> ErrorDescriptorResponse:
        ErrorDescriptor.from_wire(self.model_dump(exclude_none=True))
        return self


class _CommonOutcomeResponse(_StrictWireModel):
    contract_version: Literal["1.0"]
    trace_id: Annotated[str, Field(pattern=_TRACE_PATTERN)]
    occurred_at: Annotated[str, Field(pattern=_INSTANT_PATTERN)]
    message: Annotated[str, Field(min_length=1, max_length=4096)]

    @field_validator("trace_id")
    @classmethod
    def validate_trace_id(cls, value: str) -> str:
        TraceId(value)
        return value


class CreatorInputAcceptanceDetails(_StrictWireModel):
    interaction_id: Annotated[str, Field(pattern=_UUIDV7_PATTERN)]
    evidence_id: Annotated[str, Field(pattern=_UUIDV7_PATTERN)]
    opportunity_id: Annotated[str, Field(pattern=_UUIDV7_PATTERN)]
    operation_url: Annotated[
        str,
        Field(pattern=rf"^/v1/operations/{_UUIDV7_PATTERN}$"),
    ]

    @field_validator("interaction_id", "evidence_id", "opportunity_id")
    @classmethod
    def validate_uuid7(cls, value: str) -> str:
        parsed = UUID(value)
        if parsed.version != 7 or str(parsed) != value:
            raise ValueError("CON-INPUT-ID: identity must be canonical UUIDv7")
        return value

    @model_validator(mode="after")
    def validate_operation_url(self) -> CreatorInputAcceptanceDetails:
        if self.operation_url != f"/v1/operations/{self.opportunity_id}":
            raise ValueError(
                "CON-INPUT-OPERATION: operation URL must match opportunity"
            )
        return self


class AcceptedOutcomeResponse(_CommonOutcomeResponse):
    status: Literal["accepted"]
    result_ref: Annotated[str, Field(pattern=_UUIDV7_PATTERN)]
    custodian: Literal["runtime"]
    details: CreatorInputAcceptanceDetails

    @model_validator(mode="after")
    def validate_kernel_contract(self) -> AcceptedOutcomeResponse:
        if self.result_ref != self.details.opportunity_id:
            raise ValueError("CON-INPUT-RESULT: result must identify the opportunity")
        AcceptedOutcome.from_wire(self.model_dump(exclude_none=True))
        return self

    @field_validator("occurred_at")
    @classmethod
    def validate_occurred_at(cls, value: str) -> str:
        normalized = Instant.from_wire(value).to_wire()
        if value != normalized:
            raise ValueError("CON-OPENAPI-TIME: occurred_at must be canonical")
        return value


class WaitingOutcomeResponse(_CommonOutcomeResponse):
    status: Literal["waiting"]
    result_ref: Annotated[str, Field(pattern=_UUIDV7_PATTERN)]
    waiting_for: Literal[
        "context_preparation",
        "model_attempt",
        "model_response",
        "candidate_validation",
        "subject_commit",
        "future_opportunity",
        "new_evidence",
    ]
    resume_condition: Literal[
        "context_prepared",
        "model_step_available",
        "model_returned",
        "candidate_validation_available",
        "candidate_validated",
        "subject_commit_available",
        "opportunity_available",
        "creator_evidence_accepted",
    ]

    @model_validator(mode="after")
    def validate_kernel_contract(self) -> WaitingOutcomeResponse:
        WaitingOutcome.from_wire(self.model_dump(exclude_none=True))
        if (
            self.waiting_for,
            self.resume_condition,
        ) not in {
            ("context_preparation", "context_prepared"),
            ("model_attempt", "model_step_available"),
            ("model_response", "model_returned"),
            ("candidate_validation", "candidate_validation_available"),
            ("candidate_validation", "candidate_validated"),
            ("subject_commit", "subject_commit_available"),
            ("future_opportunity", "opportunity_available"),
            ("new_evidence", "creator_evidence_accepted"),
        }:
            raise ValueError("CON-INPUT-OPERATION: waiting state is inconsistent")
        return self


class AppliedOutcomeResponse(_CommonOutcomeResponse):
    status: Literal["applied"]
    result_ref: Annotated[str, Field(pattern=_UUIDV7_PATTERN)]
    state_version: Annotated[int, Field(ge=0)]

    @model_validator(mode="after")
    def validate_kernel_contract(self) -> AppliedOutcomeResponse:
        AppliedOutcome.from_wire(self.model_dump(exclude_none=True))
        return self


class CompletedOutcomeResponse(_CommonOutcomeResponse):
    status: Literal["completed"]
    result_ref: Annotated[str, Field(pattern=_UUIDV7_PATTERN)]
    completion_evidence: Annotated[str, Field(pattern=r"sha256:[0-9a-f]{64}")]

    @model_validator(mode="after")
    def validate_kernel_contract(self) -> CompletedOutcomeResponse:
        CompletedOutcome.from_wire(self.model_dump(exclude_none=True))
        return self


class FailedOutcomeResponse(_CommonOutcomeResponse):
    status: Literal["failed"]
    error: ErrorDescriptorResponse
    retryable: bool

    @model_validator(mode="after")
    def validate_kernel_contract(self) -> FailedOutcomeResponse:
        FailedOutcome.from_wire(self.model_dump(exclude_none=True))
        return self


class RejectedOutcomeResponse(_CommonOutcomeResponse):
    status: Literal["rejected"]
    error: ErrorDescriptorResponse
    details: dict[str, JsonValue] | None = None

    @model_validator(mode="after")
    def validate_kernel_contract(self) -> RejectedOutcomeResponse:
        RejectedOutcome.from_wire(self.model_dump(exclude_none=True))
        return self


type OperationOutcomeResponse = Annotated[
    AcceptedOutcomeResponse
    | AppliedOutcomeResponse
    | CompletedOutcomeResponse
    | WaitingOutcomeResponse
    | RejectedOutcomeResponse
    | FailedOutcomeResponse,
    Field(discriminator="status"),
]


class SubjectComponentSummaryResponse(_StrictWireModel):
    kind: Literal["self", "mind", "life_mode"]
    version: Annotated[int, Field(ge=1)]
    schema_version: Literal["armi.self.v1", "armi.mind.v1", "armi.life-mode.v1"]
    content_visibility: Literal["private"]


class SubjectSummaryResponse(_StrictWireModel):
    contract_version: Literal["1.0"]
    subject_version: Annotated[int, Field(ge=0)]
    components: Annotated[
        list[SubjectComponentSummaryResponse], Field(min_length=3, max_length=3)
    ]
    latest_commit_ref: Annotated[str, Field(pattern=_UUIDV7_PATTERN)] | None = None
    observed_at: Annotated[str, Field(pattern=_INSTANT_PATTERN)]

    @model_validator(mode="after")
    def validate_summary(self) -> SubjectSummaryResponse:
        if [item.kind for item in self.components] != ["self", "mind", "life_mode"]:
            raise ValueError("CON-SUBJECT-SUMMARY: component order is invalid")
        if Instant.from_wire(self.observed_at).to_wire() != self.observed_at:
            raise ValueError("CON-SUBJECT-SUMMARY: time is not canonical")
        return self


class CapabilityRequestItemResponse(_StrictWireModel):
    capability_request_id: Annotated[str, Field(pattern=_UUIDV7_PATTERN)]
    capability_kind: Literal["creator.scene.reply", "codex.delegated-work"]
    operation: Literal["send", "execute"]
    subject_id: Annotated[str, Field(pattern=_UUIDV7_PATTERN)]
    scene_id: Annotated[str, Field(pattern=_UUIDV7_PATTERN)]
    purpose: Literal["respond_to_creator", "delegate_codex_work"]
    audience_scope: Literal["creator"] | None = None
    data_scope: Literal["creator_visible_response"] | None = None
    workspace_scope: Literal["isolated_ephemeral"] | None = None
    artifact_scope: Literal["explicit_only"] | None = None
    network_access: Literal[False] | None = None
    valid_for_seconds: Annotated[int, Field(ge=60, le=604800)]
    max_uses: Annotated[int, Field(ge=1, le=16)]
    max_payload_bytes: Annotated[int, Field(ge=1, le=65536)] | None = None
    status: Literal["pending", "granted", "limited", "denied", "revoked", "expired"]
    request_version: Annotated[int, Field(ge=1)]
    created_at: Annotated[str, Field(pattern=_INSTANT_PATTERN)]
    grant_ref: Annotated[str, Field(pattern=_UUIDV7_PATTERN)] | None = None

    @field_validator("capability_request_id", "subject_id", "scene_id", "grant_ref")
    @classmethod
    def validate_identity(cls, value: str | None) -> str | None:
        if value is not None:
            parsed = UUID(value)
            if parsed.version != 7 or str(parsed) != value:
                raise ValueError("CON-CAPABILITY-ID: identity must be UUIDv7")
        return value

    @model_validator(mode="after")
    def validate_scope(self) -> CapabilityRequestItemResponse:
        if Instant.from_wire(self.created_at).to_wire() != self.created_at:
            raise ValueError("CON-CAPABILITY-TIME: time must be canonical")
        if self.capability_kind == "creator.scene.reply":
            if (
                self.operation != "send"
                or self.purpose != "respond_to_creator"
                or self.max_payload_bytes is None
                or self.audience_scope != "creator"
                or self.data_scope != "creator_visible_response"
                or any(
                    value is not None
                    for value in (
                        self.workspace_scope,
                        self.artifact_scope,
                        self.network_access,
                    )
                )
            ):
                raise ValueError("CON-CAPABILITY-SCOPE: reply scope is invalid")
        elif (
            self.operation != "execute"
            or self.purpose != "delegate_codex_work"
            or self.max_uses != 1
            or self.max_payload_bytes is not None
            or self.valid_for_seconds > 3600
            or self.audience_scope is not None
            or self.data_scope is not None
            or self.workspace_scope != "isolated_ephemeral"
            or self.artifact_scope != "explicit_only"
            or self.network_access is not False
        ):
            raise ValueError("CON-CAPABILITY-SCOPE: Codex scope is invalid")
        if self.status in {"granted", "limited"} and self.grant_ref is None:
            raise ValueError("CON-CAPABILITY-STATE: grant reference is missing")
        if self.status in {"pending", "denied"} and self.grant_ref is not None:
            raise ValueError("CON-CAPABILITY-STATE: grant reference is inconsistent")
        return self


class CapabilityRequestPageResponse(_StrictWireModel):
    contract_version: Literal["1.0"]
    projection_version: Literal["capability-request.v1"]
    items: Annotated[list[CapabilityRequestItemResponse], Field(max_length=100)]
    next_cursor: (
        Annotated[str, Field(pattern=_CURSOR_PATTERN, max_length=2048)] | None
    ) = None


class CapabilityRequestDecisionRequest(_StrictWireModel):
    contract_version: Literal["1.0"]
    decision_id: Annotated[str, Field(pattern=_UUIDV7_PATTERN)]
    expected_request_version: Annotated[int, Field(ge=1)]
    decision: Literal["grant", "limit", "deny", "revoke"]
    valid_for_seconds: Annotated[int, Field(ge=60, le=604800)] | None = None
    max_uses: Annotated[int, Field(ge=1, le=16)] | None = None
    max_payload_bytes: Annotated[int, Field(ge=1, le=65536)] | None = None
    reason_code: (
        Annotated[
            str,
            Field(pattern=r"(?:CON|CAPABILITY|POLICY|CONFLICT|SCOPE)-[A-Z0-9-]{1,96}"),
        ]
        | None
    ) = None

    @field_validator("decision_id")
    @classmethod
    def validate_decision_id(cls, value: str) -> str:
        parsed = UUID(value)
        if parsed.version != 7 or str(parsed) != value:
            raise ValueError("CON-CAPABILITY-ID: decision identity must be UUIDv7")
        return value

    @model_validator(mode="after")
    def validate_decision_scope(self) -> CapabilityRequestDecisionRequest:
        limits = (
            self.valid_for_seconds,
            self.max_uses,
            self.max_payload_bytes,
        )
        if self.decision == "limit" and all(value is None for value in limits):
            raise ValueError("CON-CAPABILITY-LIMIT: limit must narrow scope")
        if self.decision != "limit" and any(value is not None for value in limits):
            raise ValueError("CON-CAPABILITY-LIMIT: only limit accepts scope fields")
        return self


class UnavailableOutcomeResponse(_CommonOutcomeResponse):
    status: Literal["unavailable"]
    error: ErrorDescriptorResponse
    details: dict[str, JsonValue] | None = None
    recovery_hint: Annotated[str, Field(min_length=1, max_length=4096)] | None = None

    @model_validator(mode="after")
    def validate_kernel_contract(self) -> UnavailableOutcomeResponse:
        UnavailableOutcome.from_wire(self.model_dump(exclude_none=True))
        return self


def build_creator_openapi() -> dict[str, object]:
    """Build the schema locally without exporting or starting an ASGI app."""

    app = FastAPI(
        title="ARMI Creator Interface",
        version=CONTRACT_VERSION,
        openapi_version="3.1.0",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    bearer = HTTPBearer(scheme_name="browserSessionBearer", auto_error=False)
    creator_bearer = HTTPBearer(scheme_name="creatorBearer", auto_error=False)

    @app.get(
        "/health/live",
        operation_id="getHealthLive",
        response_model=LiveResponse,
    )
    async def health_live() -> LiveResponse:
        raise NotImplementedError

    @app.get(
        "/health/ready",
        operation_id="getHealthReady",
        response_model=ReadyResponse,
        responses={503: {"model": ReadyResponse}},
    )
    async def health_ready() -> ReadyResponse:
        raise NotImplementedError

    @app.post(
        "/v1/browser-bootstrap-codes",
        operation_id="createBrowserBootstrapCode",
        response_model=BootstrapCodeResponse,
        responses={
            401: {"model": RejectedOutcomeResponse},
            429: {"model": RejectedOutcomeResponse},
            503: {"model": UnavailableOutcomeResponse},
        },
        dependencies=[Security(creator_bearer)],
    )
    async def create_browser_bootstrap_code() -> BootstrapCodeResponse:
        raise NotImplementedError

    @app.post(
        "/v1/browser-sessions",
        operation_id="createBrowserSession",
        response_model=BrowserSessionResponse,
        responses={
            400: {"model": RejectedOutcomeResponse},
            401: {"model": RejectedOutcomeResponse},
            403: {"model": RejectedOutcomeResponse},
            429: {"model": RejectedOutcomeResponse},
        },
    )
    async def create_browser_session(
        _request: BrowserSessionCreateRequest,
    ) -> BrowserSessionResponse:
        raise NotImplementedError

    @app.get(
        "/v1/browser-sessions/current",
        operation_id="getCurrentBrowserSession",
        response_model=BrowserSessionCurrentResponse,
        responses={
            401: {"model": RejectedOutcomeResponse},
            403: {"model": RejectedOutcomeResponse},
        },
        dependencies=[Security(bearer)],
    )
    async def current_browser_session() -> BrowserSessionCurrentResponse:
        raise NotImplementedError

    @app.delete(
        "/v1/browser-sessions/current",
        operation_id="deleteCurrentBrowserSession",
        status_code=204,
        responses={
            401: {"model": RejectedOutcomeResponse},
            403: {"model": RejectedOutcomeResponse},
        },
        dependencies=[Security(bearer)],
    )
    async def delete_browser_session() -> None:
        raise NotImplementedError

    @app.get(
        "/v1/runtime/status",
        operation_id="getRuntimeStatus",
        response_model=RuntimeStatusResponse,
        responses={
            401: {"model": RejectedOutcomeResponse},
            403: {"model": RejectedOutcomeResponse},
            503: {"model": UnavailableOutcomeResponse},
        },
        dependencies=[Security(bearer)],
    )
    async def runtime_status() -> RuntimeStatusResponse:
        raise NotImplementedError

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
    async def subject_summary() -> SubjectSummaryResponse:
        raise NotImplementedError

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
    async def list_capability_requests(
        limit: Annotated[int, Query(ge=1, le=100)] = 50,
        cursor: Annotated[
            str | None,
            Query(pattern=_CURSOR_PATTERN, max_length=2048),
        ] = None,
    ) -> CapabilityRequestPageResponse:
        del limit, cursor
        raise NotImplementedError

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
        capability_request_id: Annotated[str, Field(pattern=_UUIDV7_PATTERN)],
        _request: CapabilityRequestDecisionRequest,
    ) -> AppliedOutcomeResponse:
        del capability_request_id, _request
        raise NotImplementedError

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
    async def scene_timeline(
        scene_key: Annotated[str, Field(pattern=_SCENE_KEY_PATTERN)],
        limit: Annotated[int, Query(ge=1, le=100)],
        cursor: Annotated[
            str | None,
            Query(pattern=_CURSOR_PATTERN, max_length=2048),
        ] = None,
    ) -> SceneTimelinePageResponse:
        del scene_key, limit, cursor
        raise NotImplementedError

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
        scene_key: Annotated[str, Field(pattern=_SCENE_KEY_PATTERN)],
        _request: CreatorInputRequest,
        _idempotency_key: Annotated[
            str,
            Header(
                alias="Idempotency-Key",
                pattern=_IDEMPOTENCY_KEY_PATTERN,
                max_length=128,
            ),
        ],
    ) -> AcceptedOutcomeResponse:
        del scene_key, _request, _idempotency_key
        raise NotImplementedError

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
        result_ref: Annotated[str, Field(pattern=_UUIDV7_PATTERN)],
    ) -> OperationOutcomeResponse:
        del result_ref
        raise NotImplementedError

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
    async def scene_events(
        scene_key: Annotated[str, Field(pattern=_SCENE_KEY_PATTERN)],
    ) -> StreamingResponse:
        del scene_key
        raise NotImplementedError

    schema_handlers = (
        health_live,
        health_ready,
        create_browser_bootstrap_code,
        create_browser_session,
        current_browser_session,
        delete_browser_session,
        runtime_status,
        subject_summary,
        list_capability_requests,
        decide_capability_request,
        scene_timeline,
        accept_creator_message,
        get_creator_operation,
        scene_events,
    )
    del schema_handlers
    schema = app.openapi()
    schema.pop("servers", None)
    schema["paths"]["/v1/scenes/{scene_key}/timeline"]["get"]["responses"].pop(
        "422", None
    )
    schema["paths"]["/v1/scenes/{scene_key}/events"]["get"]["responses"].pop(
        "422", None
    )
    schema["paths"]["/v1/scenes/{scene_key}/messages"]["post"]["responses"].pop(
        "422", None
    )
    schema["paths"]["/v1/operations/{result_ref}"]["get"]["responses"].pop("422", None)
    schema["paths"]["/v1/capability-requests"]["get"]["responses"].pop("422", None)
    schema["paths"]["/v1/capability-requests/{capability_request_id}/decision"]["post"][
        "responses"
    ].pop("422", None)
    schemas = schema["components"]["schemas"]
    schemas["CreatorProjectionEventResponse"] = (
        CreatorProjectionEventResponse.model_json_schema(
            ref_template="#/components/schemas/{model}",
        )
    )
    return schema


__all__ = (
    "AcceptedOutcomeResponse",
    "AppliedOutcomeResponse",
    "BootstrapCodeResponse",
    "BrowserSessionCreateRequest",
    "BrowserSessionCurrentResponse",
    "BrowserSessionResponse",
    "CapabilityRequestDecisionRequest",
    "CapabilityRequestItemResponse",
    "CapabilityRequestPageResponse",
    "CompletedOutcomeResponse",
    "CreatorInputRequest",
    "CreatorProjectionEventResponse",
    "ErrorDescriptorResponse",
    "FailedOutcomeResponse",
    "LiveResponse",
    "OperationOutcomeResponse",
    "Readiness",
    "ReadyResponse",
    "RejectedOutcomeResponse",
    "RuntimeState",
    "RuntimeStatusResponse",
    "SceneTimelineItemResponse",
    "SceneTimelinePageResponse",
    "SubjectComponentSummaryResponse",
    "SubjectSummaryResponse",
    "UnavailableOutcomeResponse",
    "WaitingOutcomeResponse",
    "build_creator_openapi",
)
