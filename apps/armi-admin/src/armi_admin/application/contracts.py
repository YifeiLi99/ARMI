"""Strict administrative contracts shared by CLI and MCP."""

from __future__ import annotations

import re
from typing import Annotated, Literal, Self, cast
from uuid import UUID

from armi_local_control.maintenance import MaintenanceParameters
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
    contract_version: Literal["5.0"] = "5.0"


class EnvironmentRequest(_StrictModel):
    contract_version: Literal["5.0"] = "5.0"
    environment_id: str

    _environment_id = field_validator("environment_id")(_uuid7)


class SchemaStatusRequest(EnvironmentRequest):
    pass


class RuntimeStatusRequest(EnvironmentRequest):
    pass


class DoctorRequest(EnvironmentRequest):
    """Read diagnostics only; never collect devices or dispatch external effects."""


class InvocationStatusRequest(EnvironmentRequest):
    operation_name: str = Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")
    idempotency_key: str = Field(pattern=r"^[A-Za-z0-9._:-]{1,128}$")


class InvocationWaitRequest(InvocationStatusRequest):
    timeout_seconds: int = Field(default=25, ge=0, le=25)


class AuthorizationGetRequest(EnvironmentRequest):
    request_id: str
    _request_id = field_validator("request_id")(_uuid7)


class AuthorizationApproveRequest(AuthorizationGetRequest):
    expected_request_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    idempotency_key: str = Field(pattern=r"^[A-Za-z0-9._:-]{1,128}$")


class AuthorizationRevokeRequest(AuthorizationGetRequest):
    idempotency_key: str = Field(pattern=r"^[A-Za-z0-9._:-]{1,128}$")


class ConfigurationRequest(EnvironmentRequest):
    target: Literal["runtime", "model-bindings", "web-search", "qq", "mood-display"] = (
        "runtime"
    )
    action: Literal["read", "validate", "preview", "apply", "status"]
    patch: dict[str, object] = Field(default_factory=dict)
    document: dict[str, object] | None = None
    expected_version: str | None = Field(default=None, pattern=r"^sha256:[0-9a-f]{64}$")
    idempotency_key: str | None = Field(
        default=None, pattern=r"^[A-Za-z0-9._:-]{1,128}$"
    )

    @model_validator(mode="after")
    def _edit_version(self) -> Self:
        if self.document is not None and self.patch:
            raise ValueError("ADMIN-CONFIG-EDIT-CONFLICT")
        if self.action == "apply" and self.idempotency_key is None:
            raise ValueError("ADMIN-IDEMPOTENCY-REQUIRED")
        if (
            self.action in {"validate", "preview", "apply"}
            and self.expected_version is None
        ):
            raise ValueError("ADMIN-CONFIG-VERSION-REQUIRED")
        if self.action in {"read", "status"} and (
            self.patch or self.document is not None or self.expected_version is not None
        ):
            raise ValueError("ADMIN-CONFIG-READ-ARGUMENTS")
        return self


class SubjectSnapshotRequest(EnvironmentRequest):
    detail: Literal["summary", "private"] = "summary"


class TraceFlowRequest(EnvironmentRequest):
    interaction_id: str | None = None
    operation_id: str | None = None
    episode_id: str | None = None
    effect_id: str | None = None
    trace_id: str | None = Field(default=None, pattern=r"^[0-9a-f]{32}$")
    limit: int = Field(default=100, ge=1, le=200)
    cursor: str | None = Field(default=None, pattern=r"^[A-Za-z0-9_-]{8,512}$")

    @model_validator(mode="after")
    def _exact_selector(self) -> Self:
        values = (
            self.interaction_id,
            self.operation_id,
            self.episode_id,
            self.effect_id,
            self.trace_id,
        )
        if sum(value is not None for value in values) != 1:
            raise ValueError("ADMIN-INPUT-TRACE-SELECTOR")
        for value in values[:-1]:
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

    @field_validator("object_ids", "relations", mode="before")
    @classmethod
    def _wire_arrays(cls, value: object) -> object:
        # MCP validates decoded JSON; CLI validates JSON bytes. Both represent
        # arrays identically, while element validation remains strictly typed.
        return tuple(cast(list[object], value)) if type(value) is list else value

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


class ScopedOperationRequest(EnvironmentRequest):
    environment_incarnation: int = Field(ge=1)
    purpose: str = Field(pattern=_TOKEN.pattern)


class OperationRequest(ScopedOperationRequest):
    idempotency_key: str | None = Field(default=None, pattern=_TOKEN.pattern)


class MutationRequest(ScopedOperationRequest):
    idempotency_key: str = Field(pattern=_TOKEN.pattern)


class EnvironmentInitializeRequest(MutationRequest):
    birth_mode: Literal["unborn", "manifest"] = "unborn"


class OtherHumanPartyCommand(_StrictModel):
    party_key: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]{0,63}$")


class OtherHumanRegisterCommand(OtherHumanPartyCommand):
    action: Literal["party_register"]
    display_label: str = Field(min_length=1, max_length=256)


class OtherHumanSceneCommand(OtherHumanPartyCommand):
    action: Literal["scene_set"]
    scene_key: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]{0,63}$")
    status: Literal["open", "closed"]


class OtherHumanMessageCommand(OtherHumanPartyCommand):
    action: Literal["message_send"]
    scene_key: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]{0,63}$")
    message: str = Field(min_length=1, max_length=262144)


class OtherHumanRightsCommand(OtherHumanPartyCommand):
    action: Literal["data_rights_request"]
    order_kind: Literal["stop_contact", "stop_use", "delete_related"]


class OtherHumanRightsListCommand(OtherHumanPartyCommand):
    action: Literal["data_rights_list"]


class OtherHumanRightsGetCommand(OtherHumanPartyCommand):
    action: Literal["data_rights_get"]
    order_id: str
    _order_id = field_validator("order_id")(_uuid7)


class OtherHumanRequest(OperationRequest):
    command: Annotated[
        OtherHumanRegisterCommand
        | OtherHumanSceneCommand
        | OtherHumanMessageCommand
        | OtherHumanRightsCommand
        | OtherHumanRightsListCommand
        | OtherHumanRightsGetCommand,
        Field(discriminator="action"),
    ]

    @property
    def read_only(self) -> bool:
        return self.command.action in {"data_rights_list", "data_rights_get"}

    @model_validator(mode="after")
    def _write_key(self) -> Self:
        if not self.read_only and self.idempotency_key is None:
            raise ValueError("ADMIN-IDEMPOTENCY-REQUIRED")
        if (
            self.command.action == "data_rights_request"
            and self.command.order_kind == "delete_related"
        ):
            raise ValueError("ADMIN-SPECIFIC-AUTHORIZATION-REQUIRED")
        return self


class MaintenanceRequest(OperationRequest, MaintenanceParameters):
    @model_validator(mode="after")
    def _no_reset_bypass(self) -> Self:
        if not self.read_only and self.idempotency_key is None:
            raise ValueError("ADMIN-IDEMPOTENCY-REQUIRED")
        if self.action == "reset":
            raise ValueError("ADMIN-RESET-PREVIEW-REQUIRED")
        if self.action == "database_maintain" and not self.apply:
            raise ValueError("ADMIN-MAINTENANCE-APPLY-REQUIRED")
        return self


class EnvironmentResetPreviewRequest(OperationRequest):
    pass


class DataDeletionPreviewRequest(OperationRequest):
    party_key: str | None = Field(default=None, pattern=r"^[a-z0-9][a-z0-9._-]{0,63}$")


class DataDeletionApplyRequest(MutationRequest):
    party_key: str | None = Field(default=None, pattern=r"^[a-z0-9][a-z0-9._-]{0,63}$")
    scope_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    authorization_id: str
    _authorization_id = field_validator("authorization_id")(_uuid7)


class EnvironmentResetRequest(MutationRequest):
    preview_token: str = Field(min_length=32, max_length=4096)
    authorization_id: str
    authorization_ref: str | None = Field(default=None, min_length=1, max_length=256)
    _authorization_id = field_validator("authorization_id")(_uuid7)


class RuntimeControlRequest(MutationRequest):
    expected_instance_id: str | None = None

    @field_validator("expected_instance_id")
    @classmethod
    def _instance_id(cls, value: str | None) -> str | None:
        return None if value is None else _uuid7(value)


class EnvironmentLifecycleRequest(OperationRequest):
    component: Literal["environment", "runtime", "postgresql", "semantic-recall"] = (
        "environment"
    )

    @model_validator(mode="after")
    def _write_key(self) -> Self:
        if self.purpose != "admin.environment_status" and self.idempotency_key is None:
            raise ValueError("ADMIN-IDEMPOTENCY-REQUIRED")
        return self


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


class PreviewCorrectionRequest(OperationRequest):
    spec: CorrectionSpec


class ApplyCorrectionRequest(MutationRequest):
    preview_token: str = Field(min_length=64, max_length=8192)
    spec: CorrectionSpec
    authorization_ref: str | None = Field(default=None, min_length=1, max_length=256)
    authorization_id: str | None = None

    @field_validator("authorization_id")
    @classmethod
    def _authorization_id(cls, value: str | None) -> str | None:
        return None if value is None else _uuid7(value)

    @model_validator(mode="after")
    def _specific_authorization(self) -> Self:
        if (
            self.spec.correction_kind
            in {
                "replace_subject_component",
                "repair_subject_component_head",
                "delete_uncommitted_creator_input",
            }
            and self.authorization_id is None
        ):
            raise ValueError("ADMIN-SPECIFIC-AUTHORIZATION-REQUIRED")
        return self


class CorrectionStatusRequest(EnvironmentRequest):
    preview_token: str = Field(min_length=64, max_length=8192)


class SettleCorrectionWorkRequest(MutationRequest):
    side_work_id: str

    _side_work_id = field_validator("side_work_id")(_uuid7)


class AdminIdentity(_StrictModel):
    application_version: Literal["0.0.0"] = "0.0.0"


class HealthPayload(_StrictModel):
    status: Literal["healthy", "unavailable", "misconfigured"]
    environment_kind: Literal["development", "system_test", "acceptance", "active"]
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
    operator_id: str | None = None
    contract_version: Literal["5.0"] = "5.0"
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
    InvocationStatusRequest
    | DoctorRequest
    | RuntimeStatusRequest
    | SubjectSnapshotRequest
    | TraceFlowRequest
    | InspectScopeRequest
    | TailDiagnosticsRequest
    | CorrectionStatusRequest
)
AdminMutationRequest = (
    DataDeletionPreviewRequest
    | DataDeletionApplyRequest
    | OtherHumanRequest
    | MaintenanceRequest
    | EnvironmentInitializeRequest
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
    "DataDeletionApplyRequest",
    "DataDeletionPreviewRequest",
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
