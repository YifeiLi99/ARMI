"""Explicit database composition for Runtime probing and operator migration."""

from __future__ import annotations

from typing import Final

from armi_kernel.application import CredentialPort, CredentialPurpose

from armi_runtime.adapters.persistence.birth import (
    ContinuityState,
    probe_continuity,
)
from armi_runtime.adapters.persistence.schema_gateway import (
    DatabaseViolation,
    PostgreSQLSchemaGateway,
    SchemaStatus,
)

from .birth_manifest import packaged_birth_digests
from .configuration import ConfigurationViolation
from .environment import PreparedEnvironment

RUNTIME_LOCATOR_NAME: Final = "database.runtime"
MIGRATOR_LOCATOR_NAME: Final = "database.migrator"

_REASON_BY_CODE: Final = {
    "DB-CONNECTION-UNAVAILABLE": "RUNTIME_DATABASE_UNAVAILABLE",
    "DB-PG-VERSION": "RUNTIME_DATABASE_VERSION_MISMATCH",
    "DB-DATABASE-IDENTITY": "RUNTIME_DATABASE_IDENTITY_MISMATCH",
    "DB-RUNTIME-ROLE-UNSAFE": "RUNTIME_DATABASE_ROLE_UNSAFE",
    "DB-SCHEMA-MISSING": "RUNTIME_SCHEMA_MISSING",
    "DB-SCHEMA-AHEAD": "RUNTIME_SCHEMA_AHEAD",
    "DB-SCHEMA-GAP": "RUNTIME_SCHEMA_INVALID",
    "DB-SCHEMA-HASH": "RUNTIME_SCHEMA_INVALID",
    "DB-SCHEMA-DIRTY": "RUNTIME_SCHEMA_INVALID",
    "DB-SCHEMA-INVARIANT": "RUNTIME_SCHEMA_INVALID",
    "DB-MANIFEST-DRIFT": "RUNTIME_SCHEMA_INVALID",
    "DB-ROLE-MANIFEST-DRIFT": "RUNTIME_DATABASE_ROLE_POLICY_INVALID",
    "DB-ROLE-IDENTITY": "RUNTIME_DATABASE_ROLE_POLICY_INVALID",
    "DB-ROLE-ATTRIBUTES": "RUNTIME_DATABASE_ROLE_POLICY_INVALID",
    "DB-ROLE-MEMBERSHIP": "RUNTIME_DATABASE_ROLE_POLICY_INVALID",
    "DB-ROLE-GRANT": "RUNTIME_DATABASE_ROLE_POLICY_INVALID",
    "DB-ROLE-OWNER": "RUNTIME_DATABASE_ROLE_POLICY_INVALID",
    "DB-ROLE-SEARCH-PATH": "RUNTIME_DATABASE_ROLE_POLICY_INVALID",
    "DB-ROLE-SESSION-DIRTY": "RUNTIME_DATABASE_ROLE_POLICY_INVALID",
    "DB-ROLE-PUBLIC-PRIVILEGE": "RUNTIME_DATABASE_ROLE_POLICY_INVALID",
    "DB-ROLE-SECURITY-DEFINER": "RUNTIME_DATABASE_ROLE_POLICY_INVALID",
    "DB-ROLE-CREDENTIAL-SCOPE": "RUNTIME_DATABASE_ROLE_POLICY_INVALID",
}


def _with_connection(
    prepared: PreparedEnvironment,
    *,
    locator_name: str,
    purpose: str,
    operation: str,
) -> SchemaStatus:
    locator = prepared.effective.config.secret_locators.get(locator_name)
    if locator is None:
        raise DatabaseViolation(
            "DB-CONNECTION-UNAVAILABLE",
            "the required database credential locator is unavailable",
            status="unavailable",
            exit_code=3,
        )
    port: CredentialPort = prepared.credential_port
    try:
        with port.resolve(locator, CredentialPurpose(purpose)) as handle:
            gateway = PostgreSQLSchemaGateway()

            def invoke(value: memoryview) -> SchemaStatus:
                try:
                    conninfo = bytes(value).decode("utf-8")
                except UnicodeDecodeError:
                    raise DatabaseViolation(
                        "DB-CONNECTION-UNAVAILABLE",
                        "the configured PostgreSQL connection is unavailable",
                        status="unavailable",
                        exit_code=3,
                    ) from None
                if operation == "upgrade":
                    return gateway.upgrade(
                        conninfo,
                        environment_id=prepared.effective.config.environment.environment_id,
                    )
                return gateway.status(
                    conninfo,
                    environment_id=prepared.effective.config.environment.environment_id,
                    role_class="runtime",
                )

            return handle.consume(invoke)
    except ConfigurationViolation as error:
        code = (
            "DB-ROLE-CREDENTIAL-SCOPE"
            if error.code == "SEC-SECRET-PURPOSE"
            else "DB-CONNECTION-UNAVAILABLE"
        )
        raise DatabaseViolation(
            code,
            "the configured PostgreSQL connection is unavailable",
            status="unavailable",
            exit_code=3,
        ) from None


def inspect_runtime_schema(prepared: PreparedEnvironment) -> SchemaStatus:
    """Read-only Runtime probe; this path cannot invoke schema upgrade."""

    return _with_connection(
        prepared,
        locator_name=RUNTIME_LOCATOR_NAME,
        purpose="database.runtime",
        operation="status",
    )


def inspect_operator_schema(prepared: PreparedEnvironment) -> SchemaStatus:
    return _with_connection(
        prepared,
        locator_name=RUNTIME_LOCATOR_NAME,
        purpose="database.status",
        operation="status",
    )


def upgrade_operator_schema(prepared: PreparedEnvironment) -> SchemaStatus:
    return _with_connection(
        prepared,
        locator_name=MIGRATOR_LOCATOR_NAME,
        purpose="database.migrator",
        operation="upgrade",
    )


def runtime_database_reason(prepared: PreparedEnvironment) -> tuple[str, ...]:
    try:
        inspect_runtime_schema(prepared)
    except DatabaseViolation as error:
        return (_REASON_BY_CODE.get(error.code, "RUNTIME_SCHEMA_INVALID"),)
    return ()


def inspect_runtime_continuity(prepared: PreparedEnvironment) -> ContinuityState:
    locator = prepared.effective.config.secret_locators.get(RUNTIME_LOCATOR_NAME)
    if locator is None:
        return ContinuityState.INVALID
    digests = packaged_birth_digests()
    try:
        with prepared.credential_port.resolve(
            locator,
            CredentialPurpose("database.runtime"),
        ) as handle:

            def invoke(value: memoryview) -> ContinuityState:
                try:
                    conninfo = bytes(value).decode("utf-8")
                except UnicodeDecodeError:
                    return ContinuityState.INVALID
                return probe_continuity(
                    conninfo,
                    composition_digest=digests["composition_digest"],
                    schema_manifest_digest=digests["schema_manifest_digest"],
                    birth_contract_digest=digests["birth_contract_digest"],
                    creator_asset_digest=digests["creator_asset_manifest_digest"],
                )

            return handle.consume(invoke)
    except ConfigurationViolation:
        return ContinuityState.INVALID


__all__ = (
    "MIGRATOR_LOCATOR_NAME",
    "RUNTIME_LOCATOR_NAME",
    "ContinuityState",
    "DatabaseViolation",
    "inspect_operator_schema",
    "inspect_runtime_continuity",
    "inspect_runtime_schema",
    "runtime_database_reason",
    "upgrade_operator_schema",
)
