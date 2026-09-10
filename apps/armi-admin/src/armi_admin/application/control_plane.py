"""Bounded environment and Runtime control for disposable Admin experiments."""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import os
import re
import shutil
import socket
import struct
import subprocess
import sys
import time
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Literal, cast
from uuid import uuid7

from armi_kernel.application import CredentialPurpose
from armi_local_control import RuntimeProcessManager, environment_control_root
from armi_local_control.configuration.paths import has_reparse_point
from armi_local_control.lifecycle import environment_control_lock
from armi_local_control.maintenance import (
    ConfigurationInvocation,
    MaintenanceInvocation,
)

from armi_admin.persistence import AdminObservationGateway

from .configuration import AdminConfig
from .credentials import AdminCredentialPort, AdminSecretError

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

    __slots__ = (
        "_config",
        "_credentials",
        "_management_session_id",
        "_observation",
    )

    def __init__(
        self,
        config: AdminConfig,
        credentials: AdminCredentialPort,
        observation: AdminObservationGateway,
    ) -> None:
        self._config = config
        self._credentials = credentials
        self._management_session_id = str(uuid7())
        self._observation = observation

    @property
    def management_session_id(self) -> str:
        return self._management_session_id

    def preview_reset(self) -> dict[str, Any]:
        self._require_reset_environment()
        if self._descriptor_path().exists():
            raise AdminControlError("ADMIN-RUNTIME-NOT-STOPPED")
        now = datetime.now(UTC)
        payload = {
            "schema_version": "armi.environment-reset-preview.v2",
            "management_session_id": self._management_session_id,
            "environment_id": self._config.environment_id,
            "incarnation": self._config.environment_incarnation,
            "database_catalog_digest": self._database_catalog_digest(),
            "config_digest": self._config.safe_digest(),
            "data_root_digest": self._tree_digest(self._config.environment_root),
            "subject_versions": self._observation.subject_snapshot(private=False),
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
            b"v2." + encoded + b"." + base64.urlsafe_b64encode(signature).rstrip(b"=")
        )
        return {
            "preview_token": token.decode("ascii"),
            "expires_at": payload["expires_at"],
            "incarnation": payload["incarnation"],
            "environment_id": self._config.environment_id,
            "environment_root": str(self._config.environment_root),
            "subject_versions": payload["subject_versions"],
            "impact": "Delete the bound ARMI database state and generated artifacts, runner workspaces, exports, logs and run state; leave the subject unborn. Configuration and secrets are retained. No backup is created.",
        }

    def validate_reset(self, token: str) -> dict[str, Any]:
        self._require_reset_environment()
        try:
            prefix, encoded_text, signature_text = token.split(".")
            if prefix != "v2":
                raise ValueError
            encoded = encoded_text.encode("ascii")
            signature = base64.urlsafe_b64decode(
                signature_text + "=" * (-len(signature_text) % 4)
            )
        except (ValueError, UnicodeEncodeError, binascii.Error) as exc:
            raise AdminControlError("ADMIN-RESET-PREVIEW-INVALID") from exc
        try:
            with self._credentials.resolve(
                self._config.preview_locator, CredentialPurpose("admin.preview")
            ) as handle:
                expected = handle.consume(
                    lambda key: hmac.new(bytes(key), encoded, hashlib.sha256).digest()
                )
        except AdminSecretError as exc:
            raise AdminControlError("ADMIN-RESET-PREVIEW-UNAVAILABLE") from exc
        try:
            if not hmac.compare_digest(signature, expected):
                raise ValueError
            decoded = json.loads(
                base64.urlsafe_b64decode(encoded_text + "=" * (-len(encoded_text) % 4))
            )
            if (
                not isinstance(decoded, dict)
                or cast(dict[str, Any], decoded).get("schema_version")
                != "armi.environment-reset-preview.v2"
            ):
                raise ValueError
            payload = cast(dict[str, Any], decoded)
            expires_at = datetime.fromisoformat(
                str(payload["expires_at"]).replace("Z", "+00:00")
            )
        except (
            ValueError,
            TypeError,
            KeyError,
            UnicodeDecodeError,
            json.JSONDecodeError,
            binascii.Error,
        ) as exc:
            raise AdminControlError("ADMIN-RESET-PREVIEW-INVALID") from exc
        if (
            payload.get("environment_id") != self._config.environment_id
            or payload.get("incarnation") != self._config.environment_incarnation
        ):
            raise AdminControlError("ADMIN-RESET-PREVIEW-SCOPE")
        if datetime.now(UTC) >= expires_at:
            raise AdminControlError("ADMIN-RESET-PREVIEW-EXPIRED")
        current = {
            "database_catalog_digest": self._database_catalog_digest(),
            "config_digest": self._config.safe_digest(),
            "data_root_digest": self._tree_digest(self._config.environment_root),
            "subject_versions": self._observation.subject_snapshot(private=False),
        }
        if any(payload.get(key) != value for key, value in current.items()):
            raise AdminControlError("ADMIN-RESET-PREVIEW-STALE")
        if self._descriptor_path().exists():
            raise AdminControlError("ADMIN-RUNTIME-NOT-STOPPED")
        return payload

    def apply_reset(
        self, token: str, *, authorize: Callable[[], None]
    ) -> dict[str, Any]:
        control_root = environment_control_root(
            self._config.environment_root, self._config.environment_id
        )
        if has_reparse_point(control_root, root=Path(control_root.anchor)):
            raise AdminControlError("ADMIN-RESET-PATH")
        control_root.mkdir(parents=True, exist_ok=True)
        with environment_control_lock(
            self._config.environment_root, self._config.environment_id
        ):
            payload = self.validate_reset(token)
            identity = hashlib.sha256(str(payload["nonce"]).encode("utf-8")).hexdigest()
            receipt = control_root / ("reset-preview-" + identity + ".json")
            if receipt.exists():
                raise AdminControlError("ADMIN-RESET-PREVIEW-USED")
            authorize()
            # Reserve durably before dispatch. An interrupted reset is unknown;
            # another key/process must not silently replay the destructive work.
            with receipt.open("xb") as stream:
                stream.write(
                    _canonical(
                        {
                            "state": "started",
                            "environment_id": self._config.environment_id,
                            "incarnation": self._config.environment_incarnation,
                        }
                    )
                )
                stream.flush()
                os.fsync(stream.fileno())
            self.maintenance(
                MaintenanceInvocation.model_validate(
                    {
                        "environment_root": self._config.environment_root,
                        "environment_id": self._config.environment_id,
                        "action": "reset",
                        "apply": True,
                    }
                )
            )
        return {
            "environment_id": self._config.environment_id,
            "previous_incarnation": self._config.environment_incarnation,
            "incarnation": self._config.environment_incarnation + 1,
            "status": "reset",
        }

    def initialize_environment(
        self, birth_mode: Literal["unborn", "manifest"]
    ) -> dict[str, Any]:
        if self._descriptor_path().exists():
            raise AdminControlError("ADMIN-RUNTIME-NOT-STOPPED")
        if self._config.template_manifest is not None:
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
            self.maintenance(
                MaintenanceInvocation.model_validate(
                    {
                        "environment_root": self._config.environment_root,
                        "environment_id": self._config.environment_id,
                        "action": "birth",
                    }
                )
            )
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
        if command not in {
            "status",
            "drain",
            "stop",
            "input",
            "fault",
            "other_human",
            "data_deletion",
        }:
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
        request_id = str(uuid7())
        request = _canonical(
            {
                "schema_version": "armi.runtime-admin-control.v1",
                "request_id": request_id,
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
        except (
            OSError,
            TimeoutError,
            UnicodeDecodeError,
            json.JSONDecodeError,
            struct.error,
            ValueError,
        ) as exc:
            raise AdminControlError("ADMIN-CONTROL-UNAVAILABLE") from exc
        if not isinstance(response, dict):
            raise AdminControlError("ADMIN-CONTROL-PROTOCOL")
        typed_response = cast(dict[str, Any], response)
        if typed_response.get("request_id") != request_id:
            raise AdminControlError("ADMIN-CONTROL-PROTOCOL")
        if typed_response.get("status") == "rejected":
            code = typed_response.get("error_code")
            if isinstance(code, str) and re.fullmatch(r"[A-Z][A-Z0-9-]{1,127}", code):
                raise AdminControlError(code)
            raise AdminControlError("ADMIN-CONTROL-PROTOCOL")
        if typed_response.get("status") != "succeeded" or not isinstance(
            typed_response.get("result"), dict
        ):
            raise AdminControlError("ADMIN-CONTROL-PROTOCOL")
        return typed_response

    def wait_until_stopped(self, timeout_seconds: float = 30.0) -> None:
        deadline = time.monotonic() + timeout_seconds
        while self._descriptor_path().exists():
            if time.monotonic() >= deadline:
                raise AdminControlError("ADMIN-CONTROL-STOP-TIMEOUT")
            time.sleep(0.1)

    def ensure_runtime_stopped(self) -> None:
        self._process().stop()

    def runtime_status(self) -> dict[str, Any]:
        return self._process().status()

    def _process(self) -> RuntimeProcessManager:
        return RuntimeProcessManager(
            self._config.environment_root,
            self._config.environment_id,
            incarnation=self._config.environment_incarnation,
        )

    def _require_reset_environment(self) -> None:
        if (
            not self._config.resettable
            and self._config.environment_kind.value != "active"
        ):
            raise AdminControlError("ADMIN-ENVIRONMENT-NOT-RESETTABLE")

    def _database_catalog_digest(self) -> str:
        return self._observation.database_catalog_digest()

    def _restore_template(self) -> None:
        manifest = self._validate_template_manifest()
        del manifest
        if self._config.template_manifest is None:
            raise AdminControlError("ADMIN-TEMPLATE-REQUIRED")
        source_root = self._config.template_manifest.parent / "environment-template"
        if not source_root.is_dir() or source_root.is_symlink():
            raise AdminControlError("ADMIN-TEMPLATE-ROOT")
        shutil.copytree(source_root, self._config.environment_root, symlinks=False)

    def _validate_template_manifest(self) -> dict[str, Any]:
        if self._config.template_manifest is None:
            raise AdminControlError("ADMIN-TEMPLATE-REQUIRED")
        manifest = self._read_json(
            self._config.template_manifest, "ADMIN-TEMPLATE-MANIFEST"
        )
        if (
            manifest.get("schema_version") != "armi.admin-experiment-environment.v1"
            or manifest.get("environment_id") != self._config.environment_id
        ):
            raise AdminControlError("ADMIN-TEMPLATE-IDENTITY")
        return manifest

    def _install_database(self) -> None:
        self.maintenance(
            MaintenanceInvocation.model_validate(
                {
                    "environment_root": self._config.environment_root,
                    "environment_id": self._config.environment_id,
                    "action": "database_install",
                }
            )
        )

    def maintenance(
        self, request: MaintenanceInvocation | ConfigurationInvocation
    ) -> dict[str, Any]:
        if (
            str(request.environment_id) != self._config.environment_id
            or request.environment_root != self._config.environment_root
        ):
            raise AdminControlError("ADMIN-ENVIRONMENT-MISMATCH")
        environment = self._runtime_environment()
        if isinstance(request, MaintenanceInvocation) and request.action in {
            "database_install",
            "database_maintain",
            "reset",
        }:
            with self._credentials.resolve(
                self._config.migrator_locator, CredentialPurpose("database.migrator")
            ) as handle:
                handle.consume(
                    lambda value: environment.__setitem__(
                        "ARMI_SECRET_MIGRATOR_DATABASE", bytes(value).decode("utf-8")
                    )
                )
        try:
            completed = subprocess.run(
                [sys.executable, "-m", "armi_runtime.maintenance_worker"],
                input=request.model_dump_json().encode("utf-8"),
                capture_output=True,
                cwd=self._config.environment_root,
                env=environment,
                timeout=600,
                check=False,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            )
        except subprocess.TimeoutExpired:
            raise AdminControlError("ADMIN-MAINTENANCE-UNKNOWN") from None
        try:
            if len(completed.stdout) > 2 * 1024 * 1024:
                raise ValueError
            payload = cast(dict[str, Any], json.loads(completed.stdout))
            if completed.returncode or payload.get("status") != "succeeded":
                code = payload.get("error_code")
                raise AdminControlError(
                    code if isinstance(code, str) else "ADMIN-MAINTENANCE-FAILED"
                )
            return cast(dict[str, Any], payload["result"])
        except ValueError, KeyError, TypeError:
            raise AdminControlError("ADMIN-MAINTENANCE-RESPONSE") from None

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
        except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
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
        return {
            "PYTHONUTF8": "1",
            **{
                name: value
                for name, value in os.environ.items()
                if name in allowed
                or (
                    name.startswith("ARMI_SECRET_")
                    and name
                    not in {
                        "ARMI_SECRET_ADMIN_DATABASE",
                        "ARMI_SECRET_ADMIN_PREVIEW_KEY",
                        "ARMI_SECRET_MIGRATOR_DATABASE",
                    }
                )
            },
        }


__all__ = ("AdminControlError", "AdminControlPlane")
