"""Business payload contracts shared by the administrative transports."""

from __future__ import annotations

from typing import Any, Literal

from armi_local_control.configuration.models import (
    CameraSourceConfig,
    ScreenSourceConfig,
    VisionConfig,
    VoiceConfig,
    VoiceDeviceConfig,
)
from pydantic import (
    BaseModel,
    ConfigDict,
    JsonValue,
    RootModel,
    SerializerFunctionWrapHandler,
    model_serializer,
)

from .authorization import AuthorizationIntent
from .contracts import (
    AdminToolResult,
    DeleteUncommittedCreatorInputSpec,
    ReconcileUnknownCreatorEffectSpec,
    RepairSubjectComponentHeadSpec,
    ReplaceSubjectComponentSpec,
    RequeueStuckWorkSpec,
)


class Payload(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    @model_serializer(mode="wrap")
    def supplied_fields(self, handler: SerializerFunctionWrapHandler) -> dict[str, Any]:
        return {
            key: value
            for key, value in handler(self).items()
            if key in self.model_fields_set
        }


class AuthorizationPayload(Payload):
    intent: AuthorizationIntent
    status: Literal["pending", "approved", "revoked", "consumed"]
    issuer_id: str | None
    consumed_by: str | None
    request_digest: str
    expired: bool


class GraphReference(Payload):
    kind: str
    id: str


class GraphAttributes(Payload):
    target_kind: str | None = None
    target_ref: str | None = None
    operation: str | None = None
    result_status: str | None = None
    occurred_at: str | None = None
    status: str | None = None
    receipt_digest: str | None = None
    subject_version: int | None = None
    trace_id: str | None = None
    prepared_at: str | None = None
    attempt_id: str | None = None
    action_intent_id: str | None = None


class GraphNode(GraphReference):
    owner: str
    attributes: GraphAttributes


class GraphEdge(Payload):
    kind: str
    source: GraphReference
    target: GraphReference
    owner: str


class GraphPage(Payload):
    nodes: list[GraphNode]
    edges: list[GraphEdge]
    missing: list[GraphReference]
    truncated: bool
    cursor: str | None


class FlowGraphPayload(GraphPage):
    schema_version: Literal["armi.admin-flow-graph.v1"]
    selector: GraphReference
    expansion_limit: int
    expansion_truncated: bool


class ScopeGraphPayload(GraphPage):
    schema_version: Literal["armi.admin-scope-graph.v2"]
    expansion_limit: int
    expansion_truncated: bool
    relations: list[
        Literal["current_owner", "direct_dependencies", "direct_dependents"]
    ]


class SubjectIdentity(Payload):
    subject_id: str
    subject_version: int
    state_epoch: int
    status: str
    current_generation_id: str
    current_bundle_activation_id: str | None


class SubjectComponent(Payload):
    component_kind: str
    component_version: int
    privacy_scope: str
    payload: JsonValue = None


class PrivateMaterial(Payload):
    material_id: str
    current_revision_id: str
    material_kind: str
    head_version: int
    revision_no: int
    title: str
    body: str
    metadata: dict[str, JsonValue]
    material_status: str
    privacy_status: str
    artifact_id: str | None
    deleted_at: str | None
    created_at: str
    updated_at: str


class SubjectSnapshotPayload(Payload):
    subject: SubjectIdentity | None
    components: list[SubjectComponent]
    materials: list[PrivateMaterial] | None = None
    materials_truncated: bool | None = None


class DiagnosticEvent(Payload):
    timestamp: str | None = None
    sequence: int | None = None
    event: str | None = None
    level: str | None = None
    service: str | None = None
    instance_id: str | None = None
    result_code: str | None = None
    reason_codes: list[str] | None = None
    duration_ms: float | int | None = None


class DiagnosticPagePayload(Payload):
    events: list[DiagnosticEvent]
    truncated: bool
    cursor: str | None


class ConsumerVersion(Payload):
    consumer: str
    source: str
    version: str


class AssetConsumption(Payload):
    source: str | None = None
    versions: list[str] | None = None
    consumers: list[ConsumerVersion] | None = None
    state: Literal["loaded", "mixed_versions", "not_loaded"] | None = None


class ConfigurationOverride(Payload):
    variable: str
    path: list[str]
    value: str | int


class ConfigurationPayload(Payload):
    # Partial YAML values and the validated effective model are configuration
    # documents. Lifecycle, file versions, activation and errors are explicit.
    version: str | None = None
    expected_version: str | None = None
    configuration_state: Literal["configured", "invalid", "missing"] | None = None
    values: dict[str, JsonValue] | None = None
    effective_on_next_start: dict[str, JsonValue] | None = None
    source: str | None = None
    sources: list[str] | None = None
    desired_digest: str | None = None
    desired_source_version: str | None = None
    error_code: str | None = None
    activation: Literal[
        "invalid",
        "not_saved",
        "saved",
        "effective",
        "partially_effective",
        "restart_required",
        "not_running",
        "environment_override",
        "not_verified",
    ]
    restart_required: bool
    running_digest: str | None = None
    running_sources: list[str] | None = None
    blocking_overrides: list[ConfigurationOverride] | None = None
    loaded: AssetConsumption | None = None


class SuboperationDescriptor(Payload):
    selector: dict[str, str | bool]
    required_scope: str
    result_schema: dict[str, JsonValue]
    read_only: bool
    destructive: bool
    authorized: bool


class OperationDescriptor(Payload):
    name: str
    description: str
    request_schema: dict[str, JsonValue]
    result_schema: dict[str, JsonValue]
    read_only: bool
    destructive: bool
    conditional_scopes: dict[str, str]
    authorized: bool
    requires_runtime: bool
    unavailable_reason: str | None
    availability: Literal["available", "unavailable", "not_verified"]
    suboperations: list[SuboperationDescriptor]


class CapabilitiesPayload(Payload):
    environment_id: str
    environment_kind: str
    operator_id: str
    package_set_digest: str
    authorized_operations: list[str]
    runtime_status: str
    database_status: Literal["not_checked"]
    operations: list[OperationDescriptor]


class RuntimeStatePayload(Payload):
    runtime_state: Literal[
        "unborn",
        "starting",
        "recovering",
        "ready",
        "degraded",
        "draining",
        "stopping",
        "stopped",
        "blocked",
    ]
    readiness: Literal["ready", "not_ready"] | None = None
    instance_id: str | None = None
    reason_codes: list[str] | None = None
    runtime_configuration_digest: str | None = None
    configuration_sources: list[str] | None = None
    configuration_overrides: list[ConfigurationOverride] | None = None
    configuration_assets: dict[str, AssetConsumption] | None = None
    observability: dict[str, JsonValue] | None = None
    armed_faults: list[str] | None = None


class ProcessPayload(Payload):
    status: Literal[
        "running",
        "starting",
        "started",
        "already_running",
        "stopped",
        "not_ready",
        "unavailable",
    ]
    pid: int | None = None
    runtime: RuntimeStatePayload | ProcessPayload | None = None
    readiness: Literal["ready", "not_ready"] | None = None
    error_code: str | None = None


class DatabaseProcessPayload(Payload):
    ownership: Literal["exclusive", "shared", "external"]
    action: Literal["not_managed"] | None = None
    status: Literal["ready", "stopped"] | None = None
    reachability: (
        Literal["reachable", "unavailable", "not_authorized", "not_checked"] | None
    ) = None
    role_status: str | None = None
    error_code: str | None = None
    port: int | None = None


class SemanticProcessPayload(Payload):
    status: Literal[
        "disabled",
        "already_running",
        "running",
        "installed",
        "missing",
        "calibration_required",
        "unavailable",
        "stopped",
    ]
    pid: int | None = None
    port: int | None = None
    model_id: str | None = None
    endpoint: str | None = None
    gpu_layers: int | None = None
    gpu_name: str | None = None
    calibrated_p95_ms: float | None = None
    calibrated_prompt_tokens: int | None = None
    calibrated_gpu_memory_mib: float | None = None
    gpu_memory_measurement: str | None = None
    calibrated_rss_mib: float | None = None
    calibrated_idle_cpu_percent: float | None = None


class EnvironmentProcessPayload(Payload):
    status: Literal["ready", "not_ready"] | None = None
    runtime: ProcessPayload
    postgresql: DatabaseProcessPayload | ProcessPayload
    semantic_recall: SemanticProcessPayload | ProcessPayload


class LifecyclePayload(
    RootModel[
        EnvironmentProcessPayload
        | ProcessPayload
        | DatabaseProcessPayload
        | SemanticProcessPayload
    ]
):
    model_config = ConfigDict(strict=True, frozen=True)


class ControlPayload[ResultT](Payload):
    request_id: str
    status: Literal["succeeded"]
    result: ResultT


class FaultPayload(Payload):
    armed_faults: list[str]


class InputAdmissionPayload(Payload):
    interaction_id: str
    evidence_id: str
    opportunity_id: str
    newly_accepted: bool


class AuthorizationPreview(Payload):
    request_id: str
    request_digest: str
    intent: AuthorizationIntent


class AuthorizationRequirement(Payload):
    authorization_required: bool | None = None
    authorization_request: AuthorizationPreview | None = None
    authorization_unavailable_reason: str | None = None


class OwnedCorrectionTarget(Payload):
    operator_purpose: Literal["admin.correction"]
    operator_identity: str


class ReplaceTarget(ReplaceSubjectComponentSpec, OwnedCorrectionTarget):
    pass


class RepairTarget(RepairSubjectComponentHeadSpec, OwnedCorrectionTarget):
    pass


class DeleteInputTarget(DeleteUncommittedCreatorInputSpec, OwnedCorrectionTarget):
    pass


class RequeueTarget(RequeueStuckWorkSpec, OwnedCorrectionTarget):
    pass


class ReconcileEffectTarget(ReconcileUnknownCreatorEffectSpec, OwnedCorrectionTarget):
    pass


type CorrectionKind = Literal[
    "replace_subject_component",
    "repair_subject_component_head",
    "delete_uncommitted_creator_input",
    "requeue_stuck_work",
    "reconcile_unknown_creator_effect",
]


class CorrectionImpact(Payload):
    scope_digest: str
    impact_digest: str
    before_digest: str
    after_digest: str
    description: str


class CorrectionPreviewPayload(AuthorizationRequirement):
    correction_kind: CorrectionKind
    target_count: int
    dependency_count: int
    side_work_required: bool
    subject_version: int
    state_epoch: int
    preview_token: str
    expires_at: str
    target: (
        ReplaceTarget
        | RepairTarget
        | DeleteInputTarget
        | RequeueTarget
        | ReconcileEffectTarget
    )
    impact: CorrectionImpact
    effect_reconciliation: dict[str, JsonValue] | None = None


class CorrectionStatusPayload(Payload):
    correction_kind: CorrectionKind
    result_id: str
    status: Literal["applied", "not_applied", "diverged", "unknown"]
    observed_state_epoch: int
    side_work_id: str | None
    reconciled: bool | None = None


class CorrectionAppliedPayload(Payload):
    result_id: str
    correction_kind: CorrectionKind
    previous_subject_version: int
    subject_version: int
    previous_state_epoch: int
    state_epoch: int
    side_work_id: str | None
    safe_to_restart: bool
    status: Literal["applied"]


class CorrectionApplyPayload(
    RootModel[CorrectionAppliedPayload | CorrectionStatusPayload]
):
    model_config = ConfigDict(strict=True, frozen=True)


class CorrectionWorkPayload(Payload):
    side_work_id: str
    status: str
    file_result: Literal["artifact_lifecycle_owned"]


class RegisteredEnvironment(Payload):
    environment_id: str
    environment_kind: str
    incarnation: int
    resettable: bool
    test_controls_enabled: bool
    registered_at: str


class EnvironmentInitializedPayload(Payload):
    environment_id: str
    incarnation: int
    birth_mode: Literal["unborn", "manifest"]
    status: Literal["initialized"]
    environment: RegisteredEnvironment | None
    created: bool


class ResetPreviewPayload(AuthorizationRequirement):
    preview_token: str
    expires_at: str
    incarnation: int
    environment_id: str
    environment_root: str
    subject_versions: SubjectSnapshotPayload
    impact: str


class ResetPayload(Payload):
    environment_id: str
    previous_incarnation: int
    incarnation: int
    status: Literal["reset"]


class DeletionTarget(Payload):
    kind: str
    id: str
    action: str
    retention_reason: str | None
    owner: str


class DeletionPreviewPayload(AuthorizationRequirement):
    party_id: str
    scope_digest: str
    expires_at: str
    scope: Literal["party_local_data"]
    target_count: int
    targets: list[DeletionTarget]


class RightsItem(Payload):
    item_id: str
    target_kind: str
    required_action: str
    result_status: str
    retention_reason: str | None
    created_at: str
    completed_at: str | None


class RightsOrderPayload(Payload):
    order_id: str
    requester_party_id: str
    requester_kind: str
    order_kind: str
    scope_kind: str
    status: str
    execution_status: str
    effective_at: str
    completed_at: str | None
    newly_created: bool
    items: list[RightsItem] | None = None


class OtherHumanPartyPayload(Payload):
    party_id: str
    party_key: str
    display_label: str
    identity_assurance: str


class OtherHumanScenePayload(Payload):
    scene_id: str
    party_id: str
    scene_key: str
    status: Literal["open", "closed"]


class OtherHumanInputPayload(InputAdmissionPayload):
    party_id: str
    scene_id: str


class OtherHumanRightsPagePayload(Payload):
    orders: list[RightsOrderPayload]


class OtherHumanRightsGetPayload(Payload):
    order: RightsOrderPayload | None


class OtherHumanPayload(
    RootModel[
        OtherHumanPartyPayload
        | OtherHumanScenePayload
        | OtherHumanInputPayload
        | RightsOrderPayload
        | OtherHumanRightsPagePayload
        | OtherHumanRightsGetPayload
    ]
):
    model_config = ConfigDict(strict=True, frozen=True)


class DiagnosticCheck(Payload):
    component: str
    status: Literal[
        "observed",
        "succeeded",
        "rejected",
        "conflict",
        "failed",
        "unknown",
        "configured",
        "invalid",
        "missing",
        "unavailable",
        "not_authorized",
        "not_checked",
    ]
    error_code: str | None = None
    evidence: JsonValue = None
    next_operations: list[str]


class DoctorPayload(Payload):
    checks: list[DiagnosticCheck]
    collection_performed: Literal[False]
    external_effects_dispatched: Literal[False]
    artifact_integrity: dict[str, JsonValue]


class OperatorSchemaPayload(Payload):
    status: str
    table_count: int
    current_revision: str
    head_revision: str
    baseline_identity: str
    resource_digest: str
    catalog_digest: str
    role_policy_digest: str


class DatabaseMaintenancePayload(Payload):
    schema_version: Literal["armi.database-maintenance.v1"]
    status: Literal["applied"]
    table_count: int
    completed_at: str


class BirthPayload(Payload):
    status: Literal["applied", "existing"]
    subject_id: str
    life_generation_id: str
    bundle_activation_id: str
    request_digest: str


class ArtifactFinding(Payload):
    category: str
    artifact_id: str | None
    content_digest: str | None


class ArtifactCleanupPreview(Payload):
    schema_version: str
    status: Literal["dry_run"]
    counts: dict[str, int]
    findings: list[ArtifactFinding]


class ArtifactCleanupApplied(Payload):
    schema_version: str
    status: Literal["applied"]
    removed_counts: dict[str, int]
    removed_bytes: int
    remaining_counts: dict[str, int]


class ArtifactCleanupPayload(
    RootModel[ArtifactCleanupPreview | ArtifactCleanupApplied]
):
    model_config = ConfigDict(strict=True, frozen=True)


class CapacityAuthority(Payload):
    active_runtime_count: int
    heartbeat_age_seconds: int | float | None


class CapacityBacklog(Payload):
    work_open: int
    work_oldest_open_age_seconds: int | None
    effects_open: int
    effects_oldest_open_age_seconds: int | None
    total_open: int


class CapacityResources(Payload):
    process_rss_bytes: int | None
    process_cpu_milliseconds: int
    process_uptime_seconds: int
    database_bytes: int
    artifact_bytes: int
    disk_free_bytes: int
    disk_state: str
    diagnostic_retained_bytes: int


class CapacitySample(Payload):
    offset_milliseconds: int
    observed_at: str
    runtime_state: str
    readiness: str
    authority: CapacityAuthority
    backlog: CapacityBacklog
    resources: CapacityResources


class CapacityThreshold(Payload):
    limit: int
    evaluation: Literal["unknown", "evaluated"]
    sample_count: int
    missing_sample_count: int


class CapacityPayload(Payload):
    schema_version: Literal["armi.runtime-capacity-baseline.v2"]
    status: Literal["pass", "attention"]
    requested_duration_seconds: int
    sample_interval_seconds: int
    sample_count: int
    unavailable_sample_count: int
    unavailable_reasons: list[str]
    issue_codes: list[str]
    thresholds: dict[str, CapacityThreshold]
    deltas: dict[str, int | None]
    maxima: dict[str, int | None]
    minimum_disk_free_bytes: int
    samples: list[CapacitySample]


class AudioDevicePayload(Payload):
    host_api: str
    name: str
    input_channels: int
    output_channels: int
    default_sample_rate: float


class VoiceDevicesPayload(Payload):
    devices: list[AudioDevicePayload]


class CameraIdentityPayload(CameraSourceConfig):
    backend: str


class VisionSourcesPayload(Payload):
    cameras: list[CameraIdentityPayload]
    screens: list[ScreenSourceConfig]


class MoodDisplayConfiguration(Payload):
    enabled: bool
    port: str
    expected_device_id: str


class DeviceBindingCheck(Payload):
    component: str
    configured_identity: (
        VoiceDeviceConfig | CameraSourceConfig | ScreenSourceConfig | None
    )
    binding_status: Literal[
        "disabled", "not_configured", "matches", "ambiguous", "missing", "unavailable"
    ]
    match_count: int | None
    error_code: str | None = None


class DeviceBindingsPayload(Payload):
    voice: VoiceConfig
    vision: VisionConfig
    mood_display: MoodDisplayConfiguration | None
    checks: list[DeviceBindingCheck]
    mood_display_binding: Literal["disabled", "not_verified"]
    mood_display_next_operation: Literal["maintenance.mood_display_probe"]
    collection_performed: Literal[False]


class MoodDisplayProbe(Payload):
    device_id: str
    firmware_version: str
    protocol_version: str
    boot_id: str


class MoodDisplayProbePayload(Payload):
    probe: MoodDisplayProbe
    expected_device_id: str
    binding_status: Literal["matches", "mismatch"]


class QQChannelPayload(Payload):
    projection_version: Literal["creator-channel-health.v2"]
    channel: Literal["qq"]
    driver: Literal["napcat"]
    state: Literal[
        "disabled",
        "starting",
        "login_required",
        "ready",
        "unavailable",
        "misconfigured",
    ]
    ingress_ready: bool
    api_reachable: bool
    account_online: bool | None
    account_matches: bool | None
    webui_url: str | None
    observed_at: str
    reason_codes: list[str]


class NapcatStartPayload(Payload):
    status: Literal["disabled", "already_ready", "started", "attention"]
    channel: QQChannelPayload


class NapcatOpenPayload(Payload):
    status: Literal["opened"]
    webui_url: str
    token_delivery: Literal["clipboard", "url_query"]


class SemanticCalibrationPayload(Payload):
    gpu_layers: int
    gpu_name: str
    calibrated_p95_ms: float
    calibrated_prompt_tokens: int
    calibrated_gpu_memory_mib: float | None
    gpu_memory_measurement: str
    calibrated_rss_mib: float | None
    calibrated_idle_cpu_percent: float | None


class SemanticInstallPayload(SemanticCalibrationPayload):
    status: Literal["installed"]
    model_id: str
    llama_cpp_version: str


class SemanticStatusPayload(SemanticProcessPayload):
    database_status: Literal["ready", "unavailable"]
    projection_count: int | None = None
    coverage_state: str | None = None
    retrieval_profile: str | None = None
    dense_index_ready: bool | None = None
    lexical_index_ready: bool | None = None
    capacity_status: str | None = None


class CredentialCheck(Payload):
    purpose: str
    name: str
    locator: str | None
    status: Literal["resolvable", "missing", "unavailable"]
    error_code: str | None


class CredentialChecksPayload(Payload):
    checks: list[CredentialCheck]
    external_effects_dispatched: Literal[False]


class MaintenancePayload(
    RootModel[
        OperatorSchemaPayload
        | DatabaseMaintenancePayload
        | BirthPayload
        | ArtifactCleanupPayload
        | CapacityPayload
        | VoiceDevicesPayload
        | VisionSourcesPayload
        | DeviceBindingsPayload
        | MoodDisplayProbePayload
        | QQChannelPayload
        | NapcatStartPayload
        | NapcatOpenPayload
        | SemanticCalibrationPayload
        | SemanticInstallPayload
        | SemanticStatusPayload
        | CredentialChecksPayload
    ]
):
    model_config = ConfigDict(strict=True, frozen=True)


MAINTENANCE_PAYLOADS: dict[str, type[BaseModel]] = {
    "credential_check": CredentialChecksPayload,
    "database_install": OperatorSchemaPayload,
    "database_check": OperatorSchemaPayload,
    "database_maintain": DatabaseMaintenancePayload,
    "birth": BirthPayload,
    "artifact_cleanup": ArtifactCleanupPayload,
    "capacity_check": CapacityPayload,
    "voice_devices": VoiceDevicesPayload,
    "vision_sources": VisionSourcesPayload,
    "device_bindings": DeviceBindingsPayload,
    "mood_display_probe": MoodDisplayProbePayload,
    "napcat_status": QQChannelPayload,
    "napcat_start": NapcatStartPayload,
    "napcat_open": NapcatOpenPayload,
    "semantic_install": SemanticInstallPayload,
    "semantic_calibrate": SemanticCalibrationPayload,
    "semantic_status": SemanticStatusPayload,
}


OTHER_HUMAN_PAYLOADS: dict[str, type[BaseModel]] = {
    "party_register": OtherHumanPartyPayload,
    "scene_set": OtherHumanScenePayload,
    "message_send": OtherHumanInputPayload,
    "data_rights_request": RightsOrderPayload,
    "data_rights_list": OtherHumanRightsPagePayload,
    "data_rights_get": OtherHumanRightsGetPayload,
}


class InvocationAudit(Payload):
    operator_id: str | None = None
    authorization_ref: str | None = None
    scope: str | None = None


class InvocationContinuation(Payload):
    operation_name: str
    idempotency_key: str


class ReconciliationPayload(Payload):
    basis: Literal[
        "recorded_outcome",
        "recorded_steps",
        "preidentified_runtime",
        "configuration_file_identity",
        "owner_deletion_request",
        "owner_correction",
        "current_configuration_only",
        "current_process_state_only",
        "insufficient_evidence",
    ]
    observed: JsonValue = None
    reason: str | None = None
    next_operations: list[str] | None = None


class InvocationPayload(Payload):
    state: Literal["not_found", "started", "running", "unknown", "finished"]
    schema_version: Literal["armi.admin-invocation.v2"] | None = None
    operation: str | None = None
    idempotency_key: str | None = None
    audit: InvocationAudit | None = None
    phase: str | None = None
    request_digest: str | None = None
    result: (
        AdminToolResult[
            LifecyclePayload
            | ProcessPayload
            | ConfigurationPayload
            | AuthorizationPayload
            | CorrectionApplyPayload
            | CorrectionWorkPayload
            | RightsOrderPayload
            | OtherHumanPayload
            | MaintenancePayload
            | EnvironmentInitializedPayload
            | ResetPayload
            | ControlPayload[RuntimeStatePayload | FaultPayload | InputAdmissionPayload]
        ]
        | None
    ) = None
    reconciliation: ReconciliationPayload | None = None
    reconciliation_reason: Literal["evidence_missing"] | None = None
    wait_timed_out: bool | None = None
    continuation: InvocationContinuation | None = None


RESULT_PAYLOADS: dict[str, type[BaseModel]] = {
    "invocation_get": InvocationPayload,
    "invocation_wait": InvocationPayload,
    "invocation_reconcile": InvocationPayload,
    "maintenance": MaintenancePayload,
    "doctor": DoctorPayload,
    "other_human": OtherHumanPayload,
    "capabilities": CapabilitiesPayload,
    "authorization_get": AuthorizationPayload,
    "authorization_approve": AuthorizationPayload,
    "authorization_revoke": AuthorizationPayload,
    "trace_flow": FlowGraphPayload,
    "inspect_scope": ScopeGraphPayload,
    "subject_snapshot": SubjectSnapshotPayload,
    "tail_diagnostics": DiagnosticPagePayload,
    "configuration": ConfigurationPayload,
    "runtime_status": ProcessPayload,
    "runtime_start": ProcessPayload,
    "runtime_stop": ProcessPayload,
    "runtime_restart": ProcessPayload,
    "runtime_drain": ControlPayload[RuntimeStatePayload],
    "arm_fault": ControlPayload[FaultPayload],
    "clear_faults": ControlPayload[FaultPayload],
    "inject_creator_input": ControlPayload[InputAdmissionPayload],
    "data_deletion_preview": DeletionPreviewPayload,
    "data_deletion_apply": RightsOrderPayload,
    "preview_correction": CorrectionPreviewPayload,
    "apply_correction": CorrectionApplyPayload,
    "correction_status": CorrectionStatusPayload,
    "settle_correction_work": CorrectionWorkPayload,
    "environment_initialize": EnvironmentInitializedPayload,
    "environment_reset_preview": ResetPreviewPayload,
    "environment_reset": ResetPayload,
    **{
        name: LifecyclePayload
        for name in (
            "environment_start",
            "environment_stop",
            "environment_restart",
            "environment_status",
        )
    },
}


__all__ = ("MAINTENANCE_PAYLOADS", "OTHER_HUMAN_PAYLOADS", "RESULT_PAYLOADS")
