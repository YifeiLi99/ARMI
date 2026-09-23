"""Restricted Windows package APIs; source execution has no package identity."""

from __future__ import annotations

import ctypes
import json
import os
import subprocess
import tempfile
from dataclasses import dataclass
from functools import cache
from pathlib import Path
from typing import Any, cast

__all__ = (
    "PackageIdentity",
    "WindowsPackageError",
    "data_root",
    "defer_update",
    "deployment_status",
    "initialize_process_paths",
    "inspect_candidate",
    "package_identity",
    "restart_update",
    "run_owned",
    "spawn_owned",
    "startup",
    "stop_idle_host",
    "uninstall",
)


class WindowsPackageError(RuntimeError):
    """A Windows package operation failed without exposing a submitted path."""


@dataclass(frozen=True)
class PackageIdentity:
    name: str
    publisher: str
    family: str
    full_name: str
    version: str
    program_root: Path
    local_app_data: Path


def _package_path() -> Path | None:
    if os.name != "nt":
        return None
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    query = kernel.GetCurrentPackagePath
    query.argtypes = [ctypes.POINTER(ctypes.c_uint32), ctypes.c_wchar_p]
    query.restype = ctypes.c_long
    length = ctypes.c_uint32()
    result = query(ctypes.byref(length), None)
    if result == 15700:  # APPMODEL_ERROR_NO_PACKAGE: explicit source execution.
        return None
    if result != 122:  # ERROR_INSUFFICIENT_BUFFER, with the required size.
        raise WindowsPackageError("MSIX-PACKAGE-PATH")
    output = ctypes.create_unicode_buffer(length.value)
    if query(ctypes.byref(length), output) != 0:
        raise WindowsPackageError("MSIX-PACKAGE-PATH")
    return Path(output.value)


@cache
def _library() -> Any:
    root = _package_path()
    if root is None:
        raise WindowsPackageError("MSIX-PACKAGE-IDENTITY-REQUIRED")
    library = ctypes.WinDLL(str(root / "armi_windows.dll"))
    library.armi_windows_call.argtypes = [
        ctypes.c_uint32,
        ctypes.c_wchar_p,
        ctypes.c_wchar_p,
        ctypes.c_uint32,
    ]
    library.armi_windows_call.restype = ctypes.c_long
    return library


def _call(operation: int, argument: str | None = None) -> dict[str, Any]:
    output = ctypes.create_unicode_buffer(65536)
    result = _library().armi_windows_call(operation, argument, output, len(output))
    if result < 0:
        detail = output.value
        raise WindowsPackageError(
            f"MSIX-WINDOWS-{result & 0xFFFFFFFF:08X} operation={operation} {detail}".rstrip()
        )
    return json.loads(output.value)


@cache
def package_identity() -> PackageIdentity | None:
    if _package_path() is None:
        return None
    value = _call(0)
    return PackageIdentity(
        name=value["name"],
        publisher=value["publisher"],
        family=value["family"],
        full_name=value["full_name"],
        version=value["version"],
        program_root=Path(value["program_root"]),
        local_app_data=Path(value["local_app_data"]),
    )


def inspect_candidate(path: Path) -> dict[str, Any]:
    return _call(1, str(path))


def defer_update(path: Path) -> dict[str, Any]:
    return _call(2, str(path))


def restart_update(path: Path) -> dict[str, Any]:
    return _call(9, str(path))


def uninstall(*, delete_data: bool = False) -> dict[str, Any]:
    return _call(10, "delete" if delete_data else "preserve")


def startup(enabled: bool | None) -> dict[str, Any]:
    value = _call(3 if enabled is None else 4 if enabled else 5)
    states = {
        0: "disabled",
        1: "disabled_by_user",
        2: "enabled",
        3: "disabled_by_policy",
        4: "enabled_by_policy",
    }
    state = value["state"]
    return {"status": states[state], "enabled": state in {2, 4}}


def deployment_status() -> dict[str, Any]:
    return _call(0)


def data_root() -> Path | None:
    identity = package_identity()
    if identity is None:
        return None
    if identity.name == "YifeiLi99.ARMI":
        directory = "ARMI"
    elif identity.name == "YifeiLi99.ARMI.Acceptance":
        directory = "ARMI.Acceptance"
    elif identity.name == "YifeiLi99.ARMI.MsixAcceptance":
        directory = "ARMI.MsixAcceptance"
    else:
        raise WindowsPackageError("MSIX-PACKAGE-NAME")
    return identity.local_app_data / directory


def initialize_process_paths() -> None:
    root = data_root()
    if root is None:
        return
    from .native_postgresql import private_directory

    paths = {
        "LOCALAPPDATA": root / "cache/local",
        "APPDATA": root / "cache/roaming",
        "TEMP": root / "tmp",
        "TMP": root / "tmp",
    }
    for path in set(paths.values()):
        private_directory(path)
    os.environ.update({key: str(path) for key, path in paths.items()})
    tempfile.tempdir = str(root / "tmp")


class _OwnedPopen(subprocess.Popen[Any]):
    """Use CPython's pipe/wait implementation with a host-parented native spawn.

    The private _execute_child seam is covered by the locked Python toolchain's
    installed stdio and lifecycle acceptance checks.
    """

    def __init__(
        self,
        command: Any,
        *,
        environment_id: str,
        diagnostic_output: bool = False,
        **options: Any,
    ) -> None:
        self._environment_id = environment_id
        self._diagnostic_output = diagnostic_output
        super().__init__(command, **options)

    def _execute_child(
        self,
        args: Any,
        executable: Any,
        preexec_fn: Any,
        close_fds: Any,
        pass_fds: Any,
        cwd: Any,
        env: Any,
        startupinfo: Any,
        creationflags: Any,
        shell: Any,
        p2cread: Any,
        p2cwrite: Any,
        c2pread: Any,
        c2pwrite: Any,
        errread: Any,
        errwrite: Any,
        *unused: Any,
    ) -> None:
        try:
            if (
                shell
                or preexec_fn is not None
                or pass_fds
                or startupinfo is not None
                or not isinstance(args, (list, tuple))
                or not args
            ):
                raise WindowsPackageError("MSIX-HOST-SPAWN-OPTIONS")
            command = [os.fsdecode(value) for value in cast(list[Any], args)]
            variables = os.environ if env is None else env
            result = _call(
                7,
                json.dumps(
                    {
                        "environment_id": self._environment_id,
                        "diagnostic_output": self._diagnostic_output,
                        "executable": os.fsdecode(executable or command[0]),
                        "command": subprocess.list2cmdline(command),
                        "cwd": os.fsdecode(cwd) if cwd is not None else os.getcwd(),
                        "creationflags": creationflags,
                        "handles": [int(p2cread), int(c2pwrite), int(errwrite)],
                        "environment": [
                            f"{key}={value}"
                            for key, value in sorted(
                                variables.items(), key=lambda item: item[0].upper()
                            )
                        ],
                    }
                ),
            )
            self._child_created = True
            self._handle = cast(Any, subprocess).Handle(int(result["handle"]))
            self.pid = int(result["pid"])
        finally:
            cast(Any, self)._close_pipe_fds(
                p2cread, p2cwrite, c2pread, c2pwrite, errread, errwrite
            )


def spawn_owned(
    command: Any,
    *,
    environment_id: str,
    diagnostic_output: bool = False,
    **options: Any,
) -> subprocess.Popen[Any]:
    """Create inside the independently activated host's process and Job tree."""
    if package_identity() is None:
        return subprocess.Popen(command, **options)
    _call(6, environment_id)
    flags = options.get("creationflags", 0)
    if flags & subprocess.CREATE_BREAKAWAY_FROM_JOB:
        raise WindowsPackageError("MSIX-HOST-BREAKAWAY-FORBIDDEN")
    return _OwnedPopen(
        command,
        environment_id=environment_id,
        diagnostic_output=diagnostic_output,
        **options,
    )


def run_owned(
    command: Any,
    *,
    environment_id: str,
    timeout: float,
    check: bool = False,
    **options: Any,
) -> subprocess.CompletedProcess[Any]:
    if package_identity() is None:
        return cast(
            subprocess.CompletedProcess[Any],
            subprocess.run(command, timeout=timeout, check=check, **options),
        )
    with spawn_owned(command, environment_id=environment_id, **options) as process:
        try:
            stdout, stderr = process.communicate(timeout=timeout)
        except BaseException:
            process.kill()
            process.wait()
            raise
        if check and process.returncode:
            raise subprocess.CalledProcessError(
                process.returncode, command, stdout, stderr
            )
        return subprocess.CompletedProcess(command, process.returncode, stdout, stderr)


def stop_idle_host(environment_id: str) -> None:
    if package_identity() is not None:
        _call(8, environment_id)
