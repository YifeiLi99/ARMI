"""PostgreSQL owner for the T-03 subject commit transaction."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, cast
from uuid import UUID, uuid7

import rfc8785
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
    CandidateActivityDecisionDraft,
    CandidateActivityDraft,
    CandidateApplicationId,
    CandidateApplicationStatus,
    CandidateDisposition,
    CandidateExactLifeQueryDraft,
    CandidateLifeMaterialDraft,
    CandidateOwner,
    CapabilityRequestDraft,
    CodexDelegationDraft,
    CreatorReplyDraft,
    CreatorSceneReplyScope,
    ExperienceId,
    FormalNoActionDraft,
    OtherHumanEndConversationDraft,
    OtherHumanReplyDraft,
    RuntimeFence,
    SubjectChangeSet,
    SubjectCommitId,
    SubjectCommitResult,
    SubjectCommitViolation,
    WebResearchRequestDraft,
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
from armi_memory.api import (
    MemoryCommitPort,
    MemoryViolation,
)
from armi_relationship.api import (
    RelationshipCommitPort,
    RelationshipPolicyPort,
    RelationshipReadPort,
    RelationshipViolation,
)
from armi_sleep.api import (
    SleepCommitContext,
    SleepCommitPort,
    SleepViolation,
)

from .life_material_commit import apply_life_materials
from .subject_prompt_commit import (
    apply_subject_prompts,
    lock_subject_prompt_heads,
    subject_prompt_heads_are_stale,
)
from .unit_of_work import PostgreSQLUnitOfWork

_WORK_KIND = "cognition.subject.commit"
_RESPONSE_WORK_KIND = "cognition.response.admit"


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


class PostgreSQLSubjectCommitRepository:
    """Read one validated ChangeSet and atomically apply or settle it."""

    __slots__ = (
        "_memory_commit",
        "_relationship_commit",
        "_relationship_policy",
        "_relationships",
        "_sleep_commit",
    )

    def __init__(
        self,
        memory_commit: MemoryCommitPort,
        relationship_commit: RelationshipCommitPort,
        relationship_read: RelationshipReadPort,
        relationship_policy: RelationshipPolicyPort,
        sleep_commit: SleepCommitPort,
    ) -> None:
        self._memory_commit = memory_commit
        self._relationship_commit = relationship_commit
        self._relationships = relationship_read
        self._relationship_policy = relationship_policy
        self._sleep_commit = sleep_commit

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
        connection = unit_of_work._connection_for_repository()  # pyright: ignore[reportPrivateUsage]
        rows = await (
            await connection.execute(
                """
                SELECT capability_request_id
                FROM armi.capability_requests
                WHERE subject_commit_id = %s
                ORDER BY capability_request_id
                """,
                (subject_commit_id.value,),
            )
        ).fetchall()
        return tuple(UUID(str(row[0])) for row in rows)

    async def affected_activity_ids(
        self,
        unit_of_work: PostgreSQLUnitOfWork,
        validation_id: UUID,
    ) -> tuple[UUID, ...]:
        connection = unit_of_work._connection_for_repository()  # pyright: ignore[reportPrivateUsage]
        rows = await (
            await connection.execute(
                """
                SELECT activity_id
                FROM armi.activity_revisions
                WHERE candidate_validation_id = %s
                UNION
                SELECT activity_id
                FROM armi.activity_decisions
                WHERE candidate_validation_id = %s
                ORDER BY activity_id
                """,
                (validation_id, validation_id),
            )
        ).fetchall()
        return tuple(UUID(str(row[0])) for row in rows)

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
        connection = unit_of_work._connection_for_repository()  # pyright: ignore[reportPrivateUsage]
        rows = await (
            await connection.execute(
                """
                SELECT life_material_id
                FROM armi.life_material_revisions
                WHERE candidate_validation_id = %s
                ORDER BY life_material_id
                """,
                (validation_id,),
            )
        ).fetchall()
        return tuple(UUID(str(row[0])) for row in rows)

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
        heads = await _lock_heads(connection, snapshot.subject_id, change_set)
        memory_heads_current = await self._memory_commit.heads_match(
            unit_of_work.transaction,
            subject_id=snapshot.subject_id,
            drafts=change_set.owner_drafts,
        )
        material_heads = await _lock_material_heads(connection, change_set)
        prompt_heads = await lock_subject_prompt_heads(
            connection,
            subject_id=snapshot.subject_id,
            prompts=change_set.prompts,
        )
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
            or _component_heads_are_stale(heads, change_set)
            or not memory_heads_current
            or any(
                material_heads.get(material.material_id)
                != (
                    (None, 0, None, None, None, None, None)
                    if material.current_revision_id is None
                    else (
                        material.current_revision_id,
                        material.expected_head_version,
                        snapshot.subject_id,
                        snapshot.generation_id,
                        material.owner_party_id,
                        material.material_kind.value,
                        None,
                    )
                )
                for material in change_set.materials
            )
            or subject_prompt_heads_are_stale(prompt_heads, change_set.prompts)
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
                sleep_commit=self._sleep_commit,
                lease=lease,
                snapshot=snapshot,
                status=status,
                observed_version=change_set.base_subject_version,
                change_set=change_set,
            )
        if (
            not change_set.experiences
            and not change_set.components
            and not change_set.capability_requests
            and not change_set.action_choices
            and not change_set.web_research_requests
            and not change_set.codex_delegations
            and not change_set.activities
            and not change_set.activity_decisions
            and not change_set.owner_drafts
            and not change_set.materials
            and not change_set.prompts
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
                await connection.execute(
                    """
                    INSERT INTO armi.experience_evidence_links (
                        experience_id, evidence_id, context_item_id,
                        link_kind, ordinal
                    ) VALUES (%s, %s, %s, 'relied_on', %s)
                    """,
                    (experience_id.value, evidence_id, context_item_id, ordinal),
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

        await apply_life_materials(
            connection,
            validation_id=snapshot.validation_id,
            subject_id=snapshot.subject_id,
            generation_id=snapshot.generation_id,
            commit_id=commit_id.value,
            materials=change_set.materials,
            artifacts=material_artifacts,
        )
        for material in change_set.materials:
            await unit_of_work.audit.append(
                _audit(
                    unit_of_work,
                    snapshot,
                    f"life_material.{material.revision_kind.value}",
                    "life_material",
                    material.material_id,
                    AuditResultStatus.APPLIED,
                )
            )

        for component in sorted(
            change_set.components, key=lambda item: item.owner.value
        ):
            head = await (
                await connection.execute(
                    """
                    SELECT current_revision_id, component_version
                    FROM armi.subject_component_heads
                    WHERE subject_id = %s AND component_kind = %s
                    """,
                    (snapshot.subject_id, component.owner.value),
                )
            ).fetchone()
            if head is None or int(head[1]) != component.expected_version:
                raise SubjectCommitViolation("SUBJECT-HEAD-STALE")
            revision_id = uuid7()
            await connection.execute(
                """
                INSERT INTO armi.subject_component_revisions (
                    component_revision_id, subject_id, component_kind,
                    component_version, previous_revision_id, origin_kind,
                    origin_ref, subject_commit_id, proposal_ref,
                    semantic_payload, privacy_scope
                ) VALUES (
                    %s, %s, %s, %s, %s, 'subject_commit', %s,
                    %s, %s, %s::jsonb, 'private'
                )
                """,
                (
                    revision_id,
                    snapshot.subject_id,
                    component.owner.value,
                    component.expected_version + 1,
                    head[0],
                    commit_id.value,
                    commit_id.value,
                    component.proposal_ref,
                    component.canonical_next_state.decode("utf-8"),
                ),
            )
            updated = await (
                await connection.execute(
                    """
                    UPDATE armi.subject_component_heads
                    SET current_revision_id = %s, component_version = %s
                    WHERE subject_id = %s AND component_kind = %s
                      AND current_revision_id = %s AND component_version = %s
                    RETURNING subject_id
                    """,
                    (
                        revision_id,
                        component.expected_version + 1,
                        snapshot.subject_id,
                        component.owner.value,
                        head[0],
                        component.expected_version,
                    ),
                )
            ).fetchone()
            if updated is None:
                raise SubjectCommitViolation("SUBJECT-HEAD-STALE")

        await apply_subject_prompts(
            connection,
            validation_id=snapshot.validation_id,
            subject_id=snapshot.subject_id,
            commit_id=commit_id.value,
            prompts=change_set.prompts,
            artifacts=prompt_artifacts,
        )
        for prompt in change_set.prompts:
            await unit_of_work.audit.append(
                _audit(
                    unit_of_work,
                    snapshot,
                    "subject_prompt.revised",
                    "prompt_document",
                    prompt.prompt_document_id,
                    AuditResultStatus.APPLIED,
                )
            )

        await _insert_activities(
            connection,
            snapshot=snapshot,
            commit_id=commit_id,
            activities=change_set.activities,
        )
        activity_result_revision = await _apply_activity_transition(
            connection,
            snapshot=snapshot,
            commit_id=commit_id,
            decisions=change_set.activity_decisions,
        )

        await _insert_capability_requests(
            unit_of_work,
            snapshot=snapshot,
            commit_id=commit_id,
            requests=change_set.capability_requests,
        )
        await _insert_response_intent(
            unit_of_work,
            relationships=self._relationships,
            relationship_policy=self._relationship_policy,
            snapshot=snapshot,
            commit_id=commit_id,
            change_set=change_set,
            response_artifact=response_artifact,
        )
        await _insert_web_research_intent(
            unit_of_work,
            snapshot=snapshot,
            commit_id=commit_id,
            requests=change_set.web_research_requests,
            query_artifact=research_artifact,
        )
        await _insert_exact_life_query_intent(
            unit_of_work,
            snapshot=snapshot,
            commit_id=commit_id,
            queries=change_set.exact_life_queries,
        )
        await _insert_codex_delegation_intent(
            unit_of_work,
            snapshot=snapshot,
            commit_id=commit_id,
            delegations=change_set.codex_delegations,
        )

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
        await _insert_activity_attention_decision(
            connection,
            snapshot=snapshot,
            application_id=application_id,
            decisions=change_set.activity_decisions,
            result_revision_id=activity_result_revision,
        )
        await _insert_activity_internal_work_decision(
            connection,
            snapshot=snapshot,
            application_id=application_id,
            decisions=change_set.activity_decisions,
            materials=change_set.materials,
            result_revision_id=activity_result_revision,
        )
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
    sleep_commit: SleepCommitPort,
    lease: WorkLease,
    snapshot: SubjectCommitSnapshot,
    status: CandidateApplicationStatus,
    observed_version: int,
    change_set: SubjectChangeSet,
) -> SubjectCommitResult:
    connection = unit_of_work._connection_for_repository()  # pyright: ignore[reportPrivateUsage]
    application_id = CandidateApplicationId(uuid7())
    successor_id = await _insert_attention_reconsideration(
        connection,
        snapshot=snapshot,
        decisions=change_set.activity_decisions,
    )
    try:
        sleep_successor = await sleep_commit.reconsideration(
            unit_of_work.transaction,
            context=_sleep_commit_context(snapshot),
            drafts=change_set.owner_drafts,
        )
    except SleepViolation as error:
        raise SubjectCommitViolation(
            f"SUBJECT-{error.code.removeprefix('SLEEP-')}"
        ) from None
    if successor_id is not None and sleep_successor is not None:
        raise SubjectCommitViolation("SUBJECT-SUCCESSOR-CONFLICT")
    successor_id = successor_id or sleep_successor
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
    if snapshot.opportunity_purpose == "consider_other_human_input":
        await _insert_other_human_terminal_decision(
            connection,
            snapshot=snapshot,
            application_id=application_id,
            status=status,
        )
    await _insert_activity_attention_decision(
        connection,
        snapshot=snapshot,
        application_id=application_id,
        decisions=change_set.activity_decisions,
        result_revision_id=None,
    )
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
    if (
        snapshot.opportunity_purpose != "consider_other_human_input"
        and not change_set.activity_decisions
        and status
        in {
            CandidateApplicationStatus.DECLINED,
            CandidateApplicationStatus.NO_ACTION,
        }
    ):
        await _insert_formal_no_action(
            unit_of_work,
            snapshot=snapshot,
            application_id=application_id,
            change_set=change_set,
        )
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
    if snapshot.opportunity_purpose == "consider_other_human_input":
        await _insert_other_human_terminal_decision(
            connection,
            snapshot=snapshot,
            application_id=application_id,
            status=status,
        )
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
    if snapshot.opportunity_purpose == "consider_codex_result" and status in {
        CandidateApplicationStatus.APPLIED,
        CandidateApplicationStatus.NO_CHANGE,
        CandidateApplicationStatus.DECLINED,
        CandidateApplicationStatus.NO_ACTION,
    }:
        await connection.execute(
            """
            UPDATE armi.action_operations AS operation
            SET phase='terminal', outcome='completed',
                completed_at=statement_timestamp()
            FROM armi.codex_result_sources AS source
            JOIN armi.codex_verification_results AS verification
              ON verification.codex_verification_id=source.codex_verification_id
            WHERE source.opportunity_id=%s
              AND operation.effect_id=verification.effect_id
              AND operation.phase='result_pending'
              AND operation.outcome IS NULL
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


async def _lock_heads(
    connection: Any,
    subject_id: UUID,
    change_set: SubjectChangeSet,
) -> dict[CandidateOwner, int]:
    owners = sorted(
        {component.owner for component in change_set.components},
        key=lambda item: item.value,
    )
    result: dict[CandidateOwner, int] = {}
    for owner in owners:
        row = await (
            await connection.execute(
                """
                SELECT component_version
                FROM armi.subject_component_heads
                WHERE subject_id = %s AND component_kind = %s
                FOR UPDATE
                """,
                (subject_id, owner.value),
            )
        ).fetchone()
        if row is None:
            raise SubjectCommitViolation("SUBJECT-HEAD-MISSING")
        result[owner] = int(row[0])
    return result


def _component_heads_are_stale(
    heads: dict[CandidateOwner, int], change_set: SubjectChangeSet
) -> bool:
    return any(
        heads.get(component.owner) != component.expected_version
        for component in change_set.components
    )


async def _lock_material_heads(
    connection: Any,
    change_set: SubjectChangeSet,
) -> dict[
    UUID,
    tuple[
        UUID | None,
        int,
        UUID | None,
        UUID | None,
        UUID | None,
        str | None,
        datetime | None,
    ],
]:
    result: dict[
        UUID,
        tuple[
            UUID | None,
            int,
            UUID | None,
            UUID | None,
            UUID | None,
            str | None,
            datetime | None,
        ],
    ] = {}
    for material_id in sorted(
        {item.material_id for item in change_set.materials},
        key=str,
    ):
        row = await (
            await connection.execute(
                """
                SELECT current_revision_id, head_version, subject_id,
                       life_generation_id, owner_party_id, material_kind,
                       deleted_at
                FROM armi.life_materials
                WHERE life_material_id = %s
                FOR UPDATE
                """,
                (material_id,),
            )
        ).fetchone()
        result[material_id] = (
            (None, 0, None, None, None, None, None)
            if row is None
            else (
                row[0],
                int(row[1]),
                row[2],
                row[3],
                row[4],
                str(row[5]),
                row[6],
            )
        )
    return result


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


async def _insert_activities(
    connection: Any,
    *,
    snapshot: SubjectCommitSnapshot,
    commit_id: SubjectCommitId,
    activities: tuple[CandidateActivityDraft, ...],
) -> None:
    for activity in activities:
        validation = await (
            await connection.execute(
                """
                SELECT 1
                FROM armi.cognitive_candidate_validation_items
                WHERE candidate_validation_id = %s
                  AND proposal_ref = %s
                  AND owner_kind = 'activity'
                  AND validation_status = 'accepted'
                """,
                (snapshot.validation_id, activity.proposal_ref),
            )
        ).fetchone()
        if validation is None:
            raise SubjectCommitViolation("SUBJECT-ACTIVITY-VALIDATION")
        await connection.execute(
            """
            INSERT INTO armi.activities (
                activity_id, subject_id, activity_kind,
                origin_opportunity_id, current_revision_id, head_version,
                privacy_scope) VALUES (%s, %s, %s, %s, NULL, 0, %s)
            """,
            (
                activity.activity_id,
                snapshot.subject_id,
                activity.activity_kind,
                snapshot.opportunity_id,
                activity.privacy_scope,
            ),
        )
        revision_id = uuid7()
        await connection.execute(
            """
            INSERT INTO armi.activity_revisions (
                activity_revision_id, activity_id, revision_no,
                previous_revision_id, subject_commit_id,
                candidate_validation_id, proposal_ref, goal,
                progress_summary, waiting_condition, resumption_cue,
                next_safe_step, status, terminal_reason,
                related_scene_id, transition_kind,
                waiting_condition_kind, resume_not_before) VALUES (
                %s, %s, 1, NULL, %s, %s, %s, %s,
                NULL, NULL, NULL, %s, %s, NULL, %s, 'created', NULL, NULL)
            """,
            (
                revision_id,
                activity.activity_id,
                commit_id.value,
                snapshot.validation_id,
                activity.proposal_ref,
                activity.goal,
                activity.next_safe_step,
                activity.status.value,
                snapshot.scene_id,
            ),
        )
        updated = await (
            await connection.execute(
                """
                UPDATE armi.activities
                SET current_revision_id = %s, head_version = 1
                WHERE activity_id = %s
                  AND current_revision_id IS NULL
                  AND head_version = 0
                RETURNING activity_id
                """,
                (revision_id, activity.activity_id),
            )
        ).fetchone()
        if updated is None:
            raise SubjectCommitViolation("SUBJECT-ACTIVITY-HEAD-STALE")


async def _apply_activity_transition(
    connection: Any,
    *,
    snapshot: SubjectCommitSnapshot,
    commit_id: SubjectCommitId,
    decisions: tuple[CandidateActivityDecisionDraft, ...],
) -> UUID | None:
    if not decisions:
        return None
    if len(decisions) != 1:
        raise SubjectCommitViolation("SUBJECT-ACTIVITY-DECISION-COUNT")
    decision = decisions[0]
    row = await (
        await connection.execute(
            """
            SELECT activity.current_revision_id, activity.head_version,
                   revision.revision_no, revision.goal, revision.progress_summary,
                   revision.next_safe_step, revision.status
            FROM armi.activities AS activity
            JOIN armi.activity_revisions AS revision
              ON revision.activity_revision_id = activity.current_revision_id
            WHERE activity.activity_id = %s AND activity.subject_id = %s
            FOR UPDATE OF activity
            """,
            (decision.activity_id, snapshot.subject_id),
        )
    ).fetchone()
    if (
        row is None
        or row[0] != decision.current_revision_id
        or int(row[1]) != decision.expected_head_version
        or snapshot.source_activity_id != decision.activity_id
        or snapshot.source_ref != decision.current_revision_id
    ):
        raise SubjectCommitViolation("SUBJECT-ACTIVITY-HEAD-STALE")
    validation = await (
        await connection.execute(
            """
            SELECT 1 FROM armi.cognitive_candidate_validation_items
            WHERE candidate_validation_id = %s AND proposal_ref = %s
              AND owner_kind = 'activity' AND validation_status = 'accepted'
            """,
            (snapshot.validation_id, decision.proposal_ref),
        )
    ).fetchone()
    if validation is None:
        raise SubjectCommitViolation("SUBJECT-ACTIVITY-VALIDATION")

    kind = decision.decision_kind.value
    target = {
        "engage": "in_progress",
        "progress": "in_progress",
        "wait": "waiting",
        "pause": "paused",
        "resume": "resuming",
        "complete": "completed",
        "abandon": "abandoned",
    }.get(kind)
    if target is None:
        raise SubjectCommitViolation("SUBJECT-ACTIVITY-TRANSITION")
    current_status = str(row[6])
    allowed = {
        "ready": {"engage"},
        "in_progress": {"engage", "progress", "wait", "pause", "complete", "abandon"},
        "waiting": {"resume"},
        "paused": {"resume"},
        "resuming": {"engage"},
    }
    if kind not in allowed.get(current_status, set()):
        raise SubjectCommitViolation("SUBJECT-ACTIVITY-TRANSITION")

    revision_id = uuid7()
    resume_not_before = (
        None
        if decision.delay_seconds is None
        else datetime.now(UTC) + timedelta(seconds=decision.delay_seconds)
    )
    await connection.execute(
        """
        INSERT INTO armi.activity_revisions (
            activity_revision_id, activity_id, revision_no,
            previous_revision_id, subject_commit_id, candidate_validation_id,
            proposal_ref, goal, progress_summary, waiting_condition,
            resumption_cue, next_safe_step, status, terminal_reason,
            related_scene_id, transition_kind, waiting_condition_kind,
            resume_not_before) VALUES (
            %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
            %s, %s, %s, %s, NULL, %s, %s, %s)
        """,
        (
            revision_id,
            decision.activity_id,
            int(row[2]) + 1,
            decision.current_revision_id,
            commit_id.value,
            snapshot.validation_id,
            decision.proposal_ref,
            str(row[3]),
            decision.progress_summary
            if decision.progress_summary is not None
            else row[4],
            decision.waiting_summary,
            decision.resumption_cue,
            decision.next_safe_step
            if decision.next_safe_step is not None
            else None
            if target in {"completed", "abandoned"}
            else row[5],
            target,
            decision.terminal_reason,
            kind,
            None if decision.waiting_kind is None else decision.waiting_kind.value,
            resume_not_before,
        ),
    )
    updated = await (
        await connection.execute(
            """
            UPDATE armi.activities
            SET current_revision_id = %s, head_version = head_version + 1
            WHERE activity_id = %s AND current_revision_id = %s
              AND head_version = %s
            RETURNING activity_id
            """,
            (
                revision_id,
                decision.activity_id,
                decision.current_revision_id,
                decision.expected_head_version,
            ),
        )
    ).fetchone()
    if updated is None:
        raise SubjectCommitViolation("SUBJECT-ACTIVITY-HEAD-STALE")
    await _update_life_focus(
        connection,
        snapshot=snapshot,
        commit_id=commit_id,
        decision=decision,
        engage=kind == "engage",
    )
    return revision_id


async def _update_life_focus(
    connection: Any,
    *,
    snapshot: SubjectCommitSnapshot,
    commit_id: SubjectCommitId,
    decision: CandidateActivityDecisionDraft,
    engage: bool,
) -> None:
    head = await (
        await connection.execute(
            """
            SELECT head.current_revision_id, head.component_version,
                   revision.semantic_payload
            FROM armi.subject_component_heads AS head
            JOIN armi.subject_component_revisions AS revision
              ON revision.component_revision_id = head.current_revision_id
            WHERE head.subject_id = %s AND head.component_kind = 'life_mode'
            FOR UPDATE OF head
            """,
            (snapshot.subject_id,),
        )
    ).fetchone()
    if head is None or not isinstance(head[2], dict):
        raise SubjectCommitViolation("SUBJECT-LIFE-MODE")
    payload = cast(dict[str, object], head[2]).copy()
    active = payload.get("active_activities")
    if type(active) is not list:
        raise SubjectCommitViolation("SUBJECT-LIFE-MODE")
    active_values = cast(list[object], active)
    if len(active_values) > 1:
        raise SubjectCommitViolation("SUBJECT-LIFE-MODE")
    payload["active_activities"] = [str(decision.activity_id)] if engage else []
    canonical = rfc8785.dumps(cast(Any, payload))
    revision_id = uuid7()
    await connection.execute(
        """
        INSERT INTO armi.subject_component_revisions (
            component_revision_id, subject_id, component_kind,
            component_version, previous_revision_id, origin_kind, origin_ref,
            subject_commit_id, proposal_ref, semantic_payload, privacy_scope
        ) VALUES (
            %s, %s, 'life_mode', %s, %s, 'subject_commit', %s,
            %s, %s, %s::jsonb, 'private'
        )
        """,
        (
            revision_id,
            snapshot.subject_id,
            int(head[1]) + 1,
            head[0],
            commit_id.value,
            commit_id.value,
            decision.proposal_ref,
            canonical.decode("utf-8"),
        ),
    )
    updated = await (
        await connection.execute(
            """
            UPDATE armi.subject_component_heads
            SET current_revision_id = %s, component_version = component_version + 1
            WHERE subject_id = %s AND component_kind = 'life_mode'
              AND current_revision_id = %s AND component_version = %s
            RETURNING subject_id
            """,
            (revision_id, snapshot.subject_id, head[0], int(head[1])),
        )
    ).fetchone()
    if updated is None:
        raise SubjectCommitViolation("SUBJECT-LIFE-MODE-STALE")


async def _insert_attention_reconsideration(
    connection: Any,
    *,
    snapshot: SubjectCommitSnapshot,
    decisions: tuple[CandidateActivityDecisionDraft, ...],
) -> UUID | None:
    if (
        snapshot.opportunity_purpose != "consider_activity_attention"
        or len(decisions) != 1
        or decisions[0].decision_kind.value != "defer"
        or snapshot.reconsideration_no != 0
    ):
        return None
    successor_id = uuid7()
    inserted = await (
        await connection.execute(
            """
            INSERT INTO armi.opportunities (
                opportunity_id, evidence_id, subject_id, scene_id,
                creator_party_id, purpose, eligibility_status,
                current_disposition, available_after, root_opportunity_id,
                predecessor_opportunity_id, reconsideration_no, source_kind,
                source_ref, source_version, activity_id) VALUES (
                %s, NULL, %s, NULL, NULL, 'consider_activity_attention',
                'eligible', 'open', statement_timestamp() + interval '60 seconds',
                %s, %s, 1, 'activity_revision', %s, %s, %s)
            ON CONFLICT (predecessor_opportunity_id) DO NOTHING
            RETURNING opportunity_id
            """,
            (
                successor_id,
                snapshot.subject_id,
                snapshot.root_opportunity_id,
                snapshot.opportunity_id,
                snapshot.source_ref,
                snapshot.source_version,
                snapshot.source_activity_id,
            ),
        )
    ).fetchone()
    return None if inserted is None else inserted[0]


async def _insert_activity_attention_decision(
    connection: Any,
    *,
    snapshot: SubjectCommitSnapshot,
    application_id: CandidateApplicationId,
    decisions: tuple[CandidateActivityDecisionDraft, ...],
    result_revision_id: UUID | None,
) -> None:
    if snapshot.opportunity_purpose != "consider_activity_attention":
        return
    if not decisions:
        return
    if len(decisions) != 1:
        raise SubjectCommitViolation("SUBJECT-ACTIVITY-DECISION-COUNT")
    decision = decisions[0]
    review_not_before = (
        datetime.now(UTC) + timedelta(seconds=60)
        if decision.decision_kind.value == "defer"
        else None
    )
    await connection.execute(
        """
        INSERT INTO armi.activity_decisions (
            activity_decision_id, decision_source, opportunity_id, cognitive_episode_id,
            candidate_validation_id, candidate_application_id, activity_id,
            expected_revision_id, expected_head_version,
            decision_kind, result_revision_id,
            review_not_before) VALUES (
            %s, 'attention', %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """,
        (
            uuid7(),
            snapshot.opportunity_id,
            snapshot.episode_id,
            snapshot.validation_id,
            application_id.value,
            decision.activity_id,
            decision.current_revision_id,
            decision.expected_head_version,
            decision.decision_kind.value,
            result_revision_id,
            review_not_before,
        ),
    )


async def _insert_activity_internal_work_decision(
    connection: Any,
    *,
    snapshot: SubjectCommitSnapshot,
    application_id: CandidateApplicationId,
    decisions: tuple[CandidateActivityDecisionDraft, ...],
    materials: tuple[CandidateLifeMaterialDraft, ...],
    result_revision_id: UUID | None,
) -> None:
    if snapshot.opportunity_purpose != "consider_activity_internal_work":
        return
    if len(decisions) != 1 or result_revision_id is None or len(materials) > 1:
        raise SubjectCommitViolation("SUBJECT-ACTIVITY-WORK-SHAPE")
    decision = decisions[0]
    outcome = {
        "progress": "progress",
        "complete": "complete",
        "wait": "need_information",
        "abandon": "abandon",
        "pause": "no_result",
    }.get(decision.decision_kind.value)
    if outcome is None:
        raise SubjectCommitViolation("SUBJECT-ACTIVITY-WORK-SHAPE")
    await connection.execute(
        """
        INSERT INTO armi.activity_decisions (
            activity_decision_id, decision_source, opportunity_id, cognitive_episode_id,
            candidate_validation_id, candidate_application_id, activity_id,
            expected_revision_id, expected_head_version,
            decision_kind, result_revision_id,
            output_material_id) VALUES (
            %s, 'internal_work', %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """,
        (
            uuid7(),
            snapshot.opportunity_id,
            snapshot.episode_id,
            snapshot.validation_id,
            application_id.value,
            decision.activity_id,
            decision.current_revision_id,
            decision.expected_head_version,
            outcome,
            result_revision_id,
            None if not materials else materials[0].material_id,
        ),
    )


async def _insert_capability_requests(
    unit_of_work: PostgreSQLUnitOfWork,
    *,
    snapshot: SubjectCommitSnapshot,
    commit_id: SubjectCommitId,
    requests: tuple[CapabilityRequestDraft, ...],
) -> None:
    connection = unit_of_work._connection_for_repository()  # pyright: ignore[reportPrivateUsage]
    for draft in requests:
        catalog = await (
            await connection.execute(
                """
                SELECT capability_id, operation_class
                FROM armi.capabilities
                WHERE capability_kind = %s
                """,
                (draft.capability.value,),
            )
        ).fetchone()
        if catalog is None or str(catalog[1]) != draft.operation.value:
            raise SubjectCommitViolation("SUBJECT-CAPABILITY-CATALOG")
        request_id = uuid7()
        scope = draft.scope
        if isinstance(scope, CreatorSceneReplyScope):
            if (
                scope.subject_id != snapshot.subject_id
                or scope.scene_id != snapshot.scene_id
                or scope.creator_party_id != snapshot.creator_party_id
            ):
                raise SubjectCommitViolation("SUBJECT-CAPABILITY-SCOPE")
            columns = (
                scope.audience_scope,
                scope.data_scope,
                scope.purpose,
                None,
                None,
                None,
                scope.valid_for_seconds,
                scope.max_uses,
                scope.max_payload_bytes,
            )
        else:
            columns = (
                None,
                None,
                "delegate_codex_work",
                scope.workspace_scope,
                scope.artifact_scope,
                scope.network_access,
                scope.valid_for_seconds,
                scope.max_uses,
                None,
            )
        inserted = await (
            await connection.execute(
                """
            INSERT INTO armi.capability_requests (
                capability_request_id, subject_commit_id, proposal_ref,
                subject_id, interaction_scene_id, creator_party_id,
                capability_id, capability_kind, operation_class,
                audience_scope, data_scope, purpose, workspace_scope,
                artifact_scope, network_access, requested_valid_for_seconds,
                requested_max_uses, requested_max_payload_bytes) VALUES (
                %s, %s, %s, %s, %s, %s, %s, %s, %s,
                %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (subject_id, capability_kind, operation_class)
            WHERE capability_kind = 'codex.delegated-work'
              AND current_status IN ('pending', 'granted', 'limited')
            DO NOTHING
            RETURNING capability_request_id
                """,
                (
                    request_id,
                    commit_id.value,
                    draft.proposal_ref,
                    snapshot.subject_id,
                    snapshot.scene_id,
                    snapshot.creator_party_id,
                    catalog[0],
                    draft.capability.value,
                    draft.operation.value,
                    *columns,
                ),
            )
        ).fetchone()
        if inserted is None:
            continue
        rows = await (
            await connection.execute(
                """
                SELECT basis.context_item_id
                FROM armi.cognitive_candidate_basis_links AS basis
                JOIN armi.cognitive_context_items AS item
                  ON item.context_item_id = basis.context_item_id
                 AND item.cognitive_episode_id = %s
                 AND item.disposition = 'included'
                WHERE basis.candidate_validation_id = %s
                  AND basis.proposal_ref = %s
                ORDER BY basis.ordinal
                """,
                (snapshot.episode_id, snapshot.validation_id, draft.proposal_ref),
            )
        ).fetchall()
        if len(rows) != len(draft.basis_ordinals):
            raise SubjectCommitViolation("SUBJECT-CAPABILITY-BASIS")
        for ordinal, row in enumerate(rows, 1):
            await connection.execute(
                """
                INSERT INTO armi.capability_request_basis_links (
                    capability_request_id, context_item_id, ordinal
                ) VALUES (%s, %s, %s)
                """,
                (request_id, row[0], ordinal),
            )
        await unit_of_work.audit.append(
            _audit(
                unit_of_work,
                snapshot,
                "capability.request.created",
                "capability_request",
                request_id,
                AuditResultStatus.APPLIED,
            )
        )
        if isinstance(scope, CreatorSceneReplyScope):
            await _grant_local_creator_reply(
                unit_of_work,
                snapshot=snapshot,
                request_id=request_id,
                capability_id=catalog[0],
                scope=scope,
            )


async def _grant_local_creator_reply(
    unit_of_work: PostgreSQLUnitOfWork,
    *,
    snapshot: SubjectCommitSnapshot,
    request_id: UUID,
    capability_id: UUID,
    scope: CreatorSceneReplyScope,
) -> None:
    """Authorize the subject's same-scene reply without a Creator approval loop."""

    connection = unit_of_work._connection_for_repository()  # pyright: ignore[reportPrivateUsage]
    now_row = await (
        await connection.execute("SELECT statement_timestamp()")
    ).fetchone()
    if now_row is None:
        raise SubjectCommitViolation("SUBJECT-DATABASE")
    now = now_row[0]
    grant_id = uuid7()
    decision_id = uuid7()
    command_digest = Digest.from_bytes(
        rfc8785.dumps(
            cast(
                Any,
                {
                    "schema_version": "armi.local-creator-reply-grant.v1",
                    "request_id": str(request_id),
                    "decision": "grant",
                    "reason": "same_scene_creator_conversation",
                },
            )
        )
    )
    await connection.execute(
        """
        INSERT INTO armi.permission_grants (
            grant_id, capability_request_id, creator_party_id,
            capability_id, subject_id, interaction_scene_id,
            operation_class, audience_scope, data_scope, purpose,
            workspace_scope, artifact_scope, network_access,
            valid_from, valid_until, max_uses, max_payload_bytes) VALUES (
            %s, %s, %s, %s, %s, %s, 'send', 'creator',
            'creator_visible_response', 'respond_to_creator',
            NULL, NULL, NULL, %s, %s, %s, %s)
        """,
        (
            grant_id,
            request_id,
            snapshot.creator_party_id,
            capability_id,
            snapshot.subject_id,
            snapshot.scene_id,
            now,
            now + timedelta(seconds=scope.valid_for_seconds),
            scope.max_uses,
            scope.max_payload_bytes,
        ),
    )
    await connection.execute(
        """
        UPDATE armi.capability_requests
        SET current_status = 'granted', request_version = 2,
            resolved_by_party_id = creator_party_id,
            resolution_reason_class = 'same_scene_creator_conversation',
            resolved_at = statement_timestamp()
        WHERE capability_request_id = %s
          AND current_status = 'pending' AND request_version = 1
        """,
        (request_id,),
    )
    await connection.execute(
        """
        INSERT INTO armi.capability_request_decisions (
            capability_decision_id, capability_request_id,
            creator_party_id, expected_request_version,
            resulting_request_version, decision_kind, command_digest,
            reason_code) VALUES (
            %s, %s, %s, 1, 2, 'grant', %s,
            'same_scene_creator_conversation')
        """,
        (
            decision_id,
            request_id,
            snapshot.creator_party_id,
            command_digest.value,
        ),
    )
    await unit_of_work.audit.append(
        _audit(
            unit_of_work,
            snapshot,
            "capability.request.granted",
            "capability_request",
            request_id,
            AuditResultStatus.APPLIED,
        )
    )


async def _insert_response_intent(
    unit_of_work: PostgreSQLUnitOfWork,
    *,
    relationships: RelationshipReadPort,
    relationship_policy: RelationshipPolicyPort,
    snapshot: SubjectCommitSnapshot,
    commit_id: SubjectCommitId,
    change_set: SubjectChangeSet,
    response_artifact: ArtifactRef | None,
) -> None:
    other_replies = tuple(
        item
        for item in change_set.action_choices
        if isinstance(item, OtherHumanReplyDraft)
    )
    endings = tuple(
        item
        for item in change_set.action_choices
        if isinstance(item, OtherHumanEndConversationDraft)
    )
    if snapshot.opportunity_purpose == "consider_other_human_input":
        if other_replies or endings:
            await _insert_other_human_action(
                unit_of_work,
                relationships=relationships,
                relationship_policy=relationship_policy,
                snapshot=snapshot,
                commit_id=commit_id,
                replies=other_replies,
                endings=endings,
                response_artifact=response_artifact,
            )
        else:
            await _insert_other_human_change_terminal_decision(
                unit_of_work,
                snapshot=snapshot,
                commit_id=commit_id,
                change_set=change_set,
                response_artifact=response_artifact,
            )
        return
    replies = tuple(
        item
        for item in change_set.action_choices
        if isinstance(item, CreatorReplyDraft)
    )
    if not replies:
        if response_artifact is not None:
            raise SubjectCommitViolation("SUBJECT-RESPONSE-ARTIFACT")
        return
    if len(replies) != 1 or response_artifact is None:
        raise SubjectCommitViolation("SUBJECT-RESPONSE-COUNT")
    reply = replies[0]
    if (
        reply.subject_id != snapshot.subject_id
        or reply.scene_id != snapshot.scene_id
        or reply.creator_party_id != snapshot.creator_party_id
    ):
        raise SubjectCommitViolation("SUBJECT-RESPONSE-SCOPE")
    connection = unit_of_work._connection_for_repository()  # pyright: ignore[reportPrivateUsage]
    item = await (
        await connection.execute(
            """
            SELECT validation_status
            FROM armi.cognitive_candidate_validation_items
            WHERE candidate_validation_id = %s AND proposal_ref = %s
              AND owner_kind = 'action'
            """,
            (snapshot.validation_id, reply.proposal_ref),
        )
    ).fetchone()
    if item is None or str(item[0]) != "accepted":
        raise SubjectCommitViolation("SUBJECT-RESPONSE-VALIDATION")
    action_id = uuid7()
    revision_id = uuid7()
    await connection.execute(
        """
        INSERT INTO armi.action_intents (
            action_intent_id, subject_id, scene_id,
            context_party_id, root_opportunity_id, purpose,
            current_revision_id, action_kind) VALUES (%s, %s, %s, %s, %s, 'respond_to_creator', NULL, 'party_response')
        """,
        (
            action_id,
            snapshot.subject_id,
            snapshot.scene_id,
            snapshot.creator_party_id,
            snapshot.root_opportunity_id,
        ),
    )
    await _finish_creator_response_intent(
        unit_of_work,
        connection=connection,
        snapshot=snapshot,
        commit_id=commit_id,
        reply=reply,
        response_artifact=response_artifact,
        action_id=action_id,
        revision_id=revision_id,
    )


async def _insert_other_human_change_terminal_decision(
    unit_of_work: PostgreSQLUnitOfWork,
    *,
    snapshot: SubjectCommitSnapshot,
    commit_id: SubjectCommitId,
    change_set: SubjectChangeSet,
    response_artifact: ArtifactRef | None,
) -> None:
    no_actions = tuple(
        item
        for item in change_set.action_choices
        if isinstance(item, FormalNoActionDraft)
    )
    if (
        snapshot.scene_id is None
        or snapshot.other_party_id is None
        or snapshot.creator_party_id is not None
        or response_artifact is not None
        or len(no_actions) > 1
        or len(no_actions) != len(change_set.action_choices)
    ):
        raise SubjectCommitViolation("SUBJECT-OTHER-HUMAN-TERMINAL")
    decision_kind = "silence" if no_actions else "defer"
    connection = unit_of_work._connection_for_repository()  # pyright: ignore[reportPrivateUsage]
    await connection.execute(
        """
        INSERT INTO armi.dialogue_decisions (
            dialogue_decision_id, opportunity_id,
            cognitive_episode_id, candidate_validation_id,
            subject_commit_id, subject_id, scene_id, context_party_id,
            decision_kind) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        """,
        (
            uuid7(),
            snapshot.opportunity_id,
            snapshot.episode_id,
            snapshot.validation_id,
            commit_id.value,
            snapshot.subject_id,
            snapshot.scene_id,
            snapshot.other_party_id,
            decision_kind,
        ),
    )


async def _insert_other_human_action(
    unit_of_work: PostgreSQLUnitOfWork,
    *,
    relationships: RelationshipReadPort,
    relationship_policy: RelationshipPolicyPort,
    snapshot: SubjectCommitSnapshot,
    commit_id: SubjectCommitId,
    replies: tuple[OtherHumanReplyDraft, ...],
    endings: tuple[OtherHumanEndConversationDraft, ...],
    response_artifact: ArtifactRef | None,
) -> None:
    if (
        snapshot.scene_id is None
        or snapshot.other_party_id is None
        or snapshot.creator_party_id is not None
        or len(replies) + len(endings) != 1
    ):
        raise SubjectCommitViolation("SUBJECT-OTHER-HUMAN-SCOPE")
    connection = unit_of_work._connection_for_repository()  # pyright: ignore[reportPrivateUsage]
    route = await (
        await connection.execute(
            """
            SELECT scene.scene_kind, scene.primary_party_id,
                   group_binding.external_binding_id,
                   person_binding.external_binding_id,
                   context_party.party_kind
            FROM armi.interaction_scenes AS scene
            JOIN armi.parties AS context_party ON context_party.party_id = %s
            LEFT JOIN armi.external_channel_bindings AS group_binding
              ON group_binding.scene_id = scene.scene_id
             AND group_binding.party_id = scene.primary_party_id
             AND group_binding.external_kind = 'group'
             AND group_binding.status = 'active'
            LEFT JOIN armi.external_channel_bindings AS person_binding
              ON person_binding.scene_id = scene.scene_id
             AND person_binding.party_id = %s
             AND person_binding.external_kind = 'person'
             AND person_binding.status = 'active'
            WHERE scene.scene_id = %s AND scene.subject_id = %s
              AND scene.current_status = 'open'
              AND scene.scene_kind IN ('other_human_dialogue', 'group_dialogue')
            """,
            (
                snapshot.other_party_id,
                snapshot.other_party_id,
                snapshot.scene_id,
                snapshot.subject_id,
            ),
        )
    ).fetchone()
    if route is None:
        raise SubjectCommitViolation("SUBJECT-OTHER-HUMAN-SCENE")
    group_route = str(route[0]) == "group_dialogue"
    private_route = str(route[0]) == "other_human_dialogue" and route[3] is not None
    relationship_scope = (
        "creator_social" if route[4] == "creator" else "other_human_social"
    )
    if group_route:
        if route[2] is None:
            raise SubjectCommitViolation("SUBJECT-OTHER-HUMAN-SCENE")
    elif route[1] != snapshot.other_party_id or route[2] is not None:
        raise SubjectCommitViolation("SUBJECT-OTHER-HUMAN-SCENE")
    destination_party_id = route[1] if group_route else snapshot.other_party_id
    destination_binding_id = route[2] if group_route else route[3]
    action = replies[0] if replies else endings[0]
    if (
        action.subject_id != snapshot.subject_id
        or action.scene_id != snapshot.scene_id
        or action.other_party_id != snapshot.other_party_id
    ):
        raise SubjectCommitViolation("SUBJECT-OTHER-HUMAN-SCOPE")
    decision_id = uuid7()
    if endings:
        if group_route:
            raise SubjectCommitViolation("SUBJECT-OTHER-HUMAN-GROUP-END")
        if response_artifact is not None:
            raise SubjectCommitViolation("SUBJECT-RESPONSE-ARTIFACT")
        updated = await (
            await connection.execute(
                """
                UPDATE armi.interaction_scenes
                SET current_status = 'closed', closed_at = statement_timestamp(),
                    scene_version = scene_version + 1
                WHERE scene_id = %s AND subject_id = %s
                  AND primary_party_id = %s
                  AND scene_kind = 'other_human_dialogue'
                  AND current_status = 'open'
                RETURNING scene_id
                """,
                (snapshot.scene_id, snapshot.subject_id, snapshot.other_party_id),
            )
        ).fetchone()
        if updated is None:
            raise SubjectCommitViolation("SUBJECT-OTHER-HUMAN-SCENE")
        await connection.execute(
            """
            INSERT INTO armi.dialogue_decisions (
                dialogue_decision_id, opportunity_id,
                cognitive_episode_id, candidate_validation_id,
                subject_commit_id, subject_id, scene_id, context_party_id,
                decision_kind) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'end_conversation')
            """,
            (
                decision_id,
                snapshot.opportunity_id,
                snapshot.episode_id,
                snapshot.validation_id,
                commit_id.value,
                snapshot.subject_id,
                snapshot.scene_id,
                snapshot.other_party_id,
            ),
        )
        return
    reply = replies[0]
    if response_artifact is None:
        raise SubjectCommitViolation("SUBJECT-RESPONSE-ARTIFACT")
    relationship = await relationships.current_for_party(
        unit_of_work.transaction,
        subject_id=snapshot.subject_id,
        generation_id=snapshot.generation_id,
        other_party_id=snapshot.other_party_id,
        scope=relationship_scope,
    )
    if relationship is not None and not relationship_policy.allows_snapshot_contact(
        relationship
    ):
        raise SubjectCommitViolation("SUBJECT-RELATIONSHIP-BOUNDARY")
    action_id = uuid7()
    revision_id = uuid7()
    operation_id = uuid7()
    effect_id = uuid7()
    capability_kind = (
        "external.group.message.send"
        if group_route
        else "external.private.message.send"
        if private_route
        else "local.other-human-inbox.deliver"
    )
    audience_scope = "social_group" if group_route else "other_human"
    effect_kind = (
        "external_group_delivery"
        if group_route
        else "external_private_delivery"
        if private_route
        else "local_inbox_delivery"
    )
    authorization_basis = (
        "runtime_configuration" if group_route or private_route else "runtime_builtin"
    )
    destination_kind = (
        "external_group"
        if group_route
        else "external_private"
        if private_route
        else "other_human_inbox"
    )
    await connection.execute(
        """
        INSERT INTO armi.action_intents (
            action_intent_id, subject_id, scene_id, context_party_id,
            root_opportunity_id, purpose, current_revision_id, action_kind) VALUES (%s, %s, %s, %s, %s, 'respond_to_other_human', NULL, 'party_response')
        """,
        (
            action_id,
            snapshot.subject_id,
            snapshot.scene_id,
            snapshot.other_party_id,
            snapshot.root_opportunity_id,
        ),
    )
    await connection.execute(
        """
        INSERT INTO armi.action_intent_revisions (
            action_intent_revision_id, action_intent_id,
            revision_no, response_artifact_id, response_digest, response_bytes,
            media_type, capability_kind, operation_class, audience_scope,
            data_scope, purpose, candidate_validation_id, proposal_ref,
            subject_commit_id) VALUES (%s, %s, 1, %s, %s, %s, 'text/plain',
            %s, 'send', %s,
            'declared_party_response', 'respond_to_other_human', %s, %s, %s)
        """,
        (
            revision_id,
            action_id,
            response_artifact.artifact_id.value,
            response_artifact.content_digest.value,
            len(reply.content_bytes),
            capability_kind,
            audience_scope,
            snapshot.validation_id,
            reply.proposal_ref,
            commit_id.value,
        ),
    )
    await connection.execute(
        """UPDATE armi.action_intents
           SET current_revision_id = %s
           WHERE action_intent_id = %s""",
        (revision_id, action_id),
    )
    await connection.execute(
        """
        INSERT INTO armi.dialogue_decisions (
            dialogue_decision_id, opportunity_id,
            cognitive_episode_id, candidate_validation_id,
            subject_commit_id, subject_id, scene_id, context_party_id,
            proposal_ref, decision_kind, action_intent_id, effect_id) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, 'reply', %s, NULL)
        """,
        (
            decision_id,
            snapshot.opportunity_id,
            snapshot.episode_id,
            snapshot.validation_id,
            commit_id.value,
            snapshot.subject_id,
            snapshot.scene_id,
            snapshot.other_party_id,
            reply.proposal_ref,
            action_id,
        ),
    )
    await connection.execute(
        """
        INSERT INTO armi.action_operations (
            operation_id, root_opportunity_id, subject_id, scene_id,
            context_party_id, action_intent_id, dialogue_decision_id,
            phase, outcome, operation_kind) VALUES (%s, %s, %s, %s, %s, %s, %s,
                  'admitted', NULL, 'party_response')
        """,
        (
            operation_id,
            snapshot.root_opportunity_id,
            snapshot.subject_id,
            snapshot.scene_id,
            snapshot.other_party_id,
            action_id,
            decision_id,
        ),
    )
    registration_digest = Digest.from_bytes(
        rfc8785.dumps(
            {
                "effect_id": str(effect_id),
                "revision_id": str(revision_id),
                "scene_id": str(snapshot.scene_id),
                "other_party_id": str(snapshot.other_party_id),
                "destination_party_id": str(destination_party_id),
                "destination_binding_id": (
                    None
                    if destination_binding_id is None
                    else str(destination_binding_id)
                ),
                "response_digest": response_artifact.content_digest.value,
            }
        )
    )
    await connection.execute(
        """
        INSERT INTO armi.effects (
            effect_id, action_intent_revision_id, action_intent_id,
            operation_id, subject_id, scene_id,
            context_party_id, payload_artifact_id, payload_digest, payload_bytes,
            effect_kind, capability_kind, operation_class, audience_scope,
            data_scope, purpose, authorization_basis, destination_kind,
            destination_party_id, destination_binding_id,
            status, verification_status,
            registration_digest, trace_id) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
            %s, %s, 'send', %s, 'declared_party_response',
            'respond_to_other_human', %s, %s,
            %s, %s, 'registered', 'not_started', %s, %s)
        """,
        (
            effect_id,
            revision_id,
            action_id,
            operation_id,
            snapshot.subject_id,
            snapshot.scene_id,
            snapshot.other_party_id,
            response_artifact.artifact_id.value,
            response_artifact.content_digest.value,
            len(reply.content_bytes),
            effect_kind,
            capability_kind,
            audience_scope,
            authorization_basis,
            destination_kind,
            destination_party_id,
            destination_binding_id,
            registration_digest.value,
            snapshot.trace_id.value,
        ),
    )
    await connection.execute(
        """
        INSERT INTO armi.effect_outbox_items (
            effect_outbox_item_id, effect_id, message_kind,
            status, dispatch_deadline, max_attempts) VALUES (
            %s, %s, 'effect.dispatch', 'ready',
            statement_timestamp() + interval '1 hour', %s)
        """,
        (uuid7(), effect_id, 1 if group_route or private_route else 2),
    )
    await connection.execute(
        """
        UPDATE armi.action_operations
        SET phase = 'effect_registered', effect_id = %s,
            effect_registered_at = statement_timestamp()
        WHERE operation_id = %s AND phase = 'admitted' AND outcome IS NULL
        """,
        (effect_id, operation_id),
    )
    await connection.execute(
        """UPDATE armi.dialogue_decisions SET effect_id = %s
           WHERE dialogue_decision_id = %s AND effect_id IS NULL""",
        (effect_id, decision_id),
    )


async def _finish_creator_response_intent(
    unit_of_work: PostgreSQLUnitOfWork,
    *,
    connection: Any,
    snapshot: SubjectCommitSnapshot,
    commit_id: SubjectCommitId,
    reply: CreatorReplyDraft,
    response_artifact: ArtifactRef,
    action_id: UUID,
    revision_id: UUID,
) -> None:
    decision_id = uuid7()
    await connection.execute(
        """
        INSERT INTO armi.action_intent_revisions (
            action_intent_revision_id, action_intent_id, revision_no,
            response_artifact_id, response_digest, response_bytes,
            media_type, capability_kind, operation_class, audience_scope,
            data_scope, purpose, candidate_validation_id, proposal_ref,
            subject_commit_id) VALUES (
            %s, %s, 1, %s, %s, %s, 'text/plain',
            'creator.scene.reply', 'send', 'creator',
            'creator_visible_response', 'respond_to_creator',
            %s, %s, %s)
        """,
        (
            revision_id,
            action_id,
            response_artifact.artifact_id.value,
            response_artifact.content_digest.value,
            len(reply.content_bytes),
            snapshot.validation_id,
            reply.proposal_ref,
            commit_id.value,
        ),
    )
    await connection.execute(
        "UPDATE armi.action_intents SET current_revision_id = %s WHERE action_intent_id = %s",
        (revision_id, action_id),
    )
    await connection.execute(
        """
        INSERT INTO armi.dialogue_decisions (
            dialogue_decision_id, opportunity_id, cognitive_episode_id,
            candidate_validation_id, subject_commit_id, subject_id, scene_id,
            context_party_id, proposal_ref, decision_kind, action_intent_id) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, 'reply', %s)
        """,
        (
            decision_id,
            snapshot.opportunity_id,
            snapshot.episode_id,
            snapshot.validation_id,
            commit_id.value,
            snapshot.subject_id,
            snapshot.scene_id,
            snapshot.creator_party_id,
            reply.proposal_ref,
            action_id,
        ),
    )
    now_row = await (
        await connection.execute("SELECT statement_timestamp()")
    ).fetchone()
    if now_row is None:
        raise SubjectCommitViolation("SUBJECT-DATABASE")
    work_id = WorkId(uuid7())
    await unit_of_work.work.enqueue(
        WorkDraft(
            work_id,
            _RESPONSE_WORK_KIND,
            WorkOwner("action_intent", action_id),
            IdempotencyKey(f"response-admit:{action_id}"),
            response_artifact.content_digest,
            50,
            Instant(now_row[0]),
            Instant(now_row[0] + timedelta(seconds=3600)),
            2,
            snapshot.trace_id,
            SubjectId(snapshot.subject_id),
            WorkPayloadRef("action_intent", action_id),
        )
    )
    await connection.execute(
        """
        INSERT INTO armi.action_operations (
            operation_id, root_opportunity_id, subject_id,
            scene_id, context_party_id, action_intent_id, dialogue_decision_id,
            admission_work_id, phase, outcome, operation_kind) VALUES (%s, %s, %s, %s, %s, %s, %s, %s,
                  'admission_pending', NULL, 'party_response')
        """,
        (
            snapshot.root_opportunity_id,
            snapshot.root_opportunity_id,
            snapshot.subject_id,
            snapshot.scene_id,
            snapshot.creator_party_id,
            action_id,
            decision_id,
            work_id.value,
        ),
    )
    await unit_of_work.audit.append(
        _audit(
            unit_of_work,
            snapshot,
            "cognition.response.intent.recorded",
            "action_intent",
            action_id,
            AuditResultStatus.ACCEPTED,
        )
    )


async def _insert_web_research_intent(
    unit_of_work: PostgreSQLUnitOfWork,
    *,
    snapshot: SubjectCommitSnapshot,
    commit_id: SubjectCommitId,
    requests: tuple[WebResearchRequestDraft, ...],
    query_artifact: ArtifactRef | None,
) -> None:
    if not requests:
        if query_artifact is not None:
            raise SubjectCommitViolation("SUBJECT-WEB-RESEARCH-ARTIFACT")
        return
    if len(requests) != 1 or query_artifact is None:
        raise SubjectCommitViolation("SUBJECT-WEB-RESEARCH-COUNT")
    request = requests[0]
    connection = unit_of_work._connection_for_repository()  # pyright: ignore[reportPrivateUsage]
    item = await (
        await connection.execute(
            """
            SELECT validation_status
            FROM armi.cognitive_candidate_validation_items
            WHERE candidate_validation_id = %s AND proposal_ref = %s
              AND owner_kind = 'web_research'
            """,
            (snapshot.validation_id, request.proposal_ref),
        )
    ).fetchone()
    if item is None or str(item[0]) != "accepted":
        raise SubjectCommitViolation("SUBJECT-WEB-RESEARCH-VALIDATION")
    now_row = await (
        await connection.execute("SELECT statement_timestamp()")
    ).fetchone()
    if now_row is None:
        raise SubjectCommitViolation("SUBJECT-DATABASE")
    intent_id = uuid7()
    work_id = WorkId(uuid7())
    await unit_of_work.work.enqueue(
        WorkDraft(
            work_id,
            "web.observation.admit",
            WorkOwner("web_research_intent", intent_id),
            IdempotencyKey(f"web-intent:{snapshot.opportunity_id}"),
            query_artifact.content_digest,
            40,
            Instant(now_row[0]),
            Instant(now_row[0] + timedelta(seconds=3600)),
            2,
            snapshot.trace_id,
            SubjectId(snapshot.subject_id),
            WorkPayloadRef("artifact", query_artifact.artifact_id.value),
        )
    )
    await connection.execute(
        """
        INSERT INTO armi.web_research_intents (
            web_research_intent_id, subject_commit_id, source_opportunity_id,
            subject_id, scene_id, creator_party_id, proposal_ref, purpose,
            operation_class, query_artifact_id, query_digest, idempotency_key,
            admission_work_id, status, trace_id) VALUES (
            %s, %s, %s, %s, %s, %s, %s, 'public_web_research',
            'search_read_public', %s, %s, %s, %s, 'pending', %s)
        """,
        (
            intent_id,
            commit_id.value,
            snapshot.opportunity_id,
            snapshot.subject_id,
            snapshot.scene_id,
            snapshot.creator_party_id,
            request.proposal_ref,
            query_artifact.artifact_id.value,
            query_artifact.content_digest.value,
            f"intent:{intent_id}",
            work_id.value,
            snapshot.trace_id.value,
        ),
    )
    await unit_of_work.audit.append(
        _audit(
            unit_of_work,
            snapshot,
            "web.research.intent.recorded",
            "web_research_intent",
            intent_id,
            AuditResultStatus.ACCEPTED,
        )
    )


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


async def _insert_codex_delegation_intent(
    unit_of_work: PostgreSQLUnitOfWork,
    *,
    snapshot: SubjectCommitSnapshot,
    commit_id: SubjectCommitId,
    delegations: tuple[CodexDelegationDraft, ...],
) -> None:
    if not delegations:
        return
    if len(delegations) != 1:
        raise SubjectCommitViolation("SUBJECT-CODEX-DELEGATION-COUNT")
    draft = delegations[0]
    connection = unit_of_work._connection_for_repository()  # pyright: ignore[reportPrivateUsage]
    validation = await (
        await connection.execute(
            """
            SELECT validation_status
            FROM armi.cognitive_candidate_validation_items
            WHERE candidate_validation_id = %s AND proposal_ref = %s
              AND owner_kind = 'codex_delegation'
            """,
            (snapshot.validation_id, draft.proposal_ref),
        )
    ).fetchone()
    source = await (
        await connection.execute(
            """
            SELECT task_manifest_digest, validator_id
            FROM armi.codex_task_sources
            WHERE codex_task_source_id = %s AND subject_id = %s
            """,
            (draft.task_source_id.value, snapshot.subject_id),
        )
    ).fetchone()
    if (
        validation is None
        or str(validation[0]) != "accepted"
        or source is None
        or str(source[0]) != draft.task_manifest_digest.value
        or str(source[1]) != draft.validator_id
    ):
        raise SubjectCommitViolation("SUBJECT-CODEX-DELEGATION-VALIDATION")
    action_id = uuid7()
    revision_id = uuid7()
    await connection.execute(
        """
        INSERT INTO armi.action_intents (
            action_intent_id, subject_id, scene_id,
            context_party_id, root_opportunity_id, purpose,
            action_kind, current_revision_id) VALUES (
            %s, %s, %s, %s, %s, 'delegate_codex_work',
            'codex_delegation', NULL)
        """,
        (
            action_id,
            snapshot.subject_id,
            snapshot.scene_id,
            snapshot.creator_party_id,
            snapshot.root_opportunity_id,
        ),
    )
    await connection.execute(
        """
        INSERT INTO armi.action_intent_revisions (
            action_intent_revision_id, action_intent_id, revision_no,
            capability_kind, operation_class, purpose,
            candidate_validation_id, proposal_ref, subject_commit_id,
            codex_task_source_id, task_manifest_digest, validator_id) VALUES (
            %s, %s, 1, 'codex.delegated-work', 'execute',
            'delegate_codex_work', %s, %s, %s, %s, %s, %s)
        """,
        (
            revision_id,
            action_id,
            snapshot.validation_id,
            draft.proposal_ref,
            commit_id.value,
            draft.task_source_id.value,
            draft.task_manifest_digest.value,
            draft.validator_id,
        ),
    )
    await connection.execute(
        "UPDATE armi.action_intents SET current_revision_id = %s WHERE action_intent_id = %s",
        (revision_id, action_id),
    )
    await connection.execute(
        """
        INSERT INTO armi.action_operations (
            operation_id, root_opportunity_id, subject_id,
            scene_id, context_party_id, action_intent_id,
            phase, outcome, operation_kind) VALUES (
            %s, %s, %s, %s, %s, %s,
            'admission_pending', NULL, 'codex_delegation')
        """,
        (
            snapshot.root_opportunity_id,
            snapshot.root_opportunity_id,
            snapshot.subject_id,
            snapshot.scene_id,
            snapshot.creator_party_id,
            action_id,
        ),
    )
    await unit_of_work.audit.append(
        _audit(
            unit_of_work,
            snapshot,
            "codex.delegation.intent.recorded",
            "action_intent",
            action_id,
            AuditResultStatus.ACCEPTED,
        )
    )


async def _insert_other_human_terminal_decision(
    connection: Any,
    *,
    snapshot: SubjectCommitSnapshot,
    application_id: CandidateApplicationId,
    status: CandidateApplicationStatus,
) -> None:
    if (
        snapshot.scene_id is None
        or snapshot.other_party_id is None
        or snapshot.creator_party_id is not None
        or status
        not in {
            CandidateApplicationStatus.NO_ACTION,
            CandidateApplicationStatus.DEFERRED,
        }
    ):
        raise SubjectCommitViolation("SUBJECT-OTHER-HUMAN-TERMINAL")
    await connection.execute(
        """
        INSERT INTO armi.dialogue_decisions (
            dialogue_decision_id, opportunity_id,
            cognitive_episode_id, candidate_validation_id,
            candidate_application_id, subject_id, scene_id, context_party_id,
            decision_kind) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        """,
        (
            uuid7(),
            snapshot.opportunity_id,
            snapshot.episode_id,
            snapshot.validation_id,
            application_id.value,
            snapshot.subject_id,
            snapshot.scene_id,
            snapshot.other_party_id,
            "silence" if status is CandidateApplicationStatus.NO_ACTION else "defer",
        ),
    )


async def _insert_formal_no_action(
    unit_of_work: PostgreSQLUnitOfWork,
    *,
    snapshot: SubjectCommitSnapshot,
    application_id: CandidateApplicationId,
    change_set: SubjectChangeSet,
) -> None:
    decisions = tuple(
        item
        for item in change_set.action_choices
        if isinstance(item, FormalNoActionDraft)
    )
    if len(decisions) != 1:
        raise SubjectCommitViolation("SUBJECT-NO-ACTION-COUNT")
    decision = decisions[0]
    connection = unit_of_work._connection_for_repository()  # pyright: ignore[reportPrivateUsage]
    rows = await (
        await connection.execute(
            """
            SELECT basis.context_item_id
            FROM armi.cognitive_candidate_basis_links AS basis
            JOIN armi.cognitive_candidate_validation_items AS item
              ON item.candidate_validation_id = basis.candidate_validation_id
             AND item.proposal_ref = basis.proposal_ref
             AND item.validation_status = 'accepted'
             AND item.owner_kind = 'action'
            WHERE basis.candidate_validation_id = %s AND basis.proposal_ref = %s
            ORDER BY basis.ordinal
            """,
            (snapshot.validation_id, decision.proposal_ref),
        )
    ).fetchall()
    if len(rows) != len(decision.basis_ordinals):
        raise SubjectCommitViolation("SUBJECT-NO-ACTION-BASIS")
    no_action_id = uuid7()
    await connection.execute(
        """
        INSERT INTO armi.dialogue_decisions (
            dialogue_decision_id, opportunity_id, candidate_application_id,
            candidate_validation_id, proposal_ref, decision_kind,
            reason_class, subject_id, scene_id, context_party_id) VALUES (
            %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """,
        (
            no_action_id,
            snapshot.root_opportunity_id,
            application_id.value,
            snapshot.validation_id,
            decision.proposal_ref,
            "silence" if decision.kind.value == "no_action" else decision.kind.value,
            decision.reason.value,
            snapshot.subject_id,
            snapshot.scene_id,
            snapshot.creator_party_id,
        ),
    )
    await connection.execute(
        """
        INSERT INTO armi.action_operations (
            operation_id, root_opportunity_id, subject_id,
            scene_id, context_party_id, dialogue_decision_id,
            phase, outcome, completed_at, operation_kind) VALUES (
            %s, %s, %s, %s, %s, %s, 'terminal', 'no_action',
            statement_timestamp(), 'party_response')
        """,
        (
            snapshot.root_opportunity_id,
            snapshot.root_opportunity_id,
            snapshot.subject_id,
            snapshot.scene_id,
            snapshot.creator_party_id,
            no_action_id,
        ),
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
