"""Stable paths shared by the installed application and environment control."""

import hashlib
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


def environment_bootstrap_control_root(environment: Path) -> Path:
    """Bound directory usable before an environment identity/configuration exists."""
    identity = hashlib.sha256(
        str(environment.absolute()).casefold().encode("utf-8")
    ).hexdigest()[:24]
    return environment_control_root(environment, "bootstrap-" + identity)


def installation_diagnostic_roots(
    environment: Path, environment_id: str
) -> tuple[Path, ...]:
    roots = {
        environment / "data/logs",
        environment_control_root(environment, environment_id) / "logs",
        environment_bootstrap_control_root(environment) / "logs",
    }
    if environment.parent.name == "environments":
        installation = environment.parent.parent
        roots.add(installation / "control/logs")
        roots.add(installation / "control/emergency/logs")
        for parent, suffix in (
            (installation / "environments", "data/logs"),
            (installation / "control/environments", "logs"),
        ):
            if parent.is_dir() and not parent.is_symlink():
                roots.update(
                    child / suffix
                    for child in parent.iterdir()
                    if child.is_dir() and not child.is_symlink()
                )
    return tuple(sorted(roots))


def installation_bootstrap_log_roots(environment: Path) -> tuple[Path, ...]:
    roots = (environment_bootstrap_control_root(environment) / "logs",)
    if environment.parent.name == "environments":
        installation = environment.parent.parent
        roots += (
            installation / "control/logs",
            installation / "control/emergency/logs",
        )
    return roots
