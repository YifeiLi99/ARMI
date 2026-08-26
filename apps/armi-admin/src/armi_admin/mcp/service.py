"""Application service behind the static S037 Admin MCP tool catalog."""

from __future__ import annotations

import base64
import hashlib
import json
import stat
from datetime import UTC, datetime
from typing import Any, Literal, cast
from uuid import uuid7

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

from .contracts import (
    AdminIdentity,
    AdminMutationRequest,
    AdminToolResult,
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
    RuntimeControlRequest,
    SchemaStatusPayload,
    SchemaStatusRequest,
    SchemaStatusResult,
    SettleCorrectionWorkRequest,
    SubjectSnapshotRequest,
    TailDiagnosticsRequest,
    TraceFlowRequest,
)

_DIAGNOSTIC_TOTAL_BYTES = 2 * 1024 * 1024
_DIAGNOSTIC_LINE_BYTES = 64 * 1024
ObservationToolName = Literal[
    "correction_status",
    "inspect_scope",
    "runtime_status",
    "subject_snapshot",
    "tail_diagnostics",
    "trace_flow",
]
MutationToolName = Literal[
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
        "_mutation_cache",
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
        self._mutation_cache: dict[
            tuple[str, str], tuple[str, AdminToolResult[dict[str, Any]]]
        ] = {}
        self._requires_reload = False
        self._identity = AdminIdentity()

    @property
    def config(self) -> AdminConfig:
        return self._config

    def health(self, request: HealthRequest) -> HealthResult:
        del request
        started = datetime.now(UTC)
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
        if self._requires_reload:
            return self._tool_failure(
                started, "conflict", "ADMIN-CONFIG-RELOAD-REQUIRED"
            )
        if request.environment_id != self._config.environment_id:
            return self._tool_failure(started, "rejected", "ADMIN-ENVIRONMENT-MISMATCH")
        try:
            if name == "correction_status":
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
                    result = gateway.runtime_status()
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
            return self._tool_success(started, result)
        except AdminCorrectionError as exc:
            return self._correction_failure(started, exc.code)
        except Exception:
            return self._tool_failure(started, "failed", "ADMIN-OBSERVATION-FAILED")

    def mutate(
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
                typed_initialize = cast(EnvironmentInitializeRequest, request)
                result = self._initialize_environment(typed_initialize.birth_mode)
            elif name == "environment_reset_preview":
                result = self._control.preview_reset()
            elif name == "environment_reset":
                typed_reset = cast(EnvironmentResetRequest, request)
                result = self._control.apply_reset(str(typed_reset.preview_token))
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
            outcome = self._tool_success(started, result)
        except AdminCorrectionError as exc:
            outcome = self._correction_failure(started, exc.code)
        except AdminControlError as exc:
            code = str(exc)
            outcome = self._tool_failure(
                started,
                "failed" if code.endswith("-UNAVAILABLE") else "rejected",
                code,
            )
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
        if (
            snapshot.server_version_num != 180004
            or snapshot.encoding != "UTF8"
            or snapshot.timezone != "UTC"
            or snapshot.revision != "0000"
            or snapshot.baseline_identity != "armi.schema-baseline.v7"
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
    ) -> Literal["development", "system_test", "acceptance"]:
        return self._config.environment_kind.value


__all__ = ("AdminToolService",)
