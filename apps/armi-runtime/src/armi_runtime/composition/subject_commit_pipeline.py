"""Production M0-S026 T-03 subject commit pipeline."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import cast
from uuid import UUID, uuid7

from armi_activity.api import (
    ActivityCognitionPort,
    ActivityCommitPort,
    CandidateActivityDecisionDraft,
    CandidateActivityDraft,
)
from armi_artifact_store.api import ArtifactCatalogPort
from armi_artifact_store.content_store import ContentAddressedArtifactStore
from armi_artifact_store.life_material_codec import (
    build_life_material_artifact,
)
from armi_attention.api import OpportunityTransitionPort
from armi_capability.api import CapabilityCommitPort, CapabilityReadPort
from armi_codex.api import CodexCommitPort
from armi_cognition.api import (
    CognitionSubjectCommitPort,
    SubjectChangeSet,
    SubjectChangeSetCodec,
)
from armi_context.api import ContextProjectionInvalidationPort
from armi_data_rights.api import DataRightsSubjectCommitGate
from armi_evidence.api import EvidenceReadPort, EvidenceWritePort
from armi_expression.api import (
    CreatorReplyDraft,
    ExpressionCommitPort,
    OtherHumanReplyDraft,
)
from armi_interaction.api import (
    InteractionSubjectCommitPort,
    SceneKey,
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
    CreatorEventViolation,
    CreatorProjectionInvalidation,
    CreatorProjectionNotifier,
    CreatorResourceKind,
    PublishedArtifact,
    SubjectCommitResult,
    SubjectCommitViolation,
    WorkLease,
    WorkViolation,
)
from armi_kernel.contracts import ContractViolation, Digest, Instant, Purpose, SubjectId
from armi_material.api import (
    CandidateLifeMaterialDraft,
    MaterialCognitionPort,
    MaterialCommitPort,
)
from armi_memory.api import (
    CandidateMemoryDraft,
    CandidateMemoryRevisionDraft,
    MemoryCognitionPort,
    MemoryCommitPort,
)
from armi_mood.api import CandidateMoodDraft, MoodCognitionPort, MoodCommitPort
from armi_prompt.api import CandidatePromptDraft, PromptCognitionPort, PromptCommitPort
from armi_relationship.api import (
    CandidateRelationshipDraft,
    RelationshipCognitionPort,
    RelationshipCommitPort,
)
from armi_sleep.api import (
    CandidateMaintenanceDecisionDraft,
    CandidateSleepDecisionDraft,
    SleepCognitionPort,
    SleepCommitPort,
)
from armi_subject_state.api import (
    CandidateSubjectStateDraft,
    SubjectStateCognitionPort,
    SubjectStateCommitPort,
)
from armi_web_observation.api import WebResearchCommitPort, WebResearchRequestDraft

from armi_runtime.adapters.persistence.durable_work import PostgreSQLDurableWorkGateway
from armi_runtime.adapters.persistence.subject_commit import (
    PostgreSQLSubjectCommitRepository,
    SubjectCommitOwnerDrafts,
    SubjectCommitSnapshot,
)
from armi_runtime.adapters.persistence.unit_of_work import (
    PostgreSQLUnitOfWork,
    PostgreSQLUnitOfWorkFactory,
)
from armi_runtime.adapters.transaction_errors import (
    DatabaseFailureKind,
    DatabaseTransactionError,
)

from .work_wakeup import (
    EFFECT_REGISTER,
    EXACT_LIFE_QUERY,
    OPPORTUNITY_AVAILABLE,
    RESPONSE_ADMIT,
    SUBJECT_COMMIT,
    WorkWakeupBus,
)

_WORK_KIND = "cognition.subject.commit"
_LEASE_SECONDS = 30
Diagnostic = Callable[[str], None]
FaultInjector = Callable[[str], None]


def _ignore_diagnostic(_event: str) -> None:
    return None


class SubjectCommitPipeline:
    """Apply validated ChangeSets through the sole T-03 coordinator."""

    __slots__ = (
        "_activity_cognition",
        "_catalog",
        "_change_set_codec",
        "_diagnostic",
        "_factory",
        "_fault_injector",
        "_lease_owner",
        "_material_cognition",
        "_memory_cognition",
        "_mood_cognition",
        "_notifier",
        "_prompt_cognition",
        "_relationship_cognition",
        "_repository",
        "_sleep_cognition",
        "_stop",
        "_storage",
        "_subject_state_cognition",
        "_wakeups",
        "_work",
    )

    def __init__(
        self,
        *,
        factory: PostgreSQLUnitOfWorkFactory,
        change_set_codec: SubjectChangeSetCodec,
        storage: ContentAddressedArtifactStore,
        catalog: ArtifactCatalogPort,
        activity_cognition: ActivityCognitionPort,
        activity_commit: ActivityCommitPort,
        capability_commit: CapabilityCommitPort,
        capability_read: CapabilityReadPort,
        codex_commit: CodexCommitPort,
        cognition_commit: CognitionSubjectCommitPort,
        context_projections: ContextProjectionInvalidationPort,
        data_rights: DataRightsSubjectCommitGate,
        evidence: EvidenceWritePort,
        evidence_read: EvidenceReadPort,
        expression_commit: ExpressionCommitPort,
        interaction_commit: InteractionSubjectCommitPort,
        memory_commit: MemoryCommitPort,
        memory_cognition: MemoryCognitionPort,
        mood_commit: MoodCommitPort,
        opportunity_transition: OpportunityTransitionPort,
        mood_cognition: MoodCognitionPort,
        prompt_cognition: PromptCognitionPort,
        prompt_commit: PromptCommitPort,
        material_cognition: MaterialCognitionPort,
        material_commit: MaterialCommitPort,
        relationship_cognition: RelationshipCognitionPort,
        relationship_commit: RelationshipCommitPort,
        sleep_cognition: SleepCognitionPort,
        sleep_commit: SleepCommitPort,
        subject_state_cognition: SubjectStateCognitionPort,
        subject_state_commit: SubjectStateCommitPort,
        web_research_commit: WebResearchCommitPort,
        notifier: CreatorProjectionNotifier | None,
        wakeups: WorkWakeupBus | None = None,
        diagnostic: Diagnostic | None = None,
        fault_injector: FaultInjector | None = None,
    ) -> None:
        self._factory = factory
        self._change_set_codec = change_set_codec
        self._activity_cognition = activity_cognition
        self._catalog = catalog
        self._storage = storage
        self._notifier = notifier
        self._memory_cognition = memory_cognition
        self._mood_cognition = mood_cognition
        self._prompt_cognition = prompt_cognition
        self._material_cognition = material_cognition
        self._relationship_cognition = relationship_cognition
        self._sleep_cognition = sleep_cognition
        self._subject_state_cognition = subject_state_cognition
        self._repository = PostgreSQLSubjectCommitRepository(
            activity_commit,
            capability_commit,
            capability_read,
            codex_commit,
            cognition_commit,
            context_projections,
            data_rights,
            evidence,
            evidence_read,
            expression_commit,
            memory_commit,
            mood_commit,
            opportunity_transition,
            interaction_commit,
            self._catalog,
            prompt_commit,
            material_commit,
            relationship_commit,
            sleep_commit,
            subject_state_commit,
            web_research_commit,
        )
        self._work = PostgreSQLDurableWorkGateway(factory)
        self._lease_owner = uuid7()
        self._stop = asyncio.Event()
        self._wakeups = wakeups or WorkWakeupBus()
        self._diagnostic = diagnostic or _ignore_diagnostic
        self._fault_injector = fault_injector or _ignore_diagnostic

    async def open(self) -> None:
        await self._storage.prepare()

    async def close(self) -> None:
        self._stop.set()

    def stop(self) -> None:
        self._stop.set()

    async def commit_once(self) -> bool:
        snapshot: SubjectCommitSnapshot | None = None
        episode_id: UUID | None = None
        try:
            records = await self._work.claim(
                work_kind=_WORK_KIND,
                lease_owner=self._lease_owner,
                lease_seconds=_LEASE_SECONDS,
                limit=1,
            )
        except WorkViolation:
            raise SubjectCommitViolation("SUBJECT-DATABASE") from None
        if not records:
            return False
        lease = cast(WorkLease, records[0].lease)
        try:
            owner = records[0].draft.owner
            if owner.kind != "cognitive_episode":
                raise SubjectCommitViolation("SUBJECT-WORK-OWNER")
            episode_id = owner.reference
            snapshot = await self._snapshot(lease, episode_id)
            change_set = self._change_set_codec.decode(await self._read(snapshot))
            snapshot = self._bind_accepted_owner_payloads(snapshot, change_set)
            owner_drafts = self._decode_owner_drafts(change_set)
            replies = tuple(
                item
                for item in change_set.action_choices
                if isinstance(item, (CreatorReplyDraft, OtherHumanReplyDraft))
            )
            if len(replies) > 1:
                raise SubjectCommitViolation("SUBJECT-RESPONSE-COUNT")
            published_reply = (
                await self._publish_response(replies[0], snapshot) if replies else None
            )
            research_requests = change_set.web_research_requests
            if len(research_requests) > 1:
                raise SubjectCommitViolation("SUBJECT-WEB-RESEARCH-COUNT")
            published_research = (
                await self._publish_research(research_requests[0], snapshot)
                if research_requests
                else None
            )
            material_drafts = owner_drafts.material
            published_materials: list[tuple[str, PublishedArtifact]] = []
            for material in material_drafts:
                if material.body_bytes is None:
                    continue
                published_materials.append(
                    (
                        material.proposal_ref,
                        await self._publish_material(material.body_bytes, snapshot),
                    )
                )
            prompt_drafts = owner_drafts.prompt
            published_prompts = [
                (
                    prompt.proposal_ref,
                    await self._publish_prompt(prompt.content_bytes, snapshot),
                )
                for prompt in prompt_drafts
            ]
            async with self._factory.unit_of_work() as unit_of_work:
                response_artifact = None
                research_artifact = None
                material_artifacts: dict[str, ArtifactRef] = {}
                prompt_artifacts: dict[str, ArtifactRef] = {}
                if published_reply is not None:
                    registration = await self._catalog.register(
                        unit_of_work,
                        ArtifactId(uuid7()),
                        published_reply,
                    )
                    response_artifact = registration.ref
                    if registration.inserted:
                        await unit_of_work.audit.append(
                            _response_artifact_audit(
                                unit_of_work,
                                registration.ref,
                                snapshot,
                            )
                        )
                if published_research is not None:
                    research_registration = await self._catalog.register(
                        unit_of_work,
                        ArtifactId(uuid7()),
                        published_research,
                    )
                    research_artifact = research_registration.ref
                    if research_registration.inserted:
                        await unit_of_work.audit.append(
                            _research_artifact_audit(
                                unit_of_work,
                                research_registration.ref,
                                snapshot,
                            )
                        )
                for proposal_ref, published_material in published_materials:
                    try:
                        material_registration = await self._catalog.register(
                            unit_of_work,
                            ArtifactId(uuid7()),
                            published_material,
                        )
                    except ArtifactViolation:
                        raise SubjectCommitViolation(
                            "SUBJECT-MATERIAL-ARTIFACT"
                        ) from None
                    material_artifacts[proposal_ref] = material_registration.ref
                    if material_registration.inserted:
                        await unit_of_work.audit.append(
                            _material_artifact_audit(
                                unit_of_work,
                                material_registration.ref,
                                snapshot,
                            )
                        )
                for proposal_ref, published_prompt in published_prompts:
                    try:
                        prompt_registration = await self._catalog.register(
                            unit_of_work,
                            ArtifactId(uuid7()),
                            published_prompt,
                        )
                    except ArtifactViolation:
                        raise SubjectCommitViolation(
                            "SUBJECT-PROMPT-ARTIFACT"
                        ) from None
                    prompt_artifacts[proposal_ref] = prompt_registration.ref
                    if prompt_registration.inserted:
                        await unit_of_work.audit.append(
                            _prompt_artifact_audit(
                                unit_of_work,
                                prompt_registration.ref,
                                snapshot,
                            )
                        )
                self._fault_injector("subject_before_cas")
                result = await self._repository.settle(
                    unit_of_work,
                    lease=lease,
                    snapshot=snapshot,
                    change_set=change_set,
                    owner_drafts=owner_drafts,
                    response_artifact=response_artifact,
                    research_artifact=research_artifact,
                    material_artifacts=material_artifacts,
                    prompt_artifacts=prompt_artifacts,
                )
            self._wake_downstream()
            await self._notify(snapshot, result)
            return True
        except SubjectCommitViolation as error:
            if error.code == "SUBJECT-WORK-STALE":
                self._diagnostic("subject_commit.work.stale")
                return True
            if error.code in {"SUBJECT-HEAD-STALE", "SUBJECT-CAS-STALE"}:
                if snapshot is not None:
                    await self._settle_stale(lease, snapshot)
                return True
            await self._fail(lease, episode_id, error.code)
            return True
        except ArtifactViolation:
            await self._fail(lease, episode_id, "SUBJECT-RESPONSE-ARTIFACT")
            return True
        except DatabaseTransactionError as error:
            if error.code == "DB-TX-COMMIT-UNKNOWN" and snapshot is not None:
                recovered = await self._recover_committed(snapshot)
                if recovered is not None:
                    self._wake_downstream()
                    await self._notify(snapshot, recovered)
                    return True
                self._diagnostic("subject_commit.commit.outcome_unknown")
                return True
            if error.retryable_work:
                await self._release(lease, error.code)
            elif error.kind is DatabaseFailureKind.DEPENDENCY:
                self._diagnostic(
                    f"subject_commit.settlement.deferred.{error.code.lower()}"
                )
            else:
                await self._fail(lease, episode_id, error.code)
            return True
        except WorkViolation as error:
            self._diagnostic(
                f"subject_commit.worker.transient_failure.{error.code.lower()}"
            )
            return True

    async def run_worker(self) -> None:
        observed = self._wakeups.version(SUBJECT_COMMIT)
        while not self._stop.is_set():
            try:
                worked = await self.commit_once()
            except SubjectCommitViolation:
                if not self._stop.is_set():
                    self._diagnostic("subject_commit.worker.failed")
                worked = False
            if worked:
                await asyncio.sleep(0)
                continue
            observed = await self._wakeups.wait(
                SUBJECT_COMMIT,
                observed,
                stop=self._stop,
                timeout_seconds=1,
            )

    def _wake_downstream(self) -> None:
        self._wakeups.notify(RESPONSE_ADMIT)
        self._wakeups.notify(OPPORTUNITY_AVAILABLE)
        self._wakeups.notify(EXACT_LIFE_QUERY)
        self._wakeups.notify(EFFECT_REGISTER)

    async def _snapshot(
        self, lease: WorkLease, episode_id: UUID
    ) -> SubjectCommitSnapshot:
        try:
            async with self._factory.unit_of_work() as unit_of_work:
                return await self._repository.snapshot(unit_of_work, lease, episode_id)
        except DatabaseTransactionError:
            raise SubjectCommitViolation("SUBJECT-DATABASE") from None

    async def _read(self, snapshot: SubjectCommitSnapshot) -> bytes:
        value = b""
        try:
            stream = await self._storage.open_verified(snapshot.change_set_artifact)
            async with stream:
                value = await stream.read()
        except ArtifactViolation, ContractViolation, OSError:
            raise SubjectCommitViolation("SUBJECT-CHANGE-SET-ARTIFACT") from None
        if not value:
            raise SubjectCommitViolation("SUBJECT-CHANGE-SET-ARTIFACT")
        return value

    def _decode_owner_drafts(
        self, change_set: SubjectChangeSet
    ) -> SubjectCommitOwnerDrafts:
        activity: list[CandidateActivityDraft | CandidateActivityDecisionDraft] = []
        material: list[CandidateLifeMaterialDraft] = []
        memory: list[CandidateMemoryDraft | CandidateMemoryRevisionDraft] = []
        mood: list[CandidateMoodDraft] = []
        prompt: list[CandidatePromptDraft] = []
        relationship: list[CandidateRelationshipDraft] = []
        sleep: list[
            CandidateSleepDecisionDraft | CandidateMaintenanceDecisionDraft
        ] = []
        subject_state: list[CandidateSubjectStateDraft] = []
        for item in change_set.owner_drafts:
            if item.owner == "activity":
                activity.append(self._activity_cognition.decode(item.canonical_payload))
            elif item.owner == "material":
                material.append(self._material_cognition.decode(item.canonical_payload))
            elif item.owner == "memory":
                memory.append(self._memory_cognition.decode(item.canonical_payload))
            elif item.owner == "mood":
                mood.append(self._mood_cognition.decode(item.canonical_payload))
            elif item.owner == "prompt":
                prompt.append(self._prompt_cognition.decode(item.canonical_payload))
            elif item.owner == "relationship":
                relationship.append(
                    self._relationship_cognition.decode_change_set(
                        item.canonical_payload
                    )
                )
            elif item.owner == "sleep":
                sleep.append(self._sleep_cognition.decode(item.canonical_payload))
            elif item.owner in {"self", "mind", "life_mode"}:
                subject_state.append(
                    self._subject_state_cognition.decode(item.canonical_payload)
                )
            else:
                raise SubjectCommitViolation("SUBJECT-CANDIDATE-OWNER")
        return SubjectCommitOwnerDrafts(
            tuple(activity),
            tuple(material),
            tuple(memory),
            tuple(mood),
            tuple(prompt),
            tuple(relationship),
            tuple(sleep),
            tuple(subject_state),
        )

    @staticmethod
    def _bind_accepted_owner_payloads(
        snapshot: SubjectCommitSnapshot, change_set: SubjectChangeSet
    ) -> SubjectCommitSnapshot:
        payloads = {
            (item.proposal_ref, item.owner): item.canonical_payload
            for item in change_set.owner_drafts
        }
        return replace(
            snapshot,
            accepted_candidates=tuple(
                replace(
                    item,
                    canonical_payload=payload,
                    payload_digest=Digest.from_bytes(payload),
                )
                if (payload := payloads.get((item.proposal_ref, item.owner_identity)))
                is not None
                else item
                for item in snapshot.accepted_candidates
            ),
        )

    async def _fail(self, lease: WorkLease, episode_id: UUID | None, code: str) -> None:
        if episode_id is None:
            self._diagnostic("subject_commit.settlement.deferred")
            return
        try:
            async with self._factory.unit_of_work() as unit_of_work:
                await self._repository.fail(
                    unit_of_work,
                    lease=lease,
                    episode_id=episode_id,
                    code=code,
                )
                self._wake_downstream()
        except DatabaseTransactionError, SubjectCommitViolation, WorkViolation:
            self._diagnostic("subject_commit.settlement.deferred")

    async def _release(self, lease: WorkLease, code: str) -> None:
        try:
            async with self._factory.unit_of_work() as unit_of_work:
                row = await (
                    await unit_of_work._connection_for_repository().execute(  # pyright: ignore[reportPrivateUsage]
                        "SELECT statement_timestamp()"
                    )
                ).fetchone()
                if row is None:
                    return
                await unit_of_work.work.release(
                    lease,
                    not_before=Instant(row[0]),
                    error_code=code,
                )
        except DatabaseTransactionError, SubjectCommitViolation, WorkViolation:
            self._diagnostic("subject_commit.settlement.deferred")

    async def _settle_stale(
        self,
        lease: WorkLease,
        snapshot: SubjectCommitSnapshot,
    ) -> None:
        try:
            async with self._factory.unit_of_work() as unit_of_work:
                result = await self._repository.settle_stale(
                    unit_of_work,
                    lease=lease,
                    snapshot=snapshot,
                )
            self._wake_downstream()
            await self._notify(snapshot, result)
        except DatabaseTransactionError, SubjectCommitViolation, WorkViolation:
            self._diagnostic("subject_commit.stale_settlement.deferred")

    async def _publish_response(
        self,
        reply: CreatorReplyDraft | OtherHumanReplyDraft,
        snapshot: SubjectCommitSnapshot,
    ):
        staged = await self._storage.stage(
            _one_chunk(reply.content_bytes),
            ArtifactPolicy(
                "text/plain",
                (
                    "other-human.response.text"
                    if isinstance(reply, OtherHumanReplyDraft)
                    else "creator.response.text"
                ),
                "subject.commit",
                snapshot.trace_id,
                ArtifactPrivacyScope.PRIVATE,
            ),
        )
        return await self._storage.publish(staged)

    async def _publish_research(
        self,
        request: WebResearchRequestDraft,
        snapshot: SubjectCommitSnapshot,
    ):
        staged = await self._storage.stage(
            _one_chunk(request.query_bytes),
            ArtifactPolicy(
                "text/plain",
                "web.research.query",
                "subject.commit",
                snapshot.trace_id,
                ArtifactPrivacyScope.PRIVATE,
            ),
        )
        return await self._storage.publish(staged)

    async def _publish_material(
        self, body_bytes: bytes, snapshot: SubjectCommitSnapshot
    ) -> PublishedArtifact:
        try:
            content = build_life_material_artifact(body_bytes)
            staged = await self._storage.stage(
                _one_chunk(content),
                ArtifactPolicy(
                    "application/json",
                    "life.material.content",
                    "subject.commit",
                    snapshot.trace_id,
                    ArtifactPrivacyScope.PRIVATE,
                ),
            )
            return await self._storage.publish(staged)
        except ValueError, ArtifactViolation:
            raise SubjectCommitViolation("SUBJECT-MATERIAL-ARTIFACT") from None

    async def _publish_prompt(
        self, content_bytes: bytes, snapshot: SubjectCommitSnapshot
    ) -> PublishedArtifact:
        try:
            staged = await self._storage.stage(
                _one_chunk(content_bytes),
                ArtifactPolicy(
                    "application/json",
                    "subject.prompt.content",
                    "subject.commit",
                    snapshot.trace_id,
                    ArtifactPrivacyScope.PRIVATE,
                ),
            )
            return await self._storage.publish(staged)
        except ArtifactViolation:
            raise SubjectCommitViolation("SUBJECT-PROMPT-ARTIFACT") from None

    async def _recover_committed(
        self, snapshot: SubjectCommitSnapshot
    ) -> SubjectCommitResult | None:
        try:
            async with self._factory.unit_of_work(read_only=True) as unit_of_work:
                return await self._repository.existing_result(
                    unit_of_work, snapshot.validation_id
                )
        except DatabaseTransactionError:
            return None

    async def _notify(
        self, snapshot: SubjectCommitSnapshot, result: SubjectCommitResult
    ) -> None:
        if self._notifier is None:
            return
        now = Instant(datetime.now(UTC))
        invalidations = [
            CreatorProjectionInvalidation(
                CreatorResourceKind("operation"),
                str(snapshot.root_opportunity_id),
                now,
                "creator-operation.v2",
            )
        ]
        if result.subject_commit_id is not None:
            if snapshot.scene_key is not None:
                invalidations.append(
                    CreatorProjectionInvalidation(
                        CreatorResourceKind("scene_timeline"),
                        SceneKey(snapshot.scene_key).value,
                        now,
                        "scene-timeline.v5",
                    )
                )
            invalidations.append(
                CreatorProjectionInvalidation(
                    CreatorResourceKind("subject_summary"),
                    str(snapshot.subject_id),
                    now,
                    "subject-summary.v1",
                )
            )
            try:
                async with self._factory.unit_of_work(read_only=True) as unit_of_work:
                    request_ids = await self._repository.capability_request_ids(
                        unit_of_work, result.subject_commit_id
                    )
                invalidations.extend(
                    CreatorProjectionInvalidation(
                        CreatorResourceKind("capability_request"),
                        str(request_id),
                        now,
                        "capability-request.v4",
                    )
                    for request_id in request_ids
                )
            except DatabaseTransactionError:
                self._diagnostic("subject_commit.notification.lookup_failed")
        try:
            async with self._factory.unit_of_work(read_only=True) as unit_of_work:
                activity_ids = await self._repository.affected_activity_ids(
                    unit_of_work, snapshot.validation_id
                )
            invalidations.extend(
                CreatorProjectionInvalidation(
                    CreatorResourceKind("activity"),
                    str(activity_id),
                    now,
                    "creator-activity.v1",
                )
                for activity_id in activity_ids
            )
        except DatabaseTransactionError:
            self._diagnostic("subject_commit.activity_notification.lookup_failed")
        try:
            async with self._factory.unit_of_work(read_only=True) as unit_of_work:
                memory_ids = await self._repository.affected_memory_ids(
                    unit_of_work,
                    snapshot.validation_id,
                )
            invalidations.extend(
                CreatorProjectionInvalidation(
                    CreatorResourceKind("memory"),
                    str(memory_id),
                    now,
                    "creator-memory.v1",
                )
                for memory_id in memory_ids
            )
        except DatabaseTransactionError:
            self._diagnostic("subject_commit.memory_notification.lookup_failed")
        try:
            async with self._factory.unit_of_work(read_only=True) as unit_of_work:
                material_ids = await self._repository.affected_material_ids(
                    unit_of_work,
                    snapshot.validation_id,
                )
            invalidations.extend(
                CreatorProjectionInvalidation(
                    CreatorResourceKind("material"),
                    str(material_id),
                    now,
                    "life-record-query.v2",
                )
                for material_id in material_ids
            )
        except DatabaseTransactionError:
            self._diagnostic("subject_commit.material_notification.lookup_failed")
        try:
            async with self._factory.unit_of_work(read_only=True) as unit_of_work:
                relationship_ids = await self._repository.affected_relationship_ids(
                    unit_of_work,
                    snapshot.validation_id,
                )
            invalidations.extend(
                CreatorProjectionInvalidation(
                    CreatorResourceKind("relationship"),
                    str(relationship_id),
                    now,
                    "creator-relationship.v2",
                )
                for relationship_id in relationship_ids
            )
        except DatabaseTransactionError:
            self._diagnostic("subject_commit.relationship_notification.lookup_failed")
        try:
            async with self._factory.unit_of_work(read_only=True) as unit_of_work:
                maintenance_ids = (
                    await self._repository.affected_maintenance_session_ids(
                        unit_of_work,
                        snapshot.validation_id,
                    )
                )
            invalidations.extend(
                CreatorProjectionInvalidation(
                    CreatorResourceKind("maintenance"),
                    str(session_id),
                    now,
                    "creator-maintenance.v2",
                )
                for session_id in maintenance_ids
            )
        except DatabaseTransactionError:
            self._diagnostic("subject_commit.maintenance_notification.lookup_failed")
        for invalidation in invalidations:
            try:
                await self._notifier.notify(invalidation)
            except CreatorEventViolation:
                self._diagnostic("subject_commit.notification.failed")


def build_subject_commit_pipeline(
    factory: PostgreSQLUnitOfWorkFactory,
    *,
    data_root: Path,
    max_object_bytes: int,
    catalog: ArtifactCatalogPort,
    change_set_codec: SubjectChangeSetCodec,
    activity_cognition: ActivityCognitionPort,
    activity_commit: ActivityCommitPort,
    capability_commit: CapabilityCommitPort,
    capability_read: CapabilityReadPort,
    codex_commit: CodexCommitPort,
    cognition_commit: CognitionSubjectCommitPort,
    context_projections: ContextProjectionInvalidationPort,
    data_rights: DataRightsSubjectCommitGate,
    evidence: EvidenceWritePort,
    evidence_read: EvidenceReadPort,
    expression_commit: ExpressionCommitPort,
    interaction_commit: InteractionSubjectCommitPort,
    memory_commit: MemoryCommitPort,
    memory_cognition: MemoryCognitionPort,
    mood_commit: MoodCommitPort,
    opportunity_transition: OpportunityTransitionPort,
    mood_cognition: MoodCognitionPort,
    prompt_cognition: PromptCognitionPort,
    prompt_commit: PromptCommitPort,
    material_cognition: MaterialCognitionPort,
    material_commit: MaterialCommitPort,
    relationship_cognition: RelationshipCognitionPort,
    relationship_commit: RelationshipCommitPort,
    sleep_cognition: SleepCognitionPort,
    sleep_commit: SleepCommitPort,
    subject_state_cognition: SubjectStateCognitionPort,
    subject_state_commit: SubjectStateCommitPort,
    web_research_commit: WebResearchCommitPort,
    notifier: CreatorProjectionNotifier | None,
    wakeups: WorkWakeupBus | None = None,
    diagnostic: Diagnostic | None = None,
    fault_injector: FaultInjector | None = None,
) -> SubjectCommitPipeline:
    return SubjectCommitPipeline(
        factory=factory,
        storage=ContentAddressedArtifactStore(
            data_root / "artifacts", max_object_bytes=max_object_bytes
        ),
        catalog=catalog,
        change_set_codec=change_set_codec,
        activity_cognition=activity_cognition,
        activity_commit=activity_commit,
        capability_commit=capability_commit,
        capability_read=capability_read,
        codex_commit=codex_commit,
        cognition_commit=cognition_commit,
        context_projections=context_projections,
        data_rights=data_rights,
        evidence=evidence,
        evidence_read=evidence_read,
        expression_commit=expression_commit,
        interaction_commit=interaction_commit,
        memory_commit=memory_commit,
        memory_cognition=memory_cognition,
        mood_commit=mood_commit,
        opportunity_transition=opportunity_transition,
        mood_cognition=mood_cognition,
        prompt_cognition=prompt_cognition,
        prompt_commit=prompt_commit,
        material_cognition=material_cognition,
        material_commit=material_commit,
        relationship_cognition=relationship_cognition,
        relationship_commit=relationship_commit,
        sleep_cognition=sleep_cognition,
        sleep_commit=sleep_commit,
        subject_state_cognition=subject_state_cognition,
        subject_state_commit=subject_state_commit,
        web_research_commit=web_research_commit,
        notifier=notifier,
        wakeups=wakeups,
        diagnostic=diagnostic,
        fault_injector=fault_injector,
    )


__all__ = ("SubjectCommitPipeline", "build_subject_commit_pipeline")


def _response_artifact_audit(
    unit_of_work: PostgreSQLUnitOfWork,
    ref: ArtifactRef,
    snapshot: SubjectCommitSnapshot,
) -> AuditDraft:
    return AuditDraft(
        AuditEventId(uuid7()),
        AuditReference("runtime", unit_of_work.environment_id),
        Purpose("cognition.response"),
        "artifact.catalog.registered",
        AuditReference("artifact", ref.artifact_id.value),
        AuditResultStatus.APPLIED,
        snapshot.trace_id,
        AuditSensitivity.RESTRICTED,
        subject_id=SubjectId(snapshot.subject_id),
        request=AuditReference("cognitive_episode", snapshot.episode_id),
    )


def _research_artifact_audit(
    unit_of_work: PostgreSQLUnitOfWork,
    ref: ArtifactRef,
    snapshot: SubjectCommitSnapshot,
) -> AuditDraft:
    return AuditDraft(
        AuditEventId(uuid7()),
        AuditReference("runtime", unit_of_work.environment_id),
        Purpose("public_web_research"),
        "artifact.catalog.registered",
        AuditReference("artifact", ref.artifact_id.value),
        AuditResultStatus.APPLIED,
        snapshot.trace_id,
        AuditSensitivity.RESTRICTED,
        subject_id=SubjectId(snapshot.subject_id),
        request=AuditReference("cognitive_episode", snapshot.episode_id),
    )


def _material_artifact_audit(
    unit_of_work: PostgreSQLUnitOfWork,
    ref: ArtifactRef,
    snapshot: SubjectCommitSnapshot,
) -> AuditDraft:
    return AuditDraft(
        AuditEventId(uuid7()),
        AuditReference("runtime", unit_of_work.environment_id),
        Purpose("life.material.write"),
        "artifact.catalog.registered",
        AuditReference("artifact", ref.artifact_id.value),
        AuditResultStatus.APPLIED,
        snapshot.trace_id,
        AuditSensitivity.RESTRICTED,
        subject_id=SubjectId(snapshot.subject_id),
        request=AuditReference("cognitive_episode", snapshot.episode_id),
    )


def _prompt_artifact_audit(
    unit_of_work: PostgreSQLUnitOfWork,
    ref: ArtifactRef,
    snapshot: SubjectCommitSnapshot,
) -> AuditDraft:
    return AuditDraft(
        AuditEventId(uuid7()),
        AuditReference("runtime", unit_of_work.environment_id),
        Purpose("subject.prompt.write"),
        "artifact.catalog.registered",
        AuditReference("artifact", ref.artifact_id.value),
        AuditResultStatus.APPLIED,
        snapshot.trace_id,
        AuditSensitivity.RESTRICTED,
        subject_id=SubjectId(snapshot.subject_id),
        request=AuditReference("cognitive_episode", snapshot.episode_id),
    )


async def _one_chunk(value: bytes) -> AsyncIterator[bytes]:
    yield value
