"""Production S023 opportunity selection and Context preparation."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from typing import Any, cast
from uuid import UUID, uuid7

import rfc8785
from armi_activity.api import ActivityReadPort
from armi_artifact_store import (
    ContentAddressedArtifactStore,
    parse_life_material_artifact,
)
from armi_attention.api import (
    OpportunityCognitionSelectionPort,
    OpportunityContextReadPort,
)
from armi_capability.api import CapabilityReadPort
from armi_codex.api import CodexTaskSourceReadPort
from armi_effect.api import EffectOperationReadPort
from armi_evidence.api import EvidenceReadPort
from armi_expression.api import ExpressionIntentReadPort
from armi_interaction.api import InteractionContextReadPort
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
    DurableWorkPort,
    ModelViolation,
    WorkLease,
    WorkViolation,
)
from armi_kernel.contracts import Instant, Purpose, SubjectId
from armi_material.api import MaterialProjectionPort
from armi_memory.api import MemoryProjectionPort, MemoryReadPort
from armi_mood.api import MoodReadPort
from armi_prompt.api import PromptReadPort
from armi_relationship.api import RelationshipReadPort
from armi_runtime_foundation import (
    PostgreSQLRuntimeUnitOfWork,
    PostgreSQLRuntimeUnitOfWorkFactory,
    RuntimeTransactionFailure,
)
from armi_sleep.api import SleepReadPort
from armi_subject_state.api import SubjectStateReadPort

from ._compiler import CONTEXT_POLICY_VERSION, DeterministicContextCompiler
from ._embedding import QUERY_MAX_CHARS
from ._embedding_postgresql import PostgreSQLContextEmbeddingRepository, RecalledContext
from ._postgresql import (
    ContextArtifactSource,
    ContextEpisodeSnapshot,
    ContextMaterialSource,
    ContextSceneTurnSource,
    PostgreSQLContextRepository,
)
from ._profiles import ContextAssemblyProfile, context_profile
from .api import (
    ContextArtifactCatalogPort,
    ContextEpisodePort,
    ContextItemCandidate,
    ContextRequest,
    ContextRequirement,
    ContextRuntimeSubjectPort,
    ContextSection,
    ContextSelectionPort,
    ContextSourceIdentity,
    ContextTrustClass,
    ContextViolation,
    ContextWakeupPort,
    EmbeddingPort,
    RecallStatus,
)

CONTEXT_PREPARE = "cognition.context.prepare"
MODEL_INVOKE = "cognition.model.invoke"
OPPORTUNITY_AVAILABLE = "opportunity.available"
_WORK_KIND = "cognition.context.prepare"
Diagnostic = Callable[[str], None]


async def _one_chunk(value: bytes) -> AsyncIterator[bytes]:
    yield value


def _ignore_diagnostic(_event: str) -> None:
    return None


@dataclass(frozen=True, slots=True)
class _Pulse:
    version: int
    event: asyncio.Event


class _LocalWakeups:
    def __init__(self) -> None:
        self._pulses: dict[str, _Pulse] = {}

    def version(self, channel: str) -> int:
        return self._pulse(channel).version

    def notify(self, channel: str) -> None:
        current = self._pulse(channel)
        current.event.set()
        self._pulses[channel] = _Pulse(current.version + 1, asyncio.Event())

    async def wait(
        self,
        channel: str,
        after_version: int,
        *,
        stop: asyncio.Event,
        timeout_seconds: float,
    ) -> int:
        current = self._pulse(channel)
        if current.version != after_version or stop.is_set():
            return current.version
        pulse_wait = asyncio.create_task(current.event.wait())
        stop_wait = asyncio.create_task(stop.wait())
        try:
            await asyncio.wait(
                (pulse_wait, stop_wait),
                timeout=timeout_seconds,
                return_when=asyncio.FIRST_COMPLETED,
            )
        finally:
            for task in (pulse_wait, stop_wait):
                if not task.done():
                    task.cancel()
            await asyncio.gather(pulse_wait, stop_wait, return_exceptions=True)
        return self.version(channel)

    def _pulse(self, channel: str) -> _Pulse:
        current = self._pulses.get(channel)
        if current is None:
            current = _Pulse(0, asyncio.Event())
            self._pulses[channel] = current
        return current


class ContextPipeline:
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
        factory: PostgreSQLRuntimeUnitOfWorkFactory,
        storage: ContentAddressedArtifactStore,
        catalog: ContextArtifactCatalogPort,
        work: DurableWorkPort,
        activity_read: ActivityReadPort,
        capability_read: CapabilityReadPort,
        memory_read: MemoryReadPort,
        memory_projection: MemoryProjectionPort,
        mood_read: MoodReadPort,
        prompt_read: PromptReadPort,
        material_projection: MaterialProjectionPort,
        relationship_read: RelationshipReadPort,
        sleep_read: SleepReadPort,
        subject_state_read: SubjectStateReadPort,
        selection: ContextSelectionPort,
        episodes: ContextEpisodePort,
        runtime_subjects: ContextRuntimeSubjectPort,
        opportunity_context: OpportunityContextReadPort,
        opportunity_transitions: OpportunityCognitionSelectionPort,
        evidence_read: EvidenceReadPort,
        interaction_context: InteractionContextReadPort,
        expression_read: ExpressionIntentReadPort,
        effect_read: EffectOperationReadPort,
        codex_read: CodexTaskSourceReadPort,
        policy_version: str = CONTEXT_POLICY_VERSION,
        web_search_active: bool = False,
        wakeups: ContextWakeupPort | None = None,
        diagnostic: Diagnostic | None = None,
        embedding: EmbeddingPort | None = None,
    ) -> None:
        self._factory = factory
        self._storage = storage
        self._policy_version = policy_version
        self._web_search_active = web_search_active
        self._repository = PostgreSQLContextRepository(
            relationship_read,
            sleep_read,
            activity_read,
            capability_read,
            memories=memory_read,
            mood=mood_read,
            prompts=prompt_read,
            subject_state=subject_state_read,
            catalog=catalog,
            selection=selection,
            episodes=episodes,
            subjects=runtime_subjects,
            opportunities=opportunity_context,
            opportunity_transitions=opportunity_transitions,
            evidence=evidence_read,
            interaction=interaction_context,
            expression=expression_read,
            effects=effect_read,
            codex=codex_read,
        )
        self._catalog = catalog
        self._compiler = DeterministicContextCompiler()
        self._work = work
        self._lease_owner = uuid7()
        self._stop = asyncio.Event()
        self._wakeups = wakeups or _LocalWakeups()
        self._diagnostic = diagnostic or _ignore_diagnostic
        self._embedding = embedding
        self._embedding_repository = PostgreSQLContextEmbeddingRepository(
            memory_projection, material_projection
        )

    async def open(self) -> None:
        try:
            await self._storage.prepare()
        except ArtifactViolation:
            raise ContextViolation("CTX-ARTIFACT") from None

    async def close(self) -> None:
        self._stop.set()

    def stop(self) -> None:
        self._stop.set()

    async def select_once(self) -> CognitiveEpisodeId | None:
        try:
            selected = await self._repository.select_one()
            if selected is not None:
                self._wakeups.notify(CONTEXT_PREPARE)
            return selected
        except ContextViolation:
            raise
        except RuntimeTransactionFailure, WorkViolation:
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
        record = claimed[0]
        lease = cast(WorkLease, record.lease)
        episode_id = record.draft.owner.reference
        if record.draft.owner.kind != "cognitive_episode":
            await self._fail_if_current(lease, episode_id, "CTX-WORK-STALE")
            return True
        try:
            snapshot = await self._snapshot(episode_id)
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
                    episode_id=episode_id,
                    result=result,
                    manifest_artifact=manifest_registration.ref,
                    compiled_artifact=compiled_registration.ref,
                )
            self._wakeups.notify(MODEL_INVOKE)
            return True
        except ContextViolation as error:
            await self._fail_if_current(lease, episode_id, error.code)
            return True
        except ArtifactViolation:
            await self._fail_if_current(lease, episode_id, "CTX-SOURCE-READ-FAILED")
            return True
        except RuntimeTransactionFailure, WorkViolation:
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

    async def _snapshot(self, episode_id: UUID) -> ContextEpisodeSnapshot:
        try:
            async with self._factory.unit_of_work(
                read_only=True,
            ) as unit_of_work:
                return await self._repository.snapshot(unit_of_work, episode_id)
        except RuntimeTransactionFailure:
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
        try:
            query = _semantic_recall_query(query_bytes)
            mood_gists = _active_mood_gists(snapshot.component_payloads)
            if mood_gists:
                query = "\n".join((query, *mood_gists)).strip()
            if not query:
                return RecalledContext(RecallStatus.UNAVAILABLE, (), (), False)
            vector = None
            if self._embedding is not None:
                try:
                    vector = (await self._embedding.embed_query(query)).vector
                except ModelViolation:
                    vector = None
            return await self._embedding_repository.recall_parallel(
                self._factory,
                subject_id=snapshot.subject_id,
                life_generation_id=snapshot.life_generation_id,
                query_text=query,
                query_vector=vector,
            )
        except UnicodeDecodeError, RuntimeTransactionFailure:
            return RecalledContext(RecallStatus.UNAVAILABLE, (), (), False)

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

    async def _fail_if_current(
        self, lease: WorkLease, episode_id: UUID, code: str
    ) -> None:
        try:
            async with self._factory.unit_of_work() as unit_of_work:
                await self._repository.fail(
                    unit_of_work,
                    lease=lease,
                    episode_id=episode_id,
                    code=code,
                )
        except ContextViolation, RuntimeTransactionFailure, WorkViolation:
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
        "mood": ContextSection.MOOD,
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
                    snapshot.purpose
                    in {
                        "perform_subject_self_check",
                        "reflect_prompt",
                    }
                    and kind in {"self", "mind"}
                ),
                relevance=90,
            )
        )
        if kind == "mood":
            for episode_id, episode_payload, intensity in _active_mood_episodes(
                payload
            ):
                items.append(
                    _candidate(
                        profile,
                        ContextSection.MOOD,
                        "active_affective_episode",
                        ContextSourceIdentity("mood_episode", episode_id, version),
                        ContextTrustClass.SUBJECTIVE_STATE,
                        "private",
                        episode_payload,
                        requested_required=False,
                        relevance=max(70, min(99, intensity)),
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
                item.source_ref,
                item.source_version,
                rfc8785.dumps(
                    {
                        "summary": item.text,
                        "accessibility": "recalled",
                    }
                ),
                "available",
                item.rank,
            )
            for item in recalled_context.memories
        )
    if accessible_memories:
        for memory_value in accessible_memories:
            memory_id, version, payload, accessibility = memory_value[:4]
            recall_rank = memory_value[4] if len(memory_value) == 5 else None
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
                    relevance=(
                        max(70, 94 - (int(recall_rank) - 1) * 4)
                        if recall_rank is not None
                        else (85 if accessibility == "available" else 70)
                    ),
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
    for experience in getattr(snapshot, "experience_context", ()):
        item_kind = (
            "maintenance_experience"
            if experience.maintenance_source
            else "recent_experience"
        )
        items.append(
            _candidate(
                profile,
                ContextSection.MEMORY,
                item_kind,
                ContextSourceIdentity(
                    "accepted_experience", experience.experience_id, 1
                ),
                ContextTrustClass.SUBJECTIVE_STATE,
                "private",
                rfc8785.dumps(
                    {
                        "schema_version": "armi.experience-context.v1",
                        "fact_class": experience.fact_class,
                        "first_person_gist": experience.first_person_gist,
                        "occurred_at": experience.occurred_at.isoformat(),
                        "accepted_at": experience.accepted_at.isoformat(),
                        "source_perspective": experience.source_perspective,
                        "uncertainty": experience.uncertainty,
                    }
                ).decode("utf-8"),
                requested_required=experience.maintenance_source,
                relevance=96 if experience.maintenance_source else 78,
                business_time=Instant(experience.accepted_at),
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
        for recalled_item in recalled_context.materials:
            items.append(
                _candidate(
                    profile,
                    ContextSection.MATERIAL,
                    "current_material",
                    ContextSourceIdentity(
                        "life_material",
                        recalled_item.source_ref,
                        recalled_item.source_version,
                    ),
                    ContextTrustClass.SUBJECTIVE_STATE,
                    "private",
                    rfc8785.dumps({"chunk": recalled_item.text}).decode("utf-8"),
                    requested_required=False,
                    relevance=max(70, 94 - (recalled_item.rank - 1) * 4),
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
                            else "dense_unavailable"
                            if not recalled_context.dense_available
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
                    "reflect_self",
                    "reflect_mind",
                    "reflect_mood",
                    "reflect_prompt",
                },
                relevance=100,
                source_kind=snapshot.opportunity_source_kind,
            )
            if snapshot.purpose
            in {
                "maintain_subjective_memory",
                "perform_subject_self_check",
                "reflect_self",
                "reflect_mind",
                "reflect_mood",
                "reflect_prompt",
            }
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
        evidence_content = cast(bytes, evidence_bytes)
        if snapshot.evidence.source_kind == "codex_task_source":
            evidence_content = _codex_task_source_content(
                snapshot.evidence,
                evidence_content,
            )
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
                evidence_content,
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


def _codex_task_source_content(
    source: ContextArtifactSource,
    content: bytes,
) -> bytes:
    if source.task_manifest_digest is None:
        raise ContextViolation("CTX-SOURCE-MISSING")
    try:
        value = json.loads(content)
    except UnicodeDecodeError, json.JSONDecodeError:
        raise ContextViolation("CTX-SOURCE-READ-FAILED") from None
    if type(value) is not dict or "task_manifest_digest" in value:
        raise ContextViolation("CTX-SOURCE-READ-FAILED")
    document = cast(dict[str, object], value)
    document["task_manifest_digest"] = source.task_manifest_digest.value
    try:
        return rfc8785.dumps(cast(Any, document))
    except TypeError, UnicodeEncodeError:
        raise ContextViolation("CTX-SOURCE-READ-FAILED") from None


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


_RECALL_TEXT_KEYS = frozenset(
    {
        "body",
        "content",
        "description",
        "gist",
        "goal",
        "kind",
        "message",
        "objective",
        "query",
        "reason",
        "summary",
        "text",
        "title",
        "topic",
        "trigger",
    }
)


def _active_mood_episodes(
    component_payloads: tuple[tuple[str, UUID, int, bytes], ...] | bytes,
) -> tuple[tuple[UUID, str, int], ...]:
    payloads = (
        (component_payloads,)
        if isinstance(component_payloads, bytes)
        else tuple(
            payload
            for kind, _source_id, _version, payload in component_payloads
            if kind == "mood"
        )
    )
    if not payloads:
        return ()
    try:
        document = json.loads(payloads[-1])
        if not isinstance(document, dict) or document.get("schema_version") != (
            "armi.mood-snapshot.v2"
        ):
            return ()
        raw_episodes = document.get("active_episodes")
        if not isinstance(raw_episodes, list):
            return ()
        result: list[tuple[UUID, str, int]] = []
        for raw in raw_episodes[:5]:
            if not isinstance(raw, dict):
                return ()
            episode_id = UUID(str(raw["episode_id"]))
            gist = str(raw["gist"])
            phase = str(raw["event_phase"])
            intensity = int(raw["intensity"])
            if (
                episode_id.version != 7
                or not gist.strip()
                or len(gist) > 64
                or phase not in {"anticipated", "ongoing", "realized", "averted"}
                or not 0 <= intensity <= 100
            ):
                return ()
            result.append(
                (
                    episode_id,
                    rfc8785.dumps(
                        {
                            "schema_version": "armi.active-affective-episode.v1",
                            "gist": gist,
                            "event_phase": phase,
                            "intensity": intensity,
                        }
                    ).decode("utf-8"),
                    intensity,
                )
            )
        return tuple(result)
    except KeyError, TypeError, ValueError, json.JSONDecodeError, UnicodeDecodeError:
        return ()


def _active_mood_gists(
    component_payloads: tuple[tuple[str, UUID, int, bytes], ...],
) -> tuple[str, ...]:
    remaining = 160
    result: list[str] = []
    for _episode_id, payload, intensity in _active_mood_episodes(component_payloads):
        if intensity < 20 or len(result) == 2 or remaining <= 0:
            continue
        gist = str(cast(dict[str, object], json.loads(payload))["gist"])
        piece = gist[:remaining]
        if piece:
            result.append(piece)
            remaining -= len(piece)
    return tuple(result)


def _semantic_recall_query(value: bytes) -> str:
    text = value.decode("utf-8", errors="strict").strip()
    if not text:
        return ""
    try:
        document: object = json.loads(text)
    except json.JSONDecodeError:
        return text[:QUERY_MAX_CHARS]
    parts: list[str] = []

    def visit(item: object, key: str | None = None) -> None:
        if sum(len(part) for part in parts) >= QUERY_MAX_CHARS:
            return
        if isinstance(item, dict):
            for nested_key, nested_value in cast(dict[object, object], item).items():
                if isinstance(nested_key, str):
                    visit(nested_value, nested_key.lower())
        elif isinstance(item, list):
            for nested_value in cast(list[object], item):
                visit(nested_value, key)
        elif key in _RECALL_TEXT_KEYS and isinstance(item, (str, int, float)):
            candidate = str(item).strip()
            if candidate and candidate not in parts:
                parts.append(candidate)

    visit(document)
    return "\n".join(parts)[:QUERY_MAX_CHARS]


def _artifact_audit(
    unit_of_work: PostgreSQLRuntimeUnitOfWork,
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


__all__ = ("ContextPipeline",)
