"""Installation use cases shared by desktop, setup CLI, and setup MCP."""

from __future__ import annotations

import json
import os
import secrets
import socket
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any, Literal, Self, cast
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
from armi_local_control.windows_package import package_identity
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from psycopg.conninfo import make_conninfo
from pydantic import BaseModel, ConfigDict, Field, SecretStr, model_validator

from .configuration import AdminConfig
from .deployment import environment_binding, register_environment
from .distribution import ProgramBundle
from .package_identity import admin_package_set_digest
from .postgresql_bootstrap import apply_policy, inspect_policy, physical_role_name
from .updates import UpdateAction


class SetupError(RuntimeError):
    """Redacted installation failure; never include input values in the message."""


class SetupNapcatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    action: Literal["status", "refresh", "prepare", "complete", "open_login"]
    creator_user_id: int | None = Field(default=None, gt=0, le=2**63 - 1)
    enabled: bool = False
    open_login: bool = False

    @model_validator(mode="after")
    def _accounts(self) -> Self:
        if self.enabled and self.creator_user_id is None:
            raise ValueError("NAPCAT-ACCOUNTS-REQUIRED")
        if self.open_login and not self.enabled:
            raise ValueError("NAPCAT-LOGIN-REQUIRES-ENABLE")
        return self


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
        update: Callable[[UpdateAction, bool | None], dict[str, Any]] | None = None,
        uninstall: Callable[[bool], dict[str, Any]] | None = None,
    ) -> None:
        self._admin_operation = admin_operation
        self._login_startup = login_startup
        self._update = update
        self._uninstall = uninstall
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
        identity = package_identity()
        if (self.control / "program.json").exists():
            bound = environment_binding(self.root)
            if bound.database != bundle.database or bound.package_family != (
                identity.family if identity else None
            ):
                raise SetupError("SETUP-DATABASE-CONTRACT-INCOMPATIBLE")
        return {
            "status": "ready",
            "package_id": bundle.package_id,
            "distribution": "msix" if identity else "source_payload",
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
        self.check()
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
                "package_family": identity.family
                if (identity := package_identity())
                else None,
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
                "schema_version": "armi.admin-config.v9",
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
        issuer = config.model_dump(mode="json")
        identity = package_identity()
        if identity is not None:
            issuer["expected"] = {"package_family": identity.family}
            issuer["packaged_postgresql_control"] = {
                key: value
                for key, value in issuer["postgresql_control"].items()
                if key != "installation_root"
            }
            for field in (
                "postgresql_client_root",
                "runtime_defaults_path",
                "creator_web_resources",
                "postgresql_control",
            ):
                issuer[field] = None
        write_control(
            self.root / "admin.yaml",
            AdminConfig.model_validate(issuer).model_dump(mode="json"),
        )
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
                if request.name in {"speech.volc_credentials", "codex.auth_json"}:
                    try:
                        decoded: object = json.loads(raw)
                        if not isinstance(decoded, dict):
                            raise ValueError
                        document = cast(dict[str, Any], decoded)
                        if request.name == "speech.volc_credentials" and (
                            set(document) != {"app_id", "access_token"}
                            or any(
                                type(value) is not str or not value.strip()
                                for value in document.values()
                            )
                        ):
                            raise ValueError
                    except ValueError:
                        raise SetupError("SETUP-CREDENTIAL-FORMAT-INVALID") from None
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
                "restart_required": request.action != "status"
                and request.name.startswith("channel.qq."),
            }

    def login_startup(self, enabled: bool | None) -> dict[str, object]:
        if self._login_startup is None:
            raise SetupError("SETUP-STARTUP-UNAVAILABLE")
        if enabled is True and self._read().stage != "ready":
            raise SetupError("SETUP-INITIALIZATION-INCOMPLETE")
        return self._login_startup(enabled)

    def update(
        self, action: UpdateAction, enabled: bool | None = None
    ) -> dict[str, Any]:
        if self._update is None:
            raise SetupError("UPDATE-UNAVAILABLE")
        return self._update(action, enabled)

    def uninstall(self, *, delete_data: bool = False) -> dict[str, Any]:
        if self._uninstall is None:
            raise SetupError("UNINSTALL-MSIX-REQUIRED")
        return self._uninstall(delete_data)

    def napcat(self, request: SetupNapcatRequest) -> dict[str, Any]:
        from armi_local_control.napcat_node import NapCatNode
        from armi_local_control.runtime_errors import RuntimeViolation

        node = NapCatNode(self.root)
        if request.action == "status":
            return node.status()
        state = self._read()
        if state.stage != "ready":
            raise SetupError("SETUP-INITIALIZATION-INCOMPLETE")
        if request.action == "refresh":
            return self._napcat_connection()
        with LocalProcessLock(self.control / "napcat-setup.lock"):
            try:
                if request.action == "open_login":
                    self._napcat_admin(
                        "environment_start", {"idempotency_key": str(uuid7())}
                    )
                    self._open_napcat_login()
                    return self._napcat_connection()
                if request.action == "complete":
                    if not node.login_path.exists():
                        return self._napcat_connection()
                    pending = json.loads(node.login_path.read_bytes())
                    try:
                        account_id = node.login_account()
                    except RuntimeViolation as error:
                        if error.code != "NAPCAT-LOGIN-UNAVAILABLE":
                            raise
                        return node.progress(
                            "awaiting_login", reason_codes=[error.code]
                        )
                    if account_id is None:
                        return node.progress("awaiting_login")
                    creator = pending["creator_user_id"]
                    if account_id == creator:
                        raise SetupError("NAPCAT-ACCOUNT-IDENTITIES")
                    # Claim once before Admin mutations. A crash or unknown receipt
                    # must not cause the desktop poller to replay configuration.
                    node.login_path.unlink()
                    result = self._configure_napcat(
                        SetupNapcatRequest(
                            action="prepare", creator_user_id=creator, enabled=True
                        ),
                        account_id=account_id,
                    )
                    return {**result, "account_id": account_id}
                node.install(state.environment_id)
                if request.creator_user_id is None or not request.enabled:
                    return node.progress(
                        "accounts_required",
                        required_fields=["creator_user_id"],
                    )
                return self._begin_napcat_login(request)
            except Exception as error:
                node.login_path.unlink(missing_ok=True)
                code = (
                    error.code
                    if isinstance(error, RuntimeViolation)
                    else str(error)
                    if isinstance(error, SetupError)
                    else "NAPCAT-PREPARE-FAILED"
                )
                node.progress("failed", error_code=code)
                raise

    def _open_napcat_login(self) -> None:
        webui = self.root / "tools/napcat/config/webui.json"
        if has_reparse_point(webui, root=self.root):
            raise SetupError("NAPCAT-CONFIGURATION-PATH")
        port = json.loads(webui.read_bytes())["port"]
        deadline = time.monotonic() + 60
        while True:
            try:
                with socket.create_connection(("127.0.0.1", port), timeout=1):
                    break
            except OSError:
                if time.monotonic() >= deadline:
                    raise SetupError("NAPCAT-LOGIN-UI-UNAVAILABLE") from None
                time.sleep(0.25)
        self._napcat_admin(
            "maintenance",
            {
                "action": "napcat_open",
                "auto_login": True,
                "idempotency_key": str(uuid7()),
            },
        )

    def _napcat_connection(self) -> dict[str, Any]:
        """Observe current login and transport health without replaying setup."""
        from armi_local_control.napcat_node import NapCatNode
        from armi_local_control.runtime_errors import RuntimeViolation

        node = NapCatNode(self.root)
        result = node.status()
        if not result["installed"] or result["login_pending"]:
            return result
        current = self._napcat_admin(
            "configuration", {"target": "qq", "action": "read"}
        )
        values: dict[str, Any] = current.get("values") or {}
        if not values:
            return {**result, "status": "accounts_required"}
        result.pop("error_code", None)
        result.pop("reason_codes", None)
        result.update(
            account_id=values["account_id"],
            creator_user_id=values["creator_user_id"],
            enabled=values.get("enabled", False),
        )
        if not result["enabled"]:
            return {**result, "status": "configured"}
        try:
            account = node.login_account()
        except RuntimeViolation as error:
            return {**result, "status": "unavailable", "reason_codes": [error.code]}
        if account is None:
            return {**result, "status": "login_required", "logged_in": False}
        result["logged_in"] = True
        if account != values["account_id"]:
            return {
                **result,
                "status": "misconfigured",
                "reason_codes": ["NAPCAT-EXISTING-ACCOUNT-BINDING"],
            }
        health = self._napcat_admin("maintenance", {"action": "napcat_status"})
        return {
            **result,
            "status": health.get("state", "unavailable"),
            "reason_codes": health.get("reason_codes", []),
        }

    def _napcat_admin(
        self, operation: str, arguments: dict[str, Any]
    ) -> dict[str, Any]:
        result = self.invoke(operation, arguments)
        if result.get("status") != "succeeded":
            raise SetupError(
                "NAPCAT-ADMIN-" + operation.upper().replace("_", "-") + "-UNCONFIRMED"
            )
        return result.get("result") or {}

    def _begin_napcat_login(self, request: SetupNapcatRequest) -> dict[str, Any]:
        from armi_local_control.napcat_node import NapCatNode

        node = NapCatNode(self.root)
        admin = self._napcat_admin
        current = admin("configuration", {"target": "qq", "action": "read"})
        if current.get("configuration_state") == "invalid":
            raise SetupError("NAPCAT-EXISTING-CONFIGURATION-INVALID")
        values: dict[str, Any] = current.get("values") or {}
        if values and values.get("creator_user_id") != request.creator_user_id:
            raise SetupError("NAPCAT-EXISTING-ACCOUNT-BINDING")
        if values.get("enabled"):
            # A bound account only needs login recovery, never another configure/restart.
            admin("environment_start", {"idempotency_key": str(uuid7())})
            if request.open_login:
                self._open_napcat_login()
            return self._napcat_connection()
        admin("environment_stop", {"idempotency_key": str(uuid7())})
        if values:
            admin(
                "configuration",
                {
                    "target": "qq",
                    "action": "apply",
                    "document": {**values, "enabled": False},
                    "expected_version": current["version"],
                    "idempotency_key": str(uuid7()),
                },
            )
        config = node.root / "config"
        private_directory(config)
        webui = config / "webui.json"
        if has_reparse_point(webui, root=self.root) or has_reparse_point(
            node.login_path, root=self.root
        ):
            raise SetupError("NAPCAT-CONFIGURATION-PATH")
        value: dict[str, Any] = (
            json.loads(webui.read_bytes())
            if webui.exists()
            else {
                "host": "127.0.0.1",
                "port": free_loopback_port(),
                "token": secrets.token_urlsafe(48),
            }
        )
        if value.get("host") != "127.0.0.1" or not value.get("token"):
            raise SetupError("NAPCAT-EXISTING-WEBUI-CONFIGURATION")
        value["autoLoginAccount"] = ""
        write_control(webui, value)
        write_control(node.login_path, {"creator_user_id": request.creator_user_id})
        node.progress("awaiting_login")
        admin("environment_start", {"idempotency_key": str(uuid7())})
        deadline = time.monotonic() + 60
        while True:
            try:
                with socket.create_connection(("127.0.0.1", value["port"]), timeout=1):
                    break
            except OSError:
                if time.monotonic() >= deadline:
                    raise SetupError("NAPCAT-LOGIN-UI-UNAVAILABLE") from None
                time.sleep(0.25)
        if request.open_login:
            admin(
                "maintenance",
                {
                    "action": "napcat_open",
                    "auto_login": True,
                    "idempotency_key": str(uuid7()),
                },
            )
        return node.progress("awaiting_login")

    def _configure_napcat(
        self, request: SetupNapcatRequest, *, account_id: int
    ) -> dict[str, Any]:
        from armi_local_control.napcat_node import NapCatNode

        node = NapCatNode(self.root)

        admin = self._napcat_admin

        current = admin("configuration", {"target": "qq", "action": "read"})
        if current.get("configuration_state") == "invalid":
            raise SetupError("NAPCAT-EXISTING-CONFIGURATION-INVALID")
        values: dict[str, Any] = current.get("values") or {}
        if values and (
            values.get("account_id") != account_id
            or values.get("creator_user_id") != request.creator_user_id
        ):
            raise SetupError("NAPCAT-EXISTING-ACCOUNT-BINDING")
        node.progress("stopping")
        admin("environment_stop", {"idempotency_key": str(uuid7())})
        node.progress("configuring")
        for path in (
            node.root / "config",
            node.root / "config/webui.json",
            node.root / f"config/onebot11_{account_id}.json",
            self.root / "secrets/provider-channel.qq.napcat_access_token",
            self.root / "secrets/provider-channel.qq.napcat_event_secret",
        ):
            if has_reparse_point(path, root=self.root):
                raise SetupError("NAPCAT-CONFIGURATION-PATH")
        ports: list[int] = []
        sockets: list[socket.socket] = []
        try:
            for _ in range(3):
                listener = socket.socket()
                listener.bind(("127.0.0.1", 0))
                sockets.append(listener)
                ports.append(listener.getsockname()[1])
        finally:
            for listener in sockets:
                listener.close()
        document: dict[str, Any] = values or {
            "schema_version": "armi.qq-napcat-channel.v3",
            "account_id": account_id,
            "creator_user_id": request.creator_user_id,
            "api_base_url": f"http://127.0.0.1:{ports[0]}",
            "event_port": ports[1],
            "request_body_max_bytes": 1048576,
            "reply_to_other_private_users": False,
            "reply_in_groups": False,
            "reply_private_user_allowlist": [],
            "reply_group_allowlist": [],
            "allowed_groups": {},
        }
        document["enabled"] = request.enabled
        # Validate with the configuration owner before creating transport files.
        admin(
            "configuration",
            {
                "target": "qq",
                "action": "preview",
                "document": document,
                "expected_version": current["version"],
            },
        )
        access = self._secret(
            "provider-channel.qq.napcat_access_token",
            lambda: secrets.token_urlsafe(48).encode(),
        ).decode()
        event = self._secret(
            "provider-channel.qq.napcat_event_secret",
            lambda: secrets.token_urlsafe(48).encode(),
        ).decode()
        config = node.root / "config"
        private_directory(config)
        from urllib.parse import urlsplit

        api = urlsplit(str(document["api_base_url"]))
        if api.scheme != "http" or api.hostname != "127.0.0.1" or api.port is None:
            raise SetupError("NAPCAT-LOCAL-TRANSPORT-REQUIRED")
        webui = config / "webui.json"
        if webui.exists():
            webui_config = json.loads(webui.read_bytes())
            if (
                webui_config.get("host") != "127.0.0.1"
                or type(webui_config.get("port")) is not int
                or not 1024 <= webui_config["port"] <= 65535
                or not webui_config.get("token")
                or webui_config.get("autoLoginAccount") not in ("", str(account_id))
            ):
                raise SetupError("NAPCAT-EXISTING-WEBUI-CONFIGURATION")
            write_control(webui, {**webui_config, "autoLoginAccount": str(account_id)})
        write_control(
            config / f"onebot11_{account_id}.json",
            {
                "network": {
                    "httpServers": [
                        {
                            "name": "ARMI API",
                            "enable": True,
                            "host": "127.0.0.1",
                            "port": api.port,
                            "token": access,
                            "messagePostFormat": "array",
                            "enableCors": False,
                            "enableWebsocket": False,
                        }
                    ],
                    "httpClients": [
                        {
                            "name": "ARMI Events",
                            "enable": True,
                            "url": f"http://127.0.0.1:{document['event_port']}/",
                            "token": event,
                            "messagePostFormat": "array",
                            "reportSelfMessage": False,
                        }
                    ],
                    "websocketServers": [],
                    "websocketClients": [],
                },
            },
        )
        if not webui.exists():
            write_control(
                webui,
                {
                    "host": "127.0.0.1",
                    "port": ports[2],
                    "token": secrets.token_urlsafe(48),
                    "autoLoginAccount": str(account_id),
                },
            )
        admin(
            "configuration",
            {
                "target": "qq",
                "action": "apply",
                "document": document,
                "expected_version": current["version"],
                "idempotency_key": str(uuid7()),
            },
        )
        if not request.enabled:
            return node.progress("configured", enabled=False)
        node.progress("starting")
        admin("environment_start", {"idempotency_key": str(uuid7())})
        webui_port = json.loads(webui.read_bytes())["port"]
        deadline = time.monotonic() + 60
        while True:
            try:
                with socket.create_connection(("127.0.0.1", webui_port), timeout=1):
                    break
            except OSError:
                if time.monotonic() >= deadline:
                    raise SetupError("NAPCAT-LOGIN-UI-UNAVAILABLE") from None
                time.sleep(0.25)
        if request.open_login:
            admin(
                "maintenance",
                {
                    "action": "napcat_open",
                    "auto_login": True,
                    "idempotency_key": str(uuid7()),
                },
            )
        node.progress(
            "starting",
            account_id=account_id,
            enabled=True,
            webui_url=f"http://127.0.0.1:{webui_port}/webui/",
        )
        return self._napcat_connection()
