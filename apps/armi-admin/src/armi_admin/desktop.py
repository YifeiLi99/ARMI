"""Current-user desktop adapter for the shared setup and Admin use cases."""

# ruff: noqa: RUF001

from __future__ import annotations

import argparse
import hashlib
import json
import os
import queue
import tkinter as tk
import webbrowser
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from tkinter import messagebox, ttk
from typing import Any, cast
from uuid import uuid7

from armi_local_control import (
    ManagedProcessIdentity,
    ManagedProcessState,
    private_directory,
    program_installation_root,
    write_control,
)
from armi_local_control.runtime_process import LocalProcessLock

from armi_admin.application.installation import SetupPaths
from armi_admin.composition import bootstrap_setup
from armi_admin.setup_cli import SetupRequest, dispatch
from armi_admin.windows_tray import WindowsTray


class Desktop:
    def __init__(self, root: tk.Tk, installation: Path, environment: Path) -> None:
        self.root = root
        self.installation = installation
        self.environment = environment
        self.application = bootstrap_setup(
            SetupPaths(
                environment_root=environment,
                installation_root=installation,
            )
        )
        self.events: queue.SimpleQueue[Any] = queue.SimpleQueue()
        self.executor = ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="armi-desktop"
        )
        self.busy = False
        self.closed = False
        self.configurations: dict[str, dict[str, Any]] = {}
        self.root.title("ARMI · 设置与状态")
        self.root.geometry("900x680")
        self.root.minsize(720, 520)
        self.root.protocol("WM_DELETE_WINDOW", self.hide)
        self.status = tk.StringVar(
            value="尚未配置"
            if not (environment / "admin.yaml").exists()
            else "就绪；可查看状态或启动"
        )
        ttk.Label(root, text="ARMI", font=("Segoe UI", 22, "bold")).pack(
            anchor="w", padx=24, pady=(20, 4)
        )
        ttk.Label(root, text=str(environment), wraplength=830).pack(anchor="w", padx=24)
        ttk.Label(root, textvariable=self.status, wraplength=830).pack(
            anchor="w", padx=24, pady=10
        )
        self.tabs = ttk.Notebook(root)
        self.tabs.pack(fill="both", expand=True, padx=20, pady=(0, 12))
        self._setup_tab()
        self._configuration_tab()
        self._credential_tab()
        self._devices_tab()
        self._startup_tab()
        self._optional_tab()
        controls = ttk.Frame(root)
        controls.pack(fill="x", padx=20, pady=(0, 18))
        for label, action in (
            ("打开对话", "open"),
            ("启动", "start"),
            ("停止", "stop"),
            ("状态", "status"),
            ("退出 ARMI", "quit"),
        ):
            ttk.Button(
                controls, text=label, command=lambda action=action: self.action(action)
            ).pack(side="left", padx=4)
        identity = hashlib.sha256(str(environment).casefold().encode()).hexdigest()
        self.tray = WindowsTray(identity, self.events.put)
        self.root.after(100, self._poll)

    def _setup_tab(self) -> None:
        frame = ttk.Frame(self.tabs, padding=20)
        self.tabs.add(frame, text="首次配置")
        ttk.Label(
            frame,
            text="先准备本机环境，再填写模型凭据。出生会建立唯一主体和 Creator 关系。",
            wraplength=760,
        ).pack(anchor="w", pady=(0, 14))
        ttk.Button(
            frame, text="准备环境 / 核对中断的初始化", command=self.prepare
        ).pack(anchor="w")
        ttk.Label(frame, text="人格锚点（1–8 项，以逗号分隔）").pack(
            anchor="w", pady=(20, 6)
        )
        self.traits = ttk.Entry(frame, width=70)
        self.traits.pack(fill="x")
        ttk.Label(
            frame,
            text="口吻按现有出生合同固定为“约 16 岁少女口吻”。姓名、经历和记忆将在生活中形成。",
            wraplength=760,
        ).pack(anchor="w", pady=10)
        ttk.Button(frame, text="确认出生", command=self.birth).pack(anchor="w")
        ttk.Label(
            frame,
            text="关闭窗口后继续在托盘运行。退出 ARMI 会先结束 Runtime，再停止本环境的数据库。",
            wraplength=760,
        ).pack(anchor="w", pady=24)

    def _configuration_tab(self) -> None:
        frame = ttk.Frame(self.tabs, padding=12)
        self.tabs.add(frame, text="功能与模型")
        bar = ttk.Frame(frame)
        bar.pack(fill="x")
        self.target = tk.StringVar(value="runtime")
        target_selector = ttk.Combobox(
            bar,
            textvariable=self.target,
            values=("runtime", "model-bindings", "web-search", "qq", "mood-display"),
            state="readonly",
            width=22,
        )
        target_selector.pack(side="left")
        target_selector.bind("<<ComboboxSelected>>", self._target_changed)
        ttk.Button(bar, text="读取设置", command=self.load_configuration).pack(
            side="left", padx=8
        )
        self.tree = ttk.Treeview(
            frame, columns=("value",), show="tree headings", selectmode="browse"
        )
        self.tree.heading("#0", text="设置")
        self.tree.heading("value", text="当前值")
        self.tree.column("#0", width=350)
        self.tree.column("value", width=350)
        scrollbar = ttk.Scrollbar(
            frame, orient="vertical", command=cast(Any, self.tree).yview
        )
        self.tree.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        self.tree.pack(fill="both", expand=True, pady=10)
        self.tree.bind("<<TreeviewSelect>>", self._select_setting)
        self.edit = ttk.Entry(frame)
        self.edit.pack(fill="x")
        ttk.Button(frame, text="保存所选设置", command=self.save_setting).pack(
            anchor="w", pady=8
        )
        ttk.Label(
            frame,
            text="布尔值填写 true / false；设备身份请从“设备”页选择。保存状态会说明是否需要重启。",
            wraplength=760,
        ).pack(anchor="w")
        self.setting_values: dict[str, Any] = {}

    def _credential_tab(self) -> None:
        frame = ttk.Frame(self.tabs, padding=20)
        self.tabs.add(frame, text="账号凭据")
        self.credential_name = tk.StringVar(value="model.ark_api_key")
        ttk.Combobox(
            frame,
            textvariable=self.credential_name,
            state="readonly",
            width=45,
            values=(
                "model.ark_api_key",
                "speech.volc_credentials",
                "codex.auth_json",
                "channel.qq.napcat_access_token",
                "channel.qq.napcat_event_secret",
            ),
        ).pack(anchor="w")
        ttk.Label(
            frame,
            text="凭据只保存到本环境受限文件，不显示已保存内容。语音与 Codex 使用各自正式 JSON 凭据。",
            wraplength=760,
        ).pack(anchor="w", pady=14)
        self.secret = ttk.Entry(frame, show="●", width=70)
        self.secret.pack(fill="x")
        actions = ttk.Frame(frame)
        actions.pack(anchor="w", pady=12)
        for label, action in (
            ("保存", "put"),
            ("移除", "remove"),
            ("检查是否已保存", "status"),
        ):
            ttk.Button(
                actions,
                text=label,
                command=lambda action=action: self.credential(action),
            ).pack(side="left", padx=4)

    def _devices_tab(self) -> None:
        frame = ttk.Frame(self.tabs, padding=20)
        self.tabs.add(frame, text="设备")
        bar = ttk.Frame(frame)
        bar.pack(fill="x")
        for index, (label, action) in enumerate(
            (
                ("枚举音频设备", "voice_devices"),
                ("枚举摄像头和屏幕", "vision_sources"),
                ("检查设备与第三方软件", "device_bindings"),
                ("检查凭据准备状态", "credential_check"),
            )
        ):
            ttk.Button(
                bar,
                text=label,
                command=lambda action=action: self.admin(
                    "maintenance",
                    {"action": action},
                    self.show_devices,
                ),
            ).grid(row=index // 2, column=index % 2, padx=4, pady=4, sticky="w")
        self.device_options: dict[str, list[dict[str, Any]]] = {}
        self.device_selectors: dict[str, ttk.Combobox] = {}
        for component, label in (
            ("input", "麦克风"),
            ("output", "扬声器"),
            ("camera", "摄像头"),
            ("screen", "屏幕"),
        ):
            row = ttk.Frame(frame)
            row.pack(fill="x", pady=4)
            ttk.Label(row, text=label, width=10).pack(side="left")
            selector = ttk.Combobox(row, state="readonly", width=55)
            selector.pack(side="left", fill="x", expand=True)
            self.device_selectors[component] = selector
            ttk.Button(
                row,
                text="选择",
                command=lambda component=component: self.save_device(component),
            ).pack(side="left", padx=5)
        self.devices = tk.Text(frame, height=6, wrap="word", state="disabled")
        self.devices.pack(fill="both", expand=True, pady=12)

    def _startup_tab(self) -> None:
        frame = ttk.Frame(self.tabs, padding=20)
        self.tabs.add(frame, text="登录自启")
        self.start_on_login = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            frame, text="登录 Windows 后启动 ARMI", variable=self.start_on_login
        ).pack(anchor="w")
        ttk.Label(
            frame, text="默认关闭。启用后仅作用于当前 Windows 用户。", wraplength=760
        ).pack(anchor="w", pady=12)
        ttk.Button(
            frame,
            text="读取当前设置",
            command=lambda: self.request(
                SetupRequest(action="login_startup"), self._startup_result
            ),
        ).pack(anchor="w", pady=5)
        ttk.Button(
            frame,
            text="保存",
            command=lambda: self.request(
                SetupRequest(action="login_startup", enabled=self.start_on_login.get()),
                self._startup_result,
            ),
        ).pack(anchor="w", pady=5)

    def _startup_result(self, result: dict[str, Any]) -> None:
        if isinstance(result.get("enabled"), bool):
            self.start_on_login.set(result["enabled"])

    def _optional_tab(self) -> None:
        frame = ttk.Frame(self.tabs, padding=20)
        self.tabs.add(frame, text="可选能力准备")
        ttk.Label(
            frame,
            text="这些能力默认关闭。准备完成后，再到功能设置中启用。第三方账号登录需要本人完成。",
            wraplength=760,
        ).pack(anchor="w", pady=(0, 12))
        for label, action in (
            ("语义召回准备状态", "semantic_status"),
            ("下载锁定的语义模型（需要联网）", "semantic_install"),
            ("校准语义召回", "semantic_calibrate"),
            ("检查 QQ / NapCat", "napcat_status"),
            ("启动已配置的 NapCat", "napcat_start"),
            ("打开 QQ 登录界面", "napcat_open"),
            ("核对心情显示设备", "mood_display_probe"),
        ):

            def invoke(action: str = action) -> None:
                arguments: dict[str, Any] = {
                    "action": action,
                    "idempotency_key": str(uuid7()),
                }
                if action == "semantic_install":
                    arguments["approved_official_direct"] = True
                self.admin("maintenance", arguments, self._optional_result)

            ttk.Button(frame, text=label, command=invoke).pack(anchor="w", pady=5)
        self.optional_status = tk.StringVar(value="尚未检查")
        ttk.Label(frame, textvariable=self.optional_status, wraplength=760).pack(
            anchor="w", pady=12
        )

    def _optional_result(self, result: dict[str, Any]) -> None:
        payload: dict[str, Any] = result.get("result") or {}
        keys = (
            "status",
            "state",
            "reason",
            "error_code",
            "binding_status",
            "capacity_status",
        )
        details = [str(payload[key]) for key in keys if payload.get(key) is not None]
        self.optional_status.set(
            str(result.get("error_code") or " / ".join(details) or result.get("status"))
        )

    def request(
        self,
        request: SetupRequest,
        callback: Callable[[dict[str, Any]], None] | None = None,
    ) -> None:
        if self.busy:
            self.status.set("正在处理上一项操作，请稍候。")
            return
        self.busy = True
        self.status.set("处理中…")
        future = self.executor.submit(dispatch, self.application, request)
        future.add_done_callback(
            lambda completed: self.events.put((completed.result(), callback))
        )

    def admin(
        self,
        operation: str,
        arguments: dict[str, Any],
        callback: Callable[[dict[str, Any]], None] | None = None,
    ) -> None:
        self.request(
            SetupRequest(action="admin", operation=operation, arguments=arguments),
            callback,
        )

    def prepare(self) -> None:
        state = self.application.status()
        self.request(
            SetupRequest(
                action="prepare", operation_id=str(state.get("operation_id") or uuid7())
            )
        )

    def birth(self) -> None:
        try:
            request = SetupRequest.model_validate(
                {
                    "action": "birth",
                    "personality_anchor": {
                        "schema_version": "armi.personality-anchor.v1",
                        "voice_style": "约 16 岁少女口吻",
                        "traits": [
                            part.strip()
                            for part in self.traits.get().replace("，", ",").split(",")
                            if part.strip()
                        ],
                    },
                }
            )
        except ValueError:
            self.status.set("请填写 1–8 项有效的人格锚点。")
            return
        self.request(request)

    def credential(self, action: str) -> None:
        payload = {"name": self.credential_name.get(), "action": action}
        if action == "put":
            payload["value"] = self.secret.get()
        self.secret.delete(0, "end")
        self.request(
            SetupRequest.model_validate({"action": "credential", "credential": payload})
        )

    def _target_changed(self, _event: object = None) -> None:
        self.tree.delete(*self.tree.get_children())
        self.setting_values.clear()
        self.edit.delete(0, "end")
        self.load_configuration()

    def load_configuration(self) -> None:
        target = self.target.get()
        self.admin(
            "configuration",
            {"target": target, "action": "read"},
            lambda outcome: self._configuration_loaded(target, outcome),
        )

    def _configuration_loaded(self, target: str, outcome: dict[str, Any]) -> None:
        if outcome.get("status") != "succeeded":
            return
        payload = outcome["result"]
        self.configurations[target] = payload
        if target != self.target.get():
            return
        self.tree.delete(*self.tree.get_children())
        self.setting_values.clear()
        values: dict[str, Any] = (
            payload.get("effective_on_next_start") or payload.get("values") or {}
        )

        def add(
            parent: str, values: dict[str, Any], path: tuple[str, ...] = ()
        ) -> None:
            for key, value in values.items():
                parts = (*path, key)
                item = json.dumps(parts)
                self.tree.insert(
                    parent,
                    "end",
                    iid=item,
                    text=key,
                    values=(
                        ""
                        if isinstance(value, dict)
                        else json.dumps(value, ensure_ascii=False),
                    ),
                )
                if isinstance(value, dict):
                    add(item, cast(dict[str, Any], value), parts)
                else:
                    self.setting_values[item] = value

        add("", values)

    def _select_setting(self, _event: object = None) -> None:
        selected = self.tree.selection()
        if selected and selected[0] in self.setting_values:
            value = self.setting_values[selected[0]]
            self.edit.delete(0, "end")
            self.edit.insert(
                0,
                value
                if isinstance(value, str)
                else json.dumps(value, ensure_ascii=False),
            )

    def save_setting(self) -> None:
        selected = self.tree.selection()
        if not selected or selected[0] not in self.setting_values:
            return
        item = selected[0]
        original = self.setting_values[item]
        try:
            value = (
                self.edit.get()
                if isinstance(original, str)
                else json.loads(self.edit.get())
            )
        except ValueError:
            self.status.set("输入类型不正确。")
            return
        patch = value
        for part in reversed(json.loads(item)):
            patch = {part: patch}
        target = self.target.get()
        config = self.configurations[target]
        self.admin(
            "configuration",
            {
                "target": target,
                "action": "apply",
                "patch": patch,
                "expected_version": config["version"],
                "idempotency_key": str(uuid7()),
            },
            lambda outcome: self._configuration_loaded(target, outcome),
        )

    def show_devices(self, result: dict[str, Any]) -> None:
        payload: dict[str, Any] = result.get("result") or {}
        groups: dict[str, list[dict[str, Any]]] = {}
        if "devices" in payload:
            groups["input"] = [
                {"host_api": device["host_api"], "name": device["name"]}
                for device in payload["devices"]
                if device["input_channels"] > 0
            ]
            groups["output"] = [
                {"host_api": device["host_api"], "name": device["name"]}
                for device in payload["devices"]
                if device["output_channels"] > 0
            ]
        if "cameras" in payload:
            groups["camera"] = [
                {key: device[key] for key in ("name", "device_path", "usb_location_id")}
                for device in payload["cameras"]
            ]
            groups["screen"] = payload["screens"]
        for component, devices in groups.items():
            self.device_options[component] = devices
            self.device_selectors[component].configure(
                values=[
                    f"{index + 1}. {device.get('name') or device.get('edid_name') or device.get('source_device_name')}"
                    for index, device in enumerate(devices)
                ]
            )
        lines = [
            f"{component}: 找到 {len(devices)} 项"
            for component, devices in groups.items()
        ]
        checks: list[dict[str, Any]] = payload.get("checks") or []
        labels = {
            "disabled": "未启用",
            "not_configured": "未配置",
            "matches": "已匹配",
            "ambiguous": "身份不唯一",
            "missing": "未找到",
            "unavailable": "不可用",
            "resolvable": "凭据已准备",
        }
        for check in checks:
            status = str(check.get("binding_status") or check.get("status"))
            lines.append(
                f"{check.get('component') or check.get('name')}: {labels.get(status, status)}"
            )
        if result.get("error_code"):
            lines.append(str(result["error_code"]))
        self.devices.configure(state="normal")
        self.devices.delete("1.0", "end")
        self.devices.insert("1.0", "\n".join(lines) or "没有可用结果。")
        self.devices.configure(state="disabled")

    def save_device(self, component: str) -> None:
        selected = self.device_selectors[component].current()
        if selected < 0:
            self.status.set("请先枚举并选择设备。")
            return
        device = self.device_options[component][selected]
        path = {
            "input": ("voice", "input_device"),
            "output": ("voice", "output_device"),
            "camera": ("vision", "camera", "identity"),
            "screen": ("vision", "screen", "identity"),
        }[component]
        patch: Any = device
        for part in reversed(path):
            patch = {part: patch}

        def save(current: dict[str, Any]) -> None:
            if current.get("status") == "succeeded":
                self.admin(
                    "configuration",
                    {
                        "target": "runtime",
                        "action": "apply",
                        "patch": patch,
                        "expected_version": current["result"]["version"],
                        "idempotency_key": str(uuid7()),
                    },
                )

        self.admin("configuration", {"target": "runtime", "action": "read"}, save)

    def action(self, action: str) -> None:
        if action == "settings":
            self.root.deiconify()
            cast(Any, self.root).lift()
        elif action == "open":
            self.start_on_launch(False)
        elif (
            action == "quit"
            and not (self.environment / "postgresql/cluster.json").exists()
        ):
            self._close()
        else:
            operation = (
                "environment_stop" if action == "quit" else "environment_" + action
            )
            arguments = {} if action == "status" else {"idempotency_key": str(uuid7())}
            self.admin(
                operation, arguments, self._quit_result if action == "quit" else None
            )

    def _quit_result(self, result: dict[str, Any]) -> None:
        if result.get("status") == "succeeded":
            self._close()
        else:
            self.root.deiconify()

    def _close(self) -> None:
        self.closed = True
        self.tray.close()
        self.executor.shutdown(wait=False)
        self.root.destroy()

    def hide(self) -> None:
        if self.tray.ready.is_set():
            self.root.withdraw()
        else:
            self.status.set("托盘尚未就绪，请保留此窗口。")

    def _poll(self) -> None:
        while not self.events.empty():
            event = self.events.get()
            if isinstance(event, str):
                self.action(event)
            else:
                result, callback = event
                self.busy = False
                payload: dict[str, Any] = result.get("result") or {}
                status = str(
                    result.get("error_code")
                    or payload.get("activation")
                    or result.get("status")
                )
                labels = {
                    "succeeded": "操作完成",
                    "ready": "环境准备完成",
                    "configured": "凭据已保存，连接尚未核验",
                    "missing": "未配置",
                    "effective": "已生效",
                    "restart_required": "已保存，重启后生效",
                    "saved": "已保存",
                    "not_running": "尚未运行",
                    "enabled": "登录自启已开启",
                    "disabled": "登录自启已关闭",
                    "reconcile_required": "初始化结果待核对，请保留环境数据",
                }
                if "runtime" in payload and "postgresql" in payload:
                    states = {
                        "ready": "就绪",
                        "running": "运行中",
                        "stopped": "已停止",
                        "unavailable": "不可用",
                    }
                    runtime = str(payload["runtime"].get("status"))
                    database = str(payload["postgresql"].get("status"))
                    status = f"Runtime：{states.get(runtime, runtime)} / PostgreSQL：{states.get(database, database)}"
                self.status.set(labels.get(status, status))
                if callback:
                    callback(result)
        if not self.closed:
            self.root.after(100, self._poll)

    def start_on_launch(self, background: bool) -> None:
        if self.application.status().get("status") != "ready":
            self.root.deiconify()
            return
        if self.busy:
            return

        def finished(result: dict[str, Any]) -> None:
            if result.get("status") == "succeeded":
                if not background:
                    url = self.application.status().get("creator_url")
                    if isinstance(url, str):
                        webbrowser.open(url)
                self.hide()
            elif result.get("status") != "succeeded":
                self.root.deiconify()

        self.admin("environment_start", {"idempotency_key": str(uuid7())}, finished)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="ARMI")
    parser.add_argument("--environment-root", type=Path)
    parser.add_argument("--installation-root", type=Path)
    parser.add_argument("--start", action="store_true")
    parser.add_argument("--background", action="store_true")
    args = parser.parse_args(argv)
    installation = args.installation_root or Path(os.environ["ARMI_INSTALLATION_ROOT"])
    root = tk.Tk()
    environment = (
        args.environment_root
        or program_installation_root(installation) / "environments/active"
    ).absolute()
    try:
        SetupPaths(environment_root=environment, installation_root=installation)
    except ValueError:
        messagebox.showerror("ARMI", "环境必须位于安装目录的 environments 子目录中。")
        root.destroy()
        return 1
    own_control_only = (
        environment.is_dir()
        and {path.name for path in environment.iterdir()} == {".setup"}
        and (environment / ".setup").is_dir()
        and {path.name for path in (environment / ".setup").iterdir()}
        <= {"desktop.lock", "desktop.json"}
    )
    if (
        environment.exists()
        and not (environment / ".setup/operation.json").exists()
        and any(environment.iterdir())
        and not own_control_only
    ):
        messagebox.showerror("ARMI", "新环境需要空目录；当前目录不会被接管。")
        root.destroy()
        return 1
    try:
        private_directory(environment / ".setup")
    except OSError, ValueError:
        messagebox.showerror("ARMI", "无法写入安装目录，请检查当前用户的目录权限。")
        root.destroy()
        return 1
    lock = LocalProcessLock(environment / ".setup/desktop.lock")
    identity = hashlib.sha256(str(environment).casefold().encode()).hexdigest()
    record = environment / ".setup/desktop.json"
    try:
        lock.__enter__()
    except Exception:
        import win32con
        import win32gui
        import win32process

        try:
            process = ManagedProcessIdentity.from_wire(json.loads(record.read_bytes()))
            window = win32gui.FindWindow("ARMI.Tray." + identity, "ARMI")
            if (
                process.inspect() != ManagedProcessState.MATCHES
                or win32process.GetWindowThreadProcessId(window)[1] != process.pid
            ):
                raise ValueError("identity mismatch")
            win32gui.PostMessage(window, win32con.WM_USER + 21, int(args.start), 0)
        except Exception:
            messagebox.showerror("ARMI", "已有实例的身份无法确认，请检查状态。")
        root.destroy()
        return 0
    try:
        process = ManagedProcessIdentity.capture(
            os.getpid(), environment_identity=identity, incarnation=1
        )
        write_control(record, process.to_wire())
        desktop = Desktop(root, installation, environment)
        if args.start:
            root.after(200, lambda: desktop.start_on_launch(args.background))
        root.mainloop()
    finally:
        record.unlink(missing_ok=True)
        lock.__exit__(None, None, None)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
