"""Durable local receipts; unfinished calls are unknown and never replayed."""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Callable
from contextvars import ContextVar
from pathlib import Path
from typing import Any, Literal
from uuid import uuid7

from armi_local_control.configuration.paths import has_reparse_point
from armi_local_control.runtime_errors import RuntimeViolation
from armi_local_control.runtime_process import LocalProcessLock
from pydantic import BaseModel, ConfigDict, Field, JsonValue


class InvocationReferences(BaseModel):
    """Safe, bound references captured before dispatch; never a command body."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)
    configuration_target: (
        Literal["runtime", "model-bindings", "web-search", "qq", "mood-display"] | None
    ) = None
    expected_version: str | None = None
    configuration_write_id: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    preview_token: str | None = None
    component: (
        Literal["environment", "runtime", "postgresql", "semantic-recall"] | None
    ) = None
    expected_instance_id: str | None = None
    launch_instance_id: str | None = None
    deletion_party_key: str | None = None


class InvocationEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)
    schema_version: Literal["armi.admin-invocation-evidence.v1"] = (
        "armi.admin-invocation-evidence.v1"
    )
    operation: str
    idempotency_key: str
    request_digest: str
    references: InvocationReferences
    completed_steps: dict[str, dict[str, JsonValue]] = Field(
        default_factory=lambda: dict[str, dict[str, JsonValue]]()
    )
    outcome: dict[str, Any] | None = None
    resolution: dict[str, Any] | None = None
    observations: list[dict[str, Any]] = Field(
        default_factory=lambda: list[dict[str, Any]]()
    )


_PROGRESS: ContextVar[Callable[[str], None] | None] = ContextVar(
    "admin_progress", default=None
)
_COMPLETED_STEP: ContextVar[Callable[[str, dict[str, Any]], None] | None] = ContextVar(
    "admin_completed_step", default=None
)
_LAUNCH_ID: ContextVar[str | None] = ContextVar("admin_launch_id", default=None)


def invocation_launch_identity() -> str | None:
    return _LAUNCH_ID.get()


def invocation_completed_step(phase: str, result: dict[str, Any]) -> None:
    report = _COMPLETED_STEP.get()
    if report is not None:
        report(phase, result)


def invocation_progress(phase: str) -> None:
    """Persist a bounded phase before a slow operation leaves this process."""
    report = _PROGRESS.get()
    if report is not None:
        report(phase)


class InvocationJournal:
    def __init__(self, root: Path, binding_digest: str) -> None:
        self.root = root / "run" / "admin-invocations"
        self.binding_digest = binding_digest

    def invoke(
        self,
        *,
        name: str,
        key: str,
        request_digest: str,
        execute: Callable[[], dict[str, Any]],
        audit: dict[str, str | None] | None = None,
        references: InvocationReferences | None = None,
    ) -> dict[str, Any]:
        identity = hashlib.sha256(
            (self.binding_digest + "\0" + name + "\0" + key).encode("utf-8")
        ).hexdigest()
        self.root.mkdir(parents=True, exist_ok=True)
        if has_reparse_point(self.root, root=self.root.parent.parent):
            raise ValueError("ADMIN-JOURNAL-PATH")
        path = self.root / (identity + ".json")
        with LocalProcessLock(self.root / (identity + ".lock")):
            if path.exists():
                receipt = self.read(name, key)
                if receipt["request_digest"] != request_digest:
                    raise ValueError("ADMIN-IDEMPOTENCY-CONFLICT")
                if receipt["state"] == "finished":
                    return receipt["result"]
                raise ValueError("ADMIN-INVOCATION-UNKNOWN")
            metadata = {
                "schema_version": "armi.admin-invocation.v2",
                "operation": name,
                "idempotency_key": key,
                "audit": audit or {},
                "phase": "accepted",
            }
            self.save_record(
                path, {**metadata, "request_digest": request_digest, "state": "started"}
            )
            evidence_path = path.with_suffix(".evidence.json")
            evidence = InvocationEvidence(
                operation=name,
                idempotency_key=key,
                request_digest=request_digest,
                references=references or InvocationReferences(),
            )
            self.save_record(evidence_path, evidence.model_dump(mode="json"))

            def progress(phase: str) -> None:
                if not phase or len(phase) > 128:
                    raise ValueError("ADMIN-INVOCATION-PHASE")
                metadata["phase"] = phase
                self.save_record(
                    path,
                    {**metadata, "request_digest": request_digest, "state": "started"},
                )

            def completed_step(phase: str, result: dict[str, Any]) -> None:
                from .results import LifecyclePayload

                nonlocal evidence
                if not phase or len(phase) > 128:
                    raise ValueError("ADMIN-INVOCATION-PHASE")
                payload = LifecyclePayload.model_validate_json(json.dumps(result))
                evidence = evidence.model_copy(
                    update={
                        "completed_steps": {
                            **evidence.completed_steps,
                            phase: payload.model_dump(mode="json"),
                        }
                    }
                )
                self.save_record(evidence_path, evidence.model_dump(mode="json"))

            context = _PROGRESS.set(progress)
            step_context = _COMPLETED_STEP.set(completed_step)
            launch_context = _LAUNCH_ID.set(evidence.references.launch_instance_id)
            try:
                result = execute()
            finally:
                _PROGRESS.reset(context)
                _COMPLETED_STEP.reset(step_context)
                _LAUNCH_ID.reset(launch_context)
            # Preserve the exact completed response separately from the original
            # journal transition. Explicit reconciliation can recover a lost save.
            evidence = evidence.model_copy(
                update={
                    "outcome": result
                    if name not in {"authorization_approve", "authorization_revoke"}
                    else None
                }
            )
            self.save_record(evidence_path, evidence.model_dump(mode="json"))
            self.save_record(
                path,
                {
                    **metadata,
                    "request_digest": request_digest,
                    "state": "finished",
                    "result": result,
                },
            )
            return result

    def read(self, name: str, key: str) -> dict[str, Any]:
        identity = hashlib.sha256(
            (self.binding_digest + "\0" + name + "\0" + key).encode("utf-8")
        ).hexdigest()
        path = self.root / (identity + ".json")
        if not path.exists():
            return {"state": "not_found"}
        result = self._read_record(path, name, key)
        evidence = self._read_evidence(path, result)
        if evidence is not None and evidence.resolution is not None:
            return {**result, "state": "finished", "result": evidence.resolution}
        if result["state"] == "started":
            try:
                with LocalProcessLock(self.root / (identity + ".lock")):
                    # The writer can finish between the first read and acquiring
                    # its lock. Only an unchanged unfinished record is unknown.
                    result = self._read_record(path, name, key)
                    evidence = self._read_evidence(path, result)
                    if evidence is not None and evidence.resolution is not None:
                        return {
                            **result,
                            "state": "finished",
                            "result": evidence.resolution,
                        }
                    if result["state"] == "started":
                        result["state"] = "unknown"
            except RuntimeViolation as error:
                if error.code != "CLI-RUNTIME-CONTROL-BUSY":
                    raise
                result["state"] = "running"
        return result

    def reconcile(
        self,
        name: str,
        key: str,
        *,
        authorized_scopes: tuple[str, ...],
        observe: Callable[
            [InvocationEvidence], tuple[dict[str, Any] | None, dict[str, Any]]
        ],
    ) -> dict[str, Any]:
        identity = hashlib.sha256(
            (self.binding_digest + "\0" + name + "\0" + key).encode("utf-8")
        ).hexdigest()
        path = self.root / (identity + ".json")
        if not path.exists():
            return {"state": "not_found"}
        with LocalProcessLock(self.root / (identity + ".lock")):
            original = self._read_record(path, name, key)
            if original.get("audit", {}).get("scope") not in authorized_scopes:
                raise ValueError("ADMIN-SCOPE-REQUIRED")
            if (
                original["state"] == "finished"
                and original["result"].get("status") != "unknown"
            ):
                return original
            evidence = self._read_evidence(path, original)
            if evidence is None:
                return {
                    **original,
                    "state": "unknown",
                    "reconciliation_reason": "evidence_missing",
                }
            resolution = evidence.resolution or evidence.outcome
            if resolution is not None and resolution.get("status") == "unknown":
                resolution = None
            observation: dict[str, Any] = {"basis": "recorded_outcome"}
            if resolution is None:
                resolution, observation = observe(evidence)
            evidence = evidence.model_copy(
                update={
                    "resolution": resolution,
                    "observations": [observation],
                }
            )
            self.save_record(
                path.with_suffix(".evidence.json"), evidence.model_dump(mode="json")
            )
            return {
                **original,
                "state": "finished" if resolution is not None else "unknown",
                "result": resolution,
                "reconciliation": observation,
            }

    def _read_evidence(
        self, path: Path, original: dict[str, Any]
    ) -> InvocationEvidence | None:
        evidence_path = path.with_suffix(".evidence.json")
        if not evidence_path.exists():
            return None
        if (
            has_reparse_point(evidence_path, root=self.root.parent.parent)
            or not evidence_path.is_file()
            or evidence_path.stat().st_size > 4 * 1024 * 1024
        ):
            raise ValueError("ADMIN-JOURNAL-PATH")
        evidence = InvocationEvidence.model_validate_json(evidence_path.read_bytes())
        if any(
            getattr(evidence, field) != original[field]
            for field in ("operation", "idempotency_key", "request_digest")
        ):
            raise ValueError("ADMIN-JOURNAL-EVIDENCE-MISMATCH")
        return evidence

    def _read_record(self, path: Path, name: str, key: str) -> dict[str, Any]:
        if (
            has_reparse_point(path, root=self.root.parent.parent)
            or not path.is_file()
            or path.stat().st_size > 4 * 1024 * 1024
        ):
            raise ValueError("ADMIN-JOURNAL-PATH")
        result: dict[str, Any] = json.loads(path.read_bytes())
        if (
            result.get("schema_version") != "armi.admin-invocation.v2"
            or result.get("operation") != name
            or result.get("idempotency_key") != key
            or result.get("state") not in {"started", "finished"}
            or not isinstance(result.get("request_digest"), str)
            or (
                result.get("state") == "finished"
                and not isinstance(result.get("result"), dict)
            )
        ):
            raise ValueError("ADMIN-JOURNAL-CONTRACT")
        return result

    @staticmethod
    def save_record(path: Path, value: dict[str, Any]) -> None:
        temporary = path.with_name(f".{uuid7()}.tmp")
        try:
            with temporary.open("xb") as stream:
                stream.write(
                    (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode(
                        "utf-8"
                    )
                )
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)


__all__ = (
    "InvocationEvidence",
    "InvocationJournal",
    "InvocationReferences",
    "invocation_completed_step",
    "invocation_launch_identity",
    "invocation_progress",
)
