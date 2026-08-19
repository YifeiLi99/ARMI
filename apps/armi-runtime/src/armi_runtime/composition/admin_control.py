"""Default-off private Runtime control endpoint for one Admin experiment."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import struct
from collections.abc import Awaitable, Callable
from contextlib import suppress
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast

_MAX_REQUEST = 64 * 1024
_MAX_RESPONSE = 1024 * 1024
_COMMANDS = {
    "status",
    "drain",
    "stop",
    "input",
    "voice",
    "clock",
    "fault",
}
_FAULTS = {
    "artifact_after_publish_before_commit",
    "subject_before_cas",
    "effect_after_register_before_settlement",
    "adapter_after_dispatch_before_settlement",
}


def load_admin_control_incarnation(
    environment_root: Path, environment_id: str
) -> int | None:
    manifest_path = (
        environment_root / "run" / "admin-control" / "runtime-control.manifest.json"
    )
    if not manifest_path.is_file() or manifest_path.is_symlink():
        return None
    value = _strict_json(manifest_path.read_bytes())
    if (
        value.get("schema_version") != "armi.runtime-admin-control.v1"
        or value.get("environment_id") != environment_id
        or type(value.get("incarnation")) is not int
        or int(value["incarnation"]) < 1
    ):
        raise RuntimeAdminControlError("ADMIN-CONTROL-MANIFEST")
    return int(value["incarnation"])


class RuntimeAdminControlError(RuntimeError):
    pass


class RuntimeAdminInjectedFault(RuntimeError):
    pass


def _strict_json(value: bytes) -> dict[str, Any]:
    def pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, item in items:
            if key in result:
                raise RuntimeAdminControlError("ADMIN-CONTROL-DUPLICATE-KEY")
            result[key] = item
        return result

    decoded = value.decode("utf-8", "strict")
    result = json.loads(decoded, object_pairs_hook=pairs)
    if not isinstance(result, dict):
        raise RuntimeAdminControlError("ADMIN-CONTROL-JSON")
    return cast(dict[str, Any], result)


class RuntimeAdminControlServer:
    """Own one loopback control listener only when a matching manifest exists."""

    __slots__ = (
        "_armed_faults",
        "_descriptor",
        "_environment_id",
        "_incarnation",
        "_input",
        "_instance_id",
        "_manifest",
        "_on_drain",
        "_on_status",
        "_on_stop",
        "_run_root",
        "_server",
        "_test_clock_seconds",
        "_token",
        "_voice",
    )

    def __init__(
        self,
        *,
        run_root: Path,
        environment_id: str,
        incarnation: int,
        instance_id: str,
        on_status: Callable[[], dict[str, Any]],
        on_drain: Callable[[], None],
        on_stop: Callable[[], None],
        on_input: Callable[[str, str], Awaitable[dict[str, Any]]] | None,
        on_voice: Callable[[str], Awaitable[dict[str, Any]]] | None = None,
    ) -> None:
        self._run_root = run_root
        self._manifest = run_root / "runtime-control.manifest.json"
        self._descriptor = run_root / "runtime-control.json"
        self._environment_id = environment_id
        self._incarnation = incarnation
        self._instance_id = instance_id
        self._on_status = on_status
        self._on_drain = on_drain
        self._on_stop = on_stop
        self._input = on_input
        self._voice = on_voice
        self._server: asyncio.AbstractServer | None = None
        self._token = ""
        self._test_clock_seconds = 0
        self._armed_faults: dict[str, datetime] = {}

    @classmethod
    def configured(cls, environment_root: Path) -> bool:
        path = (
            environment_root / "run" / "admin-control" / "runtime-control.manifest.json"
        )
        return path.is_file() and not path.is_symlink()

    async def start(self) -> None:
        manifest = self._read_json(self._manifest)
        allowed = {
            "schema_version",
            "environment_id",
            "incarnation",
            "descriptor",
            "token",
            "token_digest",
        }
        if set(manifest) != allowed:
            raise RuntimeAdminControlError("ADMIN-CONTROL-MANIFEST")
        if (
            manifest["schema_version"] != "armi.runtime-admin-control.v1"
            or manifest["environment_id"] != self._environment_id
            or manifest["incarnation"] != self._incarnation
            or manifest["descriptor"] != "runtime-control.json"
            or manifest["token"] != "runtime-control.token"
        ):
            raise RuntimeAdminControlError("ADMIN-CONTROL-IDENTITY")
        token_path = self._run_root / "runtime-control.token"
        self._token = token_path.read_text(encoding="utf-8").strip()
        digest = f"sha256:{hashlib.sha256(self._token.encode('ascii')).hexdigest()}"
        if digest != manifest["token_digest"]:
            raise RuntimeAdminControlError("ADMIN-CONTROL-TOKEN")
        self._server = await asyncio.start_server(
            self._handle, "127.0.0.1", 0, limit=_MAX_REQUEST
        )
        sockets = self._server.sockets
        if not sockets:
            raise RuntimeAdminControlError("ADMIN-CONTROL-LISTENER")
        address = sockets[0].getsockname()
        self._atomic_json(
            self._descriptor,
            {
                "schema_version": "armi.runtime-admin-control.v1",
                "environment_id": self._environment_id,
                "incarnation": self._incarnation,
                "instance_id": self._instance_id,
                "pid": os.getpid(),
                "port": int(address[1]),
                "token_digest": digest,
            },
        )

    async def close(self) -> None:
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()
            self._server = None
        self._descriptor.unlink(missing_ok=True)
        (self._run_root / "runtime-control.token").unlink(missing_ok=True)
        self._manifest.unlink(missing_ok=True)
        self._token = ""
        self._armed_faults.clear()

    async def _handle(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        try:
            try:
                size = struct.unpack(">I", await reader.readexactly(4))[0]
                if size < 2 or size > _MAX_REQUEST:
                    raise RuntimeAdminControlError("ADMIN-CONTROL-REQUEST-SIZE")
                request = _strict_json(await reader.readexactly(size))
                response = await self._dispatch(request)
            except (
                RuntimeAdminControlError,
                asyncio.IncompleteReadError,
                UnicodeDecodeError,
                json.JSONDecodeError,
                struct.error,
                RecursionError,
            ):
                response = {
                    "request_id": None,
                    "status": "rejected",
                    "error_code": "ADMIN-CONTROL-PROTOCOL",
                }
            encoded = json.dumps(
                response, ensure_ascii=False, separators=(",", ":"), sort_keys=True
            ).encode("utf-8")
            if len(encoded) <= _MAX_RESPONSE:
                writer.write(struct.pack(">I", len(encoded)) + encoded)
                await writer.drain()
        finally:
            writer.close()
            with suppress(ConnectionError):
                await writer.wait_closed()

    async def _dispatch(self, request: dict[str, Any]) -> dict[str, Any]:
        allowed = {
            "schema_version",
            "request_id",
            "environment_id",
            "incarnation",
            "instance_id",
            "token",
            "command",
            "arguments",
        }
        if set(request) != allowed:
            raise RuntimeAdminControlError("ADMIN-CONTROL-FIELDS")
        if (
            request["schema_version"] != "armi.runtime-admin-control.v1"
            or request["environment_id"] != self._environment_id
            or request["incarnation"] != self._incarnation
            or request["instance_id"] != self._instance_id
            or request["token"] != self._token
            or request["command"] not in _COMMANDS
            or not isinstance(request["arguments"], dict)
        ):
            raise RuntimeAdminControlError("ADMIN-CONTROL-AUTHORITY")
        command = str(request["command"])
        arguments = cast(dict[str, Any], request["arguments"])
        if command == "status":
            result = self._status()
        elif command == "drain":
            self._on_drain()
            result = self._status()
        elif command == "stop":
            self._on_stop()
            result = {"runtime_state": "stopping"}
        elif command == "input":
            if self._input is None or set(arguments) != {"message", "idempotency_key"}:
                raise RuntimeAdminControlError("ADMIN-CONTROL-INPUT")
            result = await self._input(
                str(arguments["message"]), str(arguments["idempotency_key"])
            )
        elif command == "voice":
            if (
                self._voice is None
                or set(arguments) != {"action"}
                or arguments["action"] not in {"status", "start", "stop"}
            ):
                raise RuntimeAdminControlError("ADMIN-CONTROL-VOICE")
            result = await self._voice(str(arguments["action"]))
        elif command == "clock":
            if set(arguments) != {"seconds"} or type(arguments["seconds"]) is not int:
                raise RuntimeAdminControlError("ADMIN-CONTROL-CLOCK")
            seconds = int(arguments["seconds"])
            if not 1 <= seconds <= 3600:
                raise RuntimeAdminControlError("ADMIN-CONTROL-CLOCK")
            self._test_clock_seconds += seconds
            result = {
                "advanced_seconds": seconds,
                "total_advanced_seconds": self._test_clock_seconds,
            }
        else:
            result = self._fault(arguments)
        return {
            "request_id": request["request_id"],
            "status": "succeeded",
            "result": result,
        }

    def _status(self) -> dict[str, Any]:
        self._expire_faults()
        return {
            **self._on_status(),
            "test_clock_seconds": self._test_clock_seconds,
            "armed_faults": sorted(self._armed_faults),
        }

    def _fault(self, arguments: dict[str, Any]) -> dict[str, Any]:
        action = arguments.get("action")
        if action == "clear":
            self._armed_faults.clear()
        elif action == "arm":
            if set(arguments) != {"action", "fault", "duration_seconds"}:
                raise RuntimeAdminControlError("ADMIN-CONTROL-FAULT")
            fault = str(arguments["fault"])
            duration = arguments["duration_seconds"]
            if (
                fault not in _FAULTS
                or type(duration) is not int
                or not 1 <= duration <= 300
            ):
                raise RuntimeAdminControlError("ADMIN-CONTROL-FAULT")
            self._armed_faults[fault] = datetime.now(UTC) + timedelta(seconds=duration)
        elif action != "status":
            raise RuntimeAdminControlError("ADMIN-CONTROL-FAULT")
        self._expire_faults()
        return {"armed_faults": sorted(self._armed_faults)}

    def trigger_fault(self, name: str) -> None:
        """Consume one unexpired, explicitly armed conformance fault."""

        self._expire_faults()
        if name in self._armed_faults:
            del self._armed_faults[name]
            raise RuntimeAdminInjectedFault("ADMIN-FAULT-INJECTED")

    def _expire_faults(self) -> None:
        now = datetime.now(UTC)
        self._armed_faults = {
            name: expiry for name, expiry in self._armed_faults.items() if expiry > now
        }

    @staticmethod
    def _read_json(path: Path) -> dict[str, Any]:
        value = _strict_json(path.read_bytes())
        return value

    @staticmethod
    def _atomic_json(path: Path, value: object) -> None:
        encoded = (
            json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
            + "\n"
        )
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(encoded, encoding="utf-8", newline="\n")
        temporary.replace(path)


__all__ = (
    "RuntimeAdminControlError",
    "RuntimeAdminControlServer",
    "RuntimeAdminInjectedFault",
    "load_admin_control_incarnation",
)
