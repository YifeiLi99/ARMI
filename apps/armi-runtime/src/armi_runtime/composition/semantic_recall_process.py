"""Install and manage the environment-bound local semantic-recall service."""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import socket
import subprocess
import time
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, BinaryIO, cast

import httpx
from armi_context.api import (
    EMBEDDING_MODEL_ID,
    EMBEDDING_MODEL_REVISION,
    EMBEDDING_MODEL_SHA256,
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
_PROFILE_SCHEMA = "armi.semantic-recall-profile.v1"
_START_TIMEOUT_SECONDS = 30.0


@dataclass(frozen=True, slots=True)
class SemanticRecallEndpoint:
    base_url: str
    api_key: str
    model_id: str


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
        selected = self.calibrate()
        return {
            "status": "installed",
            "model_id": EMBEDDING_MODEL_ID,
            "llama_cpp_version": LLAMA_CPP_VERSION,
            "gpu_layers": selected,
        }

    def calibrate(self) -> int:
        for layers in (28, 24, 16, 8, 0):
            gpu_memory_before = self._gpu_memory_mib()
            _atomic_json(
                self._profile_path,
                {"schema_version": _PROFILE_SCHEMA, "gpu_layers": layers},
            )
            try:
                self.start(force=True)
                latency_ms = self._benchmark()
                gpu_memory = max(0, self._gpu_memory_mib() - gpu_memory_before)
            except RuntimeViolation:
                self.stop()
                continue
            self.stop()
            if gpu_memory <= 1024 and latency_ms <= 200:
                _atomic_json(
                    self._profile_path,
                    {
                        "schema_version": _PROFILE_SCHEMA,
                        "gpu_layers": layers,
                        "calibrated_p95_ms": latency_ms,
                        "calibrated_gpu_memory_mib": gpu_memory,
                    },
                )
                return layers
        raise RuntimeViolation(
            "SEMANTIC-RECALL-CALIBRATION",
            "no local embedding profile satisfied the resource and latency gates",
        )

    def start(self, *, force: bool = False) -> dict[str, object]:
        if not force and not self.enabled:
            return {"status": "disabled"}
        current = self.status()
        if current["status"] == "running":
            return {**current, "status": "already_running"}
        install = self._verified_install()
        profile = _read_json(self._profile_path, "SEMANTIC-RECALL-PROFILE")
        layers = profile.get("gpu_layers")
        if type(layers) is not int or not 0 <= layers <= 28:
            raise RuntimeViolation(
                "SEMANTIC-RECALL-PROFILE", "semantic recall profile is invalid"
            )
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
        if layers == 0:
            command += ("--device", "none", "--no-op-offload")
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
                return {
                    "status": "running",
                    "pid": process.pid,
                    "port": port,
                    "model_id": EMBEDDING_MODEL_ID,
                    "gpu_layers": layers,
                }
            time.sleep(0.1)
        process.terminate()
        self._clear_run_files()
        raise RuntimeViolation(
            "SEMANTIC-RECALL-START",
            "local embedding service did not become healthy before timeout",
        )

    def status(self) -> dict[str, object]:
        state_path = self._run_root / "service.json"
        if not state_path.is_file():
            return {
                "status": "installed" if self._install_path.is_file() else "missing"
            }
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
            return {
                "status": "running",
                "pid": pid,
                "port": port,
                "model_id": state.get("model_id"),
                "gpu_layers": state.get("gpu_layers"),
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

    def _benchmark(self) -> int:
        endpoint = self.endpoint()
        durations: list[float] = []
        text = "请找出与这段当前对话最相关的个人记忆和生活资料。" * 5
        for _ in range(20):
            started = time.perf_counter()
            try:
                response = httpx.post(
                    f"{endpoint.base_url}/embeddings",
                    headers={"authorization": f"Bearer {endpoint.api_key}"},
                    json={"model": endpoint.model_id, "input": text},
                    timeout=10,
                    trust_env=False,
                )
                response.raise_for_status()
            except httpx.HTTPError as exc:
                raise RuntimeViolation(
                    "SEMANTIC-RECALL-CALIBRATION", "embedding benchmark failed"
                ) from exc
            durations.append((time.perf_counter() - started) * 1000)
        durations.sort()
        return round(durations[18])

    @staticmethod
    def _gpu_memory_mib() -> int:
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
        return sum(values)

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
