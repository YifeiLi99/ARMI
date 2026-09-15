import queue
import time
import tkinter as tk
from importlib.resources import files

import win32con
import win32gui
from armi_admin.windows_tray import WindowsTray


def test_window_loads_packaged_avatar_icon():
    root = tk.Tk()
    root.withdraw()
    try:
        root.iconbitmap(str(files("armi_admin") / "icon_resources/armi.ico"))
    finally:
        root.destroy()


def test_native_tray_refresh_and_explorer_restart_preserve_exit_semantics():
    events = queue.Queue()
    tray = WindowsTray("isolated-tray-test", events.put)
    try:
        assert tray.ready.wait(5)
        tray.set_status("运行中", running=True)
        win32gui.PostMessage(tray.window, tray.taskbar_created, 0, 0)
        win32gui.PostMessage(tray.window, win32con.WM_USER + 22, 0, 0)
        assert events.get(timeout=5) == "quit"
        assert tray.thread.is_alive()
        tray.set_status("已停止")
        time.sleep(0.05)
        assert tray.thread.is_alive()
    finally:
        tray.close()
        tray.thread.join(5)
        assert not tray.thread.is_alive()
