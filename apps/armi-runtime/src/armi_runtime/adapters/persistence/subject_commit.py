"""PostgreSQL owner for the T-03 subject commit transaction."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, cast
from uuid import UUID, uuid7

import rfc8785
from armi_activity.api import (
    ActivityCommitContext,
    ActivityCommitPort,
    ActivityViolation,
    CandidateActivityDecisionDraft,
    CandidateActivityDraft,
)
from armi_artifact_store.api import ArtifactCatalogPort
from armi_attention.api import LifeViolation, OpportunityTransitionPort
from armi_capability.api import (
    CapabilityAcceptedBasis,
    CapabilityCommitContext,
    CapabilityCommitPort,
    CapabilityReadPort,
    CapabilityViolation,
)
from armi_codex.api import (
    CodexCommitContext,
    CodexCommitPort,
    CodexDelegationViolation,
)
from armi_cognition.api import (
    CandidateExactLifeQueryDraft,
    CognitionAcceptedCandidate,
    CognitionApplicationDraft,
    CognitionEpisodeStatus,
    CognitionExactLifeQueryIntentDraft,
    CognitionSubjectCommitPort,
    SubjectChangeSet,
)
from armi_context.api import (
    ContextProjectionInvalidationPort,
    ContextProjectionSourceRef,
)
from armi_data_rights.api import DataRightsSubjectCommitGate
from armi_evidence.api import (
    EvidenceId,
    EvidenceReadPort,
    EvidenceViolation,
    EvidenceWritePort,
    ExperienceEvidenceLink,
)
from armi_experience.api import (
    AcceptedExperienceDraft,
    ExperienceCommitPort,
    ExperienceKind,
    ExperienceSourcePerspective,
)
from armi_expression.api import (
    ExpressionCommitContext,
    ExpressionCommitPort,
    ResponseViolation,
)
from armi_interaction.api import InteractionSubjectCommitPort, SceneQueryViolation
from armi_kernel.application import (
    ArtifactRef,
    AuditDraft,
    AuditEventId,
    AuditReference,
    AuditResultStatus,
    AuditSensitivity,
    CandidateApplicationId,
    CandidateApplicationStatus,
    CandidateDisposition,
    ExperienceId,
    RuntimeFence,
    SubjectCommitId,
    SubjectCommitResult,
    SubjectCommitViolation,
    WorkDraft,
    WorkId,
    WorkLease,
    WorkOwner,
    WorkPayloadRef,
    WorkResultRef,
)
from armi_kernel.contracts import (
    Digest,
    IdempotencyKey,
    Instant,
    Purpose,
    SubjectId,
    TraceId,
)
from armi_material.api import (
    CandidateLifeMaterialDraft,
    MaterialCommitPort,
    MaterialViolation,
)
from armi_memory.api import (
    CandidateMemoryDraft,
    CandidateMemoryRevisionDraft,
    MemoryCommitPort,
    MemoryExperienceSource,
    MemoryViolation,
)
from armi_mood.api import CandidateMoodDraft, MoodCommitPort, MoodViolation
from armi_prompt.api import CandidatePromptDraft, PromptCommitPort, PromptViolation
from armi_relationship.api import (
    CandidateRelationshipDraft,
    RelationshipCommitPort,
    RelationshipViolation,
)
from armi_sleep.api import (
    CandidateMaintenanceDecisionDraft,
    CandidateSleepDecisionDraft,
    SleepCommitContext,
    SleepCommitPort,
    SleepViolation,
)
from armi_subject_state.api import (
    CandidateSubjectStateDraft,
    SubjectStateCommitPort,
    SubjectStateViolation,
)
from armi_web_observation.api import (
    WebResearchCommitContext,
    WebResearchCommitPort,
    WebResearchViolation,
)

from .unit_of_work import PostgreSQLUnitOfWork

_WORK_KIND = "cognition.subject.commit"


@dataclass(frozen=True, slots=True)
class SubjectCommitSnapshot:
    validation_id: UUID
    episode_id: UUID
    subject_id: UUID
    generation_id: UUID
    activation_id: UUID
    opportunity_id: UUID
    root_opportunity_id: UUID
    reconsideration_no: int
    evidence_id: UUID | None
    scene_id: UUID | None
    scene_key: str | None
    creator_party_id: UUID | None
    other_party_id: UUID | None
    subject_party_id: UUID
    change_set_artifact: ArtifactRef
    base_subject_version: int
    base_state_epoch: int
    context_digest: Digest
    trace_id: TraceId
    opportunity_purpose: str
    source_kind: str
    source_ref: UUID
    source_version: int
    source_activity_id: UUID | None
    opportunity_available_after: datetime
    opportunity_expires_at: datetime | None
    accepted_candidates: tuple[CognitionAcceptedCandidate, ...]


@dataclass(frozen=True, slots=True)
class SubjectCommitOwnerDrafts:
    activity: tuple[CandidateActivityDraft | CandidateActivityDecisionDraft, ...]
    material: tuple[CandidateLifeMaterialDraft, ...]
    memory: tuple[CandidateMemoryDraft | CandidateMemoryRevisionDraft, ...]
    mood: tuple[CandidateMoodDraft, ...]
    prompt: tuple[CandidatePromptDraft, ...]
    relationship: tuple[CandidateRelationshipDraft, ...]
    sleep: tuple[CandidateSleepDecisionDraft | CandidateMaintenanceDecisionDraft, ...]
    subject_state: tuple[CandidateSubjectStateDraft, ...]


def _sleep_commit_context(snapshot: SubjectCommitSnapshot) -> SleepCommitContext:
    return SleepCommitContext(
        validation_id=snapshot.validation_id,
        episode_id=snapshot.episode_id,
        opportunity_id=snapshot.opportunity_id,
        root_opportunity_id=snapshot.root_opportunity_id,
        reconsideration_no=snapshot.reconsideration_no,
        subject_id=snapshot.subject_id,
        generation_id=snapshot.generation_id,
        opportunity_purpose=snapshot.opportunity_purpose,
        source_kind=snapshot.source_kind,
        source_ref=snapshot.source_ref,
        source_version=snapshot.source_version,
        base_state_epoch=snapshot.base_state_epoch,
        opportunity_available_after=snapshot.opportunity_available_after,
        opportunity_expires_at=snapshot.opportunity_expires_at,
    )


def _activity_commit_context(snapshot: SubjectCommitSnapshot) -> ActivityCommitContext:
    return ActivityCommitContext(
        snapshot.validation_id,
        snapshot.episode_id,
        snapshot.opportunity_id,
        snapshot.root_opportunity_id,
        snapshot.reconsideration_no,
        snapshot.subject_id,
        snapshot.scene_id,
        snapshot.opportunity_purpose,
        snapshot.source_ref,
        snapshot.source_version,
        snapshot.source_activity_id,
    )


def _expression_commit_context(
    snapshot: SubjectCommitSnapshot,
) -> ExpressionCommitContext:
    return ExpressionCommitContext(
        snapshot.validation_id,
        snapshot.episode_id,
        snapshot.opportunity_id,
        snapshot.root_opportunity_id,
        snapshot.subject_id,
        snapshot.generation_id,
        snapshot.scene_id,
        snapshot.creator_party_id,
        snapshot.other_party_id,
        snapshot.opportunity_purpose,
        snapshot.trace_id,
    )


def _capability_commit_context(
    snapshot: SubjectCommitSnapshot,
) -> CapabilityCommitContext:
    return CapabilityCommitContext(
        snapshot.validation_id,
        snapshot.episode_id,
        snapshot.subject_id,
        snapshot.scene_id,
        snapshot.creator_party_id,
        snapshot.trace_id,
        tuple(
            CapabilityAcceptedBasis(item.proposal_ref, item.basis_context_ids)
            for item in snapshot.accepted_candidates
            if item.owner_identity == "capability"
        ),
    )


def _web_research_commit_context(
    snapshot: SubjectCommitSnapshot,
) -> WebResearchCommitContext:
    return WebResearchCommitContext(
        snapshot.validation_id,
        snapshot.episode_id,
        snapshot.opportunity_id,
        snapshot.subject_id,
        snapshot.scene_id,
        snapshot.creator_party_id,
        snapshot.trace_id,
    )


def _codex_commit_context(snapshot: SubjectCommitSnapshot) -> CodexCommitContext:
    return CodexCommitContext(
        snapshot.validation_id,
        snapshot.episode_id,
        snapshot.root_opportunity_id,
        snapshot.subject_id,
        snapshot.scene_id,
        snapshot.creator_party_id,
        snapshot.trace_id,
    )


class PostgreSQLSubjectCommitRepository:
    """Read one validated ChangeSet and atomically apply or settle it."""

    __slots__ = (
        "_activity_commit",
        "_artifact_catalog",
        "_capability_commit",
        "_capability_read",
        "_codex_commit",
        "_cognition_commit",
        "_context_projections",
        "_data_rights",
        "_evidence",
        "_evidence_read",
        "_experience_commit",
        "_expression_commit",
        "_interaction_commit",
        "_material_commit",
        "_memory_commit",
        "_mood_commit",
        "_opportunity_transition",
        "_prompt_commit",
        "_relationship_commit",
        "_sleep_commit",
        "_subject_state_commit",
        "_web_research_commit",
    )

    def __init__(
        self,
        activity_commit: ActivityCommitPort,
        capability_commit: CapabilityCommitPort,
        capability_read: CapabilityReadPort,
        codex_commit: CodexCommitPort,
        cognition_commit: CognitionSubjectCommitPort,
        experience_commit: ExperienceCommitPort,
        context_projections: ContextProjectionInvalidationPort,
        data_rights: DataRightsSubjectCommitGate,
        evidence: EvidenceWritePort,
        evidence_read: EvidenceReadPort,
        expression_commit: ExpressionCommitPort,
        memory_commit: MemoryCommitPort,
        mood_commit: MoodCommitPort,
        opportunity_transition: OpportunityTransitionPort,
        interaction_commit: InteractionSubjectCommitPort,
        artifact_catalog: ArtifactCatalogPort,
        prompt_commit: PromptCommitPort,
        material_commit: MaterialCommitPort,
        relationship_commit: RelationshipCommitPort,
        sleep_commit: SleepCommitPort,
        subject_state_commit: SubjectStateCommitPort,
        web_research_commit: WebResearchCommitPort,
    ) -> None:
        self._activity_commit = activity_commit
        self._capability_commit = capability_commit
        self._capability_read = capability_read
        self._codex_commit = codex_commit
        self._cognition_commit = cognition_commit
        self._experience_commit = experience_commit
        self._context_projections = context_projections
        self._data_rights = data_rights
        self._evidence = evidence
        self._evidence_read = evidence_read
        self._expression_commit = expression_commit
        self._memory_commit = memory_commit
        self._mood_commit = mood_commit
        self._opportunity_transition = opportunity_transition
        self._interaction_commit = interaction_commit
        self._artifact_catalog = artifact_catalog
        self._prompt_commit = prompt_commit
        self._material_commit = material_commit
        self._relationship_commit = relationship_commit
        self._sleep_commit = sleep_commit
        self._subject_state_commit = subject_state_commit
        self._web_research_commit = web_research_commit

    async def settle_stale(
        self,
        unit_of_work: PostgreSQLUnitOfWork,
        *,
        lease: WorkLease,
        snapshot: SubjectCommitSnapshot,
    ) -> SubjectCommitResult:
        connection = unit_of_work._connection_for_repository()  # pyright: ignore[reportPrivateUsage]
        await _assert_lease(connection, lease, snapshot.episode_id)
        row = await (
            await connection.execute(
                """
                SELECT subject_version
                FROM armi.subjects
                WHERE singleton_key = 1 AND subject_id = %s
                FOR UPDATE
                """,
                (snapshot.subject_id,),
            )
        ).fetchone()
        if row is None:
            raise SubjectCommitViolation("SUBJECT-IDENTITY")
        return await self._settle_stale(
            unit_of_work,
            lease=lease,
            snapshot=snapshot,
            observed_version=int(row[0]),
        )

    async def fail(
        self,
        unit_of_work: PostgreSQLUnitOfWork,
        *,
        lease: WorkLease,
        episode_id: UUID,
        code: str,
    ) -> None:
        """Terminally settle a current subject-commit attempt and its episode."""

        connection = unit_of_work._connection_for_repository()  # pyright: ignore[reportPrivateUsage]
        await _assert_lease(connection, lease, episode_id)
        cognition = await self._cognition_commit.snapshot(
            unit_of_work.transaction, episode_id=episode_id
        )
        await self._cognition_commit.finish_episode(
            unit_of_work.transaction,
            episode_id=episode_id,
            status=CognitionEpisodeStatus.FAILED,
            application_status=None,
            failure_code=code,
        )
        try:
            await self._opportunity_transition.resolve_subject_commit(
                unit_of_work.transaction,
                opportunity_id=cognition.opportunity_id,
            )
        except LifeViolation:
            raise SubjectCommitViolation("SUBJECT-OPPORTUNITY-STATE") from None
        await unit_of_work.work.fail(lease, error_code=code)
        await unit_of_work.audit.append(
            AuditDraft(
                AuditEventId(uuid7()),
                AuditReference("runtime", unit_of_work.environment_id),
                Purpose("cognition.subject.commit"),
                "cognition.subject.failed",
                AuditReference("cognitive_episode", episode_id),
                AuditResultStatus.FAILED,
                cognition.trace_id,
                AuditSensitivity.PRIVATE,
                subject_id=SubjectId(cognition.subject_id),
                request=AuditReference("durable_work", lease.work_id.value),
            )
        )

    async def capability_request_ids(
        self,
        unit_of_work: PostgreSQLUnitOfWork,
        subject_commit_id: SubjectCommitId,
    ) -> tuple[UUID, ...]:
        return await self._capability_read.request_ids_for_commit(
            unit_of_work.transaction,
            commit_id=subject_commit_id.value,
        )

    async def affected_activity_ids(
        self,
        unit_of_work: PostgreSQLUnitOfWork,
        validation_id: UUID,
    ) -> tuple[UUID, ...]:
        return await self._activity_commit.affected_activity_ids(
            unit_of_work.transaction, validation_id
        )

    async def affected_maintenance_session_ids(
        self,
        unit_of_work: PostgreSQLUnitOfWork,
        validation_id: UUID,
    ) -> tuple[UUID, ...]:
        return await self._sleep_commit.affected_session_ids(
            unit_of_work.transaction, validation_id
        )

    async def affected_memory_ids(
        self,
        unit_of_work: PostgreSQLUnitOfWork,
        validation_id: UUID,
    ) -> tuple[UUID, ...]:
        return await self._memory_commit.affected_memory_ids(
            unit_of_work.transaction, validation_id
        )

    async def affected_material_ids(
        self,
        unit_of_work: PostgreSQLUnitOfWork,
        validation_id: UUID,
    ) -> tuple[UUID, ...]:
        return await self._material_commit.affected_material_ids(
            unit_of_work.transaction, validation_id
        )

    async def affected_relationship_ids(
        self,
        unit_of_work: PostgreSQLUnitOfWork,
        validation_id: UUID,
    ) -> tuple[UUID, ...]:
        return await self._relationship_commit.affected_relationship_ids(
            unit_of_work.transaction, validation_id
        )

    async def snapshot(
        self,
        unit_of_work: PostgreSQLUnitOfWork,
        lease: WorkLease,
        episode_id: UUID,
    ) -> SubjectCommitSnapshot:
        connection = unit_of_work._connection_for_repository()  # pyright: ignore[reportPrivateUsage]
        await _assert_lease(connection, lease, episode_id)
        cognition = await self._cognition_commit.snapshot(
            unit_of_work.transaction, episode_id=episode_id
        )
        try:
            opportunity = await self._opportunity_transition.subject_commit_snapshot(
                unit_of_work.transaction,
                opportunity_id=cognition.opportunity_id,
            )
            interaction = await self._interaction_commit.snapshot(
                unit_of_work.transaction,
                subject_id=cognition.subject_id,
                scene_id=opportunity.scene_id,
                context_party_id=opportunity.context_party_id,
            )
        except LifeViolation, SceneQueryViolation:
            raise SubjectCommitViolation("SUBJECT-OWNER-SNAPSHOT") from None
        if opportunity.subject_id != cognition.subject_id:
            raise SubjectCommitViolation("SUBJECT-OWNER-SNAPSHOT")
        artifact = await self._artifact_catalog.retained_ref_in(
            unit_of_work.transaction, cognition.change_set_artifact_id
        )
        if artifact is None:
            raise SubjectCommitViolation("SUBJECT-CHANGE-SET-ARTIFACT")
        return SubjectCommitSnapshot(
            cognition.validation_id,
            cognition.episode_id,
            cognition.subject_id,
            cognition.generation_id,
            cognition.activation_id,
            opportunity.opportunity_id,
            opportunity.root_opportunity_id,
            opportunity.reconsideration_no,
            opportunity.evidence_id,
            interaction.scene_id,
            interaction.scene_key,
            interaction.creator_party_id,
            interaction.other_party_id,
            interaction.subject_party_id,
            artifact,
            cognition.base_subject_version,
            cognition.base_state_epoch,
            cognition.context_digest,
            cognition.trace_id,
            opportunity.purpose,
            opportunity.source_kind,
            opportunity.source_ref,
            opportunity.source_version,
            opportunity.activity_id,
            opportunity.available_after,
            opportunity.expires_at,
            cognition.accepted_candidates,
        )

    async def existing_result(
        self,
        unit_of_work: PostgreSQLUnitOfWork,
        validation_id: UUID,
    ) -> SubjectCommitResult | None:
        """Re-read the unique application after an indeterminate commit."""
        application = await self._cognition_commit.existing_application(
            unit_of_work.transaction, validation_id=validation_id
        )
        if application is None:
            return None
        commit_id = (
            SubjectCommitId(application.subject_commit_id)
            if application.subject_commit_id is not None
            else None
        )
        return SubjectCommitResult(
            application.application_id,
            application.status,
            commit_id,
            application.observed_subject_version if commit_id is not None else None,
            application.successor_opportunity_id,
        )

    async def settle(
        self,
        unit_of_work: PostgreSQLUnitOfWork,
        *,
        lease: WorkLease,
        snapshot: SubjectCommitSnapshot,
        change_set: SubjectChangeSet,
        owner_drafts: SubjectCommitOwnerDrafts,
        response_artifact: ArtifactRef | None = None,
        research_artifact: ArtifactRef | None = None,
        material_artifacts: dict[str, ArtifactRef] | None = None,
        prompt_artifacts: dict[str, ArtifactRef] | None = None,
    ) -> SubjectCommitResult:
        connection = unit_of_work._connection_for_repository()  # pyright: ignore[reportPrivateUsage]
        await _assert_lease(connection, lease, snapshot.episode_id)
        fence = unit_of_work.runtime_fence
        if fence is None:
            raise SubjectCommitViolation("SUBJECT-FENCE")
        if (
            change_set.subject_id != snapshot.subject_id
            or change_set.generation_id != snapshot.generation_id
            or change_set.episode_id != snapshot.episode_id
            or change_set.bundle_activation_id != snapshot.activation_id
            or change_set.base_subject_version != snapshot.base_subject_version
            or change_set.base_state_epoch != snapshot.base_state_epoch
            or change_set.context_digest != snapshot.context_digest
        ):
            raise SubjectCommitViolation("SUBJECT-CHANGE-SET-IDENTITY")
        _assert_accepted_change_set(snapshot, change_set)

        party_id = snapshot.other_party_id or snapshot.creator_party_id
        if party_id is not None and await self._data_rights.blocks_subject_commit(
            unit_of_work,
            requester_party_id=party_id,
            opportunity_purpose=snapshot.opportunity_purpose,
        ):
            return await _settle_data_rights_blocked(
                unit_of_work,
                cognition_commit=self._cognition_commit,
                opportunity_transition=self._opportunity_transition,
                expression_commit=self._expression_commit,
                lease=lease,
                snapshot=snapshot,
                observed_version=change_set.base_subject_version,
            )

        subject = await (
            await connection.execute(
                """
                SELECT subject_version, state_epoch, current_generation_id,
                       current_bundle_activation_id
                FROM armi.subjects
                WHERE singleton_key = 1 AND subject_id = %s
                FOR UPDATE
                """,
                (snapshot.subject_id,),
            )
        ).fetchone()
        if subject is None:
            raise SubjectCommitViolation("SUBJECT-IDENTITY")
        subject_state_heads_current = await self._subject_state_commit.heads_match(
            unit_of_work.transaction,
            subject_id=snapshot.subject_id,
            drafts=owner_drafts.subject_state,
        )
        try:
            activity_heads_current = await self._activity_commit.heads_match(
                unit_of_work.transaction,
                context=_activity_commit_context(snapshot),
                drafts=owner_drafts.activity,
            )
        except ActivityViolation as error:
            raise SubjectCommitViolation(
                f"SUBJECT-{error.code.removeprefix('ACTIVITY-')}"
            ) from None
        memory_heads_current = await self._memory_commit.heads_match(
            unit_of_work.transaction,
            subject_id=snapshot.subject_id,
            drafts=owner_drafts.memory,
        )
        mood_heads_current = await self._mood_commit.heads_match(
            unit_of_work.transaction,
            subject_id=snapshot.subject_id,
            drafts=owner_drafts.mood,
        )
        try:
            material_heads_current = await self._material_commit.heads_match(
                unit_of_work.transaction,
                subject_id=snapshot.subject_id,
                generation_id=snapshot.generation_id,
                drafts=owner_drafts.material,
            )
        except MaterialViolation as error:
            raise SubjectCommitViolation(
                f"SUBJECT-{error.code.removeprefix('MATERIAL-')}"
            ) from None
        try:
            prompt_heads_current = await self._prompt_commit.heads_match(
                unit_of_work.transaction,
                subject_id=snapshot.subject_id,
                drafts=owner_drafts.prompt,
            )
        except PromptViolation as error:
            raise SubjectCommitViolation(f"SUBJECT-{error.code}") from None
        try:
            sleep_heads_current = await self._sleep_commit.heads_match(
                unit_of_work.transaction,
                context=_sleep_commit_context(snapshot),
                drafts=owner_drafts.sleep,
            )
        except SleepViolation as error:
            raise SubjectCommitViolation(
                f"SUBJECT-{error.code.removeprefix('SLEEP-')}"
            ) from None
        stale = (
            int(subject[0]) != change_set.base_subject_version
            or int(subject[1]) != change_set.base_state_epoch
            or subject[2] != change_set.generation_id
            or subject[3] != change_set.bundle_activation_id
            or not subject_state_heads_current
            or not activity_heads_current
            or not memory_heads_current
            or not mood_heads_current
            or not material_heads_current
            or not prompt_heads_current
            or not sleep_heads_current
        )
        if stale:
            return await self._settle_stale(
                unit_of_work,
                lease=lease,
                snapshot=snapshot,
                observed_version=int(subject[0]),
            )
        return await self._settle_current(
            unit_of_work,
            lease=lease,
            snapshot=snapshot,
            change_set=change_set,
            owner_drafts=owner_drafts,
            response_artifact=response_artifact,
            research_artifact=research_artifact,
            material_artifacts=material_artifacts or {},
            prompt_artifacts=prompt_artifacts or {},
        )

    async def _settle_current(
        self,
        unit_of_work: PostgreSQLUnitOfWork,
        *,
        lease: WorkLease,
        snapshot: SubjectCommitSnapshot,
        change_set: SubjectChangeSet,
        owner_drafts: SubjectCommitOwnerDrafts,
        response_artifact: ArtifactRef | None,
        research_artifact: ArtifactRef | None,
        material_artifacts: dict[str, ArtifactRef],
        prompt_artifacts: dict[str, ArtifactRef],
    ) -> SubjectCommitResult:
        connection = unit_of_work._connection_for_repository()  # pyright: ignore[reportPrivateUsage]
        disposition_map = {
            CandidateDisposition.NO_CHANGE: CandidateApplicationStatus.NO_CHANGE,
            CandidateDisposition.DEFER: CandidateApplicationStatus.DEFERRED,
            CandidateDisposition.DECLINE: CandidateApplicationStatus.DECLINED,
            CandidateDisposition.NO_ACTION: CandidateApplicationStatus.NO_ACTION,
            CandidateDisposition.NEED_INFORMATION: CandidateApplicationStatus.NEED_INFORMATION,
        }
        if change_set.disposition is not CandidateDisposition.CHANGE:
            status = disposition_map[change_set.disposition]
            return await _settle_without_commit(
                unit_of_work,
                activity_commit=self._activity_commit,
                cognition_commit=self._cognition_commit,
                opportunity_transition=self._opportunity_transition,
                expression_commit=self._expression_commit,
                sleep_commit=self._sleep_commit,
                lease=lease,
                snapshot=snapshot,
                status=status,
                observed_version=change_set.base_subject_version,
                change_set=change_set,
                owner_drafts=owner_drafts,
            )
        if (
            not change_set.experiences
            and not change_set.capability_requests
            and not change_set.action_choices
            and not change_set.web_research_requests
            and not change_set.codex_delegations
            and not change_set.owner_drafts
            and not change_set.exact_life_queries
        ):
            raise SubjectCommitViolation("SUBJECT-EMPTY-COMMIT")

        commit_id = SubjectCommitId(uuid7())
        new_version = change_set.base_subject_version + 1
        fence = cast(RuntimeFence, unit_of_work.runtime_fence)
        await connection.execute(
            """
            INSERT INTO armi.subject_commits (
                subject_commit_id, candidate_validation_id,
                cognitive_episode_id, subject_id, life_generation_id,
                bundle_activation_id, base_subject_version,
                new_subject_version, base_state_epoch,
                runtime_instance_id, fence_token, trace_id) VALUES (
                %s, %s, %s, %s, %s, %s, %s, %s, %s,
                %s, %s, %s)
            """,
            (
                commit_id.value,
                snapshot.validation_id,
                snapshot.episode_id,
                snapshot.subject_id,
                snapshot.generation_id,
                snapshot.activation_id,
                change_set.base_subject_version,
                new_version,
                change_set.base_state_epoch,
                fence.runtime_instance_id.value,
                fence.fence_token,
                snapshot.trace_id.value,
            ),
        )
        experience_ids: dict[str, ExperienceId] = {}
        memory_experience_sources: list[MemoryExperienceSource] = []
        for experience in change_set.experiences:
            experience_id = ExperienceId(uuid7())
            experience_ids[experience.proposal_ref] = experience_id
            memory_experience_sources.append(
                MemoryExperienceSource(
                    experience.proposal_ref,
                    experience_id.value,
                    experience.uncertainty,
                )
            )
            proof = next(
                (
                    item
                    for item in snapshot.accepted_candidates
                    if item.proposal_ref == experience.proposal_ref
                    and item.owner_identity == "experience"
                ),
                None,
            )
            if (
                proof is None
                or not proof.basis_context_ids
                or snapshot.evidence_id is None
            ):
                raise SubjectCommitViolation("SUBJECT-EXPERIENCE-BASIS")
            try:
                evidence_snapshot = await self._evidence_read.snapshot(
                    unit_of_work,
                    evidence_id=EvidenceId(snapshot.evidence_id),
                )
            except EvidenceViolation:
                raise SubjectCommitViolation("SUBJECT-EXPERIENCE-BASIS") from None
            try:
                experience_kind, source_perspective = {
                    "consider_creator_input": (
                        ExperienceKind.CREATOR_INPUT,
                        ExperienceSourcePerspective.CREATOR_CLAIM,
                    ),
                    "consider_web_evidence": (
                        ExperienceKind.WEB_OBSERVATION,
                        ExperienceSourcePerspective.WEB_CLAIM,
                    ),
                    "consider_codex_result": (
                        ExperienceKind.CODEX_OBSERVATION,
                        ExperienceSourcePerspective.CODEX_OBSERVATION,
                    ),
                    "consider_other_human_input": (
                        ExperienceKind.OTHER_HUMAN_INPUT,
                        ExperienceSourcePerspective.OTHER_HUMAN_CLAIM,
                    ),
                }[snapshot.opportunity_purpose]
            except KeyError:
                raise SubjectCommitViolation("SUBJECT-EXPERIENCE-SOURCE") from None
            if snapshot.scene_id is None:
                raise SubjectCommitViolation("SUBJECT-EXPERIENCE-SCENE")
            await self._experience_commit.record(
                unit_of_work.transaction,
                AcceptedExperienceDraft(
                    experience_id=experience_id,
                    subject_id=snapshot.subject_id,
                    subject_commit_id=commit_id.value,
                    cognitive_episode_id=snapshot.episode_id,
                    proposal_ref=experience.proposal_ref,
                    experience_kind=experience_kind,
                    fact_class=experience.fact_class,
                    first_person_gist=experience.first_person_gist,
                    scene_id=snapshot.scene_id,
                    occurred_at=evidence_snapshot.received_at,
                    source_perspective=source_perspective,
                    uncertainty=experience.uncertainty,
                ),
            )
            await self._cognition_commit.note_accepted_experience(
                unit_of_work.transaction,
                subject_id=snapshot.subject_id,
                generation_id=snapshot.generation_id,
                experience_id=experience_id.value,
            )
            for ordinal, context_item_id in enumerate(proof.basis_context_ids, 1):
                await self._evidence.link_experience(
                    unit_of_work,
                    ExperienceEvidenceLink(
                        experience_id.value,
                        evidence_snapshot.evidence_id,
                        context_item_id,
                        ordinal,
                    ),
                )

        try:
            committed_memory_ids = await self._memory_commit.commit(
                unit_of_work.transaction,
                subject_id=snapshot.subject_id,
                generation_id=snapshot.generation_id,
                commit_id=commit_id.value,
                validation_id=snapshot.validation_id,
                drafts=owner_drafts.memory,
                experience_sources=tuple(memory_experience_sources),
            )
        except MemoryViolation as error:
            raise SubjectCommitViolation(
                f"SUBJECT-{error.code.removeprefix('MEMORY-')}"
            ) from None

        try:
            await self._relationship_commit.commit(
                unit_of_work.transaction,
                validation_id=snapshot.validation_id,
                subject_id=snapshot.subject_id,
                generation_id=snapshot.generation_id,
                commit_id=commit_id.value,
                drafts=owner_drafts.relationship,
                experience_ids={
                    key: value.value for key, value in experience_ids.items()
                },
            )
        except RelationshipViolation as error:
            raise SubjectCommitViolation(
                f"SUBJECT-{error.code.removeprefix('RELATIONSHIP-')}"
            ) from None

        try:
            committed_material_ids = await self._material_commit.commit(
                unit_of_work.transaction,
                validation_id=snapshot.validation_id,
                subject_id=snapshot.subject_id,
                generation_id=snapshot.generation_id,
                commit_id=commit_id.value,
                drafts=owner_drafts.material,
                artifacts=material_artifacts,
            )
        except MaterialViolation as error:
            raise SubjectCommitViolation(
                f"SUBJECT-{error.code.removeprefix('MATERIAL-')}"
            ) from None
        await self._context_projections.invalidate(
            unit_of_work.transaction,
            tuple(
                ContextProjectionSourceRef("subjective_memory", memory_id)
                for memory_id in committed_memory_ids
            )
            + tuple(
                ContextProjectionSourceRef("life_material", material_id)
                for material_id in committed_material_ids
            ),
        )
        for material_id in committed_material_ids:
            await unit_of_work.audit.append(
                _audit(
                    unit_of_work,
                    snapshot,
                    "life_material.changed",
                    "life_material",
                    material_id,
                    AuditResultStatus.APPLIED,
                )
            )

        try:
            await self._subject_state_commit.commit(
                unit_of_work.transaction,
                subject_id=snapshot.subject_id,
                commit_id=commit_id.value,
                drafts=owner_drafts.subject_state,
            )
        except SubjectStateViolation as error:
            raise SubjectCommitViolation(
                f"SUBJECT-{error.code.removeprefix('SUBJECT-STATE-')}"
            ) from None

        try:
            await self._mood_commit.commit(
                unit_of_work.transaction,
                subject_id=snapshot.subject_id,
                commit_id=commit_id.value,
                drafts=owner_drafts.mood,
            )
        except MoodViolation as error:
            raise SubjectCommitViolation(
                f"SUBJECT-{error.code.removeprefix('MOOD-')}"
            ) from None

        try:
            changed_prompt_ids = await self._prompt_commit.commit(
                unit_of_work.transaction,
                validation_id=snapshot.validation_id,
                subject_id=snapshot.subject_id,
                author_party_id=snapshot.subject_party_id,
                commit_id=commit_id.value,
                drafts=owner_drafts.prompt,
                artifacts=prompt_artifacts,
            )
        except PromptViolation as error:
            raise SubjectCommitViolation(f"SUBJECT-{error.code}") from None
        for prompt_document_id in changed_prompt_ids:
            await unit_of_work.audit.append(
                _audit(
                    unit_of_work,
                    snapshot,
                    "subject_prompt.revised",
                    "prompt_document",
                    prompt_document_id,
                    AuditResultStatus.APPLIED,
                )
            )

        try:
            activity_result = await self._activity_commit.commit(
                unit_of_work.transaction,
                context=_activity_commit_context(snapshot),
                commit_id=commit_id.value,
                drafts=owner_drafts.activity,
            )
        except ActivityViolation as error:
            raise SubjectCommitViolation(
                f"SUBJECT-{error.code.removeprefix('ACTIVITY-')}"
            ) from None
        if activity_result.update_focus:
            if activity_result.focus_proposal_ref is None:
                raise SubjectCommitViolation("SUBJECT-LIFE-MODE")
            await self._subject_state_commit.update_life_focus(
                unit_of_work.transaction,
                subject_id=snapshot.subject_id,
                commit_id=commit_id.value,
                activity_id=activity_result.focus_activity_id,
                proposal_ref=activity_result.focus_proposal_ref,
            )

        try:
            await self._capability_commit.commit_requests(
                unit_of_work,
                context=_capability_commit_context(snapshot),
                commit_id=commit_id.value,
                requests=change_set.capability_requests,
            )
        except CapabilityViolation as error:
            raise SubjectCommitViolation(f"SUBJECT-{error.code}") from None
        try:
            await self._expression_commit.commit(
                unit_of_work,
                context=_expression_commit_context(snapshot),
                commit_id=commit_id.value,
                choices=change_set.action_choices,
                response_artifact=response_artifact,
            )
        except ResponseViolation as error:
            raise SubjectCommitViolation(error.code) from None
        try:
            await self._web_research_commit.commit_requests(
                unit_of_work,
                context=_web_research_commit_context(snapshot),
                commit_id=commit_id.value,
                requests=change_set.web_research_requests,
                query_artifact=research_artifact,
            )
        except WebResearchViolation as error:
            raise SubjectCommitViolation(f"SUBJECT-{error.code}") from None
        await _insert_exact_life_query_intent(
            unit_of_work,
            cognition_commit=self._cognition_commit,
            snapshot=snapshot,
            commit_id=commit_id,
            queries=change_set.exact_life_queries,
        )
        try:
            await self._codex_commit.commit_delegations(
                unit_of_work,
                context=_codex_commit_context(snapshot),
                commit_id=commit_id.value,
                delegations=change_set.codex_delegations,
            )
        except CodexDelegationViolation as error:
            raise SubjectCommitViolation(f"SUBJECT-{error.code}") from None

        updated_subject = await (
            await connection.execute(
                """
                UPDATE armi.subjects SET subject_version = %s
                WHERE subject_id = %s AND subject_version = %s
                  AND state_epoch = %s
                RETURNING subject_id
                """,
                (
                    new_version,
                    snapshot.subject_id,
                    change_set.base_subject_version,
                    change_set.base_state_epoch,
                ),
            )
        ).fetchone()
        if updated_subject is None:
            raise SubjectCommitViolation("SUBJECT-CAS-STALE")

        application_id = CandidateApplicationId(uuid7())
        await _insert_application(
            cognition_commit=self._cognition_commit,
            unit_of_work=unit_of_work,
            application_id=application_id,
            snapshot=snapshot,
            lease=lease,
            status=CandidateApplicationStatus.APPLIED,
            observed_version=new_version,
            commit_id=commit_id,
        )
        try:
            await self._activity_commit.record_decision(
                unit_of_work.transaction,
                context=_activity_commit_context(snapshot),
                application_id=application_id.value,
                drafts=owner_drafts.activity,
                result_revision_id=activity_result.result_revision_id,
                output_material_ids=committed_material_ids,
            )
        except ActivityViolation as error:
            raise SubjectCommitViolation(
                f"SUBJECT-{error.code.removeprefix('ACTIVITY-')}"
            ) from None
        try:
            await self._sleep_commit.commit(
                unit_of_work.transaction,
                context=_sleep_commit_context(snapshot),
                application_id=application_id.value,
                commit_id=commit_id.value,
                resulting_subject_version=new_version,
                drafts=owner_drafts.sleep,
                committed_memory_ids=committed_memory_ids,
            )
        except SleepViolation as error:
            raise SubjectCommitViolation(
                f"SUBJECT-{error.code.removeprefix('SLEEP-')}"
            ) from None
        if snapshot.scene_id is not None:
            await self._interaction_commit.append_timeline(
                unit_of_work.transaction,
                scene_id=snapshot.scene_id,
                subject_commit_id=commit_id.value,
            )
        await _finish_episode_and_work(
            unit_of_work,
            cognition_commit=self._cognition_commit,
            opportunity_transition=self._opportunity_transition,
            lease=lease,
            snapshot=snapshot,
            status=CandidateApplicationStatus.APPLIED,
            result_ref=application_id.value,
        )
        await unit_of_work.audit.append(
            _audit(
                unit_of_work,
                snapshot,
                "cognition.subject.committed",
                "subject_commit",
                commit_id.value,
                AuditResultStatus.APPLIED,
            )
        )
        return SubjectCommitResult(
            application_id,
            CandidateApplicationStatus.APPLIED,
            commit_id,
            new_version,
        )

    async def _settle_stale(
        self,
        unit_of_work: PostgreSQLUnitOfWork,
        *,
        lease: WorkLease,
        snapshot: SubjectCommitSnapshot,
        observed_version: int,
    ) -> SubjectCommitResult:
        try:
            successor_value = (
                await self._opportunity_transition.supersede_subject_commit(
                    unit_of_work.transaction,
                    opportunity_id=snapshot.opportunity_id,
                )
            )
        except LifeViolation:
            raise SubjectCommitViolation("SUBJECT-OPPORTUNITY-STATE") from None
        successor = None if successor_value is None else successor_value.value
        application_id = CandidateApplicationId(uuid7())
        await _insert_application(
            cognition_commit=self._cognition_commit,
            unit_of_work=unit_of_work,
            application_id=application_id,
            snapshot=snapshot,
            lease=lease,
            status=CandidateApplicationStatus.STALE,
            observed_version=observed_version,
            successor_id=successor,
        )
        await self._cognition_commit.finish_episode(
            unit_of_work.transaction,
            episode_id=snapshot.episode_id,
            status=CognitionEpisodeStatus.STALE,
            application_status=CandidateApplicationStatus.STALE,
        )
        await unit_of_work.work.complete(
            lease, WorkResultRef("candidate_application", application_id.value)
        )
        await unit_of_work.audit.append(
            _audit(
                unit_of_work,
                snapshot,
                "cognition.subject.stale",
                "candidate_application",
                application_id.value,
                AuditResultStatus.REJECTED,
            )
        )
        return SubjectCommitResult(
            application_id,
            CandidateApplicationStatus.STALE,
            successor_opportunity_id=successor,
        )


async def _settle_without_commit(
    unit_of_work: PostgreSQLUnitOfWork,
    *,
    activity_commit: ActivityCommitPort,
    cognition_commit: CognitionSubjectCommitPort,
    opportunity_transition: OpportunityTransitionPort,
    expression_commit: ExpressionCommitPort,
    sleep_commit: SleepCommitPort,
    lease: WorkLease,
    snapshot: SubjectCommitSnapshot,
    status: CandidateApplicationStatus,
    observed_version: int,
    change_set: SubjectChangeSet,
    owner_drafts: SubjectCommitOwnerDrafts,
) -> SubjectCommitResult:
    application_id = CandidateApplicationId(uuid7())
    try:
        activity_reconsideration = activity_commit.requests_reconsideration(
            context=_activity_commit_context(snapshot),
            drafts=owner_drafts.activity,
        )
    except ActivityViolation as error:
        raise SubjectCommitViolation(
            f"SUBJECT-{error.code.removeprefix('ACTIVITY-')}"
        ) from None
    try:
        sleep_reconsideration = sleep_commit.requests_reconsideration(
            context=_sleep_commit_context(snapshot),
            drafts=owner_drafts.sleep,
        )
    except SleepViolation as error:
        raise SubjectCommitViolation(
            f"SUBJECT-{error.code.removeprefix('SLEEP-')}"
        ) from None
    if activity_reconsideration and sleep_reconsideration:
        raise SubjectCommitViolation("SUBJECT-SUCCESSOR-CONFLICT")
    successor_id: UUID | None = None
    if activity_reconsideration:
        if snapshot.source_activity_id is None:
            raise SubjectCommitViolation("SUBJECT-ACTIVITY-SOURCE")
        successor = await opportunity_transition.reconsider_activity(
            unit_of_work.transaction,
            subject_id=snapshot.subject_id,
            root_opportunity_id=snapshot.root_opportunity_id,
            predecessor_opportunity_id=snapshot.opportunity_id,
            source_ref=snapshot.source_ref,
            source_version=snapshot.source_version,
            activity_id=snapshot.source_activity_id,
        )
        successor_id = None if successor is None else successor.value
    elif sleep_reconsideration:
        successor = await opportunity_transition.reconsider_sleep(
            unit_of_work.transaction,
            predecessor_opportunity_id=snapshot.opportunity_id,
        )
        successor_id = None if successor is None else successor.value
    await _insert_application(
        cognition_commit=cognition_commit,
        unit_of_work=unit_of_work,
        application_id=application_id,
        snapshot=snapshot,
        lease=lease,
        status=status,
        observed_version=observed_version,
        successor_id=successor_id,
    )
    try:
        await activity_commit.record_decision(
            unit_of_work.transaction,
            context=_activity_commit_context(snapshot),
            application_id=application_id.value,
            drafts=owner_drafts.activity,
            result_revision_id=None,
        )
    except ActivityViolation as error:
        raise SubjectCommitViolation(
            f"SUBJECT-{error.code.removeprefix('ACTIVITY-')}"
        ) from None
    try:
        await sleep_commit.commit(
            unit_of_work.transaction,
            context=_sleep_commit_context(snapshot),
            application_id=application_id.value,
            commit_id=None,
            resulting_subject_version=observed_version,
            drafts=owner_drafts.sleep,
        )
    except SleepViolation as error:
        raise SubjectCommitViolation(
            f"SUBJECT-{error.code.removeprefix('SLEEP-')}"
        ) from None
    try:
        await expression_commit.record_terminal(
            unit_of_work,
            context=_expression_commit_context(snapshot),
            application_id=application_id.value,
            application_status=status.value,
            choices=change_set.action_choices,
            activity_owned=bool(owner_drafts.activity),
        )
    except ResponseViolation as error:
        raise SubjectCommitViolation(error.code) from None
    await _finish_episode_and_work(
        unit_of_work,
        cognition_commit=cognition_commit,
        opportunity_transition=opportunity_transition,
        lease=lease,
        snapshot=snapshot,
        status=status,
        result_ref=application_id.value,
    )
    audit_status = (
        AuditResultStatus.COMPLETED
        if status
        in {
            CandidateApplicationStatus.NO_CHANGE,
            CandidateApplicationStatus.DECLINED,
            CandidateApplicationStatus.NO_ACTION,
        }
        else AuditResultStatus.WAITING
    )
    await unit_of_work.audit.append(
        _audit(
            unit_of_work,
            snapshot,
            f"cognition.subject.{status.value}",
            "candidate_application",
            application_id.value,
            audit_status,
        )
    )
    return SubjectCommitResult(
        application_id,
        status,
        successor_opportunity_id=successor_id,
    )


async def _settle_data_rights_blocked(
    unit_of_work: PostgreSQLUnitOfWork,
    *,
    cognition_commit: CognitionSubjectCommitPort,
    opportunity_transition: OpportunityTransitionPort,
    expression_commit: ExpressionCommitPort,
    lease: WorkLease,
    snapshot: SubjectCommitSnapshot,
    observed_version: int,
) -> SubjectCommitResult:
    status = CandidateApplicationStatus.NO_ACTION
    application_id = CandidateApplicationId(uuid7())
    await _insert_application(
        cognition_commit=cognition_commit,
        unit_of_work=unit_of_work,
        application_id=application_id,
        snapshot=snapshot,
        lease=lease,
        status=status,
        observed_version=observed_version,
        successor_id=None,
    )
    try:
        await expression_commit.record_terminal(
            unit_of_work,
            context=_expression_commit_context(snapshot),
            application_id=application_id.value,
            application_status=status.value,
            choices=(),
            activity_owned=True,
        )
    except ResponseViolation as error:
        raise SubjectCommitViolation(error.code) from None
    await _finish_episode_and_work(
        unit_of_work,
        cognition_commit=cognition_commit,
        opportunity_transition=opportunity_transition,
        lease=lease,
        snapshot=snapshot,
        status=status,
        result_ref=application_id.value,
    )
    await unit_of_work.audit.append(
        _audit(
            unit_of_work,
            snapshot,
            "cognition.subject.data_rights_blocked",
            "candidate_application",
            application_id.value,
            AuditResultStatus.REJECTED,
        )
    )
    return SubjectCommitResult(application_id, status)


async def _finish_episode_and_work(
    unit_of_work: PostgreSQLUnitOfWork,
    *,
    cognition_commit: CognitionSubjectCommitPort,
    opportunity_transition: OpportunityTransitionPort,
    lease: WorkLease,
    snapshot: SubjectCommitSnapshot,
    status: CandidateApplicationStatus,
    result_ref: UUID,
) -> None:
    await cognition_commit.finish_episode(
        unit_of_work.transaction,
        episode_id=snapshot.episode_id,
        status=CognitionEpisodeStatus.COMPLETED,
        application_status=status,
    )
    try:
        await opportunity_transition.resolve_subject_commit(
            unit_of_work.transaction,
            opportunity_id=snapshot.opportunity_id,
        )
    except LifeViolation:
        raise SubjectCommitViolation("SUBJECT-OPPORTUNITY-STATE") from None
    await unit_of_work.work.complete(
        lease, WorkResultRef("candidate_application", result_ref)
    )


async def _insert_application(
    *,
    cognition_commit: CognitionSubjectCommitPort,
    unit_of_work: PostgreSQLUnitOfWork,
    application_id: CandidateApplicationId,
    snapshot: SubjectCommitSnapshot,
    lease: WorkLease,
    status: CandidateApplicationStatus,
    observed_version: int,
    commit_id: SubjectCommitId | None = None,
    successor_id: UUID | None = None,
) -> None:
    fence = cast(RuntimeFence, unit_of_work.runtime_fence)
    await cognition_commit.record_application(
        unit_of_work.transaction,
        CognitionApplicationDraft(
            application_id=application_id,
            validation_id=snapshot.validation_id,
            episode_id=snapshot.episode_id,
            work_id=lease.work_id.value,
            status=status,
            subject_commit_id=commit_id.value if commit_id is not None else None,
            successor_opportunity_id=successor_id,
            base_subject_version=snapshot.base_subject_version,
            observed_subject_version=observed_version,
            runtime_instance_id=fence.runtime_instance_id.value,
            fence_token=fence.fence_token,
            purpose=snapshot.opportunity_purpose,
            generation_id=snapshot.generation_id,
        ),
    )


async def _insert_exact_life_query_intent(
    unit_of_work: PostgreSQLUnitOfWork,
    *,
    cognition_commit: CognitionSubjectCommitPort,
    snapshot: SubjectCommitSnapshot,
    commit_id: SubjectCommitId,
    queries: tuple[CandidateExactLifeQueryDraft, ...],
) -> None:
    if not queries:
        return
    if len(queries) != 1:
        raise SubjectCommitViolation("SUBJECT-EXACT-LIFE-QUERY-COUNT")
    query = queries[0]
    if snapshot.scene_id is None or snapshot.creator_party_id is None:
        raise SubjectCommitViolation("SUBJECT-EXACT-LIFE-QUERY-SCENE")
    connection = unit_of_work._connection_for_repository()  # pyright: ignore[reportPrivateUsage]
    now_row = await (
        await connection.execute("SELECT statement_timestamp()")
    ).fetchone()
    if now_row is None:
        raise SubjectCommitViolation("SUBJECT-DATABASE")
    intent_id = uuid7()
    work_id = WorkId(uuid7())
    payload = {
        "record_kind": str(query.record_kind),
        "query_text": query.query_text,
        "limit": query.limit,
    }
    query_digest = Digest.from_bytes(rfc8785.dumps(cast(Any, payload)))
    await unit_of_work.work.enqueue(
        WorkDraft(
            work_id,
            "life.query.execute",
            WorkOwner("exact_life_query_intent", intent_id),
            IdempotencyKey(f"life-query:{snapshot.opportunity_id}"),
            query_digest,
            45,
            Instant(now_row[0]),
            Instant(now_row[0] + timedelta(seconds=3600)),
            2,
            snapshot.trace_id,
            SubjectId(snapshot.subject_id),
            WorkPayloadRef("exact_life_query_intent", intent_id),
        )
    )
    await cognition_commit.record_exact_life_query(
        unit_of_work.transaction,
        CognitionExactLifeQueryIntentDraft(
            intent_id=intent_id,
            subject_commit_id=commit_id.value,
            source_opportunity_id=snapshot.opportunity_id,
            subject_id=snapshot.subject_id,
            scene_id=snapshot.scene_id,
            creator_party_id=snapshot.creator_party_id,
            proposal_ref=query.proposal_ref,
            record_kind=str(query.record_kind),
            query_text=query.query_text,
            result_limit=query.limit,
            query_digest=query_digest,
            execution_work_id=work_id.value,
            trace_id=snapshot.trace_id,
        ),
    )
    await unit_of_work.audit.append(
        _audit(
            unit_of_work,
            snapshot,
            "life.query.intent.recorded",
            "exact_life_query_intent",
            intent_id,
            AuditResultStatus.ACCEPTED,
        )
    )


async def _assert_lease(connection: Any, lease: WorkLease, episode_id: UUID) -> None:
    row = await (
        await connection.execute(
            """
            SELECT 1 FROM armi.durable_work
            WHERE work_id = %s AND owner_ref = %s
              AND work_kind = 'cognition.subject.commit'
              AND status = 'leased' AND current_attempt_id = %s
              AND lease_owner = %s AND lease_token = %s
              AND lease_expires_at > statement_timestamp()
            """,
            (
                lease.work_id.value,
                episode_id,
                lease.attempt_id.value,
                lease.owner,
                lease.token,
            ),
        )
    ).fetchone()
    if row is None:
        raise SubjectCommitViolation("SUBJECT-WORK-STALE")


def _audit(
    unit_of_work: PostgreSQLUnitOfWork,
    snapshot: SubjectCommitSnapshot,
    operation: str,
    target_kind: str,
    target_ref: UUID,
    result: AuditResultStatus,
) -> AuditDraft:
    return AuditDraft(
        AuditEventId(uuid7()),
        AuditReference("runtime", unit_of_work.environment_id),
        Purpose("cognition.subject"),
        operation,
        AuditReference(target_kind, target_ref),
        result,
        snapshot.trace_id,
        AuditSensitivity.PRIVATE,
        subject_id=SubjectId(snapshot.subject_id),
        request=AuditReference("cognitive_episode", snapshot.episode_id),
    )


def _assert_accepted_change_set(
    snapshot: SubjectCommitSnapshot, change_set: SubjectChangeSet
) -> None:
    accepted = {
        (item.proposal_ref, item.owner_identity): item
        for item in snapshot.accepted_candidates
    }
    actual: dict[tuple[str, str], object] = {}
    groups = (
        ("experience", change_set.experiences),
        ("capability", change_set.capability_requests),
        ("action", change_set.action_choices),
        ("web_research", change_set.web_research_requests),
        ("codex_delegation", change_set.codex_delegations),
        ("exact_life_query", change_set.exact_life_queries),
    )
    for owner, values in groups:
        for value in values:
            actual[(value.proposal_ref, owner)] = value
    for value in change_set.owner_drafts:
        actual[(value.proposal_ref, value.owner)] = value
        proof = accepted.get((value.proposal_ref, value.owner))
        if (
            proof is None
            or proof.atomic_group_ref != value.atomic_group_ref
            or proof.fact_class is not value.fact_class
        ):
            raise SubjectCommitViolation("SUBJECT-CANDIDATE-ACCEPTANCE")
    if set(actual) != set(accepted):
        raise SubjectCommitViolation("SUBJECT-CANDIDATE-ACCEPTANCE")


__all__ = (
    "PostgreSQLSubjectCommitRepository",
    "SubjectCommitOwnerDrafts",
    "SubjectCommitSnapshot",
)
