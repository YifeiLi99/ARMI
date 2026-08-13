"""PostgreSQL owner for the T-03 subject commit transaction."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import Any, cast
from uuid import UUID, uuid7

import rfc8785
from armi_activity.api import (
    ActivityCommitContext,
    ActivityCommitPort,
    ActivityViolation,
)
from armi_capability.api import (
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
from armi_cognition.api import SubjectChangeSet
from armi_evidence.api import EvidenceId, EvidenceWritePort, ExperienceEvidenceLink
from armi_expression.api import (
    ExpressionCommitContext,
    ExpressionCommitPort,
    ResponseViolation,
)
from armi_kernel.application import (
    ArtifactId,
    ArtifactIntegrityStatus,
    ArtifactPrivacyScope,
    ArtifactRef,
    AuditDraft,
    AuditEventId,
    AuditReference,
    AuditResultStatus,
    AuditSensitivity,
    CandidateApplicationId,
    CandidateApplicationStatus,
    CandidateDisposition,
    CandidateExactLifeQueryDraft,
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
from armi_material.api import MaterialCommitPort, MaterialViolation
from armi_memory.api import (
    MemoryCommitPort,
    MemoryViolation,
)
from armi_mood.api import MoodCommitPort, MoodViolation
from armi_opportunity.api import OpportunityTransitionPort
from armi_prompt.api import PromptCommitPort, PromptViolation
from armi_relationship.api import RelationshipCommitPort, RelationshipViolation
from armi_sleep.api import (
    SleepCommitContext,
    SleepCommitPort,
    SleepViolation,
)
from armi_subject_state.api import SubjectStateCommitPort, SubjectStateViolation
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
        "_capability_commit",
        "_capability_read",
        "_codex_commit",
        "_evidence",
        "_expression_commit",
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
        evidence: EvidenceWritePort,
        expression_commit: ExpressionCommitPort,
        memory_commit: MemoryCommitPort,
        mood_commit: MoodCommitPort,
        opportunity_transition: OpportunityTransitionPort,
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
        self._evidence = evidence
        self._expression_commit = expression_commit
        self._memory_commit = memory_commit
        self._mood_commit = mood_commit
        self._opportunity_transition = opportunity_transition
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
        code: str,
    ) -> None:
        """Terminally settle a current subject-commit attempt and its episode."""

        connection = unit_of_work._connection_for_repository()  # pyright: ignore[reportPrivateUsage]
        row = await (
            await connection.execute(
                """
                SELECT episode.cognitive_episode_id,
                       episode.subject_id,
                       episode.trace_id
                FROM armi.durable_work AS work
                JOIN armi.cognitive_episodes AS episode
                  ON episode.cognitive_episode_id = work.owner_ref
                WHERE work.work_id = %s
                  AND work.work_kind = 'cognition.subject.commit'
                  AND work.owner_kind = 'cognitive_episode'
                  AND work.status = 'leased'
                  AND work.current_attempt_id = %s
                  AND work.lease_owner = %s
                  AND work.lease_token = %s
                  AND work.lease_expires_at >= statement_timestamp()
                  AND episode.status = 'candidate_validated'
                FOR UPDATE OF work, episode
                """,
                (
                    lease.work_id.value,
                    lease.attempt_id.value,
                    lease.owner,
                    lease.token,
                ),
            )
        ).fetchone()
        if row is None:
            raise SubjectCommitViolation("SUBJECT-WORK-STALE")
        await connection.execute(
            """
            UPDATE armi.cognitive_episodes
            SET status = 'failed', failure_code = %s
            WHERE cognitive_episode_id = %s
              AND status = 'candidate_validated'
            """,
            (code, row[0]),
        )
        resolved = await (
            await connection.execute(
                """
                UPDATE armi.opportunities AS opportunity
                SET current_disposition = 'resolved',
                    resolved_at = statement_timestamp()
                FROM armi.cognitive_episodes AS episode
                WHERE episode.cognitive_episode_id = %s
                  AND opportunity.opportunity_id = episode.opportunity_id
                  AND opportunity.current_disposition = 'selected'
                RETURNING opportunity.opportunity_id
                """,
                (row[0],),
            )
        ).fetchone()
        if resolved is None:
            raise SubjectCommitViolation("SUBJECT-OPPORTUNITY-STATE")
        await unit_of_work.work.fail(lease, error_code=code)
        await unit_of_work.audit.append(
            AuditDraft(
                AuditEventId(uuid7()),
                AuditReference("runtime", unit_of_work.environment_id),
                Purpose("cognition.subject.commit"),
                "cognition.subject.failed",
                AuditReference("cognitive_episode", row[0]),
                AuditResultStatus.FAILED,
                TraceId(str(row[2])),
                AuditSensitivity.PRIVATE,
                subject_id=SubjectId(row[1]),
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
    ) -> SubjectCommitSnapshot:
        connection = unit_of_work._connection_for_repository()  # pyright: ignore[reportPrivateUsage]
        row = await (
            await connection.execute(
                """
                SELECT
                    validation.candidate_validation_id,
                    episode.cognitive_episode_id,
                    episode.subject_id,
                    validation.life_generation_id,
                    validation.bundle_activation_id,
                    opportunity.opportunity_id,
                    opportunity.root_opportunity_id,
                    opportunity.reconsideration_no,
                    opportunity.evidence_id,
                    opportunity.scene_id,
                    scene.scene_key,
                    opportunity.context_party_id,
                    validation.change_set_artifact_id,
                    validation.base_subject_version,
                    validation.base_state_epoch,
                    validation.context_digest,
                    episode.trace_id,
                    opportunity.purpose,
                    opportunity.source_kind,
                    opportunity.source_ref,
                    opportunity.source_version,
                    opportunity.activity_id,
                    opportunity.context_party_id
                FROM armi.durable_work AS work
                JOIN armi.cognitive_episodes AS episode
                  ON episode.cognitive_episode_id = work.owner_ref
                JOIN armi.cognitive_candidate_validations AS validation
                  ON validation.cognitive_episode_id = episode.cognitive_episode_id
                JOIN armi.opportunities AS opportunity
                  ON opportunity.opportunity_id = episode.opportunity_id
                LEFT JOIN armi.interaction_scenes AS scene
                  ON scene.scene_id = opportunity.scene_id
                WHERE work.work_id = %s
                  AND work.work_kind = 'cognition.subject.commit'
                  AND work.status = 'leased'
                  AND work.current_attempt_id = %s
                  AND work.lease_owner = %s
                  AND work.lease_token = %s
                  AND work.lease_expires_at > statement_timestamp()
                  AND episode.status = 'candidate_validated'
                  AND validation.validation_status IN ('accepted', 'partially_accepted')
                  AND validation.change_set_artifact_id IS NOT NULL
                  AND NOT EXISTS (
                      SELECT 1
                      FROM armi.cognitive_candidate_applications AS application
                      WHERE application.candidate_validation_id = validation.candidate_validation_id
                  )
                """,
                (
                    lease.work_id.value,
                    lease.attempt_id.value,
                    lease.owner,
                    lease.token,
                ),
            )
        ).fetchone()
        if row is None:
            raise SubjectCommitViolation("SUBJECT-WORK-STALE")
        return SubjectCommitSnapshot(
            row[0],
            row[1],
            row[2],
            row[3],
            row[4],
            row[5],
            row[6],
            int(row[7]),
            row[8],
            row[9],
            None if row[10] is None else str(row[10]),
            row[11],
            row[22],
            await _artifact_ref(connection, row[12]),
            int(row[13]),
            int(row[14]),
            Digest(str(row[15])),
            TraceId(str(row[16])),
            str(row[17]),
            str(row[18]),
            row[19],
            int(row[20]),
            row[21],
        )

    async def existing_result(
        self,
        unit_of_work: PostgreSQLUnitOfWork,
        validation_id: UUID,
    ) -> SubjectCommitResult | None:
        """Re-read the unique application after an indeterminate commit."""
        connection = unit_of_work._connection_for_repository()  # pyright: ignore[reportPrivateUsage]
        row = await (
            await connection.execute(
                """
                SELECT candidate_application_id, resolution,
                       subject_commit_id,
                       observed_subject_version, successor_opportunity_id
                FROM armi.cognitive_candidate_applications
                WHERE candidate_validation_id = %s
                """,
                (validation_id,),
            )
        ).fetchone()
        if row is None:
            return None
        status = CandidateApplicationStatus(str(row[1]))
        commit_id = SubjectCommitId(row[2]) if row[2] is not None else None
        return SubjectCommitResult(
            CandidateApplicationId(row[0]),
            status,
            commit_id,
            int(row[3]) if commit_id is not None else None,
            row[4],
        )

    async def settle(
        self,
        unit_of_work: PostgreSQLUnitOfWork,
        *,
        lease: WorkLease,
        snapshot: SubjectCommitSnapshot,
        change_set: SubjectChangeSet,
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

        if await _data_rights_block_subject_commit(connection, snapshot):
            return await _settle_data_rights_blocked(
                unit_of_work,
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
            drafts=change_set.owner_drafts,
        )
        try:
            activity_heads_current = await self._activity_commit.heads_match(
                unit_of_work.transaction,
                context=_activity_commit_context(snapshot),
                drafts=change_set.owner_drafts,
            )
        except ActivityViolation as error:
            raise SubjectCommitViolation(
                f"SUBJECT-{error.code.removeprefix('ACTIVITY-')}"
            ) from None
        memory_heads_current = await self._memory_commit.heads_match(
            unit_of_work.transaction,
            subject_id=snapshot.subject_id,
            drafts=change_set.owner_drafts,
        )
        mood_heads_current = await self._mood_commit.heads_match(
            unit_of_work.transaction,
            subject_id=snapshot.subject_id,
            drafts=change_set.owner_drafts,
        )
        try:
            material_heads_current = await self._material_commit.heads_match(
                unit_of_work.transaction,
                subject_id=snapshot.subject_id,
                generation_id=snapshot.generation_id,
                drafts=change_set.owner_drafts,
            )
        except MaterialViolation as error:
            raise SubjectCommitViolation(
                f"SUBJECT-{error.code.removeprefix('MATERIAL-')}"
            ) from None
        try:
            prompt_heads_current = await self._prompt_commit.heads_match(
                unit_of_work.transaction,
                subject_id=snapshot.subject_id,
                drafts=change_set.owner_drafts,
            )
        except PromptViolation as error:
            raise SubjectCommitViolation(f"SUBJECT-{error.code}") from None
        try:
            sleep_heads_current = await self._sleep_commit.heads_match(
                unit_of_work.transaction,
                context=_sleep_commit_context(snapshot),
                drafts=change_set.owner_drafts,
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
                opportunity_transition=self._opportunity_transition,
                expression_commit=self._expression_commit,
                sleep_commit=self._sleep_commit,
                lease=lease,
                snapshot=snapshot,
                status=status,
                observed_version=change_set.base_subject_version,
                change_set=change_set,
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
        for experience in change_set.experiences:
            experience_id = ExperienceId(uuid7())
            experience_ids[experience.proposal_ref] = experience_id
            evidence_links = await _evidence_links(
                connection,
                snapshot=snapshot,
                proposal_ref=experience.proposal_ref,
            )
            if not evidence_links:
                raise SubjectCommitViolation("SUBJECT-EXPERIENCE-BASIS")
            received_at = evidence_links[0][2]
            try:
                experience_kind, source_perspective = {
                    "consider_creator_input": ("creator_input", "creator_claim"),
                    "consider_web_evidence": ("web_observation", "web_claim"),
                    "consider_codex_result": (
                        "codex_observation",
                        "codex_observation",
                    ),
                    "consider_other_human_input": (
                        "other_human_input",
                        "other_human_claim",
                    ),
                }[snapshot.opportunity_purpose]
            except KeyError:
                raise SubjectCommitViolation("SUBJECT-EXPERIENCE-SOURCE") from None
            await connection.execute(
                """
                INSERT INTO armi.accepted_experiences (
                    experience_id, subject_id, subject_commit_id, cognitive_episode_id,
                    proposal_ref, experience_kind, fact_class,
                    first_person_gist, scene_id, occurred_at, learned_at,
                    source_perspective, uncertainty, privacy_scope) VALUES (
                    %s, %s, %s, %s, %s, %s, %s,
                    %s, %s, %s, %s, %s, %s, 'private')
                """,
                (
                    experience_id.value,
                    snapshot.subject_id,
                    commit_id.value,
                    snapshot.episode_id,
                    experience.proposal_ref,
                    experience_kind,
                    experience.fact_class.value,
                    experience.first_person_gist,
                    snapshot.scene_id,
                    received_at,
                    received_at,
                    source_perspective,
                    experience.uncertainty,
                ),
            )
            for ordinal, (context_item_id, evidence_id, _) in enumerate(
                evidence_links, 1
            ):
                await self._evidence.link_experience(
                    unit_of_work,
                    ExperienceEvidenceLink(
                        experience_id.value,
                        EvidenceId(evidence_id),
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
                drafts=change_set.owner_drafts,
                experience_ids={
                    key: value.value for key, value in experience_ids.items()
                },
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
                drafts=change_set.owner_drafts,
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
                drafts=change_set.owner_drafts,
                artifacts=material_artifacts,
            )
        except MaterialViolation as error:
            raise SubjectCommitViolation(
                f"SUBJECT-{error.code.removeprefix('MATERIAL-')}"
            ) from None
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
                drafts=change_set.owner_drafts,
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
                drafts=change_set.owner_drafts,
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
                commit_id=commit_id.value,
                drafts=change_set.owner_drafts,
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
                drafts=change_set.owner_drafts,
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
            connection,
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
                drafts=change_set.owner_drafts,
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
                drafts=change_set.owner_drafts,
                committed_memory_ids=committed_memory_ids,
            )
        except SleepViolation as error:
            raise SubjectCommitViolation(
                f"SUBJECT-{error.code.removeprefix('SLEEP-')}"
            ) from None
        if snapshot.scene_id is not None:
            timeline_item_id = uuid7()
            await connection.execute(
                """
                INSERT INTO armi.scene_timeline_items (
                    timeline_item_id, scene_id, source_kind, source_ref,
                    source_event_no, result_status, occurred_at) VALUES (
                    %s, %s, 'subject_commit', %s, 1, 'applied',
                    statement_timestamp())
                """,
                (timeline_item_id, snapshot.scene_id, commit_id.value),
            )
        await _finish_episode_and_work(
            unit_of_work,
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
        connection = unit_of_work._connection_for_repository()  # pyright: ignore[reportPrivateUsage]
        successor = uuid7() if snapshot.reconsideration_no == 0 else None
        if successor is not None:
            await connection.execute(
                """
                INSERT INTO armi.opportunities (
                    opportunity_id, evidence_id, subject_id, scene_id,
                    creator_party_id, other_party_id, purpose, eligibility_status,
                    current_disposition, root_opportunity_id,
                    predecessor_opportunity_id, reconsideration_no,
                    source_kind, source_ref, source_version,
                    activity_id) VALUES (
                    %s, %s, %s, %s, %s, %s, %s,
                    'eligible', 'open', %s, %s, 1,
                    %s, %s, %s, %s)
                """,
                (
                    successor,
                    snapshot.evidence_id,
                    snapshot.subject_id,
                    snapshot.scene_id,
                    snapshot.creator_party_id,
                    snapshot.other_party_id,
                    snapshot.opportunity_purpose,
                    snapshot.root_opportunity_id,
                    snapshot.opportunity_id,
                    snapshot.source_kind,
                    snapshot.source_ref,
                    snapshot.source_version,
                    snapshot.source_activity_id,
                ),
            )
        application_id = CandidateApplicationId(uuid7())
        await _insert_application(
            connection,
            unit_of_work=unit_of_work,
            application_id=application_id,
            snapshot=snapshot,
            lease=lease,
            status=CandidateApplicationStatus.STALE,
            observed_version=observed_version,
            successor_id=successor,
        )
        await connection.execute(
            """
            UPDATE armi.cognitive_episodes
            SET status = 'stale', application_resolution = 'stale',
                committed_at = statement_timestamp()
            WHERE cognitive_episode_id = %s AND status = 'candidate_validated'
            """,
            (snapshot.episode_id,),
        )
        await connection.execute(
            """
            UPDATE armi.opportunities
            SET current_disposition = %s, resolved_at = statement_timestamp()
            WHERE opportunity_id = %s AND current_disposition = 'selected'
            """,
            (
                "superseded" if successor is not None else "resolved",
                snapshot.opportunity_id,
            ),
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
    opportunity_transition: OpportunityTransitionPort,
    expression_commit: ExpressionCommitPort,
    sleep_commit: SleepCommitPort,
    lease: WorkLease,
    snapshot: SubjectCommitSnapshot,
    status: CandidateApplicationStatus,
    observed_version: int,
    change_set: SubjectChangeSet,
) -> SubjectCommitResult:
    connection = unit_of_work._connection_for_repository()  # pyright: ignore[reportPrivateUsage]
    application_id = CandidateApplicationId(uuid7())
    try:
        activity_reconsideration = activity_commit.requests_reconsideration(
            context=_activity_commit_context(snapshot),
            drafts=change_set.owner_drafts,
        )
    except ActivityViolation as error:
        raise SubjectCommitViolation(
            f"SUBJECT-{error.code.removeprefix('ACTIVITY-')}"
        ) from None
    try:
        sleep_reconsideration = sleep_commit.requests_reconsideration(
            context=_sleep_commit_context(snapshot),
            drafts=change_set.owner_drafts,
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
        connection,
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
            drafts=change_set.owner_drafts,
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
            drafts=change_set.owner_drafts,
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
            activity_owned=any(
                item.owner == "activity" for item in change_set.owner_drafts
            ),
        )
    except ResponseViolation as error:
        raise SubjectCommitViolation(error.code) from None
    await _finish_episode_and_work(
        unit_of_work,
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


async def _data_rights_block_subject_commit(
    connection: Any,
    snapshot: SubjectCommitSnapshot,
) -> bool:
    party_id = snapshot.other_party_id or snapshot.creator_party_id
    if party_id is None:
        return False
    await connection.execute(
        "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
        (f"data-rights:{party_id}",),
    )
    row = await (
        await connection.execute(
            """
            SELECT EXISTS (
                SELECT 1
                FROM armi.deletion_orders
                WHERE requester_party_id = %s
                  AND status = 'effective'
                  AND (
                      order_kind IN ('stop_use', 'delete_related')
                      OR (
                          order_kind = 'stop_contact'
                          AND %s IN (
                              'consider_creator_input',
                              'consider_other_human_input',
                              'consider_creator_outreach'
                          )
                      )
                  )
            )
            """,
            (party_id, snapshot.opportunity_purpose),
        )
    ).fetchone()
    return bool(row is not None and row[0])


async def _settle_data_rights_blocked(
    unit_of_work: PostgreSQLUnitOfWork,
    *,
    expression_commit: ExpressionCommitPort,
    lease: WorkLease,
    snapshot: SubjectCommitSnapshot,
    observed_version: int,
) -> SubjectCommitResult:
    connection = unit_of_work._connection_for_repository()  # pyright: ignore[reportPrivateUsage]
    status = CandidateApplicationStatus.NO_ACTION
    application_id = CandidateApplicationId(uuid7())
    await _insert_application(
        connection,
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
    lease: WorkLease,
    snapshot: SubjectCommitSnapshot,
    status: CandidateApplicationStatus,
    result_ref: UUID,
) -> None:
    connection = unit_of_work._connection_for_repository()  # pyright: ignore[reportPrivateUsage]
    await connection.execute(
        """
        UPDATE armi.cognitive_episodes
        SET status = 'completed', application_resolution = %s,
            committed_at = statement_timestamp()
        WHERE cognitive_episode_id = %s AND status = 'candidate_validated'
        """,
        (status.value, snapshot.episode_id),
    )
    await connection.execute(
        """
        UPDATE armi.opportunities
        SET current_disposition = 'resolved', resolved_at = statement_timestamp()
        WHERE opportunity_id = %s AND current_disposition = 'selected'
        """,
        (snapshot.opportunity_id,),
    )
    await unit_of_work.work.complete(
        lease, WorkResultRef("candidate_application", result_ref)
    )


async def _insert_application(
    connection: Any,
    *,
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
    await connection.execute(
        """
        INSERT INTO armi.cognitive_candidate_applications (
            candidate_application_id, candidate_validation_id,
            cognitive_episode_id, work_id, resolution, subject_commit_id,
            successor_opportunity_id, base_subject_version,
            observed_subject_version,
            runtime_instance_id, fence_token) VALUES (
            %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """,
        (
            application_id.value,
            snapshot.validation_id,
            snapshot.episode_id,
            lease.work_id.value,
            status.value,
            commit_id.value if commit_id is not None else None,
            successor_id,
            snapshot.base_subject_version,
            observed_version,
            fence.runtime_instance_id.value,
            fence.fence_token,
        ),
    )


async def _evidence_links(
    connection: Any,
    *,
    snapshot: SubjectCommitSnapshot,
    proposal_ref: str,
) -> list[tuple[UUID, UUID, Any]]:
    rows = await (
        await connection.execute(
            """
            SELECT basis.context_item_id, evidence.evidence_id, evidence.received_at
            FROM armi.cognitive_candidate_basis_links AS basis
            JOIN armi.cognitive_context_items AS item
              ON item.context_item_id = basis.context_item_id
             AND item.cognitive_episode_id = %s
             AND item.disposition = 'included'
             AND item.trust_class = 'external_claim'
             AND item.source_ref = %s
            JOIN armi.external_evidence AS evidence
              ON evidence.evidence_id = item.source_ref
             AND evidence.evidence_id = %s
            WHERE basis.candidate_validation_id = %s
              AND basis.proposal_ref = %s
            ORDER BY basis.ordinal
            """,
            (
                snapshot.episode_id,
                snapshot.evidence_id,
                snapshot.evidence_id,
                snapshot.validation_id,
                proposal_ref,
            ),
        )
    ).fetchall()
    return [(row[0], row[1], row[2]) for row in rows]


async def _insert_exact_life_query_intent(
    unit_of_work: PostgreSQLUnitOfWork,
    *,
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
    item = await (
        await connection.execute(
            """
            SELECT validation_status
            FROM armi.cognitive_candidate_validation_items
            WHERE candidate_validation_id = %s AND proposal_ref = %s
              AND owner_kind = 'exact_life_query'
            """,
            (snapshot.validation_id, query.proposal_ref),
        )
    ).fetchone()
    if item is None or str(item[0]) != "accepted":
        raise SubjectCommitViolation("SUBJECT-EXACT-LIFE-QUERY-VALIDATION")
    now_row = await (
        await connection.execute("SELECT statement_timestamp()")
    ).fetchone()
    if now_row is None:
        raise SubjectCommitViolation("SUBJECT-DATABASE")
    intent_id = uuid7()
    work_id = WorkId(uuid7())
    payload = {
        "record_kind": query.record_kind.value,
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
    await connection.execute(
        """
        INSERT INTO armi.exact_life_query_intents (
            exact_life_query_intent_id, subject_commit_id,
            source_opportunity_id, subject_id, scene_id, creator_party_id,
            proposal_ref, record_kind, query_text, result_limit,
            query_digest, execution_work_id, status, trace_id) VALUES (
            %s, %s, %s, %s, %s, %s,
            %s, %s, %s, %s,
            %s, %s, 'pending', %s)
        """,
        (
            intent_id,
            commit_id.value,
            snapshot.opportunity_id,
            snapshot.subject_id,
            snapshot.scene_id,
            snapshot.creator_party_id,
            query.proposal_ref,
            query.record_kind.value,
            query.query_text,
            query.limit,
            query_digest.value,
            work_id.value,
            snapshot.trace_id.value,
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


async def _artifact_ref(connection: Any, artifact_id: UUID) -> ArtifactRef:
    row = await (
        await connection.execute(
            """
            SELECT artifact_id, content_digest, media_type, byte_size,
                   logical_kind, privacy_scope, integrity_status
            FROM armi.artifacts
            WHERE artifact_id = %s AND retention_status = 'retained'
            """,
            (artifact_id,),
        )
    ).fetchone()
    if row is None:
        raise SubjectCommitViolation("SUBJECT-CHANGE-SET-ARTIFACT")
    return ArtifactRef(
        ArtifactId(row[0]),
        Digest(str(row[1])),
        int(row[3]),
        str(row[2]),
        str(row[4]),
        ArtifactPrivacyScope(str(row[5])),
        ArtifactIntegrityStatus(str(row[6])),
    )


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


__all__ = ("PostgreSQLSubjectCommitRepository", "SubjectCommitSnapshot")
