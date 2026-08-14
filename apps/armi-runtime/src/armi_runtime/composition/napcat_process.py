"""Operator-owned NapCat startup and health for one local QQ channel."""

from __future__ import annotations

import asyncio
import ctypes
import hmac
import json
import os
import shutil
import socket
import subprocess
import time
import webbrowser
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal, TypeVar, cast
from urllib.parse import urlencode, urlsplit

import httpx
from armi_adapter_qq import QQNapCatBindingConfig, load_qq_napcat_config
from armi_channel_napcat import NapCatHealthSnapshot, NapCatHttpClient
from armi_kernel.application import CredentialPurpose

from .configuration import ConfigurationViolation
from .configuration.paths import has_reparse_point, require_within_roots
from .environment import PreparedEnvironment
from .qq_channel import (
    QQ_NAPCAT_ACCESS_TOKEN_LOCATOR,
    QQ_NAPCAT_ACCESS_TOKEN_PURPOSE,
    QQ_NAPCAT_EVENT_SECRET_LOCATOR,
    QQ_NAPCAT_EVENT_SECRET_PURPOSE,
)
from .runtime_errors import RuntimeViolation

type QQChannelState = Literal[
    "disabled",
    "starting",
    "login_required",
    "ready",
    "unavailable",
    "misconfigured",
]

_START_TIMEOUT_SECONDS = 60.0
_HEALTH_TIMEOUT_SECONDS = 1.0
_ResultT = TypeVar("_ResultT")


@dataclass(frozen=True, slots=True)
class QQChannelHealth:
    state: QQChannelState
    ingress_ready: bool
    api_reachable: bool
    account_online: bool | None
    account_matches: bool | None
    webui_url: str | None
    observed_at: str
    reason_codes: tuple[str, ...]

    def safe_view(self) -> dict[str, object]:
        return {
            "projection_version": "creator-channel-health.v2",
            "channel": "qq",
            "driver": "napcat",
            "state": self.state,
            "ingress_ready": self.ingress_ready,
            "api_reachable": self.api_reachable,
            "account_online": self.account_online,
            "account_matches": self.account_matches,
            "webui_url": self.webui_url,
            "observed_at": self.observed_at,
            "reason_codes": list(self.reason_codes),
        }


@dataclass(frozen=True, slots=True)
class NapCatStartResult:
    status: Literal["disabled", "already_ready", "started", "attention"]
    health: QQChannelHealth

    def safe_view(self) -> dict[str, object]:
        return {"status": self.status, "channel": self.health.safe_view()}


@dataclass(frozen=True, slots=True)
class NapCatWebUIOpenResult:
    webui_url: str
    token_delivery: Literal["clipboard", "url_query"]

    def safe_view(self) -> dict[str, object]:
        return {
            "status": "opened",
            "webui_url": self.webui_url,
            "token_delivery": self.token_delivery,
        }


class NapCatProcessManager:
    """Observe and idempotently start the configured external NapCat instance."""

    __slots__ = ("_prepared",)

    def __init__(self, prepared: PreparedEnvironment) -> None:
        self._prepared = prepared

    def status(self) -> QQChannelHealth:
        try:
            binding = self._binding()
        except RuntimeViolation as error:
            return _misconfigured_health(False, error.code.replace("-", "_"))
        if binding is None:
            return _disabled_health()
        ingress_ready = _port_is_listening("127.0.0.1", binding.event_port)
        try:
            health = self._with_access_token(
                binding,
                lambda token: asyncio.run(_inspect(binding, token)),
            )
        except ConfigurationViolation, RuntimeViolation, UnicodeDecodeError:
            return _misconfigured_health(
                ingress_ready,
                "NAPCAT_CREDENTIAL_UNAVAILABLE",
            )
        return compose_qq_health(
            health,
            ingress_ready=ingress_ready,
            environment_root=self._prepared.root,
        )

    def start(self) -> NapCatStartResult:
        binding = self._binding()
        if binding is None:
            return NapCatStartResult("disabled", _disabled_health())
        if not _port_is_listening("127.0.0.1", binding.event_port):
            raise RuntimeViolation(
                "CLI-QQ-INGRESS-UNAVAILABLE",
                "the Runtime QQ event ingress is unavailable",
            )
        current = self.status()
        if current.state == "ready":
            return NapCatStartResult("already_ready", current)
        if current.state == "login_required":
            return NapCatStartResult("attention", current)
        parsed_api = urlsplit(binding.api_base_url)
        api_port = parsed_api.port
        if current.api_reachable or (
            api_port is not None and _port_is_listening("127.0.0.1", api_port)
        ):
            raise RuntimeViolation(
                "CLI-QQ-NAPCAT-CONFLICT",
                "the configured NapCat endpoint is occupied or misconfigured",
            )
        installation = self._installation(binding)
        if _executable_is_running(installation.qq_executable):
            raise RuntimeViolation(
                "CLI-QQ-UNMANAGED-PROCESS",
                "QQ is already running without a healthy managed NapCat endpoint",
            )

        def launch_with_access(access_token: memoryview) -> subprocess.Popen[bytes]:
            def launch_with_event(event_secret: memoryview) -> subprocess.Popen[bytes]:
                access = access_token.tobytes().decode("utf-8", "strict")
                event = event_secret.tobytes().decode("utf-8", "strict")
                self._validate_onebot_config(
                    installation,
                    binding,
                    access_token=access,
                    event_secret=event,
                )
                return self._launch(installation, binding)

            return self._with_event_secret(launch_with_event)

        process = self._with_access_token(binding, launch_with_access)
        deadline = time.monotonic() + _START_TIMEOUT_SECONDS
        last = current
        while time.monotonic() < deadline:
            time.sleep(0.5)
            last = self.status()
            if last.state == "ready":
                return NapCatStartResult("started", last)
            if last.state == "login_required":
                return NapCatStartResult("attention", last)
            if last.state == "misconfigured":
                raise RuntimeViolation(
                    "CLI-QQ-NAPCAT-CONFLICT",
                    "NapCat became reachable with an invalid configuration",
                )
            if process.poll() is not None and not _executable_is_running(
                installation.qq_executable
            ):
                break
        return NapCatStartResult(
            "attention",
            QQChannelHealth(
                "starting",
                True,
                last.api_reachable,
                last.account_online,
                last.account_matches,
                last.webui_url,
                _observed_at(),
                ("NAPCAT_START_PENDING",),
            ),
        )

    def open_webui(self, *, auto_login: bool = False) -> NapCatWebUIOpenResult:
        config = _load_napcat_webui_config(self._prepared.root)
        if not _port_is_listening("127.0.0.1", config.port):
            raise RuntimeViolation(
                "CLI-QQ-WEBUI-UNAVAILABLE",
                "the NapCat WebUI is not listening on its configured local port",
            )
        target_url = config.url
        token_delivery: Literal["clipboard", "url_query"] = "clipboard"
        if auto_login:
            target_url = f"{config.url}?{urlencode({'token': config.token})}"
            token_delivery = "url_query"
        else:
            try:
                _copy_text_to_clipboard(config.token)
            except RuntimeViolation:
                raise
            except Exception as exc:
                raise RuntimeViolation(
                    "CLI-QQ-WEBUI-CLIPBOARD",
                    "the NapCat WebUI token could not be copied to the clipboard",
                ) from exc
        try:
            opened = _open_default_browser(target_url)
        except Exception as exc:
            raise RuntimeViolation(
                "CLI-QQ-WEBUI-OPEN",
                "the NapCat WebUI could not be opened in the default browser",
            ) from exc
        if not opened:
            raise RuntimeViolation(
                "CLI-QQ-WEBUI-OPEN",
                "the NapCat WebUI could not be opened in the default browser",
            )
        return NapCatWebUIOpenResult(config.url, token_delivery)

    def _binding(self) -> QQNapCatBindingConfig | None:
        path = self._prepared.root / "channels" / "qq-napcat.yaml"
        try:
            resolved, root = require_within_roots(
                path,
                (self._prepared.root,),
                code="CFG-QQ-CHANNEL",
            )
            if resolved.exists() and has_reparse_point(resolved, root=root):
                raise ValueError
            return load_qq_napcat_config(resolved)
        except ConfigurationViolation, OSError, ValueError:
            raise RuntimeViolation(
                "CLI-QQ-CONFIGURATION",
                "the QQ channel configuration is invalid",
            ) from None

    def _with_access_token(
        self,
        binding: QQNapCatBindingConfig,
        operation: Callable[[memoryview], _ResultT],
    ) -> _ResultT:
        del binding
        locator = self._prepared.effective.config.secret_locators.get(
            QQ_NAPCAT_ACCESS_TOKEN_LOCATOR
        )
        if locator is None:
            raise RuntimeViolation(
                "CLI-QQ-CREDENTIAL",
                "the NapCat access token locator is unavailable",
            )
        with self._prepared.credential_port.resolve(
            locator,
            CredentialPurpose(QQ_NAPCAT_ACCESS_TOKEN_PURPOSE),
        ) as handle:
            return handle.consume(operation)

    def _with_event_secret(
        self,
        operation: Callable[[memoryview], _ResultT],
    ) -> _ResultT:
        locator = self._prepared.effective.config.secret_locators.get(
            QQ_NAPCAT_EVENT_SECRET_LOCATOR
        )
        if locator is None:
            raise RuntimeViolation(
                "CLI-QQ-CREDENTIAL",
                "the NapCat event secret locator is unavailable",
            )
        with self._prepared.credential_port.resolve(
            locator,
            CredentialPurpose(QQ_NAPCAT_EVENT_SECRET_PURPOSE),
        ) as handle:
            return handle.consume(operation)

    def _installation(self, binding: QQNapCatBindingConfig) -> _Installation:
        root = self._prepared.root / "tools" / "napcat"
        try:
            resolved, environment_root = require_within_roots(
                root,
                (self._prepared.root,),
                code="CLI-QQ-INSTALLATION",
            )
        except ConfigurationViolation:
            raise RuntimeViolation(
                "CLI-QQ-INSTALLATION",
                "the NapCat installation root is invalid",
            ) from None
        if not resolved.is_dir() or has_reparse_point(resolved, root=environment_root):
            raise RuntimeViolation(
                "CLI-QQ-INSTALLATION",
                "the NapCat installation root is unavailable",
            )
        required = {
            "launcher": resolved / "NapCatWinBootMain.exe",
            "hook": resolved / "NapCatWinBootHook.dll",
            "main": resolved / "napcat.mjs",
            "patch": resolved / "qqnt.json",
            "onebot": resolved
            / "config"
            / f"onebot11_{binding.adapter.account_id}.json",
        }
        if any(
            not path.is_file()
            or path.is_symlink()
            or has_reparse_point(path, root=environment_root)
            for path in required.values()
        ):
            raise RuntimeViolation(
                "CLI-QQ-INSTALLATION",
                "the NapCat installation is incomplete",
            )
        qq_executable = _discover_qq_executable()
        return _Installation(
            resolved,
            required["launcher"],
            required["hook"],
            required["main"],
            required["patch"],
            required["onebot"],
            qq_executable,
        )

    @staticmethod
    def _validate_onebot_config(
        installation: _Installation,
        binding: QQNapCatBindingConfig,
        *,
        access_token: str,
        event_secret: str,
    ) -> None:
        try:
            document: object = json.loads(
                installation.onebot_config.read_text(encoding="utf-8", errors="strict")
            )
        except OSError, UnicodeError, json.JSONDecodeError:
            raise RuntimeViolation(
                "CLI-QQ-NAPCAT-CONFIG",
                "the NapCat OneBot configuration is invalid",
            ) from None
        if not isinstance(document, dict):
            raise RuntimeViolation(
                "CLI-QQ-NAPCAT-CONFIG",
                "the NapCat OneBot configuration is invalid",
            )
        network = cast(dict[object, object], document).get("network")
        if not isinstance(network, dict):
            raise RuntimeViolation(
                "CLI-QQ-NAPCAT-CONFIG",
                "the NapCat OneBot network configuration is invalid",
            )
        values = cast(dict[object, object], network)
        servers = values.get("httpServers")
        clients = values.get("httpClients")
        parsed = urlsplit(binding.api_base_url)
        server_match = _matching_network_entry(
            servers,
            host="127.0.0.1",
            port=parsed.port,
            token=access_token,
            required_values={"messagePostFormat": "array"},
        )
        client_match = _matching_network_entry(
            clients,
            url=f"http://127.0.0.1:{binding.event_port}/",
            token=event_secret,
            required_values={
                "messagePostFormat": "array",
                "reportSelfMessage": False,
            },
        )
        if not server_match or not client_match:
            raise RuntimeViolation(
                "CLI-QQ-NAPCAT-CONFIG",
                "the NapCat OneBot endpoints do not match the ARMI channel",
            )

    @staticmethod
    def _launch(
        installation: _Installation,
        binding: QQNapCatBindingConfig,
    ) -> subprocess.Popen[bytes]:
        main_uri = installation.main_script.as_uri()
        load_script = installation.root / "loadNapCat.js"
        temporary = load_script.with_name(f".{load_script.name}.{os.getpid()}.tmp")
        temporary.write_text(
            f"(async () => {{await import({json.dumps(main_uri)})}})()\n",
            encoding="utf-8",
            newline="\n",
        )
        temporary.replace(load_script)
        environment = {
            name: value
            for name in (
                "APPDATA",
                "LOCALAPPDATA",
                "PATH",
                "PROGRAMDATA",
                "PROGRAMFILES",
                "SYSTEMDRIVE",
                "SYSTEMROOT",
                "TEMP",
                "TMP",
                "USERPROFILE",
                "WINDIR",
            )
            if (value := os.environ.get(name)) is not None
        }
        environment.update(
            {
                "NAPCAT_PATCH_PACKAGE": os.fspath(installation.patch_package),
                "NAPCAT_LOAD_PATH": os.fspath(load_script),
                "NAPCAT_INJECT_PATH": os.fspath(installation.hook_library),
                "NAPCAT_LAUNCHER_PATH": os.fspath(installation.launcher),
                "NAPCAT_MAIN_PATH": os.fspath(installation.main_script),
            }
        )
        command = (
            os.fspath(installation.launcher),
            os.fspath(installation.qq_executable),
            os.fspath(installation.hook_library),
            str(binding.adapter.account_id),
        )
        creation_flags = 0
        if os.name == "nt":
            creation_flags = (
                subprocess.CREATE_NEW_PROCESS_GROUP
                | subprocess.CREATE_NO_WINDOW
                | subprocess.CREATE_BREAKAWAY_FROM_JOB
            )
        try:
            return subprocess.Popen(
                command,
                cwd=installation.root,
                env=environment,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                close_fds=True,
                creationflags=creation_flags,
            )
        except OSError as exc:
            raise RuntimeViolation(
                "CLI-QQ-NAPCAT-START-FAILED",
                "NapCat could not be started",
            ) from exc


@dataclass(frozen=True, slots=True)
class _Installation:
    root: Path
    launcher: Path
    hook_library: Path
    main_script: Path
    patch_package: Path
    onebot_config: Path
    qq_executable: Path


@dataclass(frozen=True, slots=True, repr=False)
class _NapCatWebUIConfig:
    url: str
    port: int
    token: str


def _load_napcat_webui_config(environment_root: Path) -> _NapCatWebUIConfig:
    path = environment_root / "tools" / "napcat" / "config" / "webui.json"
    try:
        resolved, root = require_within_roots(
            path,
            (environment_root,),
            code="CLI-QQ-WEBUI-CONFIG",
        )
    except ConfigurationViolation:
        raise RuntimeViolation(
            "CLI-QQ-WEBUI-CONFIG",
            "the NapCat WebUI configuration path is invalid",
        ) from None
    if (
        not resolved.is_file()
        or resolved.is_symlink()
        or has_reparse_point(resolved, root=root)
    ):
        raise RuntimeViolation(
            "CLI-QQ-WEBUI-CONFIG",
            "the NapCat WebUI configuration is unavailable",
        )
    try:
        document: object = json.loads(
            resolved.read_text(encoding="utf-8", errors="strict")
        )
    except OSError, UnicodeError, json.JSONDecodeError:
        raise RuntimeViolation(
            "CLI-QQ-WEBUI-CONFIG",
            "the NapCat WebUI configuration is invalid",
        ) from None
    if not isinstance(document, dict):
        raise RuntimeViolation(
            "CLI-QQ-WEBUI-CONFIG",
            "the NapCat WebUI configuration is invalid",
        )
    values = cast(dict[object, object], document)
    host = values.get("host")
    port = values.get("port")
    token = values.get("token")
    if (
        type(host) is not str
        or host.strip().casefold()
        not in {"::", "::1", "0.0.0.0", "127.0.0.1", "localhost"}
        or type(port) is not int
        or not 1 <= port <= 65535
        or type(token) is not str
        or not token
        or len(token) > 4096
        or "\r" in token
        or "\n" in token
    ):
        raise RuntimeViolation(
            "CLI-QQ-WEBUI-CONFIG",
            "the NapCat WebUI configuration is invalid",
        )
    return _NapCatWebUIConfig(
        f"http://127.0.0.1:{port}/webui/",
        port,
        token,
    )


def _discover_napcat_webui_url(environment_root: Path) -> str | None:
    try:
        return _load_napcat_webui_config(environment_root).url
    except RuntimeViolation:
        return None


def _copy_text_to_clipboard(value: str) -> None:
    executable = shutil.which("pwsh")
    if os.name != "nt" or executable is None:
        raise RuntimeViolation(
            "CLI-QQ-WEBUI-CLIPBOARD",
            "the Windows clipboard is unavailable",
        )
    try:
        completed = subprocess.run(
            (
                executable,
                "-NoLogo",
                "-NoProfile",
                "-NonInteractive",
                "-Command",
                "Set-Clipboard -Value ([Console]::In.ReadToEnd())",
            ),
            input=value,
            text=True,
            encoding="utf-8",
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=5.0,
            check=False,
        )
    except OSError, subprocess.TimeoutExpired:
        raise RuntimeViolation(
            "CLI-QQ-WEBUI-CLIPBOARD",
            "the NapCat WebUI token could not be copied to the clipboard",
        ) from None
    if completed.returncode != 0:
        raise RuntimeViolation(
            "CLI-QQ-WEBUI-CLIPBOARD",
            "the NapCat WebUI token could not be copied to the clipboard",
        )


def _open_default_browser(url: str) -> bool:
    try:
        return webbrowser.open(url, new=2)
    except OSError, webbrowser.Error:
        return False


async def _inspect(
    binding: QQNapCatBindingConfig, token_view: memoryview
) -> NapCatHealthSnapshot:
    token = token_view.tobytes().decode("utf-8", "strict")
    async with httpx.AsyncClient(
        base_url=binding.api_base_url.rstrip("/"),
        headers={"Authorization": f"Bearer {token}"},
        timeout=httpx.Timeout(_HEALTH_TIMEOUT_SECONDS),
        trust_env=False,
    ) as client:
        gateway = NapCatHttpClient(
            base_url=binding.api_base_url,
            access_token=token,
            client=client,
        )
        return await gateway.inspect_health(
            expected_account_id=binding.adapter.account_id
        )


def _compose_health(
    health: NapCatHealthSnapshot,
    *,
    ingress_ready: bool,
    webui_url: str | None,
) -> QQChannelHealth:
    reasons = tuple(reason.replace("-", "_") for reason in health.reason_codes)
    state: QQChannelState = health.state
    if health.state == "ready" and not ingress_ready:
        state = "unavailable"
        reasons = (*reasons, "QQ_INGRESS_UNAVAILABLE")
    return QQChannelHealth(
        state,
        ingress_ready,
        health.api_reachable,
        health.account_online,
        health.account_matches,
        webui_url,
        health.observed_at,
        reasons,
    )


def compose_qq_health(
    health: NapCatHealthSnapshot,
    *,
    ingress_ready: bool,
    environment_root: Path | None = None,
) -> QQChannelHealth:
    webui_url = (
        _discover_napcat_webui_url(environment_root)
        if environment_root is not None
        else None
    )
    composed = _compose_health(
        health,
        ingress_ready=ingress_ready,
        webui_url=webui_url,
    )
    if (
        environment_root is not None
        and composed.state == "unavailable"
        and not composed.api_reachable
        and _executable_is_running(
            environment_root / "tools" / "napcat" / "NapCatWinBootMain.exe"
        )
    ):
        return QQChannelHealth(
            "login_required",
            ingress_ready,
            False,
            False,
            None,
            composed.webui_url,
            composed.observed_at,
            ("NAPCAT_LOGIN_REQUIRED",),
        )
    return composed


def _disabled_health() -> QQChannelHealth:
    return QQChannelHealth(
        "disabled",
        False,
        False,
        None,
        None,
        None,
        _observed_at(),
        (),
    )


def disabled_qq_health() -> QQChannelHealth:
    return _disabled_health()


def _misconfigured_health(ingress_ready: bool, reason: str) -> QQChannelHealth:
    return QQChannelHealth(
        "misconfigured",
        ingress_ready,
        False,
        None,
        None,
        None,
        _observed_at(),
        (reason,),
    )


def _observed_at() -> str:
    return datetime.now(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _port_is_listening(host: str, port: int) -> bool:
    try:
        with socket.create_connection((host, port), timeout=0.25):
            return True
    except OSError:
        return False


def _matching_network_entry(
    entries: object,
    *,
    token: str,
    host: str | None = None,
    port: int | None = None,
    url: str | None = None,
    required_values: dict[str, str | bool] | None = None,
) -> bool:
    if not isinstance(entries, list):
        return False
    for raw in cast(list[object], entries):
        if not isinstance(raw, dict):
            continue
        entry = cast(dict[object, object], raw)
        if entry.get("enable") is not True:
            continue
        candidate = entry.get("token")
        if type(candidate) is not str or not hmac.compare_digest(candidate, token):
            continue
        if host is not None and entry.get("host") != host:
            continue
        if port is not None and entry.get("port") != port:
            continue
        if url is not None and entry.get("url") != url:
            continue
        if required_values is not None and any(
            entry.get(name) != expected for name, expected in required_values.items()
        ):
            continue
        return True
    return False


def _discover_qq_executable() -> Path:
    candidates: list[Path] = []
    if os.name == "nt":
        try:
            import winreg

            for access in (winreg.KEY_WOW64_32KEY, winreg.KEY_WOW64_64KEY):
                try:
                    with winreg.OpenKey(
                        winreg.HKEY_LOCAL_MACHINE,
                        r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\QQ",
                        0,
                        winreg.KEY_READ | access,
                    ) as key:
                        uninstall = winreg.QueryValueEx(key, "UninstallString")[0]
                    if type(uninstall) is str and uninstall:
                        candidates.append(
                            Path(uninstall.strip().strip('"')).parent / "QQ.exe"
                        )
                except OSError:
                    continue
        except ImportError:
            pass
    program_files = os.environ.get("PROGRAMFILES")
    if program_files:
        candidates.append(Path(program_files) / "Tencent" / "QQNT" / "QQ.exe")
    for candidate in candidates:
        try:
            resolved = candidate.resolve(strict=True)
        except OSError:
            continue
        if resolved.is_file() and not resolved.is_symlink():
            return resolved
    raise RuntimeViolation(
        "CLI-QQ-EXECUTABLE",
        "the installed QQ executable could not be located",
    )


def _executable_is_running(executable: Path) -> bool:
    if os.name != "nt":
        return False
    from ctypes import wintypes

    snapshot_flag = 0x00000002
    process_query_limited_information = 0x1000
    invalid_handle = ctypes.c_void_p(-1).value

    class ProcessEntry(ctypes.Structure):
        _fields_ = (
            ("dwSize", wintypes.DWORD),
            ("cntUsage", wintypes.DWORD),
            ("th32ProcessID", wintypes.DWORD),
            ("th32DefaultHeapID", ctypes.POINTER(wintypes.ULONG)),
            ("th32ModuleID", wintypes.DWORD),
            ("cntThreads", wintypes.DWORD),
            ("th32ParentProcessID", wintypes.DWORD),
            ("pcPriClassBase", wintypes.LONG),
            ("dwFlags", wintypes.DWORD),
            ("szExeFile", wintypes.WCHAR * 260),
        )

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    snapshot = kernel32.CreateToolhelp32Snapshot(snapshot_flag, 0)
    if snapshot == invalid_handle:
        return False
    target = os.path.normcase(os.fspath(executable))
    entry = ProcessEntry()
    entry.dwSize = ctypes.sizeof(entry)
    try:
        has_entry = bool(kernel32.Process32FirstW(snapshot, ctypes.byref(entry)))
        while has_entry:
            if entry.szExeFile.casefold() == executable.name.casefold():
                handle = kernel32.OpenProcess(
                    process_query_limited_information,
                    False,
                    entry.th32ProcessID,
                )
                if handle:
                    try:
                        size = wintypes.DWORD(32768)
                        buffer = ctypes.create_unicode_buffer(size.value)
                        if (
                            kernel32.QueryFullProcessImageNameW(
                                handle, 0, buffer, ctypes.byref(size)
                            )
                            and os.path.normcase(buffer.value) == target
                        ):
                            return True
                    finally:
                        kernel32.CloseHandle(handle)
            has_entry = bool(kernel32.Process32NextW(snapshot, ctypes.byref(entry)))
    finally:
        kernel32.CloseHandle(snapshot)
    return False


__all__ = (
    "NapCatProcessManager",
    "NapCatStartResult",
    "NapCatWebUIOpenResult",
    "QQChannelHealth",
    "QQChannelState",
    "compose_qq_health",
    "disabled_qq_health",
)
