"""Administrative application service shared by CLI and MCP."""

from __future__ import annotations

import base64
import hashlib
import json
import stat
import time
from collections.abc import Callable
from contextlib import nullcontext
from datetime import UTC, datetime
from typing import Any, Literal, cast
from uuid import uuid7

from armi_kernel.application import CredentialPurpose
from armi_local_control import ConfigurationViolation, environment_control_root
from armi_local_control.configuration.defaults import runtime_defaults_file
from armi_local_control.configuration.editing import (
    EnvironmentConfiguration,
    verify_write,
    write_identity,
)
from armi_local_control.lifecycle import (
    LocalEnvironmentController,
    environment_control_lock,
)
from armi_local_control.maintenance import (
    ConfigurationInvocation,
    MaintenanceInvocation,
    MaintenanceParameters,
)
from armi_local_control.runtime_errors import RuntimeViolation
from psycopg import Error as PostgreSQLError
from pydantic import BaseModel, JsonValue

from armi_admin.application import (
    AdminConfig,
    AdminControlError,
    AdminControlPlane,
    AdminCorrectionCoordinator,
    AdminCorrectionError,
    AdminCredentialPort,
)
from armi_admin.persistence import (
    AdminObservationGateway,
    AdminRoleSessionError,
    AdminSchemaGateway,
    AdminSchemaSnapshot,
)
from armi_admin.persistence.role_session import AdminRoleBoundPool

from .authorization import AuthorizationError, AuthorizationStore
from .configuration_activation import asset_activation, runtime_activation
from .contracts import (
    AdminIdentity,
    AdminMutationRequest,
    AdminToolResult,
    ApplyCorrectionRequest,
    ArmFaultRequest,
    AuthorizationApproveRequest,
    AuthorizationGetRequest,
    ConfigurationRequest,
    CorrectionStatusRequest,
    DataDeletionApplyRequest,
    DataDeletionPreviewRequest,
    EnvironmentInitializeRequest,
    EnvironmentLifecycleRequest,
    EnvironmentResetRequest,
    HealthPayload,
    HealthRequest,
    HealthResult,
    InjectCreatorInputRequest,
    InspectScopeRequest,
    InvocationStatusRequest,
    InvocationWaitRequest,
    MaintenanceRequest,
    ObservationRequest,
    OtherHumanRequest,
    PreviewCorrectionRequest,
    RuntimeControlRequest,
    SchemaStatusPayload,
    SchemaStatusRequest,
    SchemaStatusResult,
    SettleCorrectionWorkRequest,
    SubjectSnapshotRequest,
    TailDiagnosticsRequest,
    TraceFlowRequest,
)
from .credentials import AdminSecretError
from .invocations import (
    InvocationEvidence,
    InvocationJournal,
    InvocationReferences,
    invocation_completed_step,
    invocation_launch_identity,
    invocation_progress,
)

_DIAGNOSTIC_TOTAL_BYTES = 2 * 1024 * 1024
_DIAGNOSTIC_LINE_BYTES = 64 * 1024
ObservationToolName = Literal[
    "invocation_get",
    "invocation_wait",
    "invocation_reconcile",
    "doctor",
    "correction_status",
    "inspect_scope",
    "runtime_status",
    "subject_snapshot",
    "tail_diagnostics",
    "trace_flow",
]
MutationToolName = Literal[
    "data_deletion_preview",
    "data_deletion_apply",
    "other_human",
    "maintenance",
    "apply_correction",
    "arm_fault",
    "clear_faults",
    "environment_initialize",
    "environment_reset",
    "environment_reset_preview",
    "inject_creator_input",
    "preview_correction",
    "runtime_drain",
    "runtime_restart",
    "runtime_start",
    "runtime_stop",
    "settle_correction_work",
]


def _sha256(value: bytes) -> str:
    return f"sha256:{hashlib.sha256(value).hexdigest()}"


class AdminToolService:
    __slots__ = (
        "_config",
        "_control",
        "_corrections",
        "_credentials",
        "_identity",
        "_observation",
        "_pool",
        "_requires_reload",
    )

    def __init__(
        self,
        *,
        config: AdminConfig,
        credentials: AdminCredentialPort,
        control: AdminControlPlane,
        corrections: AdminCorrectionCoordinator,
        observation: AdminObservationGateway,
        pool: AdminRoleBoundPool,
    ) -> None:
        self._config = config
        self._credentials = credentials
        self._control = control
        self._corrections = corrections
        self._observation = observation
        self._pool = pool
        self._requires_reload = False
        self._identity = AdminIdentity()

    @property
    def config(self) -> AdminConfig:
        return self._config

    def capabilities(self) -> AdminToolResult[dict[str, Any]]:
        from .catalog import ADMIN_OPERATIONS

        try:
            runtime_status = self._control.runtime_status().get("status", "unknown")
        except AdminControlError, RuntimeViolation, OSError, ValueError:
            runtime_status = "unknown"
        runtime_required = {
            "inject_creator_input",
            "arm_fault",
            "clear_faults",
            "other_human",
            "data_deletion_preview",
            "data_deletion_apply",
            "runtime_drain",
        }

        def authorized(name: str) -> bool:
            return (
                name == "capabilities"
                or name in self._config.authorized_operations
                or any(
                    scope.startswith(name + ".")
                    for scope in self._config.authorized_operations
                )
            )

        def unavailable(name: str) -> str | None:
            if not authorized(name):
                return "scope_not_granted"
            if (
                name in {"arm_fault", "clear_faults", "inject_creator_input"}
                and not self._config.test_controls_enabled
            ):
                return "test_controls_disabled"
            if name in runtime_required and runtime_status != "running":
                return "runtime_" + str(runtime_status)
            if (
                name == "data_deletion_apply"
                and self._config.authorization_public_key is None
            ):
                return "authorization_not_configured"
            return None

        return self._tool_success(
            datetime.now(UTC),
            {
                "environment_id": self._config.environment_id,
                "environment_kind": self._config.environment_kind.value,
                "operator_id": self._config.operator_id,
                "package_set_digest": self._config.expected.package_set_digest,
                "authorized_operations": list(self._config.authorized_operations),
                "runtime_status": runtime_status,
                "database_status": "not_checked",
                "operations": [
                    {
                        "name": operation.name,
                        "description": operation.description,
                        "request_schema": operation.request.model_json_schema(),
                        "result_schema": operation.result.model_json_schema(),
                        "read_only": operation.read_only,
                        "destructive": operation.destructive,
                        "conditional_scopes": {
                            "detail=private": "subject_snapshot.private"
                        }
                        if operation.name == "subject_snapshot"
                        else {},
                        "authorized": authorized(operation.name),
                        "requires_runtime": operation.name in runtime_required,
                        "unavailable_reason": unavailable(operation.name),
                        "availability": "unavailable"
                        if unavailable(operation.name)
                        else "available"
                        if operation.name == "capabilities"
                        else "not_verified",
                        "suboperations": [
                            {
                                **variant,
                                "authorized": variant["required_scope"]
                                in self._config.authorized_operations,
                            }
                            for variant in operation.suboperations()
                        ],
                    }
                    for operation in ADMIN_OPERATIONS
                ],
            },
        )

    def authorization(
        self, name: str, request: AuthorizationGetRequest
    ) -> AdminToolResult[dict[str, Any]]:
        started = datetime.now(UTC)
        if name not in self._config.authorized_operations:
            return self._tool_failure(started, "rejected", "ADMIN-SCOPE-REQUIRED")
        if request.environment_id != self._config.environment_id:
            return self._tool_failure(started, "rejected", "ADMIN-ENVIRONMENT-MISMATCH")

        def execute() -> AdminToolResult[dict[str, Any]]:
            store = AuthorizationStore(self._config, self._credentials)
            try:
                if name == "authorization_get":
                    result = store.get(request.request_id)
                elif name == "authorization_approve":
                    result = store.approve(
                        request.request_id,
                        cast(
                            AuthorizationApproveRequest, request
                        ).expected_request_digest,
                    )
                elif name == "authorization_revoke":
                    result = store.revoke(request.request_id)
                else:
                    raise AuthorizationError("ADMIN-AUTHORIZATION-OPERATION")
                return self._tool_success(started, result)
            except AuthorizationError as error:
                return self._tool_failure(started, "rejected", str(error))
            except OSError, ValueError, AdminSecretError:
                return self._tool_failure(
                    started, "failed", "ADMIN-AUTHORIZATION-UNAVAILABLE"
                )

        return (
            execute()
            if name == "authorization_get"
            else self._write(name, request, name, execute)
        )

    def configuration(
        self, request: ConfigurationRequest
    ) -> AdminToolResult[dict[str, Any]]:
        started = datetime.now(UTC)
        if f"configuration.{request.action}" not in self._config.authorized_operations:
            return self._tool_failure(started, "rejected", "ADMIN-SCOPE-REQUIRED")
        if request.environment_id != self._config.environment_id:
            return self._tool_failure(started, "rejected", "ADMIN-ENVIRONMENT-MISMATCH")
        if self._requires_reload:
            return self._tool_failure(
                started, "conflict", "ADMIN-CONFIG-RELOAD-REQUIRED"
            )
        if request.action == "apply":
            return self._write(
                "configuration",
                request,
                "configuration.apply",
                lambda: self._configuration_once(request),
            )
        return self._configuration_once(request)

    def _configuration_once(
        self, request: ConfigurationRequest
    ) -> AdminToolResult[dict[str, Any]]:
        if request.action == "apply":
            try:
                with environment_control_lock(
                    self._config.environment_root, self._config.environment_id
                ):
                    return self._configuration_execute(request)
            except RuntimeViolation as error:
                return self._tool_failure(datetime.now(UTC), "conflict", error.code)
        return self._configuration_execute(request)

    def _configuration_execute(
        self, request: ConfigurationRequest
    ) -> AdminToolResult[dict[str, Any]]:
        started = datetime.now(UTC)
        try:
            editor = EnvironmentConfiguration(
                self._config.environment_root,
                self._config.runtime_defaults_path or runtime_defaults_file(),
                environment_id=self._config.environment_id,
            )
            if request.target != "runtime":
                result = self._control.maintenance(
                    ConfigurationInvocation.model_validate(
                        {
                            "environment_root": self._config.environment_root,
                            "environment_id": self._config.environment_id,
                            "target": request.target,
                            "action": request.action,
                            "patch": dict(request.patch),
                            "document": request.document,
                            "expected_version": request.expected_version,
                            "write_id": write_identity(
                                self._config.invocation_identity(),
                                request.idempotency_key,
                            )
                            if request.action == "apply" and request.idempotency_key
                            else None,
                        }
                    )
                )
                if (
                    request.action == "status"
                    and result.get("configuration_state") != "invalid"
                ):
                    runtime = self._control.runtime_status()
                    result.update(
                        asset_activation(
                            runtime,
                            request.target,
                            result.get("desired_source_version"),
                        )
                    )
            elif request.action in {"read", "status"}:
                result = editor.read()
                if (
                    request.action == "status"
                    and result["configuration_state"] != "invalid"
                ):
                    from armi_local_control.runtime_process import RuntimeProcessManager

                    runtime = RuntimeProcessManager(
                        self._config.environment_root, self._config.environment_id
                    ).status()
                    result.update(runtime_activation(runtime, result))
            else:
                if request.expected_version is None:
                    return self._tool_failure(
                        started, "rejected", "ADMIN-CONFIG-VERSION-REQUIRED"
                    )
                result = (
                    editor.apply(
                        dict(request.patch),
                        request.expected_version,
                        document=request.document,
                        write_id=write_identity(
                            self._config.invocation_identity(), request.idempotency_key
                        )
                        if request.idempotency_key
                        else None,
                    )
                    if request.action == "apply"
                    else editor.preview(
                        dict(request.patch),
                        request.expected_version,
                        document=request.document,
                    )
                )
        except AdminControlError as error:
            return self._tool_failure(started, "rejected", str(error))
        except RuntimeViolation as error:
            return self._tool_failure(started, "failed", error.code)
        except ConfigurationViolation as error:
            return self._tool_failure(started, "rejected", error.code)
        except ValueError as error:
            code = str(error)
            return self._tool_failure(
                started,
                "rejected",
                code if code.startswith("ADMIN-CONFIG-") else "ADMIN-CONFIG-INVALID",
            )
        except OSError:
            return self._tool_failure(started, "failed", "ADMIN-CONFIG-UNAVAILABLE")
        return self._tool_success(started, result)

    def lifecycle(
        self,
        action: Literal["start", "stop", "restart", "status"],
        request: EnvironmentLifecycleRequest,
    ) -> AdminToolResult[dict[str, Any]]:
        started = datetime.now(UTC)
        if f"environment_{action}" not in self._config.authorized_operations:
            return self._tool_failure(started, "rejected", "ADMIN-SCOPE-REQUIRED")
        if (
            request.environment_id != self._config.environment_id
            or request.environment_incarnation != self._config.environment_incarnation
        ):
            return self._tool_failure(started, "rejected", "ADMIN-ENVIRONMENT-MISMATCH")
        if request.purpose != f"admin.environment_{action}":
            return self._tool_failure(started, "rejected", "ADMIN-PURPOSE")
        if self._requires_reload:
            return self._tool_failure(
                started, "conflict", "ADMIN-CONFIG-RELOAD-REQUIRED"
            )
        if action != "status":
            return self._write(
                f"environment_{action}",
                request,
                f"environment_{action}",
                lambda: self._lifecycle_once(action, request),
            )
        return self._lifecycle_once(action, request)

    def _lifecycle_once(
        self,
        action: Literal["start", "stop", "restart", "status"],
        request: EnvironmentLifecycleRequest,
    ) -> AdminToolResult[dict[str, Any]]:
        started = datetime.now(UTC)
        try:
            controller = self._environment_controller()
            result = controller.execute(action, component=request.component)
        except RuntimeViolation as error:
            return self._tool_failure(
                started,
                "unknown" if error.code.endswith("UNKNOWN") else "failed",
                error.code,
            )
        except OSError, ValueError:
            return self._tool_failure(started, "failed", "ADMIN-LIFECYCLE-UNAVAILABLE")
        if result.get("status") == "not_ready":
            return AdminToolResult[dict[str, Any]](
                operation_id=str(uuid7()),
                status="failed",
                result=result,
                error_code="ADMIN-RUNTIME-NOT-READY",
                started_at=started.isoformat(),
                ended_at=datetime.now(UTC).isoformat(),
            )
        return self._tool_success(started, result)

    def _environment_controller(
        self, expected_instance_id: str | None = None
    ) -> LocalEnvironmentController:
        return LocalEnvironmentController(
            environment_root=self._config.environment_root,
            environment_id=self._config.environment_id,
            incarnation=self._config.environment_incarnation,
            defaults_path=self._config.runtime_defaults_path or runtime_defaults_file(),
            postgresql=self._config.postgresql_control,
            creator_web_resources=self._config.creator_web_resources,
            database_probe=self._database_probe,
            progress=invocation_progress,
            completed_step=invocation_completed_step,
            launch_instance_id=invocation_launch_identity(),
            expected_instance_id=expected_instance_id,
        )

    def _database_probe(self) -> dict[str, Any]:
        health = self.health(HealthRequest())
        payload = health.result
        return {
            "reachability": "reachable"
            if payload is not None and payload.database_reachable
            else "unavailable"
            if health.error_code != "ADMIN-SCOPE-REQUIRED"
            else "not_authorized",
            "error_code": health.error_code,
            "role_status": None if payload is None else payload.role_status,
        }

    def health(self, request: HealthRequest) -> HealthResult:
        del request
        started = datetime.now(UTC)
        if "health" not in self._config.authorized_operations:
            return self._health_result(
                started,
                status="rejected",
                payload_status="misconfigured",
                role_status="rejected",
                code="ADMIN-SCOPE-REQUIRED",
            )
        if self._requires_reload:
            return self._health_result(
                started,
                status="rejected",
                payload_status="misconfigured",
                role_status="rejected",
                code="ADMIN-CONFIG-RELOAD-REQUIRED",
            )
        try:
            snapshot = self._read_snapshot()
            self._validate_database_identity(snapshot)
            return self._health_result(
                started,
                status="succeeded",
                payload_status="healthy",
                role_status="verified",
                code=None,
            )
        except AdminRoleSessionError:
            return self._health_result(
                started,
                status="rejected",
                payload_status="misconfigured",
                role_status="rejected",
                code="ADMIN-DB-ROLE",
            )
        except ValueError as exc:
            code = str(exc)
            if not code.startswith("ADMIN-DB-"):
                code = "ADMIN-DB-IDENTITY"
            return self._health_result(
                started,
                status="rejected",
                payload_status="misconfigured",
                role_status="rejected",
                code=code,
            )
        except Exception:
            return self._health_result(
                started,
                status="failed",
                payload_status="unavailable",
                role_status="unavailable",
                code="ADMIN-DB-UNAVAILABLE",
            )

    def schema_status(self, request: SchemaStatusRequest) -> SchemaStatusResult:
        started = datetime.now(UTC)
        if "schema_status" not in self._config.authorized_operations:
            return self._schema_result(
                started,
                outer_status="rejected",
                status="unavailable",
                table_count=0,
                missing_tables=(),
                code="ADMIN-SCOPE-REQUIRED",
            )
        if self._requires_reload:
            return self._schema_result(
                started,
                outer_status="rejected",
                status="unavailable",
                table_count=0,
                missing_tables=(),
                code="ADMIN-CONFIG-RELOAD-REQUIRED",
            )
        if request.environment_id != self._config.environment_id:
            return self._schema_result(
                started,
                outer_status="rejected",
                status="unavailable",
                table_count=0,
                missing_tables=(),
                code="ADMIN-ENVIRONMENT-MISMATCH",
            )
        try:
            snapshot = self._read_snapshot()
            self._validate_database_identity(snapshot)
            return self._schema_result_from_payload(
                started, self._classify_schema(snapshot)
            )
        except AdminRoleSessionError:
            code = "ADMIN-DB-ROLE"
        except ValueError as exc:
            code = str(exc)
            if not code.startswith("ADMIN-DB-"):
                code = "ADMIN-DB-IDENTITY"
        except Exception:
            code = "ADMIN-DB-UNAVAILABLE"
        return self._schema_result(
            started,
            outer_status="failed",
            status="unavailable",
            table_count=0,
            missing_tables=(),
            code=code,
        )

    def observe(
        self, name: ObservationToolName, request: ObservationRequest
    ) -> AdminToolResult[dict[str, Any]]:
        started = datetime.now(UTC)
        if name not in self._config.authorized_operations:
            return self._tool_failure(started, "rejected", "ADMIN-SCOPE-REQUIRED")
        if (
            name == "subject_snapshot"
            and cast(SubjectSnapshotRequest, request).detail == "private"
            and "subject_snapshot.private" not in self._config.authorized_operations
        ):
            return self._tool_failure(
                started, "rejected", "ADMIN-PRIVATE-SCOPE-REQUIRED"
            )
        if self._requires_reload:
            return self._tool_failure(
                started, "conflict", "ADMIN-CONFIG-RELOAD-REQUIRED"
            )
        if request.environment_id != self._config.environment_id:
            return self._tool_failure(started, "rejected", "ADMIN-ENVIRONMENT-MISMATCH")
        try:
            if name in {"invocation_get", "invocation_wait", "invocation_reconcile"}:
                typed_invocation = cast(InvocationStatusRequest, request)
                journal = InvocationJournal(
                    environment_control_root(
                        self._config.environment_root, self._config.environment_id
                    ),
                    self._config.invocation_identity(),
                )
                result = journal.read(
                    typed_invocation.operation_name, typed_invocation.idempotency_key
                )
                if (
                    result["state"] != "not_found"
                    and result.get("audit", {}).get("scope")
                    not in self._config.authorized_operations
                ):
                    return self._tool_failure(
                        started, "rejected", "ADMIN-SCOPE-REQUIRED"
                    )
                if name == "invocation_reconcile":
                    result = journal.reconcile(
                        typed_invocation.operation_name,
                        typed_invocation.idempotency_key,
                        authorized_scopes=self._config.authorized_operations,
                        observe=self._reconcile_invocation,
                    )
                elif name == "invocation_wait":
                    deadline = (
                        time.monotonic()
                        + cast(InvocationWaitRequest, request).timeout_seconds
                    )
                    while result["state"] == "running" and time.monotonic() < deadline:
                        time.sleep(min(0.25, max(0, deadline - time.monotonic())))
                        result = journal.read(
                            typed_invocation.operation_name,
                            typed_invocation.idempotency_key,
                        )
                    result = {
                        **result,
                        "wait_timed_out": result["state"] == "running",
                        "continuation": {
                            "operation_name": typed_invocation.operation_name,
                            "idempotency_key": typed_invocation.idempotency_key,
                        },
                    }
            elif name == "doctor":
                result = self._diagnose()
            elif name == "correction_status":
                typed = cast(CorrectionStatusRequest, request)
                result = self._corrections.status(str(typed.preview_token))
            elif name == "tail_diagnostics":
                typed_tail = cast(TailDiagnosticsRequest, request)
                result = self._tail_diagnostics(
                    runtime_instance_id=typed_tail.runtime_instance_id,
                    limit=int(typed_tail.limit),
                    cursor=typed_tail.cursor,
                )
            else:
                gateway = self._observation
                if name == "runtime_status":
                    result = self._control.runtime_status()
                elif name == "subject_snapshot":
                    typed_snapshot = cast(SubjectSnapshotRequest, request)
                    result = gateway.subject_snapshot(
                        private=typed_snapshot.detail == "private"
                    )
                elif name == "trace_flow":
                    typed_trace = cast(TraceFlowRequest, request)
                    selector = next(
                        (key, value)
                        for key in (
                            "interaction_id",
                            "operation_id",
                            "episode_id",
                            "effect_id",
                            "trace_id",
                        )
                        if (value := getattr(typed_trace, key)) is not None
                    )
                    result = gateway.trace_flow(
                        selector,
                        limit=int(typed_trace.limit),
                        cursor=typed_trace.cursor,
                    )
                elif name == "inspect_scope":
                    typed_scope = cast(InspectScopeRequest, request)
                    result = gateway.inspect_scope(
                        str(typed_scope.kind),
                        tuple(typed_scope.object_ids),
                        relations=tuple(typed_scope.relations),
                        limit=int(typed_scope.limit),
                        cursor=typed_scope.cursor,
                    )
                else:
                    raise ValueError("ADMIN-OBSERVATION-OPERATION")
            return self._tool_success(started, result)
        except AdminCorrectionError as exc:
            return self._correction_failure(started, exc.code)
        except RuntimeViolation as exc:
            return self._tool_failure(
                started,
                "conflict" if exc.code == "CLI-RUNTIME-CONTROL-BUSY" else "failed",
                exc.code,
            )
        except Exception:
            return self._tool_failure(started, "failed", "ADMIN-OBSERVATION-FAILED")

    def _reconcile_invocation(
        self, evidence: InvocationEvidence
    ) -> tuple[dict[str, Any] | None, dict[str, Any]]:
        with environment_control_lock(
            self._config.environment_root, self._config.environment_id
        ):
            return self._reconcile_invocation_facts(evidence)

    def _reconcile_invocation_facts(
        self, evidence: InvocationEvidence
    ) -> tuple[dict[str, Any] | None, dict[str, Any]]:
        refs = evidence.references
        if evidence.operation == "data_deletion_apply":
            observed = self._control.send_control(
                "data_deletion",
                {
                    "action": "reconcile",
                    "party_key": refs.deletion_party_key,
                    "idempotency_key": evidence.idempotency_key,
                },
            )["result"]
            order = observed["order"]
            return (
                None
                if order is None
                else self._tool_success(datetime.now(UTC), order).model_dump(
                    mode="json"
                )
            ), {
                "basis": "owner_deletion_request",
                "next_operations": ["other_human", "invocation_get"],
            }
        if evidence.operation in {
            "environment_start",
            "environment_stop",
            "environment_restart",
            "runtime_start",
            "runtime_stop",
            "runtime_restart",
        }:
            action = "stop" if evidence.operation.endswith("_stop") else "start"
            component = refs.component or (
                "runtime"
                if evidence.operation.startswith("runtime_")
                else "environment"
            )
            steps = dict(evidence.completed_steps)
            basis = "recorded_steps"
            if (
                action == "start"
                and component in {"runtime", "environment"}
                and "runtime.readiness" not in steps
                and refs.launch_instance_id
            ):
                current = self._control.runtime_status()
                runtime = current.get("runtime", {})
                if (
                    current.get("status") == "running"
                    and runtime.get("instance_id") == refs.launch_instance_id
                    and runtime.get("readiness") == "ready"
                ):
                    steps["runtime.readiness"] = {
                        **current,
                        "status": "started",
                        "readiness": "ready",
                    }
                    basis = "preidentified_runtime"
            required: tuple[str, ...] = (
                (
                    "postgresql." + action,
                    "semantic." + action,
                    "runtime.readiness" if action == "start" else "runtime.stop",
                )
                if component == "environment"
                else (
                    "runtime.readiness"
                    if component == "runtime" and action == "start"
                    else ("semantic" if component == "semantic-recall" else component)
                    + "."
                    + action,
                )
            )
            if all(phase in steps for phase in required):
                final = steps[required[-1]]
                confirmed = (
                    final.get("readiness") == "ready"
                    if action == "start" and component in {"environment", "runtime"}
                    else final.get("status")
                    in {"stopped", "running", "already_running", "disabled", "started"}
                    or final.get("action") == "not_managed"
                )
                if confirmed:
                    payload = (
                        {
                            "runtime": final,
                            "postgresql": steps[required[0]],
                            "semantic_recall": steps["semantic." + action],
                            **({"status": "ready"} if action == "start" else {}),
                        }
                        if component == "environment"
                        else final
                    )
                    return self._tool_success(datetime.now(UTC), payload).model_dump(
                        mode="json"
                    ), {
                        "basis": basis,
                        "next_operations": ["environment_status"],
                    }
        if evidence.operation == "apply_correction" and refs.preview_token is not None:
            observed = self._corrections.status(refs.preview_token)
            if observed["status"] == "applied":
                return self._tool_success(
                    datetime.now(UTC), {**observed, "reconciled": True}
                ).model_dump(mode="json"), {
                    "basis": "owner_correction",
                    "observed": observed,
                }
            return None, {"basis": "owner_correction", "observed": observed}
        if (
            evidence.operation == "configuration"
            and refs.configuration_target is not None
        ):
            if refs.configuration_write_id and refs.expected_version:
                relative = {
                    "runtime": "environment.yaml",
                    "model-bindings": "configs/model-bindings.yaml",
                    "web-search": "configs/web-search.yaml",
                    "qq": "channels/qq-napcat.yaml",
                    "mood-display": "devices/mood-display.yaml",
                }[refs.configuration_target]
                version = verify_write(
                    self._config.environment_root,
                    self._config.environment_id,
                    refs.configuration_write_id,
                    target=self._config.environment_root / relative,
                    expected_version=refs.expected_version,
                )
                if version is not None:
                    return self._tool_success(
                        datetime.now(UTC),
                        {
                            "version": version,
                            "activation": "saved",
                            "restart_required": False,
                        },
                    ).model_dump(mode="json"), {
                        "basis": "configuration_file_identity",
                        "next_operations": ["configuration"],
                    }
            result = self._configuration_once(
                ConfigurationRequest(
                    environment_id=self._config.environment_id,
                    action="status",
                    target=refs.configuration_target,
                )
            )
            return None, {
                "basis": "current_configuration_only",
                "observed": {
                    "status": result.status,
                    "error_code": result.error_code,
                    "version": (result.result or {}).get("version"),
                    "activation": (result.result or {}).get("activation"),
                },
                "reason": "Current bytes do not prove which invocation wrote them.",
            }
        if evidence.operation.startswith(("environment_", "runtime_")):
            return None, {
                "basis": "current_process_state_only",
                "observed": self._environment_controller().execute("status"),
                "reason": "Current process state alone does not prove the original outcome.",
            }
        return None, {
            "basis": "insufficient_evidence",
            "next_operations": ["trace_flow", "inspect_scope"],
        }

    def _diagnose(self) -> dict[str, Any]:
        checks: list[dict[str, Any]] = []
        for purpose, locator, scopes in (
            ("database.admin", self._config.locator, ("health", "schema_status")),
            (
                "database.migrator",
                self._config.migrator_locator,
                (
                    "maintenance.database_install",
                    "maintenance.database_check",
                    "maintenance.database_maintain",
                ),
            ),
            (
                "admin.correction.preview",
                self._config.preview_locator,
                ("preview_correction", "apply_correction", "correction_status"),
            ),
        ):
            permitted = any(
                scope in self._config.authorized_operations for scope in scopes
            )
            code: str | None = None
            status = "not_authorized"
            if permitted:
                try:
                    with self._credentials.resolve(locator, CredentialPurpose(purpose)):
                        status = "observed"
                except AdminSecretError:
                    status, code = "unavailable", "ADMIN-SECRET-UNAVAILABLE"
            checks.append(
                {
                    "component": "credential." + purpose,
                    "status": status,
                    "error_code": code,
                    "evidence": {
                        "locator": locator.identity(),
                        "resolvable": status == "observed",
                    },
                    "next_operations": list(scopes),
                }
            )
        health = self.health(HealthRequest())
        checks.append(
            {
                "component": "database_identity_and_credentials",
                "status": health.status,
                "error_code": health.error_code,
                "evidence": health.model_dump(mode="json"),
                "next_operations": ["health", "schema_status"],
            }
        )
        schema = self.schema_status(
            SchemaStatusRequest(environment_id=self._config.environment_id)
        )
        owner_diagnostics: dict[str, object] = {}
        if schema.status == "succeeded":
            try:
                owner_diagnostics = self._observation.diagnostics()
                checks.append(
                    {
                        "component": "owner_work_leases_recovery_and_artifacts",
                        "status": "observed",
                        "evidence": owner_diagnostics,
                        "next_operations": [
                            "inspect_scope",
                            "trace_flow",
                            "preview_correction",
                        ],
                    }
                )
            except (
                PostgreSQLError,
                AdminRoleSessionError,
                AdminSecretError,
                OSError,
                ValueError,
            ):
                checks.append(
                    {
                        "component": "owner_work_leases_recovery_and_artifacts",
                        "status": "unavailable",
                        "error_code": "ADMIN-DIAGNOSTIC-OWNER-UNAVAILABLE",
                        "next_operations": ["schema_status", "health"],
                    }
                )
        else:
            checks.append(
                {
                    "component": "owner_work_leases_recovery_and_artifacts",
                    "status": "unavailable",
                    "error_code": "ADMIN-DIAGNOSTIC-SCHEMA-REQUIRED",
                    "next_operations": ["schema_status"],
                }
            )
        checks.append(
            {
                "component": "schema_and_acl",
                "status": schema.status,
                "error_code": schema.error_code,
                "evidence": schema.model_dump(mode="json"),
                "next_operations": ["schema_status"],
            }
        )
        config = self.configuration(
            ConfigurationRequest(
                environment_id=self._config.environment_id, action="read"
            )
        )
        checks.append(
            {
                "component": "configuration",
                "status": (config.result or {}).get(
                    "configuration_state", config.status
                ),
                "error_code": config.error_code,
                "evidence": {
                    "operation_id": config.operation_id,
                    "version": (config.result or {}).get("version"),
                },
                "next_operations": ["configuration"],
            }
        )
        for target in ("model-bindings", "web-search", "qq", "mood-display"):
            asset = self.configuration(
                ConfigurationRequest(
                    environment_id=self._config.environment_id,
                    action="read",
                    target=target,
                )
            )
            checks.append(
                {
                    "component": "configuration." + target,
                    "status": (asset.result or {}).get(
                        "configuration_state", asset.status
                    ),
                    "error_code": asset.error_code
                    or (asset.result or {}).get("error_code"),
                    "evidence": {
                        "operation_id": asset.operation_id,
                        "version": (asset.result or {}).get("version"),
                    },
                    "next_operations": ["configuration"],
                }
            )
        for action in (
            "semantic_status",
            "device_bindings",
            "napcat_status",
            "credential_check",
        ):
            maintenance = self.mutate(
                "maintenance",
                MaintenanceRequest.model_validate(
                    {
                        "environment_id": self._config.environment_id,
                        "environment_incarnation": self._config.environment_incarnation,
                        "purpose": "admin.maintenance",
                        "action": action,
                    }
                ),
            )
            checks.append(
                {
                    "component": action,
                    "status": maintenance.status,
                    "error_code": maintenance.error_code,
                    "evidence": maintenance.result,
                    "next_operations": ["maintenance"],
                }
            )
        try:
            runtime = self._control.runtime_status()
            checks.append(
                {
                    "component": "runtime_process_and_readiness",
                    "status": "observed",
                    "evidence": runtime,
                    "next_operations": [
                        "runtime_status",
                        "trace_flow",
                        "inspect_scope",
                        "tail_diagnostics",
                    ],
                }
            )
        except AdminControlError as error:
            checks.append(
                {
                    "component": "runtime_process_and_readiness",
                    "status": "unavailable",
                    "error_code": str(error),
                    "next_operations": [
                        "environment_status",
                        "environment_start",
                        "tail_diagnostics",
                    ],
                }
            )
        return {
            "checks": checks,
            "collection_performed": False,
            "external_effects_dispatched": False,
            "artifact_integrity": owner_diagnostics.get(
                "artifact_integrity",
                {
                    "status": "unavailable",
                    "next_operations": ["schema_status", "doctor"],
                },
            ),
        }

    def mutate(
        self, name: MutationToolName, request: AdminMutationRequest
    ) -> AdminToolResult[dict[str, Any]]:
        started = datetime.now(UTC)
        permission = (
            f"other_human.{request.command.action}"
            if isinstance(request, OtherHumanRequest)
            else f"maintenance.{request.action}"
            if isinstance(request, MaintenanceRequest)
            else name
        )
        if permission not in self._config.authorized_operations:
            return self._tool_failure(started, "rejected", "ADMIN-SCOPE-REQUIRED")
        if (
            request.environment_id != self._config.environment_id
            or request.environment_incarnation != self._config.environment_incarnation
        ):
            return self._tool_failure(started, "rejected", "ADMIN-ENVIRONMENT-MISMATCH")
        if request.purpose != f"admin.{name}":
            return self._tool_failure(started, "rejected", "ADMIN-PURPOSE")
        if name in {
            "environment_reset_preview",
            "preview_correction",
            "data_deletion_preview",
        } or (
            isinstance(request, (MaintenanceRequest, OtherHumanRequest))
            and request.read_only
        ):
            return self._mutate_once(name, request)
        return self._write(
            name, request, permission, lambda: self._mutate_once(name, request)
        )

    def _write(
        self,
        name: str,
        request: BaseModel,
        permission: str,
        execute: Callable[[], AdminToolResult[dict[str, Any]]],
    ) -> AdminToolResult[dict[str, Any]]:
        started = datetime.now(UTC)
        key = getattr(request, "idempotency_key", None)
        if key is None:
            return self._tool_failure(started, "rejected", "ADMIN-IDEMPOTENCY-REQUIRED")
        digest = _sha256(
            json.dumps(
                request.model_dump(mode="json"), ensure_ascii=False, sort_keys=True
            ).encode("utf-8")
        )
        journal = InvocationJournal(
            environment_control_root(
                self._config.environment_root, self._config.environment_id
            ),
            self._config.invocation_identity(),
        )
        try:
            result = journal.invoke(
                name=name,
                key=key,
                request_digest=digest,
                references=InvocationReferences(
                    configuration_target=request.target
                    if isinstance(request, ConfigurationRequest)
                    else None,
                    expected_version=getattr(request, "expected_version", None),
                    configuration_write_id=write_identity(
                        self._config.invocation_identity(), key
                    )
                    if isinstance(request, ConfigurationRequest)
                    else None,
                    preview_token=request.preview_token
                    if isinstance(request, ApplyCorrectionRequest)
                    else None,
                    component=request.component
                    if isinstance(request, EnvironmentLifecycleRequest)
                    else None,
                    expected_instance_id=getattr(request, "expected_instance_id", None),
                    launch_instance_id=str(uuid7())
                    if name
                    in {
                        "environment_start",
                        "environment_restart",
                        "runtime_start",
                        "runtime_restart",
                    }
                    else None,
                    deletion_party_key=request.party_key
                    if isinstance(request, DataDeletionApplyRequest)
                    else None,
                ),
                audit={
                    "operator_id": self._config.operator_id,
                    "authorization_ref": getattr(request, "authorization_ref", None),
                    "scope": permission,
                },
                execute=lambda: execute().model_dump(mode="json"),
            )
            return AdminToolResult[dict[str, Any]].model_validate(result)
        except ValueError as error:
            code = str(error)
            return self._tool_failure(
                started,
                "unknown" if code == "ADMIN-INVOCATION-UNKNOWN" else "conflict",
                code if code.startswith("ADMIN-") else "ADMIN-JOURNAL-INVALID",
            )
        except OSError, RuntimeViolation:
            return self._tool_failure(started, "conflict", "ADMIN-INVOCATION-BUSY")

    def _mutate_once(
        self, name: MutationToolName, request: AdminMutationRequest
    ) -> AdminToolResult[dict[str, Any]]:
        started = datetime.now(UTC)
        if request.environment_id != self._config.environment_id:
            return self._tool_failure(started, "rejected", "ADMIN-ENVIRONMENT-MISMATCH")
        if (
            getattr(request, "environment_incarnation", None)
            != self._config.environment_incarnation
        ):
            return self._tool_failure(
                started, "conflict", "ADMIN-ENVIRONMENT-INCARNATION"
            )
        expected_purpose = f"admin.{name}"
        if request.purpose != expected_purpose:
            return self._tool_failure(started, "rejected", "ADMIN-PURPOSE")
        if self._requires_reload:
            return self._tool_failure(
                started, "conflict", "ADMIN-CONFIG-RELOAD-REQUIRED"
            )
        try:
            if name in {"data_deletion_preview", "data_deletion_apply"}:
                deletion = cast(
                    DataDeletionPreviewRequest | DataDeletionApplyRequest, request
                )
                arguments: dict[str, JsonValue] = {"party_key": deletion.party_key}
                if isinstance(deletion, DataDeletionApplyRequest):
                    arguments["scope_digest"] = deletion.scope_digest
                    AuthorizationStore(self._config, self._credentials).consume(
                        deletion.authorization_id,
                        operation=name,
                        arguments=arguments,
                        invocation_key=deletion.idempotency_key,
                    )
                    arguments["idempotency_key"] = deletion.idempotency_key
                result = self._control.send_control(
                    "data_deletion",
                    {
                        "action": "apply"
                        if isinstance(deletion, DataDeletionApplyRequest)
                        else "preview",
                        **arguments,
                    },
                )["result"]
                if isinstance(deletion, DataDeletionPreviewRequest):
                    result["authorization_request"] = (
                        None
                        if self._config.authorization_public_key is None
                        else AuthorizationStore(
                            self._config, self._credentials
                        ).prepare(
                            "data_deletion_apply",
                            {
                                "party_key": deletion.party_key,
                                "scope_digest": result["scope_digest"],
                            },
                            result,
                        )
                    )
                    result["authorization_required"] = True
            elif name == "other_human":
                typed_other = cast(OtherHumanRequest, request)
                action = typed_other.command.action
                if action == "message_send":
                    self._require_test_controls()
                payload = typed_other.command.model_dump(
                    mode="json", exclude={"action"}
                )
                if action in {"message_send", "data_rights_request"}:
                    payload["idempotency_key"] = request.idempotency_key
                result = self._control.send_control(
                    "other_human", {"action": action, "payload": payload}
                )["result"]
            elif name == "maintenance":
                typed_maintenance = cast(MaintenanceRequest, request)
                invocation = MaintenanceInvocation.model_validate(
                    {
                        "environment_root": self._config.environment_root,
                        "environment_id": self._config.environment_id,
                        **typed_maintenance.model_dump(
                            include=set(MaintenanceParameters.model_fields)
                        ),
                    }
                )
                with (
                    nullcontext()
                    if invocation.read_only
                    else environment_control_lock(
                        self._config.environment_root, self._config.environment_id
                    )
                ):
                    invocation_progress("maintenance." + invocation.action)
                    result = self._control.maintenance(invocation)
            elif name == "environment_initialize":
                typed_initialize = cast(EnvironmentInitializeRequest, request)
                with environment_control_lock(
                    self._config.environment_root, self._config.environment_id
                ):
                    result = self._initialize_environment(typed_initialize.birth_mode)
            elif name == "environment_reset_preview":
                result = self._control.preview_reset()
            elif name == "environment_reset":
                typed_reset = cast(EnvironmentResetRequest, request)
                result = self._control.apply_reset(
                    typed_reset.preview_token,
                    authorize=lambda: AuthorizationStore(
                        self._config, self._credentials
                    ).consume(
                        typed_reset.authorization_id,
                        operation=name,
                        arguments={"preview_token": typed_reset.preview_token},
                        invocation_key=typed_reset.idempotency_key,
                    ),
                )
                self._register_environment(int(result["incarnation"]))
                self._requires_reload = True
            elif name == "runtime_start":
                result = self._environment_controller().execute(
                    "start", component="runtime"
                )
            elif name == "runtime_drain":
                result = self._runtime_control(request, "drain")
            elif name == "runtime_stop":
                result = self._environment_controller(
                    cast(RuntimeControlRequest, request).expected_instance_id
                ).execute("stop", component="runtime")
            elif name == "runtime_restart":
                result = self._environment_controller(
                    cast(RuntimeControlRequest, request).expected_instance_id
                ).execute("restart", component="runtime")
            elif name == "inject_creator_input":
                self._require_test_controls()
                typed_input = cast(InjectCreatorInputRequest, request)
                result = self._control.send_control(
                    "input",
                    {
                        "message": str(typed_input.message),
                        "idempotency_key": str(typed_input.idempotency_key),
                    },
                )
            elif name == "arm_fault":
                typed_fault = cast(ArmFaultRequest, request)
                self._require_test_controls()
                result = self._control.send_control(
                    "fault",
                    {
                        "action": "arm",
                        "fault": str(typed_fault.fault),
                        "duration_seconds": int(typed_fault.duration_seconds),
                    },
                )
            elif name == "clear_faults":
                self._require_test_controls()
                result = self._control.send_control("fault", {"action": "clear"})
            elif name == "preview_correction":
                typed_preview = cast(PreviewCorrectionRequest, request)
                result = self._corrections.preview(
                    typed_preview.spec.model_dump(mode="json"),
                    purpose=str(typed_preview.purpose),
                )
            elif name == "apply_correction":
                typed_apply = cast(ApplyCorrectionRequest, request)
                with environment_control_lock(
                    self._config.environment_root, self._config.environment_id
                ):
                    if typed_apply.authorization_id is not None:
                        AuthorizationStore(self._config, self._credentials).consume(
                            typed_apply.authorization_id,
                            operation=name,
                            arguments={
                                "preview_token": typed_apply.preview_token,
                                "spec": typed_apply.spec.model_dump(mode="json"),
                            },
                            invocation_key=typed_apply.idempotency_key,
                        )
                    result = self._corrections.apply(
                        typed_apply.spec.model_dump(mode="json"),
                        str(typed_apply.preview_token),
                        purpose=str(typed_apply.purpose),
                    )
            elif name == "settle_correction_work":
                typed_settle = cast(SettleCorrectionWorkRequest, request)
                result = self._corrections.settle_side_work(
                    str(typed_settle.side_work_id)
                )
            else:
                raise ValueError("ADMIN-OPERATION-UNKNOWN")
            if name == "environment_reset_preview" or (
                isinstance(request, PreviewCorrectionRequest)
                and request.spec.correction_kind
                in {
                    "replace_subject_component",
                    "repair_subject_component_head",
                    "delete_uncommitted_creator_input",
                }
            ):
                arguments: dict[str, JsonValue] = {
                    "preview_token": result["preview_token"]
                }
                if isinstance(request, PreviewCorrectionRequest):
                    arguments["spec"] = request.spec.model_dump(mode="json")
                required_operation = (
                    "environment_reset"
                    if name == "environment_reset_preview"
                    else "apply_correction"
                )
                authorization = (
                    None
                    if self._config.authorization_public_key is None
                    else AuthorizationStore(self._config, self._credentials).prepare(
                        required_operation, arguments, result
                    )
                )
                result = {
                    **result,
                    "authorization_required": True,
                    "authorization_request": authorization,
                    "authorization_unavailable_reason": "signing_authority_not_configured"
                    if authorization is None
                    else None,
                }
            outcome = (
                AdminToolResult[dict[str, Any]](
                    operation_id=str(uuid7()),
                    status="failed",
                    result=result,
                    error_code="ADMIN-RUNTIME-NOT-READY",
                    started_at=started.isoformat(),
                    ended_at=datetime.now(UTC).isoformat(),
                )
                if result.get("status") == "not_ready"
                else self._tool_success(started, result)
            )
        except AuthorizationError as exc:
            outcome = self._tool_failure(started, "rejected", str(exc))
        except AdminCorrectionError as exc:
            outcome = self._correction_failure(started, exc.code)
        except AdminControlError as exc:
            code = str(exc)
            outcome = self._tool_failure(
                started,
                "unknown"
                if code.endswith("-UNKNOWN")
                else "failed"
                if code.endswith("-UNAVAILABLE")
                else "rejected",
                code,
            )
        except Exception:
            outcome = self._tool_failure(started, "failed", "ADMIN-CONTROL-FAILED")
        return outcome

    def _correction_failure(
        self, started: datetime, code: str
    ) -> AdminToolResult[dict[str, Any]]:
        if code == "ADMIN-CORRECTION-COMMIT-UNKNOWN":
            status: Literal["rejected", "conflict", "failed", "unknown"] = "unknown"
        elif code in {
            "ADMIN-CORRECTION-PREVIEW-STALE",
            "ADMIN-CORRECTION-PREVIEW-EXPIRED",
            "ADMIN-CORRECTION-PREVIEW-SESSION",
            "ADMIN-CORRECTION-COMPONENT-VERSION",
            "ADMIN-CORRECTION-RUNTIME-ACTIVE",
            "ADMIN-CORRECTION-COMPONENT-CAS",
            "ADMIN-CORRECTION-WORK-CAS",
            "ADMIN-CORRECTION-EFFECT-CAS",
        }:
            status = "conflict"
        elif code.endswith("-FAILED") or code.endswith("-UNAVAILABLE"):
            status = "failed"
        else:
            status = "rejected"
        return self._tool_failure(started, status, code)

    def _runtime_control(
        self, request: AdminMutationRequest, command: str
    ) -> dict[str, Any]:
        typed = cast(RuntimeControlRequest, request)
        return self._control.send_control(
            command, {}, expected_instance_id=typed.expected_instance_id
        )

    def _read_snapshot(self) -> AdminSchemaSnapshot:
        return AdminSchemaGateway(self._pool).read_snapshot()

    def _initialize_environment(
        self, birth_mode: Literal["unborn", "manifest"]
    ) -> dict[str, Any]:
        initialization = self._control.initialize_environment(birth_mode)
        gateway = self._observation
        existing = gateway.environment()
        if existing is not None:
            if (
                existing["environment_id"] == self._config.environment_id
                and existing["incarnation"] == self._config.environment_incarnation
            ):
                return {
                    **initialization,
                    "environment": existing,
                    "created": False,
                }
            raise AdminControlError("ADMIN-ENVIRONMENT-ALREADY-REGISTERED")
        self._register_environment(self._config.environment_incarnation)
        return {
            **initialization,
            "environment": gateway.environment(),
            "created": True,
        }

    def _register_environment(self, incarnation: int) -> None:
        gateway = self._observation
        values = {
            "environment_id": self._config.environment_id,
            "environment_kind": self._config.environment_kind.value,
            "incarnation": incarnation,
            "resettable": self._config.resettable,
            "test_controls_enabled": self._config.test_controls_enabled,
        }
        gateway.register_environment(values)

    def _tail_diagnostics(
        self,
        *,
        runtime_instance_id: str,
        limit: int,
        cursor: str | None,
    ) -> dict[str, Any]:
        log_root = self._config.environment_root / "data" / "logs"
        if not log_root.is_dir() or log_root.is_symlink():
            return {"events": [], "truncated": False, "cursor": None}
        query_digest = hashlib.sha256(runtime_instance_id.encode("ascii")).hexdigest()
        offset = self._diagnostic_cursor_offset(cursor, query_digest)
        events: list[dict[str, Any]] = []
        allowed = {
            "duration_ms",
            "event",
            "instance_id",
            "level",
            "reason_codes",
            "result_code",
            "sequence",
            "service",
            "timestamp",
        }
        total_bytes = 0
        prefix = f"runtime-{runtime_instance_id}"
        paths = sorted(
            (
                path
                for path in log_root.iterdir()
                if path.name == f"{prefix}.jsonl"
                or (path.name.startswith(f"{prefix}.") and path.name.endswith(".jsonl"))
            ),
            key=lambda path: path.stat().st_mtime_ns,
            reverse=True,
        )
        all_events: list[dict[str, Any]] = []
        budget_exhausted = False
        for path in paths:
            before = path.lstat()
            if (
                not stat.S_ISREG(before.st_mode)
                or path.is_symlink()
                or before.st_nlink != 1
                or getattr(before, "st_file_attributes", 0) & 0x400
            ):
                continue
            remaining = _DIAGNOSTIC_TOTAL_BYTES - total_bytes
            if remaining <= 0:
                budget_exhausted = True
                break
            read_bytes = min(before.st_size, remaining)
            with path.open("rb") as stream:
                stream.seek(max(0, before.st_size - read_bytes))
                data = stream.read(read_bytes)
            after = path.lstat()
            if (
                before.st_dev,
                before.st_ino,
                before.st_size,
                before.st_mtime_ns,
            ) != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns):
                raise RuntimeError("ADMIN-DIAGNOSTIC-FILE-RACE")
            total_bytes += len(data)
            lines = data.splitlines()
            if read_bytes < before.st_size and lines:
                lines = lines[1:]
                budget_exhausted = True
            for raw_line in reversed(lines):
                if len(raw_line) > _DIAGNOSTIC_LINE_BYTES:
                    budget_exhausted = True
                    continue
                try:
                    value = json.loads(raw_line.decode("utf-8"))
                except UnicodeDecodeError, json.JSONDecodeError:
                    continue
                if (
                    isinstance(value, dict)
                    and cast(dict[str, object], value).get("instance_id")
                    == runtime_instance_id
                    and isinstance(cast(dict[str, object], value).get("sequence"), int)
                ):
                    typed_value = cast(dict[str, object], value)
                    all_events.append(
                        {
                            key: typed_value[key]
                            for key in sorted(allowed)
                            if key in typed_value
                        }
                    )
        events = all_events[offset : offset + limit]
        next_offset = offset + len(events)
        truncated = next_offset < len(all_events) or budget_exhausted
        return {
            "events": events,
            "truncated": truncated,
            "cursor": self._diagnostic_cursor(query_digest, next_offset)
            if truncated and events
            else None,
            "bytes_examined": total_bytes,
        }

    @staticmethod
    def _diagnostic_cursor(query_digest: str, offset: int) -> str:
        payload = json.dumps(
            {"offset": offset, "query": query_digest},
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return base64.urlsafe_b64encode(payload).decode("ascii").rstrip("=")

    @staticmethod
    def _diagnostic_cursor_offset(cursor: str | None, query_digest: str) -> int:
        if cursor is None:
            return 0
        try:
            payload = json.loads(
                base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4)).decode(
                    "utf-8"
                )
            )
        except (ValueError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("ADMIN-DIAGNOSTIC-CURSOR") from exc
        if (
            not isinstance(payload, dict)
            or cast(dict[str, object], payload).get("query") != query_digest
            or not isinstance(cast(dict[str, object], payload).get("offset"), int)
            or cast(int, cast(dict[str, object], payload)["offset"]) < 0
        ):
            raise ValueError("ADMIN-DIAGNOSTIC-CURSOR")
        return cast(int, cast(dict[str, object], payload)["offset"])

    def _require_test_controls(self) -> None:
        if not self._config.test_controls_enabled:
            raise AdminControlError("ADMIN-TEST-CONTROLS-DISABLED")

    def _tool_success(
        self, started: datetime, result: dict[str, Any]
    ) -> AdminToolResult[dict[str, Any]]:
        return AdminToolResult[dict[str, Any]](
            operator_id=self._config.operator_id,
            operation_id=str(uuid7()),
            status="succeeded",
            result=result,
            observed_versions={
                "environment_incarnation": self._config.environment_incarnation,
            },
            started_at=started.isoformat().replace("+00:00", "Z"),
            ended_at=datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        )

    def _tool_failure(
        self,
        started: datetime,
        status: Literal["rejected", "conflict", "failed", "unknown"],
        code: str,
    ) -> AdminToolResult[dict[str, Any]]:
        return AdminToolResult[dict[str, Any]](
            operator_id=self._config.operator_id,
            operation_id=str(uuid7()),
            status=status,
            error_code=code,
            observed_versions={
                "environment_incarnation": self._config.environment_incarnation,
            },
            started_at=started.isoformat().replace("+00:00", "Z"),
            ended_at=datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        )

    @staticmethod
    def _validate_database_identity(snapshot: AdminSchemaSnapshot) -> None:
        if (
            snapshot.server_version_num != 180004
            or snapshot.encoding != "UTF8"
            or snapshot.timezone != "UTC"
            or snapshot.revision != "0000"
            or snapshot.baseline_identity != "armi.schema-baseline.v16"
        ):
            raise ValueError("ADMIN-DB-IDENTITY")

    def _classify_schema(self, snapshot: AdminSchemaSnapshot) -> SchemaStatusPayload:
        return SchemaStatusPayload(
            status="current",
            environment_id=self._config.environment_id,
            table_count=len(snapshot.tables),
            revision=snapshot.revision,
            baseline_identity=snapshot.baseline_identity,
            resource_digest=snapshot.resource_digest,
            catalog_digest=snapshot.catalog_digest,
            role_policy_digest=snapshot.role_policy_digest,
        )

    def _health_result(
        self,
        started: datetime,
        *,
        status: Literal["succeeded", "rejected", "failed"],
        payload_status: Literal["healthy", "unavailable", "misconfigured"],
        role_status: Literal["verified", "unavailable", "rejected"],
        code: str | None,
    ) -> HealthResult:
        return HealthResult(
            operation_id=str(uuid7()),
            status=status,
            result=HealthPayload(
                status=payload_status,
                environment_kind=self._environment_kind(),
                environment_id=self._config.environment_id,
                identity=self._identity,
                database_reachable=payload_status != "unavailable",
                role_status=role_status,
                error_code=code,
            ),
            error_code=code,
            observed_versions={
                "environment_incarnation": self._config.environment_incarnation,
                "schema": "current",
            },
            started_at=started.isoformat().replace("+00:00", "Z"),
            ended_at=datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        )

    def _schema_result_from_payload(
        self, started: datetime, payload: SchemaStatusPayload
    ) -> SchemaStatusResult:
        outer_status: Literal["succeeded", "failed"] = (
            "succeeded" if payload.status == "current" else "failed"
        )
        return SchemaStatusResult(
            operation_id=str(uuid7()),
            status=outer_status,
            result=payload,
            error_code=payload.error_code,
            observed_versions={
                "environment_incarnation": self._config.environment_incarnation,
                "schema": payload.status,
            },
            started_at=started.isoformat().replace("+00:00", "Z"),
            ended_at=datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        )

    def _schema_result(
        self,
        started: datetime,
        *,
        outer_status: Literal["rejected", "failed"],
        status: Literal["unavailable"],
        table_count: int,
        missing_tables: tuple[str, ...],
        code: str,
    ) -> SchemaStatusResult:
        payload = SchemaStatusPayload(
            status=status,
            environment_id=self._config.environment_id,
            table_count=table_count,
            missing_tables=missing_tables,
            error_code=code,
        )
        return SchemaStatusResult(
            operation_id=str(uuid7()),
            status=outer_status,
            result=payload,
            error_code=code,
            observed_versions={
                "environment_incarnation": self._config.environment_incarnation,
                "schema": status,
            },
            started_at=started.isoformat().replace("+00:00", "Z"),
            ended_at=datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        )

    def _environment_kind(
        self,
    ) -> Literal["development", "system_test", "acceptance", "active"]:
        return self._config.environment_kind.value


__all__ = ("AdminToolService",)
