"""Durable local receipts; unfinished calls are unknown and never replayed."""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Callable
from contextvars import ContextVar
from pathlib import Path
from typing import Any
from uuid import uuid7

from armi_local_control.configuration.paths import has_reparse_point
from armi_local_control.runtime_errors import RuntimeViolation
from armi_local_control.runtime_process import LocalProcessLock

_PROGRESS: ContextVar[Callable[[str], None] | None] = ContextVar(
    "admin_progress", default=None
)


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

            def progress(phase: str) -> None:
                if not phase or len(phase) > 128:
                    raise ValueError("ADMIN-INVOCATION-PHASE")
                metadata["phase"] = phase
                self.save_record(
                    path,
                    {**metadata, "request_digest": request_digest, "state": "started"},
                )

            context = _PROGRESS.set(progress)
            try:
                result = execute()
            finally:
                _PROGRESS.reset(context)
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
        if result["state"] == "started":
            try:
                with LocalProcessLock(self.root / (identity + ".lock")):
                    # The writer can finish between the first read and acquiring
                    # its lock. Only an unchanged unfinished record is unknown.
                    result = self._read_record(path, name, key)
                    if result["state"] == "started":
                        result["state"] = "unknown"
            except RuntimeViolation as error:
                if error.code != "CLI-RUNTIME-CONTROL-BUSY":
                    raise
                result["state"] = "running"
        return result

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


__all__ = ("InvocationJournal", "invocation_progress")
