"""Install and manage the environment-bound local semantic-recall service."""

# ruff: noqa: RUF001

from __future__ import annotations

import ctypes
import hashlib
import json
import math
import os
import secrets
import socket
import subprocess
import time
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from statistics import median
from typing import Any, BinaryIO, cast

import httpx
from armi_context.api import (
    EMBEDDING_DIMENSIONS,
    EMBEDDING_MODEL_ID,
    EMBEDDING_MODEL_REVISION,
    EMBEDDING_MODEL_SHA256,
    EMBEDDING_QUERY_INSTRUCTION,
)

from .runtime_errors import RuntimeViolation

LLAMA_CPP_VERSION = "b10218"
LLAMA_ARCHIVE = f"llama-{LLAMA_CPP_VERSION}-bin-win-cuda-12.4-x64.zip"
LLAMA_ARCHIVE_SHA256 = (
    "28b08668627672d9f91ff716c32cd08e1d8d14b2e65427627951e5fc29d802a1"
)
CUDA_ARCHIVE = "cudart-llama-bin-win-cuda-12.4-x64.zip"
CUDA_ARCHIVE_SHA256 = "8c79a9b226de4b3cacfd1f83d24f962d0773be79f1e7b75c6af4ded7e32ae1d6"
MODEL_FILENAME = "Qwen3-Embedding-0.6B-Q8_0.gguf"
_MODEL_URL = (
    "https://huggingface.co/Qwen/Qwen3-Embedding-0.6B-GGUF/resolve/"
    f"{EMBEDDING_MODEL_REVISION}/{MODEL_FILENAME}?download=true"
)
_RELEASE_BASE = (
    f"https://github.com/ggml-org/llama.cpp/releases/download/{LLAMA_CPP_VERSION}"
)
_SCHEMA = "armi.semantic-recall-service.v1"
_INSTALL_SCHEMA = "armi.semantic-recall-install.v1"
_PROFILE_SCHEMA = "armi.semantic-recall-profile.v2"
_START_TIMEOUT_SECONDS = 30.0
_GPU_LAYERS = 28
_GPU_MEMORY_LIMIT_MIB = 1800
_RSS_LIMIT_MIB = 1536
_IDLE_CPU_LIMIT_PERCENT = 1.0
_LATENCY_LIMITS_MS = {100: 30, 256: 50, 700: 100}
_CALIBRATION_SAMPLES = 30
_CALIBRATION_TOPICS = (
    "主人把纪念日安排在五月二十日并准备蓝莓蛋糕",
    "团团不能吃三文鱼但很喜欢在书房窗边睡觉",
    "下次去冰岛旅行时要避开夜间起飞的红眼航班",
    "极光计划使用内部代号Aurora十七并由林晓负责",
    "书房路由器地址是一九二点一六八点五十点一",
    "周三晚上练四十五分钟钢琴之后整理当天的笔记",
    "手冲咖啡使用埃塞俄比亚浅烘豆和九十二度热水",
    "卧室空调睡眠温度保持二十四度并使用最低风速",
    "每月十五号给绿萝施肥但进入冬季以后暂停养护",
    "牙医预约安排在九月三日上午十点半不要迟到",
    "家庭存储设备名为MoonVault凌晨两点开始备份",
    "跑步鞋需要四十二码宽楦并且不要选择碳板结构",
    "电影清单优先安排科幻片暂时避开所有恐怖电影",
    "药箱里的布洛芬有效期到二零二七年十一月",
    "会议室预订名称是Nebula临时门禁码为六零四八",
    "车辆每行驶一万公里保养下次里程是四万八千",
    "常用代码分支使用codex斜杠前缀并写中文提交说明",
    "生日蛋糕要求低糖不放芒果并使用新鲜蓝莓装饰",
    "紧急联系人是林晓电话号码最后四位为七三一九",
    "主人不喜欢香菜的味道但是能够接受少量欧芹",
    "周末计划沿河慢跑六公里下雨时改为室内单车",
    "客厅阅读灯使用暖黄色亮度保持在百分之四十",
    "重要文件每周日同步到离线硬盘并核对备份结果",
    "上午工作前先喝一杯温水再检查当天活动安排",
    "厨房采购清单需要燕麦牛奶鸡蛋以及无糖酸奶",
    "睡前不再查看工作消息而是阅读半小时纸质小说",
    "朋友来访时准备乌龙茶并提前整理靠窗的座位",
    "冬季旅行需要携带防水手套和备用相机电池",
    "每次长途驾驶两小时后停车休息并补充饮用水",
    "书桌右侧抽屉保存备用钥匙和设备保修凭证",
)


@dataclass(frozen=True, slots=True)
class SemanticRecallEndpoint:
    base_url: str
    api_key: str
    model_id: str


def _calibration_query(length: int, index: int, *, label: str | None = None) -> str:
    topic = _CALIBRATION_TOPICS[index % len(_CALIBRATION_TOPICS)]
    identity = label or f"length-{length}-sample-{index + 1}"
    prefix = f"检索场景{identity}：{topic}。请找出与这件事真正有关的记忆和生活资料。"
    filler = f"补充语境是{topic}，需要保留专名、数字、偏好、时间和隐含含义。"
    value = prefix
    while len(value) < length:
        value += filler
    return value[:length]


class _ProcessMemoryCounters(ctypes.Structure):
    _fields_ = (
        ("cb", ctypes.c_ulong),
        ("PageFaultCount", ctypes.c_ulong),
        ("PeakWorkingSetSize", ctypes.c_size_t),
        ("WorkingSetSize", ctypes.c_size_t),
        ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
        ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
        ("PagefileUsage", ctypes.c_size_t),
        ("PeakPagefileUsage", ctypes.c_size_t),
    )


class _FileTime(ctypes.Structure):
    _fields_ = (("low", ctypes.c_ulong), ("high", ctypes.c_ulong))


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _atomic_json(path: Path, value: object, *, mode: int = 0o600) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
        + "\n",
        encoding="utf-8",
        newline="\n",
    )
    temporary.chmod(mode)
    temporary.replace(path)
    path.chmod(mode)


def _read_json(path: Path, code: str) -> dict[str, Any]:
    try:
        value: object = json.loads(path.read_text(encoding="utf-8", errors="strict"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise RuntimeViolation(code, "semantic recall metadata is unavailable") from exc
    if not isinstance(value, dict):
        raise RuntimeViolation(code, "semantic recall metadata is invalid")
    return cast(dict[str, Any], value)


def _protect_secret_file(path: Path) -> None:
    if os.name != "nt":
        path.chmod(0o600)
        return
    windows = Path(os.environ.get("WINDIR", r"C:\Windows"))
    try:
        account_result = subprocess.run(
            (os.fspath(windows / "System32" / "whoami.exe"),),
            check=True,
            capture_output=True,
            timeout=5,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        account = account_result.stdout.decode("utf-8", errors="strict").strip()
        if not account or "\n" in account or "\r" in account:
            raise OSError
        subprocess.run(
            (
                os.fspath(windows / "System32" / "icacls.exe"),
                os.fspath(path),
                "/inheritance:r",
                "/grant:r",
                f"{account}:F",
                "/grant:r",
                "SYSTEM:F",
            ),
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=10,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
    except (OSError, UnicodeError, subprocess.SubprocessError) as exc:
        raise RuntimeViolation(
            "SEMANTIC-RECALL-TOKEN", "semantic recall API token could not be protected"
        ) from exc


def _safe_extract(archive: Path, destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    root = destination.resolve(strict=True)
    with zipfile.ZipFile(archive) as package:
        for item in package.infolist():
            relative = PurePosixPath(item.filename)
            if relative.is_absolute() or ".." in relative.parts:
                raise RuntimeViolation(
                    "SEMANTIC-RECALL-ARCHIVE",
                    "semantic recall archive contains an unsafe path",
                )
            target = (root / Path(*relative.parts)).resolve(strict=False)
            try:
                target.relative_to(root)
            except ValueError:
                raise RuntimeViolation(
                    "SEMANTIC-RECALL-ARCHIVE",
                    "semantic recall archive escapes its install root",
                ) from None
        package.extractall(root)


class SemanticRecallProcessManager:
    __slots__ = (
        "_enabled",
        "_environment_root",
        "_install_path",
        "_profile_path",
        "_run_root",
    )

    def __init__(self, environment_root: Path, *, enabled: bool | None = None) -> None:
        self._environment_root = environment_root.resolve(strict=True)
        self._enabled = enabled
        tool_root = self._environment_root / "tools" / "semantic-recall"
        self._install_path = tool_root / "install.json"
        self._profile_path = tool_root / "profile.json"
        self._run_root = self._environment_root / "run" / "semantic-recall"

    @property
    def enabled(self) -> bool:
        if self._enabled is not None:
            return self._enabled
        environment_path = self._environment_root / "environment.yaml"
        try:
            text = environment_path.read_text(encoding="utf-8", errors="strict")
        except OSError:
            return False
        return "semantic_recall_enabled: true" in text

    def install(self, *, approved_official_direct: bool) -> dict[str, object]:
        if not approved_official_direct:
            raise RuntimeViolation(
                "SEMANTIC-RECALL-EGRESS",
                "official semantic recall download requires explicit approval",
            )
        tool_root = self._install_path.parent
        cache = tool_root / "cache"
        install_root = tool_root / LLAMA_CPP_VERSION
        model_root = self._environment_root / "models" / "semantic-recall"
        cache.mkdir(parents=True, exist_ok=True)
        model_root.mkdir(parents=True, exist_ok=True)
        llama_archive = cache / LLAMA_ARCHIVE
        cuda_archive = cache / CUDA_ARCHIVE
        model_path = model_root / MODEL_FILENAME
        self._download(
            f"{_RELEASE_BASE}/{LLAMA_ARCHIVE}",
            llama_archive,
            LLAMA_ARCHIVE_SHA256,
        )
        self._download(
            f"{_RELEASE_BASE}/{CUDA_ARCHIVE}",
            cuda_archive,
            CUDA_ARCHIVE_SHA256,
        )
        self._download(_MODEL_URL, model_path, EMBEDDING_MODEL_SHA256)
        if not install_root.exists():
            temporary = tool_root / f".{LLAMA_CPP_VERSION}.{os.getpid()}.tmp"
            if temporary.exists():
                raise RuntimeViolation(
                    "SEMANTIC-RECALL-INSTALL",
                    "semantic recall temporary install path already exists",
                )
            _safe_extract(llama_archive, temporary)
            _safe_extract(cuda_archive, temporary)
            temporary.replace(install_root)
        server = next(install_root.rglob("llama-server.exe"), None)
        if server is None or not server.is_file():
            raise RuntimeViolation(
                "SEMANTIC-RECALL-INSTALL",
                "llama-server.exe is missing from the pinned archive",
            )
        _atomic_json(
            self._install_path,
            {
                "schema_version": _INSTALL_SCHEMA,
                "llama_cpp_version": LLAMA_CPP_VERSION,
                "llama_server": os.fspath(server.resolve(strict=True)),
                "llama_server_sha256": _sha256(server),
                "model_id": EMBEDDING_MODEL_ID,
                "model_revision": EMBEDDING_MODEL_REVISION,
                "model_path": os.fspath(model_path.resolve(strict=True)),
                "model_sha256": EMBEDDING_MODEL_SHA256,
                "archives": {
                    LLAMA_ARCHIVE: LLAMA_ARCHIVE_SHA256,
                    CUDA_ARCHIVE: CUDA_ARCHIVE_SHA256,
                },
            },
        )
        calibration = self.calibrate()
        return {
            "status": "installed",
            "model_id": EMBEDDING_MODEL_ID,
            "llama_cpp_version": LLAMA_CPP_VERSION,
            **calibration,
        }

    def calibrate(self) -> dict[str, object]:
        if (self._run_root / "service.json").is_file():
            raise RuntimeViolation(
                "SEMANTIC-RECALL-CALIBRATION-BUSY",
                "local embedding service must be stopped before calibration",
            )
        install = self._verified_install()
        gpu_uuid, gpu_name = self._gpu_identity()
        gpu_before = [self._device_gpu_memory_mib() for _ in range(5)]
        started: dict[str, object] | None = None
        process: subprocess.Popen[Any] | None = None
        try:
            started, endpoint, process = self._start_service(install, _GPU_LAYERS)
            pid = cast(int, started["pid"])
            latency_ms, prompt_tokens = self._benchmark(endpoint)
            process_gpu_memory = self._process_gpu_memory_mib(pid)
            if process_gpu_memory is None:
                gpu_after = [self._device_gpu_memory_mib() for _ in range(5)]
                gpu_memory = max(0, round(median(gpu_after) - median(gpu_before)))
                gpu_measurement = "device_median_delta"
            else:
                gpu_memory = process_gpu_memory
                gpu_measurement = "process"
            rss_memory = self._process_rss_mib(pid)
            idle_cpu = self._idle_cpu_percent(pid)
        finally:
            if started is not None:
                try:
                    self.stop()
                finally:
                    if process is not None and process.poll() is None:
                        process.terminate()
                        try:
                            process.wait(timeout=10)
                        except subprocess.TimeoutExpired:
                            process.kill()
                            process.wait(timeout=10)
        failed = (
            gpu_memory > _GPU_MEMORY_LIMIT_MIB
            or rss_memory > _RSS_LIMIT_MIB
            or idle_cpu > _IDLE_CPU_LIMIT_PERCENT
            or any(
                latency_ms[str(length)] > limit
                for length, limit in _LATENCY_LIMITS_MS.items()
            )
        )
        if failed:
            raise RuntimeViolation(
                "SEMANTIC-RECALL-CALIBRATION",
                "full-GPU embedding profile did not satisfy its gates: "
                f"p95_ms={latency_ms}, gpu_mib={gpu_memory}, "
                f"rss_mib={rss_memory}, idle_cpu_percent={idle_cpu}",
            )
        profile: dict[str, object] = {
            "schema_version": _PROFILE_SCHEMA,
            "model_id": EMBEDDING_MODEL_ID,
            "model_revision": EMBEDDING_MODEL_REVISION,
            "model_sha256": EMBEDDING_MODEL_SHA256,
            "llama_cpp_version": LLAMA_CPP_VERSION,
            "gpu_layers": _GPU_LAYERS,
            "gpu_uuid": gpu_uuid,
            "gpu_name": gpu_name,
            "calibrated_p95_ms": latency_ms,
            "calibrated_prompt_tokens": prompt_tokens,
            "calibrated_gpu_memory_mib": gpu_memory,
            "gpu_memory_measurement": gpu_measurement,
            "calibrated_rss_mib": rss_memory,
            "calibrated_idle_cpu_percent": idle_cpu,
        }
        _atomic_json(self._profile_path, profile)
        return self._profile_view(profile)

    def start(self, *, force: bool = False) -> dict[str, object]:
        if not force and not self.enabled:
            return {"status": "disabled"}
        current = self.status()
        if current["status"] == "running":
            return {**current, "status": "already_running"}
        install = self._verified_install()
        profile = self._verified_profile()
        layers = cast(int, profile["gpu_layers"])
        started, _endpoint, _process = self._start_service(install, layers)
        return {**started, **self._profile_view(profile)}

    def _start_service(
        self, install: dict[str, Any], layers: int
    ) -> tuple[dict[str, object], SemanticRecallEndpoint, subprocess.Popen[Any]]:
        port = self._available_port()
        api_key = secrets.token_urlsafe(32)
        server = Path(str(install["llama_server"]))
        model = Path(str(install["model_path"]))
        self._run_root.mkdir(parents=True, exist_ok=True)
        token_path = self._run_root / "api-key"
        token_path.write_text(api_key, encoding="ascii")
        try:
            _protect_secret_file(token_path)
        except RuntimeViolation:
            token_path.unlink(missing_ok=True)
            raise
        log_handle: BinaryIO = (self._run_root / "server.log").open("ab")
        command = (
            os.fspath(server),
            "--model",
            os.fspath(model),
            "--alias",
            EMBEDDING_MODEL_ID,
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
            "--api-key",
            api_key,
            "--embedding",
            "--pooling",
            "last",
            "--embd-normalize",
            "2",
            "--ctx-size",
            "1024",
            "--parallel",
            "1",
            "--batch-size",
            "1024",
            "--ubatch-size",
            "1024",
            "--n-gpu-layers",
            str(layers),
            "--no-webui",
        )
        options: dict[str, Any] = {
            "cwd": server.parent,
            "stdin": subprocess.DEVNULL,
            "stdout": log_handle,
            "stderr": subprocess.STDOUT,
            "close_fds": True,
        }
        if os.name == "nt":
            options["creationflags"] = (
                subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP
            )
        try:
            process = subprocess.Popen(command, **options)
        except OSError as exc:
            log_handle.close()
            raise RuntimeViolation(
                "SEMANTIC-RECALL-START", "local embedding service could not start"
            ) from exc
        finally:
            log_handle.close()
        _atomic_json(
            self._run_root / "service.json",
            {
                "schema_version": _SCHEMA,
                "pid": process.pid,
                "port": port,
                "model_id": EMBEDDING_MODEL_ID,
                "gpu_layers": layers,
            },
        )
        deadline = time.monotonic() + _START_TIMEOUT_SECONDS
        while time.monotonic() < deadline:
            if process.poll() is not None:
                self._clear_run_files()
                raise RuntimeViolation(
                    "SEMANTIC-RECALL-START",
                    "local embedding service exited before becoming healthy",
                )
            if self._healthy(port, api_key):
                endpoint = SemanticRecallEndpoint(
                    f"http://127.0.0.1:{port}/v1", api_key, EMBEDDING_MODEL_ID
                )
                try:
                    self._embedding_request(
                        endpoint,
                        _calibration_query(64, 0, label="warmup-start"),
                    )
                except RuntimeViolation:
                    process.terminate()
                    try:
                        process.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait(timeout=10)
                    self._clear_run_files()
                    raise
                return (
                    {
                        "status": "running",
                        "pid": process.pid,
                        "port": port,
                        "model_id": EMBEDDING_MODEL_ID,
                        "gpu_layers": layers,
                    },
                    endpoint,
                    process,
                )
            time.sleep(0.1)
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=10)
        self._clear_run_files()
        raise RuntimeViolation(
            "SEMANTIC-RECALL-START",
            "local embedding service did not become healthy before timeout",
        )

    def status(self) -> dict[str, object]:
        profile: dict[str, Any] | None
        try:
            profile = self._verified_profile()
        except RuntimeViolation:
            profile = None
        state_path = self._run_root / "service.json"
        if not state_path.is_file():
            if not self._install_path.is_file():
                return {"status": "missing"}
            if profile is None:
                return {"status": "calibration_required"}
            return {"status": "installed", **self._profile_view(profile)}
        state = _read_json(state_path, "SEMANTIC-RECALL-STATE")
        pid = state.get("pid")
        port = state.get("port")
        try:
            api_key = (self._run_root / "api-key").read_text(encoding="ascii")
        except OSError:
            api_key = ""
        if (
            type(pid) is int
            and type(port) is int
            and api_key
            and self._healthy(port, api_key)
        ):
            if profile is None or state.get("gpu_layers") != _GPU_LAYERS:
                return {"status": "calibration_required", "pid": pid}
            return {
                "status": "running",
                "pid": pid,
                "port": port,
                "model_id": state.get("model_id"),
                "gpu_layers": state.get("gpu_layers"),
                **self._profile_view(profile),
            }
        return {"status": "unavailable", "pid": pid}

    def stop(self) -> dict[str, object]:
        state_path = self._run_root / "service.json"
        if not state_path.is_file():
            self._clear_run_files()
            return {"status": "stopped"}
        state = _read_json(state_path, "SEMANTIC-RECALL-STATE")
        pid = state.get("pid")
        port = state.get("port")
        try:
            api_key = (self._run_root / "api-key").read_text(encoding="ascii")
        except OSError:
            api_key = ""
        owned_process_is_healthy = (
            type(port) is int and bool(api_key) and self._healthy(port, api_key)
        )
        if type(pid) is int and pid > 0 and owned_process_is_healthy:
            owned_port = cast(int, port)
            try:
                subprocess.run(
                    ("taskkill.exe", "/PID", str(pid), "/T", "/F"),
                    check=True,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=10,
                )
            except (OSError, subprocess.SubprocessError) as exc:
                raise RuntimeViolation(
                    "SEMANTIC-RECALL-STOP",
                    "local embedding service could not be stopped",
                ) from exc
            deadline = time.monotonic() + 10
            while time.monotonic() < deadline and self._healthy(owned_port, api_key):
                time.sleep(0.05)
            if self._healthy(owned_port, api_key):
                raise RuntimeViolation(
                    "SEMANTIC-RECALL-STOP",
                    "local embedding service did not stop cleanly",
                )
        self._clear_run_files()
        return {"status": "stopped", "pid": pid}

    def endpoint(self) -> SemanticRecallEndpoint:
        state = self.status()
        if state["status"] != "running":
            raise RuntimeViolation(
                "SEMANTIC-RECALL-UNAVAILABLE",
                "local embedding service is unavailable",
            )
        api_key = (self._run_root / "api-key").read_text(encoding="ascii").strip()
        return SemanticRecallEndpoint(
            f"http://127.0.0.1:{state['port']}/v1",
            api_key,
            EMBEDDING_MODEL_ID,
        )

    def _verified_install(self) -> dict[str, Any]:
        install = _read_json(self._install_path, "SEMANTIC-RECALL-INSTALL")
        if install.get("schema_version") != _INSTALL_SCHEMA:
            raise RuntimeViolation(
                "SEMANTIC-RECALL-INSTALL", "semantic recall install is invalid"
            )
        server = Path(str(install.get("llama_server", "")))
        model = Path(str(install.get("model_path", "")))
        if (
            not server.is_file()
            or not model.is_file()
            or _sha256(server) != install.get("llama_server_sha256")
            or _sha256(model) != EMBEDDING_MODEL_SHA256
        ):
            raise RuntimeViolation(
                "SEMANTIC-RECALL-INSTALL",
                "semantic recall files failed integrity verification",
            )
        return install

    def _verified_profile(self) -> dict[str, Any]:
        profile = _read_json(self._profile_path, "SEMANTIC-RECALL-PROFILE")
        latency_value = profile.get("calibrated_p95_ms")
        tokens_value = profile.get("calibrated_prompt_tokens")
        gpu_memory = profile.get("calibrated_gpu_memory_mib")
        rss_memory = profile.get("calibrated_rss_mib")
        idle_cpu = profile.get("calibrated_idle_cpu_percent")
        measurement = profile.get("gpu_memory_measurement")
        expected_scalars = (
            profile.get("schema_version") == _PROFILE_SCHEMA,
            profile.get("model_id") == EMBEDDING_MODEL_ID,
            profile.get("model_revision") == EMBEDDING_MODEL_REVISION,
            profile.get("model_sha256") == EMBEDDING_MODEL_SHA256,
            profile.get("llama_cpp_version") == LLAMA_CPP_VERSION,
            profile.get("gpu_layers") == _GPU_LAYERS,
            type(profile.get("gpu_uuid")) is str,
            bool(profile.get("gpu_uuid")),
            type(profile.get("gpu_name")) is str,
            bool(profile.get("gpu_name")),
            type(gpu_memory) is int,
            type(rss_memory) is int,
            type(idle_cpu) in {int, float},
            measurement in {"process", "device_median_delta"},
        )
        if not isinstance(latency_value, dict) or not isinstance(tokens_value, dict):
            raise RuntimeViolation(
                "SEMANTIC-RECALL-PROFILE",
                "semantic recall calibration is required",
            )
        latency = cast(dict[str, object], latency_value)
        tokens = cast(dict[str, object], tokens_value)
        if (
            not all(expected_scalars)
            or set(latency) != {"100", "256", "700"}
            or set(tokens) != {"100", "256", "700"}
            or any(type(latency[key]) is not int for key in latency)
            or any(type(tokens[key]) is not int for key in tokens)
            or cast(int, gpu_memory) < 0
            or cast(int, rss_memory) <= 0
            or cast(float, idle_cpu) < 0
            or cast(int, gpu_memory) > _GPU_MEMORY_LIMIT_MIB
            or cast(int, rss_memory) > _RSS_LIMIT_MIB
            or cast(float, idle_cpu) > _IDLE_CPU_LIMIT_PERCENT
            or any(
                cast(int, latency[str(length)]) > limit
                or cast(int, latency[str(length)]) < 0
                for length, limit in _LATENCY_LIMITS_MS.items()
            )
            or any(not 0 < cast(int, tokens[key]) < 1024 for key in tokens)
        ):
            raise RuntimeViolation(
                "SEMANTIC-RECALL-PROFILE",
                "semantic recall calibration is required",
            )
        gpu_uuid, _gpu_name = self._gpu_identity()
        if profile["gpu_uuid"] != gpu_uuid:
            raise RuntimeViolation(
                "SEMANTIC-RECALL-PROFILE",
                "semantic recall calibration does not match the active GPU",
            )
        return profile

    @staticmethod
    def _profile_view(profile: dict[str, Any]) -> dict[str, object]:
        return {
            "gpu_layers": profile["gpu_layers"],
            "gpu_name": profile["gpu_name"],
            "calibrated_p95_ms": profile["calibrated_p95_ms"],
            "calibrated_prompt_tokens": profile["calibrated_prompt_tokens"],
            "calibrated_gpu_memory_mib": profile["calibrated_gpu_memory_mib"],
            "gpu_memory_measurement": profile["gpu_memory_measurement"],
            "calibrated_rss_mib": profile["calibrated_rss_mib"],
            "calibrated_idle_cpu_percent": profile["calibrated_idle_cpu_percent"],
        }

    @staticmethod
    def _download(url: str, destination: Path, expected_sha256: str) -> None:
        if destination.is_file():
            if _sha256(destination) != expected_sha256:
                raise RuntimeViolation(
                    "SEMANTIC-RECALL-DIGEST", "cached semantic recall file is invalid"
                )
            return
        temporary = destination.with_name(f".{destination.name}.{os.getpid()}.tmp")
        try:
            with httpx.stream(
                "GET", url, timeout=600, follow_redirects=True, trust_env=False
            ) as response:
                response.raise_for_status()
                with temporary.open("xb") as handle:
                    for chunk in response.iter_bytes(1024 * 1024):
                        handle.write(chunk)
            if _sha256(temporary) != expected_sha256:
                raise RuntimeViolation(
                    "SEMANTIC-RECALL-DIGEST",
                    "downloaded semantic recall file is invalid",
                )
            temporary.replace(destination)
        except RuntimeViolation:
            temporary.unlink(missing_ok=True)
            raise
        except (OSError, httpx.HTTPError) as exc:
            temporary.unlink(missing_ok=True)
            raise RuntimeViolation(
                "SEMANTIC-RECALL-DOWNLOAD",
                "semantic recall file could not be downloaded",
            ) from exc

    def _benchmark(
        self, endpoint: SemanticRecallEndpoint
    ) -> tuple[dict[str, int], dict[str, int]]:
        with httpx.Client(timeout=10, trust_env=False) as client:
            for index in range(3):
                self._embedding_request(
                    endpoint,
                    _calibration_query(
                        80, index, label=f"warmup-calibration-{index + 1}"
                    ),
                    client=client,
                )
            latency: dict[str, int] = {}
            prompt_tokens: dict[str, int] = {}
            token_medians: list[float] = []
            for length in _LATENCY_LIMITS_MS:
                durations: list[float] = []
                observed_tokens: list[int] = []
                for index in range(_CALIBRATION_SAMPLES):
                    text = _calibration_query(length, index)
                    started = time.perf_counter()
                    observed_tokens.append(
                        self._embedding_request(endpoint, text, client=client)
                    )
                    durations.append((time.perf_counter() - started) * 1000)
                durations.sort()
                rank = math.ceil(0.95 * len(durations)) - 1
                latency[str(length)] = round(durations[rank])
                prompt_tokens[str(length)] = max(observed_tokens)
                token_medians.append(median(observed_tokens))
        if token_medians != sorted(token_medians) or len(set(token_medians)) != 3:
            raise RuntimeViolation(
                "SEMANTIC-RECALL-CALIBRATION",
                "embedding benchmark input lengths were not preserved",
            )
        return latency, prompt_tokens

    @staticmethod
    def _embedding_request(
        endpoint: SemanticRecallEndpoint,
        text: str,
        *,
        client: httpx.Client | None = None,
    ) -> int:
        url = f"{endpoint.base_url}/embeddings"
        headers = {"authorization": f"Bearer {endpoint.api_key}"}
        payload = {
            "model": endpoint.model_id,
            "input": f"{EMBEDDING_QUERY_INSTRUCTION}{text}",
            "encoding_format": "float",
        }
        try:
            response = (
                httpx.post(
                    url,
                    headers=headers,
                    json=payload,
                    timeout=10,
                    trust_env=False,
                )
                if client is None
                else client.post(url, headers=headers, json=payload)
            )
            response.raise_for_status()
            value: object = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise RuntimeViolation(
                "SEMANTIC-RECALL-CALIBRATION", "embedding benchmark failed"
            ) from exc
        if not isinstance(value, dict):
            raise RuntimeViolation(
                "SEMANTIC-RECALL-CALIBRATION", "embedding benchmark response is invalid"
            )
        document = cast(dict[object, object], value)
        data_value = document.get("data")
        usage_value = document.get("usage")
        if not isinstance(data_value, list):
            raise RuntimeViolation(
                "SEMANTIC-RECALL-CALIBRATION", "embedding benchmark response is invalid"
            )
        data = cast(list[object], data_value)
        if (
            len(data) != 1
            or not isinstance(data[0], dict)
            or not isinstance(usage_value, dict)
        ):
            raise RuntimeViolation(
                "SEMANTIC-RECALL-CALIBRATION", "embedding benchmark response is invalid"
            )
        row = cast(dict[object, object], data[0])
        embedding_value = row.get("embedding")
        tokens = cast(dict[object, object], usage_value).get("prompt_tokens")
        if not isinstance(embedding_value, list):
            raise RuntimeViolation(
                "SEMANTIC-RECALL-CALIBRATION", "embedding benchmark response is invalid"
            )
        embedding = cast(list[object], embedding_value)
        if (
            len(embedding) != EMBEDDING_DIMENSIONS
            or any(type(part) not in {int, float} for part in embedding)
            or type(tokens) is not int
            or not 0 < tokens < 1024
        ):
            raise RuntimeViolation(
                "SEMANTIC-RECALL-CALIBRATION", "embedding benchmark response is invalid"
            )
        vector = tuple(float(cast(int | float, part)) for part in embedding)
        norm = math.sqrt(sum(part * part for part in vector))
        if any(not math.isfinite(part) for part in vector) or not 0.98 <= norm <= 1.02:
            raise RuntimeViolation(
                "SEMANTIC-RECALL-CALIBRATION", "embedding benchmark response is invalid"
            )
        return tokens

    @staticmethod
    def _gpu_identity() -> tuple[str, str]:
        try:
            result = subprocess.run(
                (
                    "nvidia-smi.exe",
                    "--query-gpu=uuid,name",
                    "--format=csv,noheader",
                ),
                check=True,
                capture_output=True,
                text=True,
                timeout=10,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise RuntimeViolation(
                "SEMANTIC-RECALL-CALIBRATION", "GPU identity could not be measured"
            ) from exc
        first = next((line for line in result.stdout.splitlines() if line.strip()), "")
        parts = [part.strip() for part in first.split(",", 1)]
        if len(parts) != 2 or not all(parts):
            raise RuntimeViolation(
                "SEMANTIC-RECALL-CALIBRATION", "GPU identity could not be measured"
            )
        return parts[0], parts[1]

    @staticmethod
    def _device_gpu_memory_mib() -> int:
        try:
            result = subprocess.run(
                (
                    "nvidia-smi.exe",
                    "--query-gpu=memory.used",
                    "--format=csv,noheader,nounits",
                ),
                check=True,
                capture_output=True,
                text=True,
                timeout=10,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise RuntimeViolation(
                "SEMANTIC-RECALL-CALIBRATION", "GPU memory could not be measured"
            ) from exc
        values = [
            int(line.strip())
            for line in result.stdout.splitlines()
            if line.strip().isdigit()
        ]
        if not values:
            raise RuntimeViolation(
                "SEMANTIC-RECALL-CALIBRATION", "GPU memory could not be measured"
            )
        return values[0]

    @staticmethod
    def _process_gpu_memory_mib(pid: int) -> int | None:
        try:
            result = subprocess.run(
                (
                    "nvidia-smi.exe",
                    "--query-compute-apps=pid,used_gpu_memory",
                    "--format=csv,noheader,nounits",
                ),
                check=True,
                capture_output=True,
                text=True,
                timeout=10,
            )
        except OSError, subprocess.SubprocessError:
            return None
        for line in result.stdout.splitlines():
            parts = [part.strip() for part in line.split(",")]
            if len(parts) == 2 and parts[0] == str(pid) and parts[1].isdigit():
                return int(parts[1])
        return None

    @staticmethod
    def _process_rss_mib(pid: int) -> int:
        if os.name != "nt":
            raise RuntimeViolation(
                "SEMANTIC-RECALL-CALIBRATION", "process RSS could not be measured"
            )
        try:
            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            psapi = ctypes.WinDLL("psapi", use_last_error=True)
            kernel32.OpenProcess.argtypes = (
                ctypes.c_ulong,
                ctypes.c_int,
                ctypes.c_ulong,
            )
            kernel32.OpenProcess.restype = ctypes.c_void_p
            kernel32.CloseHandle.argtypes = (ctypes.c_void_p,)
            psapi.GetProcessMemoryInfo.argtypes = (
                ctypes.c_void_p,
                ctypes.POINTER(_ProcessMemoryCounters),
                ctypes.c_ulong,
            )
            psapi.GetProcessMemoryInfo.restype = ctypes.c_int
            handle = kernel32.OpenProcess(0x0410, False, pid)
            if not handle:
                raise OSError
            try:
                counters = _ProcessMemoryCounters()
                counters.cb = ctypes.sizeof(counters)
                if not psapi.GetProcessMemoryInfo(
                    handle, ctypes.byref(counters), counters.cb
                ):
                    raise OSError
                return math.ceil(counters.WorkingSetSize / (1024 * 1024))
            finally:
                kernel32.CloseHandle(handle)
        except (AttributeError, OSError, ValueError) as exc:
            raise RuntimeViolation(
                "SEMANTIC-RECALL-CALIBRATION", "process RSS could not be measured"
            ) from exc

    @classmethod
    def _idle_cpu_percent(cls, pid: int) -> float:
        before = cls._process_cpu_seconds(pid)
        started = time.perf_counter()
        time.sleep(3)
        elapsed = time.perf_counter() - started
        after = cls._process_cpu_seconds(pid)
        capacity = max(1, os.cpu_count() or 1)
        return round(max(0.0, after - before) / elapsed / capacity * 100, 3)

    @staticmethod
    def _process_cpu_seconds(pid: int) -> float:
        if os.name != "nt":
            raise RuntimeViolation(
                "SEMANTIC-RECALL-CALIBRATION", "process CPU could not be measured"
            )
        try:
            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            kernel32.OpenProcess.argtypes = (
                ctypes.c_ulong,
                ctypes.c_int,
                ctypes.c_ulong,
            )
            kernel32.OpenProcess.restype = ctypes.c_void_p
            kernel32.CloseHandle.argtypes = (ctypes.c_void_p,)
            kernel32.GetProcessTimes.argtypes = (
                ctypes.c_void_p,
                ctypes.POINTER(_FileTime),
                ctypes.POINTER(_FileTime),
                ctypes.POINTER(_FileTime),
                ctypes.POINTER(_FileTime),
            )
            kernel32.GetProcessTimes.restype = ctypes.c_int
            handle = kernel32.OpenProcess(0x1000, False, pid)
            if not handle:
                raise OSError
            try:
                created = _FileTime()
                exited = _FileTime()
                kernel = _FileTime()
                user = _FileTime()
                if not kernel32.GetProcessTimes(
                    handle,
                    ctypes.byref(created),
                    ctypes.byref(exited),
                    ctypes.byref(kernel),
                    ctypes.byref(user),
                ):
                    raise OSError
                kernel_ticks = (kernel.high << 32) | kernel.low
                user_ticks = (user.high << 32) | user.low
                return (kernel_ticks + user_ticks) / 10_000_000
            finally:
                kernel32.CloseHandle(handle)
        except (AttributeError, OSError, ValueError) as exc:
            raise RuntimeViolation(
                "SEMANTIC-RECALL-CALIBRATION", "process CPU could not be measured"
            ) from exc

    @staticmethod
    def _healthy(port: int, api_key: str) -> bool:
        try:
            response = httpx.get(
                f"http://127.0.0.1:{port}/health",
                headers={"authorization": f"Bearer {api_key}"},
                timeout=0.5,
                trust_env=False,
            )
            return response.status_code == 200
        except httpx.HTTPError:
            return False

    @staticmethod
    def _available_port() -> int:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as channel:
            channel.bind(("127.0.0.1", 0))
            return int(channel.getsockname()[1])

    def _clear_run_files(self) -> None:
        for path in (self._run_root / "service.json", self._run_root / "api-key"):
            path.unlink(missing_ok=True)


__all__ = (
    "LLAMA_CPP_VERSION",
    "SemanticRecallEndpoint",
    "SemanticRecallProcessManager",
)
