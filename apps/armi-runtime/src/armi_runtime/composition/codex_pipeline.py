"""S039 Codex task admission, isolated dispatch, verification and evidence custody."""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import io
import json
import shutil
import threading
import zipfile
from collections.abc import AsyncIterator, Callable, Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast
from uuid import UUID, uuid7

import rfc8785
from armi_artifact_store.content_store import ContentAddressedArtifactStore
from armi_evidence.api import EvidenceWritePort
from armi_interaction.api import (
    CreatorInputAcceptance,
    CreatorInputContext,
    CreatorInputTransactionPort,
)
from armi_kernel.application import (
    ArtifactId,
    ArtifactPolicy,
    ArtifactPrivacyScope,
    ArtifactRef,
    ArtifactViolation,
    AuditDraft,
    AuditEventId,
    AuditReference,
    AuditResultStatus,
    AuditSensitivity,
    CodexCleanupStatus,
    CodexDelegationViolation,
    CodexExecutionId,
    CodexModel,
    CodexReasoningEffort,
    CodexRunnerViolation,
    CodexRunStatus,
    CodexTaskManifest,
    CodexTaskSourceAdmissionPort,
    CodexTaskSourceDraft,
    CodexTaskSourceId,
    CodexVerificationStatus,
    CreatorCodexTaskAdmissionPort,
    CreatorCodexTaskCommand,
    CreatorEventResourceKind,
    CreatorProjectionInvalidation,
    CreatorProjectionNotifier,
)
from armi_kernel.contracts import Digest, Instant, Purpose, SubjectId, TraceId

from armi_runtime.adapters.codex.runner import CodexRunArtifactSet
from armi_runtime.adapters.codex.subprocess_client import run_custodied_subprocess
from armi_runtime.adapters.persistence.artifact_catalog import ArtifactCatalogRepository
from armi_runtime.adapters.persistence.codex_delegation import (
    CodexDispatchSnapshot,
    PostgreSQLCodexDelegationRepository,
)
from armi_runtime.adapters.persistence.unit_of_work import (
    PostgreSQLUnitOfWork,
    PostgreSQLUnitOfWorkFactory,
)
from armi_runtime.adapters.transaction_errors import DatabaseTransactionError

Diagnostic = Callable[[str], None]


def _ignore_diagnostic(_event: str) -> None:
    return None


class CodexTaskSourceGateway(
    CodexTaskSourceAdmissionPort,
    CreatorCodexTaskAdmissionPort[CreatorInputAcceptance],
):
    __slots__ = (
        "_catalog",
        "_creator_party_id",
        "_diagnostic",
        "_factory",
        "_input_repository",
        "_notifier",
        "_repository",
        "_storage",
    )

    def __init__(
        self,
        factory: PostgreSQLUnitOfWorkFactory,
        *,
        storage: ContentAddressedArtifactStore,
        creator_party_id: UUID,
        input_repository: CreatorInputTransactionPort,
        evidence: EvidenceWritePort,
        notifier: CreatorProjectionNotifier | None,
        diagnostic: Diagnostic,
    ) -> None:
        self._factory = factory
        self._storage = storage
        self._creator_party_id = creator_party_id
        self._notifier = notifier
        self._diagnostic = diagnostic
        self._repository = PostgreSQLCodexDelegationRepository(evidence)
        self._input_repository = input_repository
        self._catalog = ArtifactCatalogRepository()

    async def admit(self, draft: CodexTaskSourceDraft) -> CodexTaskSourceId:
        try:
            async with self._factory.unit_of_work() as uow:
                return await self._repository.admit_task_source(uow, draft)
        except CodexDelegationViolation:
            raise
        except DatabaseTransactionError:
            raise CodexDelegationViolation("CODEX-TASK-DATABASE") from None

    async def accept(self, command: CreatorCodexTaskCommand) -> CreatorInputAcceptance:
        context = await self._context(command.scene_key)
        objective_digest = Digest.from_bytes(command.objective.encode("utf-8"))
        request_digest = Digest.from_bytes(
            rfc8785.dumps(
                cast(
                    Any,
                    {
                        "schema_version": "armi.creator-codex-task.v2",
                        "environment_id": str(self._factory.environment_id),
                        "subject_id": str(context.subject_id),
                        "scene_id": str(context.scene_id),
                        "creator_party_id": str(context.creator_party_id),
                        "objective_digest": objective_digest.value,
                        "model_id": command.model_id.value,
                        "reasoning_effort": command.reasoning_effort.value,
                        "web_search": command.web_search,
                    },
                )
            )
        )
        existing = await self._existing(command, context, request_digest)
        if existing is not None:
            return existing
        task_source_id = CodexTaskSourceId(uuid7())
        bundle, source_tree_digest = _creator_task_bundle(task_source_id)
        manifest = _creator_task_manifest(
            task_source_id,
            command.objective,
            source_tree_digest,
            command.model_id,
            command.reasoning_effort,
            command.web_search,
        )
        try:
            published_bundle = await self._storage.publish(
                await self._storage.stage(
                    _one_chunk(bundle),
                    ArtifactPolicy(
                        "application/zip",
                        "codex.task-source-bundle",
                        "creator.codex-task",
                        command.trace_id,
                        ArtifactPrivacyScope.PRIVATE,
                    ),
                )
            )
            published_manifest = await self._storage.publish(
                await self._storage.stage(
                    _one_chunk(manifest),
                    ArtifactPolicy(
                        "application/json",
                        "codex.task-source-manifest",
                        "creator.codex-task",
                        command.trace_id,
                        ArtifactPrivacyScope.PRIVATE,
                    ),
                )
            )
        except ArtifactViolation, OSError:
            raise CodexDelegationViolation("CODEX-TASK-ARTIFACT") from None
        try:
            async with self._factory.unit_of_work() as uow:
                await self._input_repository.lock_scene(
                    uow,
                    scene_id=context.scene_id,
                )
                current = await self._input_repository.context(
                    uow,
                    scene_key=command.scene_key,
                    creator_party_id=self._creator_party_id,
                )
                if current != context:
                    raise CodexDelegationViolation("CODEX-TASK-SUBJECT")
                existing = await self._repository.existing_creator_task(
                    uow,
                    context=context,
                    idempotency_key=command.idempotency_key.value,
                    request_digest=request_digest,
                )
                if existing is not None:
                    return existing
                bundle_registration = await self._catalog.register(
                    uow, ArtifactId(uuid7()), published_bundle
                )
                manifest_registration = await self._catalog.register(
                    uow, ArtifactId(uuid7()), published_manifest
                )
                for registration in (bundle_registration, manifest_registration):
                    if registration.inserted:
                        await uow.audit.append(
                            _artifact_audit(uow, registration.ref, command.trace_id)
                        )
                acceptance = await self._repository.admit_creator_task_source(
                    uow,
                    context=context,
                    idempotency_key=command.idempotency_key.value,
                    request_digest=request_digest,
                    draft=CodexTaskSourceDraft(
                        task_source_id,
                        SubjectId(context.subject_id),
                        bundle_registration.ref.artifact_id,
                        bundle_registration.ref.content_digest,
                        source_tree_digest,
                        manifest_registration.ref.artifact_id,
                        manifest_registration.ref.content_digest,
                        "codex.output-artifact.v1",
                        (),
                        (".armi-task-id",),
                        900,
                        command.trace_id,
                    ),
                )
        except DatabaseTransactionError as error:
            if error.code in {"DB-TX-UNIQUE", "DB-TX-COMMIT-UNKNOWN"}:
                recovered = await self._existing(command, context, request_digest)
                if recovered is not None:
                    return recovered
            self._diagnostic(f"codex.task.database_failed.{error.code}")
            raise CodexDelegationViolation("CODEX-TASK-DATABASE") from None
        if acceptance.newly_accepted:
            await self._notify(command.scene_key, acceptance)
        return acceptance

    async def _context(self, scene_key: str) -> CreatorInputContext:
        try:
            async with self._factory.unit_of_work(read_only=True) as uow:
                return await self._input_repository.context(
                    uow,
                    scene_key=scene_key,
                    creator_party_id=self._creator_party_id,
                )
        except DatabaseTransactionError:
            raise CodexDelegationViolation("CODEX-TASK-DATABASE") from None

    async def _existing(
        self,
        command: CreatorCodexTaskCommand,
        context: CreatorInputContext,
        request_digest: Digest,
    ) -> CreatorInputAcceptance | None:
        try:
            async with self._factory.unit_of_work(read_only=True) as uow:
                return await self._repository.existing_creator_task(
                    uow,
                    context=context,
                    idempotency_key=command.idempotency_key.value,
                    request_digest=request_digest,
                )
        except DatabaseTransactionError:
            raise CodexDelegationViolation("CODEX-TASK-DATABASE") from None

    async def _notify(self, scene_key: str, acceptance: CreatorInputAcceptance) -> None:
        if self._notifier is None:
            self._diagnostic("codex.task.notification_unavailable")
            return
        now = Instant(datetime.now(UTC))
        try:
            await self._notifier.notify(
                CreatorProjectionInvalidation(
                    CreatorEventResourceKind.SCENE_TIMELINE,
                    scene_key,
                    now,
                    "scene-timeline.v5",
                )
            )
            await self._notifier.notify(
                CreatorProjectionInvalidation(
                    CreatorEventResourceKind.OPERATION,
                    str(acceptance.opportunity_id),
                    now,
                    "creator-operation.v1",
                )
            )
        except Exception:
            self._diagnostic("codex.task.notification_failed")


class CodexEffectPipeline:
    __slots__ = (
        "_catalog",
        "_diagnostic",
        "_environment_root",
        "_factory",
        "_lease_owner",
        "_repository",
        "_run_root",
        "_stop",
        "_storage",
        "task_sources",
    )

    def __init__(
        self,
        *,
        factory: PostgreSQLUnitOfWorkFactory,
        storage: ContentAddressedArtifactStore,
        environment_root: Path,
        run_root: Path,
        creator_party_id: UUID,
        creator_input: CreatorInputTransactionPort,
        evidence: EvidenceWritePort,
        notifier: CreatorProjectionNotifier | None,
        diagnostic: Diagnostic | None = None,
    ) -> None:
        self._factory = factory
        self._storage = storage
        self._environment_root = environment_root
        self._run_root = run_root
        self._repository = PostgreSQLCodexDelegationRepository(evidence)
        self._catalog = ArtifactCatalogRepository()
        self._lease_owner = uuid7()
        self._stop = asyncio.Event()
        self._diagnostic = diagnostic or _ignore_diagnostic
        self.task_sources = CodexTaskSourceGateway(
            factory,
            storage=storage,
            creator_party_id=creator_party_id,
            input_repository=creator_input,
            evidence=evidence,
            notifier=notifier,
            diagnostic=self._diagnostic,
        )

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
            async with self._factory.unit_of_work() as uow:
                snapshot = await self._repository.claim(
                    uow, claim_owner=self._lease_owner
                )
            if snapshot is None:
                return False
            bundle = await self._read(snapshot.source_bundle)
            manifest_bytes = await self._read(snapshot.task_manifest)
            task = _task_manifest(snapshot, manifest_bytes)
            async with self._factory.unit_of_work() as uow:
                dispatching = await self._repository.mark_dispatching(uow, snapshot)
            if not dispatching:
                return True
            _install_intake(self._run_root, task, bundle)
            heartbeat = asyncio.create_task(self._heartbeat(snapshot))
            cancellation = threading.Event()
            runner_task = asyncio.create_task(
                asyncio.to_thread(
                    run_custodied_subprocess,
                    environment_root=self._environment_root,
                    process_temp=self._run_root
                    / "process-temp"
                    / task.execution_id.value.hex,
                    task=task,
                    cancellation=cancellation,
                )
            )
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
                    cancellation.set()
                    try:
                        await asyncio.wait_for(
                            asyncio.shield(runner_task),
                            timeout=10,
                        )
                    except TimeoutError:
                        runner_task.cancel()
                        self._diagnostic("codex.dispatch.cancel_timeout")
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
            async with self._factory.unit_of_work() as uow:
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
                    "error_code": error.code,
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
        async with self._factory.unit_of_work() as uow:
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


def _creator_task_bundle(task_source_id: CodexTaskSourceId) -> tuple[bytes, Digest]:
    files = {
        ".armi-task-id": f"{task_source_id.value}\n".encode(),
        "result.md": b"PENDING\n",
    }
    records = [
        {
            "path": path,
            "sha256": hashlib.sha256(value).hexdigest(),
            "bytes": len(value),
        }
        for path, value in sorted(files.items())
    ]
    output = io.BytesIO()
    with zipfile.ZipFile(
        output,
        mode="w",
        compression=zipfile.ZIP_DEFLATED,
        compresslevel=9,
    ) as archive:
        for path, value in sorted(files.items()):
            info = zipfile.ZipInfo(path, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100600 << 16
            archive.writestr(info, value)
    return output.getvalue(), Digest.from_bytes(rfc8785.dumps(cast(Any, records)))


def _creator_task_manifest(
    task_source_id: CodexTaskSourceId,
    objective: str,
    source_tree_digest: Digest,
    model_id: CodexModel,
    reasoning_effort: CodexReasoningEffort,
    web_search: bool,
) -> bytes:
    facts = [
        "result.md is the only Creator-visible task deliverable.",
        f"The stable task source identity is {task_source_id.value}.",
    ]
    if web_search:
        facts.append(
            "Codex built-in Web Search is enabled for public read-only research; "
            "credentials, login, downloads and external write actions remain forbidden."
        )
    else:
        facts.append("Codex built-in Web Search is disabled for this task.")
    return rfc8785.dumps(
        cast(
            Any,
            {
                "schema_version": "armi.codex-task-source.v2",
                "objective": objective,
                "facts": facts,
                "allowed_paths": [],
                "forbidden_paths": [".armi-task-id"],
                "validator_id": "codex.output-artifact.v1",
                "deadline_seconds": 900,
                "source_tree_digest": source_tree_digest.value,
                "model_id": model_id.value,
                "reasoning_effort": reasoning_effort.value,
                "web_search": web_search,
            },
        )
    )


def _artifact_audit(
    uow: PostgreSQLUnitOfWork,
    reference: ArtifactRef,
    trace_id: TraceId,
) -> AuditDraft:
    return AuditDraft(
        AuditEventId(uuid7()),
        AuditReference("runtime", uow.environment_id),
        Purpose("delegate_codex_work"),
        "artifact.catalog.registered",
        AuditReference("artifact", reference.artifact_id.value),
        AuditResultStatus.APPLIED,
        trace_id,
        AuditSensitivity.PRIVATE,
    )


def _task_manifest(snapshot: CodexDispatchSnapshot, value: bytes) -> CodexTaskManifest:
    try:
        raw = json.loads(value, object_pairs_hook=_strict_object)
        if type(raw) is not dict:
            raise ValueError
        document = cast(dict[str, Any], raw)
        version = document.get("schema_version")
        expected_keys = {
            "schema_version",
            "objective",
            "facts",
            "allowed_paths",
            "forbidden_paths",
            "validator_id",
            "deadline_seconds",
            "source_tree_digest",
        }
        if version == "armi.codex-task-source.v2":
            expected_keys.update({"model_id", "reasoning_effort", "web_search"})
            if type(document.get("web_search")) is not bool:
                raise ValueError
        elif version != "armi.codex-task-source.v1":
            raise ValueError
        if set(document) != expected_keys:
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
            model_id=(
                CodexModel(document["model_id"])
                if version == "armi.codex-task-source.v2"
                else CodexModel.SOL
            ),
            reasoning_effort=(
                CodexReasoningEffort(document["reasoning_effort"])
                if version == "armi.codex-task-source.v2"
                else CodexReasoningEffort.MEDIUM
            ),
            web_search=(
                document["web_search"]
                if version == "armi.codex-task-source.v2"
                else False
            ),
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
