"""Stable paths shared by the installed application and environment control."""

from pathlib import Path


def program_installation_root(program: Path) -> Path:
    from .windows_package import data_root, package_identity

    identity = package_identity()
    if identity is None:
        return program
    if program != identity.program_root:
        raise ValueError("MSIX-PROGRAM-IDENTITY")
    root = data_root()
    assert root is not None
    return root


def environment_control_root(environment: Path, environment_id: str) -> Path:
    if environment.parent.name == "environments":
        return environment.parent.parent / "control/environments" / environment_id
    # Explicit standalone developer/test environments retain their independent
    # control area outside the resettable environment, within their test root.
    return environment.parent / ".armi-admin" / environment_id
