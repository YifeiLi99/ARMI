"""Static MCPServer composition root for the local Admin stdio process."""

# pyright: reportUnusedFunction=false

from __future__ import annotations

from typing import Any

from mcp.server import MCPServer
from mcp.types import ToolAnnotations

from .contracts import (
    AdminToolResult,
    AdvanceTestClockRequest,
    ArmFaultRequest,
    ClearFaultsRequest,
    EnvironmentInitializeRequest,
    EnvironmentResetPreviewRequest,
    EnvironmentResetRequest,
    HealthRequest,
    HealthResult,
    InjectCreatorInputRequest,
    InspectScopeRequest,
    RunTestRequest,
    RuntimeControlRequest,
    RuntimeStatusRequest,
    SchemaStatusRequest,
    SchemaStatusResult,
    SubjectSnapshotRequest,
    TailDiagnosticsRequest,
    TraceFlowRequest,
)
from .service import AdminToolService

SERVER_NAME = "armi_admin"
SERVER_VERSION = "0.0.0"
SERVER_INSTRUCTIONS = (
    "Observe and control one explicitly bound disposable ARMI environment. "
    "Never infer another environment, path, command, or credential."
)
READ_ONLY_ANNOTATIONS = ToolAnnotations(
    read_only_hint=True,
    destructive_hint=False,
    idempotent_hint=True,
    open_world_hint=False,
)
CONTROL_ANNOTATIONS = ToolAnnotations(
    read_only_hint=False,
    destructive_hint=False,
    idempotent_hint=True,
    open_world_hint=False,
)
RESET_ANNOTATIONS = ToolAnnotations(
    read_only_hint=False,
    destructive_hint=True,
    idempotent_hint=True,
    open_world_hint=False,
)


def create_admin_server(service: AdminToolService) -> MCPServer:
    """Register the exact S036 catalog without package or entry-point discovery."""

    server = MCPServer(
        name=SERVER_NAME,
        title="ARMI Admin",
        description="Local administration for one disposable ARMI environment.",
        instructions=SERVER_INSTRUCTIONS,
        version=SERVER_VERSION,
        tools=[],
        resources=[],
        extensions=[],
        log_level="ERROR",
    )

    @server.tool(
        name="health",
        description="Verify the bound package, configuration, database, and Admin role.",
        annotations=READ_ONLY_ANNOTATIONS,
        structured_output=True,
    )
    def health(request: HealthRequest) -> HealthResult:  # pyright: ignore[reportUnusedFunction]
        return service.health(request)

    @server.tool(
        name="schema_status",
        description="Read and verify the packaged migration ledger.",
        annotations=READ_ONLY_ANNOTATIONS,
        structured_output=True,
    )
    def schema_status(request: SchemaStatusRequest) -> SchemaStatusResult:  # pyright: ignore[reportUnusedFunction]
        return service.schema_status(request)

    @server.tool(
        name="runtime_status",
        description="Observe the current environment registration and Runtime authority.",
        annotations=READ_ONLY_ANNOTATIONS,
        structured_output=True,
    )
    def runtime_status(
        request: RuntimeStatusRequest,
    ) -> AdminToolResult[dict[str, Any]]:  # pyright: ignore[reportUnusedFunction]
        return service.observe("runtime_status", request)

    @server.tool(
        name="subject_snapshot",
        description="Read a bounded current subject snapshot.",
        annotations=READ_ONLY_ANNOTATIONS,
        structured_output=True,
    )
    def subject_snapshot(
        request: SubjectSnapshotRequest,
    ) -> AdminToolResult[dict[str, Any]]:  # pyright: ignore[reportUnusedFunction]
        return service.observe("subject_snapshot", request)

    @server.tool(
        name="trace_flow",
        description="Trace one exact operation, episode, effect, or trace identity.",
        annotations=READ_ONLY_ANNOTATIONS,
        structured_output=True,
    )
    def trace_flow(request: TraceFlowRequest) -> AdminToolResult[dict[str, Any]]:  # pyright: ignore[reportUnusedFunction]
        return service.observe("trace_flow", request)

    @server.tool(
        name="inspect_scope",
        description="Inspect a bounded allowlisted dependency scope.",
        annotations=READ_ONLY_ANNOTATIONS,
        structured_output=True,
    )
    def inspect_scope(request: InspectScopeRequest) -> AdminToolResult[dict[str, Any]]:  # pyright: ignore[reportUnusedFunction]
        return service.observe("inspect_scope", request)

    @server.tool(
        name="tail_diagnostics",
        description="Read bounded redacted diagnostics for the bound environment.",
        annotations=READ_ONLY_ANNOTATIONS,
        structured_output=True,
    )
    def tail_diagnostics(
        request: TailDiagnosticsRequest,
    ) -> AdminToolResult[dict[str, Any]]:  # pyright: ignore[reportUnusedFunction]
        return service.observe("tail_diagnostics", request)

    @server.tool(
        name="environment_initialize",
        description="Register the configured disposable environment template.",
        annotations=CONTROL_ANNOTATIONS,
        structured_output=True,
    )
    def environment_initialize(
        request: EnvironmentInitializeRequest,
    ) -> AdminToolResult[dict[str, Any]]:  # pyright: ignore[reportUnusedFunction]
        return service.mutate("environment_initialize", request)

    @server.tool(
        name="environment_reset_preview",
        description="Preview a reset of the configured disposable environment.",
        annotations=READ_ONLY_ANNOTATIONS,
        structured_output=True,
    )
    def environment_reset_preview(
        request: EnvironmentResetPreviewRequest,
    ) -> AdminToolResult[dict[str, Any]]:  # pyright: ignore[reportUnusedFunction]
        return service.mutate("environment_reset_preview", request)

    @server.tool(
        name="environment_reset",
        description="Apply one unexpired environment reset preview.",
        annotations=RESET_ANNOTATIONS,
        structured_output=True,
    )
    def environment_reset(
        request: EnvironmentResetRequest,
    ) -> AdminToolResult[dict[str, Any]]:  # pyright: ignore[reportUnusedFunction]
        return service.mutate("environment_reset", request)

    @server.tool(
        name="runtime_start",
        description="Start the fixed Runtime entry for the bound environment.",
        annotations=CONTROL_ANNOTATIONS,
        structured_output=True,
    )
    def runtime_start(
        request: RuntimeControlRequest,
    ) -> AdminToolResult[dict[str, Any]]:  # pyright: ignore[reportUnusedFunction]
        return service.mutate("runtime_start", request)

    @server.tool(
        name="runtime_drain",
        description="Drain the bound Runtime through its private control endpoint.",
        annotations=CONTROL_ANNOTATIONS,
        structured_output=True,
    )
    def runtime_drain(
        request: RuntimeControlRequest,
    ) -> AdminToolResult[dict[str, Any]]:  # pyright: ignore[reportUnusedFunction]
        return service.mutate("runtime_drain", request)

    @server.tool(
        name="runtime_stop",
        description="Stop an already drained bound Runtime.",
        annotations=CONTROL_ANNOTATIONS,
        structured_output=True,
    )
    def runtime_stop(request: RuntimeControlRequest) -> AdminToolResult[dict[str, Any]]:  # pyright: ignore[reportUnusedFunction]
        return service.mutate("runtime_stop", request)

    @server.tool(
        name="runtime_restart",
        description="Drain, stop, and restart the fixed bound Runtime.",
        annotations=CONTROL_ANNOTATIONS,
        structured_output=True,
    )
    def runtime_restart(
        request: RuntimeControlRequest,
    ) -> AdminToolResult[dict[str, Any]]:  # pyright: ignore[reportUnusedFunction]
        return service.mutate("runtime_restart", request)

    @server.tool(
        name="inject_creator_input",
        description="Inject input through the formal Creator intake boundary.",
        annotations=CONTROL_ANNOTATIONS,
        structured_output=True,
    )
    def inject_creator_input(
        request: InjectCreatorInputRequest,
    ) -> AdminToolResult[dict[str, Any]]:  # pyright: ignore[reportUnusedFunction]
        return service.mutate("inject_creator_input", request)

    @server.tool(
        name="advance_test_clock",
        description="Advance only the injected scheduling clock.",
        annotations=CONTROL_ANNOTATIONS,
        structured_output=True,
    )
    def advance_test_clock(
        request: AdvanceTestClockRequest,
    ) -> AdminToolResult[dict[str, Any]]:  # pyright: ignore[reportUnusedFunction]
        return service.mutate("advance_test_clock", request)

    @server.tool(
        name="arm_fault",
        description="Arm one allowlisted one-shot Runtime fault.",
        annotations=CONTROL_ANNOTATIONS,
        structured_output=True,
    )
    def arm_fault(request: ArmFaultRequest) -> AdminToolResult[dict[str, Any]]:  # pyright: ignore[reportUnusedFunction]
        return service.mutate("arm_fault", request)

    @server.tool(
        name="clear_faults",
        description="Clear all armed faults in the bound Runtime.",
        annotations=CONTROL_ANNOTATIONS,
        structured_output=True,
    )
    def clear_faults(request: ClearFaultsRequest) -> AdminToolResult[dict[str, Any]]:  # pyright: ignore[reportUnusedFunction]
        return service.mutate("clear_faults", request)

    @server.tool(
        name="run_test",
        description="Run one static registered conformance scenario.",
        annotations=CONTROL_ANNOTATIONS,
        structured_output=True,
    )
    def run_test(request: RunTestRequest) -> AdminToolResult[dict[str, Any]]:  # pyright: ignore[reportUnusedFunction]
        return service.mutate("run_test", request)

    return server


__all__ = (
    "CONTROL_ANNOTATIONS",
    "READ_ONLY_ANNOTATIONS",
    "RESET_ANNOTATIONS",
    "SERVER_INSTRUCTIONS",
    "SERVER_NAME",
    "SERVER_VERSION",
    "create_admin_server",
)
