"""Strict Creator wire models and deterministic schema-only OpenAPI export."""

from __future__ import annotations

import re
from enum import StrEnum
from typing import Annotated, Literal
from uuid import UUID

from armi_kernel.contracts import (
    CONTRACT_VERSION,
    ErrorDescriptor,
    ErrorInstanceId,
    Instant,
    RejectedOutcome,
    TraceId,
    UnavailableOutcome,
)
from fastapi import FastAPI, Security
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
    details: dict[str, JsonValue] | None = None

    @field_validator("trace_id")
    @classmethod
    def validate_trace_id(cls, value: str) -> str:
        TraceId(value)
        return value

    @field_validator("occurred_at")
    @classmethod
    def validate_occurred_at(cls, value: str) -> str:
        normalized = Instant.from_wire(value).to_wire()
        if value != normalized:
            raise ValueError("CON-OPENAPI-TIME: occurred_at must be canonical")
        return value


class RejectedOutcomeResponse(_CommonOutcomeResponse):
    status: Literal["rejected"]
    error: ErrorDescriptorResponse

    @model_validator(mode="after")
    def validate_kernel_contract(self) -> RejectedOutcomeResponse:
        RejectedOutcome.from_wire(self.model_dump(exclude_none=True))
        return self


class UnavailableOutcomeResponse(_CommonOutcomeResponse):
    status: Literal["unavailable"]
    error: ErrorDescriptorResponse
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

    schema_handlers = (health_live, health_ready, runtime_status)
    del schema_handlers
    schema = app.openapi()
    schema.pop("servers", None)
    return schema


__all__ = (
    "ErrorDescriptorResponse",
    "LiveResponse",
    "Readiness",
    "ReadyResponse",
    "RejectedOutcomeResponse",
    "RuntimeState",
    "RuntimeStatusResponse",
    "UnavailableOutcomeResponse",
    "build_creator_openapi",
)
