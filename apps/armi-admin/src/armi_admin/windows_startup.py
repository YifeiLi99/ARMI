"""Windows owns login startup and any user or policy disable decision."""

from pathlib import Path

from armi_local_control.windows_package import data_root, package_identity, startup


def login_startup(
    launcher: Path, environment: Path, enabled: bool | None
) -> dict[str, object]:
    identity = package_identity()
    root = data_root()
    if identity is None or root is None:
        raise ValueError("SETUP-STARTUP-MSIX-REQUIRED")
    if (
        launcher != identity.program_root / "ARMI.exe"
        or environment != root / "environments/active"
    ):
        raise ValueError("SETUP-STARTUP-BINDING-MISMATCH")
    return startup(enabled)
