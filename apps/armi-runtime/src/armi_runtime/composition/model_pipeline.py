"""Production S024 model work execution outside database write transactions."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable
from datetime import timedelta
from pathlib import Path
from typing import Any
from uuid import UUID, uuid7

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
    CredentialLocator,
    CredentialPort,
    LockPlan,
    LockTarget,
    ModelAttemptId,
    ModelInvocationResult,
    ModelRequest,
    ModelResultStatus,
    ModelViolation,
    RuntimeFence,
    WorkLease,
    WorkViolation,
)
from armi_kernel.contracts import Digest, Instant, Purpose, SubjectId

from armi_runtime.adapters.artifacts.content_store import (
    ContentAddressedArtifactStore,
)
from armi_runtime.adapters.model.volcengine_ark import VolcengineArkModelAdapter
from armi_runtime.adapters.persistence.artifact_catalog import (
    ArtifactCatalogRepository,
)
from armi_runtime.adapters.persistence.cognitive_model import (
    ModelEpisodeSnapshot,
    PostgreSQLCognitiveModelRepository,
)
from armi_runtime.adapters.persistence.durable_work import (
    PostgreSQLDurableWorkGateway,
)
from armi_runtime.adapters.persistence.unit_of_work import (
    PostgreSQLUnitOfWork,
    PostgreSQLUnitOfWorkFactory,
)
from armi_runtime.adapters.transaction_errors import DatabaseTransactionError

from .model_contract import (
    build_request_bytes,
    candidate_schema,
    checked_model_request,
    load_active_binding,
    parse_candidate,
)

_WORK_KIND = "cognition.model.invoke"
_LEASE_SECONDS = 30
_RENEW_SECONDS = 20
Diagnostic = Callable[[str], None]


async def _one_chunk(value: bytes) -> AsyncIterator[bytes]:
    yield value


def _ignore_diagnostic(_event: str) -> None:
    return None


class ModelPipeline:
    """Claim model work and preserve every physical provider attempt."""

    __slots__ = (
        "_adapter",
        "_catalog",
        "_diagnostic",
        "_factory",
        "_lease_owner",
        "_repository",
        "_stop",
        "_storage",
        "_work",
    )

    def __init__(
        self,
        *,
        factory: PostgreSQLUnitOfWorkFactory,
        storage: ContentAddressedArtifactStore,
        credential_port: CredentialPort,
        credential_locator: CredentialLocator,
        diagnostic: Diagnostic | None = None,
    ) -> None:
        binding = load_active_binding()
        self._factory = factory
        self._storage = storage
        self._adapter = VolcengineArkModelAdapter(
            binding=binding,
            credential_port=credential_port,
            locator=credential_locator,
            candidate_schema=candidate_schema(),
            candidate_parser=parse_candidate,
        )
        self._catalog = ArtifactCatalogRepository()
        self._repository = PostgreSQLCognitiveModelRepository()
        self._work = PostgreSQLDurableWorkGateway(factory)
        self._lease_owner = uuid7()
        self._stop = asyncio.Event()
        self._diagnostic = diagnostic or _ignore_diagnostic

    async def open(self) -> None:
        try:
            await self._factory.open()
            await self._storage.prepare()
        except DatabaseTransactionError:
            raise ModelViolation("MODEL-DATABASE") from None
        except ArtifactViolation:
            raise ModelViolation("MODEL-ARTIFACT") from None

    async def close(self) -> None:
        self._stop.set()
        await self._factory.close()

    def stop(self) -> None:
        self._stop.set()

    async def invoke_once(self) -> bool:
        try:
            records = await self._work.claim(
                work_kind=_WORK_KIND,
                lease_owner=self._lease_owner,
                lease_seconds=_LEASE_SECONDS,
                limit=1,
            )
        except WorkViolation:
            raise ModelViolation("MODEL-DATABASE") from None
        if not records:
            return False
        lease = records[0].lease
        assert lease is not None
        try:
            snapshot = await self._snapshot(lease)
            context_bytes = await self._read_context(snapshot)
            request_bytes = build_request_bytes(
                binding=self._adapter.binding,
                compiled_context=context_bytes,
                context_digest=snapshot.context_digest,
                included_context_refs=snapshot.included_context_refs,
            )
            input_tokens = await self._adapter.tokenize(request_bytes)
            request = checked_model_request(
                binding=self._adapter.binding,
                request_bytes=request_bytes,
                context_digest=snapshot.context_digest,
                input_tokens=input_tokens,
            )
            published_request = await self._publish(
                request.canonical_bytes,
                logical_kind="model.request",
                snapshot=snapshot,
            )
            async with self._factory.unit_of_work(LockPlan()) as unit_of_work:
                request_registration = await self._catalog.register(
                    unit_of_work,
                    ArtifactId(uuid7()),
                    published_request,
                )
                if request_registration.inserted:
                    await unit_of_work.audit.append(
                        _artifact_audit(
                            unit_of_work,
                            request_registration.ref,
                            snapshot,
                        )
                    )
                attempt_id = await self._repository.prepare_attempt(
                    unit_of_work,
                    lease=lease,
                    snapshot=snapshot,
                    binding=self._adapter.binding,
                    request_artifact_id=request_registration.ref.artifact_id,
                    request_digest=request.digest,
                )
            async with self._factory.unit_of_work(LockPlan()) as unit_of_work:
                await self._repository.mark_dispatched(
                    unit_of_work,
                    lease=lease,
                    attempt_id=attempt_id,
                    episode_id=snapshot.episode_id,
                )
            result, lease = await self._invoke_with_renewal(request, lease)
            if result.status is ModelResultStatus.SUCCEEDED:
                assert result.response_bytes is not None
                published_response = await self._publish(
                    result.response_bytes,
                    logical_kind="model.response",
                    snapshot=snapshot,
                )
                async with self._factory.unit_of_work(LockPlan()) as unit_of_work:
                    response_registration = await self._catalog.register(
                        unit_of_work,
                        ArtifactId(uuid7()),
                        published_response,
                    )
                    if response_registration.inserted:
                        await unit_of_work.audit.append(
                            _artifact_audit(
                                unit_of_work,
                                response_registration.ref,
                                snapshot,
                            )
                        )
                    await self._repository.settle_success(
                        unit_of_work,
                        lease=lease,
                        snapshot=snapshot,
                        attempt_id=attempt_id,
                        response_artifact_id=(response_registration.ref.artifact_id),
                        result=result,
                    )
            else:
                await self._settle_failure(
                    lease=lease,
                    snapshot=snapshot,
                    attempt_id=attempt_id,
                    result=result,
                    retryable=None,
                )
            return True
        except ModelViolation as error:
            if error.code == "MODEL-WORK-STALE":
                self._diagnostic("model.work.stale")
                return True
            attempt = locals().get("attempt_id")
            current_snapshot = locals().get("snapshot")
            if isinstance(attempt, ModelAttemptId) and isinstance(
                current_snapshot, ModelEpisodeSnapshot
            ):
                await self._settle_failure(
                    lease=lease,
                    snapshot=current_snapshot,
                    attempt_id=attempt,
                    result=_error_result(error),
                    retryable=error.retryable,
                )
                return True
            await self._settle_before_attempt(lease, locals().get("snapshot"), error)
            return True
        except ArtifactViolation:
            error = ModelViolation("MODEL-ARTIFACT", retryable=True)
            attempt = locals().get("attempt_id")
            current_snapshot = locals().get("snapshot")
            if isinstance(attempt, ModelAttemptId) and isinstance(
                current_snapshot, ModelEpisodeSnapshot
            ):
                await self._settle_failure(
                    lease=lease,
                    snapshot=current_snapshot,
                    attempt_id=attempt,
                    result=_error_result(error),
                    retryable=True,
                )
            else:
                await self._settle_before_attempt(
                    lease,
                    current_snapshot,
                    error,
                )
            return True
        except DatabaseTransactionError, WorkViolation:
            self._diagnostic("model.worker.transient_failure")
            return True

    async def run_worker(self) -> None:
        while not self._stop.is_set():
            try:
                worked = await self.invoke_once()
            except ModelViolation:
                self._diagnostic("model.worker.failed")
                worked = False
            await self._wait(0 if worked else 1)

    async def _wait(self, seconds: int) -> None:
        if seconds == 0:
            await asyncio.sleep(0)
            return
        try:
            await asyncio.wait_for(self._stop.wait(), timeout=seconds)
        except TimeoutError:
            return

    async def _snapshot(self, lease: WorkLease) -> ModelEpisodeSnapshot:
        try:
            async with self._factory.unit_of_work(LockPlan()) as unit_of_work:
                return await self._repository.snapshot(unit_of_work, lease)
        except DatabaseTransactionError:
            raise ModelViolation("MODEL-DATABASE") from None

    async def _read_context(self, snapshot: ModelEpisodeSnapshot) -> bytes:
        value = b""
        try:
            stream = await self._storage.open_verified(snapshot.compiled_context)
            async with stream:
                value = await stream.read()
        except ArtifactViolation:
            raise ModelViolation("MODEL-CONTEXT") from None
        if (
            not value
            or Digest.from_bytes(value) != snapshot.compiled_context.content_digest
        ):
            raise ModelViolation("MODEL-CONTEXT")
        return value

    async def _publish(
        self,
        value: bytes,
        *,
        logical_kind: str,
        snapshot: ModelEpisodeSnapshot,
    ):
        staged = await self._storage.stage(
            _one_chunk(value),
            ArtifactPolicy(
                "application/json",
                logical_kind,
                "model.adapter",
                snapshot.trace_id,
                ArtifactPrivacyScope.RESTRICTED,
            ),
        )
        return await self._storage.publish(staged)

    async def _invoke_with_renewal(
        self,
        request: ModelRequest,
        lease: WorkLease,
    ) -> tuple[ModelInvocationResult, WorkLease]:
        task = asyncio.create_task(
            self._adapter.invoke(request),
            name=f"model-attempt-{lease.attempt_id}",
        )
        current_lease = lease
        try:
            while True:
                done, _ = await asyncio.wait({task}, timeout=_RENEW_SECONDS)
                if done:
                    return await task, current_lease
                try:
                    current_lease = await self._work.renew(
                        current_lease,
                        lease_seconds=_LEASE_SECONDS,
                    )
                except WorkViolation:
                    task.cancel()
                    await asyncio.gather(task, return_exceptions=True)
                    raise ModelViolation("MODEL-WORK-STALE") from None
        except asyncio.CancelledError:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            raise

    async def _settle_failure(
        self,
        *,
        lease: WorkLease,
        snapshot: ModelEpisodeSnapshot,
        attempt_id: ModelAttemptId,
        result: ModelInvocationResult,
        retryable: bool | None,
    ) -> None:
        if retryable is None:
            retryable = result.status in {
                ModelResultStatus.TIMED_OUT,
                ModelResultStatus.OUTCOME_UNKNOWN,
                ModelResultStatus.REJECTED,
            }
        async with self._factory.unit_of_work(LockPlan()) as unit_of_work:
            await self._repository.settle_failure(
                unit_of_work,
                lease=lease,
                snapshot=snapshot,
                attempt_id=attempt_id,
                result=result,
                retryable=retryable,
            )

    async def _settle_before_attempt(
        self,
        lease: WorkLease,
        snapshot: object,
        error: ModelViolation,
    ) -> None:
        if not isinstance(snapshot, ModelEpisodeSnapshot):
            self._diagnostic("model.preparation.deferred")
            return
        try:
            async with self._factory.unit_of_work(LockPlan()) as unit_of_work:
                if error.retryable:
                    now = await (
                        await unit_of_work._connection_for_repository().execute(  # pyright: ignore[reportPrivateUsage]
                            "SELECT statement_timestamp()"
                        )
                    ).fetchone()
                    if now is None:
                        raise ModelViolation("MODEL-DATABASE")
                    await unit_of_work.work.release(
                        lease,
                        not_before=Instant(now[0] + timedelta(seconds=1)),
                        error_code=error.code,
                    )
                else:
                    await self._repository.fail_before_attempt(
                        unit_of_work,
                        lease=lease,
                        snapshot=snapshot,
                        code=error.code,
                    )
        except DatabaseTransactionError, ModelViolation, WorkViolation:
            self._diagnostic("model.preparation.settlement_deferred")


def _artifact_audit(
    unit_of_work: PostgreSQLUnitOfWork,
    ref: ArtifactRef,
    snapshot: ModelEpisodeSnapshot,
) -> AuditDraft:
    return AuditDraft(
        AuditEventId(uuid7()),
        AuditReference("runtime", unit_of_work.environment_id),
        Purpose("cognition.model"),
        "artifact.catalog.registered",
        AuditReference("artifact", ref.artifact_id.value),
        AuditResultStatus.APPLIED,
        snapshot.trace_id,
        AuditSensitivity.RESTRICTED,
        subject_id=SubjectId(snapshot.subject_id),
        request=AuditReference("cognitive_episode", snapshot.episode_id),
        artifact_digest=ref.content_digest,
    )


def _error_result(error: ModelViolation) -> ModelInvocationResult:
    status = (
        ModelResultStatus.OUTCOME_UNKNOWN
        if error.outcome_unknown
        else ModelResultStatus.TIMED_OUT
        if error.code == "MODEL-REQUEST-TIMEOUT"
        else ModelResultStatus.PROVIDER_FAILED
    )
    return ModelInvocationResult(
        status,
        None,
        None,
        None,
        None,
        None,
        error.code,
    )


def build_model_pipeline(
    conninfo: str,
    *,
    environment_id: UUID,
    data_root: Path,
    max_object_bytes: int,
    pool_min: int,
    pool_max: int,
    acquire_timeout_seconds: int,
    statement_timeout_seconds: int,
    authority_admission: Callable[[], RuntimeFence],
    credential_port: CredentialPort,
    credential_locator: CredentialLocator,
    diagnostic: Diagnostic | None,
) -> ModelPipeline:
    async def reject_dynamic_lock(connection: Any, target: LockTarget) -> None:
        del connection, target
        raise ModelViolation("MODEL-LOCK")

    factory = PostgreSQLUnitOfWorkFactory(
        conninfo,
        environment_id=environment_id,
        lock_acquirer=reject_dynamic_lock,
        pool_min=pool_min,
        pool_max=pool_max,
        acquire_timeout_seconds=acquire_timeout_seconds,
        statement_timeout_seconds=statement_timeout_seconds,
        authority_admission=authority_admission,
    )
    return ModelPipeline(
        factory=factory,
        storage=ContentAddressedArtifactStore(
            data_root / "artifacts",
            max_object_bytes=max_object_bytes,
        ),
        credential_port=credential_port,
        credential_locator=credential_locator,
        diagnostic=diagnostic,
    )


__all__ = ("ModelPipeline", "build_model_pipeline")
