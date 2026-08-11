"""Technology-neutral model invocation and attempt contracts."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol, runtime_checkable
from uuid import UUID

from armi_kernel.contracts import Digest

_TOKEN = re.compile(r"^[a-z][a-z0-9._-]{0,127}$", re.ASCII)
_MODEL_ID = re.compile(r"^[a-z0-9][a-z0-9._-]{0,127}$", re.ASCII)
_CODE = re.compile(r"^MODEL-[A-Z0-9-]+$", re.ASCII)


class ModelResultStatus(StrEnum):
    SUCCEEDED = "succeeded"
    REJECTED = "rejected"
    TIMED_OUT = "timed_out"
    PROVIDER_FAILED = "provider_failed"
    CANCELLED = "cancelled"
    OUTCOME_UNKNOWN = "outcome_unknown"


class ModelViolation(RuntimeError):
    """Expose a stable model failure without provider or credential detail."""

    __slots__ = ("code", "outcome_unknown", "retryable")

    def __init__(
        self,
        code: str,
        *,
        retryable: bool = False,
        outcome_unknown: bool = False,
    ) -> None:
        if type(code) is not str or _CODE.fullmatch(code) is None:
            raise ValueError("model violation code is invalid")
        if type(retryable) is not bool or type(outcome_unknown) is not bool:
            raise ValueError("model violation flags are invalid")
        self.code = code
        self.retryable = retryable
        self.outcome_unknown = outcome_unknown
        super().__init__("model operation failed")

    def __str__(self) -> str:
        return f"{self.code}: model operation failed"


@dataclass(frozen=True, slots=True)
class ModelAttemptId:
    value: UUID

    def __post_init__(self) -> None:
        if type(self.value) is not UUID or self.value.version != 7:
            raise ModelViolation("MODEL-ATTEMPT-ID")

    def __str__(self) -> str:
        return str(self.value)


@dataclass(frozen=True, slots=True)
class ModelBinding:
    provider: str
    api_base: str
    model_id: str
    version_policy: str
    response_model_identity_required: bool
    profile: str
    request_contract_version: str
    response_contract_version: str
    pricing_snapshot_id: str
    credential_identity: str
    input_token_limit: int
    output_token_limit: int
    timeout_seconds: int
    input_microyuan_per_million: int
    output_microyuan_per_million: int
    attempt_cost_limit_microyuan: int

    def __post_init__(self) -> None:
        for value in (
            self.provider,
            self.version_policy,
            self.profile,
            self.request_contract_version,
            self.response_contract_version,
            self.pricing_snapshot_id,
            self.credential_identity,
        ):
            _require_token(value)
        if type(self.api_base) is not str or self.api_base != (
            "https://ark.cn-beijing.volces.com/api/v3"
        ):
            raise ModelViolation("MODEL-BINDING-API-BASE")
        if type(self.model_id) is not str or _MODEL_ID.fullmatch(self.model_id) is None:
            raise ModelViolation("MODEL-BINDING-ID")
        if type(self.response_model_identity_required) is not bool:
            raise ModelViolation("MODEL-BINDING-ID")
        for value in (
            self.input_token_limit,
            self.output_token_limit,
            self.timeout_seconds,
            self.input_microyuan_per_million,
            self.output_microyuan_per_million,
            self.attempt_cost_limit_microyuan,
        ):
            if type(value) is not int or value <= 0:
                raise ModelViolation("MODEL-BINDING-BUDGET")
        if self.output_token_limit > self.input_token_limit:
            raise ModelViolation("MODEL-BINDING-BUDGET")

    def estimate_cost_microyuan(
        self,
        *,
        input_tokens: int,
        output_tokens: int,
    ) -> int:
        for value in (input_tokens, output_tokens):
            if type(value) is not int or value < 0:
                raise ModelViolation("MODEL-USAGE")
        numerator = (
            input_tokens * self.input_microyuan_per_million
            + output_tokens * self.output_microyuan_per_million
        )
        return (numerator + 999_999) // 1_000_000


@dataclass(frozen=True, slots=True)
class ModelRequest:
    canonical_bytes: bytes
    context_digest: Digest
    input_tokens: int
    max_output_tokens: int

    def __post_init__(self) -> None:
        if (
            type(self.canonical_bytes) is not bytes
            or not self.canonical_bytes
            or type(self.context_digest) is not Digest
            or type(self.input_tokens) is not int
            or self.input_tokens <= 0
            or type(self.max_output_tokens) is not int
            or self.max_output_tokens <= 0
        ):
            raise ModelViolation("MODEL-REQUEST")


@dataclass(frozen=True, slots=True)
class ModelUsage:
    input_tokens: int
    output_tokens: int
    cached_input_tokens: int
    estimated_cost_microyuan: int

    def __post_init__(self) -> None:
        for value in (
            self.input_tokens,
            self.output_tokens,
            self.cached_input_tokens,
            self.estimated_cost_microyuan,
        ):
            if type(value) is not int or value < 0:
                raise ModelViolation("MODEL-USAGE")
        if self.cached_input_tokens > self.input_tokens:
            raise ModelViolation("MODEL-USAGE")


@dataclass(frozen=True, slots=True)
class ModelInvocationResult:
    status: ModelResultStatus
    provider_request_id: str | None
    provider_model_id: str | None
    response_bytes: bytes | None
    usage: ModelUsage | None
    error_code: str | None = None

    def __post_init__(self) -> None:
        if type(self.status) is not ModelResultStatus:
            raise ModelViolation("MODEL-RESULT")
        success = self.status is ModelResultStatus.SUCCEEDED
        if success:
            if (
                type(self.provider_request_id) is not str
                or not self.provider_request_id
                or type(self.provider_model_id) is not str
                or _MODEL_ID.fullmatch(self.provider_model_id) is None
                or type(self.response_bytes) is not bytes
                or not self.response_bytes
                or type(self.usage) is not ModelUsage
                or self.error_code is not None
            ):
                raise ModelViolation("MODEL-RESULT")
        elif self.error_code is None or _CODE.fullmatch(self.error_code) is None:
            raise ModelViolation("MODEL-RESULT")


@runtime_checkable
class ModelPort(Protocol):
    async def tokenize(self, canonical_request: bytes) -> int:
        """Count the final request with the active provider tokenizer."""
        ...

    async def invoke(self, request: ModelRequest) -> ModelInvocationResult:
        """Invoke one physical provider attempt outside a database transaction."""
        ...


def _require_token(value: object) -> None:
    if type(value) is not str or _TOKEN.fullmatch(value) is None:
        raise ModelViolation("MODEL-BINDING")


__all__ = (
    "ModelAttemptId",
    "ModelBinding",
    "ModelInvocationResult",
    "ModelPort",
    "ModelRequest",
    "ModelResultStatus",
    "ModelUsage",
    "ModelViolation",
)
