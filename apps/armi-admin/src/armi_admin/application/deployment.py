"""Program activation and retained-environment registration for the installer."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

from armi_local_control import private_directory, write_control
from armi_local_control.runtime_process import LocalProcessLock
from pydantic import BaseModel, ConfigDict

from .distribution import BundleDatabase, ProgramBundle


class EnvironmentProgramBinding(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)
    installation_root: str
    database: BundleDatabase


class EnvironmentIndex(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)
    schema_version: Literal["armi.installation-environments.v1"]
    installation_root: str
    environments: list[str]


def installed_root(program: Path) -> Path | None:
    if program.parent.name != "versions":
        return None
    candidate = program.parent.parent
    current = candidate / ".current-version"
    if current.exists() and current.read_text(encoding="ascii").strip() == program.name:
        return candidate
    return None


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
                "schema_version": "armi.installation-environments.v1",
                "installation_root": str(installation),
                "environments": sorted(str(root) for root in roots),
            },
        )


def environment_binding(environment: Path) -> EnvironmentProgramBinding:
    return EnvironmentProgramBinding.model_validate_json(
        (environment / ".setup/program.json").read_bytes()
    )


def replacement_config(
    value: dict[str, Any], program: Path, bundle: ProgramBundle
) -> dict[str, Any]:
    return {
        **value,
        "postgresql_client_root": str(program / "postgresql/pgsql"),
        "runtime_defaults_path": str(program / "resources/runtime.yaml"),
        "creator_web_resources": str(program / "resources/creator-web"),
        "postgresql_control": {
            **value["postgresql_control"],
            "installation_root": str(program / "postgresql/pgsql"),
        },
        "expected": {"package_set_digest": bundle.package_set_digest},
    }
