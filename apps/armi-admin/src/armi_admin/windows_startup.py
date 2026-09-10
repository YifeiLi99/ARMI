"""Per-user, explicitly enabled login startup for one native environment."""

from __future__ import annotations

import hashlib
import subprocess
import winreg
from pathlib import Path

from armi_admin.application.deployment import installed_root


def login_startup(
    launcher: Path, environment: Path, enabled: bool | None, *, migrate: bool = False
) -> dict[str, object]:
    installation = installed_root(launcher.parent)
    if installation is not None:
        launcher = installation / launcher.name
    name = (
        "ARMI-" + hashlib.sha256(str(environment).casefold().encode()).hexdigest()[:24]
    )
    location = r"Software\Microsoft\Windows\CurrentVersion\Run"
    command = subprocess.list2cmdline(
        [
            str(launcher),
            "--environment-root",
            str(environment),
            "--background",
        ]
    )
    try:
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER, location, 0, winreg.KEY_READ
        ) as key:
            try:
                current, kind = winreg.QueryValueEx(key, name)
            except FileNotFoundError:
                current, kind = None, winreg.REG_SZ
    except FileNotFoundError:
        current, kind = None, winreg.REG_SZ
    if current is not None and (current != command or kind != winreg.REG_SZ):
        legacy = subprocess.list2cmdline(
            [
                str(launcher.with_name("armi-desktop.exe")),
                "--environment-root",
                str(environment),
                "--start",
                "--background",
            ]
        )
        if current != legacy or kind != winreg.REG_SZ:
            raise ValueError("SETUP-STARTUP-BINDING-MISMATCH")
        if enabled is None and migrate:
            enabled = True
    if enabled is True:
        if not launcher.is_absolute() or not launcher.is_file():
            raise ValueError("SETUP-STARTUP-LAUNCHER-MISSING")
        with winreg.CreateKeyEx(
            winreg.HKEY_CURRENT_USER, location, 0, winreg.KEY_SET_VALUE
        ) as key:
            winreg.SetValueEx(key, name, 0, winreg.REG_SZ, command)
        current = command
    elif enabled is False and current is not None:
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER, location, 0, winreg.KEY_SET_VALUE
        ) as key:
            winreg.DeleteValue(key, name)
        current = None
    return {
        "status": "enabled" if current else "disabled",
        "enabled": current is not None,
    }
