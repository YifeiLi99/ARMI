"""Public, persistent administration binding for product machine transports."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from threading import RLock
from time import monotonic
from typing import Any
from uuid import uuid7

from armi_kernel.application import diagnostic_scope, record_diagnostic
from armi_local_control import environment_control_root, installation_diagnostic_roots
from armi_local_control.windows_package import package_identity
from armi_runtime_foundation import DiagnosticLog, bootstrap_diagnostics
from pydantic import ValidationError

from .application import (
    AdminCredentialPort,
    load_admin_config,
)
from .application.catalog import ADMIN_OPERATIONS
from .application.local_authority import verify_local_owner
from .composition import AdminComposition, bootstrap_admin


class AdminSession:
    """Rebind on configuration changes without retaining a stale database pool."""

    def __init__(self, config_path: Path, *, local_owner: bool = False) -> None:
        self.path = config_path
        self.local_owner = local_owner
        self._composition: AdminComposition | None = None
        self._configuration: str | None = None
        self._lock = RLock()
        self._diagnostic: DiagnosticLog | None = None

    def close(self) -> None:
        with self._lock:
            if self._composition is not None:
                self._composition.close()
                self._composition = None
                self._configuration = None
            if self._diagnostic is not None:
                self._diagnostic.close()
                self._diagnostic = None

    def _bound(self) -> AdminComposition:
        config, path = load_admin_config({"ARMI_ADMIN_CONFIG": str(self.path)})
        config.expected.verify()
        if self.local_owner:
            verify_local_owner(config, path)
        signature = config.model_dump_json()
        if self._composition is not None and (
            signature != self._configuration
            or self._composition.service.requires_reload
        ):
            self.close()
        if self._diagnostic is None:
            self._diagnostic = bootstrap_diagnostics(
                root=environment_control_root(
                    config.environment_root, config.environment_id
                ),
                environment_id=config.environment_id,
                service="armi-admin",
                version=package.version
                if (package := package_identity())
                else "source",
                retention_roots=installation_diagnostic_roots(
                    config.environment_root, config.environment_id
                ),
            )
        if self._composition is None:
            credentials = AdminCredentialPort(
                locator=config.locator,
                migrator_locator=config.migrator_locator,
                preview_locator=config.preview_locator,
                authorization_locator=config.authorization_signing_key_locator,
                config_root=path.parent,
            )
            self._composition = bootstrap_admin(
                config, credentials, local_owner=self.local_owner
            )
            self._configuration = signature
        return self._composition

    def permitted_operations(self) -> frozenset[str]:
        with self._lock:
            return frozenset(self._bound().service.config.authorized_operations)

    def environment(self) -> tuple[str, Path]:
        with self._lock:
            config = self._bound().service.config
            return config.environment_id, config.environment_root

    def invoke(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            operation = next(
                (item for item in ADMIN_OPERATIONS if item.name == name), None
            )
            if operation is None:
                raise ValueError("ADMIN-OPERATION-UNKNOWN")
            composition = self._bound()
            config = composition.service.config
            payload = dict(arguments)
            for field, value in {
                "environment_id": config.environment_id,
                "environment_incarnation": config.environment_incarnation,
                "purpose": "admin." + name,
            }.items():
                if field in operation.bound_fields:
                    if field in payload and payload[field] != value:
                        raise ValueError("ADMIN-BINDING-MISMATCH")
                    payload[field] = value
            request = operation.request.model_validate_json(json.dumps(payload))
            with diagnostic_scope(request_id=uuid7()):
                started = monotonic()
                record_diagnostic(
                    "admin.operation.started", component="admin", operation=name
                )
                try:
                    result = operation.invoke(composition.service, request).model_dump(
                        mode="json"
                    )
                except Exception as error:
                    record_diagnostic(
                        "admin.operation.failed",
                        component="admin",
                        level=logging.ERROR,
                        error=error,
                        operation=name,
                    )
                    if isinstance(error, ValidationError):
                        raise RuntimeError(
                            "ADMIN-EXECUTION-CONTRACT-INVALID"
                        ) from error
                    raise
                record_diagnostic(
                    "admin.operation.completed",
                    component="admin",
                    operation=name,
                    status=result["status"],
                    result_code=result.get("error_code"),
                    duration_ms=round((monotonic() - started) * 1000),
                    level=logging.ERROR
                    if result["status"] in {"failed", "unknown"}
                    else logging.INFO,
                )
                return result


__all__ = ("ADMIN_OPERATIONS", "AdminSession")
