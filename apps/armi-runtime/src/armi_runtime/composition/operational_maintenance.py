"""Explicit operator entry points for P0 retention and database maintenance."""

from __future__ import annotations

from armi_artifact_store.bootstrap import bootstrap_artifact_catalog
from armi_artifact_store.content_store import (
    ContentAddressedArtifactStore,
)
from armi_kernel.application import (
    ArtifactViolation,
    CredentialPurpose,
)

from armi_runtime.adapters.persistence.database_maintenance import (
    DatabaseMaintenanceReport,
    PostgreSQLDatabaseMaintenance,
)
from armi_runtime.adapters.persistence.maintenance_guard import (
    PostgreSQLMaintenanceGuard,
)
from armi_runtime.adapters.persistence.unit_of_work import (
    PostgreSQLUnitOfWorkFactory,
)
from armi_runtime.adapters.transaction_errors import DatabaseTransactionError

from .artifacts import (
    ArtifactCleanupReport,
    ArtifactOrphanReport,
    ContentAddressedArtifactCoordinator,
)
from .configuration import ConfigurationViolation
from .database import MIGRATOR_LOCATOR_NAME, RUNTIME_LOCATOR_NAME
from .environment import PreparedEnvironment
from .runtime_errors import RuntimeViolation


async def run_artifact_retention(
    prepared: PreparedEnvironment,
    *,
    apply: bool,
) -> ArtifactOrphanReport | ArtifactCleanupReport:
    """Inspect or explicitly clean only proven local artifact orphans."""

    locator = prepared.effective.config.secret_locators.get(RUNTIME_LOCATOR_NAME)
    if locator is None:
        raise RuntimeViolation(
            "MAINTENANCE-ARTIFACT-DATABASE",
            "artifact maintenance database access is unavailable",
        )
    try:
        with prepared.credential_port.resolve(
            locator,
            CredentialPurpose("database.artifact-maintenance"),
        ) as handle:

            def create(value: memoryview) -> PostgreSQLUnitOfWorkFactory:
                try:
                    conninfo = bytes(value).decode("utf-8")
                except UnicodeDecodeError:
                    raise RuntimeViolation(
                        "MAINTENANCE-ARTIFACT-DATABASE",
                        "artifact maintenance database access is unavailable",
                    ) from None

                config = prepared.effective.config
                return PostgreSQLUnitOfWorkFactory(
                    conninfo,
                    environment_id=config.environment.environment_id,
                    pool_min=1,
                    pool_max=1,
                    acquire_timeout_seconds=(
                        config.database.pool_acquire_timeout_seconds
                    ),
                    statement_timeout_seconds=(
                        config.database.diagnostic_statement_timeout_seconds
                    ),
                    require_runtime_fence=False,
                )

            factory = handle.consume(create)
    except ConfigurationViolation:
        raise RuntimeViolation(
            "MAINTENANCE-ARTIFACT-DATABASE",
            "artifact maintenance database access is unavailable",
        ) from None
    storage = ContentAddressedArtifactStore(
        prepared.data_root / "artifacts",
        max_object_bytes=prepared.effective.config.artifacts.max_object_bytes,
    )
    coordinator = ContentAddressedArtifactCoordinator(
        storage,
        bootstrap_artifact_catalog(),
        factory,
        orphan_grace_seconds=(prepared.effective.config.artifacts.orphan_grace_seconds),
    )
    try:
        await factory.open()
        await storage.prepare()
        if apply:
            async with factory.unit_of_work(
                read_only=True,
            ) as unit_of_work:
                await PostgreSQLMaintenanceGuard().require_runtime_stopped(unit_of_work)
            return await coordinator.cleanup_orphans()
        return await coordinator.report_orphans()
    except ArtifactViolation as error:
        code = (
            "MAINTENANCE-RUNTIME-ACTIVE"
            if error.code == "ART-RUNTIME-ACTIVE"
            else "MAINTENANCE-ARTIFACT-FAILED"
        )
        raise RuntimeViolation(code, "artifact maintenance did not complete") from None
    except DatabaseTransactionError:
        raise RuntimeViolation(
            "MAINTENANCE-ARTIFACT-DATABASE",
            "artifact maintenance database access is unavailable",
        ) from None
    finally:
        await factory.close()


def run_database_maintenance(
    prepared: PreparedEnvironment,
) -> DatabaseMaintenanceReport:
    """Run fixed VACUUM/ANALYZE through the scoped migrator credential."""

    locator = prepared.effective.config.secret_locators.get(MIGRATOR_LOCATOR_NAME)
    if locator is None:
        raise RuntimeViolation(
            "MAINTENANCE-DATABASE-CREDENTIAL",
            "database maintenance access is unavailable",
        )
    try:
        with prepared.credential_port.resolve(
            locator,
            CredentialPurpose("database.maintenance"),
        ) as handle:

            def execute(value: memoryview) -> DatabaseMaintenanceReport:
                try:
                    conninfo = bytes(value).decode("utf-8")
                except UnicodeDecodeError:
                    raise RuntimeViolation(
                        "MAINTENANCE-DATABASE-CREDENTIAL",
                        "database maintenance access is unavailable",
                    ) from None
                config = prepared.effective.config
                return PostgreSQLDatabaseMaintenance().run(
                    conninfo,
                    environment_id=config.environment.environment_id,
                    statement_timeout_seconds=(
                        config.database.maintenance_statement_timeout_seconds
                    ),
                    lock_timeout_seconds=(config.database.pool_acquire_timeout_seconds),
                )

            return handle.consume(execute)
    except ConfigurationViolation:
        raise RuntimeViolation(
            "MAINTENANCE-DATABASE-CREDENTIAL",
            "database maintenance access is unavailable",
        ) from None


__all__ = ("run_artifact_retention", "run_database_maintenance")
