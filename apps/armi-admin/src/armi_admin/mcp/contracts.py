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
    contract_version: Literal["1.0"] = "1.0"


class EnvironmentRequest(_StrictModel):
    contract_version: Literal["1.0"] = "1.0"
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


class AdvanceTestClockRequest(MutationRequest):
    seconds: int = Field(ge=1, le=3600)


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


class RunTestRequest(MutationRequest):
    scenario: Literal[
        "admin.observation-isolation.v1",
        "admin.runtime-lifecycle.v1",
        "admin.creator-input-intake.v1",
        "admin.fault-control.v1",
    ]


class _ComponentState(_StrictModel):
    pass


class SelfState(_ComponentState):
    schema_version: Literal["armi.self.v1"]
    identity_kind: Literal["electronic_person"]
    creator_role_awareness: Literal["unique_primary_creator"]
    name: str | None = Field(default=None, max_length=256)
    self_description: str | None = Field(default=None, max_length=4096)
    interests: tuple[str, ...] = Field(max_length=32)
    values: tuple[str, ...] = Field(max_length=32)
    preferences: tuple[str, ...] = Field(max_length=32)
    goals: tuple[str, ...] = Field(max_length=32)
    self_narrative: str | None = Field(default=None, max_length=4096)
    tensions: tuple[str, ...] = Field(max_length=32)

    @field_validator(
        "name",
        "self_description",
        "self_narrative",
    )
    @classmethod
    def _optional_text(cls, value: str | None) -> str | None:
        if value is not None and ("\x00" in value or not value.strip()):
            raise ValueError("ADMIN-CORRECTION-COMPONENT-PAYLOAD")
        return value

    @field_validator("interests", "values", "preferences", "goals", "tensions")
    @classmethod
    def _text_list(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if any(
            "\x00" in value or not value.strip() or len(value) > 1024
            for value in values
        ):
            raise ValueError("ADMIN-CORRECTION-COMPONENT-PAYLOAD")
        return values


class MindState(_ComponentState):
    schema_version: Literal["armi.mind.v1"]
    understanding: tuple[str, ...] = Field(max_length=32)
    attention: tuple[str, ...] = Field(max_length=32)
    emotions: tuple[str, ...] = Field(max_length=32)
    thoughts: tuple[str, ...] = Field(max_length=32)
    wishes: tuple[str, ...] = Field(max_length=32)
    motivations: tuple[str, ...] = Field(max_length=32)
    mood: str | None = Field(default=None, max_length=256)

    @field_validator(
        "understanding",
        "attention",
        "emotions",
        "thoughts",
        "wishes",
        "motivations",
    )
    @classmethod
    def _text_list(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if any(
            "\x00" in value or not value.strip() or len(value) > 1024
            for value in values
        ):
            raise ValueError("ADMIN-CORRECTION-COMPONENT-PAYLOAD")
        return values

    @field_validator("mood")
    @classmethod
    def _mood(cls, value: str | None) -> str | None:
        if value is not None and ("\x00" in value or not value.strip()):
            raise ValueError("ADMIN-CORRECTION-COMPONENT-PAYLOAD")
        return value


class LifeModeState(_ComponentState):
    schema_version: Literal["armi.life-mode.v1"]
    mode: Literal["awake"]
    active_activities: tuple[str, ...] = Field(default=(), max_length=1)


ComponentState = Annotated[
    SelfState | MindState | LifeModeState,
    Field(discriminator="schema_version"),
]


class ReplaceSubjectComponentSpec(_StrictModel):
    correction_kind: Literal["replace_subject_component"]
    component_kind: Literal["self", "mind", "life_mode"]
    expected_component_version: int = Field(ge=1)
    replacement: ComponentState

    @model_validator(mode="after")
    def _matching_component(self) -> Self:
        expected = {
            "self": "armi.self.v1",
            "mind": "armi.mind.v1",
            "life_mode": "armi.life-mode.v1",
        }[self.component_kind]
        if self.replacement.schema_version != expected:
            raise ValueError("ADMIN-CORRECTION-COMPONENT-KIND")
        return self


class RepairSubjectComponentHeadSpec(_StrictModel):
    correction_kind: Literal["repair_subject_component_head"]
    component_kind: Literal["self", "mind", "life_mode"]
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

    _effect_id = field_validator("effect_id")(_uuid7)


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

    _environment_id = field_validator("environment_id")(_uuid7)


class SchemaStatusPayload(_StrictModel):
    status: Literal["current", "dirty", "unavailable"]
    environment_id: str
    table_count: int
    missing_tables: tuple[str, ...] = ()
    error_code: str | None = None

    _environment_id = field_validator("environment_id")(_uuid7)


class AdminToolResult[PayloadT](_StrictModel):
    contract_version: Literal["1.0"] = "1.0"
    operation_id: str
    status: Literal["succeeded", "rejected", "conflict", "failed", "unknown"]
    result: PayloadT | None = None
    error_code: str | None = None
    observed_versions: dict[str, int | str | None] = Field(default_factory=dict)
    started_at: str
    ended_at: str

    _operation_id = field_validator("operation_id")(_uuid7)


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
    | AdvanceTestClockRequest
    | ArmFaultRequest
    | ClearFaultsRequest
    | RunTestRequest
    | PreviewCorrectionRequest
    | ApplyCorrectionRequest
    | SettleCorrectionWorkRequest
)


__all__ = (
    "AdminIdentity",
    "AdminMutationRequest",
    "AdminToolResult",
    "AdvanceTestClockRequest",
    "ApplyCorrectionRequest",
    "ArmFaultRequest",
    "ClearFaultsRequest",
    "ComponentState",
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
    "RunTestRequest",
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
