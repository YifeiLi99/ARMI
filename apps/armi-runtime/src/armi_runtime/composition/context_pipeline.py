"""Production S023 opportunity selection and Context preparation."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Callable
from pathlib import Path
from typing import cast
from uuid import UUID, uuid7

import rfc8785
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
    ContextSection,
    ContextSourceIdentity,
    ContextTrustClass,
    ContextViolation,
    OpportunitySelector,
    RuntimeFence,
    WorkLease,
    WorkViolation,
)
from armi_kernel.contracts import Instant, Purpose, SubjectId

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
        policy_version: str = CONTEXT_POLICY_VERSION,
        web_search_active: bool = False,
        wakeups: WorkWakeupBus | None = None,
        diagnostic: Diagnostic | None = None,
    ) -> None:
        self._factory = factory
        self._storage = storage
        self._policy_version = policy_version
        self._web_search_active = web_search_active
        self._repository = PostgreSQLContextRepository()
        self._catalog = ArtifactCatalogRepository()
        self._compiler = DeterministicContextCompiler()
        self._work = PostgreSQLDurableWorkGateway(factory)
        self._lease_owner = uuid7()
        self._stop = asyncio.Event()
        self._wakeups = wakeups or WorkWakeupBus()
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
            )
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
        if snapshot.purpose == "consider_other_human_input" and kind != "self":
            continue
        items.append(
            ContextItemCandidate(
                section_by_component[kind],
                kind,
                ContextSourceIdentity(kind, source_id, version),
                ContextTrustClass.SUBJECTIVE_STATE,
                "private",
                payload.decode("utf-8"),
                kind == "self"
                or (
                    snapshot.purpose == "perform_subject_self_check"
                    and kind in {"self", "mind"}
                ),
                90,
            )
        )
    if snapshot.scene_id is not None:
        items.append(
            _item(
                ContextSection.SCENE,
                "current_scene",
                snapshot.scene_id,
                1,
                cast(bytes, snapshot.scene_bytes),
                ContextTrustClass.RUNTIME_AUTHORITY,
                required=snapshot.purpose == "consider_creator_outreach",
                relevance=80,
            )
        )
        for source, payload in recent_scene_payloads:
            items.append(
                ContextItemCandidate(
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
                    False,
                    88,
                    Instant(source.occurred_at),
                )
            )
    accessible_memories = tuple(
        item
        for item in snapshot.memory_payloads
        if item[3] in {"available", "faded"}
        and snapshot.purpose != "perform_subject_self_check"
        and snapshot.purpose != "consider_other_human_input"
    )
    if accessible_memories:
        for memory_id, version, payload, accessibility in accessible_memories:
            items.append(
                ContextItemCandidate(
                    ContextSection.MEMORY,
                    "current_memory",
                    ContextSourceIdentity("subjective_memory", memory_id, version),
                    ContextTrustClass.SUBJECTIVE_STATE,
                    "private",
                    payload.decode("utf-8"),
                    False,
                    85 if accessibility == "available" else 70,
                )
            )
    else:
        items.append(
            _unavailable(
                ContextSection.MEMORY,
                "memory",
                reason=(
                    "CTX-MEMORY-NOT-RECALLABLE"
                    if snapshot.has_memory_records
                    else "CTX-MEMORY-NONE"
                ),
            )
        )
    if material_payloads and snapshot.purpose != "consider_other_human_input":
        for source, payload in material_payloads:
            items.append(
                ContextItemCandidate(
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
                    False,
                    82,
                )
            )
    else:
        items.append(
            _unavailable(
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
            ContextItemCandidate(
                ContextSection.CAPABILITY,
                f"capability_state_{authorization_status}",
                ContextSourceIdentity("capability_state", capability_id, version),
                ContextTrustClass.RUNTIME_AUTHORITY,
                "private",
                payload.decode("utf-8", errors="strict"),
                snapshot.purpose
                in {"consider_creator_input", "consider_creator_outreach"},
                100 if authorization_status == "pending" else 96,
            )
        )
    if snapshot.relationship_payloads:
        for relationship_id, version, payload in snapshot.relationship_payloads:
            items.append(
                ContextItemCandidate(
                    ContextSection.RELATIONSHIP,
                    "current_relationship",
                    ContextSourceIdentity("relationship", relationship_id, version),
                    ContextTrustClass.SUBJECTIVE_STATE,
                    "private",
                    payload.decode("utf-8"),
                    False,
                    96,
                )
            )
    else:
        items.append(
            _unavailable(
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
                ContextItemCandidate(
                    ContextSection.RELATIONSHIP,
                    "current_relationship_commitment",
                    ContextSourceIdentity(
                        "relationship_commitment", commitment_id, version
                    ),
                    ContextTrustClass.SUBJECTIVE_STATE,
                    "private",
                    payload.decode("utf-8"),
                    False,
                    92 if status == "active" else 80,
                )
            )
    else:
        items.append(
            _unavailable(
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
            ContextItemCandidate(
                ContextSection.RELATIONSHIP,
                "current_relationship_issue",
                ContextSourceIdentity("relationship_issue", issue_id, version),
                ContextTrustClass.SUBJECTIVE_STATE,
                "private",
                payload.decode("utf-8"),
                False,
                90,
            )
        )
    items.extend(
        (
            _item(
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
            else _unavailable(ContextSection.LIFE_MODE, "maintenance_window"),
            _item(
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
            else _unavailable(ContextSection.LIFE_MODE, "maintenance_phase"),
            _item(
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
            else _unavailable(ContextSection.ACTIVITY, "activities"),
            _item(
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
            else _unavailable(ContextSection.ACTIVITY, "activity"),
            _item(
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
                _unavailable(ContextSection.PROMPT, "creator_prompt")
                if snapshot.purpose == "consider_other_human_input"
                or snapshot.creator_prompt is None
                or creator_prompt_bytes is None
                else _item(
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
                _unavailable(ContextSection.PROMPT, "subject_prompt")
                if snapshot.subject_prompt is None or subject_prompt_bytes is None
                else _item(
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
    if snapshot.evidence is not None:
        items.append(
            _item(
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
        ),
        trust,
        "private",
        content,
        required,
        relevance,
    )


def _unavailable(
    section: ContextSection,
    kind: str,
    *,
    reason: str = "CTX-SOURCE-NOT-IMPLEMENTED",
) -> ContextItemCandidate:
    return ContextItemCandidate(
        section,
        kind,
        ContextSourceIdentity("not_implemented", None, None),
        ContextTrustClass.RUNTIME_AUTHORITY,
        "private",
        None,
        False,
        0,
        unavailable_reason=reason,
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
    web_search_active: bool = False,
    wakeups: WorkWakeupBus | None = None,
    diagnostic: Diagnostic | None = None,
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
        web_search_active=web_search_active,
        wakeups=wakeups,
        diagnostic=diagnostic,
    )


__all__ = ("ContextPipeline", "build_context_pipeline")
