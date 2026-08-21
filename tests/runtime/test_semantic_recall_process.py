"""Local semantic-recall process lifecycle tests."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

import pytest
from armi_context.api import EMBEDDING_QUERY_INSTRUCTION
from armi_runtime.composition import semantic_recall_process
from armi_runtime.composition.runtime_errors import RuntimeViolation
from armi_runtime.composition.semantic_recall_process import (
    SemanticRecallEndpoint,
    SemanticRecallProcessManager,
)


def _environment_root(tmp_path: Path) -> Path:
    root = tmp_path / "environment"
    root.mkdir()
    (root / "environment.yaml").write_text("environment: {}\n", encoding="utf-8")
    return root


def _profile(*, gpu_layers: int = 28, gpu_uuid: str = "GPU-test") -> dict[str, object]:
    return {
        "schema_version": "armi.semantic-recall-profile.v2",
        "model_id": "Qwen/Qwen3-Embedding-0.6B-GGUF:Q8_0",
        "model_revision": "370f27d7550e0def9b39c1f16d3fbaa13aa67728",
        "model_sha256": (
            "06507c7b42688469c4e7298b0a1e16deff06caf291cf0a5b278c308249c3e439"
        ),
        "llama_cpp_version": "b10218",
        "gpu_layers": gpu_layers,
        "gpu_uuid": gpu_uuid,
        "gpu_name": "NVIDIA Test GPU",
        "calibrated_p95_ms": {"100": 20, "256": 35, "700": 80},
        "calibrated_prompt_tokens": {"100": 100, "256": 200, "700": 500},
        "calibrated_gpu_memory_mib": 1566,
        "gpu_memory_measurement": "device_median_delta",
        "calibrated_rss_mib": 700,
        "calibrated_idle_cpu_percent": 0.1,
    }


def test_disabled_service_does_not_require_an_install(tmp_path: Path) -> None:
    manager = SemanticRecallProcessManager(_environment_root(tmp_path), enabled=False)

    assert manager.start() == {"status": "disabled"}
    assert manager.status() == {"status": "missing"}


def test_enabled_service_fails_clearly_when_not_installed(tmp_path: Path) -> None:
    manager = SemanticRecallProcessManager(_environment_root(tmp_path), enabled=True)

    with pytest.raises(RuntimeViolation, match="SEMANTIC-RECALL-INSTALL"):
        manager.start()


def test_install_requires_explicit_official_download_approval(tmp_path: Path) -> None:
    manager = SemanticRecallProcessManager(_environment_root(tmp_path))

    with pytest.raises(RuntimeViolation, match="SEMANTIC-RECALL-EGRESS"):
        manager.install(approved_official_direct=False)


def test_start_already_running_crash_restart_and_stop(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _environment_root(tmp_path)
    server = root / "llama-server.exe"
    model = root / "model.gguf"
    server.write_bytes(b"server")
    model.write_bytes(b"model")
    profile = root / "tools/semantic-recall/profile.json"
    profile.parent.mkdir(parents=True)
    profile.write_text(json.dumps(_profile()), encoding="utf-8")
    running = True
    commands: list[tuple[str, ...]] = []
    next_pid = 41000

    class Process:
        def __init__(self, command: tuple[str, ...], **_options: Any) -> None:
            nonlocal next_pid, running
            commands.append(command)
            self.pid = next_pid
            next_pid += 1
            running = True

        def poll(self) -> None:
            return None

        def terminate(self) -> None:
            return None

        def wait(self, *, timeout: int) -> int:
            return 0

        def kill(self) -> None:
            return None

    def healthy(_port: int, _api_key: str) -> bool:
        return running

    def stop_process(*_args: object, **_kwargs: object) -> subprocess.CompletedProcess:
        nonlocal running
        running = False
        return subprocess.CompletedProcess([], 0)

    monkeypatch.setattr(
        SemanticRecallProcessManager,
        "_verified_install",
        lambda _self: {
            "llama_server": str(server),
            "model_path": str(model),
        },
    )
    monkeypatch.setattr(SemanticRecallProcessManager, "_healthy", staticmethod(healthy))
    monkeypatch.setattr(
        SemanticRecallProcessManager,
        "_gpu_identity",
        staticmethod(lambda: ("GPU-test", "NVIDIA Test GPU")),
    )
    monkeypatch.setattr(
        SemanticRecallProcessManager,
        "_embedding_request",
        staticmethod(lambda _endpoint, _text: 100),
    )
    monkeypatch.setattr(
        semantic_recall_process, "_protect_secret_file", lambda _path: None
    )
    monkeypatch.setattr(subprocess, "Popen", Process)
    monkeypatch.setattr(subprocess, "run", stop_process)
    manager = SemanticRecallProcessManager(root, enabled=True)

    started = manager.start()
    assert started["status"] == "running"
    assert manager.start()["status"] == "already_running"
    assert "--embedding" in commands[0]
    assert commands[0][commands[0].index("--pooling") + 1] == "last"
    assert commands[0][commands[0].index("--n-gpu-layers") + 1] == "28"

    running = False
    assert manager.status()["status"] == "unavailable"
    restarted = manager.start()
    assert restarted["status"] == "running"
    assert restarted["pid"] != started["pid"]
    assert manager.stop()["status"] == "stopped"
    assert manager.status()["status"] == "missing"


def test_old_or_cpu_profile_requires_calibration(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _environment_root(tmp_path)
    tool_root = root / "tools/semantic-recall"
    tool_root.mkdir(parents=True)
    (tool_root / "install.json").write_text("{}", encoding="utf-8")
    (tool_root / "profile.json").write_text(
        '{"schema_version":"armi.semantic-recall-profile.unsupported","gpu_layers":0}',
        encoding="utf-8",
    )
    monkeypatch.setattr(
        SemanticRecallProcessManager,
        "_gpu_identity",
        staticmethod(lambda: ("GPU-test", "NVIDIA Test GPU")),
    )

    manager = SemanticRecallProcessManager(root, enabled=True)

    assert manager.status() == {"status": "calibration_required"}


def test_hardware_mismatch_requires_calibration(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _environment_root(tmp_path)
    tool_root = root / "tools/semantic-recall"
    tool_root.mkdir(parents=True)
    (tool_root / "install.json").write_text("{}", encoding="utf-8")
    (tool_root / "profile.json").write_text(
        json.dumps(_profile(gpu_uuid="GPU-old")), encoding="utf-8"
    )
    monkeypatch.setattr(
        SemanticRecallProcessManager,
        "_gpu_identity",
        staticmethod(lambda: ("GPU-new", "NVIDIA Test GPU")),
    )

    assert SemanticRecallProcessManager(root).status() == {
        "status": "calibration_required"
    }


def test_benchmark_uses_varied_queries_and_nearest_rank_p95(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manager = SemanticRecallProcessManager(_environment_root(tmp_path))
    observed: list[str] = []

    def embed(
        _endpoint: SemanticRecallEndpoint,
        text: str,
        *,
        client: object | None = None,
    ) -> int:
        assert client is not None
        observed.append(text)
        if len(text) <= 100:
            return 100
        if len(text) <= 256:
            return 200
        return 500

    monkeypatch.setattr(
        SemanticRecallProcessManager, "_embedding_request", staticmethod(embed)
    )

    latency, tokens = manager._benchmark(
        SemanticRecallEndpoint("http://127.0.0.1:40000/v1", "token", "model")
    )

    assert set(latency) == {"100", "256", "700"}
    assert tokens == {"100": 100, "256": 200, "700": 500}
    measured = observed[3:]
    assert len(measured) == 90
    assert len(set(measured)) == 90
    assert {len(text) for text in measured} == {100, 256, 700}


def test_calibration_request_uses_query_instruction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payloads: list[dict[str, object]] = []

    class Response:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, object]:
            return {
                "data": [{"index": 0, "embedding": [0.03125] * 1024}],
                "usage": {"prompt_tokens": 120},
            }

    def post(_url: str, **options: Any) -> Response:
        payloads.append(options["json"])
        return Response()

    monkeypatch.setattr(semantic_recall_process.httpx, "post", post)
    endpoint = SemanticRecallEndpoint(
        "http://127.0.0.1:40000/v1", "temporary-token", "model"
    )

    tokens = SemanticRecallProcessManager._embedding_request(endpoint, "真实查询")

    assert tokens == 120
    assert payloads[0]["input"] == f"{EMBEDDING_QUERY_INSTRUCTION}真实查询"


def test_calibration_publishes_profile_only_after_all_gates_pass(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _environment_root(tmp_path)
    manager = SemanticRecallProcessManager(root)
    install = {"llama_server": "server", "model_path": "model"}
    stopped: list[bool] = []
    endpoint = SemanticRecallEndpoint("http://127.0.0.1:40000/v1", "token", "model")

    class Process:
        def poll(self) -> int:
            return 0

    monkeypatch.setattr(
        SemanticRecallProcessManager, "_verified_install", lambda _self: install
    )
    monkeypatch.setattr(
        SemanticRecallProcessManager,
        "_gpu_identity",
        staticmethod(lambda: ("GPU-test", "Test GPU")),
    )
    monkeypatch.setattr(
        SemanticRecallProcessManager,
        "_device_gpu_memory_mib",
        staticmethod(lambda: 1000),
    )
    monkeypatch.setattr(
        SemanticRecallProcessManager,
        "_start_service",
        lambda _self, _install, _layers: ({"pid": 42}, endpoint, Process()),
    )
    monkeypatch.setattr(
        SemanticRecallProcessManager,
        "_benchmark",
        lambda _self, _endpoint: (
            {"100": 20, "256": 35, "700": 80},
            {"100": 100, "256": 200, "700": 500},
        ),
    )
    monkeypatch.setattr(
        SemanticRecallProcessManager,
        "_process_gpu_memory_mib",
        staticmethod(lambda _pid: 1566),
    )
    monkeypatch.setattr(
        SemanticRecallProcessManager,
        "_process_rss_mib",
        staticmethod(lambda _pid: 700),
    )
    monkeypatch.setattr(
        SemanticRecallProcessManager,
        "_idle_cpu_percent",
        staticmethod(lambda _pid: 0.1),
    )
    monkeypatch.setattr(
        SemanticRecallProcessManager,
        "stop",
        lambda _self: stopped.append(True) or {},
    )

    result = manager.calibrate()

    assert result["gpu_layers"] == 28
    assert result["calibrated_p95_ms"] == {"100": 20, "256": 35, "700": 80}
    assert stopped == [True]
    stored = json.loads(
        (root / "tools/semantic-recall/profile.json").read_text(encoding="utf-8")
    )
    assert stored["schema_version"] == "armi.semantic-recall-profile.v2"


def test_failed_calibration_keeps_previous_profile_and_stops_service(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _environment_root(tmp_path)
    profile_path = root / "tools/semantic-recall/profile.json"
    profile_path.parent.mkdir(parents=True)
    profile_path.write_text("previous-profile", encoding="utf-8")
    manager = SemanticRecallProcessManager(root)
    endpoint = SemanticRecallEndpoint("http://127.0.0.1:40000/v1", "token", "model")
    stopped: list[bool] = []

    class Process:
        def poll(self) -> int:
            return 0

    monkeypatch.setattr(
        SemanticRecallProcessManager, "_verified_install", lambda _self: {}
    )
    monkeypatch.setattr(
        SemanticRecallProcessManager,
        "_gpu_identity",
        staticmethod(lambda: ("GPU-test", "Test GPU")),
    )
    monkeypatch.setattr(
        SemanticRecallProcessManager,
        "_device_gpu_memory_mib",
        staticmethod(lambda: 1000),
    )
    monkeypatch.setattr(
        SemanticRecallProcessManager,
        "_start_service",
        lambda _self, _install, _layers: ({"pid": 42}, endpoint, Process()),
    )
    monkeypatch.setattr(
        SemanticRecallProcessManager,
        "_benchmark",
        lambda _self, _endpoint: (
            {"100": 31, "256": 35, "700": 80},
            {"100": 100, "256": 200, "700": 500},
        ),
    )
    monkeypatch.setattr(
        SemanticRecallProcessManager,
        "_process_gpu_memory_mib",
        staticmethod(lambda _pid: 1566),
    )
    monkeypatch.setattr(
        SemanticRecallProcessManager,
        "_process_rss_mib",
        staticmethod(lambda _pid: 700),
    )
    monkeypatch.setattr(
        SemanticRecallProcessManager,
        "_idle_cpu_percent",
        staticmethod(lambda _pid: 0.1),
    )
    monkeypatch.setattr(
        SemanticRecallProcessManager,
        "stop",
        lambda _self: stopped.append(True) or {},
    )

    with pytest.raises(RuntimeViolation, match="SEMANTIC-RECALL-CALIBRATION"):
        manager.calibrate()

    assert stopped == [True]
    assert profile_path.read_text(encoding="utf-8") == "previous-profile"
