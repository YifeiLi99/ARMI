"""Production M0-S026 T-03 subject commit pipeline."""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid7

from armi_activity.api import (
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
from armi_codex.api import CodexCommitPort, CodexDelegationViolation
from armi_cognition.api import (
    CandidateFocusDraft,
    CognitionPreparedCandidate,
    CognitionSubjectCommitPort,
    FocusCommitPort,
    SubjectChangeSet,
)
from armi_context.api import ContextProjectionInvalidationPort
from armi_data_rights.api import DataRightsSubjectCommitGate
from armi_evidence.api import EvidenceReadPort
from armi_experience.api import ExperienceCommitPort
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
    ArtifactPublication,
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
    SubjectCommitResult,
    SubjectCommitViolation,
    WorkLease,
    WorkViolation,
)
from armi_kernel.contracts import Digest, Instant, Purpose, SubjectId, TraceId
from armi_live_vision.api import VisualObservationCommitPort
from armi_live_voice.api import (
    LiveVoiceViolation,
    VoiceActivityState,
    VoiceCognitionResultPort,
)
from armi_material.api import (
    CandidateLifeMaterialDraft,
    MaterialCommitPort,
)
from armi_memory.api import (
    CandidateMemoryDraft,
    CandidateMemoryRevisionDraft,
    MemoryCommitPort,
)
from armi_prompt.api import CandidatePromptDraft, PromptCommitPort
from armi_relationship.api import (
    CandidateRelationshipDraft,
    RelationshipCommitPort,
)
from armi_sleep.api import (
    CandidateMaintenanceDecisionDraft,
    CandidateSleepDecisionDraft,
    SleepCommitPort,
)
from armi_subject_state.api import (
    CandidateSubjectStateDraft,
    SubjectStateCommitPort,
)

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
    DatabaseTransactionError,
)

from .work_wakeup import (
    EXACT_LIFE_QUERY,
    OPPORTUNITY_AVAILABLE,
    WorkWakeupBus,
)

Diagnostic = Callable[[str], None]
FaultInjector = Callable[[str], None]


def _ignore_diagnostic(_event: str) -> None:
    return None


class SubjectCommitPipeline:
    """Apply validated ChangeSets through the sole T-03 coordinator."""

    __slots__ = (
        "_catalog",
        "_codex_commit",
        "_diagnostic",
        "_factory",
        "_fault_injector",
        "_notifier",
        "_repository",
        "_storage",
        "_voice_results",
        "_wakeups",
    )

    def __init__(
        self,
        *,
        factory: PostgreSQLUnitOfWorkFactory,
        storage: ContentAddressedArtifactStore,
        catalog: ArtifactCatalogPort,
        activity_commit: ActivityCommitPort,
        codex_commit: CodexCommitPort,
        cognition_commit: CognitionSubjectCommitPort,
        experience_commit: ExperienceCommitPort,
        context_projections: ContextProjectionInvalidationPort,
        data_rights: DataRightsSubjectCommitGate,
        evidence_read: EvidenceReadPort,
        expression_commit: ExpressionCommitPort,
        interaction_commit: InteractionSubjectCommitPort,
        memory_commit: MemoryCommitPort,
        opportunity_transition: OpportunityTransitionPort,
        prompt_commit: PromptCommitPort,
        material_commit: MaterialCommitPort,
        relationship_commit: RelationshipCommitPort,
        sleep_commit: SleepCommitPort,
        subject_state_commit: SubjectStateCommitPort,
        focus_commit: FocusCommitPort,
        visual_observation_commit: VisualObservationCommitPort,
        notifier: CreatorProjectionNotifier | None,
        voice_results: VoiceCognitionResultPort | None = None,
        voice_activity_state: VoiceActivityState | None = None,
        wakeups: WorkWakeupBus | None = None,
        diagnostic: Diagnostic | None = None,
        fault_injector: FaultInjector | None = None,
    ) -> None:
        self._factory = factory
        self._codex_commit = codex_commit
        self._catalog = catalog
        self._storage = storage
        self._notifier = notifier
        self._voice_results = voice_results
        self._repository = PostgreSQLSubjectCommitRepository(
            activity_commit,
            codex_commit,
            cognition_commit,
            experience_commit,
            context_projections,
            data_rights,
            evidence_read,
            expression_commit,
            memory_commit,
            opportunity_transition,
            interaction_commit,
            self._catalog,
            prompt_commit,
            material_commit,
            relationship_commit,
            sleep_commit,
            subject_state_commit,
            focus_commit,
            visual_observation_commit,
            voice_activity_state=voice_activity_state,
        )
        self._wakeups = wakeups or WorkWakeupBus()
        self._diagnostic = diagnostic or _ignore_diagnostic
        self._fault_injector = fault_injector or _ignore_diagnostic

    async def submit(
        self, lease: WorkLease, candidate: CognitionPreparedCandidate
    ) -> None:
        snapshot: SubjectCommitSnapshot | None = None
        episode_id = candidate.episode_id
        change_set = candidate.result.change_set
        has_reply = False
        awaits_followup = False
        try:
            if change_set is None:
                async with self._factory.unit_of_work() as unit_of_work:
                    await candidate.record(unit_of_work, lease)
                self._wake_downstream()
                return
            owner_drafts = self.collect_owner_drafts(change_set)
            replies = tuple(
                item
                for item in change_set.action_choices
                if isinstance(item, (CreatorReplyDraft, OtherHumanReplyDraft))
            )
            if len(replies) > 1:
                raise SubjectCommitViolation("SUBJECT-RESPONSE-COUNT")
            has_reply = bool(replies)
            published_reply = (
                await self._publish_response(replies[0], candidate.trace_id)
                if replies
                else None
            )
            awaits_followup = bool(
                change_set.exact_life_queries or change_set.visual_observation_requests
            )
            material_drafts = owner_drafts.material
            prepared_codex = (
                await self._codex_commit.prepare_tasks(
                    delegations=change_set.codex_delegations,
                    storage=self._storage,
                    trace_id=candidate.trace_id,
                )
                if any(
                    item.new_task is not None for item in change_set.codex_delegations
                )
                else ()
            )
            published_materials: list[tuple[str, ArtifactPublication]] = []
            for material in material_drafts:
                if material.body_bytes is None:
                    continue
                published_materials.append(
                    (
                        material.proposal_ref,
                        await self._publish_material(
                            material.body_bytes, candidate.trace_id
                        ),
                    )
                )
            prompt_drafts = owner_drafts.prompt
            published_prompts = [
                (
                    prompt.proposal_ref,
                    await self._publish_prompt(
                        prompt.content_bytes, candidate.trace_id
                    ),
                )
                for prompt in prompt_drafts
            ]
            async with self._factory.unit_of_work() as unit_of_work:
                await candidate.record(unit_of_work, lease)
                snapshot = await self._repository.snapshot(
                    unit_of_work,
                    lease,
                    episode_id,
                    accepted_candidates=candidate.accepted_candidates,
                )
                snapshot = self._bind_accepted_owner_payloads(snapshot, change_set)
                response_artifact = None
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
                    prepared_codex=prepared_codex,
                    material_artifacts=material_artifacts,
                    prompt_artifacts=prompt_artifacts,
                )
            self._wake_downstream()
            await self._notify(snapshot, result)
            await self._notify_voice(
                snapshot,
                has_reply=has_reply,
                awaits_followup=awaits_followup,
            )
            return
        except SubjectCommitViolation as error:
            if error.code == "SUBJECT-WORK-STALE":
                self._diagnostic("subject_commit.work.stale")
                return
            if error.code in {"SUBJECT-HEAD-STALE", "SUBJECT-CAS-STALE"}:
                if snapshot is not None:
                    await self._settle_stale(lease, snapshot, candidate)
                return
            raise
        except CodexDelegationViolation as error:
            raise SubjectCommitViolation(f"SUBJECT-{error.code}") from None
        except ArtifactViolation:
            raise SubjectCommitViolation("SUBJECT-RESPONSE-ARTIFACT") from None
        except DatabaseTransactionError as error:
            if error.code == "DB-TX-COMMIT-UNKNOWN" and snapshot is not None:
                recovered = await self._recover_committed(snapshot)
                if recovered is not None:
                    self._wake_downstream()
                    await self._notify(snapshot, recovered)
                    await self._notify_voice(
                        snapshot,
                        has_reply=has_reply,
                        awaits_followup=awaits_followup,
                    )
                    return
                self._diagnostic("subject_commit.commit.outcome_unknown")
                return
            raise
        except WorkViolation as error:
            self._diagnostic(
                f"subject_commit.worker.transient_failure.{error.code.lower()}"
            )
            return

    def _wake_downstream(self) -> None:
        self._wakeups.notify(OPPORTUNITY_AVAILABLE)
        self._wakeups.notify(EXACT_LIFE_QUERY)

    async def _notify_voice(
        self,
        snapshot: SubjectCommitSnapshot,
        *,
        has_reply: bool,
        awaits_followup: bool,
    ) -> None:
        if self._voice_results is None:
            return
        try:
            await self._voice_results.committed(
                root_opportunity_id=snapshot.root_opportunity_id,
                has_reply=has_reply,
                awaits_followup=awaits_followup,
            )
        except LiveVoiceViolation:
            self._diagnostic("subject_commit.voice_result.failed")

    @staticmethod
    def collect_owner_drafts(change_set: SubjectChangeSet) -> SubjectCommitOwnerDrafts:
        activity: list[CandidateActivityDraft | CandidateActivityDecisionDraft] = []
        material: list[CandidateLifeMaterialDraft] = []
        memory: list[CandidateMemoryDraft | CandidateMemoryRevisionDraft] = []
        prompt: list[CandidatePromptDraft] = []
        relationship: list[CandidateRelationshipDraft] = []
        sleep: list[
            CandidateSleepDecisionDraft | CandidateMaintenanceDecisionDraft
        ] = []
        subject_state: list[CandidateSubjectStateDraft] = []
        focus: list[CandidateFocusDraft] = []
        for item in change_set.owner_drafts:
            value = item.candidate
            if item.owner == "activity" and isinstance(
                value, (CandidateActivityDraft, CandidateActivityDecisionDraft)
            ):
                activity.append(value)
            elif item.owner == "material" and isinstance(
                value, CandidateLifeMaterialDraft
            ):
                material.append(value)
            elif item.owner == "memory" and isinstance(
                value, (CandidateMemoryDraft, CandidateMemoryRevisionDraft)
            ):
                memory.append(value)
            elif item.owner == "prompt" and isinstance(value, CandidatePromptDraft):
                prompt.append(value)
            elif item.owner == "relationship" and isinstance(
                value, CandidateRelationshipDraft
            ):
                relationship.append(value)
            elif item.owner == "sleep" and isinstance(
                value, (CandidateSleepDecisionDraft, CandidateMaintenanceDecisionDraft)
            ):
                sleep.append(value)
            elif item.owner == "focus" and isinstance(value, CandidateFocusDraft):
                focus.append(value)
            elif item.owner in {"self", "life_mode"} and isinstance(
                value, CandidateSubjectStateDraft
            ):
                subject_state.append(value)
            else:
                raise SubjectCommitViolation("SUBJECT-CANDIDATE-OWNER")
        return SubjectCommitOwnerDrafts(
            tuple(activity),
            tuple(material),
            tuple(memory),
            tuple(prompt),
            tuple(relationship),
            tuple(sleep),
            tuple(subject_state),
            tuple(focus),
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

    async def _settle_stale(
        self,
        lease: WorkLease,
        snapshot: SubjectCommitSnapshot,
        candidate: CognitionPreparedCandidate,
    ) -> None:
        try:
            async with self._factory.unit_of_work() as unit_of_work:
                await candidate.record(unit_of_work, lease)
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
        trace_id: TraceId,
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
                trace_id,
                ArtifactPrivacyScope.PRIVATE,
            ),
        )
        return await self._storage.publish(staged)

    async def _publish_material(
        self, body_bytes: bytes, trace_id: TraceId
    ) -> ArtifactPublication:
        try:
            content = build_life_material_artifact(body_bytes)
            staged = await self._storage.stage(
                _one_chunk(content),
                ArtifactPolicy(
                    "application/json",
                    "life.material.content",
                    "subject.commit",
                    trace_id,
                    ArtifactPrivacyScope.PRIVATE,
                ),
            )
            return await self._storage.publish(staged)
        except ValueError, ArtifactViolation:
            raise SubjectCommitViolation("SUBJECT-MATERIAL-ARTIFACT") from None

    async def _publish_prompt(
        self, content_bytes: bytes, trace_id: TraceId
    ) -> ArtifactPublication:
        try:
            staged = await self._storage.stage(
                _one_chunk(content_bytes),
                ArtifactPolicy(
                    "application/json",
                    "subject.prompt.content",
                    "subject.commit",
                    trace_id,
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
                "creator-operation",
            )
        ]
        if result.subject_commit_id is not None:
            if snapshot.scene_key is not None:
                invalidations.append(
                    CreatorProjectionInvalidation(
                        CreatorResourceKind("scene_timeline"),
                        SceneKey(snapshot.scene_key).value,
                        now,
                        "scene-timeline",
                    )
                )
            invalidations.append(
                CreatorProjectionInvalidation(
                    CreatorResourceKind("subject_summary"),
                    str(snapshot.subject_id),
                    now,
                    "subject-summary",
                )
            )
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
                    "creator-activity",
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
                    "creator-memory",
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
                    "life-record-query",
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
                    "creator-relationship",
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
                    "creator-maintenance",
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
    orphan_grace_seconds: int,
    catalog: ArtifactCatalogPort,
    activity_commit: ActivityCommitPort,
    codex_commit: CodexCommitPort,
    cognition_commit: CognitionSubjectCommitPort,
    experience_commit: ExperienceCommitPort,
    context_projections: ContextProjectionInvalidationPort,
    data_rights: DataRightsSubjectCommitGate,
    evidence_read: EvidenceReadPort,
    expression_commit: ExpressionCommitPort,
    interaction_commit: InteractionSubjectCommitPort,
    memory_commit: MemoryCommitPort,
    opportunity_transition: OpportunityTransitionPort,
    prompt_commit: PromptCommitPort,
    material_commit: MaterialCommitPort,
    relationship_commit: RelationshipCommitPort,
    sleep_commit: SleepCommitPort,
    subject_state_commit: SubjectStateCommitPort,
    focus_commit: FocusCommitPort,
    visual_observation_commit: VisualObservationCommitPort,
    notifier: CreatorProjectionNotifier | None,
    voice_results: VoiceCognitionResultPort | None = None,
    voice_activity_state: VoiceActivityState | None = None,
    wakeups: WorkWakeupBus | None = None,
    diagnostic: Diagnostic | None = None,
    fault_injector: FaultInjector | None = None,
) -> SubjectCommitPipeline:
    return SubjectCommitPipeline(
        factory=factory,
        storage=ContentAddressedArtifactStore(
            data_root / "artifacts",
            max_object_bytes=max_object_bytes,
            publication_catalog=catalog,
            publication_uow_factory=factory,
            orphan_grace_seconds=orphan_grace_seconds,
        ),
        catalog=catalog,
        activity_commit=activity_commit,
        codex_commit=codex_commit,
        cognition_commit=cognition_commit,
        experience_commit=experience_commit,
        context_projections=context_projections,
        data_rights=data_rights,
        evidence_read=evidence_read,
        expression_commit=expression_commit,
        interaction_commit=interaction_commit,
        memory_commit=memory_commit,
        opportunity_transition=opportunity_transition,
        prompt_commit=prompt_commit,
        material_commit=material_commit,
        relationship_commit=relationship_commit,
        sleep_commit=sleep_commit,
        subject_state_commit=subject_state_commit,
        focus_commit=focus_commit,
        visual_observation_commit=visual_observation_commit,
        notifier=notifier,
        voice_results=voice_results,
        voice_activity_state=voice_activity_state,
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
