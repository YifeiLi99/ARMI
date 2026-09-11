"""Program activation and retained-environment registration for the installer."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from armi_local_control import private_directory, write_control
from armi_local_control.runtime_process import LocalProcessLock
from pydantic import BaseModel, ConfigDict

from .distribution import BundleDatabase


class EnvironmentProgramBinding(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)
    package_family: str | None
    database: BundleDatabase


class EnvironmentIndex(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)
    schema_version: Literal["armi.installation-environments.v2"]
    installation_root: str
    environments: list[str]


def installed_root(program: Path) -> Path | None:
    from armi_local_control.windows_package import data_root, package_identity

    identity = package_identity()
    if identity is None:
        return None
    if identity.program_root != program:
        raise ValueError("MSIX-PROGRAM-IDENTITY")
    return data_root()


def environment_index(installation: Path) -> Path:
    return installation / "control/environments.yaml"


def registered_environments(installation: Path) -> tuple[Path, ...]:
    path = environment_index(installation)
    if not path.exists():
        return ()
    value = EnvironmentIndex.model_validate_json(path.read_bytes())
    if value.installation_root != str(installation):
        raise ValueError("INSTALLER-ENVIRONMENT-INDEX")
    paths = value.environments
    if any(
        not Path(item).is_absolute()
        or Path(item).parent != installation / "environments"
        for item in paths
    ):
        raise ValueError("INSTALLER-ENVIRONMENT-INDEX")
    return tuple(Path(item) for item in paths)


def register_environment(program: Path, environment: Path) -> None:
    installation = installed_root(program)
    if installation is None:
        return  # Standalone build/test payloads never register a desktop installation.
    if environment.parent != installation / "environments":
        raise ValueError("INSTALLER-ENVIRONMENT-BOUNDARY")
    path = environment_index(installation)
    private_directory(path.parent)
    with LocalProcessLock(path.parent / "index.lock"):
        roots = set(registered_environments(installation))
        roots.add(environment)
        write_control(
            path,
            {
                "schema_version": "armi.installation-environments.v2",
                "installation_root": str(installation),
                "environments": sorted(str(root) for root in roots),
            },
        )


def environment_binding(environment: Path) -> EnvironmentProgramBinding:
    return EnvironmentProgramBinding.model_validate_json(
        (environment / ".setup/program.json").read_bytes()
    )
