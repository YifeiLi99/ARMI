"""Current-user desktop adapter for the shared setup and Admin use cases."""

# ruff: noqa: RUF001

from __future__ import annotations

import argparse
import hashlib
import json
import os
import queue
import time
import tkinter as tk
import webbrowser
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
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

from armi_admin.application.installation import SetupNapcatRequest, SetupPaths
from armi_admin.application.setup_operations import (
    SetupRequest,
    SetupUpdateRequest,
    dispatch,
)
from armi_admin.application.updates import UpdateAction
from armi_admin.composition import bootstrap_setup
from armi_admin.windows_tray import WindowsTray

_CREDENTIAL_NAMES = {
    "火山方舟 API Key（模型与网页搜索）": "model.ark_api_key",
    "豆包语音 API Key（识别与合成）": "speech.volc_credentials",
    "Codex 登录凭据": "codex.auth_json",
}


class Desktop:
    def __init__(self, root: tk.Tk, installation: Path, environment: Path) -> None:
        self.root = root
        cast(Any, self.root).iconbitmap(
            str(Path(__file__).parent / "icon_resources/armi.ico")
        )
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
        self.runtime_status = tk.StringVar(value="后台状态：正在读取")
        ttk.Label(root, textvariable=self.runtime_status, wraplength=830).pack(
            anchor="w", padx=24
        )
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
        self._update_tab()
        self._uninstall_tab()
        self._optional_tab()
        self._qq_tab()
        controls = ttk.Frame(root)
        controls.pack(fill="x", padx=20, pady=(0, 18))
        for label, action in (
            ("打开对话", "open"),
            ("启动", "start"),
            ("停止", "stop"),
            ("状态", "status"),
            ("退出托盘", "quit"),
            ("停止并退出", "stop_quit"),
        ):
            ttk.Button(
                controls, text=label, command=lambda action=action: self.action(action)
            ).pack(side="left", padx=4)
        identity = hashlib.sha256(str(environment).casefold().encode()).hexdigest()
        self.tray = WindowsTray(identity, self.events.put)
        self.root.after(100, self._poll)
        self.root.after(5000, self._automatic_update)
        self.root.after(1000, self._refresh_runtime_status)

    def _update_tab(self) -> None:
        frame = ttk.Frame(self.tabs, padding=20)
        self.tabs.add(frame, text="更新与数据")
        data = program_installation_root(self.installation)
        ttk.Label(
            frame,
            text=f"永久数据位置：{data}\n从 Windows 卸载 ARMI 会保留此目录。重新安装兼容版本后可接续使用。",
            wraplength=760,
        ).pack(anchor="w", pady=(0, 16))
        self.automatic_updates = tk.BooleanVar(value=True)
        ttk.Checkbutton(
            frame,
            text="自动检查并准备兼容更新（每 24 小时）",
            variable=self.automatic_updates,
            command=lambda: self._update_request(
                "automatic", self.automatic_updates.get()
            ),
        ).pack(anchor="w")
        self.update_status = tk.StringVar(value="尚未读取更新状态")
        ttk.Label(frame, textvariable=self.update_status, wraplength=760).pack(
            anchor="w", pady=16
        )
        for label, action in (
            ("读取状态", "status"),
            ("检查更新", "check"),
            ("下载并准备", "prepare"),
            ("重启并更新", "apply"),
        ):
            ttk.Button(
                frame,
                text=label,
                command=lambda action=action: self._update_request(
                    cast(UpdateAction, action)
                ),
            ).pack(anchor="w", pady=4)
        ttk.Label(
            frame,
            text="更新由 Windows 部署；数据库合同不兼容时不会自动更新。准备完成后，下次启动生效，也可重启并更新。",
            wraplength=760,
        ).pack(anchor="w", pady=16)

    def _uninstall_tab(self) -> None:
        frame = ttk.Frame(self.tabs, padding=20)
        self.tabs.add(frame, text="卸载")
        ttk.Label(
            frame,
            text="默认只卸载程序，保留数据库、身份、生活记录、配置和凭据。\n"
            "需要同时清理数据时，请在卸载窗口中明确勾选。\n"
            "直接从 Windows 设置卸载始终保留数据。",
            wraplength=760,
        ).pack(anchor="w", pady=(0, 20))
        ttk.Button(frame, text="卸载 ARMI…", command=self._uninstall_dialog).pack(
            anchor="w"
        )

    def _uninstall_dialog(self) -> None:
        if self.busy:
            return
        window = tk.Toplevel(self.root)
        window.title("卸载 ARMI")
        window.transient(self.root)
        window.resizable(False, False)
        frame = ttk.Frame(window, padding=24)
        frame.pack(fill="both", expand=True)
        data = program_installation_root(self.installation)
        ttk.Label(
            frame,
            text=f"将停止本机此安装版的全部环境并卸载程序。\n数据目录：{data}",
            wraplength=520,
        ).pack(anchor="w", pady=(0, 16))
        delete_data = tk.BooleanVar(master=window, value=False)
        ttk.Checkbutton(
            frame,
            text="同时永久删除全部数据（数据库、身份、生活记录、配置和凭据）",
            variable=delete_data,
        ).pack(anchor="w")
        ttk.Label(
            frame,
            text="未勾选时保留数据，重装兼容版本后可接续。\n"
            "勾选后无法恢复；数据清理与 Windows 卸载不是原子操作，失败时可能已清理部分数据。",
            wraplength=520,
        ).pack(anchor="w", pady=16)

        def submit() -> None:
            selected = delete_data.get()
            window.destroy()
            self.request(
                SetupRequest(action="uninstall", delete_data=selected),
                self._uninstall_result,
            )

        buttons = ttk.Frame(frame)
        buttons.pack(anchor="e")
        cancel = ttk.Button(buttons, text="取消", command=window.destroy)
        cancel.pack(side="left", padx=8)
        ttk.Button(buttons, text="确认卸载", command=submit).pack(side="left")
        window.bind("<Escape>", lambda _event: window.destroy())
        window.grab_set()
        cancel.focus_set()

    def _uninstall_result(self, result: dict[str, Any]) -> None:
        if result.get("status") == "uninstall_requested":
            self._close()

    def _update_request(
        self, action: UpdateAction, enabled: bool | None = None
    ) -> None:
        self.request(
            SetupRequest(
                action="update",
                update=SetupUpdateRequest(action=action, enabled=enabled),
            ),
            self._update_result,
        )

    def _update_result(self, result: dict[str, Any]) -> None:
        if isinstance(result.get("automatic"), bool):
            self.automatic_updates.set(result["automatic"])
        labels = {
            "idle": "尚未检查更新"
            if result.get("checked_at") is None
            else "当前没有可用的新版本",
            "available": "发现兼容更新，可下载准备",
            "incompatible": "新版本数据库合同不兼容，保留当前程序和数据",
            "downloaded": "已下载，尚未登记部署",
            "deployment_requested": "已请求部署，结果待 Windows 确认",
            "registration_deferred": "Windows 已登记延后更新，尚未切换运行版本",
            "deployed": "Windows 已确认新版本部署",
            "unavailable": "仅 MSIX 安装版支持自动更新",
            "failed": "更新未完成",
        }
        status = labels.get(str(result.get("status")), str(result.get("status")))
        if result.get("installed_version"):
            status = f"已安装版本：{result['installed_version']}\n{status}"
        if result.get("error_code"):
            status += f"\n{result['error_code']}"
        self.update_status.set(status)
        self.status.set("更新状态已读取")

    def _automatic_update(self) -> None:
        if self.closed:
            return
        self.root.after(60000, self._automatic_update)
        if self.busy:
            return

        def checked(result: dict[str, Any]) -> None:
            self._update_result(result)
            if result.get("status") == "available":
                self._update_request("prepare")

        def observed(result: dict[str, Any]) -> None:
            self._update_result(result)
            if (
                result.get("automatic") is True
                and result.get("status")
                not in {"deployment_requested", "registration_deferred"}
                and time.time() - (result.get("checked_at") or 0) >= 86400
            ):
                self.request(
                    SetupRequest(
                        action="update", update=SetupUpdateRequest(action="check")
                    ),
                    checked,
                )

        self.request(
            SetupRequest(action="update", update=SetupUpdateRequest(action="status")),
            observed,
        )

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
            text="关闭窗口只隐藏设置；退出托盘不停止后台。停止并退出会先结束 Runtime，再停止本环境的数据库。",
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
            values=(
                "runtime",
                "model-bindings",
                "provider-pricing",
                "web-search",
                "qq",
                "mood-display",
            ),
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
        self.credential_name = tk.StringVar(value=next(iter(_CREDENTIAL_NAMES)))
        selector = ttk.Combobox(
            frame,
            textvariable=self.credential_name,
            state="readonly",
            width=48,
            values=tuple(_CREDENTIAL_NAMES),
        )
        selector.pack(anchor="w")
        selector.bind("<<ComboboxSelected>>", self._credential_selected)
        self.credential_help = tk.StringVar()
        ttk.Label(
            frame,
            textvariable=self.credential_help,
            wraplength=760,
        ).pack(anchor="w", pady=14)
        self.secret = ttk.Entry(frame, show="●", width=70)
        self.secret.pack(fill="x")
        self.codex_import = ttk.Button(
            frame,
            text="选择并导入 Codex 登录文件…",
            command=self._import_codex_credential,
        )
        actions = ttk.Frame(frame)
        self.credential_actions = actions
        actions.pack(anchor="w", pady=12)
        for label, action in (
            ("保存并验证", "put_and_verify"),
            ("验证已保存的 Key", "verify"),
            ("移除", "remove"),
            ("检查是否已保存", "status"),
        ):
            button = ttk.Button(
                actions,
                text=label,
                command=lambda action=action: self.credential(action),
            )
            button.pack(side="left", padx=4)
            if action == "put_and_verify":
                self.credential_save_button = button
            elif action == "verify":
                self.credential_verify_button = button
        self.credential_status = tk.StringVar(value="请选择凭据并检查保存状态。")
        ttk.Label(frame, textvariable=self.credential_status, wraplength=760).pack(
            anchor="w", pady=10
        )
        ttk.Label(
            frame,
            text="“保存并验证”和“验证已保存的 Key”会实际调用服务，产生少量用量；只发送固定测试内容，不发送生活数据。\nQQ 通信凭据由“QQ 接入”自动生成。凭据只保存在本环境的受限文件中，不回显已保存内容。",
            wraplength=760,
        ).pack(anchor="w", pady=10)
        self._credential_selected()

    def _credential_selected(self, _event: object = None) -> None:
        self.secret.delete(0, "end")
        self.secret.pack_forget()
        self.codex_import.pack_forget()
        name = _CREDENTIAL_NAMES[self.credential_name.get()]
        provider_key = name in {"model.ark_api_key", "speech.volc_credentials"}
        self.credential_save_button.configure(
            text="保存并验证" if provider_key else "导入并保存"
        )
        self.credential_verify_button.configure(
            state="normal" if provider_key else "disabled"
        )
        if name == "model.ark_api_key":
            self.credential_help.set(
                "填写火山方舟控制台创建的 API Key，用于模型调用及已启用的网页搜索。\n保存后后续请求读取新 Key，无需为更换 Key 重启；保存不代表服务商验证通过。"
            )
            self.secret.pack(fill="x", before=self.credential_actions)
        elif name == "speech.volc_credentials":
            self.credential_help.set(
                "填写豆包语音新版控制台“API Key 管理”创建的一个 API Key，用于语音识别与合成。\n无需 App ID 或 Access Token；与方舟模型 Key 分开保存。新语音会话读取新 Key，保存不代表服务已开通或验证通过。"
            )
            self.secret.pack(fill="x", before=self.credential_actions)
        else:
            self.credential_help.set(
                "先在本机 Codex 完成登录，再选择其 auth.json 登录文件导入，无需手写 JSON。\n通常位于用户目录的 .codex 文件夹；也可选择你自定义 Codex 目录中的文件。后续委托读取，当前任务不切换。"
            )
            self.codex_import.pack(anchor="w", before=self.credential_actions)
        self.credential_status.set("尚未检查当前项；点击“检查是否已保存”查看。")
        self.root.after(200, lambda: self._refresh_credential_selection(name))

    def _refresh_credential_selection(self, name: str) -> None:
        if self.closed or _CREDENTIAL_NAMES[self.credential_name.get()] != name:
            return
        if self.busy:
            self.root.after(500, lambda: self._refresh_credential_selection(name))
            return
        self._save_credential(name, "status", None)

    def _import_codex_credential(self) -> None:
        if self.busy:
            return
        path = filedialog.askopenfilename(
            title="选择 Codex 登录文件 auth.json",
            filetypes=[("JSON 登录文件", "*.json")],
        )
        if not path:
            return
        try:
            source = Path(path)
            if source.stat().st_size > 16_384:
                raise ValueError
            value = source.read_text(encoding="utf-8")
            if not isinstance(json.loads(value), dict):
                raise ValueError
        except OSError, ValueError:
            messagebox.showerror(
                "无法导入", "请选择有效的 Codex JSON 登录文件（不超过 16 KB）。"
            )
            return
        self._save_credential("codex.auth_json", "put", value)

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

    def _qq_tab(self) -> None:
        frame = ttk.Frame(self.tabs, padding=20)
        self.tabs.add(frame, text="QQ 接入")
        ttk.Label(
            frame,
            text="QQ 默认关闭。填写你的 QQ 号后，一键准备并打开扫码页，ARMI 的 QQ 号从登录结果自动读取。\n"
            "首次扫码和 QQ 安全验证需本人完成。默认仅与你私聊，群聊及其他人的回复保持关闭。",
            wraplength=760,
        ).pack(anchor="w", pady=(0, 12))
        self.qq_creator = tk.StringVar()
        for label, variable in (("你的 QQ 号（Creator）", self.qq_creator),):
            row = ttk.Frame(frame)
            row.pack(fill="x", pady=5)
            ttk.Label(row, text=label, width=25).pack(side="left")
            ttk.Entry(row, textvariable=variable, width=28).pack(side="left")
        self.qq_action = "prepare"
        self.qq_installed = False
        self.qq_button = ttk.Button(
            frame, text="正在检查状态…", state="disabled", command=self._prepare_qq
        )
        self.qq_button.pack(anchor="w", pady=12)
        ttk.Button(
            frame,
            text="刷新安装与连接状态",
            command=lambda: self.request(
                SetupRequest(
                    action="napcat", napcat=SetupNapcatRequest(action="refresh")
                ),
                self._qq_result,
            ),
        ).pack(anchor="w")
        self.qq_progress = ttk.Progressbar(frame, maximum=100)
        self.qq_component = tk.StringVar(value="1. 组件：正在检查")
        ttk.Label(frame, textvariable=self.qq_component).pack(anchor="w", pady=(12, 6))
        self.qq_status = tk.StringVar(value="尚未准备；安装完成不代表已登录 QQ")
        self.qq_status_label = ttk.Label(
            frame, textvariable=self.qq_status, wraplength=760
        )
        self.qq_status_label.pack(anchor="w")
        ttk.Label(
            frame,
            text="组件由 NapCat 官方发布，适用其使用许可。账号会话和组件保存在本环境，更新 ARMI 时保留。",
            wraplength=760,
        ).pack(anchor="w", pady=16)
        ttk.Button(
            frame,
            text="查看 NapCat 使用许可",
            command=lambda: webbrowser.open(
                "https://github.com/NapNeko/NapCatQQ/blob/v4.18.9/LICENSE"
            ),
        ).pack(anchor="w")
        self.qq_preparing = False
        self.qq_login_timer: str | None = None
        self.root.after(1000, self._qq_resume_login)

    def _qq_resume_login(self) -> None:
        if self.closed:
            return
        if self.busy:
            self.root.after(1000, self._qq_resume_login)
            return
        self.request(
            SetupRequest(action="napcat", napcat=SetupNapcatRequest(action="refresh")),
            self._qq_result,
        )

    def _qq_complete_login(self) -> None:
        self.qq_login_timer = None
        if self.closed:
            return
        if self.busy:
            self.qq_login_timer = self.root.after(1000, self._qq_complete_login)
            return
        self.request(
            SetupRequest(action="napcat", napcat=SetupNapcatRequest(action="complete")),
            self._qq_result,
        )

    def _prepare_qq(self) -> None:
        if self.busy:
            return
        if self.qq_action == "open_login":
            self.qq_button.configure(state="disabled")
            self.request(
                SetupRequest(
                    action="napcat", napcat=SetupNapcatRequest(action="open_login")
                ),
                self._qq_result,
            )
            return
        try:
            request = SetupNapcatRequest(
                action="prepare",
                creator_user_id=int(self.qq_creator.get()),
                enabled=True,
                open_login=True,
            )
        except ValueError:
            messagebox.showerror(
                "QQ 接入",
                "请填写你本人的有效 QQ 号（Creator）；ARMI 的账号由扫码登录确定。",
            )
            return
        self.qq_preparing = True
        self.qq_button.configure(state="disabled")
        self.request(SetupRequest(action="napcat", napcat=request), self._qq_result)
        self.root.after(500, self._qq_progress_poll)

    def _qq_progress_poll(self) -> None:
        if self.closed or not self.qq_preparing:
            return
        try:
            result = self.application.napcat(SetupNapcatRequest(action="status"))
            self._qq_display(result)
        except OSError, ValueError, RuntimeError:
            self.qq_status.set("暂时无法读取进度，操作仍在进行中")
        self.root.after(500, self._qq_progress_poll)

    def _qq_display(self, result: dict[str, Any]) -> None:
        phase = str(result.get("status", "unavailable"))
        installed = bool(result.get("installed", self.qq_installed)) or phase in {
            "installed",
            "accounts_required",
            "awaiting_login",
            "stopping",
            "configuring",
            "configured",
            "starting",
            "login_required",
            "ready",
        }
        self.qq_installed = installed
        self.qq_component.set(
            "1. 组件："
            + (
                f"已安装 NapCat {result.get('version', '')}"
                if installed
                else "尚未安装"
            )
        )
        self.qq_progress.stop()
        self.qq_progress.pack_forget()
        if phase in {"downloading", "extracting", "verifying"}:
            self.qq_component.set("1. 组件：正在下载或安装，请稍候")
            self.qq_progress.pack(fill="x", pady=8, before=self.qq_status_label)
            self.qq_progress.configure(
                mode="determinate" if result.get("total") else "indeterminate"
            )
            if not result.get("total"):
                self.qq_progress.start()
        bound = bool(result.get("account_id"))
        self.qq_action = (
            "open_login"
            if bound or result.get("login_pending") or phase == "awaiting_login"
            else "prepare"
        )
        working = phase in {
            "downloading",
            "extracting",
            "verifying",
            "stopping",
            "configuring",
            "starting",
        }
        self.qq_button.configure(
            text=(
                "已连接"
                if phase == "ready"
                else "打开登录页 / 继续扫码"
                if self.qq_action == "open_login"
                else "继续设置 QQ"
                if installed
                else "安装并接入 QQ（联网）"
            ),
            state="disabled" if working or phase == "ready" else "normal",
        )
        if result.get("creator_user_id") and not self.qq_creator.get():
            self.qq_creator.set(str(result["creator_user_id"]))
        labels = {
            "not_installed": "2. 账号：尚未登录\n3. 连接：尚未设置\n下一步：填写你的 Creator QQ 号，点击安装并接入。",
            "downloading": "正在下载组件",
            "extracting": "校验通过，正在安装",
            "verifying": "正在验证组件可运行",
            "installed": "组件已安装",
            "accounts_required": "2. 账号：尚未绑定\n3. 连接：尚未设置\n下一步：填写你的 Creator QQ 号，点击继续设置；已安装组件会复用。",
            "awaiting_login": "2. 账号：等待扫码登录\n3. 连接：等待账号确认\n下一步：在登录页扫码并完成 QQ 验证，随后自动配置。登录页关闭时可重新打开。",
            "stopping": "正在正常停止环境",
            "configuring": "正在自动配置 QQ 接入",
            "configured": "2. 账号：已保存绑定\n3. 连接：QQ 功能已关闭\n下一步：在功能设置中启用 QQ 后重新启动环境。",
            "starting": "正在启动环境和 QQ 登录页",
            "login_required": "2. 账号：未登录或登录已失效\n3. 连接：尚未就绪\n下一步：打开登录页扫码。已有配置会保留，不会重新安装或配置。",
            "ready": "2. 账号：已登录\n3. 连接：QQ 接入已就绪\n无需继续设置；实际回复还取决于 Runtime 和模型是否可用。",
            "failed": "本次操作失败；已有组件和账号数据保留。\n下一步：刷新状态检查当前进度，再按提示继续。",
            "unavailable": "2. 账号：暂时无法确认登录\n3. 连接：未就绪\n下一步：打开登录页检查；若仍失败，刷新状态查看原因。",
            "misconfigured": "2. 账号或通信配置不匹配\n3. 连接：未就绪\n下一步：确认扫码的是原绑定账号；不要反复安装。",
        }
        text = labels.get(str(result.get("status")), str(result.get("status")))
        if phase == "unavailable" and result.get("logged_in"):
            text = "2. 账号：已登录\n3. 连接：通信检查尚未通过\n下一步：稍候会自动复查，无需再次扫码或安装。"
        if result.get("total"):
            percent = 100 * result.get("received", 0) / result["total"]
            self.qq_progress["value"] = percent
            text += f"（{percent:.0f}%）"
        if result.get("error_code"):
            text += "：" + str(result["error_code"])
        if result.get("reason_codes"):
            text += "\n原因：" + "、".join(result["reason_codes"])
        if result.get("account_id"):
            text += "；ARMI QQ：" + str(result["account_id"])
        if result.get("error_code") == "NAPCAT-ACCOUNT-IDENTITIES":
            text = "扫码账号与你的 Creator QQ 相同，请使用另一个 QQ 账号登录 ARMI。"
        self.qq_status.set(text)

    def _qq_result(self, result: dict[str, Any]) -> None:
        self.qq_preparing = False
        self._qq_display(result)
        self.status.set("QQ 状态已更新，请查看接入步骤和下一步提示。")
        if self.qq_login_timer is not None:
            self.root.after_cancel(self.qq_login_timer)
            self.qq_login_timer = None
        if result.get("status") in {
            "awaiting_login",
            "login_required",
            "starting",
            "unavailable",
            "ready",
        } or result.get("login_pending"):
            self.qq_login_timer = self.root.after(10000, self._qq_complete_login)

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
        if request.operation in {"environment_start", "environment_stop"}:
            self._set_runtime_status(
                "正在启动" if request.operation == "environment_start" else "正在停止"
            )
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
        if self.busy:
            return
        name = _CREDENTIAL_NAMES[self.credential_name.get()]
        value = None
        if action in {"put", "put_and_verify"}:
            if name == "codex.auth_json":
                self._import_codex_credential()
                return
            value = self.secret.get().strip()
            if not value:
                messagebox.showerror(
                    "请填写 API Key", "请按上方说明粘贴对应服务控制台创建的 API Key。"
                )
                return
        self.secret.delete(0, "end")
        self._save_credential(name, action, value)

    def _save_credential(self, name: str, action: str, value: str | None) -> None:
        payload = {"name": name, "action": action}
        if value is not None:
            payload["value"] = value
        if action in {"put_and_verify", "verify"}:
            self.credential_status.set(
                "正在实际验证服务，请稍候。测试会产生少量服务商用量；不发送生活数据。"
            )
        self.request(
            SetupRequest.model_validate(
                {"action": "credential", "credential": payload}
            ),
            lambda result: self._credential_result(name, result),
        )

    def _credential_result(self, name: str, result: dict[str, Any]) -> None:
        if _CREDENTIAL_NAMES[self.credential_name.get()] != name:
            return
        status = result.get("status")
        text = (
            "未配置。请按上方说明填写。"
            if status == "missing"
            else "已保存；尚未验证服务商连接。后续请求或新会话使用所保存的凭据。"
            if status == "configured"
            else "操作失败：" + str(result.get("error_code", "未知原因"))
        )
        self.credential_status.set(text)
        verification = result.get("verification")
        if isinstance(verification, dict):
            verification = cast(dict[str, Any], verification)
            labels = {
                "model": "普通模型",
                "voice_model": "语音专用模型",
                "tts": "语音合成 TTS",
                "asr": "语音识别 ASR",
            }
            lines = [
                "已保存，本次实际验证通过。"
                if verification.get("status") == "passed"
                else "已保存，但验证未通过。"
            ]
            for check, item in verification.get("checks", {}).items():
                state = {
                    "passed": "通过",
                    "failed": "失败",
                    "not_tested": "尚未验证",
                }.get(item.get("status"), "未知")
                lines.append(
                    f"{labels.get(check, check)}：{state}。{item.get('message', '')} {item.get('error_code', '')}".strip()
                )
            if verification.get("error_code"):
                lines.append(
                    str(verification["error_code"])
                    + "："
                    + str(verification.get("message", ""))
                )
            text = "\n".join(lines)
            self.credential_status.set(text)
        self.status.set(text)

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
        elif action == "quit":
            if self.busy:
                self.status.set("正在处理操作，请完成后再退出托盘；后台状态不会改变。")
                self.root.deiconify()
                return
            self._close()
        elif (
            action == "stop_quit"
            and not (self.environment / "postgresql/cluster.json").exists()
        ):
            self._close()
        else:
            operation = (
                "environment_stop" if action == "stop_quit" else "environment_" + action
            )
            arguments = {} if action == "status" else {"idempotency_key": str(uuid7())}
            self.admin(
                operation,
                arguments,
                self._quit_result if action == "stop_quit" else None,
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
        self.application.close()
        self.root.destroy()

    def _refresh_runtime_status(self) -> None:
        if self.closed:
            return
        if not self.busy:
            if not (self.environment / "admin.yaml").exists():
                self._set_runtime_status("尚未准备环境")
            else:
                self.busy = True
                future = self.executor.submit(
                    dispatch,
                    self.application,
                    SetupRequest(action="admin", operation="environment_status"),
                )
                future.add_done_callback(
                    lambda completed: self.events.put(
                        (completed.result(), self._runtime_status_result)
                    )
                )
        self.root.after(5000, self._refresh_runtime_status)

    def _set_runtime_status(
        self, text: str, *, running: bool = False, error: bool = False
    ) -> None:
        self.runtime_status.set("后台状态：" + text)
        self.tray.set_status(text, running=running, error=error)

    def _runtime_status_result(self, result: dict[str, Any]) -> None:
        if result.get("status") != "succeeded":
            self._set_runtime_status(
                "无法确认 / " + str(result.get("error_code") or result.get("status")),
                error=True,
            )
            return
        payload: dict[str, Any] = result.get("result") or {}
        runtime_info: dict[str, Any] = payload.get("runtime") or {}
        runtime = str(runtime_info.get("status"))
        labels = {"ready": "运行中", "running": "运行中", "stopped": "已停止"}
        self._set_runtime_status(
            labels.get(runtime, "异常 / " + str(runtime)),
            running=runtime in {"ready", "running"},
            error=runtime not in labels,
        )

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
                if callback == self._runtime_status_result:
                    callback(result)
                    continue
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
                    "disabled_by_user": "Windows 中已禁用自启，请在系统设置中重新开启",
                    "disabled_by_policy": "系统策略已禁用自启",
                    "enabled_by_policy": "系统策略已开启自启",
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
        messagebox.showerror("ARMI", "环境必须位于数据目录的 environments 子目录中。")
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
        messagebox.showerror("ARMI", "无法写入数据目录，请检查当前用户的目录权限。")
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
