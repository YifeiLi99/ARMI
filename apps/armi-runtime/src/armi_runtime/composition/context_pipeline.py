"""Production S023 opportunity selection and Context preparation."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Callable
from pathlib import Path
from typing import cast
from uuid import UUID, uuid7

import rfc8785
from armi_activity.api import ActivityReadPort
from armi_artifact_store.content_store import (
    ContentAddressedArtifactStore,
)
from armi_artifact_store.life_material_codec import (
    parse_life_material_artifact,
)
from armi_kernel.application import (
    ArtifactId,
    ArtifactIntegrityStatus,
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
    ContextRequirement,
    ContextSection,
    ContextSourceIdentity,
    ContextTrustClass,
    ContextViolation,
    CredentialLocator,
    CredentialPort,
    ModelViolation,
    OpportunitySelector,
    RuntimeFence,
    WorkLease,
    WorkViolation,
)
from armi_kernel.contracts import Instant, Purpose, SubjectId
from armi_material.api import MaterialProjectionPort
from armi_memory.api import MemoryProjectionPort, MemoryReadPort
from armi_relationship.api import RelationshipReadPort
from armi_sleep.api import SleepReadPort

from armi_runtime.adapters.model.volcengine_embedding import (
    VolcengineArkEmbeddingAdapter,
)
from armi_runtime.adapters.persistence.artifact_catalog import (
    ArtifactCatalogRepository,
)
from armi_runtime.adapters.persistence.context import (
    ContextArtifactSource,
    ContextEpisodeSnapshot,
    ContextMaterialSource,
    ContextSceneTurnSource,
    PostgreSQLContextRepository,
)
from armi_runtime.adapters.persistence.context_embedding import (
    PostgreSQLContextEmbeddingRepository,
    RecalledContext,
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
    CONTEXT_POLICY_VERSION,
    DeterministicContextCompiler,
)
from .context_embedding import RecallStatus, load_embedding_binding
from .context_profiles import ContextAssemblyProfile, context_profile
from .work_wakeup import (
    CONTEXT_PREPARE,
    MODEL_INVOKE,
    OPPORTUNITY_AVAILABLE,
    WorkWakeupBus,
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
        "_embedding",
        "_embedding_repository",
        "_factory",
        "_lease_owner",
        "_policy_version",
        "_repository",
        "_stop",
        "_storage",
        "_wakeups",
        "_web_search_active",
        "_work",
    )

    def __init__(
        self,
        *,
        factory: PostgreSQLUnitOfWorkFactory,
        storage: ContentAddressedArtifactStore,
        activity_read: ActivityReadPort,
        memory_read: MemoryReadPort,
        memory_projection: MemoryProjectionPort,
        material_projection: MaterialProjectionPort,
        relationship_read: RelationshipReadPort,
        sleep_read: SleepReadPort,
        policy_version: str = CONTEXT_POLICY_VERSION,
        web_search_active: bool = False,
        wakeups: WorkWakeupBus | None = None,
        diagnostic: Diagnostic | None = None,
        embedding: VolcengineArkEmbeddingAdapter | None = None,
    ) -> None:
        self._factory = factory
        self._storage = storage
        self._policy_version = policy_version
        self._web_search_active = web_search_active
        self._repository = PostgreSQLContextRepository(
            relationship_read, sleep_read, activity_read, memories=memory_read
        )
        self._catalog = ArtifactCatalogRepository()
        self._compiler = DeterministicContextCompiler()
        self._work = PostgreSQLDurableWorkGateway(factory)
        self._lease_owner = uuid7()
        self._stop = asyncio.Event()
        self._wakeups = wakeups or WorkWakeupBus()
        self._diagnostic = diagnostic or _ignore_diagnostic
        self._embedding = embedding
        self._embedding_repository = PostgreSQLContextEmbeddingRepository(
            memory_projection, material_projection
        )

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
            async with self._factory.unit_of_work() as unit_of_work:
                selected = await self._repository.select_one(unit_of_work)
            if selected is not None:
                self._wakeups.notify(CONTEXT_PREPARE)
            return selected
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
        lease = cast(WorkLease, claimed[0].lease)
        try:
            snapshot = await self._snapshot(lease)
            evidence_bytes = (
                None
                if snapshot.evidence is None
                else await self._read_source(snapshot.evidence, snapshot)
            )
            prompt_bytes = await self._read_source(snapshot.fixed_prompt, snapshot)
            creator_prompt_bytes = (
                None
                if snapshot.creator_prompt is None
                else await self._read_source(snapshot.creator_prompt, snapshot)
            )
            subject_prompt_bytes = (
                None
                if snapshot.subject_prompt is None
                else await self._read_source(snapshot.subject_prompt, snapshot)
            )
            recalled = await self._recall(
                snapshot,
                evidence_bytes
                or snapshot.outreach_trigger_bytes
                or snapshot.activity_summary_bytes,
            )
            material_payloads: list[tuple[ContextMaterialSource, bytes]] = []
            for source in snapshot.material_sources:
                material_payloads.append(
                    (source, await self._read_material_source(source, snapshot))
                )
            recent_scene_payloads: list[tuple[ContextSceneTurnSource, bytes]] = []
            for source in snapshot.recent_scene_sources:
                recent_scene_payloads.append(
                    (source, await self._read_recent_scene_source(source, snapshot))
                )
            request = _context_request(
                snapshot,
                evidence_bytes,
                prompt_bytes,
                tuple(material_payloads),
                creator_prompt_bytes,
                subject_prompt_bytes,
                tuple(recent_scene_payloads),
                web_search_active=self._web_search_active,
                recalled_context=recalled,
            )
            context_profile(snapshot.purpose).validate(request.items)
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
            async with self._factory.unit_of_work() as unit_of_work:
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
                    manifest_artifact=manifest_registration.ref,
                    compiled_artifact=compiled_registration.ref,
                )
            self._wakeups.notify(MODEL_INVOKE)
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
        observed = self._wakeups.version(OPPORTUNITY_AVAILABLE)
        while not self._stop.is_set():
            try:
                selected = await self.select_once()
            except ContextViolation:
                if not self._stop.is_set():
                    self._diagnostic("context.selector.failed")
                selected = None
            if selected is not None:
                await asyncio.sleep(0)
                continue
            observed = await self._wakeups.wait(
                OPPORTUNITY_AVAILABLE,
                observed,
                stop=self._stop,
                timeout_seconds=1,
            )

    async def run_worker(self) -> None:
        observed = self._wakeups.version(CONTEXT_PREPARE)
        while not self._stop.is_set():
            try:
                worked = await self.prepare_once()
            except ContextViolation:
                if not self._stop.is_set():
                    self._diagnostic("context.worker.failed")
                worked = False
            if worked:
                await asyncio.sleep(0)
                continue
            observed = await self._wakeups.wait(
                CONTEXT_PREPARE,
                observed,
                stop=self._stop,
                timeout_seconds=1,
            )

    async def _snapshot(self, lease: WorkLease) -> ContextEpisodeSnapshot:
        try:
            async with self._factory.unit_of_work(
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
        if len(value) > 262_144:
            raise ContextViolation("CTX-BUDGET-REQUIRED")
        try:
            value.decode("utf-8", errors="strict")
        except UnicodeDecodeError:
            raise ContextViolation("CTX-SOURCE-INVALID") from None
        del snapshot
        return value

    async def _recall(
        self,
        snapshot: ContextEpisodeSnapshot,
        query_bytes: bytes,
    ) -> RecalledContext | None:
        profile = context_profile(snapshot.purpose)
        if not profile.retrieval_kinds:
            return None
        if self._embedding is None:
            return RecalledContext(RecallStatus.UNAVAILABLE, (), ())
        try:
            query = query_bytes.decode("utf-8", errors="strict")[:1500]
            response = await self._embedding.embed(query)
            async with self._factory.unit_of_work(read_only=True) as unit_of_work:
                return await self._embedding_repository.recall(
                    unit_of_work,
                    subject_id=snapshot.subject_id,
                    life_generation_id=snapshot.life_generation_id,
                    query_vector=response.vector,
                )
        except UnicodeDecodeError, ModelViolation, DatabaseTransactionError:
            return RecalledContext(RecallStatus.UNAVAILABLE, (), ())

    async def _read_material_source(
        self,
        source: ContextMaterialSource,
        snapshot: ContextEpisodeSnapshot,
    ) -> bytes:
        if (
            source.ref.integrity_status is not ArtifactIntegrityStatus.VERIFIED
            or source.ref.media_type != "application/json"
            or source.ref.logical_kind != "life.material.content"
            or source.ref.privacy_scope is not ArtifactPrivacyScope.PRIVATE
        ):
            raise ContextViolation("CTX-SOURCE-READ-FAILED")
        artifact_bytes = await self._read_source(
            ContextArtifactSource(
                source.ref,
                source.material_id,
                source.head_version,
                "life_material",
            ),
            snapshot,
        )
        try:
            body = parse_life_material_artifact(artifact_bytes).decode(
                "utf-8", errors="strict"
            )
        except ValueError, UnicodeError:
            raise ContextViolation("CTX-SOURCE-INVALID") from None
        return rfc8785.dumps(
            {
                "material_kind": source.material_kind,
                "title": source.title,
                "body": body,
                "metadata": dict(source.metadata),
                "material_status": source.material_status,
                "privacy_status": source.privacy_status,
            }
        )

    async def _read_recent_scene_source(
        self,
        source: ContextSceneTurnSource,
        snapshot: ContextEpisodeSnapshot,
    ) -> bytes:
        expected_kind, expected_privacy = _recent_scene_artifact_contract(
            snapshot.purpose,
            source.speaker,
        )
        if (
            source.ref.integrity_status is not ArtifactIntegrityStatus.VERIFIED
            or source.ref.media_type != "text/plain"
            or source.ref.logical_kind != expected_kind
            or source.ref.privacy_scope is not expected_privacy
        ):
            raise ContextViolation("CTX-SOURCE-READ-FAILED")
        value = await self._read_source(
            ContextArtifactSource(
                source.ref,
                source.timeline_item_id,
                source.source_version,
                "recent_scene_turn",
            ),
            snapshot,
        )
        return rfc8785.dumps(
            {
                "speaker": source.speaker,
                "text": value.decode("utf-8", errors="strict"),
                "occurred_at": source.occurred_at.isoformat(),
            }
        )

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
            async with self._factory.unit_of_work() as unit_of_work:
                await self._repository.fail(
                    unit_of_work,
                    lease=lease,
                    code=code,
                )
        except ContextViolation, DatabaseTransactionError, WorkViolation:
            self._diagnostic("context.prepare.failure_settlement_deferred")


def _recent_scene_artifact_contract(
    purpose: str,
    speaker: str,
) -> tuple[str, ArtifactPrivacyScope]:
    if purpose == "consider_other_human_input":
        if speaker == "other_human":
            return "other_human.input.text", ArtifactPrivacyScope.PRIVATE
        if speaker == "armi":
            return "other-human.response.text", ArtifactPrivacyScope.PRIVATE
    else:
        if speaker == "creator":
            return "creator.input.text", ArtifactPrivacyScope.CREATOR_VISIBLE
        if speaker == "armi":
            return "creator.response.text", ArtifactPrivacyScope.PRIVATE
    raise ContextViolation("CTX-SOURCE-READ-FAILED")


def _scene_turn_content(source: ContextSceneTurnSource, payload: bytes) -> str:
    content = payload.decode("utf-8", errors="strict")
    if source.speaker_label is None:
        return content
    return f"[{source.speaker_label}] {content}"


def _complete_recent_turns(
    values: tuple[tuple[ContextSceneTurnSource, bytes], ...],
) -> tuple[tuple[ContextSceneTurnSource, bytes], ...]:
    complete: list[tuple[ContextSceneTurnSource, bytes]] = []
    index = 0
    while index + 1 < len(values):
        first = values[index]
        second = values[index + 1]
        if (
            first[0].speaker in {"creator", "other_human"}
            and second[0].speaker == "armi"
        ):
            complete.extend((first, second))
            index += 2
        else:
            index += 1
    return tuple(complete[-8:])


def _context_request(
    snapshot: ContextEpisodeSnapshot,
    evidence_bytes: bytes | None,
    prompt_bytes: bytes,
    material_payloads: tuple[tuple[ContextMaterialSource, bytes], ...] = (),
    creator_prompt_bytes: bytes | None = None,
    subject_prompt_bytes: bytes | None = None,
    recent_scene_payloads: tuple[tuple[ContextSceneTurnSource, bytes], ...] = (),
    *,
    web_search_active: bool,
    recalled_context: RecalledContext | None = None,
) -> ContextRequest:
    profile = context_profile(snapshot.purpose)
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
            profile,
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
            profile,
            ContextSection.RUNTIME_TRUTH,
            "resource_snapshot",
            UUID("01985d00-0000-7000-8000-000000000029"),
            1,
            rfc8785.dumps(
                {
                    "schema_version": "armi.life-resource-snapshot.v1",
                    "model_concurrency": 2,
                    "reserved_creator_slots": 1,
                    "activity_burst_limit": 1,
                }
            ),
            ContextTrustClass.RUNTIME_AUTHORITY,
            required=snapshot.purpose
            in {"consider_activity_attention", "consider_activity_internal_work"},
            relevance=100,
            source_kind="resource_snapshot",
        ),
        _item(
            profile,
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
    for kind, source_id, version, payload in snapshot.component_payloads:
        items.append(
            _candidate(
                profile,
                section_by_component[kind],
                kind,
                ContextSourceIdentity(kind, source_id, version),
                ContextTrustClass.SUBJECTIVE_STATE,
                "private",
                payload.decode("utf-8"),
                requested_required=kind == "self"
                or (
                    snapshot.purpose == "perform_subject_self_check"
                    and kind in {"self", "mind"}
                ),
                relevance=90,
            )
        )
    if snapshot.scene_id is not None:
        items.append(
            _item(
                profile,
                ContextSection.SCENE,
                "current_scene",
                snapshot.scene_id,
                1,
                cast(bytes, snapshot.scene_bytes),
                ContextTrustClass.RUNTIME_AUTHORITY,
                required=snapshot.purpose
                in {
                    "consider_creator_input",
                    "consider_life_query_result",
                    "consider_creator_outreach",
                    "consider_other_human_input",
                },
                relevance=80,
            )
        )
        for source, payload in _complete_recent_turns(recent_scene_payloads):
            items.append(
                _candidate(
                    profile,
                    ContextSection.SCENE,
                    "recent_scene_turn",
                    ContextSourceIdentity(
                        "scene_timeline_item",
                        source.timeline_item_id,
                        source.source_version,
                    ),
                    (
                        ContextTrustClass.EXTERNAL_CLAIM
                        if source.speaker in {"creator", "other_human"}
                        else ContextTrustClass.RUNTIME_AUTHORITY
                    ),
                    (
                        "private"
                        if snapshot.purpose == "consider_other_human_input"
                        else "creator_visible"
                    ),
                    _scene_turn_content(source, payload),
                    requested_required=False,
                    relevance=88,
                    business_time=Instant(source.occurred_at),
                )
            )
    accessible_memories = tuple(
        item
        for item in snapshot.memory_payloads
        if item[3] in {"available", "faded"}
        and (
            "current_memory" in profile.retrieval_kinds
            or snapshot.purpose == "maintain_subjective_memory"
        )
    )
    if recalled_context is not None:
        accessible_memories = tuple(
            (
                memory_id,
                version,
                rfc8785.dumps(
                    {
                        "summary": summary,
                        "accessibility": "recalled",
                        "similarity": similarity,
                    }
                ),
                "available",
            )
            for memory_id, version, summary, similarity in recalled_context.memories
        )
    if accessible_memories:
        for (
            memory_id,
            version,
            payload,
            accessibility,
        ) in accessible_memories:
            items.append(
                _candidate(
                    profile,
                    ContextSection.MEMORY,
                    "current_memory",
                    ContextSourceIdentity("subjective_memory", memory_id, version),
                    ContextTrustClass.SUBJECTIVE_STATE,
                    "private",
                    payload.decode("utf-8"),
                    requested_required=False,
                    relevance=85 if accessibility == "available" else 70,
                )
            )
    elif recalled_context is None and "current_memory" not in profile.forbidden_kinds:
        items.append(
            _unavailable(
                profile,
                ContextSection.MEMORY,
                "memory",
                reason=(
                    "CTX-MEMORY-NOT-RECALLABLE"
                    if snapshot.has_memory_records
                    else "CTX-MEMORY-NONE"
                ),
            )
        )
    if (
        recalled_context is None
        and material_payloads
        and "current_material" in profile.retrieval_kinds
    ):
        for source, payload in material_payloads:
            items.append(
                _candidate(
                    profile,
                    ContextSection.MATERIAL,
                    "current_material",
                    ContextSourceIdentity(
                        "life_material",
                        source.material_id,
                        source.head_version,
                    ),
                    ContextTrustClass.SUBJECTIVE_STATE,
                    "private",
                    payload.decode("utf-8", errors="strict"),
                    requested_required=False,
                    relevance=82,
                )
            )
    if recalled_context is not None and "current_material" in profile.retrieval_kinds:
        for material_id, version, chunk, similarity in recalled_context.materials:
            items.append(
                _candidate(
                    profile,
                    ContextSection.MATERIAL,
                    "current_material",
                    ContextSourceIdentity("life_material", material_id, version),
                    ContextTrustClass.SUBJECTIVE_STATE,
                    "private",
                    rfc8785.dumps({"chunk": chunk, "similarity": similarity}).decode(
                        "utf-8"
                    ),
                    requested_required=False,
                    relevance=max(0, min(100, round(similarity * 100))),
                )
            )
        items.append(
            _candidate(
                profile,
                ContextSection.MATERIAL,
                "recall_status",
                ContextSourceIdentity("semantic_recall", snapshot.opportunity_id, 1),
                ContextTrustClass.RUNTIME_AUTHORITY,
                "private",
                rfc8785.dumps(
                    {
                        "status": recalled_context.status.value,
                        "signal": (
                            "recall_unavailable"
                            if recalled_context.status is RecallStatus.UNAVAILABLE
                            else None
                        ),
                    }
                ).decode("utf-8"),
                requested_required=False,
                relevance=100,
            )
        )
    elif (
        recalled_context is None
        and not material_payloads
        and "current_material" not in profile.forbidden_kinds
    ):
        items.append(
            _unavailable(
                profile,
                ContextSection.MATERIAL,
                "material",
                reason="CTX-MATERIAL-NONE",
            )
        )
    capability_states = (
        ()
        if snapshot.purpose == "consider_other_human_input"
        else snapshot.capability_state_payloads
    )
    for (
        capability_id,
        version,
        payload,
        authorization_status,
    ) in capability_states:
        items.append(
            _candidate(
                profile,
                ContextSection.CAPABILITY,
                f"capability_state_{authorization_status}",
                ContextSourceIdentity("capability_state", capability_id, version),
                ContextTrustClass.RUNTIME_AUTHORITY,
                "private",
                payload.decode("utf-8", errors="strict"),
                requested_required=False,
                relevance=100 if authorization_status == "pending" else 96,
            )
        )
    if snapshot.relationship_payloads:
        for relationship_id, version, payload in snapshot.relationship_payloads:
            items.append(
                _candidate(
                    profile,
                    ContextSection.RELATIONSHIP,
                    "current_relationship",
                    ContextSourceIdentity("relationship", relationship_id, version),
                    ContextTrustClass.SUBJECTIVE_STATE,
                    "private",
                    payload.decode("utf-8"),
                    requested_required=snapshot.purpose
                    in {
                        "consider_creator_input",
                        "consider_life_query_result",
                        "consider_other_human_input",
                    },
                    relevance=96,
                )
            )
    else:
        if "current_relationship" in profile.required_kinds:
            items.append(
                _candidate(
                    profile,
                    ContextSection.RELATIONSHIP,
                    "current_relationship",
                    ContextSourceIdentity(
                        "relationship_slot", snapshot.opportunity_id, 1
                    ),
                    ContextTrustClass.RUNTIME_AUTHORITY,
                    "private",
                    '{"status":"none"}',
                    requested_required=True,
                    relevance=96,
                )
            )
        else:
            items.append(
                _unavailable(
                    profile,
                    ContextSection.RELATIONSHIP,
                    "relationship",
                    reason="CTX-RELATIONSHIP-NONE",
                )
            )
    recallable_commitments = tuple(
        item
        for item in snapshot.relationship_commitment_payloads
        if item[3] != "forgotten"
    )
    if recallable_commitments:
        for commitment_id, version, payload, status in recallable_commitments:
            items.append(
                _candidate(
                    profile,
                    ContextSection.RELATIONSHIP,
                    "current_relationship_commitment",
                    ContextSourceIdentity(
                        "relationship_commitment", commitment_id, version
                    ),
                    ContextTrustClass.SUBJECTIVE_STATE,
                    "private",
                    payload.decode("utf-8"),
                    requested_required=False,
                    relevance=92 if status == "active" else 80,
                )
            )
    else:
        items.append(
            _unavailable(
                profile,
                ContextSection.RELATIONSHIP,
                "relationship_commitment",
                reason=(
                    "CTX-COMMITMENT-NOT-RECALLABLE"
                    if snapshot.relationship_commitment_payloads
                    else "CTX-COMMITMENT-NONE"
                ),
            )
        )
    for issue_id, version, payload in snapshot.relationship_issue_payloads:
        items.append(
            _candidate(
                profile,
                ContextSection.RELATIONSHIP,
                "current_relationship_issue",
                ContextSourceIdentity("relationship_issue", issue_id, version),
                ContextTrustClass.SUBJECTIVE_STATE,
                "private",
                payload.decode("utf-8"),
                requested_required=False,
                relevance=90,
            )
        )
    items.extend(
        (
            _item(
                profile,
                ContextSection.ACTIVITY,
                "current_life_opportunity",
                snapshot.opportunity_source_ref,
                snapshot.opportunity_source_version,
                rfc8785.dumps(
                    {
                        "source_kind": snapshot.opportunity_source_kind,
                        "source_ref": str(snapshot.opportunity_source_ref),
                        "source_version": snapshot.opportunity_source_version,
                    }
                ),
                ContextTrustClass.RUNTIME_AUTHORITY,
                required=snapshot.purpose == "consider_autonomous_life",
                relevance=100,
                source_kind=snapshot.opportunity_source_kind,
            ),
            _item(
                profile,
                ContextSection.LIFE_MODE,
                "current_maintenance_window",
                snapshot.opportunity_source_ref,
                snapshot.opportunity_source_version,
                rfc8785.dumps(
                    {
                        "source_kind": snapshot.opportunity_source_kind,
                        "source_ref": str(snapshot.opportunity_source_ref),
                        "source_version": snapshot.opportunity_source_version,
                        "available_after": snapshot.opportunity_available_after.isoformat(),
                        "expires_at": (
                            None
                            if snapshot.opportunity_expires_at is None
                            else snapshot.opportunity_expires_at.isoformat()
                        ),
                    }
                ),
                ContextTrustClass.RUNTIME_AUTHORITY,
                required=snapshot.purpose == "consider_sleep",
                relevance=100,
                source_kind=snapshot.opportunity_source_kind,
            )
            if snapshot.purpose == "consider_sleep"
            else _unavailable(profile, ContextSection.LIFE_MODE, "maintenance_window"),
            _item(
                profile,
                ContextSection.LIFE_MODE,
                "current_maintenance_phase",
                snapshot.opportunity_source_ref,
                snapshot.opportunity_source_version,
                rfc8785.dumps(
                    {
                        "source_kind": snapshot.opportunity_source_kind,
                        "source_ref": str(snapshot.opportunity_source_ref),
                        "source_version": snapshot.opportunity_source_version,
                        "purpose": snapshot.purpose,
                    }
                ),
                ContextTrustClass.RUNTIME_AUTHORITY,
                required=snapshot.purpose
                in {
                    "maintain_subjective_memory",
                    "perform_subject_self_check",
                    "consider_creator_outreach",
                },
                relevance=100,
                source_kind=snapshot.opportunity_source_kind,
            )
            if snapshot.purpose
            in {"maintain_subjective_memory", "perform_subject_self_check"}
            else _unavailable(profile, ContextSection.LIFE_MODE, "maintenance_phase"),
            _item(
                profile,
                ContextSection.ACTIVITY,
                "current_activities",
                snapshot.subject_id,
                1,
                snapshot.activity_summary_bytes,
                ContextTrustClass.RUNTIME_AUTHORITY,
                required=snapshot.purpose
                in {
                    "consider_autonomous_life",
                    "consider_activity_attention",
                    "consider_activity_internal_work",
                    "consider_sleep",
                    "perform_subject_self_check",
                },
                relevance=95,
                source_kind="activity_summary",
            )
            if snapshot.purpose != "consider_other_human_input"
            else _unavailable(profile, ContextSection.ACTIVITY, "activities"),
            _item(
                profile,
                ContextSection.ACTIVITY,
                "current_activity",
                snapshot.opportunity_source_ref,
                snapshot.opportunity_source_version,
                snapshot.activity_summary_bytes,
                ContextTrustClass.RUNTIME_AUTHORITY,
                required=snapshot.purpose
                in {"consider_activity_attention", "consider_activity_internal_work"},
                relevance=100,
                source_kind=snapshot.opportunity_source_kind,
            )
            if snapshot.purpose != "consider_other_human_input"
            else _unavailable(profile, ContextSection.ACTIVITY, "activity"),
            _item(
                profile,
                ContextSection.CAPABILITY,
                "web_search_availability",
                UUID("01985d00-0000-7000-8000-000000000034"),
                1,
                rfc8785.dumps(
                    {
                        "binding": "armi.model-tool.volcengine-ark-web-search-v1",
                        "implementation_status": "complete",
                        "activation_status": "active"
                        if web_search_active
                        else "inactive",
                        "operation_class": "search_read_public",
                    }
                ),
                ContextTrustClass.POLICY,
                required=False,
                relevance=60,
            ),
            _item(
                profile,
                ContextSection.CAPABILITY,
                "capability_catalog",
                UUID("01985d00-0000-7000-8000-000000000027"),
                2,
                _capability_catalog_bytes(capability_states),
                ContextTrustClass.POLICY,
                required=True,
                relevance=70,
            ),
            _item(
                profile,
                ContextSection.PROMPT,
                "fixed_prompt",
                snapshot.fixed_prompt.source_id,
                snapshot.fixed_prompt.source_version,
                prompt_bytes,
                ContextTrustClass.POLICY,
                required=True,
                relevance=100,
            ),
            (
                _unavailable(profile, ContextSection.PROMPT, "creator_prompt")
                if snapshot.creator_prompt is None or creator_prompt_bytes is None
                else _item(
                    profile,
                    ContextSection.PROMPT,
                    "creator_prompt",
                    snapshot.creator_prompt.source_id,
                    snapshot.creator_prompt.source_version,
                    creator_prompt_bytes,
                    ContextTrustClass.POLICY,
                    required=False,
                    relevance=90,
                )
            ),
            (
                _unavailable(profile, ContextSection.PROMPT, "subject_prompt")
                if snapshot.subject_prompt is None or subject_prompt_bytes is None
                else _item(
                    profile,
                    ContextSection.PROMPT,
                    "subject_prompt",
                    snapshot.subject_prompt.source_id,
                    snapshot.subject_prompt.source_version,
                    subject_prompt_bytes,
                    ContextTrustClass.POLICY,
                    required=False,
                    relevance=95,
                    source_kind="subject_prompt",
                )
            ),
        )
    )
    items = [item for item in items if profile.allows(item.item_kind)]
    if snapshot.evidence is not None:
        items.append(
            _item(
                profile,
                ContextSection.EVIDENCE,
                (
                    "codex_task_source"
                    if snapshot.evidence.source_kind == "codex_task_source"
                    else "current_evidence"
                ),
                snapshot.evidence.source_id,
                snapshot.evidence.source_version,
                cast(bytes, evidence_bytes),
                (
                    ContextTrustClass.RUNTIME_AUTHORITY
                    if snapshot.evidence.source_kind == "life_query_result"
                    else ContextTrustClass.EXTERNAL_CLAIM
                ),
                required=True,
                relevance=100,
                source_kind=snapshot.evidence.source_kind,
            )
        )
    if snapshot.outreach_trigger_bytes is not None:
        items.append(
            _item(
                profile,
                ContextSection.EVIDENCE,
                "current_evidence",
                snapshot.opportunity_source_ref,
                snapshot.opportunity_source_version,
                snapshot.outreach_trigger_bytes,
                ContextTrustClass.RUNTIME_AUTHORITY,
                required=True,
                relevance=100,
                source_kind=snapshot.opportunity_source_kind,
            )
        )
    dialogue_purpose = snapshot.purpose in {
        "consider_creator_input",
        "consider_life_query_result",
        "consider_other_human_input",
    }
    required_content_bytes = sum(
        len(item.content.encode("utf-8"))
        for item in items
        if item.required and item.content is not None
    )
    return ContextRequest(
        Purpose(snapshot.purpose),
        snapshot.subject_id,
        snapshot.scene_id,
        snapshot.subject_version,
        snapshot.state_epoch,
        snapshot.bundle_activation_id,
        snapshot.policy_version,
        snapshot.mechanism_identity,
        32,
        262_144,
        max(16_384, required_content_bytes + 8192) if dialogue_purpose else 524_288,
        tuple(items),
    )


def _item(
    profile: ContextAssemblyProfile,
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
    return _candidate(
        profile,
        section,
        kind,
        ContextSourceIdentity(
            source_kind or kind,
            source_id,
            version,
        ),
        trust,
        "private",
        content,
        requested_required=required,
        relevance=relevance,
    )


def _unavailable(
    profile: ContextAssemblyProfile,
    section: ContextSection,
    kind: str,
    *,
    reason: str = "CTX-SOURCE-NOT-IMPLEMENTED",
) -> ContextItemCandidate:
    policy = profile.candidate_policy(kind, requested_required=False)
    if policy.requirement is ContextRequirement.REQUIRED:
        raise ContextViolation("CTX-SOURCE-MISSING")
    return ContextItemCandidate(
        section,
        kind,
        ContextSourceIdentity("not_implemented", None, None),
        ContextTrustClass.RUNTIME_AUTHORITY,
        "private",
        None,
        ContextRequirement.OPTIONAL,
        policy.layer,
        0,
        unavailable_reason=reason,
    )


def _candidate(
    profile: ContextAssemblyProfile,
    section: ContextSection,
    kind: str,
    source: ContextSourceIdentity,
    trust: ContextTrustClass,
    privacy_scope: str,
    content: str,
    *,
    requested_required: bool,
    relevance: int,
    business_time: Instant | None = None,
) -> ContextItemCandidate:
    policy = profile.candidate_policy(
        kind,
        requested_required=requested_required,
    )
    return ContextItemCandidate(
        section,
        kind,
        source,
        trust,
        privacy_scope,
        content,
        policy.requirement,
        policy.layer,
        relevance,
        business_time,
    )


def _capability_catalog_bytes(
    capability_states: tuple[tuple[UUID, int, bytes, str], ...],
) -> bytes:
    try:
        capabilities = [json.loads(item[2]) for item in capability_states]
        return rfc8785.dumps(
            {
                "schema_version": "armi.capability-catalog.v2",
                "runtime_discovery_allowed": False,
                "capabilities": capabilities,
            }
        )
    except UnicodeDecodeError, json.JSONDecodeError, TypeError:
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
    activity_read: ActivityReadPort,
    memory_read: MemoryReadPort,
    memory_projection: MemoryProjectionPort,
    material_projection: MaterialProjectionPort,
    relationship_read: RelationshipReadPort,
    sleep_read: SleepReadPort,
    web_search_active: bool = False,
    wakeups: WorkWakeupBus | None = None,
    diagnostic: Diagnostic | None = None,
    credential_port: CredentialPort | None = None,
    embedding_credential_locator: CredentialLocator | None = None,
) -> ContextPipeline:
    factory = PostgreSQLUnitOfWorkFactory(
        conninfo,
        environment_id=environment_id,
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
        activity_read=activity_read,
        memory_read=memory_read,
        memory_projection=memory_projection,
        material_projection=material_projection,
        relationship_read=relationship_read,
        sleep_read=sleep_read,
        web_search_active=web_search_active,
        wakeups=wakeups,
        diagnostic=diagnostic,
        embedding=(
            VolcengineArkEmbeddingAdapter(
                binding=load_embedding_binding(),
                credential_port=credential_port,
                locator=embedding_credential_locator,
            )
            if credential_port is not None and embedding_credential_locator is not None
            else None
        ),
    )


__all__ = ("ContextPipeline", "build_context_pipeline")
