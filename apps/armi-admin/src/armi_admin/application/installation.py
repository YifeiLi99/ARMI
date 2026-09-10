"""Installation use cases shared by desktop, setup CLI, and setup MCP."""

from __future__ import annotations

import json
import os
import secrets
from collections.abc import Callable
from pathlib import Path
from typing import Any, Literal, Self
from uuid import UUID, uuid7

import psycopg
from armi_kernel.application import PersonalityAnchor
from armi_local_control import (
    NativePostgreSQL,
    PostgreSQLControlBinding,
    free_loopback_port,
    private_directory,
    program_installation_root,
    write_control,
)
from armi_local_control.configuration.models import AbsolutePath
from armi_local_control.configuration.paths import has_reparse_point
from armi_local_control.runtime_process import LocalProcessLock
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from psycopg.conninfo import make_conninfo
from pydantic import BaseModel, ConfigDict, Field, SecretStr, model_validator

from .configuration import AdminConfig
from .deployment import register_environment
from .distribution import ProgramBundle
from .package_identity import admin_package_set_digest
from .postgresql_bootstrap import apply_policy, inspect_policy, physical_role_name


class SetupError(RuntimeError):
    """Redacted installation failure; never include input values in the message."""


ProviderCredential = Literal[
    "model.ark_api_key",
    "speech.volc_credentials",
    "codex.auth_json",
    "channel.qq.napcat_access_token",
    "channel.qq.napcat_event_secret",
]
_PROVIDER_CREDENTIALS = (
    "model.ark_api_key",
    "speech.volc_credentials",
    "codex.auth_json",
    "channel.qq.napcat_access_token",
    "channel.qq.napcat_event_secret",
)


class SetupCredentialRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    name: ProviderCredential
    action: Literal["put", "remove", "status"]
    value: SecretStr | None = None


class SetupPaths(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    environment_root: AbsolutePath
    installation_root: AbsolutePath

    @model_validator(mode="after")
    def contained_data(self) -> Self:
        program_boundary = program_installation_root(self.installation_root)
        if self.environment_root.parent != program_boundary / "environments":
            raise ValueError("SETUP-ENVIRONMENT-BOUNDARY")
        if self.environment_root.drive.startswith("\\\\"):
            raise ValueError("SETUP-LOCAL-DIRECTORY-REQUIRED")
        if has_reparse_point(
            self.environment_root, root=Path(self.environment_root.anchor)
        ):
            raise ValueError("SETUP-ENVIRONMENT-BOUNDARY")
        return self

    @property
    def postgresql_root(self) -> Path:
        return self.installation_root / "postgresql/pgsql"

    @property
    def runtime_defaults(self) -> Path:
        return self.installation_root / "resources/runtime.yaml"

    @property
    def creator_web(self) -> Path:
        return self.installation_root / "resources/creator-web"


class SetupIdentity(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    schema_version: Literal["armi.setup-state.v1"] = "armi.setup-state.v1"
    operation_id: str
    environment_id: str
    creator_party_id: str
    delegate_id: str
    birth_request_id: str
    postgresql_port: int = Field(ge=1024, le=65535)
    creator_port: int = Field(ge=1024, le=65535)
    stage: Literal["claimed", "configured", "roles_ready", "installing", "ready"]


_DAILY_SCOPES = (
    "health",
    "capabilities",
    "doctor",
    "schema_status",
    "runtime_status",
    "environment_start",
    "environment_stop",
    "environment_restart",
    "environment_status",
    "configuration.read",
    "configuration.validate",
    "configuration.preview",
    "configuration.apply",
    "configuration.status",
    "invocation_get",
    "invocation_wait",
    "invocation_reconcile",
    "maintenance.database_check",
    "maintenance.credential_check",
    "maintenance.device_bindings",
    "maintenance.voice_devices",
    "maintenance.vision_sources",
    "maintenance.birth",
    "maintenance.semantic_install",
    "maintenance.semantic_calibrate",
    "maintenance.semantic_status",
    "maintenance.napcat_status",
    "maintenance.napcat_start",
    "maintenance.napcat_open",
    "maintenance.mood_display_probe",
    "maintenance.database_install",
    "environment_initialize",
)


class SetupApplication:
    def __init__(
        self,
        paths: SetupPaths,
        admin_operation: Callable[[str, dict[str, Any]], dict[str, Any]],
        login_startup: Callable[[bool | None], dict[str, object]] | None = None,
    ) -> None:
        self._admin_operation = admin_operation
        self._login_startup = login_startup
        self.paths = paths
        self.root = paths.environment_root
        if has_reparse_point(self.root, root=Path(self.root.anchor)):
            raise SetupError("SETUP-LOCAL-DIRECTORY-REQUIRED")
        self.control = self.root / ".setup"
        self.state_path = self.control / "operation.json"

    def _read(self) -> SetupIdentity:
        try:
            return SetupIdentity.model_validate_json(self.state_path.read_bytes())
        except OSError, ValueError:
            raise SetupError("SETUP-STATE-UNAVAILABLE") from None

    def check(self) -> dict[str, object]:
        bundle = ProgramBundle.read(self.paths.installation_root)
        bundle.verify(self.paths.installation_root)
        if bundle.package_set_digest != admin_package_set_digest():
            raise SetupError("SETUP-PROGRAM-IDENTITY-MISMATCH")
        return {
            "status": "ready",
            "package_id": bundle.package_id,
            "signed": bundle.signed,
        }

    def _save(self, state: SetupIdentity, stage: str) -> SetupIdentity:
        result = SetupIdentity.model_validate({**state.model_dump(), "stage": stage})
        write_control(self.state_path, result.model_dump(mode="json"))
        return result

    def _secret(self, name: str, factory: Any) -> bytes:
        # Called only while holding the initialization lock of a claimed new root.
        path = self.root / "secrets" / name
        if path.exists():
            return path.read_bytes()
        value: bytes = factory()
        with path.open("xb") as output:
            output.write(value)
            output.flush()
            os.fsync(output.fileno())
        return value

    def _locator(self, name: str) -> str:
        return "file:" + (self.root / "secrets" / name).as_posix()

    def _database(self, state: SetupIdentity) -> NativePostgreSQL:
        return NativePostgreSQL(
            PostgreSQLControlBinding(
                ownership="exclusive",
                installation_root=self.paths.postgresql_root,
                data_directory=self.root / "postgresql/data",
                port=state.postgresql_port,
            ),
            environment_root=self.root,
            environment_id=state.environment_id,
        )

    def prepare(self, *, operation_id: str) -> dict[str, object]:
        if UUID(operation_id).version != 7:
            raise SetupError("SETUP-OPERATION-ID")
        if (
            self.root.exists()
            and not self.control.exists()
            and any(self.root.iterdir())
        ):
            raise SetupError("SETUP-NEW-EMPTY-ENVIRONMENT-REQUIRED")
        self.check()
        private_directory(self.root)
        private_directory(self.control)
        with LocalProcessLock(self.control / "setup.lock"):
            if self.state_path.exists():
                state = self._read()
                if state.operation_id != operation_id:
                    raise SetupError("SETUP-OPERATION-MISMATCH")
            else:
                if any(path != self.control for path in self.root.iterdir()):
                    raise SetupError("SETUP-NEW-EMPTY-ENVIRONMENT-REQUIRED")
                postgres_port = free_loopback_port()
                creator_port = free_loopback_port()
                while creator_port == postgres_port:
                    creator_port = free_loopback_port()
                state = SetupIdentity(
                    operation_id=operation_id,
                    environment_id=str(uuid7()),
                    creator_party_id=str(uuid7()),
                    delegate_id=str(uuid7()),
                    birth_request_id=str(uuid7()),
                    postgresql_port=postgres_port,
                    creator_port=creator_port,
                    stage="claimed",
                )
                write_control(self.state_path, state.model_dump(mode="json"))
            if state.stage == "claimed":
                self._configure(state)
                state = self._save(state, "configured")
            if state.stage == "configured":
                register_environment(self.paths.installation_root, self.root)
                database = self._database(state)
                bootstrap_password = (
                    self.root / "secrets/bootstrap-password"
                ).read_text(encoding="utf-8")
                database.initialize(
                    username="armi_bootstrap", password=bootstrap_password
                )
                database.execute("start")
                with psycopg.connect(
                    host="127.0.0.1",
                    port=state.postgresql_port,
                    dbname="postgres",
                    user="armi_bootstrap",
                    password=bootstrap_password,
                    connect_timeout=10,
                ) as connection:
                    apply_policy(
                        connection,
                        environment_id=UUID(state.environment_id),
                        passwords={
                            role: (
                                self.root / "secrets" / (role + "-password")
                            ).read_text(encoding="utf-8")
                            for role in ("runtime", "admin", "migrator")
                        },
                    )
                    inspect_policy(
                        connection, environment_id=UUID(state.environment_id)
                    )
                state = self._save(state, "roles_ready")
            if state.stage == "roles_ready":
                self._database(state).execute("start")
                state = self._save(state, "installing")
                outcome = self.invoke(
                    "environment_initialize",
                    {
                        "birth_mode": "unborn",
                        "idempotency_key": operation_id,
                    },
                )
                if outcome["status"] != "succeeded":
                    return {
                        "status": "incomplete",
                        "stage": state.stage,
                        "operation": outcome,
                    }
                state = self._save(state, "ready")
            if state.stage == "installing":
                # The existing Admin invocation owns database installation recovery.
                # Do not replay installation against a possibly committed baseline.
                self._database(state).execute("start")
                reconciliation = self.invoke(
                    "invocation_reconcile",
                    {
                        "operation_name": "environment_initialize",
                        "idempotency_key": operation_id,
                    },
                )
                receipt: dict[str, Any] = reconciliation.get("result") or {}
                original: dict[str, Any] = receipt.get("result") or {}
                if (
                    receipt.get("state") == "finished"
                    and original.get("status") == "succeeded"
                ):
                    state = self._save(state, "ready")
                else:
                    return {
                        "status": "reconcile_required",
                        "operation_id": operation_id,
                        "operation": reconciliation,
                    }
            return {
                "status": "ready",
                "environment_id": state.environment_id,
            }

    def birth(self, anchor: PersonalityAnchor) -> dict[str, Any]:
        with LocalProcessLock(self.control / "setup.lock"):
            state = self._read()
            if state.stage != "ready":
                raise SetupError("SETUP-INITIALIZATION-INCOMPLETE")
            manifest: dict[str, object] = {
                "schema_version": "armi.birth-manifest.v1",
                "environment_id": state.environment_id,
                "birth_request_id": state.birth_request_id,
                "creator_party_id": state.creator_party_id,
                "idempotency_key": state.birth_request_id,
                "personality_anchor": {
                    "schema_version": anchor.schema_version,
                    "voice_style": anchor.voice_style,
                    "traits": list(anchor.traits),
                },
            }
            path = self.root / "bootstrap/birth-manifest.json"
            if path.exists():
                if json.loads(path.read_bytes()) != manifest:
                    raise SetupError("SETUP-BIRTH-REQUEST-MISMATCH")
            else:
                write_control(path, manifest)
            self._database(state).execute("start")
            return self.invoke(
                "maintenance",
                {"action": "birth", "idempotency_key": state.birth_request_id},
            )

    def _configure(self, state: SetupIdentity) -> None:
        private_directory(self.root / "secrets")
        for directory in ("data", "bootstrap"):
            (self.root / directory).mkdir(exist_ok=True)
        bundle = ProgramBundle.read(self.paths.installation_root)
        write_control(
            self.control / "program.json",
            {
                "installation_root": str(self.paths.installation_root),
                "database": bundle.database.model_dump(mode="json"),
            },
        )
        for role in ("bootstrap", "runtime", "admin", "migrator"):
            self._secret(role + "-password", lambda: secrets.token_urlsafe(48).encode())
        for role in ("runtime", "admin", "migrator"):
            password = (self.root / "secrets" / (role + "-password")).read_text(
                encoding="utf-8"
            )
            dsn = make_conninfo(
                host="127.0.0.1",
                port=state.postgresql_port,
                dbname="postgres",
                user=physical_role_name(UUID(state.environment_id), role),
                password=password,
                connect_timeout=10,
            )
            self._secret(role + "-database", lambda dsn=dsn: dsn.encode())
        for name in (
            "admin-preview",
            "creator-bearer",
            "interaction",
            "data-rights-identity",
        ):
            self._secret(name, lambda: secrets.token_urlsafe(48).encode())
        signing = self._secret(
            "creator-authorization",
            lambda: Ed25519PrivateKey.generate().private_bytes(
                serialization.Encoding.PEM,
                serialization.PrivateFormat.PKCS8,
                serialization.NoEncryption(),
            ),
        )
        key = serialization.load_pem_private_key(signing, password=None)
        if not isinstance(key, Ed25519PrivateKey):
            raise SetupError("SETUP-SIGNING-KEY-TYPE")
        environment: dict[str, object] = {
            "environment": {
                "environment_id": state.environment_id,
                "data_root": str(self.root / "data"),
            },
            "creator": {"port": state.creator_port},
            "secret_locators": {
                **{
                    name: self._locator("provider-" + name)
                    for name in _PROVIDER_CREDENTIALS
                },
                "database.runtime": self._locator("runtime-database"),
                "database.migrator": self._locator("migrator-database"),
                "creator.bearer": self._locator("creator-bearer"),
                "data_rights.identity_token_key": self._locator("data-rights-identity"),
            },
        }
        write_control(self.root / "environment.yaml", environment)
        config = AdminConfig.model_validate(
            {
                "schema_version": "armi.admin-config.v8",
                "operator_id": "native-local-admin",
                "authorized_operations": list(_DAILY_SCOPES),
                "environment_kind": "active",
                "environment_id": state.environment_id,
                "environment_incarnation": 1,
                "resettable": False,
                "test_controls_enabled": False,
                "environment_root": self.root,
                "postgresql_client_root": self.paths.postgresql_root,
                "runtime_defaults_path": self.paths.runtime_defaults,
                "creator_web_resources": self.paths.creator_web,
                "postgresql_control": self._database(state).binding,
                "database_locator": self._locator("admin-database"),
                "migrator_database_locator": self._locator("migrator-database"),
                "preview_key_locator": self._locator("admin-preview"),
                "authorization_public_key": key.public_key().public_bytes_raw().hex(),
                "expected": {"package_set_digest": admin_package_set_digest()},
            }
        )
        write_control(self.root / "admin.yaml", config.model_dump(mode="json"))
        issuer = config.model_dump(mode="json")
        issuer.update(
            {
                "operator_id": "native-creator-issuer",
                "authorized_operations": ["authorization_approve"],
                "authorization_signing_key_locator": self._locator(
                    "creator-authorization"
                ),
            }
        )
        write_control(
            self.root / "issuer.yaml",
            AdminConfig.model_validate(issuer).model_dump(mode="json"),
        )
        delegate = {
            "delegate_id": state.delegate_id,
            "creator_party_id": state.creator_party_id,
            "credential_locator": self._locator("interaction"),
            "scopes": ["interaction.read", "interaction.write"],
        }
        write_control(
            self.root / "interaction-access.yaml",
            {
                "schema_version": "armi.interaction-access.v1",
                "environment_id": state.environment_id,
                "delegates": [delegate],
            },
        )
        write_control(
            self.root / "client.yaml",
            {
                **delegate,
                "schema_version": "armi.interaction-client.v1",
                "environment_id": state.environment_id,
                "environment_root": str(self.root),
                "endpoint": f"http://127.0.0.1:{state.creator_port}",
            },
        )

    def invoke(self, operation_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        return self._admin_operation(operation_name, arguments)

    def status(self) -> dict[str, object]:
        if not self.state_path.exists():
            return {"status": "not_configured"}
        state = self._read()
        return {
            "status": state.stage,
            "environment_id": state.environment_id,
            "operation_id": state.operation_id,
            "creator_url": f"http://127.0.0.1:{state.creator_port}/ui/",
        }

    def credential(self, request: SetupCredentialRequest) -> dict[str, object]:
        with LocalProcessLock(self.control / "setup.lock"):
            if self._read().stage != "ready":
                raise SetupError("SETUP-INITIALIZATION-INCOMPLETE")
            path = self.root / "secrets" / ("provider-" + request.name)
            if has_reparse_point(path, root=self.root):
                raise SetupError("SETUP-CREDENTIAL-PATH")
            if request.action == "put":
                if request.value is None:
                    raise SetupError("SETUP-CREDENTIAL-VALUE-REQUIRED")
                raw = request.value.get_secret_value().encode("utf-8")
                if not raw or len(raw) > 16_384 or b"\x00" in raw:
                    raise SetupError("SETUP-CREDENTIAL-VALUE-INVALID")
                temporary = path.with_suffix(path.suffix + ".pending")
                try:
                    with temporary.open("wb") as output:
                        output.write(raw)
                        output.flush()
                        os.fsync(output.fileno())
                    os.replace(temporary, path)
                finally:
                    temporary.unlink(missing_ok=True)
            elif request.action == "remove":
                path.unlink(missing_ok=True)
            return {
                "status": "configured" if path.is_file() else "missing",
                "name": request.name,
                "restart_required": request.action != "status",
            }

    def login_startup(self, enabled: bool | None) -> dict[str, object]:
        if self._login_startup is None:
            raise SetupError("SETUP-STARTUP-UNAVAILABLE")
        if self._read().stage != "ready":
            raise SetupError("SETUP-INITIALIZATION-INCOMPLETE")
        return self._login_startup(enabled)
