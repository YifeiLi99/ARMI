"""Durable local receipts; unfinished calls are unknown and never replayed."""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Callable
from pathlib import Path
from typing import Any
from uuid import uuid7

from armi_local_control.configuration.paths import has_reparse_point
from armi_local_control.runtime_process import LocalProcessLock


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
                "schema_version": "armi.admin-invocation.v1",
                "operation": name,
                "idempotency_key": key,
                "audit": audit or {},
            }
            self._save(
                path, {**metadata, "request_digest": request_digest, "state": "started"}
            )
            result = execute()
            self._save(
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
        if (
            has_reparse_point(path, root=self.root.parent.parent)
            or not path.is_file()
            or path.stat().st_size > 4 * 1024 * 1024
        ):
            raise ValueError("ADMIN-JOURNAL-PATH")
        result: dict[str, Any] = json.loads(path.read_bytes())
        if (
            result.get("schema_version") != "armi.admin-invocation.v1"
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
        return {
            **result,
            "state": "unknown" if result["state"] == "started" else result["state"],
        }

    @staticmethod
    def _save(path: Path, value: dict[str, Any]) -> None:
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


__all__ = ("InvocationJournal",)
