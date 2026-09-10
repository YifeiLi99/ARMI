"""Windows notification-area adapter; application work stays on the UI queue."""

from __future__ import annotations

import hashlib
import json
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import win32api
import win32con
import win32gui as _win32gui
import win32process
from armi_local_control.process_identity import (
    ManagedProcessIdentity,
    ManagedProcessState,
)

# The pywin32 stubs omit writable WNDCLASS properties and tuple notification
# records. Keep this dynamic native boundary behind the typed tray adapter.
win32gui: Any = _win32gui


def stop_desktop(environment: Path) -> None:
    record = environment / ".setup/desktop.json"
    if not record.exists():
        return
    process = ManagedProcessIdentity.from_wire(json.loads(record.read_bytes()))
    state = process.inspect()
    if state == ManagedProcessState.ABSENT:
        return
    identity = hashlib.sha256(str(environment).casefold().encode()).hexdigest()
    window = win32gui.FindWindow("ARMI.Tray." + identity, "ARMI")
    if (
        state != ManagedProcessState.MATCHES
        or process.environment_identity != identity
        or not window
        or win32process.GetWindowThreadProcessId(window)[1] != process.pid
    ):
        raise ValueError("INSTALLER-DESKTOP-IDENTITY")
    win32gui.PostMessage(window, win32con.WM_USER + 22, 0, 0)
    deadline = time.monotonic() + 90
    while time.monotonic() < deadline:
        if process.inspect() == ManagedProcessState.ABSENT:
            return
        time.sleep(0.1)
    raise ValueError("INSTALLER-DESKTOP-STOP-TIMEOUT")


class WindowsTray:
    def __init__(self, identity: str, emit: Callable[[str], None]) -> None:
        self.identity = identity
        self.emit = emit
        self.window: int | None = None
        self.ready = threading.Event()
        self.thread = threading.Thread(target=self._run, name="armi-tray", daemon=True)
        self.thread.start()

    def _run(self) -> None:
        instance = win32api.GetModuleHandle(None)
        window_class = win32gui.WNDCLASS()
        window_class.hInstance = instance
        window_class.lpszClassName = "ARMI.Tray." + self.identity
        window_class.lpfnWndProc = self._message
        atom = win32gui.RegisterClass(window_class)
        self.window = win32gui.CreateWindow(
            atom,
            "ARMI",
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            instance,
            None,
        )
        icon = win32gui.LoadIcon(0, win32con.IDI_APPLICATION)
        win32gui.Shell_NotifyIcon(
            win32gui.NIM_ADD,
            (
                self.window,
                0,
                win32gui.NIF_ICON | win32gui.NIF_MESSAGE | win32gui.NIF_TIP,
                win32con.WM_USER + 20,
                icon,
                "ARMI",
            ),
        )
        self.ready.set()
        try:
            win32gui.PumpMessages()
        finally:
            win32gui.Shell_NotifyIcon(win32gui.NIM_DELETE, (self.window, 0))
            win32gui.UnregisterClass(window_class.lpszClassName, instance)

    def _message(self, window: int, message: int, wparam: int, lparam: int) -> int:
        if message == win32con.WM_USER + 20:
            if lparam == win32con.WM_LBUTTONDBLCLK:
                self.emit("open")
            elif lparam == win32con.WM_RBUTTONUP:
                menu = win32gui.CreatePopupMenu()
                items = (
                    ("open", "打开对话"),
                    ("settings", "设置"),
                    ("status", "状态"),
                    ("start", "启动"),
                    ("stop", "停止"),
                    ("quit", "退出 ARMI"),
                )
                for index, (_, label) in enumerate(items, 1):
                    win32gui.AppendMenu(menu, win32con.MF_STRING, index, label)
                win32gui.SetForegroundWindow(window)
                selected = win32gui.TrackPopupMenu(
                    menu,
                    win32con.TPM_RETURNCMD | win32con.TPM_RIGHTBUTTON,
                    *win32gui.GetCursorPos(),
                    0,
                    window,
                    None,
                )
                win32gui.DestroyMenu(menu)
                if selected:
                    self.emit(items[int(selected) - 1][0])
                win32gui.PostMessage(window, win32con.WM_NULL, 0, 0)
            return 0
        if message == win32con.WM_USER + 21:
            self.emit("open" if wparam else "settings")
            return 0
        if message == win32con.WM_USER + 22:
            self.emit("quit")
            return 0
        if message == win32con.WM_QUERYENDSESSION:
            self.emit("quit")
            return 1
        if message == win32con.WM_CLOSE:
            win32gui.DestroyWindow(window)
            return 0
        if message == win32con.WM_DESTROY:
            win32gui.PostQuitMessage(0)
            return 0
        return int(win32gui.DefWindowProc(window, message, wparam, lparam))

    def close(self) -> None:
        if self.window is not None:
            win32gui.PostMessage(self.window, win32con.WM_CLOSE, 0, 0)
