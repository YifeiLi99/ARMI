from __future__ import annotations

import asyncio
import threading
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock
from uuid import uuid7

import pytest
from armi_codex import _application as application
from armi_codex._application import CodexEffectPipeline, _cleanup_abandoned_runs
from armi_codex._postgresql import PostgreSQLCodexDelegationRepository
from armi_codex.api import (
    CodexDelegationViolation,
    CodexExecutionId,
    CodexRunnerViolation,
)
from armi_kernel.contracts import Digest


@pytest.mark.asyncio
async def test_lost_lease_cancels_runner_and_preserves_unknown(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fence = object()
    started = threading.Event()
    stopped = threading.Event()
    task = SimpleNamespace(
        execution_id=CodexExecutionId(uuid7()),
        source_bundle_digest=Digest.from_bytes(b"bundle"),
    )
    snapshot = SimpleNamespace(
        creator_party_id=uuid7(),
        scene_id=uuid7(),
        dispatch_deadline=None,
        source_bundle=object(),
        task_manifest=object(),
    )

    @asynccontextmanager
    async def transaction(**_kwargs: object):
        yield SimpleNamespace(transaction=object(), runtime_fence=fence)

    @asynccontextmanager
    async def custody(*_args: object, **_kwargs: object):
        yield None

    def runner(**kwargs: Any):
        started.set()
        try:
            assert kwargs["cancellation"].wait(5)
            raise CodexRunnerViolation("CODEX-CANCELLED")
        finally:
            stopped.set()

    async def heartbeat(*_args: object) -> None:
        assert await asyncio.to_thread(started.wait, 5)
        raise CodexDelegationViolation("CODEX-DELEGATION-STALE")

    pipeline = cast(Any, object.__new__(CodexEffectPipeline))
    pipeline._stop = asyncio.Event()
    pipeline._cancellation = threading.Event()
    pipeline._factory = SimpleNamespace(
        unit_of_work=transaction, environment_id=uuid7()
    )
    pipeline._lease_owner = uuid7()
    pipeline._repository = SimpleNamespace(
        claim=AsyncMock(return_value=snapshot),
        mark_dispatching=AsyncMock(return_value=True),
        fail_dispatch=AsyncMock(),
    )
    pipeline._runtime_admission = lambda: fence
    pipeline._unavailable_reason = lambda: None
    pipeline._custody = SimpleNamespace(hold=custody)
    pipeline._data_rights = SimpleNamespace(blocks_effect=AsyncMock(return_value=False))
    pipeline._data_rights_fence = SimpleNamespace(
        capture=AsyncMock(), validate=AsyncMock()
    )
    pipeline._run_root = tmp_path
    pipeline._environment_root = tmp_path
    pipeline._runner_entry_module = "controlled_runner"
    pipeline._diagnostic = lambda _message: None
    monkeypatch.setattr(CodexEffectPipeline, "_read", AsyncMock(return_value=b"bundle"))
    monkeypatch.setattr(CodexEffectPipeline, "_heartbeat", heartbeat)
    monkeypatch.setattr(application, "_task_manifest", lambda *_args: task)
    monkeypatch.setattr(application, "run_custodied_subprocess", runner)

    assert await asyncio.wait_for(pipeline.dispatch_once(), timeout=10)
    assert stopped.is_set()
    assert pipeline._repository.fail_dispatch.await_args.kwargs["started"] is True
    assert not (tmp_path / "intake" / task.execution_id.value.hex).exists()
    pipeline.stop()
    assert await pipeline.dispatch_once() is False
    assert pipeline._repository.claim.await_count == 1


def test_startup_discards_temporary_runs_without_reading_results(
    tmp_path: Path,
) -> None:
    execution = uuid7()
    for segment in ("intake", "private", "process-temp"):
        directory = tmp_path / segment / execution.hex
        directory.mkdir(parents=True)
        (directory / "untrusted-result.json").write_bytes(b"not a result")
    _cleanup_abandoned_runs(tmp_path)
    assert all(
        not (tmp_path / segment / execution.hex).exists()
        for segment in ("intake", "private", "process-temp")
    )


def test_startup_cleans_platform_credentials_without_execution_directories(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    platform = tmp_path / "platform-home"
    platform.mkdir()
    credential = platform / "auth.json"
    credential.write_text("temporary fixture", encoding="utf-8")

    def sanitize(path: Path) -> None:
        assert path == platform
        credential.unlink()

    monkeypatch.setattr(application, "sanitize_platform_home", sanitize)
    _cleanup_abandoned_runs(tmp_path)
    assert not credential.exists()


@pytest.mark.asyncio
async def test_removed_task_artifact_settles_claim_before_execution() -> None:
    claim = SimpleNamespace(action_intent_id=uuid7())
    effect = SimpleNamespace(
        claim_codex=AsyncMock(return_value=claim), settle_codex=AsyncMock()
    )
    repository = cast(Any, object.__new__(PostgreSQLCodexDelegationRepository))
    repository._effect = effect
    repository._expression = SimpleNamespace(
        intent_snapshot=AsyncMock(
            return_value=SimpleNamespace(codex_task_source_id=uuid7())
        )
    )
    repository._sources = SimpleNamespace(
        task_source=AsyncMock(
            return_value=SimpleNamespace(
                source_bundle_artifact_id=uuid7(), task_manifest_artifact_id=uuid7()
            )
        )
    )
    repository._artifacts = SimpleNamespace(
        retained_ref_in=AsyncMock(return_value=None)
    )
    transaction = object()
    result = await repository.claim(
        SimpleNamespace(transaction=transaction), claim_owner=uuid7()
    )
    assert result is None
    effect.settle_codex.assert_awaited_once_with(
        transaction,
        claim=claim,
        status="failed",
        observation_digest=Digest.from_bytes(b"CODEX-TASK-ARTIFACT"),
        error_code="CODEX-TASK-ARTIFACT",
    )
