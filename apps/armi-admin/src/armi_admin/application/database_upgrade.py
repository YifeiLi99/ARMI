"""Local owner's explicit upgrade of an already prepared, retained database."""

from __future__ import annotations

from typing import Any, Literal, cast

import psycopg
from armi_kernel.application import CredentialPurpose
from armi_local_control import write_control
from armi_local_control.configuration.defaults import runtime_defaults_file
from armi_local_control.lifecycle import LocalEnvironmentController
from armi_local_control.windows_package import package_identity
from armi_postgresql_contract import PostgreSQLContractError
from armi_postgresql_contract.upgrades import (
    apply_upgrade,
    check_upgrade,
    supported_upgrade,
    upgrade_target,
    verify_upgrade_resources,
)
from armi_runtime_foundation import PostgreSQLAdminTransaction

from armi_admin.persistence.runtime_foundation import RuntimeFoundationAdminAdapter

from .configuration import load_admin_config
from .credentials import AdminCredentialPort
from .deployment import environment_binding
from .distribution import ProgramBundle
from .installation import SetupError, SetupPaths
from .local_authority import verify_local_owner


def database_upgrade(
    paths: SetupPaths, action: Literal["check", "apply", "status"]
) -> dict[str, Any]:
    bundle = ProgramBundle.read(paths.installation_root)
    bundle.verify(paths.installation_root)
    if bundle.database.model_dump() != upgrade_target():
        raise SetupError("SETUP-UPGRADE-PROGRAM-IDENTITY")
    config, config_path = load_admin_config(
        {"ARMI_ADMIN_CONFIG": str(paths.environment_root / "admin.yaml")},
        allow_supported_database_upgrade=True,
    )
    verify_local_owner(config, config_path)
    bound = environment_binding(paths.environment_root)
    identity = package_identity()
    if bound.package_family != (identity.family if identity else None):
        raise SetupError("SETUP-UPGRADE-PACKAGE-FAMILY")
    if bound.database != bundle.database and not supported_upgrade(
        bound.database.model_dump(), bundle.database.model_dump()
    ):
        raise SetupError("SETUP-UPGRADE-PATH-UNSUPPORTED")
    verify_upgrade_resources()
    locator = config.migrator_locator if action == "apply" else config.locator
    credentials = AdminCredentialPort(
        locator=config.locator,
        migrator_locator=config.migrator_locator,
        config_root=config_path.parent,
    )
    controller = LocalEnvironmentController(
        environment_root=config.environment_root,
        environment_id=config.environment_id,
        incarnation=config.environment_incarnation,
        defaults_path=config.runtime_defaults_path or runtime_defaults_file(),
        postgresql=config.postgresql_control,
    )

    def execute() -> dict[str, Any]:
        if action == "apply":
            controller.database("start")
        with credentials.resolve(
            locator,
            CredentialPurpose(
                "database.migrator" if action == "apply" else "database.admin"
            ),
        ) as handle:
            conninfo = handle.consume(lambda raw: bytes(raw).decode("utf-8"))
        try:
            with psycopg.connect(conninfo, connect_timeout=5) as connection:
                role = connection.execute("SELECT session_user,current_user").fetchone()
                expected = config.expected_role.removesuffix("_admin") + (
                    "_migrator" if action == "apply" else "_admin"
                )
                if role != (expected, expected):
                    raise SetupError("SETUP-UPGRADE-DATABASE-ROLE")
                if action == "apply":
                    connection.execute("SET LOCAL ROLE armi_owner")
                environment = RuntimeFoundationAdminAdapter(
                    environment_id=config.environment_id,
                    incarnation=config.environment_incarnation,
                ).environment(cast(PostgreSQLAdminTransaction, connection))
                if (
                    environment is None
                    or environment.environment_id != config.environment_id
                    or environment.incarnation != config.environment_incarnation
                ):
                    raise SetupError("SETUP-UPGRADE-ENVIRONMENT")
                result = (
                    apply_upgrade(connection)
                    if action == "apply"
                    else check_upgrade(connection)
                )
            # Database commit precedes binding refresh. A later status/apply can recover this gap.
            if action == "apply":
                write_control(
                    paths.environment_root / ".setup/program.json",
                    {
                        "package_family": bound.package_family,
                        "database": bundle.database.model_dump(mode="json"),
                    },
                )
            return {
                "status": "succeeded",
                "database_upgrade": result,
                "program_status": "deployed",
                "runtime_status": "stopped" if action == "apply" else "not_checked",
            }
        except psycopg.OperationalError:
            return {
                "status": "unknown" if action == "apply" else "failed",
                "error_code": "SETUP-UPGRADE-DATABASE-UNAVAILABLE",
                "program_status": "deployed",
                "database_status": "not_confirmed",
            }
        except PostgreSQLContractError as error:
            return {
                "status": "failed",
                "error_code": str(error),
                "program_status": "deployed",
                "database_status": "upgrade_not_completed",
            }
        except psycopg.Error as error:
            return {
                "status": "failed",
                "error_code": "SETUP-UPGRADE-" + (error.sqlstate or "DATABASE-FAILED"),
                "program_status": "deployed",
                "database_status": "upgrade_not_completed",
            }

    return controller.maintain_database(execute) if action == "apply" else execute()


__all__ = ("database_upgrade",)
