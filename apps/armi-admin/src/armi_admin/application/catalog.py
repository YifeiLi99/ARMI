"""Explicit operation contracts for both administrative transports."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal, cast

from pydantic import BaseModel

from .contracts import (
    AdminToolResult,
    ApplyCorrectionRequest,
    ArmFaultRequest,
    AuthorizationApproveRequest,
    AuthorizationGetRequest,
    AuthorizationRevokeRequest,
    ClearFaultsRequest,
    ConfigurationRequest,
    CorrectionStatusRequest,
    DataDeletionApplyRequest,
    DataDeletionPreviewRequest,
    DoctorRequest,
    EnvironmentInitializeRequest,
    EnvironmentLifecycleRequest,
    EnvironmentResetPreviewRequest,
    EnvironmentResetRequest,
    HealthRequest,
    HealthResult,
    InjectCreatorInputRequest,
    InspectScopeRequest,
    InvocationStatusRequest,
    InvocationWaitRequest,
    MaintenanceRequest,
    OtherHumanRequest,
    PreviewCorrectionRequest,
    RuntimeControlRequest,
    RuntimeStatusRequest,
    SchemaStatusRequest,
    SchemaStatusResult,
    SettleCorrectionWorkRequest,
    SubjectSnapshotRequest,
    TailDiagnosticsRequest,
    TraceFlowRequest,
)

if TYPE_CHECKING:
    from .service import AdminToolService


@dataclass(frozen=True, slots=True)
class AdminOperation:
    name: str
    request: type[BaseModel]
    mode: Literal[
        "health",
        "schema",
        "observe",
        "mutate",
        "lifecycle",
        "configuration",
        "capabilities",
        "authorization",
    ]

    @property
    def read_only(self) -> bool:
        return self.mode in {
            "health",
            "schema",
            "observe",
            "capabilities",
        } or self.name in {
            "environment_status",
            "environment_reset_preview",
            "data_deletion_preview",
            "preview_correction",
            "authorization_get",
        }

    @property
    def destructive(self) -> bool:
        return self.name in {
            "environment_reset",
            "data_deletion_apply",
            "apply_correction",
            "settle_correction_work",
        }

    @property
    def result(self) -> type[AdminToolResult[Any]]:
        return (
            HealthResult
            if self.mode == "health"
            else SchemaStatusResult
            if self.mode == "schema"
            else AdminToolResult[dict[str, Any]]
        )

    @property
    def description(self) -> str:
        return OPERATION_DESCRIPTIONS[self.name]

    def invoke(
        self, service: AdminToolService, request: BaseModel
    ) -> AdminToolResult[Any]:
        if not isinstance(request, self.request):
            raise ValueError("ADMIN-INPUT")
        match self.mode:
            case "health":
                return service.health(cast(HealthRequest, request))
            case "schema":
                return service.schema_status(cast(SchemaStatusRequest, request))
            case "capabilities":
                return service.capabilities()
            case "authorization":
                return service.authorization(
                    self.name, cast(AuthorizationGetRequest, request)
                )
            case "configuration":
                return service.configuration(cast(ConfigurationRequest, request))
            case "observe":
                return service.observe(cast(Any, self.name), cast(Any, request))
            case "lifecycle":
                return service.lifecycle(
                    cast(Any, self.name.removeprefix("environment_")),
                    cast(EnvironmentLifecycleRequest, request),
                )
            case "mutate":
                return service.mutate(cast(Any, self.name), cast(Any, request))


OPERATION_DESCRIPTIONS = {
    "data_deletion_preview": "Read owner-discovered deletion targets for Creator (no party key) or one other person; prepare a concrete authorization request without deleting data.",
    "data_deletion_apply": "Apply one Creator-authorized deletion scope; revalidate current owner targets and return the governed order and execution status.",
    "authorization_get": "Read the exact preview, recipient, expiry and single-use authorization state.",
    "authorization_approve": "Creator issuer only: sign an exact preview digest for one delegated operation; requires a separate signing credential.",
    "authorization_revoke": "Revoke an unconsumed authorization; this does not undo an executed operation.",
    "capabilities": "Discover bound identity, authorization and operation contracts without opening the database.",
    "doctor": "Inspect scoped configuration, schema/ACL, work and channel diagnostics; no device capture or external effects.",
    "invocation_get": "Read a durable receipt by operation and stable idempotency key; unknown outcomes are never replayed.",
    "invocation_wait": "Wait up to 25 seconds for a durable invocation; return current progress and a continuation without replaying it.",
    "configuration": "Read, validate, preview, apply or inspect bound configuration using file versions; saving never implicitly restarts Runtime.",
    "maintenance": "Use fixed database, birth, artifact, capacity, semantic recall and device maintenance actions; downloads require explicit approval.",
    "other_human": "Manage registration, scenes and governed data-rights orders; synthetic message intake is test-only.",
    "health": "Verify bound package, configuration, database and Admin role.",
    "schema_status": "Read authoritative schema and ACL status.",
    "runtime_status": "Read registered environment and authoritative Runtime status.",
    "subject_snapshot": "Read a bounded current subject snapshot within the granted scope.",
    "trace_flow": "Trace one exact operation, episode, effect or trace identity.",
    "inspect_scope": "Inspect a bounded, explicitly allowlisted dependency scope.",
    "tail_diagnostics": "Read bounded redacted diagnostics for the bound environment.",
    "environment_initialize": "Register the configured environment template using the owner initialization path.",
    "environment_reset_preview": "Preview the exact target and impact of a disposable environment reset; this does not authorize applying it.",
    "environment_reset": "Apply an unchanged unexpired reset preview with specific authorization, including an explicitly authorized active environment reset; never infer approval from the preview.",
    "runtime_start": "Start the fixed Runtime entry for the bound environment.",
    "runtime_drain": "Drain the bound Runtime through its authenticated private control endpoint.",
    "runtime_stop": "Stop the drained bound Runtime and retain shared dependencies.",
    "runtime_restart": "Drain, stop and restart the fixed bound Runtime.",
    "inject_creator_input": "Inject formal Creator intake only in an explicitly enabled test environment.",
    "arm_fault": "Arm one allowlisted one-shot fault only in an explicitly enabled test environment.",
    "clear_faults": "Clear armed faults in the bound test Runtime.",
    "preview_correction": "Preview a fixed owner correction without changing authority facts or authorizing its application.",
    "apply_correction": "Apply an unchanged unexpired owner preview; content replacement and deletion require specific authorization.",
    "correction_status": "Resolve a prior correction outcome from authoritative facts.",
    "settle_correction_work": "Settle one registered artifact cleanup responsibility through its owner.",
    **{
        f"environment_{action}": f"{action.capitalize()} the bound environment or selected component; shared dependencies are retained, startup waits for readiness."
        for action in ("start", "stop", "restart", "status")
    },
}


ADMIN_OPERATIONS = (
    AdminOperation("data_deletion_preview", DataDeletionPreviewRequest, "mutate"),
    AdminOperation("data_deletion_apply", DataDeletionApplyRequest, "mutate"),
    AdminOperation("authorization_get", AuthorizationGetRequest, "authorization"),
    AdminOperation(
        "authorization_approve", AuthorizationApproveRequest, "authorization"
    ),
    AdminOperation("authorization_revoke", AuthorizationRevokeRequest, "authorization"),
    AdminOperation("capabilities", HealthRequest, "capabilities"),
    AdminOperation("doctor", DoctorRequest, "observe"),
    AdminOperation("invocation_get", InvocationStatusRequest, "observe"),
    AdminOperation("invocation_wait", InvocationWaitRequest, "observe"),
    AdminOperation("maintenance", MaintenanceRequest, "mutate"),
    AdminOperation("other_human", OtherHumanRequest, "mutate"),
    AdminOperation("configuration", ConfigurationRequest, "configuration"),
    AdminOperation("health", HealthRequest, "health"),
    AdminOperation("schema_status", SchemaStatusRequest, "schema"),
    AdminOperation("runtime_status", RuntimeStatusRequest, "observe"),
    AdminOperation("subject_snapshot", SubjectSnapshotRequest, "observe"),
    AdminOperation("trace_flow", TraceFlowRequest, "observe"),
    AdminOperation("inspect_scope", InspectScopeRequest, "observe"),
    AdminOperation("tail_diagnostics", TailDiagnosticsRequest, "observe"),
    AdminOperation("environment_initialize", EnvironmentInitializeRequest, "mutate"),
    AdminOperation(
        "environment_reset_preview", EnvironmentResetPreviewRequest, "mutate"
    ),
    AdminOperation("environment_reset", EnvironmentResetRequest, "mutate"),
    AdminOperation("runtime_start", RuntimeControlRequest, "mutate"),
    AdminOperation("runtime_drain", RuntimeControlRequest, "mutate"),
    AdminOperation("runtime_stop", RuntimeControlRequest, "mutate"),
    AdminOperation("runtime_restart", RuntimeControlRequest, "mutate"),
    AdminOperation("inject_creator_input", InjectCreatorInputRequest, "mutate"),
    AdminOperation("arm_fault", ArmFaultRequest, "mutate"),
    AdminOperation("clear_faults", ClearFaultsRequest, "mutate"),
    AdminOperation("preview_correction", PreviewCorrectionRequest, "mutate"),
    AdminOperation("apply_correction", ApplyCorrectionRequest, "mutate"),
    AdminOperation("correction_status", CorrectionStatusRequest, "observe"),
    AdminOperation("settle_correction_work", SettleCorrectionWorkRequest, "mutate"),
    *(
        AdminOperation(
            f"environment_{action}", EnvironmentLifecycleRequest, "lifecycle"
        )
        for action in ("start", "stop", "restart", "status")
    ),
)


__all__ = ("ADMIN_OPERATIONS", "AdminOperation")
