"""Application service behind the two static S035 Admin MCP tools."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from importlib.resources import files
from typing import Any, Literal

from armi_kernel.application import CredentialPurpose

from armi_admin.application import AdminConfig, AdminCredentialPort
from armi_admin.persistence import (
    AdminRoleSessionError,
    AdminSchemaGateway,
    AdminSchemaSnapshot,
)

from .contracts import (
    AdminIdentity,
    HealthRequest,
    HealthResult,
    SchemaStatusRequest,
    SchemaStatusResult,
)

_EXPECTED_POSTGRESQL = 180004


def _sha256(value: bytes) -> str:
    return f"sha256:{hashlib.sha256(value).hexdigest()}"


def _resource_bytes(name: str) -> bytes:
    return files("armi_admin.mcp.resources").joinpath(name).read_bytes()


@dataclass(frozen=True, slots=True)
class _ExpectedMigration:
    version: int
    name: str
    path: str
    sha256: str


class AdminToolService:
    __slots__ = (
        "_config",
        "_credentials",
        "_identity",
        "_manifest",
        "_migrations",
    )

    def __init__(
        self,
        *,
        config: AdminConfig,
        credentials: AdminCredentialPort,
    ) -> None:
        self._config = config
        self._credentials = credentials
        schema_bytes = _resource_bytes("schema-manifest.json")
        self._manifest: dict[str, Any] = json.loads(schema_bytes)
        self._migrations = tuple(
            _ExpectedMigration(
                version=int(item["version"]),
                name=str(item["name"]),
                path=str(item["path"]),
                sha256=str(item["sha256"]),
            )
            for item in self._manifest["migrations"]
        )
        manifest_digest = _sha256(schema_bytes)
        governance = json.loads(_resource_bytes("admin-mcp-manifest.json"))
        self._identity = AdminIdentity(
            package_digest=str(governance["package_surface_digest"]),
            config_digest=config.safe_digest(),
            tool_catalog_digest=str(governance["tool_catalog_digest"]),
            schema_manifest_digest=manifest_digest,
        )

    @property
    def config(self) -> AdminConfig:
        return self._config

    def health(self, request: HealthRequest) -> HealthResult:
        del request
        if (
            self._identity.schema_manifest_digest
            != self._config.expected.schema_manifest_digest
            or self._identity.package_digest != self._config.expected.package_digest
        ):
            return self._health_failure(
                "misconfigured", "rejected", "ADMIN-MANIFEST-DRIFT"
            )
        try:
            snapshot = self._read_snapshot()
            self._validate_database_identity(snapshot)
            return HealthResult(
                status="healthy",
                environment_kind=self._environment_kind(),
                environment_id=self._config.environment_id,
                identity=self._identity,
                database_reachable=True,
                role_status="verified",
            )
        except AdminRoleSessionError:
            return self._health_failure("misconfigured", "rejected", "ADMIN-DB-ROLE")
        except ValueError as exc:
            code = str(exc)
            if not code.startswith("ADMIN-DB-"):
                code = "ADMIN-DB-IDENTITY"
            return self._health_failure("misconfigured", "rejected", code)
        except Exception:
            return self._health_failure(
                "unavailable", "unavailable", "ADMIN-DB-UNAVAILABLE"
            )

    def schema_status(self, request: SchemaStatusRequest) -> SchemaStatusResult:
        target = int(self._manifest["target"]["version"])
        expected_set = str(self._manifest["migration_set_sha256"])
        if request.environment_id != self._config.environment_id:
            return SchemaStatusResult(
                status="unavailable",
                environment_id=self._config.environment_id,
                target_version=target,
                applied_version=None,
                applied_migration_count=0,
                expected_migration_set_digest=expected_set,
                observed_migration_set_digest=None,
                error_code="ADMIN-ENVIRONMENT-MISMATCH",
            )
        try:
            snapshot = self._read_snapshot()
            self._validate_database_identity(snapshot)
            return self._classify_schema(snapshot)
        except AdminRoleSessionError:
            code = "ADMIN-DB-ROLE"
        except ValueError as exc:
            code = str(exc)
            if not code.startswith("ADMIN-DB-"):
                code = "ADMIN-DB-IDENTITY"
        except Exception:
            code = "ADMIN-DB-UNAVAILABLE"
        return SchemaStatusResult(
            status="unavailable",
            environment_id=self._config.environment_id,
            target_version=target,
            applied_version=None,
            applied_migration_count=0,
            expected_migration_set_digest=expected_set,
            observed_migration_set_digest=None,
            error_code=code,
        )

    def _read_snapshot(self) -> AdminSchemaSnapshot:
        with self._credentials.resolve(
            self._config.locator,
            CredentialPurpose("database.admin"),
        ) as handle:
            conninfo = handle.consume(lambda value: bytes(value).decode("utf-8"))
        return AdminSchemaGateway(
            conninfo,
            expected_role=self._config.expected_role,
        ).read_snapshot()

    @staticmethod
    def _validate_database_identity(snapshot: AdminSchemaSnapshot) -> None:
        if snapshot.server_version_num != _EXPECTED_POSTGRESQL:
            raise ValueError("ADMIN-DB-PG-VERSION")
        if snapshot.encoding != "UTF8" or snapshot.timezone != "UTC":
            raise ValueError("ADMIN-DB-IDENTITY")

    def _classify_schema(self, snapshot: AdminSchemaSnapshot) -> SchemaStatusResult:
        rows = snapshot.migrations
        applied = rows[-1][0] if rows else None
        observed = self._migration_digest(rows)
        expected_set = str(self._manifest["migration_set_sha256"])
        expected_by_version = {item.version: item for item in self._migrations}
        status = "current"
        error_code: str | None = None
        if rows and applied is not None and applied > len(self._migrations):
            status, error_code = "ahead", "ADMIN-SCHEMA-AHEAD"
        elif [row[0] for row in rows] != list(range(1, len(rows) + 1)):
            status, error_code = "dirty", "ADMIN-SCHEMA-GAP"
        elif any(
            row[0] not in expected_by_version
            or row[1] != expected_by_version[row[0]].name
            or row[2] != expected_by_version[row[0]].sha256
            for row in rows
        ):
            status, error_code = "dirty", "ADMIN-SCHEMA-HASH"
        elif len(rows) < len(self._migrations):
            status, error_code = "behind", "ADMIN-SCHEMA-BEHIND"
        elif observed != expected_set:
            status, error_code = "dirty", "ADMIN-SCHEMA-DIGEST"
        return SchemaStatusResult(
            status=status,
            environment_id=self._config.environment_id,
            target_version=len(self._migrations),
            applied_version=applied,
            applied_migration_count=len(rows),
            expected_migration_set_digest=expected_set,
            observed_migration_set_digest=observed,
            error_code=error_code,
        )

    def _migration_digest(self, rows: tuple[tuple[int, str, str], ...]) -> str:
        expected_by_version = {item.version: item for item in self._migrations}
        lines: list[str] = []
        for version, name, digest in rows:
            path = expected_by_version.get(version)
            safe_path = (
                path.path
                if path is not None and path.name == name
                else f"schema/migrations/{version:04d}_{name}.sql"
            )
            lines.append(f"{version}\t{safe_path}\t{digest}\n")
        return _sha256("".join(lines).encode("utf-8"))

    def _health_failure(
        self,
        status: Literal["healthy", "unavailable", "misconfigured"],
        role_status: Literal["verified", "unavailable", "rejected"],
        error_code: str,
    ) -> HealthResult:
        return HealthResult(
            status=status,
            environment_kind=self._environment_kind(),
            environment_id=self._config.environment_id,
            identity=self._identity,
            database_reachable=status != "unavailable",
            role_status=role_status,
            error_code=error_code,
        )

    def _environment_kind(
        self,
    ) -> Literal["development", "system_test", "acceptance"]:
        return self._config.environment_kind.value


__all__ = ("AdminToolService",)
