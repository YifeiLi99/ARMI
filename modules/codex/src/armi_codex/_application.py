"""S039 Codex task admission, isolated dispatch, verification and evidence custody."""

from __future__ import annotations

import asyncio
import contextlib
import json
import threading
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast
from uuid import UUID, uuid7

import rfc8785
from armi_artifact_store.api import ArtifactCatalogPort
from armi_attention.api import OpportunityAdmissionPort
from armi_data_rights.api import (
    DataRightsEffectGate,
    DataRightsFencePort,
    DataRightsInteractionGate,
)
from armi_effect.api import EffectCodexLifecyclePort, EffectViolation
from armi_evidence.api import EvidenceReadPort, EvidenceWritePort
from armi_expression.api import ExpressionIntentReadPort
from armi_interaction.api import (
    CreatorInputAcceptance,
    CreatorInputContext,
    CreatorInputTransactionPort,
    InteractionIdentityPort,
)
from armi_kernel.application import (
    ArtifactId,
    ArtifactPolicy,
    ArtifactPrivacyScope,
    ArtifactRef,
    ArtifactViolation,
    CreatorProjectionInvalidation,
    CreatorProjectionNotifier,
    CreatorResourceKind,
    ExecutionCustodyMode,
    ExecutionCustodyPort,
    ExecutionCustodyRequest,
    ExecutionCustodyScope,
    ExecutionCustodyScopeKind,
    ExecutionCustodyViolation,
    RuntimeFence,
    ordered_custody_requests,
)
from armi_kernel.contracts import Digest, Instant, SubjectId, TraceId
from armi_runtime_foundation import (
    PostgreSQLRuntimeUnitOfWorkFactory,
    RuntimeTransactionFailure,
)

from ._delegation_contract import (
    CodexCleanupStatus,
    CodexDelegationViolation,
    CodexTaskSourceAdmissionPort,
    CodexTaskSourceDraft,
    CodexTaskSourceId,
    CodexVerificationStatus,
    CreatorCodexTaskAdmissionPort,
    CreatorCodexTaskCommand,
)
from ._postgresql import (
    CodexDispatchSnapshot,
    PostgreSQLCodexDelegationRepository,
)
from ._runner import remove_private_directory, sanitize_platform_home
from ._runner_contract import (
    CodexExecutionId,
    CodexModel,
    CodexReasoningEffort,
    CodexRunnerViolation,
    CodexRunResult,
    CodexRunStatus,
    CodexTaskManifest,
)
from ._subprocess_client import run_subprocess
from ._task_content import task_manifest
from .api import CodexArtifactStorePort, CodexTaskSourceReadPort

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
        "_custody",
        "_data_rights",
        "_data_rights_fence",
        "_diagnostic",
        "_factory",
        "_input_repository",
        "_notifier",
        "_repository",
        "_storage",
        "_unavailable_reason",
    )

    def __init__(
        self,
        factory: PostgreSQLRuntimeUnitOfWorkFactory,
        *,
        storage: CodexArtifactStorePort,
        catalog: ArtifactCatalogPort,
        creator_party_id: UUID,
        custody: ExecutionCustodyPort,
        data_rights: DataRightsInteractionGate,
        data_rights_fence: DataRightsFencePort,
        input_repository: CreatorInputTransactionPort,
        evidence: EvidenceWritePort,
        evidence_read: EvidenceReadPort,
        identity: InteractionIdentityPort,
        opportunity: OpportunityAdmissionPort,
        effect: EffectCodexLifecyclePort,
        expression: ExpressionIntentReadPort,
        sources: CodexTaskSourceReadPort,
        unavailable_reason: Callable[[], str | None],
        notifier: CreatorProjectionNotifier | None,
        diagnostic: Diagnostic,
    ) -> None:
        self._factory = factory
        self._storage = storage
        self._creator_party_id = creator_party_id
        self._custody = custody
        self._data_rights = data_rights
        self._data_rights_fence = data_rights_fence
        self._notifier = notifier
        self._diagnostic = diagnostic
        self._repository = PostgreSQLCodexDelegationRepository(
            evidence,
            opportunity,
            effect,
            expression,
            catalog,
            sources,
            evidence_read,
            identity,
            input_repository,
        )
        self._input_repository = input_repository
        self._catalog = catalog
        self._unavailable_reason = unavailable_reason

    async def admit(self, draft: CodexTaskSourceDraft) -> CodexTaskSourceId:
        try:
            async with self._factory.unit_of_work() as uow:
                return await self._repository.admit_task_source(uow, draft)
        except CodexDelegationViolation:
            raise
        except RuntimeTransactionFailure:
            raise CodexDelegationViolation("CODEX-TASK-DATABASE") from None

    async def accept(self, command: CreatorCodexTaskCommand) -> CreatorInputAcceptance:
        context = await self._context(command.scene_key)
        requests = ordered_custody_requests(
            ExecutionCustodyRequest(
                ExecutionCustodyScope(
                    ExecutionCustodyScopeKind.DATA_RIGHTS_PARTY,
                    context.creator_party_id,
                ),
                ExecutionCustodyMode.SHARED,
            )
        )
        try:
            async with self._custody.hold(requests, deadline_at=None):
                return await self._accept_custodied(command, context)
        except ExecutionCustodyViolation:
            raise CodexDelegationViolation("CODEX-TASK-DATA-RIGHTS") from None

    async def _accept_custodied(
        self, command: CreatorCodexTaskCommand, context: CreatorInputContext
    ) -> CreatorInputAcceptance:
        async with self._factory.unit_of_work() as uow:
            if await self._data_rights.blocks_new_interaction(
                uow, context.creator_party_id
            ):
                raise CodexDelegationViolation("CODEX-TASK-DATA-RIGHTS")
            rights_fence = await self._data_rights_fence.capture(
                uow.transaction, party_id=context.creator_party_id
            )
        objective_digest = Digest.from_bytes(command.objective.encode("utf-8"))
        request_digest = Digest.from_bytes(
            rfc8785.dumps(
                cast(
                    Any,
                    {
                        "schema_kind": "armi.creator-codex-task",
                        "environment_id": str(self._factory.environment_id),
                        "subject_id": str(context.subject_id),
                        "scene_id": str(context.scene_id),
                        "creator_party_id": str(context.creator_party_id),
                        "delegate_id": str(command.delegate_id)
                        if command.delegate_id is not None
                        else None,
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
        reason = self._unavailable_reason()
        if reason is not None:
            raise CodexDelegationViolation(reason)
        task_source_id = CodexTaskSourceId(uuid7())
        manifest = task_manifest(
            task_source_id,
            command.objective,
            command.model_id,
            command.reasoning_effort,
            command.web_search,
        )
        try:
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
                await self._data_rights_fence.validate(
                    uow.transaction,
                    rights_fence,
                    require_contact=True,
                    require_use=True,
                )
                if await self._data_rights.blocks_new_interaction(
                    uow, context.creator_party_id
                ):
                    raise CodexDelegationViolation("CODEX-TASK-DATA-RIGHTS")
                existing = await self._repository.existing_creator_task(
                    uow,
                    context=context,
                    idempotency_key=command.idempotency_key.value,
                    request_digest=request_digest,
                )
                if existing is not None:
                    return existing
                manifest_registration = await self._catalog.register(
                    uow, ArtifactId(uuid7()), published_manifest
                )
                acceptance = await self._repository.admit_creator_task_source(
                    uow,
                    delegate_id=command.delegate_id,
                    context=context,
                    idempotency_key=command.idempotency_key.value,
                    request_digest=request_digest,
                    draft=CodexTaskSourceDraft(
                        task_source_id,
                        SubjectId(context.subject_id),
                        manifest_registration.ref.artifact_id,
                        manifest_registration.ref.content_digest,
                        900,
                        command.trace_id,
                    ),
                )
        except RuntimeTransactionFailure as error:
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
        except RuntimeTransactionFailure:
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
        except RuntimeTransactionFailure:
            raise CodexDelegationViolation("CODEX-TASK-DATABASE") from None

    async def _notify(self, scene_key: str, acceptance: CreatorInputAcceptance) -> None:
        if self._notifier is None:
            self._diagnostic("codex.task.notification_unavailable")
            return
        now = Instant(datetime.now(UTC))
        try:
            await self._notifier.notify(
                CreatorProjectionInvalidation(
                    CreatorResourceKind("scene_timeline"),
                    scene_key,
                    now,
                    "scene-timeline",
                )
            )
            await self._notifier.notify(
                CreatorProjectionInvalidation(
                    CreatorResourceKind("operation"),
                    str(acceptance.opportunity_id),
                    now,
                    "creator-operation",
                )
            )
        except Exception:
            self._diagnostic("codex.task.notification_failed")


class CodexEffectPipeline:
    __slots__ = (
        "_cancellation",
        "_catalog",
        "_custody",
        "_data_rights",
        "_data_rights_fence",
        "_diagnostic",
        "_environment_root",
        "_factory",
        "_failure_notification",
        "_lease_owner",
        "_repository",
        "_run_root",
        "_runner_entry_module",
        "_runtime_admission",
        "_stop",
        "_storage",
        "_unavailable_reason",
        "task_sources",
    )

    def __init__(
        self,
        *,
        factory: PostgreSQLRuntimeUnitOfWorkFactory,
        storage: CodexArtifactStorePort,
        catalog: ArtifactCatalogPort,
        environment_root: Path,
        run_root: Path,
        creator_party_id: UUID,
        creator_input: CreatorInputTransactionPort,
        evidence: EvidenceWritePort,
        evidence_read: EvidenceReadPort,
        identity: InteractionIdentityPort,
        opportunity: OpportunityAdmissionPort,
        effect: EffectCodexLifecyclePort,
        expression: ExpressionIntentReadPort,
        sources: CodexTaskSourceReadPort,
        unavailable_reason: Callable[[], str | None],
        custody: ExecutionCustodyPort,
        data_rights: DataRightsEffectGate,
        interaction_data_rights: DataRightsInteractionGate,
        data_rights_fence: DataRightsFencePort,
        runtime_admission: Callable[[], RuntimeFence],
        runner_entry_module: str,
        notifier: CreatorProjectionNotifier | None,
        diagnostic: Diagnostic | None = None,
        failure_notification: Callable[[UUID, str], Awaitable[None]] | None = None,
    ) -> None:
        self._factory = factory
        self._failure_notification = failure_notification
        self._storage = storage
        self._environment_root = environment_root
        self._run_root = run_root
        self._runner_entry_module = runner_entry_module
        self._repository = PostgreSQLCodexDelegationRepository(
            evidence,
            opportunity,
            effect,
            expression,
            catalog,
            sources,
            evidence_read,
            identity,
            creator_input,
        )
        self._catalog = catalog
        self._unavailable_reason = unavailable_reason
        self._custody = custody
        self._data_rights = data_rights
        self._data_rights_fence = data_rights_fence
        self._runtime_admission = runtime_admission
        self._lease_owner = uuid7()
        self._stop = asyncio.Event()
        self._cancellation = threading.Event()
        self._diagnostic = diagnostic or _ignore_diagnostic
        self.task_sources = CodexTaskSourceGateway(
            factory,
            storage=storage,
            catalog=catalog,
            creator_party_id=creator_party_id,
            input_repository=creator_input,
            evidence=evidence,
            evidence_read=evidence_read,
            identity=identity,
            opportunity=opportunity,
            effect=effect,
            expression=expression,
            sources=sources,
            unavailable_reason=unavailable_reason,
            custody=custody,
            data_rights=interaction_data_rights,
            data_rights_fence=data_rights_fence,
            notifier=notifier,
            diagnostic=self._diagnostic,
        )

    async def open(self) -> None:
        try:
            await self._storage.prepare()
            _cleanup_abandoned_runs(self._run_root)
        except ArtifactViolation, CodexRunnerViolation, OSError:
            raise CodexDelegationViolation("CODEX-TASK-ARTIFACT") from None

    async def close(self) -> None:
        self.stop()

    def stop(self) -> None:
        self._stop.set()
        self._cancellation.set()

    async def dispatch_once(self) -> bool:
        if self._stop.is_set():
            return False
        self._cancellation.clear()
        snapshot: CodexDispatchSnapshot | None = None
        task: CodexTaskManifest | None = None
        dispatched = False
        cleanup_failed = False
        custody_context = None
        try:
            async with self._factory.unit_of_work() as uow:
                snapshot = await self._repository.claim(
                    uow, claim_owner=self._lease_owner
                )
            if snapshot is None:
                return False
            reason = self._unavailable_reason()
            if reason is not None:
                raise CodexDelegationViolation(reason)
            runtime_fence = self._runtime_admission()
            requests = ordered_custody_requests(
                ExecutionCustodyRequest(
                    ExecutionCustodyScope(
                        ExecutionCustodyScopeKind.RUNTIME_AUTHORITY,
                        self._factory.environment_id,
                    ),
                    ExecutionCustodyMode.SHARED,
                ),
                ExecutionCustodyRequest(
                    ExecutionCustodyScope(
                        ExecutionCustodyScopeKind.DATA_RIGHTS_PARTY,
                        snapshot.creator_party_id,
                    ),
                    ExecutionCustodyMode.SHARED,
                ),
                ExecutionCustodyRequest(
                    ExecutionCustodyScope(
                        ExecutionCustodyScopeKind.OUTREACH_SCENE,
                        snapshot.scene_id,
                    ),
                    ExecutionCustodyMode.EXCLUSIVE,
                ),
            )
            custody_context = self._custody.hold(
                requests, deadline_at=snapshot.dispatch_deadline
            )
            await custody_context.__aenter__()
            manifest_bytes = await self._read(snapshot.task_manifest)
            task = _task_manifest(snapshot, manifest_bytes)
            async with self._factory.unit_of_work() as uow:
                if uow.runtime_fence != runtime_fence:
                    raise CodexDelegationViolation("CODEX-DELEGATION-STALE")
                data_fence = await self._data_rights_fence.capture(
                    uow.transaction,
                    party_id=snapshot.creator_party_id,
                )
                if await self._data_rights.blocks_effect(
                    uow,
                    requester_party_id=snapshot.creator_party_id,
                ):
                    raise CodexDelegationViolation("CODEX-DATA-RIGHTS-STALE")
                await self._data_rights_fence.validate(
                    uow.transaction,
                    data_fence,
                    require_contact=True,
                    require_use=True,
                )
                dispatching = await self._repository.mark_dispatching(
                    uow,
                    snapshot,
                    runtime_fence=runtime_fence,
                    data_rights_fence=data_fence,
                )
            if not dispatching:
                return True
            if self._stop.is_set():
                return True
            dispatched = True
            heartbeat = asyncio.create_task(self._heartbeat(snapshot))
            cancellation = self._cancellation
            runner_task = asyncio.create_task(
                asyncio.to_thread(
                    run_subprocess,
                    runner_entry_module=self._runner_entry_module,
                    environment_root=self._environment_root,
                    process_temp=self._run_root
                    / "process-temp"
                    / task.execution_id.value.hex,
                    task=task,
                    cancellation=cancellation,
                )
            )
            runner_completed = False
            try:
                done, _pending = await asyncio.wait(
                    {heartbeat, runner_task}, return_when=asyncio.FIRST_COMPLETED
                )
                if heartbeat in done:
                    await heartbeat
                    raise CodexDelegationViolation("CODEX-DELEGATION-STALE")
                result = await runner_task
                runner_completed = True
            finally:
                heartbeat.cancel()
                await asyncio.gather(heartbeat, return_exceptions=True)
                if not runner_task.done():
                    cancellation.set()
                    try:
                        await asyncio.wait_for(
                            asyncio.shield(runner_task),
                            timeout=10,
                        )
                    except CodexRunnerViolation:
                        pass  # The cancelled child has exited; continue local cleanup.
                    except TimeoutError:
                        runner_task.cancel()
                        self._diagnostic("codex.dispatch.cancel_timeout")
                if not runner_completed:
                    try:
                        _cleanup_execution(self._run_root, task.execution_id)
                    except CodexDelegationViolation:
                        cleanup_failed = True
                task = None
            if self._stop.is_set():
                return True
            published = await self._publish_success(snapshot.trace_id, result)
            await self._settle(
                snapshot,
                status=CodexVerificationStatus.VERIFIED,
                cleanup_status=CodexCleanupStatus.FAILED
                if cleanup_failed or result.cleanup_error_code
                else CodexCleanupStatus.CLEAN,
                published=published,
                execution_error_code=None,
                cleanup_error_code=result.cleanup_error_code
                or ("CODEX-CLEANUP" if cleanup_failed else None),
            )
            return True
        except CodexRunnerViolation as error:
            if self._stop.is_set():
                return True
            self._diagnostic(f"codex.dispatch.runner_failed.{error.code}")
            if cleanup_failed and error.cleanup_error_code is None:
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
                execution_error_code=error.code,
                cleanup_error_code=error.cleanup_error_code,
            )
            return True
        except EffectViolation as error:
            if error.code != "EFFECT-SETTLEMENT-STALE":
                raise
            self._diagnostic("codex.dispatch.result_superseded")
            return True
        except (
            ArtifactViolation,
            CodexDelegationViolation,
            ExecutionCustodyViolation,
        ) as error:
            if snapshot is not None and not self._stop.is_set():
                try:
                    async with self._factory.unit_of_work() as uow:
                        await self._repository.fail_dispatch(
                            uow, snapshot, reason_code=error.code, started=dispatched
                        )
                    await self._notify_failure(snapshot, error.code)
                except RuntimeTransactionFailure, EffectViolation:
                    self._diagnostic("codex.dispatch.settlement_deferred")
            else:
                self._diagnostic("codex.dispatch.custody_failed")
            return True
        except RuntimeTransactionFailure:
            self._diagnostic("codex.dispatch.database_unavailable")
            return True
        finally:
            if task is not None:
                try:
                    _cleanup_execution(self._run_root, task.execution_id)
                except CodexDelegationViolation:
                    self._diagnostic("codex.dispatch.cleanup_failed")
            if custody_context is not None:
                await custody_context.__aexit__(None, None, None)

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
        result: CodexRunResult,
    ) -> dict[str, Any]:
        if result.status is not CodexRunStatus.SUCCEEDED:
            raise CodexDelegationViolation("CODEX-VERIFICATION-RESULT")
        return await self._publish_values(
            trace_id,
            {
                "final_result": (
                    "text/plain",
                    "codex.final-result",
                    result.final_response.encode("utf-8"),
                ),
            },
        )

    async def _publish_failure(
        self,
        trace_id: TraceId,
        status: CodexVerificationStatus,
        error: CodexRunnerViolation,
    ) -> dict[str, Any]:
        value = (
            json.dumps(
                {
                    "status": status.value,
                    "error_code": error.code,
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n"
        ).encode("utf-8")
        return await self._publish_values(
            trace_id,
            {
                "final_result": ("application/json", "codex.final-result", value),
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
        execution_error_code: str | None,
        cleanup_error_code: str | None,
    ) -> None:
        try:
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
                    execution_error_code=execution_error_code,
                    cleanup_error_code=cleanup_error_code,
                )
        except EffectViolation as error:
            if error.code != "EFFECT-SETTLEMENT-STALE":
                raise
            self._diagnostic("codex.dispatch.result_superseded")
            return
        if status in {CodexVerificationStatus.FAILED, CodexVerificationStatus.UNKNOWN}:
            await self._notify_failure(
                snapshot, execution_error_code or cleanup_error_code or "CODEX-FAILED"
            )

    async def _notify_failure(self, snapshot: CodexDispatchSnapshot, code: str) -> None:
        if code in {
            "CODEX-DELEGATION-STALE",
            "CODEX-DATA-RIGHTS-STALE",
            "CODEX-CANCELLED",
        }:
            return
        if self._failure_notification is not None and not self._stop.is_set():
            await self._failure_notification(snapshot.root_operation_id, code)


def _task_manifest(snapshot: CodexDispatchSnapshot, value: bytes) -> CodexTaskManifest:
    try:
        parsed = json.loads(value.decode("utf-8"), object_pairs_hook=_strict_object)
        if type(parsed) is not dict:
            raise ValueError
        document = cast(dict[str, Any], parsed)
        if set(document) != {
            "schema_kind",
            "task_source_id",
            "objective",
            "deadline_seconds",
            "model_id",
            "reasoning_effort",
            "web_search",
        }:
            raise ValueError
        if (
            document["schema_kind"] != "armi.codex-task-source"
            or document["task_source_id"] != str(snapshot.task_source_id)
            or document["deadline_seconds"] != snapshot.deadline_seconds
        ):
            raise ValueError
        return CodexTaskManifest(
            execution_id=CodexExecutionId(snapshot.attempt_id),
            task_id=snapshot.task_source_id,
            effect_id=snapshot.effect_id,
            objective=document["objective"],
            deadline_seconds=snapshot.deadline_seconds,
            model_id=CodexModel(document["model_id"]),
            reasoning_effort=CodexReasoningEffort(document["reasoning_effort"]),
            web_search=document["web_search"],
        )
    except ValueError, KeyError, TypeError, CodexRunnerViolation:
        raise CodexDelegationViolation("CODEX-TASK-MANIFEST") from None


def _strict_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError
        result[key] = value
    return result


def _cleanup_execution(run_root: Path, execution_id: CodexExecutionId) -> None:
    base = run_root.resolve()
    for segment in ("intake", "private", "process-temp"):
        root = (base / segment).resolve()
        target = (root / execution_id.value.hex).resolve()
        if root.parent != base or target.parent != root:
            raise CodexDelegationViolation("CODEX-TASK-CLEANUP")
        try:
            remove_private_directory(target)
        except CodexRunnerViolation:
            raise CodexDelegationViolation("CODEX-TASK-CLEANUP") from None
    _cleanup_platform_home(base)


def _cleanup_platform_home(base: Path) -> None:
    platform = (base / "platform-home").resolve()
    if platform.parent != base:
        raise CodexDelegationViolation("CODEX-TASK-CLEANUP")
    if platform.exists():
        try:
            sanitize_platform_home(platform)
        except CodexRunnerViolation:
            raise CodexDelegationViolation("CODEX-TASK-CLEANUP") from None


def _cleanup_abandoned_runs(run_root: Path) -> None:
    base = run_root.resolve()
    execution_ids: set[UUID] = set()
    for segment in ("intake", "private", "process-temp"):
        root = (base / segment).resolve()
        if root.parent != base:
            raise CodexDelegationViolation("CODEX-TASK-CLEANUP")
        if not root.exists():
            continue
        for child in root.iterdir():
            try:
                execution = UUID(hex=child.name)
            except ValueError:
                raise CodexDelegationViolation("CODEX-TASK-CLEANUP") from None
            if execution.version != 7 or execution.hex != child.name:
                raise CodexDelegationViolation("CODEX-TASK-CLEANUP")
            execution_ids.add(execution)
    for execution in execution_ids:
        _cleanup_execution(base, CodexExecutionId(execution))
    if not execution_ids:
        _cleanup_platform_home(base)


async def _one_chunk(value: bytes) -> AsyncIterator[bytes]:
    yield value


__all__ = ("CodexEffectPipeline", "CodexTaskSourceGateway")
