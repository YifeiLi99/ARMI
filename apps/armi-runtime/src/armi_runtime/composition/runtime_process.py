"""Manage one detached Runtime process through the private control protocol."""

from __future__ import annotations

import base64
import ctypes
import hashlib
import json
import os
import socket
import struct
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, BinaryIO, cast
from uuid import uuid7

from .runtime_errors import RuntimeViolation

_CONTROL_SCHEMA = "armi.runtime-admin-control.v1"
_PROCESS_SCHEMA = "armi.runtime-process.v1"
_MAX_REQUEST = 64 * 1024
_MAX_RESPONSE = 1024 * 1024
_START_TIMEOUT_SECONDS = 30.0
_STOP_TIMEOUT_SECONDS = 30.0
_STILL_ACTIVE = 259


def _strict_json(value: bytes, code: str) -> dict[str, Any]:
    def pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, item in items:
            if key in result:
                raise RuntimeViolation(code, "runtime process metadata is invalid")
            result[key] = item
        return result

    try:
        decoded = value.decode("utf-8", "strict")
        result = json.loads(decoded, object_pairs_hook=pairs)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeViolation(code, "runtime process metadata is invalid") from exc
    if not isinstance(result, dict):
        raise RuntimeViolation(code, "runtime process metadata is invalid")
    return cast(dict[str, Any], result)


def _receive(channel: socket.socket, size: int) -> bytes:
    result = bytearray()
    while len(result) < size:
        part = channel.recv(size - len(result))
        if not part:
            raise RuntimeViolation(
                "CLI-RUNTIME-CONTROL-UNAVAILABLE",
                "runtime control connection closed early",
            )
        result.extend(part)
    return bytes(result)


def _pid_is_alive(pid: int) -> bool:
    if pid < 1:
        return False
    if os.name != "nt":
        try:
            os.kill(pid, 0)
        except OSError:
            return False
        return True
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.GetExitCodeProcess.argtypes = (
        wintypes.HANDLE,
        ctypes.POINTER(wintypes.DWORD),
    )
    kernel32.GetExitCodeProcess.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
    kernel32.CloseHandle.restype = wintypes.BOOL
    handle = kernel32.OpenProcess(0x1000, False, pid)
    if not handle:
        return False
    try:
        exit_code = wintypes.DWORD()
        if not kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
            return False
        return exit_code.value == _STILL_ACTIVE
    finally:
        kernel32.CloseHandle(handle)


def _lock_file(handle: BinaryIO) -> None:
    try:
        if os.name == "nt":
            import msvcrt

            handle.seek(0)
            if handle.read(1) == b"":
                handle.write(b"\0")
                handle.flush()
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError as exc:
        raise RuntimeViolation(
            "CLI-RUNTIME-CONTROL-BUSY",
            "another runtime lifecycle command is active",
        ) from exc


def _unlock_file(handle: BinaryIO) -> None:
    if os.name == "nt":
        import msvcrt

        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
    else:
        import fcntl

        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


class RuntimeProcessManager:
    """Start, observe, and gracefully stop one environment-bound Runtime."""

    __slots__ = (
        "_control_root",
        "_environment_id",
        "_environment_root",
        "_incarnation",
        "_lock_path",
        "_state_path",
    )

    def __init__(
        self,
        environment_root: Path,
        environment_id: str,
        *,
        incarnation: int = 1,
    ) -> None:
        self._environment_root = environment_root.resolve(strict=True)
        self._environment_id = environment_id
        self._incarnation = incarnation
        run_root = self._environment_root / "run"
        self._control_root = run_root / "admin-control"
        self._state_path = run_root / "runtime-process.json"
        self._lock_path = run_root / "runtime-process.lock"

    def start(self) -> dict[str, Any]:
        with self._exclusive():
            current = self.status()
            if current["status"] == "running":
                return {**current, "status": "already_running"}
            if current["status"] == "starting":
                return current
            self._clear_stale_files()
            self._control_root.mkdir(parents=True, exist_ok=True)
            self._control_root.chmod(0o700)
            token = (
                base64.urlsafe_b64encode(os.urandom(32)).rstrip(b"=").decode("ascii")
            )
            token_digest = f"sha256:{hashlib.sha256(token.encode('ascii')).hexdigest()}"
            self._atomic_json(
                self._control_root / "runtime-control.manifest.json",
                {
                    "schema_version": _CONTROL_SCHEMA,
                    "environment_id": self._environment_id,
                    "incarnation": self._incarnation,
                    "descriptor": "runtime-control.json",
                    "token": "runtime-control.token",
                    "token_digest": token_digest,
                },
            )
            self._atomic_text(
                self._control_root / "runtime-control.token",
                token,
                mode=0o600,
            )
            command = (
                sys.executable,
                "-m",
                "armi_runtime.cli",
                "runtime",
                "start",
                "--environment-root",
                os.fspath(self._environment_root),
            )
            environment = {
                name: os.environ[name]
                for name in ("PATH", "SYSTEMROOT", "WINDIR", "TEMP", "TMP")
                if name in os.environ
            }
            options: dict[str, Any] = {
                "cwd": self._environment_root,
                "env": environment,
                "stdin": subprocess.DEVNULL,
                "stdout": subprocess.DEVNULL,
                "stderr": subprocess.DEVNULL,
                "close_fds": True,
            }
            if os.name == "nt":
                options["creationflags"] = (
                    subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS
                )
            else:
                options["start_new_session"] = True
            try:
                process = subprocess.Popen(command, **options)
            except OSError as exc:
                self._clear_stale_files()
                raise RuntimeViolation(
                    "CLI-RUNTIME-START-FAILED",
                    "runtime process could not be started",
                ) from exc
            self._atomic_json(
                self._state_path,
                {
                    "schema_version": _PROCESS_SCHEMA,
                    "environment_id": self._environment_id,
                    "incarnation": self._incarnation,
                    "pid": process.pid,
                    "started_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
                },
            )
            deadline = time.monotonic() + _START_TIMEOUT_SECONDS
            while time.monotonic() < deadline:
                if self._descriptor_path().is_file():
                    observed = self.status()
                    if observed["status"] == "running":
                        return {**observed, "status": "started"}
                if process.poll() is not None:
                    self._clear_stale_files()
                    raise RuntimeViolation(
                        "CLI-RUNTIME-START-FAILED",
                        "runtime exited before becoming controllable",
                    )
                time.sleep(0.05)
            raise RuntimeViolation(
                "CLI-RUNTIME-START-TIMEOUT",
                "runtime did not become controllable before the startup deadline",
            )

    def status(self) -> dict[str, Any]:
        descriptor = self._read_optional(
            self._descriptor_path(), "CLI-RUNTIME-DESCRIPTOR"
        )
        state = self._read_optional(self._state_path, "CLI-RUNTIME-STATE")
        pid = self._pid_from(descriptor) or self._pid_from(state)
        if descriptor is None:
            if pid is not None and _pid_is_alive(pid):
                return {"status": "starting", "pid": pid}
            manifest_path = self._control_root / "runtime-control.manifest.json"
            if (
                state is None
                and manifest_path.is_file()
                and not manifest_path.is_symlink()
            ):
                age = time.time() - manifest_path.stat().st_mtime
                if age <= _START_TIMEOUT_SECONDS:
                    return {"status": "starting", "pid": None}
            return {"status": "stopped", "pid": pid}
        try:
            response = self._send_control("status")
        except RuntimeViolation:
            if pid is not None and not _pid_is_alive(pid):
                return {"status": "stopped", "pid": pid}
            raise
        return {
            "status": "running",
            "pid": pid,
            "runtime": response["result"],
        }

    def stop(self) -> dict[str, Any]:
        with self._exclusive():
            current = self.status()
            if current["status"] == "stopped":
                self._clear_stale_files()
                return current
            if current["status"] == "starting":
                raise RuntimeViolation(
                    "CLI-RUNTIME-STARTING",
                    "runtime is still starting",
                )
            pid = current.get("pid")
            self._send_control("drain")
            self._send_control("stop")
            deadline = time.monotonic() + _STOP_TIMEOUT_SECONDS
            while time.monotonic() < deadline:
                descriptor_exists = self._descriptor_path().exists()
                alive = isinstance(pid, int) and _pid_is_alive(pid)
                if not descriptor_exists and not alive:
                    self._clear_stale_files()
                    return {"status": "stopped", "pid": pid}
                time.sleep(0.05)
            raise RuntimeViolation(
                "CLI-RUNTIME-STOP-TIMEOUT",
                "runtime did not stop before the graceful deadline",
            )

    def _send_control(self, command: str) -> dict[str, Any]:
        descriptor = self._read_required(
            self._descriptor_path(), "CLI-RUNTIME-DESCRIPTOR"
        )
        expected = {
            "schema_version",
            "environment_id",
            "incarnation",
            "instance_id",
            "pid",
            "port",
            "token_digest",
        }
        if (
            set(descriptor) != expected
            or descriptor.get("schema_version") != _CONTROL_SCHEMA
            or descriptor.get("environment_id") != self._environment_id
            or descriptor.get("incarnation") != self._incarnation
            or type(descriptor.get("pid")) is not int
            or type(descriptor.get("port")) is not int
        ):
            raise RuntimeViolation(
                "CLI-RUNTIME-DESCRIPTOR", "runtime control descriptor is invalid"
            )
        try:
            token = (
                (self._control_root / "runtime-control.token")
                .read_text(encoding="utf-8")
                .strip()
            )
        except OSError as exc:
            raise RuntimeViolation(
                "CLI-RUNTIME-CONTROL-UNAVAILABLE",
                "runtime control token is unavailable",
            ) from exc
        digest = f"sha256:{hashlib.sha256(token.encode('ascii')).hexdigest()}"
        if digest != descriptor["token_digest"]:
            raise RuntimeViolation(
                "CLI-RUNTIME-CONTROL-UNAVAILABLE",
                "runtime control token does not match the descriptor",
            )
        request_id = str(uuid7())
        encoded = json.dumps(
            {
                "schema_version": _CONTROL_SCHEMA,
                "request_id": request_id,
                "environment_id": self._environment_id,
                "incarnation": self._incarnation,
                "instance_id": descriptor["instance_id"],
                "token": token,
                "command": command,
                "arguments": {},
            },
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        if len(encoded) > _MAX_REQUEST:
            raise RuntimeViolation(
                "CLI-RUNTIME-CONTROL-UNAVAILABLE",
                "runtime control request exceeded its boundary",
            )
        try:
            with socket.create_connection(
                ("127.0.0.1", int(descriptor["port"])), timeout=5
            ) as channel:
                channel.sendall(struct.pack(">I", len(encoded)) + encoded)
                size = struct.unpack(">I", _receive(channel, 4))[0]
                if size > _MAX_RESPONSE:
                    raise RuntimeViolation(
                        "CLI-RUNTIME-CONTROL-UNAVAILABLE",
                        "runtime control response exceeded its boundary",
                    )
                response = _strict_json(
                    _receive(channel, size), "CLI-RUNTIME-CONTROL-UNAVAILABLE"
                )
        except RuntimeViolation:
            raise
        except (OSError, ValueError) as exc:
            raise RuntimeViolation(
                "CLI-RUNTIME-CONTROL-UNAVAILABLE",
                "runtime control endpoint is unavailable",
            ) from exc
        if (
            response.get("request_id") != request_id
            or response.get("status") != "succeeded"
            or not isinstance(response.get("result"), dict)
        ):
            raise RuntimeViolation(
                "CLI-RUNTIME-CONTROL-UNAVAILABLE",
                "runtime control response is invalid",
            )
        return response

    def _exclusive(self) -> _RuntimeProcessLock:
        return _RuntimeProcessLock(self._lock_path)

    def _clear_stale_files(self) -> None:
        for path in (
            self._descriptor_path(),
            self._control_root / "runtime-control.token",
            self._control_root / "runtime-control.manifest.json",
            self._state_path,
        ):
            path.unlink(missing_ok=True)

    def _descriptor_path(self) -> Path:
        return self._control_root / "runtime-control.json"

    @staticmethod
    def _pid_from(value: dict[str, Any] | None) -> int | None:
        if value is None or type(value.get("pid")) is not int:
            return None
        pid = int(value["pid"])
        return pid if pid > 0 else None

    @staticmethod
    def _read_optional(path: Path, code: str) -> dict[str, Any] | None:
        if not path.is_file() or path.is_symlink():
            return None
        return _strict_json(path.read_bytes(), code)

    @classmethod
    def _read_required(cls, path: Path, code: str) -> dict[str, Any]:
        value = cls._read_optional(path, code)
        if value is None:
            raise RuntimeViolation(code, "runtime process metadata is unavailable")
        return value

    @staticmethod
    def _atomic_json(path: Path, value: object) -> None:
        RuntimeProcessManager._atomic_text(
            path,
            json.dumps(
                value,
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            )
            + "\n",
        )

    @staticmethod
    def _atomic_text(path: Path, value: str, *, mode: int = 0o600) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
        temporary.write_text(value, encoding="utf-8", newline="\n")
        temporary.chmod(mode)
        temporary.replace(path)
        path.chmod(mode)


class _RuntimeProcessLock:
    __slots__ = ("_handle", "_path")

    def __init__(self, path: Path) -> None:
        self._path = path
        self._handle: BinaryIO | None = None

    def __enter__(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        handle = self._path.open("a+b")
        try:
            _lock_file(handle)
        except Exception:
            handle.close()
            raise
        self._handle = handle

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: object,
    ) -> None:
        del exc_type, exc, traceback
        handle = self._handle
        self._handle = None
        if handle is not None:
            try:
                _unlock_file(handle)
            finally:
                handle.close()


__all__ = ("RuntimeProcessManager",)
