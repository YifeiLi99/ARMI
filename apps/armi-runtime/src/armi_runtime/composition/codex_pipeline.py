"""S039 Codex task admission, isolated dispatch, verification and evidence custody."""

from __future__ import annotations

import asyncio
import contextlib
import json
import shutil
from collections.abc import AsyncIterator, Callable, Mapping
from pathlib import Path
from typing import Any, cast
from uuid import uuid7

import rfc8785
from armi_kernel.application import (
    ArtifactId,
    ArtifactPolicy,
    ArtifactPrivacyScope,
    ArtifactRef,
    ArtifactViolation,
    CodexCleanupStatus,
    CodexDelegationViolation,
    CodexExecutionId,
    CodexRunnerViolation,
    CodexRunStatus,
    CodexTaskManifest,
    CodexTaskSourceAdmissionPort,
    CodexTaskSourceDraft,
    CodexTaskSourceId,
    CodexVerificationStatus,
    LockPlan,
)
from armi_kernel.contracts import Digest, TraceId

from armi_runtime.adapters.artifacts.content_store import ContentAddressedArtifactStore
from armi_runtime.adapters.codex.runner import CodexRunArtifactSet, IsolatedCodexRunner
from armi_runtime.adapters.persistence.artifact_catalog import ArtifactCatalogRepository
from armi_runtime.adapters.persistence.codex_delegation import (
    CodexDispatchSnapshot,
    PostgreSQLCodexDelegationRepository,
)
from armi_runtime.adapters.persistence.unit_of_work import PostgreSQLUnitOfWorkFactory
from armi_runtime.adapters.transaction_errors import DatabaseTransactionError

Diagnostic = Callable[[str], None]


def _ignore_diagnostic(_event: str) -> None:
    return None


class CodexTaskSourceGateway(CodexTaskSourceAdmissionPort):
    __slots__ = ("_factory", "_repository")

    def __init__(self, factory: PostgreSQLUnitOfWorkFactory) -> None:
        self._factory = factory
        self._repository = PostgreSQLCodexDelegationRepository()

    async def admit(self, draft: CodexTaskSourceDraft) -> CodexTaskSourceId:
        if type(draft) is not CodexTaskSourceDraft:
            raise CodexDelegationViolation("CODEX-TASK-ADMISSION")
        try:
            async with self._factory.unit_of_work(LockPlan()) as uow:
                return await self._repository.admit_task_source(uow, draft)
        except CodexDelegationViolation:
            raise
        except DatabaseTransactionError:
            raise CodexDelegationViolation("CODEX-TASK-DATABASE") from None


class CodexEffectPipeline:
    __slots__ = (
        "_catalog",
        "_diagnostic",
        "_factory",
        "_lease_owner",
        "_repository",
        "_run_root",
        "_runner",
        "_stop",
        "_storage",
        "task_sources",
    )

    def __init__(
        self,
        *,
        factory: PostgreSQLUnitOfWorkFactory,
        storage: ContentAddressedArtifactStore,
        run_root: Path,
        runner: IsolatedCodexRunner,
        diagnostic: Diagnostic | None = None,
    ) -> None:
        self._factory = factory
        self._storage = storage
        self._run_root = run_root
        self._runner = runner
        self._repository = PostgreSQLCodexDelegationRepository()
        self._catalog = ArtifactCatalogRepository()
        self._lease_owner = uuid7()
        self._stop = asyncio.Event()
        self._diagnostic = diagnostic or _ignore_diagnostic
        self.task_sources = CodexTaskSourceGateway(factory)

    async def open(self) -> None:
        try:
            await self._factory.open()
            await self._storage.prepare()
        except DatabaseTransactionError:
            raise CodexDelegationViolation("CODEX-TASK-DATABASE") from None
        except ArtifactViolation:
            raise CodexDelegationViolation("CODEX-TASK-ARTIFACT") from None

    async def close(self) -> None:
        self._stop.set()
        await self._factory.close()

    def stop(self) -> None:
        self._stop.set()

    async def dispatch_once(self) -> bool:
        snapshot: CodexDispatchSnapshot | None = None
        intake_cleanup_failed = False
        try:
            async with self._factory.unit_of_work(LockPlan()) as uow:
                snapshot = await self._repository.claim(
                    uow, claim_owner=self._lease_owner
                )
            if snapshot is None:
                return False
            bundle = await self._read(snapshot.source_bundle)
            manifest_bytes = await self._read(snapshot.task_manifest)
            task = _task_manifest(snapshot, manifest_bytes)
            _install_intake(self._run_root, task, bundle)
            async with self._factory.unit_of_work(LockPlan()) as uow:
                await self._repository.mark_dispatching(uow, snapshot)
            heartbeat = asyncio.create_task(self._heartbeat(snapshot))
            runner_task = asyncio.create_task(self._runner.run_custodied(task))
            try:
                done, _pending = await asyncio.wait(
                    {heartbeat, runner_task}, return_when=asyncio.FIRST_COMPLETED
                )
                if heartbeat in done:
                    await heartbeat
                    raise CodexDelegationViolation("CODEX-DELEGATION-STALE")
                result, artifact_set = await runner_task
            finally:
                heartbeat.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await heartbeat
                if not runner_task.done():
                    runner_task.cancel()
                    with contextlib.suppress(asyncio.CancelledError):
                        await runner_task
                try:
                    _cleanup_intake(self._run_root, task.execution_id)
                except CodexDelegationViolation:
                    intake_cleanup_failed = True
            if intake_cleanup_failed:
                cleanup_error = CodexRunnerViolation("CODEX-CLEANUP")
                cleanup_error.record_cleanup_failure("CODEX-CLEANUP")
                raise cleanup_error
            published = await self._publish_success(
                snapshot.trace_id, result.status, artifact_set
            )
            await self._settle(
                snapshot,
                status=CodexVerificationStatus.VERIFIED,
                cleanup_status=CodexCleanupStatus.CLEAN,
                published=published,
                final_tree_digest=result.final_tree_digest,
                patch_digest=result.patch_digest,
                changed_path_count=result.modified_file_count,
                execution_error_code=None,
                cleanup_error_code=None,
            )
            return True
        except CodexRunnerViolation as error:
            if intake_cleanup_failed and error.cleanup_error_code is None:
                error.record_cleanup_failure("CODEX-CLEANUP")
            if snapshot is None:
                self._diagnostic("codex.dispatch.preflight_failed")
                return True
            status = (
                CodexVerificationStatus.UNKNOWN
                if error.outcome_unknown
                else CodexVerificationStatus.CANCELLED
                if error.code == "CODEX-CANCELLED"
                else CodexVerificationStatus.FAILED
            )
            published = await self._publish_failure(snapshot.trace_id, status, error)
            await self._settle(
                snapshot,
                status=status,
                cleanup_status=(
                    CodexCleanupStatus.FAILED
                    if error.cleanup_error_code is not None
                    else CodexCleanupStatus.CLEAN
                ),
                published=published,
                final_tree_digest=None,
                patch_digest=None,
                changed_path_count=0,
                execution_error_code=error.code,
                cleanup_error_code=error.cleanup_error_code,
            )
            return True
        except ArtifactViolation, CodexDelegationViolation, DatabaseTransactionError:
            self._diagnostic("codex.dispatch.custody_failed")
            return True

    async def run_worker(self) -> None:
        while not self._stop.is_set():
            if await self.dispatch_once():
                await asyncio.sleep(0)
                continue
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(self._stop.wait(), timeout=1)

    async def _heartbeat(self, snapshot: CodexDispatchSnapshot) -> None:
        while True:
            await asyncio.sleep(20)
            async with self._factory.unit_of_work(LockPlan()) as uow:
                if not await self._repository.heartbeat(uow, snapshot):
                    raise CodexDelegationViolation("CODEX-DELEGATION-STALE")

    async def _read(self, reference: ArtifactRef) -> bytes:
        value = b""
        async with await self._storage.open_verified(reference) as stream:
            value = await stream.read()
        if len(value) != reference.byte_size:
            raise ArtifactViolation("ART-CORRUPT")
        return value

    async def _publish_success(
        self,
        trace_id: TraceId,
        run_status: CodexRunStatus,
        values: CodexRunArtifactSet,
    ) -> dict[str, Any]:
        if run_status is not CodexRunStatus.SUCCEEDED:
            raise CodexDelegationViolation("CODEX-VERIFICATION-RESULT")
        evidence = rfc8785.dumps(
            cast(
                Any,
                {
                    "schema_version": "armi.codex-result-evidence.v1",
                    "result_kind": "verified_completion",
                    "validation_digest": Digest.from_bytes(
                        values.validation_report
                    ).value,
                },
            )
        )
        return await self._publish_values(
            trace_id,
            {
                "event_transcript": (
                    "application/json",
                    "codex.event-transcript",
                    values.event_transcript,
                ),
                "final_result": (
                    "application/json",
                    "codex.final-result",
                    values.final_result,
                ),
                "patch": ("application/json", "codex.normalized-patch", values.patch),
                "result_bundle": (
                    "application/zip",
                    "codex.result-tree",
                    values.result_bundle,
                ),
                "diagnostics": (
                    "application/json",
                    "codex.diagnostics",
                    values.diagnostics,
                ),
                "validation_report": (
                    "application/json",
                    "codex.validation-report",
                    values.validation_report,
                ),
                "result_evidence": (
                    "application/json",
                    "codex.result-evidence",
                    evidence,
                ),
            },
        )

    async def _publish_failure(
        self,
        trace_id: TraceId,
        status: CodexVerificationStatus,
        error: CodexRunnerViolation,
    ) -> dict[str, Any]:
        report = rfc8785.dumps(
            cast(
                Any,
                {
                    "schema_version": "armi.codex-verification-report.v1",
                    "status": status.value,
                    "error_code": error.code,
                    "cleanup_error_code": error.cleanup_error_code,
                },
            )
        )
        evidence = rfc8785.dumps(
            cast(
                Any,
                {
                    "schema_version": "armi.codex-result-evidence.v1",
                    "result_kind": {
                        CodexVerificationStatus.FAILED: "execution_failure",
                        CodexVerificationStatus.UNKNOWN: "outcome_unknown",
                        CodexVerificationStatus.CANCELLED: "cancelled",
                    }[status],
                    "validation_digest": Digest.from_bytes(report).value,
                },
            )
        )
        diagnostics = rfc8785.dumps(
            cast(
                Any,
                {
                    "schema_version": "armi.codex-diagnostics.v1",
                    "error_code": error.code,
                    "cleanup_error_code": error.cleanup_error_code,
                },
            )
        )
        return await self._publish_values(
            trace_id,
            {
                "diagnostics": ("application/json", "codex.diagnostics", diagnostics),
                "validation_report": (
                    "application/json",
                    "codex.validation-report",
                    report,
                ),
                "result_evidence": (
                    "application/json",
                    "codex.result-evidence",
                    evidence,
                ),
            },
        )

    async def _publish_values(
        self,
        trace_id: TraceId,
        values: Mapping[str, tuple[str, str, bytes]],
    ) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for name, (media_type, logical_kind, value) in values.items():
            staged = await self._storage.stage(
                _one_chunk(value),
                ArtifactPolicy(
                    media_type,
                    logical_kind,
                    "codex.dispatch",
                    trace_id,
                    ArtifactPrivacyScope.PRIVATE,
                ),
            )
            result[name] = await self._storage.publish(staged)
        return result

    async def _settle(
        self,
        snapshot: CodexDispatchSnapshot,
        *,
        status: CodexVerificationStatus,
        cleanup_status: CodexCleanupStatus,
        published: Mapping[str, Any],
        final_tree_digest: Digest | None,
        patch_digest: Digest | None,
        changed_path_count: int,
        execution_error_code: str | None,
        cleanup_error_code: str | None,
    ) -> None:
        async with self._factory.unit_of_work(LockPlan()) as uow:
            refs: dict[str, ArtifactRef] = {}
            for name, artifact in published.items():
                registration = await self._catalog.register(
                    uow, ArtifactId(uuid7()), artifact
                )
                refs[name] = registration.ref
            await self._repository.settle(
                uow,
                snapshot=snapshot,
                status=status,
                cleanup_status=cleanup_status,
                artifacts=refs,
                source_tree_digest=snapshot.source_tree_digest,
                final_tree_digest=final_tree_digest,
                patch_digest=patch_digest,
                changed_path_count=changed_path_count,
                execution_error_code=execution_error_code,
                cleanup_error_code=cleanup_error_code,
            )


def _task_manifest(snapshot: CodexDispatchSnapshot, value: bytes) -> CodexTaskManifest:
    try:
        raw = json.loads(value, object_pairs_hook=_strict_object)
        if type(raw) is not dict:
            raise ValueError
        document = cast(dict[str, Any], raw)
        if (
            set(document)
            != {
                "schema_version",
                "objective",
                "facts",
                "allowed_paths",
                "forbidden_paths",
                "validator_id",
                "deadline_seconds",
                "source_tree_digest",
            }
            or document["schema_version"] != "armi.codex-task-source.v1"
        ):
            raise ValueError
        if (
            document["validator_id"] != snapshot.validator_id
            or document["deadline_seconds"] != snapshot.deadline_seconds
            or document["source_tree_digest"] != snapshot.source_tree_digest.value
        ):
            raise ValueError
        facts = tuple(document["facts"])
        allowed = tuple(document["allowed_paths"])
        forbidden = tuple(document["forbidden_paths"])
        return CodexTaskManifest(
            CodexExecutionId(uuid7()),
            snapshot.task_source_id,
            snapshot.effect_id,
            snapshot.source_bundle.content_digest,
            snapshot.source_tree_digest,
            document["objective"],
            facts,
            allowed,
            forbidden,
            snapshot.validator_id,
            snapshot.deadline_seconds,
        )
    except TypeError, ValueError, UnicodeDecodeError, json.JSONDecodeError:
        raise CodexDelegationViolation("CODEX-TASK-MANIFEST") from None


def _strict_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError
        result[key] = value
    return result


def _install_intake(run_root: Path, task: CodexTaskManifest, bundle: bytes) -> None:
    intake = run_root / "intake" / task.execution_id.value.hex
    try:
        intake.mkdir(parents=True, exist_ok=False)
        target = intake / f"{task.source_bundle_digest.value[7:]}.zip"
        with target.open("xb") as stream:
            stream.write(bundle)
    except OSError:
        raise CodexDelegationViolation("CODEX-TASK-INTAKE") from None


def _cleanup_intake(run_root: Path, execution_id: CodexExecutionId) -> None:
    intake_root = (run_root / "intake").resolve()
    target = (intake_root / execution_id.value.hex).resolve()
    if target.parent != intake_root:
        raise CodexDelegationViolation("CODEX-TASK-CLEANUP")
    try:
        if target.exists():
            shutil.rmtree(target)
    except OSError:
        raise CodexDelegationViolation("CODEX-TASK-CLEANUP") from None


async def _one_chunk(value: bytes) -> AsyncIterator[bytes]:
    yield value


__all__ = ("CodexEffectPipeline", "CodexTaskSourceGateway")
