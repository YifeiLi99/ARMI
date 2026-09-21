"""Admin credential-check receipts available before PostgreSQL/Runtime starts."""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import cast
from uuid import UUID, uuid7

from .configuration.paths import has_reparse_point
from .process_identity import ManagedProcessIdentity, ManagedProcessState


class ProviderCheckReceipts:
    def __init__(self, environment_root: Path) -> None:
        self._environment_root = environment_root
        self._root = environment_root / "run" / "admin-invocations" / "provider-calls"
        self._writer: ManagedProcessIdentity | None = None

    def save(
        self, *, verification_id: str, credential_name: str, call: dict[str, object]
    ) -> None:
        call_id = UUID(str(call["call_id"]))
        if call_id.version != 7 or call.get("schema_kind") != "armi.provider-call":
            raise ValueError("USAGE-ADMIN-RECEIPT")
        if UUID(verification_id).version != 7:
            raise ValueError("USAGE-ADMIN-RECEIPT")
        if has_reparse_point(self._root, root=self._environment_root):
            raise ValueError("USAGE-ADMIN-PATH")
        self._root.mkdir(parents=True, exist_ok=True)
        path = self._root / f"{call_id}.json"
        if self._writer is None:
            self._writer = ManagedProcessIdentity.capture(
                os.getpid(),
                environment_identity=str(self._environment_root),
                incarnation=1,
            )
        document = {
            "schema_kind": "armi.admin-provider-call",
            "verification_id": verification_id,
            "credential_name": credential_name,
            "call": call,
            "writer": self._writer.to_wire(),
        }
        temporary = self._root / f".{uuid7()}.tmp"
        try:
            with temporary.open("xb") as stream:
                stream.write(
                    (json.dumps(document, ensure_ascii=False, indent=2) + "\n").encode(
                        "utf-8"
                    )
                )
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)

    def read(
        self, *, project_interrupted: bool = True
    ) -> tuple[dict[str, object], ...]:
        if not self._root.exists():
            return ()
        if has_reparse_point(self._root, root=self._environment_root):
            raise ValueError("USAGE-ADMIN-PATH")
        result: list[dict[str, object]] = []
        for path in self._root.glob("*.json"):
            if (
                has_reparse_point(path, root=self._environment_root)
                or not path.is_file()
                or path.stat().st_size > 131072
            ):
                raise ValueError("USAGE-ADMIN-PATH")
            value: object = json.loads(path.read_bytes())
            if type(value) is not dict:
                raise ValueError("USAGE-ADMIN-RECEIPT")
            row = cast(dict[str, object], value)
            call = row.get("call")
            if type(call) is not dict:
                raise ValueError("USAGE-ADMIN-RECEIPT")
            call = cast(dict[str, object], call)
            if (
                row.get("schema_kind") != "armi.admin-provider-call"
                or call.get("call_id") != path.stem
                or call.get("schema_kind") != "armi.provider-call"
            ):
                raise ValueError("USAGE-ADMIN-RECEIPT")
            result.append(row)
            if project_interrupted and call.get("outcome") == "pending":
                writer = ManagedProcessIdentity.from_wire(row["writer"])
                if writer.inspect() in {
                    ManagedProcessState.ABSENT,
                    ManagedProcessState.MISMATCH,
                }:
                    row["call"] = {
                        **call,
                        "outcome": "unknown",
                        "error_code": "USAGE-PROBE-INTERRUPTED",
                    }
        return tuple(result)

    def settle_interrupted(self, verification_id: str) -> None:
        """Called after the probe process has exited; never retry its requests."""
        for row in self.read(project_interrupted=False):
            if row["verification_id"] != verification_id:
                continue
            call = cast(dict[str, object], row["call"])
            if call["outcome"] != "pending":
                continue
            self.save(
                verification_id=verification_id,
                credential_name=str(row["credential_name"]),
                call={
                    **call,
                    "outcome": "unknown",
                    "finished_at": datetime.now(UTC).isoformat(),
                    "error_code": "USAGE-PROBE-INTERRUPTED",
                },
            )


__all__ = ("ProviderCheckReceipts",)
