from __future__ import annotations

import ctypes
import json
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
from uuid import uuid7

import pytest
from armi_codex import _runner as runner_module
from armi_codex._codec import decode_result, decode_task, encode_result, encode_task
from armi_codex._runner import IsolatedCodexRunner
from armi_codex._sdk_codec import SdkTurnEvidence
from armi_codex._subprocess_client import _decode_failure, run_subprocess
from armi_codex.api import (
    CodexExecutionId,
    CodexModel,
    CodexReasoningEffort,
    CodexRunnerViolation,
    CodexRunResult,
    CodexRunStatus,
    CodexTaskManifest,
    CodexUsage,
)
from armi_kernel.application import (
    CredentialLocator,
    CredentialPort,
    CredentialPurpose,
    SecretHandle,
)


def test_supervisor_cancellation_terminates_child_process_tree(tmp_path: Path) -> None:
    task, _workspace = _prepare_output_task(tmp_path)
    module = tmp_path / "controlled_runner.py"
    module.write_text(
        "import subprocess,sys,time\nfrom pathlib import Path\n"
        "child=subprocess.Popen([sys.executable,'-c','import time; time.sleep(60)'])\n"
        "Path('child.pid').write_text(str(child.pid))\ntime.sleep(60)\n",
        encoding="utf-8",
    )
    cancellation = threading.Event()
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.OpenProcess.restype = ctypes.c_void_p
    kernel.OpenProcess.argtypes = (ctypes.c_uint32, ctypes.c_int, ctypes.c_uint32)
    kernel.WaitForSingleObject.argtypes = (ctypes.c_void_p, ctypes.c_uint32)
    kernel.CloseHandle.argtypes = (ctypes.c_void_p,)
    handle = None
    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(
            run_subprocess,
            runner_entry_module="controlled_runner",
            environment_root=tmp_path,
            process_temp=tmp_path / "supervisor-temp",
            task=task,
            cancellation=cancellation,
        )
        try:
            deadline = time.monotonic() + 10
            marker = tmp_path / "child.pid"
            while not marker.exists() and time.monotonic() < deadline:
                time.sleep(0.01)
            assert marker.exists()
            handle = kernel.OpenProcess(0x00100000, False, int(marker.read_text()))
            assert handle
        finally:
            cancellation.set()
        try:
            with pytest.raises(CodexRunnerViolation, match="CODEX-CANCELLED"):
                future.result(timeout=20)
            assert kernel.WaitForSingleObject(handle, 5000) == 0
            assert not (tmp_path / "supervisor-temp").exists()
        finally:
            if handle:
                kernel.CloseHandle(handle)


class _Handle:
    def __init__(self, value: bytes) -> None:
        self.value = bytearray(value)
        self.closed = False

    def consume(self, operation):  # type: ignore[no-untyped-def]
        if self.closed:
            raise RuntimeError
        return operation(memoryview(self.value).toreadonly())

    def close(self) -> None:
        for index in range(len(self.value)):
            self.value[index] = 0
        self.closed = True

    def __enter__(self):  # type: ignore[no-untyped-def]
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        self.close()


def test_codex_runner_preflight_starts_without_model_invocation() -> None:
    root = Path(__file__).resolve().parents[3]
    completed = subprocess.run(
        (
            sys.executable,
            str(root / "tools/verify_codex_runner.py"),
            "--preflight",
        ),
        cwd=root,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=30,
    )
    evidence = json.loads(completed.stdout)

    assert completed.returncode == 0, completed.stderr
    assert completed.stderr == ""
    assert evidence["result"] == "pass"
    assert evidence["model_invocation_count"] == 0
    assert evidence["sdk_version"] == "0.144.4"
    assert evidence["runtime_version"] == "0.144.4"
    assert evidence["job_object"] == "pass"
    assert evidence["platform_home"] == "clean_reusable"


class _Credentials(CredentialPort):
    def resolve(
        self, locator: CredentialLocator, purpose: CredentialPurpose
    ) -> SecretHandle:
        assert locator.identity() == "file:auth.json"
        assert purpose.value == "codex.runner.auth"
        return _Handle(b'{"tokens":{"access_token":"conformance"}}')


def _prepare(tmp_path: Path) -> tuple[CodexTaskManifest, Path]:
    return CodexTaskManifest(
        CodexExecutionId(uuid7()),
        uuid7(),
        uuid7(),
        "整理资料并说明来源。",
        60,
    ), tmp_path / "runs"


_prepare_output_task = _prepare


def _evidence(output: str) -> SdkTurnEvidence:
    return SdkTurnEvidence(output, CodexUsage(12, 0, 4))


def test_runner_message_preserves_plain_result_and_cleanup_failure(
    tmp_path: Path,
) -> None:
    task, _root = _prepare(tmp_path)
    result = CodexRunResult(
        task.execution_id,
        CodexRunStatus.SUCCEEDED,
        "gpt-5.6-sol",
        "0.144.4",
        "中文结果\n含来源",
        None,
        cleanup_error_code="CODEX-CLEANUP",
    )
    assert decode_result(encode_result(result)) == result
    assert decode_task(encode_task(task)) == task
    with pytest.raises(CodexRunnerViolation, match="CODEX-RESULT-FORMAT"):
        decode_result(encode_result(result) + b"trailing")


def test_subprocess_failure_preserves_unknown_outcome() -> None:
    error = _decode_failure(
        b'{"cleanup_error_code":null,"code":"CODEX-STREAM-DISCONNECTED",'
        b'"message":"Codex runner operation failed","outcome_unknown":true,'
        b'"status":"blocked"}'
    )
    assert error.code == "CODEX-STREAM-DISCONNECTED"
    assert error.outcome_unknown is True


def test_task_options_use_luna_low_reasoning_and_live_search(
    tmp_path: Path,
) -> None:
    task, _run_root = _prepare(tmp_path)
    task = replace(
        task,
        model_id=CodexModel.LUNA,
        reasoning_effort=CodexReasoningEffort.LOW,
        web_search=True,
    )
    config = runner_module._config(task)

    assert runner_module._model(task) == "gpt-5.6-luna"
    assert 'model_reasoning_effort="low"' in config
    assert 'web_search="live"' in config
    assert "tools.web_search=true" in config
    assert "sandbox_workspace_write.network_access=false" in config
    assert 'web_search="disabled"' not in config
    assert runner_module._prompt(task) == task.objective


def test_task_codec_rejects_duplicate_keys() -> None:
    with pytest.raises(CodexRunnerViolation, match="CODEX-TASK-FORMAT"):
        decode_task(b'{"schema_version":"a","schema_version":"b"}')


@pytest.mark.asyncio
async def test_fake_sdk_run_is_scoped_and_preserves_only_platform_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    task, run_root = _prepare(tmp_path)

    async def fake_invoke_sdk(**values):  # type: ignore[no-untyped-def]
        workspace = values["workspace"]
        platform_home = values["platform_home"]
        assert (platform_home / "auth.json").is_file()
        (workspace / "result.txt").write_text(
            "ARMI_CODEX_CONFORMANCE_OK\n", encoding="utf-8", newline="\n"
        )
        return _evidence("任务结果及来源")

    monkeypatch.setattr(runner_module, "_invoke_sdk", fake_invoke_sdk)
    runner = IsolatedCodexRunner(
        run_root=run_root,
        credential_port=_Credentials(),
        auth_locator=CredentialLocator.parse("file:auth.json"),
    )
    result = await runner.run(task)
    assert result.status is CodexRunStatus.SUCCEEDED
    assert result.final_response == "任务结果及来源"
    assert result.usage is not None and result.usage.input_tokens == 12
    assert not (run_root / "private" / task.execution_id.value.hex).exists()
    assert {path.name for path in (run_root / "platform-home").iterdir()} == {
        "runner-state.json"
    }


@pytest.mark.asyncio
async def test_completed_result_survives_cleanup_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    task, run_root = _prepare(tmp_path)

    async def fake_invoke_sdk(**values):
        # Scratch files do not invalidate an otherwise completed delegation.
        (values["workspace"] / "notes.txt").write_text("scratch", encoding="utf-8")
        return _evidence("研究结果与来源")

    original_cleanup = runner_module.remove_private_directory

    def cleanup_reports_failure(path):
        original_cleanup(path)
        raise CodexRunnerViolation("CODEX-CLEANUP")

    monkeypatch.setattr(runner_module, "_invoke_sdk", fake_invoke_sdk)
    monkeypatch.setattr(
        runner_module, "remove_private_directory", cleanup_reports_failure
    )
    runner = IsolatedCodexRunner(
        run_root=run_root,
        credential_port=_Credentials(),
        auth_locator=CredentialLocator.parse("file:auth.json"),
    )
    result = await runner.run(task)
    assert result.status is CodexRunStatus.SUCCEEDED
    assert result.final_response == "研究结果与来源"
    assert result.cleanup_error_code == "CODEX-CLEANUP"


@pytest.mark.asyncio
async def test_unknown_persistent_platform_state_blocks_reuse(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    task, run_root = _prepare(tmp_path)
    platform = run_root / "platform-home"
    platform.mkdir(parents=True)
    runner_module._write_platform_state(platform, usable=True)
    (platform / "config.toml").write_text("model='bad'\n", encoding="utf-8")
    monkeypatch.setattr(runner_module, "_owner_only", lambda path: None)
    runner = IsolatedCodexRunner(
        run_root=run_root,
        credential_port=_Credentials(),
        auth_locator=CredentialLocator.parse("file:auth.json"),
    )
    with pytest.raises(CodexRunnerViolation, match="CODEX-PLATFORM-HOME"):
        await runner.run(task)


@pytest.mark.asyncio
async def test_cleanup_failure_does_not_replace_execution_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    task, run_root = _prepare(tmp_path)

    async def fake_invoke_sdk(**values):  # type: ignore[no-untyped-def]
        del values
        raise CodexRunnerViolation("CODEX-TIMEOUT")

    def fake_cleanup(path: Path) -> None:
        del path
        raise CodexRunnerViolation("CODEX-CLEANUP")

    monkeypatch.setattr(runner_module, "_invoke_sdk", fake_invoke_sdk)
    monkeypatch.setattr(runner_module, "remove_private_directory", fake_cleanup)
    runner = IsolatedCodexRunner(
        run_root=run_root,
        credential_port=_Credentials(),
        auth_locator=CredentialLocator.parse("file:auth.json"),
    )
    with pytest.raises(CodexRunnerViolation) as captured:
        await runner.run(task)
    assert captured.value.code == "CODEX-TIMEOUT"
    assert captured.value.cleanup_error_code == "CODEX-CLEANUP"
