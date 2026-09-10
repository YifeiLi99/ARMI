"""Stable paths shared by the installed application and environment control."""

from pathlib import Path


def program_installation_root(program: Path) -> Path:
    return program.parent if program.name == "app" else program


def environment_control_root(environment: Path, environment_id: str) -> Path:
    if environment.parent.name == "environments":
        return environment.parent.parent / "control/environments" / environment_id
    # Explicit standalone developer/test environments retain their independent
    # control area outside the resettable environment, within their test root.
    return environment.parent / ".armi-admin" / environment_id
