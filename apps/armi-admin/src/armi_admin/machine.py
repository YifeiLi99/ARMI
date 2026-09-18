"""Public, persistent administration binding for product machine transports."""

from __future__ import annotations

import json
from pathlib import Path
from threading import RLock
from typing import Any

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

    def close(self) -> None:
        with self._lock:
            if self._composition is not None:
                self._composition.close()
                self._composition = None
                self._configuration = None

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
            return operation.invoke(composition.service, request).model_dump(
                mode="json"
            )


__all__ = ("ADMIN_OPERATIONS", "AdminSession")
