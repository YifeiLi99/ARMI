"""Run the explicit S038 no-model preflight or single SDK live gate."""

from __future__ import annotations

import argparse
import importlib.metadata
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import time
import zipfile
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any, cast
from uuid import uuid7

import rfc8785
from armi_kernel.application import (
    CodexExecutionId,
    CodexRunStatus,
    CodexTaskManifest,
)
from armi_kernel.contracts import Digest
from armi_runtime.adapters.codex.codec import decode_result, encode_task
from armi_runtime.adapters.codex.runner import (
    _config,
    _owner_only,
    _sanitize_platform_home,
    _validate_platform_home,
    _write_platform_state,
)
from armi_runtime.adapters.codex.windows_job import WindowsJob
from armi_runtime.adapters.codex.workspace import snapshot_tree

_SDK_VERSION = "0.144.4"
_MODEL = "gpt-5.6-sol"
_GATE_ID = "s038-openai-python-sdk-live-gate-final"
_PREFLIGHT_ID = "s038-openai-python-sdk-preflight-1"


def _strict_object(value: bytes) -> dict[str, object]:
    def hook(items: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, item in items:
            if key in result:
                raise ValueError
            result[key] = item
        return result

    try:
        parsed = json.loads(value.decode("utf-8", "strict"), object_pairs_hook=hook)
    except UnicodeDecodeError, json.JSONDecodeError, ValueError:
        raise RuntimeError("CODEX-LIVE-AUTH") from None
    if type(parsed) is not dict:
        raise RuntimeError("CODEX-LIVE-AUTH")
    return cast(dict[str, object], parsed)


def _auth_source() -> bytearray:
    configured = os.environ.get("CODEX_HOME")
    root = Path(configured) if configured else Path.home() / ".codex"
    source = root / "auth.json"
    try:
        metadata = source.stat(follow_symlinks=False)
        value = source.read_bytes()
    except OSError:
        raise RuntimeError("CODEX-LIVE-AUTH") from None
    if (
        source.is_symlink()
        or not source.is_file()
        or not 0 < metadata.st_size <= 1024 * 1024
    ):
        raise RuntimeError("CODEX-LIVE-AUTH")
    if _strict_object(value).get("auth_mode") != "chatgpt":
        raise RuntimeError("CODEX-LIVE-AUTH-MODE")
    return bytearray(value)


def _runtime_binary() -> tuple[Path, str]:
    sdk = importlib.metadata.distribution("openai-codex")
    runtime = importlib.metadata.distribution("openai-codex-cli-bin")
    files = [
        item for item in runtime.files or () if item.as_posix().endswith("codex.exe")
    ]
    if (
        sdk.version != _SDK_VERSION
        or runtime.version != _SDK_VERSION
        or len(files) != 1
    ):
        raise RuntimeError("CODEX-PREFLIGHT-SDK-VERSION")
    binary = Path(os.fspath(cast(Any, runtime.locate_file(files[0])))).resolve()
    if not binary.is_file() or binary.is_symlink():
        raise RuntimeError("CODEX-PREFLIGHT-RUNTIME")
    completed = subprocess.run(
        [str(binary), "--version"],
        check=False,
        capture_output=True,
        timeout=10,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    version = completed.stdout.decode("utf-8", errors="strict").strip()
    if completed.returncode != 0 or version != "codex-cli 0.144.4":
        raise RuntimeError("CODEX-PREFLIGHT-RUNTIME")
    return binary, Digest.from_bytes(binary.read_bytes()).to_wire()


def _write_source(root: Path) -> tuple[Path, Path]:
    source = root / "source"
    source.mkdir()
    (source / "result.txt").write_bytes(b"PENDING\n")
    bundle = root / "source.zip"
    with zipfile.ZipFile(bundle, "w", compression=zipfile.ZIP_STORED) as archive:
        archive.write(source / "result.txt", "result.txt")
    return source, bundle


def _task(root: Path, execution: CodexExecutionId) -> tuple[CodexTaskManifest, Path]:
    source, bundle = _write_source(root)
    source_tree = snapshot_tree(source, byte_limit=1024 * 1024)
    bundle_digest = Digest.from_bytes(bundle.read_bytes())
    task = CodexTaskManifest(
        execution_id=execution,
        task_id=uuid7(),
        effect_id=uuid7(),
        source_bundle_digest=bundle_digest,
        source_tree_digest=source_tree.digest,
        objective="Replace result.txt with ARMI_CODEX_CONFORMANCE_OK followed by LF.",
        facts=(
            "result.txt is the only file in the conformance workspace.",
            "The independent validator requires its exact UTF-8 bytes.",
        ),
        allowed_paths=("result.txt",),
        forbidden_paths=(),
        validator_id="codex.conformance.minimal-edit.v1",
        deadline_seconds=900,
    )
    return task, bundle


def _environment(root: Path, auth: bytes) -> tuple[Path, Path]:
    environment_root = root / "environment"
    data_root = environment_root / "data"
    secret_root = environment_root / "secrets"
    data_root.mkdir(parents=True)
    secret_root.mkdir()
    _owner_only(secret_root)
    auth_path = secret_root / "auth.json"
    auth_path.write_bytes(auth)
    (environment_root / "environment.toml").write_text(
        "\n".join(
            (
                "[environment]",
                'environment_id = "01980f7d-7b8f-7e2a-8a11-2ab8e1234567"',
                f'data_root = "{data_root.resolve().as_posix()}"',
                "",
                "[creator]",
                "port = 45678",
                "",
                "[secret_locators]",
                f'"codex.auth_json" = "file:{auth_path.resolve().as_posix()}"',
                "",
            )
        ),
        encoding="utf-8",
        newline="\n",
    )
    return environment_root, data_root


def _runner_environment(temp: Path) -> dict[str, str]:
    temp.mkdir(parents=True, exist_ok=True)
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


def _invoke_runner(
    *, environment_root: Path, task: CodexTaskManifest, temp: Path
) -> tuple[bytes, bytes, int]:
    process = subprocess.Popen(
        (
            sys.executable,
            "-m",
            "armi_runtime.codex_runner_cli",
            "--environment-root",
            str(environment_root.resolve()),
        ),
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        cwd=Path.cwd(),
        env=_runner_environment(temp),
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    stdout = b""
    stderr = b""
    with WindowsJob() as job:
        try:
            job.assign(int(process._handle))  # type: ignore[attr-defined]
            stdout, stderr = process.communicate(
                input=encode_task(task), timeout=task.deadline_seconds + 60
            )
        except subprocess.TimeoutExpired:
            job.close()
            process.wait(timeout=15)
            raise RuntimeError("CODEX-LIVE-TIMEOUT") from None
    return stdout, stderr, process.returncode


def _live(root: Path) -> dict[str, object]:
    auth = _auth_source()
    execution = CodexExecutionId(uuid7())
    live_root = Path(tempfile.mkdtemp(prefix="armi-s038-sdk-live-"))
    started = time.perf_counter()
    dispatched = False
    evidence: dict[str, object] = {
        "schema_version": "armi.codex-runner-live-evidence.v2",
        "gate_id": _GATE_ID,
        "result": "blocked",
        "invocation_count": 0,
        "sdk_version": _SDK_VERSION,
        "runtime_version": _SDK_VERSION,
        "model_id": _MODEL,
        "error_code": "CODEX-LIVE-UNEXPECTED",
    }
    try:
        environment_root, data_root = _environment(live_root, bytes(auth))
        task, bundle = _task(live_root, execution)
        intake = data_root / "codex-runner" / "intake" / execution.value.hex
        intake.mkdir(parents=True)
        shutil.copyfile(bundle, intake / f"{task.source_bundle_digest.value[7:]}.zip")
        dispatched = True
        stdout, stderr, returncode = _invoke_runner(
            environment_root=environment_root,
            task=task,
            temp=live_root / "process-temp",
        )
        if returncode != 0 or stderr:
            safe_code = "CODEX-LIVE-RUNNER"
            try:
                failure = _strict_object(stderr)
                candidate = failure.get("code")
                if type(candidate) is str and candidate.startswith("CODEX-"):
                    safe_code = candidate
            except RuntimeError:
                pass
            evidence["runner_error_digest"] = Digest.from_bytes(stderr).to_wire()
            raise RuntimeError(safe_code)
        result = decode_result(stdout)
        if result.status is not CodexRunStatus.SUCCEEDED or result.usage is None:
            raise RuntimeError(result.error_code or "CODEX-LIVE-FAILED")
        final_tree_digest = result.final_tree_digest
        patch_digest = result.patch_digest
        if (
            type(final_tree_digest) is not Digest
            or type(patch_digest) is not Digest
            or result.sdk_version != _SDK_VERSION
        ):
            raise RuntimeError("CODEX-LIVE-RESULT")
        platform_home = data_root / "codex-runner" / "platform-home"
        _validate_platform_home(platform_home)
        evidence = {
            "schema_version": "armi.codex-runner-live-evidence.v2",
            "gate_id": _GATE_ID,
            "result": "pass",
            "invocation_count": 1,
            "runtime_version": _SDK_VERSION,
            "model_id": result.model_id,
            "sdk_version": result.sdk_version,
            "source_bundle_digest": task.source_bundle_digest.to_wire(),
            "source_tree_digest": result.source_tree_digest.to_wire(),
            "final_tree_digest": final_tree_digest.to_wire(),
            "patch_digest": patch_digest.to_wire(),
            "modified_file_count": result.modified_file_count,
            "validation_passed": result.validation_passed,
            "input_tokens": result.usage.input_tokens,
            "cached_input_tokens": result.usage.cached_input_tokens,
            "output_tokens": result.usage.output_tokens,
            "auth_mode": "chatgpt",
            "billing_basis": "chatgpt_subscription_auth",
            "incremental_cost_cny": None,
            "budget_limit_cny": 5,
            "sandbox": "windows_unelevated",
            "platform_home": "clean_reusable",
            "elapsed_ms": round((time.perf_counter() - started) * 1000),
        }
    except Exception as error:
        candidate = (
            error.args[0] if isinstance(error, RuntimeError) and error.args else None
        )
        error_code = getattr(error, "code", None)
        if type(error_code) is not str:
            error_code = (
                candidate
                if type(candidate) is str and candidate.startswith("CODEX-")
                else "CODEX-LIVE-UNEXPECTED"
            )
        evidence.update(
            invocation_count=1 if dispatched else 0,
            error_code=error_code,
            execution_error_code=error_code,
            cleanup_error_code=getattr(error, "cleanup_error_code", None),
            elapsed_ms=round((time.perf_counter() - started) * 1000),
        )
    finally:
        for index in range(len(auth)):
            auth[index] = 0
        try:
            _remove_tree(live_root)
        except OSError:
            evidence["result"] = "blocked"
            evidence["cleanup_error_code"] = "CODEX-LIVE-CLEANUP"
    return evidence


def _preflight(root: Path) -> dict[str, object]:
    started = time.perf_counter()
    preflight_root = Path(tempfile.mkdtemp(prefix="armi-s038-sdk-preflight-"))
    evidence: dict[str, object] = {
        "schema_version": "armi.codex-runner-preflight-evidence.v2",
        "gate_id": _PREFLIGHT_ID,
        "result": "blocked",
        "model_invocation_count": 0,
        "sdk_version": _SDK_VERSION,
        "runtime_version": _SDK_VERSION,
        "model_id": _MODEL,
        "error_code": "CODEX-PREFLIGHT-UNEXPECTED",
    }
    try:
        _binary, binary_digest = _runtime_binary()
        contract_root = preflight_root / "contract"
        contract_root.mkdir()
        default_task, _bundle = _task(
            contract_root,
            CodexExecutionId(uuid7()),
        )
        runner_config = _config(default_task)
        temp = preflight_root / "temp"
        platform_home = preflight_root / "data" / "codex-runner" / "platform-home"
        temp.mkdir()
        platform_home.mkdir(parents=True)
        _write_platform_state(platform_home, usable=True)
        required_config = frozenset(
            {
                'approval_policy="never"',
                'windows.sandbox="unelevated"',
                "sandbox_workspace_write.network_access=false",
                'shell_environment_policy.inherit="none"',
                'web_search="disabled"',
                "features.enable_mcp_apps=false",
                "features.plugins=false",
                "features.hooks=false",
                'history.persistence="none"',
            }
        )
        if not required_config <= frozenset(runner_config):
            raise RuntimeError("CODEX-PREFLIGHT-CONFIG")
        runner_environment = _runner_environment(temp)
        forbidden = frozenset(
            {
                "ARMI_ADMIN_CONFIG",
                "ARMI_SECRET_ARK_API_KEY",
                "DATABASE_URL",
                "OPENAI_API_KEY",
                "CODEX_HOME",
            }
        )
        if forbidden & frozenset(runner_environment):
            raise RuntimeError("CODEX-PREFLIGHT-ENVIRONMENT")
        windows = Path(runner_environment["WINDIR"])
        stderr = b""
        process = subprocess.Popen(
            (str(windows / "System32/cmd.exe"), "/d", "/q", "/c", "exit 0"),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=runner_environment,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        with WindowsJob() as job:
            job.assign(int(process._handle))  # type: ignore[attr-defined]
            _stdout, stderr = process.communicate(timeout=15)
        if process.returncode != 0:
            raise RuntimeError("CODEX-PREFLIGHT-JOB")
        _sanitize_platform_home(platform_home)
        _validate_platform_home(platform_home)
        evidence = {
            "schema_version": "armi.codex-runner-preflight-evidence.v2",
            "gate_id": _PREFLIGHT_ID,
            "result": "pass",
            "model_invocation_count": 0,
            "sdk_version": _SDK_VERSION,
            "runtime_version": _SDK_VERSION,
            "runtime_binary_digest": binary_digest,
            "configuration_digest": Digest.from_bytes(
                rfc8785.dumps(cast(Any, list(runner_config)))
            ).to_wire(),
            "sandbox": "windows_unelevated",
            "sandbox_runtime_verification": "live_sdk_turn_required",
            "job_object": "pass",
            "platform_home": "clean_reusable",
            "read_confidentiality": "deferred_to_s045_service_identity_and_acl",
            "workspace_write": "configured",
            "network": "configured_disabled",
            "user_extensions": "unavailable",
            "stderr_digest": Digest.from_bytes(stderr).to_wire(),
            "elapsed_ms": round((time.perf_counter() - started) * 1000),
        }
    except Exception as error:
        candidate = (
            error.args[0] if isinstance(error, RuntimeError) and error.args else None
        )
        error_code = getattr(error, "code", None)
        if type(error_code) is not str:
            error_code = (
                candidate
                if type(candidate) is str and candidate.startswith("CODEX-")
                else "CODEX-PREFLIGHT-UNEXPECTED"
            )
        evidence.update(
            error_code=error_code,
            elapsed_ms=round((time.perf_counter() - started) * 1000),
        )
    finally:
        try:
            _remove_tree(preflight_root)
        except OSError:
            evidence["result"] = "blocked"
            evidence["cleanup_error_code"] = "CODEX-PREFLIGHT-CLEANUP"
    return evidence


def _remove_tree(path: Path) -> None:
    if not path.exists():
        return
    windows = Path(os.environ.get("WINDIR", r"C:\Windows"))
    whoami = subprocess.run(
        [str(windows / "System32/whoami.exe")],
        check=False,
        capture_output=True,
        timeout=5,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    account = whoami.stdout.decode("utf-8", errors="strict").strip()
    if whoami.returncode != 0 or not account:
        raise OSError
    for arguments in (
        ("/reset", "/T", "/C"),
        ("/inheritance:e", "/grant:r", f"{account}:(OI)(CI)F", "/T", "/C"),
    ):
        completed = subprocess.run(
            [str(windows / "System32/icacls.exe"), str(path), *arguments],
            check=False,
            capture_output=True,
            timeout=30,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        if completed.returncode != 0:
            raise OSError
    shutil.rmtree(path, onexc=_make_writable_and_retry)
    if path.exists():
        raise OSError


def _safe_diagnostic(
    value: bytes, root: Path, temporary: Path, *additional: Path
) -> str:
    if value[:256].count(b"\x00") > 16:
        text = value.decode("utf-16-le", errors="replace")
    else:
        try:
            text = value.decode("utf-8", errors="strict")
        except UnicodeDecodeError:
            text = value.decode("mbcs", errors="replace")
    text = text[:2048]
    replacements = (
        *((str(path), "<temporary>") for path in (temporary, *additional)),
        (str(root), "<repository>"),
        (str(Path.home()), "<profile>"),
    )
    for source, target in replacements:
        text = text.replace(source, target).replace(source.replace("\\", "/"), target)
    return text.encode("ascii", errors="backslashreplace").decode("ascii")


def _make_writable_and_retry(
    function: Callable[..., object], path: str, error: BaseException
) -> None:
    del error
    os.chmod(path, stat.S_IWRITE)
    function(path)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--live", action="store_true")
    mode.add_argument("--preflight", action="store_true")
    args = parser.parse_args(argv)
    root = Path(__file__).resolve().parents[1]
    evidence = _live(root) if args.live else _preflight(root)
    print(json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if evidence["result"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
