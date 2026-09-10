"""End only this transport when its native launcher is cancelled."""

from __future__ import annotations

import ctypes
import os
import threading
from ctypes import wintypes


def watch_launcher() -> None:
    value = os.environ.get("ARMI_LAUNCHER_PID")
    if os.name != "nt" or value is None or int(value) != os.getppid():
        return
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.WaitForSingleObject.argtypes = (wintypes.HANDLE, wintypes.DWORD)
    kernel.WaitForSingleObject.restype = wintypes.DWORD
    kernel.CloseHandle.argtypes = (wintypes.HANDLE,)
    handle = kernel.OpenProcess(0x00100000, False, int(value))
    if not handle:
        raise OSError("ARMI-LAUNCHER-UNAVAILABLE")

    def wait() -> None:
        result = kernel.WaitForSingleObject(handle, 0xFFFFFFFF)
        kernel.CloseHandle(handle)
        if result == 0:
            os._exit(2)

    threading.Thread(target=wait, name="armi-launcher-lifetime", daemon=True).start()
