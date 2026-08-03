"""Supervise the isolated one-shot Codex SDK process."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import cast

from armi_kernel.application import (
    CodexRunnerViolation,
    CodexRunResult,
    CodexTaskManifest,
)

from .codec import encode_task
from .custody_codec import decode_custodied_result
from .runner import CodexRunArtifactSet
from .windows_job import WindowsJob

_MAX_ERROR_BYTES = 4096


def run_custodied_subprocess(
    *,
    environment_root: Path,
    process_temp: Path,
    task: CodexTaskManifest,
    cancellation: threading.Event,
) -> tuple[CodexRunResult, CodexRunArtifactSet]:
    process_temp.mkdir(parents=True, exist_ok=True)
    result: tuple[CodexRunResult, CodexRunArtifactSet] | None = None
    execution_error: CodexRunnerViolation | None = None
    try:
        result = _run_process(
            environment_root=environment_root,
            process_temp=process_temp,
            task=task,
            cancellation=cancellation,
        )
    except CodexRunnerViolation as error:
        execution_error = error
    try:
        shutil.rmtree(process_temp)
    except OSError:
        if execution_error is None:
            execution_error = CodexRunnerViolation("CODEX-CLEANUP")
        else:
            execution_error.record_cleanup_failure("CODEX-CLEANUP")
    if execution_error is not None:
        raise execution_error from None
    if result is None:
        raise CodexRunnerViolation("CODEX-PROCESS")
    return result


def _run_process(
    *,
    environment_root: Path,
    process_temp: Path,
    task: CodexTaskManifest,
    cancellation: threading.Event,
) -> tuple[CodexRunResult, CodexRunArtifactSet]:
    process = subprocess.Popen(
        (
            sys.executable,
            "-m",
            "armi_runtime.codex_runner_cli",
            "--environment-root",
            str(environment_root),
            "--custodied",
        ),
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        cwd=environment_root,
        env=_environment(process_temp),
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    stdout = b""
    stderr = b""
    payload: bytes | None = encode_task(task)
    deadline = time.monotonic() + task.deadline_seconds + 60
    with WindowsJob() as job:
        try:
            job.assign(int(process._handle))  # type: ignore[attr-defined]
            while True:
                if cancellation.is_set():
                    job.close()
                    process.wait(timeout=15)
                    raise CodexRunnerViolation("CODEX-CANCELLED")
                if time.monotonic() >= deadline:
                    job.close()
                    process.wait(timeout=15)
                    raise CodexRunnerViolation("CODEX-TIMEOUT")
                try:
                    stdout, stderr = process.communicate(input=payload, timeout=0.25)
                    break
                except subprocess.TimeoutExpired:
                    payload = None
        except CodexRunnerViolation:
            raise
        except OSError, subprocess.SubprocessError:
            job.close()
            raise CodexRunnerViolation("CODEX-PROCESS", outcome_unknown=True) from None
    if process.returncode != 0:
        raise _decode_failure(stderr)
    if stderr:
        raise CodexRunnerViolation("CODEX-STDOUT-POLLUTION")
    result, artifacts = decode_custodied_result(stdout)
    if result.execution_id != task.execution_id:
        raise CodexRunnerViolation("CODEX-RESULT-FORMAT")
    return result, artifacts


def _decode_failure(value: bytes) -> CodexRunnerViolation:
    if not value or len(value) > _MAX_ERROR_BYTES:
        return CodexRunnerViolation("CODEX-PROCESS")
    try:
        parsed = json.loads(value.decode("utf-8", "strict"))
        if type(parsed) is not dict:
            raise ValueError
        data = cast(dict[str, object], parsed)
        if frozenset(data) != frozenset(
            {"status", "code", "cleanup_error_code", "message"}
        ):
            raise ValueError
        code = data["code"]
        cleanup = data["cleanup_error_code"]
        if (
            data["status"] != "blocked"
            or type(code) is not str
            or not code.startswith("CODEX-")
            or (cleanup is not None and type(cleanup) is not str)
        ):
            raise ValueError
        error = CodexRunnerViolation(code)
        if type(cleanup) is str:
            error.record_cleanup_failure(cleanup)
        return error
    except UnicodeDecodeError, ValueError, json.JSONDecodeError:
        return CodexRunnerViolation("CODEX-PROCESS")


def _environment(temp: Path) -> dict[str, str]:
    windows = Path(os.environ.get("WINDIR", r"C:\Windows"))
    return {
        "PATH": os.pathsep.join(
            (
                str(windows / "System32"),
                str(windows / "System32/WindowsPowerShell/v1.0"),
            )
        ),
        "SYSTEMROOT": str(windows),
        "WINDIR": str(windows),
        "TEMP": str(temp),
        "TMP": str(temp),
        "PYTHONIOENCODING": "utf-8:strict",
    }


__all__ = ("run_custodied_subprocess",)
