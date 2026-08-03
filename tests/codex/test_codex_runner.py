from __future__ import annotations

import json
import zipfile
from pathlib import Path
from uuid import uuid7

import pytest
from armi_kernel.application import (
    CodexExecutionId,
    CodexRunnerViolation,
    CodexRunStatus,
    CodexTaskManifest,
    CodexUsage,
    CredentialLocator,
    CredentialPort,
    CredentialPurpose,
    SecretHandle,
)
from armi_kernel.contracts import Digest
from armi_runtime.adapters.codex import runner as runner_module
from armi_runtime.adapters.codex.codec import decode_task
from armi_runtime.adapters.codex.runner import IsolatedCodexRunner
from armi_runtime.adapters.codex.sdk_codec import SdkTurnEvidence
from armi_runtime.adapters.codex.workspace import snapshot_tree


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


class _Credentials(CredentialPort):
    def resolve(
        self, locator: CredentialLocator, purpose: CredentialPurpose
    ) -> SecretHandle:
        assert locator.identity() == "file:auth.json"
        assert purpose.value == "codex.runner.auth"
        return _Handle(b'{"tokens":{"access_token":"conformance"}}')


def _task(bundle: Path, source: Path) -> CodexTaskManifest:
    return CodexTaskManifest(
        CodexExecutionId(uuid7()),
        uuid7(),
        uuid7(),
        Digest.from_bytes(bundle.read_bytes()),
        snapshot_tree(source, byte_limit=1024 * 1024).digest,
        "Create result.txt containing the fixed conformance marker.",
        ("This is an isolated conformance repository.",),
        ("result.txt",),
        ("input.txt",),
        "codex.conformance.minimal-edit.v1",
        60,
    )


def _bundle(tmp_path: Path) -> tuple[Path, Path]:
    source = tmp_path / "source"
    source.mkdir()
    (source / "input.txt").write_text("input\n", encoding="utf-8", newline="\n")
    bundle = tmp_path / "source.zip"
    with zipfile.ZipFile(bundle, "w", compression=zipfile.ZIP_STORED) as archive:
        archive.write(source / "input.txt", "input.txt")
    return source, bundle


def _prepare(tmp_path: Path) -> tuple[CodexTaskManifest, Path]:
    source, bundle = _bundle(tmp_path)
    task = _task(bundle, source)
    run_root = tmp_path / "runs"
    intake = run_root / "intake" / task.execution_id.value.hex
    intake.mkdir(parents=True)
    bundle.rename(intake / f"{task.source_bundle_digest.value[7:]}.zip")
    return task, run_root


def _evidence(output: bytes) -> SdkTurnEvidence:
    transcript = b'[{"type":"commandExecution"}]'
    return SdkTurnEvidence(
        output,
        transcript,
        Digest.from_bytes(transcript),
        CodexUsage(12, 0, 4),
        (),
    )


def test_task_codec_rejects_duplicate_keys_and_paths(tmp_path: Path) -> None:
    source, bundle = _bundle(tmp_path)
    task = _task(bundle, source)
    value = {
        field: getattr(task, field)
        for field in task.__dataclass_fields__  # type: ignore[attr-defined]
    }
    value.update(
        execution_id=str(task.execution_id.value),
        task_id=str(task.task_id),
        effect_id=str(task.effect_id),
        source_bundle_digest=str(task.source_bundle_digest),
        source_tree_digest=str(task.source_tree_digest),
        facts=list(task.facts),
        allowed_paths=list(task.allowed_paths),
        forbidden_paths=list(task.forbidden_paths),
    )
    assert decode_task(json.dumps(value).encode()) == task
    with pytest.raises(CodexRunnerViolation, match="CODEX-TASK-FORMAT"):
        decode_task(b'{"schema_version":"a","schema_version":"b"}')
    for invalid in ("../escape", ".codex/config.toml", "CON.txt", "wild*.txt"):
        with pytest.raises(CodexRunnerViolation, match="CODEX-TASK-PATH"):
            CodexTaskManifest(
                task.execution_id,
                task.task_id,
                task.effect_id,
                task.source_bundle_digest,
                task.source_tree_digest,
                task.objective,
                task.facts,
                (invalid,),
                (),
                task.validator_id,
                task.deadline_seconds,
            )


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
        output = json.dumps(
            {"summary": "created marker", "changed_paths": ["result.txt"]},
            separators=(",", ":"),
        ).encode()
        return _evidence(output)

    monkeypatch.setattr(runner_module, "_invoke_sdk", fake_invoke_sdk)
    runner = IsolatedCodexRunner(
        run_root=run_root,
        credential_port=_Credentials(),
        auth_locator=CredentialLocator.parse("file:auth.json"),
    )
    result = await runner.run(task)
    assert result.status is CodexRunStatus.SUCCEEDED
    assert result.modified_file_count == 1
    assert result.usage is not None and result.usage.input_tokens == 12
    assert not (run_root / "private" / task.execution_id.value.hex).exists()
    assert {path.name for path in (run_root / "platform-home").iterdir()} == {
        "runner-state.json"
    }


@pytest.mark.asyncio
async def test_scope_violation_fails_without_exposing_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    task, run_root = _prepare(tmp_path)

    async def fake_invoke_sdk(**values):  # type: ignore[no-untyped-def]
        (values["workspace"] / "input.txt").write_text("changed\n", encoding="utf-8")
        return _evidence(b'{"summary":"bad","changed_paths":["input.txt"]}')

    monkeypatch.setattr(runner_module, "_invoke_sdk", fake_invoke_sdk)
    runner = IsolatedCodexRunner(
        run_root=run_root,
        credential_port=_Credentials(),
        auth_locator=CredentialLocator.parse("file:auth.json"),
    )
    with pytest.raises(CodexRunnerViolation) as captured:
        await runner.run(task)
    assert captured.value.code == "CODEX-SCOPE"
    assert "input.txt" not in str(captured.value)


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
    monkeypatch.setattr(runner_module, "_remove_private", fake_cleanup)
    runner = IsolatedCodexRunner(
        run_root=run_root,
        credential_port=_Credentials(),
        auth_locator=CredentialLocator.parse("file:auth.json"),
    )
    with pytest.raises(CodexRunnerViolation) as captured:
        await runner.run(task)
    assert captured.value.code == "CODEX-TIMEOUT"
    assert captured.value.cleanup_error_code == "CODEX-CLEANUP"
