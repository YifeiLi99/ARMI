"""S033 admission and provider-call custody outside database transactions."""

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
    RuntimeFence,
    WebObservationAttemptId,
    WebObservationDraft,
    WebObservationInvocationResult,
    WebObservationRecord,
    WebObservationResultStatus,
    WebObservationViolation,
    WebResearchViolation,
    WorkDraft,
    WorkId,
    WorkLease,
    WorkOwner,
    WorkPayloadRef,
    WorkViolation,
)
from armi_kernel.contracts import (
    Digest,
    IdempotencyKey,
    Instant,
    Purpose,
    TraceId,
)

from armi_runtime.adapters.artifacts.content_store import ContentAddressedArtifactStore
from armi_runtime.adapters.model.web_search_custody import (
    ArkWebSearchAdapter,
    build_request_bytes,
    load_custody_policy,
    parse_request_bytes,
)
from armi_runtime.adapters.persistence.artifact_catalog import ArtifactCatalogRepository
from armi_runtime.adapters.persistence.durable_work import PostgreSQLDurableWorkGateway
from armi_runtime.adapters.persistence.unit_of_work import (
    PostgreSQLUnitOfWork,
    PostgreSQLUnitOfWorkFactory,
)
from armi_runtime.adapters.persistence.web_evidence import (
    PostgreSQLWebEvidenceRepository,
)
from armi_runtime.adapters.persistence.web_observation import (
    PostgreSQLWebObservationRepository,
    WebObservationSnapshot,
)
from armi_runtime.adapters.transaction_errors import DatabaseTransactionError

from .web_evidence import normalize_web_evidence

_WORK_KIND = "web.search.invoke"
_LEASE_SECONDS = 30
_RENEW_SECONDS = 20
Diagnostic = Callable[[str], None]


async def _one_chunk(value: bytes) -> AsyncIterator[bytes]:
    yield value


def _ignore_diagnostic(_event: str) -> None:
    return None


class WebSearchPipeline:
    """Admit explicit internal observations and settle one durable Ark attempt."""

    __slots__ = (
        "_adapter",
        "_catalog",
        "_diagnostic",
        "_evidence_repository",
        "_factory",
        "_lease_owner",
        "_policy",
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
        manifest_bytes: bytes,
        diagnostic: Diagnostic | None = None,
    ) -> None:
        self._factory = factory
        self._storage = storage
        self._adapter = ArkWebSearchAdapter(credential_port, credential_locator)
        self._policy = load_custody_policy(manifest_bytes)
        self._catalog = ArtifactCatalogRepository()
        self._repository = PostgreSQLWebObservationRepository()
        self._evidence_repository = PostgreSQLWebEvidenceRepository()
        self._work = PostgreSQLDurableWorkGateway(factory)
        self._lease_owner = uuid7()
        self._stop = asyncio.Event()
        self._diagnostic = diagnostic or _ignore_diagnostic

    async def open(self) -> None:
        try:
            await self._factory.open()
            await self._storage.prepare()
        except ArtifactViolation, DatabaseTransactionError:
            raise WebObservationViolation("WEB-DEPENDENCY") from None

    async def close(self) -> None:
        self._stop.set()
        await self._factory.close()

    def stop(self) -> None:
        self._stop.set()

    async def admit(self, draft: WebObservationDraft) -> WebObservationRecord:
        if type(draft) is not WebObservationDraft:
            raise WebObservationViolation("WEB-REQUEST")
        query = draft.query_bytes.decode("utf-8", errors="strict")
        request_bytes = build_request_bytes(
            request_id=str(draft.request_id.value),
            subject_id=str(draft.subject_id.value),
            runtime_instance_id=str(draft.runtime_fence.runtime_instance_id.value),
            fence_token=draft.runtime_fence.fence_token,
            idempotency_key=draft.idempotency_key.value,
            query=query,
        )
        try:
            staged = await self._storage.stage(
                _one_chunk(request_bytes),
                ArtifactPolicy(
                    "application/json",
                    "web.search.request",
                    "web.observation",
                    draft.trace_id,
                    ArtifactPrivacyScope.PRIVATE,
                ),
            )
        except ArtifactViolation:
            raise WebObservationViolation("WEB-ARTIFACT") from None
        request_digest = staged.content_digest
        try:
            existing = await self._existing(draft, request_digest)
        except Exception:
            await self._storage.discard(staged)
            raise
        if existing is not None:
            await self._storage.discard(staged)
            return existing
        try:
            published = await self._storage.publish(staged)
        except ArtifactViolation:
            raise WebObservationViolation("WEB-ARTIFACT") from None
        try:
            async with self._factory.unit_of_work(LockPlan()) as unit_of_work:
                existing = await self._repository.existing(
                    unit_of_work,
                    subject_id=draft.subject_id,
                    idempotency_key=draft.idempotency_key.value,
                    request_digest=request_digest,
                )
                if existing is not None:
                    return existing
                if unit_of_work.runtime_fence != draft.runtime_fence:
                    raise WebObservationViolation("WEB-FENCE")
                registration = await self._catalog.register(
                    unit_of_work,
                    ArtifactId(uuid7()),
                    published,
                )
                now = await _database_now(unit_of_work)
                work_id = WorkId(uuid7())
                await unit_of_work.work.enqueue(
                    WorkDraft(
                        work_id,
                        _WORK_KIND,
                        WorkOwner("web_observation", draft.request_id.value),
                        IdempotencyKey(f"web:{draft.idempotency_key.value}"),
                        registration.ref.content_digest,
                        40,
                        now,
                        Instant(now.value + timedelta(seconds=90)),
                        2,
                        draft.trace_id,
                        draft.subject_id,
                        WorkPayloadRef("artifact", registration.ref.artifact_id.value),
                    )
                )
                record = await self._repository.create(
                    unit_of_work,
                    request_id=draft.request_id,
                    subject_id=draft.subject_id,
                    idempotency_key=draft.idempotency_key.value,
                    request_artifact_id=registration.ref.artifact_id,
                    request_digest=request_digest,
                    work_id=work_id,
                )
                if registration.inserted:
                    await unit_of_work.audit.append(
                        _artifact_audit(unit_of_work, registration.ref, draft)
                    )
                await unit_of_work.audit.append(_request_audit(unit_of_work, draft))
                return record
        except WebObservationViolation:
            raise
        except ArtifactViolation, DatabaseTransactionError, WorkViolation:
            recovered = await self._existing(draft, request_digest)
            if recovered is not None:
                return recovered
            raise WebObservationViolation("WEB-DATABASE") from None

    async def invoke_once(self) -> bool:
        try:
            records = await self._work.claim(
                work_kind=_WORK_KIND,
                lease_owner=self._lease_owner,
                lease_seconds=_LEASE_SECONDS,
                limit=1,
            )
        except WorkViolation:
            raise WebObservationViolation("WEB-DATABASE") from None
        if not records:
            return False
        lease = records[0].lease
        assert lease is not None
        try:
            snapshot = await self._snapshot(lease)
            request_bytes = await self._read_request(snapshot)
            request = parse_request_bytes(request_bytes)
            if request["request_id"] != str(snapshot.request_id.value) or request[
                "subject_id"
            ] != str(snapshot.subject_id.value):
                raise WebObservationViolation("WEB-REQUEST-IDENTITY")
            credential_identity = Digest(self._adapter.credential_fingerprint())
            async with self._factory.unit_of_work(LockPlan()) as unit_of_work:
                attempt_id = await self._repository.prepare_attempt(
                    unit_of_work,
                    lease=lease,
                    snapshot=snapshot,
                    credential_identity=credential_identity,
                )
            async with self._factory.unit_of_work(LockPlan()) as unit_of_work:
                await self._repository.mark_dispatched(
                    unit_of_work,
                    lease=lease,
                    snapshot=snapshot,
                    attempt_id=attempt_id,
                )
            result, lease = await self._invoke_with_renewal(request_bytes, lease)
            await self._settle(lease, snapshot, attempt_id, result)
            return True
        except WebObservationViolation as error:
            if error.code == "WEB-WORK-STALE":
                self._diagnostic("web.observation.work_stale")
                return True
            attempt = locals().get("attempt_id")
            snapshot_value = locals().get("snapshot")
            if isinstance(attempt, WebObservationAttemptId) and isinstance(
                snapshot_value, WebObservationSnapshot
            ):
                await self._settle(
                    lease,
                    snapshot_value,
                    attempt,
                    _failure(error),
                )
            else:
                self._diagnostic("web.observation.preparation_failed")
            return True
        except ArtifactViolation, DatabaseTransactionError, WorkViolation:
            self._diagnostic("web.observation.transient_failure")
            return True

    async def run_worker(self) -> None:
        while not self._stop.is_set():
            worked = await self.invoke_once()
            if worked:
                await asyncio.sleep(0)
                continue
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=1)
            except TimeoutError:
                continue

    async def _existing(
        self,
        draft: WebObservationDraft,
        request_digest: Digest,
    ) -> WebObservationRecord | None:
        try:
            async with self._factory.unit_of_work(LockPlan(), read_only=True) as unit:
                return await self._repository.existing(
                    unit,
                    subject_id=draft.subject_id,
                    idempotency_key=draft.idempotency_key.value,
                    request_digest=request_digest,
                )
        except WebObservationViolation:
            raise
        except DatabaseTransactionError:
            return None

    async def _snapshot(self, lease: WorkLease) -> WebObservationSnapshot:
        try:
            async with self._factory.unit_of_work(LockPlan()) as unit:
                return await self._repository.snapshot(unit, lease)
        except DatabaseTransactionError:
            raise WebObservationViolation("WEB-DATABASE") from None

    async def _read_request(self, snapshot: WebObservationSnapshot) -> bytes:
        value = b""
        try:
            stream = await self._storage.open_verified(snapshot.request_artifact)
            async with stream:
                value = await stream.read()
        except ArtifactViolation:
            raise WebObservationViolation("WEB-REQUEST-ARTIFACT") from None
        return value

    async def _invoke_with_renewal(
        self,
        request_bytes: bytes,
        lease: WorkLease,
    ) -> tuple[WebObservationInvocationResult, WorkLease]:
        task = asyncio.create_task(self._adapter.invoke(request_bytes))
        current = lease
        try:
            while True:
                done, _ = await asyncio.wait({task}, timeout=_RENEW_SECONDS)
                if done:
                    return await task, current
                try:
                    current = await self._work.renew(
                        current,
                        lease_seconds=_LEASE_SECONDS,
                    )
                except WorkViolation:
                    task.cancel()
                    await asyncio.gather(task, return_exceptions=True)
                    raise WebObservationViolation("WEB-WORK-STALE") from None
        except asyncio.CancelledError:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            raise

    async def _settle(
        self,
        lease: WorkLease,
        snapshot: WebObservationSnapshot,
        attempt_id: WebObservationAttemptId,
        result: WebObservationInvocationResult,
    ) -> None:
        if result.status is WebObservationResultStatus.SUCCEEDED:
            assert result.canonical_result_bytes is not None
            published = await self._publish(
                result.canonical_result_bytes,
                logical_kind="web.search.result",
                trace_id=snapshot.trace_id,
            )
            try:
                normalized_evidence = (
                    normalize_web_evidence(result.canonical_result_bytes)
                    if snapshot.research_intent_id is not None
                    else None
                )
            except WebResearchViolation:
                raise WebObservationViolation("WEB-EVIDENCE-INVALID") from None
            published_evidence = (
                await self._publish(
                    normalized_evidence.canonical_bytes,
                    logical_kind="web.evidence.provider-synthesis",
                    trace_id=snapshot.trace_id,
                )
                if normalized_evidence is not None
                else None
            )
            published_sources = (
                tuple(
                    [
                        await self._publish(
                            source.canonical_bytes,
                            logical_kind="web.evidence.source-reference",
                            trace_id=snapshot.trace_id,
                        )
                        for source in normalized_evidence.sources
                    ]
                )
                if normalized_evidence is not None
                else ()
            )
            async with self._factory.unit_of_work(LockPlan()) as unit:
                registration = await self._catalog.register(
                    unit,
                    ArtifactId(uuid7()),
                    published,
                )
                if registration.inserted:
                    await unit.audit.append(
                        _result_artifact_audit(unit, registration.ref, snapshot)
                    )
                await self._repository.settle_success(
                    unit,
                    lease=lease,
                    snapshot=snapshot,
                    attempt_id=attempt_id,
                    result_artifact=registration.ref,
                    result=result,
                )
                if normalized_evidence is not None and published_evidence is not None:
                    evidence_registration = await self._catalog.register(
                        unit,
                        ArtifactId(uuid7()),
                        published_evidence,
                    )
                    source_registrations = tuple(
                        [
                            await self._catalog.register(
                                unit,
                                ArtifactId(uuid7()),
                                source,
                            )
                            for source in published_sources
                        ]
                    )
                    for evidence_item in (
                        evidence_registration,
                        *source_registrations,
                    ):
                        if evidence_item.inserted:
                            await unit.audit.append(
                                _result_artifact_audit(
                                    unit,
                                    evidence_item.ref,
                                    snapshot,
                                )
                            )
                    await self._evidence_repository.accept_evidence(
                        unit,
                        request_id=snapshot.request_id,
                        attempt_id=attempt_id,
                        evidence_artifact_id=evidence_registration.ref.artifact_id,
                        source_artifact_ids=tuple(
                            item.ref.artifact_id for item in source_registrations
                        ),
                        sources=tuple(
                            (
                                source.ordinal,
                                source.canonical_url_digest,
                            )
                            for source in normalized_evidence.sources
                        ),
                    )
                await unit.audit.append(
                    _settlement_audit(
                        unit,
                        snapshot,
                        AuditResultStatus.COMPLETED,
                    )
                )
            return
        async with self._factory.unit_of_work(LockPlan()) as unit:
            await self._repository.settle_failure(
                unit,
                lease=lease,
                snapshot=snapshot,
                attempt_id=attempt_id,
                result=result,
            )
            await unit.audit.append(
                _settlement_audit(
                    unit,
                    snapshot,
                    AuditResultStatus.UNKNOWN
                    if result.status is WebObservationResultStatus.OUTCOME_UNKNOWN
                    else AuditResultStatus.FAILED,
                )
            )

    async def _publish(
        self,
        value: bytes,
        *,
        logical_kind: str,
        trace_id: TraceId,
    ):
        try:
            staged = await self._storage.stage(
                _one_chunk(value),
                ArtifactPolicy(
                    "application/json",
                    logical_kind,
                    "web.observation",
                    trace_id,
                    ArtifactPrivacyScope.PRIVATE,
                ),
            )
            return await self._storage.publish(staged)
        except ArtifactViolation:
            raise WebObservationViolation("WEB-ARTIFACT") from None


def _failure(error: WebObservationViolation) -> WebObservationInvocationResult:
    return WebObservationInvocationResult(
        WebObservationResultStatus.OUTCOME_UNKNOWN
        if error.outcome_unknown
        else WebObservationResultStatus.FAILED,
        None,
        None,
        None,
        (),
        None,
        error.code,
    )


async def _database_now(unit: PostgreSQLUnitOfWork) -> Instant:
    connection = unit._connection_for_repository()  # pyright: ignore[reportPrivateUsage]
    row = await (await connection.execute("SELECT statement_timestamp()")).fetchone()
    if row is None:
        raise WebObservationViolation("WEB-DATABASE")
    return Instant(row[0])


def _artifact_audit(
    unit: PostgreSQLUnitOfWork,
    ref: ArtifactRef,
    draft: WebObservationDraft,
) -> AuditDraft:
    return AuditDraft(
        AuditEventId(uuid7()),
        AuditReference("runtime", unit.environment_id),
        Purpose("web.observation"),
        "artifact.catalog.registered",
        AuditReference("artifact", ref.artifact_id.value),
        AuditResultStatus.APPLIED,
        draft.trace_id,
        AuditSensitivity.RESTRICTED,
        subject_id=draft.subject_id,
    )


def _request_audit(
    unit: PostgreSQLUnitOfWork, draft: WebObservationDraft
) -> AuditDraft:
    return AuditDraft(
        AuditEventId(uuid7()),
        AuditReference("runtime", unit.environment_id),
        Purpose("web.observation"),
        "web.observation.admitted",
        AuditReference("web_observation", draft.request_id.value),
        AuditResultStatus.ACCEPTED,
        draft.trace_id,
        AuditSensitivity.RESTRICTED,
        subject_id=draft.subject_id,
    )


def _result_artifact_audit(
    unit: PostgreSQLUnitOfWork,
    ref: ArtifactRef,
    snapshot: WebObservationSnapshot,
) -> AuditDraft:
    return AuditDraft(
        AuditEventId(uuid7()),
        AuditReference("runtime", unit.environment_id),
        Purpose("web.observation"),
        "artifact.catalog.registered",
        AuditReference("artifact", ref.artifact_id.value),
        AuditResultStatus.APPLIED,
        snapshot.trace_id,
        AuditSensitivity.RESTRICTED,
        subject_id=snapshot.subject_id,
    )


def _settlement_audit(
    unit: PostgreSQLUnitOfWork,
    snapshot: WebObservationSnapshot,
    status: AuditResultStatus,
) -> AuditDraft:
    return AuditDraft(
        AuditEventId(uuid7()),
        AuditReference("runtime", unit.environment_id),
        Purpose("web.observation"),
        "web.observation.settled",
        AuditReference("web_observation", snapshot.request_id.value),
        status,
        snapshot.trace_id,
        AuditSensitivity.RESTRICTED,
        subject_id=snapshot.subject_id,
    )


def build_web_search_pipeline(
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
    manifest_bytes: bytes,
    diagnostic: Diagnostic | None,
) -> WebSearchPipeline:
    async def reject_dynamic_lock(connection: Any, target: LockTarget) -> None:
        del connection, target
        raise WebObservationViolation("WEB-LOCK")

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
    return WebSearchPipeline(
        factory=factory,
        storage=ContentAddressedArtifactStore(
            data_root / "artifacts",
            max_object_bytes=max_object_bytes,
        ),
        credential_port=credential_port,
        credential_locator=credential_locator,
        manifest_bytes=manifest_bytes,
        diagnostic=diagnostic,
    )


__all__ = ("WebSearchPipeline", "build_web_search_pipeline")
