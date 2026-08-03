"""Production S023 opportunity selection and Context preparation."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable
from importlib.resources import files
from pathlib import Path
from typing import Any
from uuid import UUID, uuid7

import rfc8785
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
    CognitiveEpisodeId,
    ContextItemCandidate,
    ContextRequest,
    ContextSection,
    ContextSourceIdentity,
    ContextTrustClass,
    ContextViolation,
    LockPlan,
    LockTarget,
    OpportunitySelector,
    RuntimeFence,
    WorkLease,
    WorkViolation,
)
from armi_kernel.contracts import Digest, Purpose, SubjectId

from armi_runtime.adapters.artifacts.content_store import (
    ContentAddressedArtifactStore,
)
from armi_runtime.adapters.persistence.artifact_catalog import (
    ArtifactCatalogRepository,
)
from armi_runtime.adapters.persistence.context import (
    ContextArtifactSource,
    ContextEpisodeSnapshot,
    PostgreSQLContextRepository,
)
from armi_runtime.adapters.persistence.durable_work import (
    PostgreSQLDurableWorkGateway,
)
from armi_runtime.adapters.persistence.unit_of_work import (
    PostgreSQLUnitOfWork,
    PostgreSQLUnitOfWorkFactory,
)
from armi_runtime.adapters.transaction_errors import DatabaseTransactionError

from .context_compiler import (
    CONTEXT_MECHANISM,
    DeterministicContextCompiler,
)

_WORK_KIND = "cognition.context.prepare"
Diagnostic = Callable[[str], None]


async def _one_chunk(value: bytes) -> AsyncIterator[bytes]:
    yield value


def _ignore_diagnostic(_event: str) -> None:
    return None


class ContextPipeline(OpportunitySelector):
    """Own the active FIFO selector and the only Context worker."""

    __slots__ = (
        "_catalog",
        "_compiler",
        "_diagnostic",
        "_factory",
        "_lease_owner",
        "_policy_digest",
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
        policy_digest: Digest,
        diagnostic: Diagnostic | None = None,
    ) -> None:
        self._factory = factory
        self._storage = storage
        self._policy_digest = policy_digest
        self._repository = PostgreSQLContextRepository()
        self._catalog = ArtifactCatalogRepository()
        self._compiler = DeterministicContextCompiler()
        self._work = PostgreSQLDurableWorkGateway(factory)
        self._lease_owner = uuid7()
        self._stop = asyncio.Event()
        self._diagnostic = diagnostic or _ignore_diagnostic

    async def open(self) -> None:
        try:
            await self._factory.open()
            await self._storage.prepare()
        except DatabaseTransactionError:
            raise ContextViolation("CTX-DATABASE") from None
        except ArtifactViolation:
            raise ContextViolation("CTX-ARTIFACT") from None

    async def close(self) -> None:
        self._stop.set()
        await self._factory.close()

    def stop(self) -> None:
        self._stop.set()

    async def select_once(self) -> CognitiveEpisodeId | None:
        try:
            async with self._factory.unit_of_work(LockPlan()) as unit_of_work:
                return await self._repository.select_one(
                    unit_of_work,
                    policy_digest=self._policy_digest,
                    mechanism_config_digest=self._policy_digest,
                )
        except ContextViolation:
            raise
        except DatabaseTransactionError, WorkViolation:
            raise ContextViolation("CTX-DATABASE") from None

    async def prepare_once(self) -> bool:
        try:
            claimed = await self._work.claim(
                work_kind=_WORK_KIND,
                lease_owner=self._lease_owner,
                lease_seconds=30,
                limit=1,
            )
        except WorkViolation:
            raise ContextViolation("CTX-DATABASE") from None
        if not claimed:
            return False
        lease = claimed[0].lease
        assert lease is not None
        try:
            snapshot = await self._snapshot(lease)
            evidence_bytes = await self._read_source(snapshot.evidence, snapshot)
            prompt_bytes = await self._read_source(snapshot.fixed_prompt, snapshot)
            request = _context_request(snapshot, evidence_bytes, prompt_bytes)
            result = self._compiler.compile(request)
            manifest = await self._publish(
                result.manifest_bytes,
                "context.manifest",
                snapshot,
            )
            compiled = await self._publish(
                result.compiled.canonical_bytes,
                "context.compiled",
                snapshot,
            )
            async with self._factory.unit_of_work(LockPlan()) as unit_of_work:
                manifest_registration = await self._catalog.register(
                    unit_of_work,
                    ArtifactId(uuid7()),
                    manifest,
                )
                compiled_registration = await self._catalog.register(
                    unit_of_work,
                    ArtifactId(uuid7()),
                    compiled,
                )
                for registration in (manifest_registration, compiled_registration):
                    if registration.inserted:
                        await unit_of_work.audit.append(
                            _artifact_audit(unit_of_work, registration.ref, snapshot)
                        )
                await self._repository.settle_prepared(
                    unit_of_work,
                    lease=lease,
                    result=result,
                    manifest_artifact_id=manifest_registration.ref.artifact_id,
                    compiled_artifact_id=compiled_registration.ref.artifact_id,
                )
            return True
        except ContextViolation as error:
            await self._fail_if_current(lease, error.code)
            return True
        except ArtifactViolation:
            await self._fail_if_current(lease, "CTX-SOURCE-READ-FAILED")
            return True
        except DatabaseTransactionError, WorkViolation:
            self._diagnostic("context.prepare.transient_failure")
            return True

    async def run_selector(self) -> None:
        while not self._stop.is_set():
            try:
                selected = await self.select_once()
            except ContextViolation:
                if not self._stop.is_set():
                    self._diagnostic("context.selector.failed")
                selected = None
            await self._wait(0 if selected is not None else 1)

    async def run_worker(self) -> None:
        while not self._stop.is_set():
            try:
                worked = await self.prepare_once()
            except ContextViolation:
                if not self._stop.is_set():
                    self._diagnostic("context.worker.failed")
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

    async def _snapshot(self, lease: WorkLease) -> ContextEpisodeSnapshot:
        try:
            async with self._factory.unit_of_work(
                LockPlan(),
                read_only=True,
            ) as unit_of_work:
                return await self._repository.snapshot(unit_of_work, lease)
        except DatabaseTransactionError:
            raise ContextViolation("CTX-DATABASE") from None

    async def _read_source(
        self,
        source: ContextArtifactSource,
        snapshot: ContextEpisodeSnapshot,
    ) -> bytes:
        value = b""
        try:
            stream = await self._storage.open_verified(source.ref)
            async with stream:
                value = await stream.read()
        except ArtifactViolation:
            raise ContextViolation("CTX-SOURCE-READ-FAILED") from None
        if not value:
            raise ContextViolation("CTX-SOURCE-MISSING")
        if Digest.from_bytes(value) != source.ref.content_digest:
            raise ContextViolation("CTX-SOURCE-READ-FAILED")
        if len(value) > 262_144:
            raise ContextViolation("CTX-BUDGET-REQUIRED")
        try:
            value.decode("utf-8", errors="strict")
        except UnicodeDecodeError:
            raise ContextViolation("CTX-SOURCE-INVALID") from None
        del snapshot
        return value

    async def _publish(
        self,
        value: bytes,
        logical_kind: str,
        snapshot: ContextEpisodeSnapshot,
    ):
        try:
            staged = await self._storage.stage(
                _one_chunk(value),
                ArtifactPolicy(
                    "application/json",
                    logical_kind,
                    "context.compiler",
                    snapshot.trace_id,
                    ArtifactPrivacyScope.PRIVATE,
                ),
            )
            return await self._storage.publish(staged)
        except ArtifactViolation:
            raise ContextViolation("CTX-ARTIFACT") from None

    async def _fail_if_current(self, lease: WorkLease, code: str) -> None:
        try:
            async with self._factory.unit_of_work(LockPlan()) as unit_of_work:
                await self._repository.fail(
                    unit_of_work,
                    lease=lease,
                    code=code,
                )
        except ContextViolation, DatabaseTransactionError, WorkViolation:
            self._diagnostic("context.prepare.failure_settlement_deferred")


def _context_request(
    snapshot: ContextEpisodeSnapshot,
    evidence_bytes: bytes,
    prompt_bytes: bytes,
) -> ContextRequest:
    runtime_bytes = rfc8785.dumps(
        {
            "subject_id": str(snapshot.subject_id),
            "subject_version": snapshot.subject_version,
            "state_epoch": snapshot.state_epoch,
            "bundle_activation_id": str(snapshot.bundle_activation_id),
        }
    )
    items: list[ContextItemCandidate] = [
        _item(
            ContextSection.RUNTIME_TRUTH,
            "runtime_identity",
            snapshot.bundle_activation_id,
            snapshot.subject_version,
            runtime_bytes,
            ContextTrustClass.RUNTIME_AUTHORITY,
            required=True,
            relevance=100,
        ),
        _item(
            ContextSection.PURPOSE,
            "current_purpose",
            snapshot.opportunity_id,
            1,
            rfc8785.dumps({"purpose": snapshot.purpose}),
            ContextTrustClass.POLICY,
            required=True,
            relevance=100,
        ),
    ]
    section_by_component = {
        "self": ContextSection.SELF,
        "mind": ContextSection.MIND,
        "life_mode": ContextSection.LIFE_MODE,
    }
    for kind, source_id, version, payload, digest in snapshot.component_payloads:
        items.append(
            ContextItemCandidate(
                section_by_component[kind],
                kind,
                ContextSourceIdentity(kind, source_id, version, digest),
                ContextTrustClass.SUBJECTIVE_STATE,
                "private",
                payload.decode("utf-8"),
                kind == "self",
                90,
            )
        )
    items.extend(
        (
            _item(
                ContextSection.SCENE,
                "current_scene",
                snapshot.scene_id,
                1,
                snapshot.scene_bytes,
                ContextTrustClass.RUNTIME_AUTHORITY,
                required=False,
                relevance=80,
            ),
            _unavailable(ContextSection.RELATIONSHIP, "relationship"),
            _unavailable(ContextSection.MEMORY, "memory"),
            _item(
                ContextSection.EVIDENCE,
                (
                    "codex_task_source"
                    if snapshot.evidence.source_kind == "codex_task_source"
                    else "current_evidence"
                ),
                snapshot.evidence.source_id,
                snapshot.evidence.source_version,
                evidence_bytes,
                ContextTrustClass.EXTERNAL_CLAIM,
                required=True,
                relevance=100,
                source_kind=snapshot.evidence.source_kind,
            ),
            _item(
                ContextSection.CAPABILITY,
                "web_search_availability",
                UUID("01985d00-0000-7000-8000-000000000034"),
                1,
                rfc8785.dumps(
                    {
                        "binding": "armi.model-tool.volcengine-ark-web-search-v1",
                        "implementation_status": "complete",
                        "activation_status": "inactive",
                        "operation_class": "search_read_public",
                    }
                ),
                ContextTrustClass.POLICY,
                required=False,
                relevance=60,
            ),
            _item(
                ContextSection.CAPABILITY,
                "capability_catalog",
                UUID("01985d00-0000-7000-8000-000000000027"),
                1,
                _capability_catalog_bytes(),
                ContextTrustClass.POLICY,
                required=True,
                relevance=70,
            ),
            _item(
                ContextSection.PROMPT,
                "fixed_prompt",
                snapshot.fixed_prompt.source_id,
                snapshot.fixed_prompt.source_version,
                prompt_bytes,
                ContextTrustClass.POLICY,
                required=True,
                relevance=100,
            ),
            _unavailable(ContextSection.PROMPT, "creator_prompt"),
            _unavailable(ContextSection.PROMPT, "subject_prompt"),
        )
    )
    return ContextRequest(
        Purpose(snapshot.purpose),
        snapshot.subject_id,
        snapshot.scene_id,
        snapshot.subject_version,
        snapshot.state_epoch,
        snapshot.bundle_activation_id,
        snapshot.policy_digest,
        CONTEXT_MECHANISM,
        snapshot.mechanism_config_digest,
        32,
        262_144,
        524_288,
        tuple(items),
    )


def _item(
    section: ContextSection,
    kind: str,
    source_id: UUID,
    version: int,
    value: bytes,
    trust: ContextTrustClass,
    *,
    required: bool,
    relevance: int,
    source_kind: str | None = None,
) -> ContextItemCandidate:
    try:
        content = value.decode("utf-8", errors="strict")
    except UnicodeDecodeError:
        raise ContextViolation("CTX-SOURCE-INVALID") from None
    return ContextItemCandidate(
        section,
        kind,
        ContextSourceIdentity(
            source_kind or kind,
            source_id,
            version,
            Digest.from_bytes(value),
        ),
        trust,
        "private",
        content,
        required,
        relevance,
    )


def _unavailable(section: ContextSection, kind: str) -> ContextItemCandidate:
    return ContextItemCandidate(
        section,
        kind,
        ContextSourceIdentity("not_implemented", None, None, None),
        ContextTrustClass.RUNTIME_AUTHORITY,
        "private",
        None,
        False,
        0,
        unavailable_reason="CTX-SOURCE-NOT-IMPLEMENTED",
    )


def _capability_catalog_bytes() -> bytes:
    try:
        return (
            files("armi_runtime.composition.runtime_resources")
            .joinpath("capability-catalog.manifest.json")
            .read_bytes()
        )
    except OSError:
        raise ContextViolation("CTX-CAPABILITY-CATALOG") from None


def _artifact_audit(
    unit_of_work: PostgreSQLUnitOfWork,
    ref: ArtifactRef,
    snapshot: ContextEpisodeSnapshot,
) -> AuditDraft:
    return AuditDraft(
        AuditEventId(uuid7()),
        AuditReference("runtime", unit_of_work.environment_id),
        Purpose("cognition.context"),
        "artifact.catalog.registered",
        AuditReference("artifact", ref.artifact_id.value),
        AuditResultStatus.APPLIED,
        snapshot.trace_id,
        AuditSensitivity.PRIVATE,
        subject_id=SubjectId(snapshot.subject_id),
        request=AuditReference("cognitive_episode", snapshot.episode_id),
        artifact_digest=ref.content_digest,
    )


def build_context_pipeline(
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
    policy_digest: Digest,
    diagnostic: Diagnostic | None,
) -> ContextPipeline:
    async def reject_dynamic_lock(
        connection: Any,
        target: LockTarget,
    ) -> None:
        del connection, target
        raise ContextViolation("CTX-LOCK")

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
    return ContextPipeline(
        factory=factory,
        storage=ContentAddressedArtifactStore(
            data_root / "artifacts",
            max_object_bytes=max_object_bytes,
        ),
        policy_digest=policy_digest,
        diagnostic=diagnostic,
    )


__all__ = ("ContextPipeline", "build_context_pipeline")
