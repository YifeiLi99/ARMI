"""Local semantic-recall process lifecycle tests."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

import pytest
from armi_runtime.composition import semantic_recall_process
from armi_runtime.composition.runtime_errors import RuntimeViolation
from armi_runtime.composition.semantic_recall_process import (
    SemanticRecallProcessManager,
)


def _environment_root(tmp_path: Path) -> Path:
    root = tmp_path / "environment"
    root.mkdir()
    (root / "environment.yaml").write_text("environment: {}\n", encoding="utf-8")
    return root


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
    profile.write_text(
        '{"schema_version":"armi.semantic-recall-profile.v1","gpu_layers":28}\n',
        encoding="utf-8",
    )
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
