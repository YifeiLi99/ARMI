"""Bounded environment and Runtime control for disposable Admin experiments."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import shutil
import socket
import struct
import subprocess
import sys
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast
from uuid import uuid7

from armi_kernel.application import CredentialPurpose
from psycopg.conninfo import conninfo_to_dict

from armi_admin.persistence import (
    AdminEnvironmentSchemaGateway,
    AdminObservationGateway,
)

from .configuration import AdminConfig
from .credentials import AdminCredentialPort

_MAX_REQUEST = 64 * 1024
_MAX_RESPONSE = 1024 * 1024


class AdminControlError(RuntimeError):
    """A stable control failure with no paths, process output, or credentials."""


def _digest(value: bytes) -> str:
    return f"sha256:{hashlib.sha256(value).hexdigest()}"


def _canonical(value: object) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, separators=(",", ":"), sort_keys=True
    ).encode("utf-8")


class AdminControlPlane:
    """Control one configured environment without caller-provided paths or commands."""

    __slots__ = ("_config", "_credentials", "_management_session_id", "_used_previews")

    def __init__(self, config: AdminConfig, credentials: AdminCredentialPort) -> None:
        self._config = config
        self._credentials = credentials
        self._management_session_id = str(uuid7())
        self._used_previews: set[str] = set()

    @property
    def management_session_id(self) -> str:
        return self._management_session_id

    def preview_reset(self) -> dict[str, Any]:
        self._require_resettable()
        if self._descriptor_path().exists():
            raise AdminControlError("ADMIN-RUNTIME-NOT-STOPPED")
        now = datetime.now(UTC)
        payload = {
            "schema_version": "armi.environment-reset-preview.v1",
            "management_session_id": self._management_session_id,
            "environment_id": self._config.environment_id,
            "incarnation": self._config.environment_incarnation,
            "template_digest": self._file_digest(self._config.template_manifest),
            "database_catalog_digest": self._database_catalog_digest(),
            "config_digest": self._config.safe_digest(),
            "data_root_digest": self._tree_digest(self._config.environment_root),
            "created_at": now.isoformat().replace("+00:00", "Z"),
            "expires_at": (now + timedelta(minutes=10))
            .isoformat()
            .replace("+00:00", "Z"),
            "nonce": str(uuid7()),
        }
        encoded = base64.urlsafe_b64encode(_canonical(payload)).rstrip(b"=")
        with self._credentials.resolve(
            self._config.preview_locator, CredentialPurpose("admin.preview")
        ) as handle:
            signature = handle.consume(
                lambda key: hmac.new(bytes(key), encoded, hashlib.sha256).digest()
            )
        token = (
            b"v1." + encoded + b"." + base64.urlsafe_b64encode(signature).rstrip(b"=")
        )
        return {
            "preview_token": token.decode("ascii"),
            "expires_at": payload["expires_at"],
            "incarnation": payload["incarnation"],
            "template_digest": payload["template_digest"],
            "data_root_digest": payload["data_root_digest"],
        }

    def validate_reset(self, token: str) -> dict[str, Any]:
        self._require_resettable()
        try:
            prefix, encoded_text, signature_text = token.split(".")
            if prefix != "v1":
                raise ValueError
            encoded = encoded_text.encode("ascii")
            signature = base64.urlsafe_b64decode(
                signature_text + "=" * (-len(signature_text) % 4)
            )
            with self._credentials.resolve(
                self._config.preview_locator, CredentialPurpose("admin.preview")
            ) as handle:
                expected = handle.consume(
                    lambda key: hmac.new(bytes(key), encoded, hashlib.sha256).digest()
                )
            if not hmac.compare_digest(signature, expected):
                raise ValueError
            payload = json.loads(
                base64.urlsafe_b64decode(encoded_text + "=" * (-len(encoded_text) % 4))
            )
        except Exception as exc:
            raise AdminControlError("ADMIN-RESET-PREVIEW-INVALID") from exc
        if (
            payload.get("management_session_id") != self._management_session_id
            or payload.get("environment_id") != self._config.environment_id
            or payload.get("incarnation") != self._config.environment_incarnation
        ):
            raise AdminControlError("ADMIN-RESET-PREVIEW-SCOPE")
        expires_at = datetime.fromisoformat(
            str(payload["expires_at"]).replace("Z", "+00:00")
        )
        if datetime.now(UTC) >= expires_at:
            raise AdminControlError("ADMIN-RESET-PREVIEW-EXPIRED")
        current = {
            "template_digest": self._file_digest(self._config.template_manifest),
            "database_catalog_digest": self._database_catalog_digest(),
            "config_digest": self._config.safe_digest(),
            "data_root_digest": self._tree_digest(self._config.environment_root),
        }
        if any(payload.get(key) != value for key, value in current.items()):
            raise AdminControlError("ADMIN-RESET-PREVIEW-STALE")
        if self._descriptor_path().exists():
            raise AdminControlError("ADMIN-RUNTIME-NOT-STOPPED")
        return payload

    def apply_reset(self, token: str) -> dict[str, Any]:
        payload = self.validate_reset(token)
        nonce = str(payload["nonce"])
        if nonce in self._used_previews:
            raise AdminControlError("ADMIN-RESET-PREVIEW-USED")
        recovery_root = (
            self._config.experiment_root
            / ".armi-admin-recovery"
            / f"{self._config.environment_id}-{self._config.environment_incarnation}-{nonce}"
        )
        if recovery_root.exists():
            raise AdminControlError("ADMIN-RESET-RECOVERY-EXISTS")
        recovery_root.mkdir(parents=True)
        dump_path = recovery_root / "database.dump"
        archived_root = recovery_root / "data-root"
        self._pg_dump(dump_path)
        dump_digest = self._file_digest(dump_path)
        self._config.environment_root.replace(archived_root)
        try:
            self._restore_template()
            self._rebuild_database()
        except Exception as exc:
            self._write_recovery_manifest(
                recovery_root,
                status="blocked",
                dump_digest=dump_digest,
                incarnation=self._config.environment_incarnation,
            )
            raise AdminControlError("ADMIN-RESET-REBUILD-BLOCKED") from exc
        self._used_previews.add(nonce)
        next_incarnation = self._config.environment_incarnation + 1
        self._write_recovery_manifest(
            recovery_root,
            status="complete",
            dump_digest=dump_digest,
            incarnation=next_incarnation,
        )
        return {
            "environment_id": self._config.environment_id,
            "previous_incarnation": self._config.environment_incarnation,
            "incarnation": next_incarnation,
            "recovery_digest": dump_digest,
            "status": "reset",
        }

    def initialize_environment(self, birth_mode: str) -> dict[str, Any]:
        if birth_mode not in {"unborn", "manifest"}:
            raise AdminControlError("ADMIN-INITIALIZE-BIRTH-MODE")
        if self._descriptor_path().exists():
            raise AdminControlError("ADMIN-RUNTIME-NOT-STOPPED")
        self._validate_template_manifest()
        if not self._config.environment_root.exists():
            self._restore_template()
        elif (
            not self._config.environment_root.is_dir()
            or self._config.environment_root.is_symlink()
        ):
            raise AdminControlError("ADMIN-ENVIRONMENT-ROOT")
        self._install_database()
        if birth_mode == "manifest":
            self._run_runtime_cli("bootstrap", "birth", timeout=180)
        return {
            "environment_id": self._config.environment_id,
            "incarnation": self._config.environment_incarnation,
            "birth_mode": birth_mode,
            "status": "initialized",
        }

    def send_control(
        self,
        command: str,
        arguments: dict[str, Any],
        *,
        expected_instance_id: str | None = None,
    ) -> dict[str, Any]:
        if command not in {"status", "drain", "stop", "input", "clock", "fault"}:
            raise AdminControlError("ADMIN-CONTROL-COMMAND")
        descriptor = self._read_json(
            self._descriptor_path(), "ADMIN-CONTROL-DESCRIPTOR"
        )
        token = self._token_path().read_text(encoding="utf-8").strip()
        if (
            descriptor.get("environment_id") != self._config.environment_id
            or descriptor.get("incarnation") != self._config.environment_incarnation
        ):
            raise AdminControlError("ADMIN-CONTROL-STALE")
        if (
            expected_instance_id is not None
            and descriptor.get("instance_id") != expected_instance_id
        ):
            raise AdminControlError("ADMIN-CONTROL-INSTANCE")
        request = _canonical(
            {
                "schema_version": "armi.runtime-admin-control.v1",
                "request_id": str(uuid7()),
                "environment_id": self._config.environment_id,
                "incarnation": self._config.environment_incarnation,
                "instance_id": descriptor["instance_id"],
                "token": token,
                "command": command,
                "arguments": arguments,
            }
        )
        if len(request) > _MAX_REQUEST:
            raise AdminControlError("ADMIN-CONTROL-REQUEST-SIZE")
        try:
            with socket.create_connection(
                ("127.0.0.1", int(descriptor["port"])), timeout=5
            ) as channel:
                channel.sendall(struct.pack(">I", len(request)) + request)
                size = struct.unpack(">I", self._receive(channel, 4))[0]
                if size > _MAX_RESPONSE:
                    raise AdminControlError("ADMIN-CONTROL-RESPONSE-SIZE")
                response = json.loads(
                    self._receive(channel, size).decode("utf-8", "strict")
                )
        except AdminControlError:
            raise
        except Exception as exc:
            raise AdminControlError("ADMIN-CONTROL-UNAVAILABLE") from exc
        if not isinstance(response, dict):
            raise AdminControlError("ADMIN-CONTROL-PROTOCOL")
        typed_response = cast(dict[str, Any], response)
        if typed_response.get("request_id") is None:
            raise AdminControlError("ADMIN-CONTROL-PROTOCOL")
        return typed_response

    def wait_until_stopped(self, timeout_seconds: float = 30.0) -> None:
        deadline = time.monotonic() + timeout_seconds
        while self._descriptor_path().exists():
            if time.monotonic() >= deadline:
                raise AdminControlError("ADMIN-CONTROL-STOP-TIMEOUT")
            time.sleep(0.1)

    def ensure_runtime_stopped(self) -> None:
        """Drain and stop through the private protocol, never by force."""

        if not self._descriptor_path().exists():
            return
        self.send_control("drain", {})
        self.send_control("stop", {})
        self.wait_until_stopped()

    def start_runtime(self) -> dict[str, Any]:
        if self._descriptor_path().exists():
            return self.send_control("status", {})
        run_root = self._run_root()
        run_root.mkdir(parents=True, exist_ok=True)
        token = base64.urlsafe_b64encode(os.urandom(32)).rstrip(b"=").decode("ascii")
        manifest = {
            "schema_version": "armi.runtime-admin-control.v1",
            "environment_id": self._config.environment_id,
            "incarnation": self._config.environment_incarnation,
            "descriptor": "runtime-control.json",
            "token": "runtime-control.token",
            "token_digest": _digest(token.encode("ascii")),
        }
        self._atomic_json(run_root / "runtime-control.manifest.json", manifest)
        self._atomic_text(self._token_path(), token)
        command = [
            sys.executable,
            "-m",
            "armi_runtime.cli",
            "runtime",
            "start",
            "--environment-root",
            os.fspath(self._config.environment_root),
        ]
        environment = self._runtime_environment()
        flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        process = subprocess.Popen(
            command,
            cwd=self._config.environment_root,
            env=environment,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=flags,
        )
        return {"pid": process.pid, "control_state": "starting"}

    def _require_resettable(self) -> None:
        if not self._config.resettable:
            raise AdminControlError("ADMIN-ENVIRONMENT-NOT-RESETTABLE")

    def _database_catalog_digest(self) -> str:
        with self._credentials.resolve(
            self._config.locator, CredentialPurpose("database.admin")
        ) as handle:
            conninfo = handle.consume(lambda value: bytes(value).decode("utf-8"))
        return AdminObservationGateway(
            conninfo, expected_role=self._config.expected_role
        ).database_catalog_digest()

    def _pg_dump(self, output: Path) -> None:
        executable = (
            self._config.postgresql_tool_root
            / "bin"
            / ("pg_dump.exe" if os.name == "nt" else "pg_dump")
        )
        if not executable.is_file() or executable.is_symlink():
            raise AdminControlError("ADMIN-RESET-PG-DUMP")
        with self._credentials.resolve(
            self._config.migrator_locator,
            CredentialPurpose("database.migrator"),
        ) as handle:
            conninfo = handle.consume(lambda value: bytes(value).decode("utf-8"))
        environment = self._runtime_environment()
        connection = conninfo_to_dict(conninfo)
        variable_map = {
            "host": "PGHOST",
            "port": "PGPORT",
            "dbname": "PGDATABASE",
            "user": "PGUSER",
            "password": "PGPASSWORD",
            "sslmode": "PGSSLMODE",
        }
        for key, variable in variable_map.items():
            if value := connection.get(key):
                environment[variable] = str(value)
        completed = subprocess.run(
            [
                os.fspath(executable),
                "--role=armi_owner",
                "--format=custom",
                "--file",
                os.fspath(output),
            ],
            env=environment,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=90,
            check=False,
        )
        if completed.returncode != 0 or not output.is_file():
            raise AdminControlError("ADMIN-RESET-PG-DUMP")

    def _restore_template(self) -> None:
        manifest = self._validate_template_manifest()
        del manifest
        source_root = self._config.template_manifest.parent / "environment-template"
        if not source_root.is_dir() or source_root.is_symlink():
            raise AdminControlError("ADMIN-TEMPLATE-ROOT")
        shutil.copytree(source_root, self._config.environment_root, symlinks=False)

    def _validate_template_manifest(self) -> dict[str, Any]:
        manifest = self._read_json(
            self._config.template_manifest, "ADMIN-TEMPLATE-MANIFEST"
        )
        if (
            manifest.get("schema_version") != "armi.admin-experiment-environment.v1"
            or manifest.get("environment_id") != self._config.environment_id
        ):
            raise AdminControlError("ADMIN-TEMPLATE-IDENTITY")
        return manifest

    def _rebuild_database(self) -> None:
        with self._credentials.resolve(
            self._config.migrator_locator, CredentialPurpose("database.migrator")
        ) as handle:
            conninfo = handle.consume(lambda value: bytes(value).decode("utf-8"))
        AdminEnvironmentSchemaGateway.recreate_empty_schema(conninfo)
        self._run_runtime_cli("db", "install", timeout=180, with_migrator=True)

    def _install_database(self) -> None:
        self._run_runtime_cli("db", "install", timeout=180, with_migrator=True)

    def _run_runtime_cli(
        self,
        group: str,
        command: str,
        *,
        timeout: int,
        with_migrator: bool = False,
    ) -> None:
        environment = self._runtime_environment()
        if with_migrator:
            with self._credentials.resolve(
                self._config.migrator_locator,
                CredentialPurpose("database.migrator"),
            ) as handle:
                handle.consume(
                    lambda value: environment.__setitem__(
                        "ARMI_SECRET_MIGRATOR_DATABASE",
                        bytes(value).decode("utf-8"),
                    )
                )
        completed = subprocess.run(
            [
                sys.executable,
                "-m",
                "armi_runtime.cli",
                group,
                command,
                "--environment-root",
                os.fspath(self._config.environment_root),
            ],
            cwd=self._config.environment_root,
            env=environment,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=timeout,
            check=False,
        )
        if completed.returncode != 0:
            raise AdminControlError("ADMIN-ENVIRONMENT-CLI")

    def _write_recovery_manifest(
        self,
        root: Path,
        *,
        status: str,
        dump_digest: str,
        incarnation: int,
    ) -> None:
        self._atomic_json(
            root / "recovery-manifest.json",
            {
                "schema_version": "armi.admin-environment-recovery.v1",
                "environment_id": self._config.environment_id,
                "source_incarnation": self._config.environment_incarnation,
                "result_incarnation": incarnation,
                "status": status,
                "database_dump_digest": dump_digest,
                "template_digest": self._file_digest(self._config.template_manifest),
            },
        )

    def _run_root(self) -> Path:
        return self._config.environment_root / "run" / "admin-control"

    def _descriptor_path(self) -> Path:
        return self._run_root() / "runtime-control.json"

    def _token_path(self) -> Path:
        return self._run_root() / "runtime-control.token"

    @staticmethod
    def _file_digest(path: Path) -> str:
        try:
            return _digest(path.read_bytes())
        except OSError as exc:
            raise AdminControlError("ADMIN-TEMPLATE-UNAVAILABLE") from exc

    @staticmethod
    def _tree_digest(root: Path) -> str:
        if not root.is_dir() or root.is_symlink():
            raise AdminControlError("ADMIN-ENVIRONMENT-ROOT")
        lines = bytearray()
        for path in sorted(root.rglob("*"), key=lambda item: item.as_posix()):
            if path.is_symlink():
                raise AdminControlError("ADMIN-ENVIRONMENT-REPARSE")
            relative = path.relative_to(root).as_posix()
            if relative.startswith("run/") or not path.is_file():
                continue
            lines.extend(relative.encode("utf-8"))
            lines.extend(b"\t")
            lines.extend(_digest(path.read_bytes()).encode("ascii"))
            lines.extend(b"\n")
        return _digest(bytes(lines))

    @staticmethod
    def _read_json(path: Path, code: str) -> dict[str, Any]:
        try:
            value = json.loads(path.read_bytes())
            if not isinstance(value, dict):
                raise ValueError
            return cast(dict[str, Any], value)
        except Exception as exc:
            raise AdminControlError(code) from exc

    @staticmethod
    def _receive(channel: socket.socket, size: int) -> bytes:
        value = bytearray()
        while len(value) < size:
            chunk = channel.recv(size - len(value))
            if not chunk:
                raise AdminControlError("ADMIN-CONTROL-TRUNCATED")
            value.extend(chunk)
        return bytes(value)

    @staticmethod
    def _atomic_json(path: Path, value: object) -> None:
        AdminControlPlane._atomic_text(path, _canonical(value).decode("utf-8") + "\n")

    @staticmethod
    def _atomic_text(path: Path, value: str) -> None:
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(value, encoding="utf-8", newline="\n")
        temporary.replace(path)

    @staticmethod
    def _runtime_environment() -> dict[str, str]:
        allowed = ("PATH", "SYSTEMROOT", "WINDIR", "TEMP", "TMP")
        return {name: os.environ[name] for name in allowed if name in os.environ}


__all__ = ("AdminControlError", "AdminControlPlane")
