"""Strict structured contracts for the S037 Admin MCP surface."""

from __future__ import annotations

import re
from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

_TOKEN = re.compile(r"^[A-Za-z0-9._:-]{1,128}$", re.ASCII)


def _uuid7(value: str) -> str:
    try:
        parsed = UUID(value)
    except (ValueError, AttributeError) as exc:
        raise ValueError("ADMIN-INPUT-UUID7") from exc
    if parsed.version != 7 or str(parsed) != value:
        raise ValueError("ADMIN-INPUT-UUID7")
    return value


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class HealthRequest(_StrictModel):
    contract_version: Literal["2.0"] = "2.0"


class EnvironmentRequest(_StrictModel):
    contract_version: Literal["2.0"] = "2.0"
    environment_id: str

    _environment_id = field_validator("environment_id")(_uuid7)


class SchemaStatusRequest(EnvironmentRequest):
    pass


class RuntimeStatusRequest(EnvironmentRequest):
    pass


class SubjectSnapshotRequest(EnvironmentRequest):
    detail: Literal["summary", "private"] = "summary"


class TraceFlowRequest(EnvironmentRequest):
    operation_id: str | None = None
    episode_id: str | None = None
    effect_id: str | None = None
    trace_id: str | None = Field(default=None, pattern=r"^[0-9a-f]{32}$")
    limit: int = Field(default=100, ge=1, le=200)
    cursor: str | None = Field(default=None, pattern=r"^[A-Za-z0-9_-]{8,512}$")

    @model_validator(mode="after")
    def _exact_selector(self) -> Self:
        values = (self.operation_id, self.episode_id, self.effect_id, self.trace_id)
        if sum(value is not None for value in values) != 1:
            raise ValueError("ADMIN-INPUT-TRACE-SELECTOR")
        for value in values[:3]:
            if value is not None:
                _uuid7(value)
        return self


class InspectScopeRequest(EnvironmentRequest):
    kind: Literal[
        "subject", "operation", "episode", "effect", "work", "artifact", "scene"
    ]
    object_ids: tuple[str, ...] = Field(min_length=1, max_length=32)
    relations: tuple[
        Literal["direct_dependencies", "direct_dependents", "current_owner"], ...
    ] = Field(default=(), max_length=3)
    limit: int = Field(default=100, ge=1, le=200)
    cursor: str | None = Field(default=None, pattern=r"^[A-Za-z0-9_-]{8,512}$")

    @field_validator("object_ids")
    @classmethod
    def _object_ids(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if len(set(values)) != len(values):
            raise ValueError("ADMIN-INPUT-SCOPE-DUPLICATE")
        for value in values:
            _uuid7(value)
        return values


class TailDiagnosticsRequest(EnvironmentRequest):
    limit: int = Field(default=50, ge=1, le=200)
    runtime_instance_id: str
    cursor: str | None = Field(default=None, pattern=r"^[A-Za-z0-9_-]{8,512}$")

    _runtime_instance_id = field_validator("runtime_instance_id")(_uuid7)


class MutationRequest(EnvironmentRequest):
    environment_incarnation: int = Field(ge=1)
    idempotency_key: str
    purpose: str

    @field_validator("idempotency_key", "purpose")
    @classmethod
    def _token(cls, value: str) -> str:
        if _TOKEN.fullmatch(value) is None:
            raise ValueError("ADMIN-INPUT-TOKEN")
        return value


class EnvironmentInitializeRequest(MutationRequest):
    birth_mode: Literal["unborn", "manifest"] = "unborn"


class EnvironmentResetPreviewRequest(MutationRequest):
    pass


class EnvironmentResetRequest(MutationRequest):
    preview_token: str = Field(min_length=32, max_length=4096)


class RuntimeControlRequest(MutationRequest):
    expected_instance_id: str | None = None

    @field_validator("expected_instance_id")
    @classmethod
    def _instance_id(cls, value: str | None) -> str | None:
        return None if value is None else _uuid7(value)


class InjectCreatorInputRequest(MutationRequest):
    message: str = Field(min_length=1, max_length=262144)

    @field_validator("message")
    @classmethod
    def _message(cls, value: str) -> str:
        if "\x00" in value or not value.strip():
            raise ValueError("ADMIN-INPUT-MESSAGE")
        return value


class ArmFaultRequest(MutationRequest):
    fault: Literal[
        "artifact_after_publish_before_commit",
        "subject_before_cas",
        "effect_after_register_before_settlement",
        "adapter_after_dispatch_before_settlement",
    ]
    duration_seconds: int = Field(default=300, ge=1, le=300)


class ClearFaultsRequest(MutationRequest):
    pass


class ReplaceSubjectComponentSpec(_StrictModel):
    correction_kind: Literal["replace_subject_component"]
    component_kind: Literal["self", "mind", "mood", "life_mode"]
    expected_component_version: int = Field(ge=1)
    replacement: dict[str, object]


class RepairSubjectComponentHeadSpec(_StrictModel):
    correction_kind: Literal["repair_subject_component_head"]
    component_kind: Literal["self", "mind", "mood", "life_mode"]
    expected_component_version: int = Field(ge=1)
    target_revision_id: str

    _target_revision_id = field_validator("target_revision_id")(_uuid7)


class DeleteUncommittedCreatorInputSpec(_StrictModel):
    correction_kind: Literal["delete_uncommitted_creator_input"]
    interaction_id: str

    _interaction_id = field_validator("interaction_id")(_uuid7)


class RequeueStuckWorkSpec(_StrictModel):
    correction_kind: Literal["requeue_stuck_work"]
    work_id: str

    _work_id = field_validator("work_id")(_uuid7)


class ReconcileUnknownCreatorEffectSpec(_StrictModel):
    correction_kind: Literal["reconcile_unknown_creator_effect"]
    effect_id: str
    conclusion: Literal["confirmed_completed", "confirmed_failed", "still_unknown"]
    observed_at: str
    evidence_kind: Literal[
        "local_delivery",
        "codex_verification",
        "platform_receipt",
        "receiver_confirmation",
        "operator_attestation",
        "inconclusive",
    ]
    evidence_ref: str | None = Field(default=None, max_length=256)
    evidence_digest: str | None = None

    _effect_id = field_validator("effect_id")(_uuid7)

    @field_validator("observed_at")
    @classmethod
    def _observed_at(cls, value: str) -> str:
        from datetime import datetime

        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError("ADMIN-INPUT-INSTANT") from exc
        if parsed.tzinfo is None:
            raise ValueError("ADMIN-INPUT-INSTANT")
        return value

    @field_validator("evidence_digest")
    @classmethod
    def _digest(cls, value: str | None) -> str | None:
        if value is not None and re.fullmatch(r"sha256:[0-9a-f]{64}", value) is None:
            raise ValueError("ADMIN-INPUT-DIGEST")
        return value

    @model_validator(mode="after")
    def _evidence_contract(self) -> Self:
        if self.conclusion == "still_unknown":
            if self.evidence_kind != "inconclusive" or any(
                value is not None for value in (self.evidence_ref, self.evidence_digest)
            ):
                raise ValueError("ADMIN-INPUT-EFFECT-EVIDENCE")
        elif self.evidence_kind == "inconclusive" or (
            self.evidence_kind in {"local_delivery", "codex_verification"}
            and (self.evidence_ref is None or self.evidence_digest is None)
        ):
            raise ValueError("ADMIN-INPUT-EFFECT-EVIDENCE")
        return self


CorrectionSpec = Annotated[
    ReplaceSubjectComponentSpec
    | RepairSubjectComponentHeadSpec
    | DeleteUncommittedCreatorInputSpec
    | RequeueStuckWorkSpec
    | ReconcileUnknownCreatorEffectSpec,
    Field(discriminator="correction_kind"),
]


class PreviewCorrectionRequest(MutationRequest):
    spec: CorrectionSpec


class ApplyCorrectionRequest(MutationRequest):
    preview_token: str = Field(min_length=64, max_length=8192)
    spec: CorrectionSpec


class CorrectionStatusRequest(EnvironmentRequest):
    preview_token: str = Field(min_length=64, max_length=8192)


class SettleCorrectionWorkRequest(MutationRequest):
    side_work_id: str

    _side_work_id = field_validator("side_work_id")(_uuid7)


class AdminIdentity(_StrictModel):
    application_version: Literal["0.0.0"] = "0.0.0"


class HealthPayload(_StrictModel):
    status: Literal["healthy", "unavailable", "misconfigured"]
    environment_kind: Literal["development", "system_test", "acceptance"]
    environment_id: str
    identity: AdminIdentity
    database_reachable: bool
    role_status: Literal["verified", "unavailable", "rejected"]
    error_code: str | None = None


class SchemaStatusPayload(_StrictModel):
    status: Literal["current", "dirty", "unavailable"]
    environment_id: str
    table_count: int
    missing_tables: tuple[str, ...] = ()
    revision: str | None = None
    baseline_identity: str | None = None
    resource_digest: str | None = None
    catalog_digest: str | None = None
    role_policy_digest: str | None = None
    error_code: str | None = None


class AdminToolResult[PayloadT](_StrictModel):
    contract_version: Literal["2.0"] = "2.0"
    operation_id: str
    status: Literal["succeeded", "rejected", "conflict", "failed", "unknown"]
    result: PayloadT | None = None
    error_code: str | None = None
    observed_versions: dict[str, int | str | None] = Field(default_factory=dict)
    started_at: str
    ended_at: str


HealthResult = AdminToolResult[HealthPayload]
SchemaStatusResult = AdminToolResult[SchemaStatusPayload]
ObservationRequest = (
    RuntimeStatusRequest
    | SubjectSnapshotRequest
    | TraceFlowRequest
    | InspectScopeRequest
    | TailDiagnosticsRequest
    | CorrectionStatusRequest
)
AdminMutationRequest = (
    EnvironmentInitializeRequest
    | EnvironmentResetPreviewRequest
    | EnvironmentResetRequest
    | RuntimeControlRequest
    | InjectCreatorInputRequest
    | ArmFaultRequest
    | ClearFaultsRequest
    | PreviewCorrectionRequest
    | ApplyCorrectionRequest
    | SettleCorrectionWorkRequest
)


__all__ = (
    "AdminIdentity",
    "AdminMutationRequest",
    "AdminToolResult",
    "ApplyCorrectionRequest",
    "ArmFaultRequest",
    "ClearFaultsRequest",
    "CorrectionSpec",
    "CorrectionStatusRequest",
    "DeleteUncommittedCreatorInputSpec",
    "EnvironmentInitializeRequest",
    "EnvironmentRequest",
    "EnvironmentResetPreviewRequest",
    "EnvironmentResetRequest",
    "HealthPayload",
    "HealthRequest",
    "HealthResult",
    "InjectCreatorInputRequest",
    "InspectScopeRequest",
    "MutationRequest",
    "ObservationRequest",
    "PreviewCorrectionRequest",
    "ReconcileUnknownCreatorEffectSpec",
    "RepairSubjectComponentHeadSpec",
    "ReplaceSubjectComponentSpec",
    "RequeueStuckWorkSpec",
    "RuntimeControlRequest",
    "RuntimeStatusRequest",
    "SchemaStatusPayload",
    "SchemaStatusRequest",
    "SchemaStatusResult",
    "SettleCorrectionWorkRequest",
    "SubjectSnapshotRequest",
    "TailDiagnosticsRequest",
    "TraceFlowRequest",
)
