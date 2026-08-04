"""Application service behind the static S037 Admin MCP tool catalog."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Any, Literal
from uuid import uuid7

from armi_kernel.application import CredentialPurpose

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

from .contracts import (
    AdminIdentity,
    AdminMutationRequest,
    AdminToolResult,
    AdvanceTestClockRequest,
    ApplyCorrectionRequest,
    ArmFaultRequest,
    CorrectionStatusRequest,
    EnvironmentInitializeRequest,
    EnvironmentResetRequest,
    HealthPayload,
    HealthRequest,
    HealthResult,
    InjectCreatorInputRequest,
    InspectScopeRequest,
    ObservationRequest,
    PreviewCorrectionRequest,
    RunTestRequest,
    RuntimeControlRequest,
    SchemaStatusPayload,
    SchemaStatusRequest,
    SchemaStatusResult,
    SettleCorrectionWorkRequest,
    SubjectSnapshotRequest,
    TailDiagnosticsRequest,
    TraceFlowRequest,
)

_EXPECTED_POSTGRESQL = 180004
_REQUIRED_SCHEMA_TABLES = frozenset(
    {
        "activities",
        "creator_input_interactions",
        "deployment_environments",
        "maintenance_sessions",
        "runtime_instances",
        "subjects",
    }
)


def _sha256(value: bytes) -> str:
    return f"sha256:{hashlib.sha256(value).hexdigest()}"


class AdminToolService:
    __slots__ = (
        "_config",
        "_control",
        "_corrections",
        "_credentials",
        "_identity",
        "_mutation_cache",
        "_requires_reload",
    )

    def __init__(
        self,
        *,
        config: AdminConfig,
        credentials: AdminCredentialPort,
    ) -> None:
        self._config = config
        self._credentials = credentials
        self._control = AdminControlPlane(config, credentials)
        self._corrections = AdminCorrectionCoordinator(
            config, credentials, self._control
        )
        self._mutation_cache: dict[
            tuple[str, str], tuple[str, AdminToolResult[dict[str, Any]]]
        ] = {}
        self._requires_reload = False
        self._identity = AdminIdentity(
            config_digest=config.safe_digest(),
        )

    @property
    def config(self) -> AdminConfig:
        return self._config

    def health(self, request: HealthRequest) -> HealthResult:
        del request
        started = datetime.now(UTC)
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
        self, name: str, request: ObservationRequest
    ) -> AdminToolResult[dict[str, Any]]:
        started = datetime.now(UTC)
        if request.environment_id != self._config.environment_id:
            return self._tool_failure(started, "rejected", "ADMIN-ENVIRONMENT-MISMATCH")
        try:
            if name == "correction_status":
                if not isinstance(request, CorrectionStatusRequest):
                    raise ValueError("ADMIN-INPUT-CONTRACT")
                result = self._corrections.status(str(request.preview_token))
            elif name == "tail_diagnostics":
                if not isinstance(request, TailDiagnosticsRequest):
                    raise ValueError("ADMIN-INPUT-CONTRACT")
                result = self._tail_diagnostics(int(request.limit))
            else:
                gateway = self._observation_gateway()
                if name == "runtime_status":
                    result = gateway.runtime_status()
                elif name == "subject_snapshot":
                    if not isinstance(request, SubjectSnapshotRequest):
                        raise ValueError("ADMIN-INPUT-CONTRACT")
                    result = gateway.subject_snapshot(
                        private=request.detail == "private"
                    )
                elif name == "trace_flow":
                    if not isinstance(request, TraceFlowRequest):
                        raise ValueError("ADMIN-INPUT-CONTRACT")
                    selector = next(
                        (key, value)
                        for key in (
                            "operation_id",
                            "episode_id",
                            "effect_id",
                            "trace_id",
                        )
                        if (value := getattr(request, key)) is not None
                    )
                    result = gateway.trace_flow(selector)
                elif name == "inspect_scope":
                    if not isinstance(request, InspectScopeRequest):
                        raise ValueError("ADMIN-INPUT-CONTRACT")
                    result = gateway.inspect_scope(
                        str(request.kind),
                        tuple(request.object_ids),
                    )
                    result["relations"] = list(request.relations)
                else:
                    raise ValueError("ADMIN-TOOL-NOT-REGISTERED")
            return self._tool_success(started, result)
        except AdminCorrectionError as exc:
            return self._correction_failure(started, str(exc))
        except Exception:
            return self._tool_failure(started, "failed", "ADMIN-OBSERVATION-FAILED")

    def mutate(
        self, name: str, request: AdminMutationRequest
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
        request_digest = _sha256(
            json.dumps(
                request.model_dump(mode="json"),
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            ).encode("utf-8")
        )
        cache_key = (name, request.idempotency_key)
        cached = self._mutation_cache.get(cache_key)
        if cached is not None:
            if cached[0] != request_digest:
                return self._tool_failure(
                    started, "conflict", "ADMIN-IDEMPOTENCY-CONFLICT"
                )
            return cached[1]
        if self._requires_reload:
            return self._tool_failure(
                started, "conflict", "ADMIN-CONFIG-RELOAD-REQUIRED"
            )
        try:
            if name == "environment_initialize":
                if not isinstance(request, EnvironmentInitializeRequest):
                    raise AdminControlError("ADMIN-INPUT-CONTRACT")
                result = self._initialize_environment(request.birth_mode)
            elif name == "environment_reset_preview":
                result = self._control.preview_reset()
            elif name == "environment_reset":
                if not isinstance(request, EnvironmentResetRequest):
                    raise AdminControlError("ADMIN-INPUT-CONTRACT")
                result = self._control.apply_reset(str(request.preview_token))
                self._register_environment(int(result["incarnation"]))
                self._requires_reload = True
            elif name == "runtime_start":
                result = self._control.start_runtime()
            elif name == "runtime_drain":
                result = self._runtime_control(request, "drain")
            elif name == "runtime_stop":
                result = self._runtime_control(request, "stop")
            elif name == "runtime_restart":
                self._runtime_control(request, "drain")
                self._runtime_control(request, "stop")
                self._control.wait_until_stopped()
                result = self._control.start_runtime()
            elif name == "inject_creator_input":
                if not isinstance(request, InjectCreatorInputRequest):
                    raise AdminControlError("ADMIN-INPUT-CONTRACT")
                result = self._control.send_control(
                    "input",
                    {
                        "message": str(request.message),
                        "idempotency_key": str(request.idempotency_key),
                    },
                )
            elif name == "advance_test_clock":
                if not isinstance(request, AdvanceTestClockRequest):
                    raise AdminControlError("ADMIN-INPUT-CONTRACT")
                self._require_test_controls()
                result = self._control.send_control(
                    "clock", {"seconds": int(request.seconds)}
                )
            elif name == "arm_fault":
                if not isinstance(request, ArmFaultRequest):
                    raise AdminControlError("ADMIN-INPUT-CONTRACT")
                self._require_test_controls()
                result = self._control.send_control(
                    "fault",
                    {
                        "action": "arm",
                        "fault": str(request.fault),
                        "duration_seconds": int(request.duration_seconds),
                    },
                )
            elif name == "clear_faults":
                self._require_test_controls()
                result = self._control.send_control("fault", {"action": "clear"})
            elif name == "run_test":
                if not isinstance(request, RunTestRequest):
                    raise AdminControlError("ADMIN-INPUT-CONTRACT")
                self._require_test_controls()
                result = self._run_test(str(request.scenario))
            elif name == "preview_correction":
                if not isinstance(request, PreviewCorrectionRequest):
                    raise AdminControlError("ADMIN-INPUT-CONTRACT")
                result = self._corrections.preview(request.spec.model_dump(mode="json"))
            elif name == "apply_correction":
                if not isinstance(request, ApplyCorrectionRequest):
                    raise AdminControlError("ADMIN-INPUT-CONTRACT")
                result = self._corrections.apply(
                    request.spec.model_dump(mode="json"),
                    str(request.preview_token),
                )
            elif name == "settle_correction_work":
                if not isinstance(request, SettleCorrectionWorkRequest):
                    raise AdminControlError("ADMIN-INPUT-CONTRACT")
                result = self._corrections.settle_side_work(str(request.side_work_id))
            else:
                raise AdminControlError("ADMIN-TOOL-NOT-REGISTERED")
            outcome = self._tool_success(started, result)
        except AdminCorrectionError as exc:
            outcome = self._correction_failure(started, str(exc))
        except AdminControlError as exc:
            outcome = self._tool_failure(started, "rejected", str(exc))
        except Exception:
            outcome = self._tool_failure(started, "failed", "ADMIN-CONTROL-FAILED")
        self._mutation_cache[cache_key] = (request_digest, outcome)
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
        if not isinstance(request, RuntimeControlRequest):
            raise AdminControlError("ADMIN-INPUT-CONTRACT")
        return self._control.send_control(
            command, {}, expected_instance_id=request.expected_instance_id
        )

    def _read_snapshot(self) -> AdminSchemaSnapshot:
        with self._credentials.resolve(
            self._config.locator,
            CredentialPurpose("database.admin"),
        ) as handle:
            conninfo = handle.consume(lambda value: bytes(value).decode("utf-8"))
        return AdminSchemaGateway(
            conninfo,
            expected_role=self._config.expected_role,
        ).read_snapshot()

    def _observation_gateway(self) -> AdminObservationGateway:
        with self._credentials.resolve(
            self._config.locator,
            CredentialPurpose("database.admin"),
        ) as handle:
            conninfo = handle.consume(lambda value: bytes(value).decode("utf-8"))
        return AdminObservationGateway(
            conninfo, expected_role=self._config.expected_role
        )

    def _initialize_environment(self, birth_mode: str) -> dict[str, Any]:
        initialization = self._control.initialize_environment(birth_mode)
        gateway = self._observation_gateway()
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
        gateway = self._observation_gateway()
        template_digest = _sha256(self._config.template_manifest.read_bytes())
        effective_config = self._config.model_copy(
            update={"environment_incarnation": incarnation}
        )
        values = {
            "environment_id": self._config.environment_id,
            "environment_kind": self._config.environment_kind.value,
            "incarnation": incarnation,
            "resettable": self._config.resettable,
            "test_controls_enabled": self._config.test_controls_enabled,
            "bundle_digest": self._config.expected.package_digest,
            "config_digest": effective_config.safe_digest(),
            "template_digest": template_digest,
            "data_root_identity_digest": _sha256(
                self._config.environment_root.as_posix().casefold().encode("utf-8")
            ),
            "database_identity_digest": _sha256(
                self._config.locator.identity().encode("utf-8")
            ),
        }
        gateway.register_environment(values)

    def _tail_diagnostics(self, limit: int) -> dict[str, Any]:
        log_root = self._config.environment_root / "data" / "logs"
        if not log_root.is_dir() or log_root.is_symlink():
            return {"events": [], "truncated": False}
        events: list[dict[str, Any]] = []
        allowed = {"timestamp", "level", "event", "code", "status", "reason_code"}
        for path in sorted(log_root.glob("*.jsonl"), reverse=True):
            if path.is_symlink() or not path.is_file():
                continue
            for line in reversed(path.read_text(encoding="utf-8").splitlines()):
                try:
                    value = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(value, dict):
                    events.append({key: value[key] for key in allowed if key in value})
                if len(events) >= limit:
                    return {"events": events, "truncated": True}
        return {"events": events, "truncated": False}

    def _require_test_controls(self) -> None:
        if not self._config.test_controls_enabled:
            raise AdminControlError("ADMIN-TEST-CONTROLS-DISABLED")

    def _run_test(self, scenario: str) -> dict[str, Any]:
        if scenario == "admin.runtime-lifecycle.v1":
            return self._control.send_control("status", {})
        if scenario == "admin.fault-control.v1":
            return self._control.send_control("fault", {"action": "status"})
        if scenario == "admin.observation-isolation.v1":
            return self._observation_gateway().subject_snapshot(private=False)
        return {"scenario": scenario, "status": "ready_for_formal_input"}

    def _tool_success(
        self, started: datetime, result: dict[str, Any]
    ) -> AdminToolResult[dict[str, Any]]:
        return AdminToolResult[dict[str, Any]](
            operation_id=str(uuid7()),
            status="succeeded",
            result=result,
            observed_versions={
                "environment_incarnation": self._config.environment_incarnation,
                "schema": "current",
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
            operation_id=str(uuid7()),
            status=status,
            error_code=code,
            observed_versions={
                "environment_incarnation": self._config.environment_incarnation,
                "schema": "current",
            },
            started_at=started.isoformat().replace("+00:00", "Z"),
            ended_at=datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        )

    @staticmethod
    def _validate_database_identity(snapshot: AdminSchemaSnapshot) -> None:
        if snapshot.server_version_num != _EXPECTED_POSTGRESQL:
            raise ValueError("ADMIN-DB-PG-VERSION")
        if snapshot.encoding != "UTF8" or snapshot.timezone != "UTC":
            raise ValueError("ADMIN-DB-IDENTITY")

    def _classify_schema(self, snapshot: AdminSchemaSnapshot) -> SchemaStatusPayload:
        missing = tuple(sorted(_REQUIRED_SCHEMA_TABLES - set(snapshot.tables)))
        status: Literal["current", "dirty"] = "dirty" if missing else "current"
        return SchemaStatusPayload(
            status=status,
            environment_id=self._config.environment_id,
            table_count=len(snapshot.tables),
            missing_tables=missing,
            error_code="ADMIN-SCHEMA-DIRTY" if missing else None,
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
    ) -> Literal["development", "system_test", "acceptance"]:
        return self._config.environment_kind.value


__all__ = ("AdminToolService",)
