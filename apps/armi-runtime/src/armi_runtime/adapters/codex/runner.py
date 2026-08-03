"""One-shot Codex runner backed by the official Python SDK."""

from __future__ import annotations

import asyncio
import io
import json
import os
import shutil
import stat
import subprocess
import zipfile
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final, cast

import rfc8785
from armi_kernel.application import (
    CodexRunnerPort,
    CodexRunnerViolation,
    CodexRunResult,
    CodexRunStatus,
    CodexTaskManifest,
    CredentialLocator,
    CredentialPort,
    CredentialPurpose,
)
from armi_kernel.contracts import Digest
from openai_codex import ApprovalMode, AsyncCodex, CodexConfig, Sandbox

from .sdk_codec import SdkTurnEvidence, normalize_sdk_turn, validate_final_output
from .validation import validate_fixed_result
from .workspace import (
    TreeSnapshot,
    changed_paths,
    extract_source_bundle,
    patch_digest,
    snapshot_tree,
)

_PURPOSE = CredentialPurpose("codex.runner.auth")
_MODEL: Final = "gpt-5.6-sol"
_SDK_VERSION: Final = "0.144.4"
_SDK_IDENTITY = Digest.from_bytes(
    b"openai-codex==0.144.4\nopenai-codex-cli-bin==0.144.4\n"
)
_PLATFORM_STATE = "runner-state.json"
_PERSISTENT_PLATFORM_CHILDREN = frozenset({".sandbox", _PLATFORM_STATE})


@dataclass(frozen=True, slots=True)
class CodexRunArtifactSet:
    event_transcript: bytes
    final_result: bytes
    patch: bytes
    result_bundle: bytes
    diagnostics: bytes
    validation_report: bytes


class IsolatedCodexRunner(CodexRunnerPort):
    __slots__ = ("_auth_locator", "_credential_port", "_run_root")

    def __init__(
        self,
        *,
        run_root: Path,
        credential_port: CredentialPort,
        auth_locator: CredentialLocator,
    ) -> None:
        if not run_root.is_absolute() or type(auth_locator) is not CredentialLocator:
            raise CodexRunnerViolation("CODEX-CONFIG")
        self._run_root = run_root
        self._credential_port = credential_port
        self._auth_locator = auth_locator

    async def run(self, task: CodexTaskManifest) -> CodexRunResult:
        result, _artifacts = await self.run_custodied(task)
        return result

    async def run_custodied(
        self, task: CodexTaskManifest
    ) -> tuple[CodexRunResult, CodexRunArtifactSet]:
        if type(task) is not CodexTaskManifest:
            raise CodexRunnerViolation("CODEX-TASK-MANIFEST")
        execution = task.execution_id.value.hex
        intake = self._run_root / "intake" / execution
        bundle = intake / f"{task.source_bundle_digest.value[7:]}.zip"
        private = self._run_root / "private" / execution
        workspace = private / "workspace"
        temp = private / "temp"
        platform_home = self._run_root / "platform-home"
        if private.exists() or not intake.is_dir():
            raise CodexRunnerViolation("CODEX-EXECUTION-STATE")
        self._prepare_roots(private, temp, platform_home)
        execution_error: CodexRunnerViolation | None = None
        result: CodexRunResult | None = None
        artifacts: CodexRunArtifactSet | None = None
        try:
            before = extract_source_bundle(bundle, workspace, task)
            self._write_auth(platform_home)
            evidence = await _invoke_sdk(
                workspace=workspace,
                platform_home=platform_home,
                temp=temp,
                task=task,
            )
            if len(evidence.final_response) > task.output_limit_bytes:
                raise CodexRunnerViolation("CODEX-OUTPUT-LIMIT")
            after = snapshot_tree(workspace, byte_limit=task.workspace_limit_bytes)
            paths = changed_paths(before, after, task)
            validate_final_output(evidence.final_response, paths)
            validate_fixed_result(
                task=task,
                workspace=workspace,
                changed_paths=paths,
            )
            artifacts = _custody_artifacts(
                workspace=workspace,
                evidence=evidence,
                before=before,
                after=after,
                paths=paths,
            )
            result = CodexRunResult(
                execution_id=task.execution_id,
                status=CodexRunStatus.SUCCEEDED,
                model_id=_MODEL,
                tool_digest=_SDK_IDENTITY,
                source_tree_digest=before.digest,
                final_tree_digest=after.digest,
                patch_digest=patch_digest(before, after, paths),
                output_digest=Digest.from_bytes(evidence.final_response),
                usage=evidence.usage,
                modified_file_count=len(paths),
                validation_passed=True,
            )
        except CodexRunnerViolation as error:
            execution_error = error
        except asyncio.CancelledError:
            execution_error = CodexRunnerViolation("CODEX-CANCELLED")
        except Exception:
            execution_error = CodexRunnerViolation("CODEX-UNEXPECTED")
        cleanup_error = self._cleanup(private, platform_home)
        if cleanup_error is not None:
            if execution_error is None:
                execution_error = cleanup_error
            else:
                execution_error.record_cleanup_failure(cleanup_error.code)
        if execution_error is not None:
            raise execution_error from None
        if result is None or artifacts is None:
            raise CodexRunnerViolation("CODEX-UNEXPECTED")
        return result, artifacts

    def _prepare_roots(
        self,
        private: Path,
        temp: Path,
        platform_home: Path,
    ) -> None:
        try:
            self._run_root.mkdir(parents=True, exist_ok=True)
            private.parent.mkdir(parents=True, exist_ok=True)
            private.mkdir()
            temp.mkdir()
            _owner_only(private)
            if not platform_home.exists():
                platform_home.mkdir()
                _owner_only(platform_home)
                _write_platform_state(platform_home, usable=True)
            _validate_platform_home(platform_home)
        except CodexRunnerViolation:
            raise
        except OSError:
            raise CodexRunnerViolation("CODEX-EXECUTION-STATE") from None

    def _write_auth(self, platform_home: Path) -> None:
        secret = bytearray()
        try:
            with self._credential_port.resolve(self._auth_locator, _PURPOSE) as handle:
                secret = handle.consume(lambda value: bytearray(value))
            if not secret or len(secret) > 1024 * 1024:
                raise CodexRunnerViolation("CODEX-AUTH")
            decoded = json.loads(bytes(secret).decode("utf-8", errors="strict"))
            if type(decoded) is not dict:
                raise CodexRunnerViolation("CODEX-AUTH")
            auth = platform_home / "auth.json"
            with auth.open("xb") as stream:
                stream.write(secret)
                stream.flush()
                os.fsync(stream.fileno())
        except CodexRunnerViolation:
            raise
        except Exception:
            raise CodexRunnerViolation("CODEX-AUTH") from None
        finally:
            for index in range(len(secret)):
                secret[index] = 0

    def _cleanup(
        self,
        private: Path,
        platform_home: Path,
    ) -> CodexRunnerViolation | None:
        cleanup_error: CodexRunnerViolation | None = None
        try:
            _sanitize_platform_home(platform_home)
        except CodexRunnerViolation as error:
            cleanup_error = error
            with suppress(OSError):
                _write_platform_state(platform_home, usable=False)
        try:
            _remove_private(private)
        except CodexRunnerViolation as error:
            cleanup_error = cleanup_error or error
        return cleanup_error


async def _invoke_sdk(
    *,
    workspace: Path,
    platform_home: Path,
    temp: Path,
    task: CodexTaskManifest,
) -> SdkTurnEvidence:
    environment = _sdk_environment(platform_home, temp)
    config = CodexConfig(
        cwd=str(workspace),
        env=environment,
        config_overrides=_CONFIG,
        client_name="armi_codex_runner",
        client_title="ARMI Codex Runner",
        client_version="2",
    )
    try:
        async with AsyncCodex(config) as codex:
            server = codex.metadata.serverInfo
            server_version = None if server is None else server.version
            if (
                type(server_version) is not str
                or server_version.split(" ", 1)[0] != _SDK_VERSION
            ):
                raise CodexRunnerViolation("CODEX-RUNTIME-VERSION")
            thread = await codex.thread_start(
                approval_mode=ApprovalMode.deny_all,
                base_instructions=_BASE_INSTRUCTIONS,
                cwd=str(workspace),
                ephemeral=True,
                model=_MODEL,
                sandbox=Sandbox.workspace_write,
            )
            turn = await thread.turn(
                _prompt(task),
                approval_mode=ApprovalMode.deny_all,
                cwd=str(workspace),
                model=_MODEL,
                output_schema=cast(Any, _OUTPUT_SCHEMA),
                sandbox=Sandbox.workspace_write,
            )
            try:
                sdk_result = await asyncio.wait_for(
                    turn.run(), timeout=task.deadline_seconds
                )
            except TimeoutError:
                await turn.interrupt()
                raise CodexRunnerViolation("CODEX-TIMEOUT") from None
        return normalize_sdk_turn(sdk_result)
    except CodexRunnerViolation:
        raise
    except asyncio.CancelledError:
        raise
    except Exception:
        raise CodexRunnerViolation("CODEX-SDK") from None


_CONFIG = (
    'approval_policy="never"',
    'windows.sandbox="unelevated"',
    "windows.sandbox_private_desktop=false",
    "sandbox_workspace_write.network_access=false",
    'shell_environment_policy.inherit="none"',
    'web_search="disabled"',
    "tools.web_search=false",
    "features.multi_agent=false",
    "features.multi_agent_v2=false",
    "features.enable_fanout=false",
    "features.apps=false",
    "features.enable_mcp_apps=false",
    "features.plugins=false",
    "features.remote_plugin=false",
    "features.plugin_sharing=false",
    "features.hooks=false",
    "features.browser_use=false",
    "features.browser_use_external=false",
    "features.browser_use_full_cdp_access=false",
    "features.computer_use=false",
    "features.image_generation=false",
    "features.in_app_browser=false",
    "features.auth_elicitation=false",
    "features.tool_call_mcp_elicitation=false",
    "features.workspace_dependencies=false",
    "apps._default.enabled=false",
    "features.skill_mcp_dependency_install=false",
    'history.persistence="none"',
    "allow_login_shell=false",
)

_OUTPUT_SCHEMA: dict[str, object] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["summary", "changed_paths"],
    "properties": {
        "summary": {"type": "string", "minLength": 1, "maxLength": 4096},
        "changed_paths": {
            "type": "array",
            "minItems": 1,
            "maxItems": 500,
            "items": {"type": "string"},
        },
    },
}

_BASE_INSTRUCTIONS = (
    "You are a one-shot isolated code modification worker. Follow only the supplied "
    "task contract and workspace facts. Never use web search, MCP, apps, skills, hooks, "
    "credentials, or paths outside the workspace."
)


def _custody_artifacts(
    *,
    workspace: Path,
    evidence: SdkTurnEvidence,
    before: TreeSnapshot,
    after: TreeSnapshot,
    paths: tuple[str, ...],
) -> CodexRunArtifactSet:
    old = {path: digest for path, digest, _ in before.files}
    new = {path: digest for path, digest, _ in after.files}
    patch = rfc8785.dumps(
        cast(
            Any,
            {
                "schema_version": "armi.codex-normalized-patch.v1",
                "changes": [
                    {
                        "path": path,
                        "before": old.get(path),
                        "after": new.get(path),
                    }
                    for path in paths
                ],
            },
        )
    )
    diagnostics = rfc8785.dumps(
        cast(
            Any,
            {
                "schema_version": "armi.codex-diagnostics.v1",
                "commands": [
                    {
                        "command_digest": Digest.from_bytes(
                            command.command.encode("utf-8")
                        ).value,
                        "output_digest": Digest.from_bytes(
                            command.output.encode("utf-8")
                        ).value,
                        "exit_code": command.exit_code,
                        "status": command.status,
                    }
                    for command in evidence.commands
                ],
            },
        )
    )
    validation = rfc8785.dumps(
        cast(
            Any,
            {
                "schema_version": "armi.codex-verification-report.v1",
                "status": "verified",
                "source_tree_digest": before.digest.value,
                "final_tree_digest": after.digest.value,
                "changed_paths": list(paths),
            },
        )
    )
    return CodexRunArtifactSet(
        evidence.transcript,
        evidence.final_response,
        patch,
        _result_bundle(workspace),
        diagnostics,
        validation,
    )


def _result_bundle(workspace: Path) -> bytes:
    output = io.BytesIO()
    try:
        with zipfile.ZipFile(
            output,
            mode="w",
            compression=zipfile.ZIP_DEFLATED,
            compresslevel=9,
        ) as archive:
            for path in sorted(item for item in workspace.rglob("*") if item.is_file()):
                relative = path.relative_to(workspace).as_posix()
                info = zipfile.ZipInfo(relative, date_time=(1980, 1, 1, 0, 0, 0))
                info.compress_type = zipfile.ZIP_DEFLATED
                info.external_attr = 0o100600 << 16
                archive.writestr(info, path.read_bytes())
    except OSError, zipfile.BadZipFile:
        raise CodexRunnerViolation("CODEX-RESULT-CUSTODY") from None
    value = output.getvalue()
    if not value or len(value) > 100 * 1024 * 1024:
        raise CodexRunnerViolation("CODEX-OUTPUT-LIMIT")
    return value


def _prompt(task: CodexTaskManifest) -> str:
    value = {
        "objective": task.objective,
        "facts": list(task.facts),
        "allowed_paths": list(task.allowed_paths),
        "forbidden_paths": list(task.forbidden_paths),
        "rules": [
            "Make the smallest necessary change.",
            "Only replace result.txt with ARMI_CODEX_CONFORMANCE_OK followed by LF.",
            "Do not use network, web search, MCP, apps, skills, hooks, or credentials.",
            "Do not read or write outside the workspace.",
            "Only modify allowed_paths and never modify forbidden_paths.",
            "Return strict JSON with summary and the exact sorted changed_paths.",
        ],
    }
    encoded = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    if len(encoded) > 64 * 1024:
        raise CodexRunnerViolation("CODEX-TASK-FORMAT")
    return encoded.decode("utf-8")


def _sdk_environment(platform_home: Path, temp: Path) -> dict[str, str]:
    windows = Path(os.environ.get("WINDIR", r"C:\Windows"))
    path = os.pathsep.join(
        (
            str(windows / "System32"),
            str(windows / "System32/WindowsPowerShell/v1.0"),
        )
    )
    return {
        "PATH": path,
        "SYSTEMROOT": str(windows),
        "WINDIR": str(windows),
        "TEMP": str(temp),
        "TMP": str(temp),
        "HOME": str(platform_home),
        "USERPROFILE": str(platform_home),
        "CODEX_HOME": str(platform_home),
    }


def _validate_platform_home(platform_home: Path) -> None:
    if platform_home.is_symlink() or not platform_home.is_dir():
        raise CodexRunnerViolation("CODEX-PLATFORM-HOME")
    state = platform_home / _PLATFORM_STATE
    try:
        value = json.loads(state.read_text(encoding="utf-8"))
    except OSError, ValueError:
        raise CodexRunnerViolation("CODEX-PLATFORM-HOME") from None
    if value != {
        "runtime_version": _SDK_VERSION,
        "sandbox": "unelevated",
        "schema_version": "armi.codex-runner-platform-state.v1",
        "sdk_version": _SDK_VERSION,
        "usable": True,
    }:
        raise CodexRunnerViolation("CODEX-PLATFORM-HOME")
    children = frozenset(path.name for path in platform_home.iterdir())
    if not children <= _PERSISTENT_PLATFORM_CHILDREN:
        raise CodexRunnerViolation("CODEX-PLATFORM-HOME")


def _write_platform_state(platform_home: Path, *, usable: bool) -> None:
    value = {
        "runtime_version": _SDK_VERSION,
        "sandbox": "unelevated",
        "schema_version": "armi.codex-runner-platform-state.v1",
        "sdk_version": _SDK_VERSION,
        "usable": usable,
    }
    (platform_home / _PLATFORM_STATE).write_text(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n",
        encoding="utf-8",
        newline="\n",
    )


def _sanitize_platform_home(platform_home: Path) -> None:
    try:
        for child in tuple(platform_home.iterdir()):
            if child.name in _PERSISTENT_PLATFORM_CHILDREN:
                continue
            _reset_owner_access(child)
            if child.is_dir() and not child.is_symlink():
                shutil.rmtree(child, onexc=_make_writable_and_retry)
            else:
                child.unlink()
        _write_platform_state(platform_home, usable=True)
        _validate_platform_home(platform_home)
    except CodexRunnerViolation, OSError:
        raise CodexRunnerViolation("CODEX-PLATFORM-CLEANUP") from None


def _owner_only(path: Path) -> None:
    windows = Path(os.environ.get("WINDIR", r"C:\Windows"))
    icacls = windows / "System32/icacls.exe"
    account = _current_account(windows)
    if not icacls.is_file():
        raise CodexRunnerViolation("CODEX-AUTH-ACL")
    result = subprocess.run(
        [
            str(icacls),
            str(path),
            "/inheritance:r",
            "/grant:r",
            f"{account}:(OI)(CI)F",
            "/grant:r",
            "SYSTEM:(OI)(CI)F",
        ],
        check=False,
        capture_output=True,
        timeout=10,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    if result.returncode != 0:
        raise CodexRunnerViolation("CODEX-AUTH-ACL")


def _remove_private(path: Path) -> None:
    try:
        if path.exists():
            _reset_owner_access(path)
            shutil.rmtree(path, onexc=_make_writable_and_retry)
        if path.exists():
            raise OSError
    except OSError:
        raise CodexRunnerViolation("CODEX-CLEANUP") from None


def _reset_owner_access(path: Path) -> None:
    windows = Path(os.environ.get("WINDIR", r"C:\Windows"))
    icacls = windows / "System32/icacls.exe"
    try:
        account = _current_account(windows)
    except CodexRunnerViolation:
        raise OSError from None
    if not icacls.is_file():
        raise OSError
    reset = subprocess.run(
        [str(icacls), str(path), "/reset", "/T", "/C"],
        check=False,
        capture_output=True,
        timeout=30,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    grant = subprocess.run(
        [
            str(icacls),
            str(path),
            "/inheritance:e",
            "/grant:r",
            f"{account}:(OI)(CI)F",
            "/T",
            "/C",
        ],
        check=False,
        capture_output=True,
        timeout=30,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    if reset.returncode != 0 or grant.returncode != 0:
        raise OSError


def _current_account(windows: Path) -> str:
    try:
        completed = subprocess.run(
            [str(windows / "System32/whoami.exe")],
            check=False,
            capture_output=True,
            timeout=5,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        value = completed.stdout.decode("utf-8", errors="strict").strip()
    except OSError, UnicodeDecodeError, subprocess.TimeoutExpired:
        raise CodexRunnerViolation("CODEX-AUTH-ACL") from None
    if completed.returncode != 0 or not value or "\n" in value or "\r" in value:
        raise CodexRunnerViolation("CODEX-AUTH-ACL")
    return value


def _make_writable_and_retry(
    function: Callable[..., object], path: str, error: BaseException
) -> None:
    del error
    os.chmod(path, stat.S_IWRITE)
    function(path)


__all__ = ("CodexRunArtifactSet", "IsolatedCodexRunner")
