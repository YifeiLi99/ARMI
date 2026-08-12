"""PostgreSQL ownership for deterministic cognition candidate validation."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import Any, cast
from uuid import UUID, uuid7

from armi_activity.api import ActivityReadPort
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
    CandidateBasis,
    CandidateExactLifeQueryDraft,
    CandidateExperienceDraft,
    CandidateFactClass,
    CandidateOwner,
    CandidateOwnerDraft,
    CandidateRejection,
    CandidateSubjectPromptDraft,
    CandidateValidationResult,
    CandidateValidationStatus,
    CandidateViolation,
    CapabilityRequestDraft,
    CodexDelegationDraft,
    CreatorReplyDraft,
    FormalNoActionDraft,
    OtherHumanEndConversationDraft,
    OtherHumanReplyDraft,
    SubjectChangeSet,
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
from armi_material.api import MaterialCandidateSource, MaterialReadPort
from armi_memory.api import (
    CandidateMemoryDraft,
    CandidateMemoryRevisionDraft,
    MemoryReadPort,
)
from armi_mood.api import MoodReadPort
from armi_relationship.api import RelationshipReadPort
from armi_sleep.api import SleepReadPort
from armi_subject_state.api import SubjectStateReadPort

from .unit_of_work import PostgreSQLUnitOfWork

_WORK_KIND = "cognition.candidate.validate"
_COMMIT_WORK_KIND = "cognition.subject.commit"


@dataclass(frozen=True, slots=True)
class CandidateEpisodeSnapshot:
    episode_id: UUID
    model_attempt_id: UUID
    subject_id: UUID
    generation_id: UUID
    bundle_activation_id: UUID
    base_subject_version: int
    base_state_epoch: int
    context_digest: Digest
    scene_id: UUID | None
    creator_party_id: UUID | None
    other_party_id: UUID | None
    response_artifact: ArtifactRef
    candidate_contract_version: str
    trace_id: TraceId
    bases: tuple[CandidateBasis, ...]
    basis_item_ids: tuple[tuple[int, UUID], ...]
    current_components: tuple[tuple[CandidateOwner, int, bytes], ...]
    purpose: str
    codex_task_sources: tuple[tuple[UUID, Digest, str], ...] = ()
    opportunity_id: UUID | None = None
    current_activity_id: UUID | None = None
    current_activity_revision_id: UUID | None = None
    current_activity_head_version: int | None = None
    current_activity_status: str | None = None
    current_memories: tuple[
        tuple[UUID, UUID, int, str, str, str, str | None, str], ...
    ] = ()
    subject_party_id: UUID | None = None
    current_relationship: (
        tuple[
            UUID,
            UUID,
            int,
            tuple[tuple[UUID, str, str], ...],
            str,
            tuple[tuple[str, str, str, str], ...],
            str,
            tuple[
                tuple[
                    UUID,
                    str,
                    str,
                    str,
                    str,
                    str,
                    str,
                ],
                ...,
            ],
            tuple[tuple[UUID, str, tuple[UUID, ...], str, str], ...],
        ]
        | None
    ) = None
    current_materials: tuple[MaterialCandidateSource, ...] = ()
    current_subject_prompt: tuple[UUID, UUID | None, int] | None = None
    current_maintenance_session_id: UUID | None = None
    current_maintenance_revision_id: UUID | None = None
    current_maintenance_head_version: int | None = None
    current_maintenance_phase: str | None = None
    scene_kind: str | None = None
    sender_party_kind: str | None = None


class PostgreSQLCandidateValidationRepository:
    """Freeze validation input and atomically preserve its result."""

    __slots__ = (
        "_activities",
        "_materials",
        "_memories",
        "_mood",
        "_relationships",
        "_sleep",
        "_subject_state",
    )

    def __init__(
        self,
        relationships: RelationshipReadPort,
        sleep: SleepReadPort,
        activities: ActivityReadPort,
        memories: MemoryReadPort | None = None,
        mood: MoodReadPort | None = None,
        materials: MaterialReadPort | None = None,
        subject_state: SubjectStateReadPort | None = None,
    ) -> None:
        self._activities = activities
        self._memories = memories
        self._mood = mood
        self._materials = materials
        self._relationships = relationships
        self._sleep = sleep
        self._subject_state = subject_state

    async def snapshot(
        self,
        unit_of_work: PostgreSQLUnitOfWork,
        lease: WorkLease,
    ) -> CandidateEpisodeSnapshot:
        connection = unit_of_work._connection_for_repository()  # pyright: ignore[reportPrivateUsage]
        row = await (
            await connection.execute(
                """
                SELECT
                    episode.cognitive_episode_id,
                    attempt.model_attempt_id,
                    episode.subject_id,
                    subject.current_generation_id,
                    episode.bundle_activation_id,
                    episode.base_subject_version,
                    episode.base_state_epoch,
                    episode.context_digest,
                    episode.scene_id,
                    episode.context_party_id,
                    attempt.response_artifact_id,
                    attempt.candidate_schema_version,
                    episode.trace_id,
                    episode.purpose,
                    episode.opportunity_id,
                    scene.scene_kind,
                    context_party.party_kind
                FROM armi.durable_work AS work
                JOIN armi.cognitive_episodes AS episode
                  ON episode.cognitive_episode_id = work.owner_ref
                JOIN armi.cognitive_attempts AS attempt
                  ON attempt.cognitive_episode_id = episode.cognitive_episode_id
                 AND attempt.model_attempt_id = work.payload_ref
                JOIN armi.subjects AS subject
                  ON subject.subject_id = episode.subject_id
                LEFT JOIN armi.interaction_scenes AS scene
                  ON scene.scene_id = episode.scene_id
                LEFT JOIN armi.parties AS context_party
                  ON context_party.party_id = episode.context_party_id
                WHERE work.work_id = %s
                  AND work.work_kind = 'cognition.candidate.validate'
                  AND work.owner_kind = 'cognitive_episode'
                  AND work.payload_kind = 'model_attempt'
                  AND work.status = 'leased'
                  AND work.current_attempt_id = %s
                  AND work.lease_owner = %s
                  AND work.lease_token = %s
                  AND work.lease_expires_at > statement_timestamp()
                  AND episode.status IN ('model_returned', 'validating')
                  AND attempt.dispatch_status = 'settled'
                  AND attempt.result_status = 'succeeded'
                  AND attempt.response_artifact_id IS NOT NULL
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
            raise CandidateViolation("CANDIDATE-WORK-STALE")
        updated = await (
            await connection.execute(
                """
                UPDATE armi.cognitive_episodes
                SET status = 'validating'
                WHERE cognitive_episode_id = %s
                  AND status IN ('model_returned', 'validating')
                RETURNING cognitive_episode_id
                """,
                (row[0],),
            )
        ).fetchone()
        if updated is None:
            raise CandidateViolation("CANDIDATE-EPISODE-STATE")
        context_rows = await (
            await connection.execute(
                """
                SELECT
                    context_item_id, ordinal, section, item_kind,
                    source_ref, source_version,
                    trust_class, privacy_scope
                FROM armi.cognitive_context_items
                WHERE cognitive_episode_id = %s
                  AND disposition = 'included'
                ORDER BY ordinal
                """,
                (row[0],),
            )
        ).fetchall()
        bases: list[CandidateBasis] = []
        basis_item_ids: list[tuple[int, UUID]] = []
        for item in context_rows:
            complete_source = all(value is not None for value in item[4:6])
            bases.append(
                CandidateBasis(
                    int(item[1]),
                    str(item[2]),
                    str(item[3]),
                    item[4] if complete_source else None,
                    int(item[5]) if complete_source else None,
                    str(item[6]),
                    str(item[7]),
                )
            )
            basis_item_ids.append((int(item[1]), item[0]))
        if self._subject_state is None:
            raise CandidateViolation("CANDIDATE-SUBJECT-STATE-OWNER")
        component_rows = await self._subject_state.current_heads(
            unit_of_work.transaction, subject_id=row[2]
        )
        components = tuple(
            (
                CandidateOwner(item.kind.value),
                item.version,
                item.canonical_state,
            )
            for item in component_rows
        )
        if self._mood is None:
            raise CandidateViolation("CANDIDATE-MOOD-CONTEXT")
        mood = await self._mood.current(unit_of_work.transaction, subject_id=row[2])
        components = (
            *components,
            (CandidateOwner.MOOD, mood.version, mood.canonical_state),
        )
        codex_rows = await (
            await connection.execute(
                """
                SELECT source.codex_task_source_id,
                       source.task_manifest_digest, source.validator_id
                FROM armi.cognitive_episodes AS episode
                JOIN armi.opportunities AS opportunity
                  ON opportunity.opportunity_id=episode.opportunity_id
                JOIN armi.external_evidence AS evidence
                  ON evidence.evidence_id=opportunity.evidence_id
                JOIN armi.codex_task_sources AS source
                  ON source.codex_task_source_id=evidence.codex_task_source_id
                WHERE episode.cognitive_episode_id=%s
                """,
                (row[0],),
            )
        ).fetchall()
        activity_row = await self._activities.candidate_head(
            unit_of_work.transaction, episode_id=row[0]
        )
        maintenance = await self._sleep.candidate_maintenance(
            connection, episode_id=row[0]
        )
        if self._memories is None:
            raise CandidateViolation("CANDIDATE-MEMORY-CONTEXT")
        memory_rows = await self._memories.candidate_context(
            connection, subject_id=row[2], episode_id=row[0]
        )
        subject_party_row = await (
            await connection.execute(
                """
                SELECT party_id
                FROM armi.parties
                WHERE party_kind = 'subject'
                  AND represented_subject_id = %s
                """,
                (row[2],),
            )
        ).fetchone()
        if subject_party_row is None:
            raise CandidateViolation("CANDIDATE-RELATIONSHIP-CONTEXT")
        relationship_context_row = await (
            await connection.execute(
                """
                SELECT item.source_ref, item.source_version
                FROM armi.cognitive_context_items AS item
                WHERE item.cognitive_episode_id = %s
                  AND item.disposition = 'included'
                  AND item.section = 'relationship'
                  AND item.item_kind = 'current_relationship'
                  AND item.source_kind = 'relationship'
                """,
                (row[0],),
            )
        ).fetchone()
        relationship_snapshot = (
            None
            if relationship_context_row is None or row[9] is None
            else await self._relationships.current_for_party(
                unit_of_work.transaction,
                subject_id=row[2],
                generation_id=row[3],
                other_party_id=row[9],
                scope=(
                    "other_human_social"
                    if row[13] == "consider_other_human_input"
                    else "creator_social"
                ),
                expected_head_version=int(relationship_context_row[1]),
            )
        )
        if relationship_context_row is not None and (
            relationship_snapshot is None
            or relationship_snapshot.relationship_id != relationship_context_row[0]
        ):
            raise CandidateViolation("CANDIDATE-RELATIONSHIP-CONTEXT")
        if self._materials is None:
            raise CandidateViolation("CANDIDATE-MATERIAL-OWNER")
        material_rows = await self._materials.candidate_sources(
            unit_of_work.transaction,
            subject_id=row[2],
            generation_id=row[3],
            episode_id=row[0],
        )
        subject_prompt_row = await (
            await connection.execute(
                """
                SELECT document.prompt_document_id,
                       document.current_revision_id,
                       COALESCE(revision.revision_no, 0)
                FROM armi.prompt_documents AS document
                LEFT JOIN armi.prompt_revisions AS revision
                  ON revision.prompt_revision_id = document.current_revision_id
                 AND revision.prompt_document_id = document.prompt_document_id
                WHERE document.subject_id = %s
                  AND document.prompt_kind = 'subject_guidance'
                  AND document.write_authority = 'subject'
                  AND document.status = 'active'
                  AND (
                      document.current_revision_id IS NULL
                      OR EXISTS (
                          SELECT 1
                          FROM armi.cognitive_context_items AS item
                          WHERE item.cognitive_episode_id = %s
                            AND item.disposition = 'included'
                            AND item.section = 'prompt'
                            AND item.item_kind = 'subject_prompt'
                            AND item.source_kind = 'subject_prompt'
                            AND item.source_ref = document.current_revision_id
                            AND item.source_version = revision.revision_no
                      )
                  )
                """,
                (row[2], row[0]),
            )
        ).fetchone()
        if subject_prompt_row is None:
            raise CandidateViolation("CANDIDATE-SUBJECT-PROMPT-CONTEXT")
        creator_party_id, other_party_id = _relationship_party_ids(
            str(row[13]),
            row[9],
        )
        return CandidateEpisodeSnapshot(
            row[0],
            row[1],
            row[2],
            row[3],
            row[4],
            int(row[5]),
            int(row[6]),
            Digest(str(row[7])),
            row[8],
            creator_party_id,
            other_party_id,
            await _artifact_ref(connection, row[10]),
            str(row[11]),
            TraceId(str(row[12])),
            tuple(bases),
            tuple(basis_item_ids),
            components,
            str(row[13]),
            tuple((item[0], Digest(str(item[1])), str(item[2])) for item in codex_rows),
            row[14],
            None if activity_row is None else activity_row.activity_id,
            None if activity_row is None else activity_row.current_revision_id,
            None if activity_row is None else activity_row.head_version,
            None if activity_row is None else activity_row.status.value,
            tuple(
                (
                    item.memory_id,
                    item.current_revision_id,
                    item.head_version,
                    item.fact_class.value,
                    item.source_kind.value,
                    item.summary,
                    item.uncertainty,
                    item.accessibility.value,
                )
                for item in memory_rows
            ),
            subject_party_row[0],
            None
            if relationship_snapshot is None
            else (
                relationship_snapshot.relationship_id,
                relationship_snapshot.current_revision_id,
                relationship_snapshot.head_version,
                tuple(
                    (item.fact_id, item.kind.value, item.summary)
                    for item in relationship_snapshot.revision.facts
                ),
                relationship_snapshot.revision.interpretation,
                tuple(
                    (
                        item.party_role.value,
                        item.kind.value,
                        item.action.value,
                        item.summary,
                    )
                    for item in relationship_snapshot.revision.boundaries
                ),
                relationship_snapshot.revision.status.value,
                tuple(
                    (
                        item.commitment_id,
                        item.party_role.value,
                        item.scope,
                        item.content,
                        item.status.value,
                        item.last_event_kind.value,
                        item.last_event_summary,
                    )
                    for item in relationship_snapshot.revision.commitments
                ),
                tuple(
                    (
                        item.issue_id,
                        item.kind.value,
                        item.commitment_ids,
                        item.summary,
                        item.status.value,
                    )
                    for item in relationship_snapshot.revision.open_issues
                ),
            ),
            material_rows,
            (
                subject_prompt_row[0],
                subject_prompt_row[1],
                int(subject_prompt_row[2]),
            ),
            None if maintenance is None else maintenance.session_id,
            None if maintenance is None else maintenance.current_revision_id,
            None if maintenance is None else maintenance.head_version,
            None if maintenance is None else maintenance.phase.value,
            None if row[15] is None else str(row[15]),
            None if row[16] is None else str(row[16]),
        )

    async def fail(
        self,
        unit_of_work: PostgreSQLUnitOfWork,
        *,
        lease: WorkLease,
        error_code: str,
    ) -> None:
        """Terminally fail deterministic validation work and its episode."""

        connection = unit_of_work._connection_for_repository()  # pyright: ignore[reportPrivateUsage]
        row = await (
            await connection.execute(
                """
                SELECT work.owner_ref
                FROM armi.durable_work AS work
                WHERE work.work_id = %s
                  AND work.work_kind = 'cognition.candidate.validate'
                  AND work.owner_kind = 'cognitive_episode'
                  AND work.status = 'leased'
                  AND work.current_attempt_id = %s
                  AND work.lease_owner = %s
                  AND work.lease_token = %s
                  AND work.lease_expires_at >= statement_timestamp()
                FOR UPDATE OF work
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
            raise CandidateViolation("CANDIDATE-WORK-STALE")
        episode_id = row[0]
        await unit_of_work.work.fail(lease, error_code=error_code)
        updated = await (
            await connection.execute(
                """
                UPDATE armi.cognitive_episodes
                SET status = 'failed', failure_code = %s
                WHERE cognitive_episode_id = %s
                  AND status IN ('model_returned', 'validating')
                RETURNING cognitive_episode_id
                """,
                (error_code, episode_id),
            )
        ).fetchone()
        if updated is None:
            raise CandidateViolation("CANDIDATE-EPISODE-STATE")

    async def settle(
        self,
        unit_of_work: PostgreSQLUnitOfWork,
        *,
        lease: WorkLease,
        snapshot: CandidateEpisodeSnapshot,
        result: CandidateValidationResult,
        validator_identity: str,
        change_set_artifact: ArtifactRef | None,
    ) -> None:
        connection = unit_of_work._connection_for_repository()  # pyright: ignore[reportPrivateUsage]
        await _assert_lease(connection, lease, snapshot)
        fence = unit_of_work.runtime_fence
        if fence is None:
            raise CandidateViolation("CANDIDATE-FENCE")
        change_set = result.change_set
        await connection.execute(
            """
            INSERT INTO armi.cognitive_candidate_validations (
                candidate_validation_id, cognitive_episode_id, model_attempt_id,
                work_id, subject_id, life_generation_id, bundle_activation_id,
                base_subject_version, base_state_epoch, context_digest,
                candidate_contract_version, validator_identity, validation_status,
                final_disposition, change_set_artifact_id,
                accepted_count, rejected_count, error_code,
                validated_by_runtime_instance_id, validation_fence_token)
            VALUES (
                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                result.validation_id.value,
                snapshot.episode_id,
                snapshot.model_attempt_id,
                lease.work_id.value,
                snapshot.subject_id,
                snapshot.generation_id,
                snapshot.bundle_activation_id,
                snapshot.base_subject_version,
                snapshot.base_state_epoch,
                snapshot.context_digest.value,
                snapshot.candidate_contract_version,
                validator_identity,
                result.status.value,
                change_set.disposition.value if change_set else None,
                (
                    change_set_artifact.artifact_id.value
                    if change_set_artifact is not None
                    else None
                ),
                result.accepted_count,
                result.rejected_count,
                result.error_code,
                fence.runtime_instance_id.value,
                fence.fence_token,
            ),
        )
        if change_set is not None:
            await _insert_items(connection, result, snapshot)
        episode_status = (
            "candidate_rejected"
            if result.status is CandidateValidationStatus.REJECTED
            else "candidate_validated"
        )
        updated = await (
            await connection.execute(
                """
                UPDATE armi.cognitive_episodes
                SET status = %s,
                    final_disposition = %s,
                    failure_code = %s,
                    validated_at = statement_timestamp()
                WHERE cognitive_episode_id = %s
                  AND status = 'validating'
                RETURNING cognitive_episode_id
                """,
                (
                    episode_status,
                    change_set.disposition.value if change_set else None,
                    result.error_code,
                    snapshot.episode_id,
                ),
            )
        ).fetchone()
        if updated is None:
            raise CandidateViolation("CANDIDATE-EPISODE-STATE")
        if result.status is CandidateValidationStatus.REJECTED:
            resolved = await (
                await connection.execute(
                    """
                    UPDATE armi.opportunities
                    SET current_disposition = 'resolved',
                        resolved_at = statement_timestamp()
                    WHERE opportunity_id = %s
                      AND current_disposition = 'selected'
                    RETURNING opportunity_id
                    """,
                    (snapshot.opportunity_id,),
                )
            ).fetchone()
            if resolved is None:
                raise CandidateViolation("CANDIDATE-OPPORTUNITY-STATE")
            if snapshot.purpose == "consider_codex_result":
                operation = await (
                    await connection.execute(
                        """
                        UPDATE armi.action_operations AS operation
                        SET phase = 'terminal', outcome = 'rejected',
                            reason_code = %s,
                            completed_at = statement_timestamp()
                        FROM armi.codex_result_sources AS source
                        JOIN armi.codex_verification_results AS verification
                          ON verification.codex_verification_id =
                             source.codex_verification_id
                        WHERE source.opportunity_id = %s
                          AND operation.effect_id = verification.effect_id
                          AND operation.phase = 'result_pending'
                          AND operation.outcome IS NULL
                        RETURNING operation.operation_id
                        """,
                        (cast(str, result.error_code), snapshot.opportunity_id),
                    )
                ).fetchone()
                if operation is None:
                    raise CandidateViolation("CANDIDATE-CODEX-RESULT-LINK")
        if change_set is not None:
            artifact = cast(ArtifactRef, change_set_artifact)
            now_row = await (
                await connection.execute("SELECT statement_timestamp()")
            ).fetchone()
            if now_row is None:
                raise CandidateViolation("CANDIDATE-DATABASE")
            now = Instant(now_row[0])
            await unit_of_work.work.enqueue(
                WorkDraft(
                    WorkId(uuid7()),
                    _COMMIT_WORK_KIND,
                    WorkOwner("cognitive_episode", snapshot.episode_id),
                    IdempotencyKey(f"subject-commit:{snapshot.episode_id}"),
                    artifact.content_digest,
                    50,
                    now,
                    Instant(now.value + timedelta(seconds=3600)),
                    2,
                    snapshot.trace_id,
                    SubjectId(snapshot.subject_id),
                    WorkPayloadRef("candidate_validation", result.validation_id.value),
                )
            )
        await unit_of_work.work.complete(
            lease,
            WorkResultRef(
                "candidate_validation",
                result.validation_id.value,
            ),
        )
        await unit_of_work.audit.append(
            AuditDraft(
                AuditEventId(uuid7()),
                AuditReference("runtime", unit_of_work.environment_id),
                Purpose("cognition.candidate"),
                "cognition.candidate.validated",
                AuditReference(
                    "candidate_validation",
                    result.validation_id.value,
                ),
                (
                    AuditResultStatus.REJECTED
                    if result.status is CandidateValidationStatus.REJECTED
                    else AuditResultStatus.COMPLETED
                ),
                snapshot.trace_id,
                AuditSensitivity.PRIVATE,
                subject_id=SubjectId(snapshot.subject_id),
            )
        )


async def _insert_items(
    connection: Any,
    result: CandidateValidationResult,
    snapshot: CandidateEpisodeSnapshot,
) -> None:
    change_set = cast(SubjectChangeSet, result.change_set)
    item_id_by_ordinal = dict(snapshot.basis_item_ids)
    drafts = _validation_drafts(change_set)
    for ordinal, draft in enumerate(
        sorted(drafts, key=lambda item: item.proposal_ref), 1
    ):
        accepted = not isinstance(draft, CandidateRejection)
        owner = _owner(draft)
        fact_class = (
            draft.fact_class
            if isinstance(
                draft,
                (
                    CandidateExperienceDraft,
                    CandidateMemoryDraft,
                    CandidateMemoryRevisionDraft,
                    CandidateOwnerDraft,
                    CandidateRejection,
                ),
            )
            else None
        )
        await connection.execute(
            """
            INSERT INTO armi.cognitive_candidate_validation_items (
                candidate_validation_id, proposal_ref, atomic_group_ref,
                owner_kind, fact_class, validation_status, reason_code,
                ordinal)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                result.validation_id.value,
                draft.proposal_ref,
                draft.atomic_group_ref,
                owner.value,
                (fact_class or _implicit_fact_class(draft)).value,
                "accepted" if accepted else "rejected",
                None if accepted else draft.code,
                ordinal,
            ),
        )
        for link_ordinal, basis_ordinal in enumerate(draft.basis_ordinals, 1):
            context_item_id = item_id_by_ordinal.get(basis_ordinal)
            if context_item_id is None:
                raise CandidateViolation("CANDIDATE-BASIS-MISSING")
            await connection.execute(
                """
                INSERT INTO armi.cognitive_candidate_basis_links (
                    candidate_validation_id, proposal_ref,
                    context_item_id, ordinal
                )
                VALUES (%s, %s, %s, %s)
                """,
                (
                    result.validation_id.value,
                    draft.proposal_ref,
                    context_item_id,
                    link_ordinal,
                ),
            )


def _validation_drafts(
    change_set: SubjectChangeSet,
) -> tuple[
    CandidateExperienceDraft
    | CandidateMemoryDraft
    | CandidateMemoryRevisionDraft
    | CandidateOwnerDraft
    | CandidateSubjectPromptDraft
    | CandidateExactLifeQueryDraft
    | CapabilityRequestDraft
    | CreatorReplyDraft
    | OtherHumanReplyDraft
    | OtherHumanEndConversationDraft
    | FormalNoActionDraft
    | WebResearchRequestDraft
    | CodexDelegationDraft
    | CandidateRejection,
    ...,
]:
    return (
        *change_set.experiences,
        *change_set.owner_drafts,
        *change_set.prompts,
        *change_set.exact_life_queries,
        *change_set.capability_requests,
        *change_set.action_choices,
        *change_set.web_research_requests,
        *change_set.codex_delegations,
        *change_set.rejections,
    )


def _owner(
    value: CandidateExperienceDraft
    | CandidateMemoryDraft
    | CandidateMemoryRevisionDraft
    | CandidateOwnerDraft
    | CandidateSubjectPromptDraft
    | CandidateExactLifeQueryDraft
    | CapabilityRequestDraft
    | CreatorReplyDraft
    | OtherHumanReplyDraft
    | OtherHumanEndConversationDraft
    | FormalNoActionDraft
    | WebResearchRequestDraft
    | CodexDelegationDraft
    | CandidateRejection,
) -> CandidateOwner:
    if isinstance(value, CandidateExperienceDraft):
        return CandidateOwner.EXPERIENCE
    if isinstance(value, (CandidateMemoryDraft, CandidateMemoryRevisionDraft)):
        return CandidateOwner.MEMORY
    if isinstance(value, CandidateOwnerDraft):
        return CandidateOwner(value.owner)
    if isinstance(value, CandidateSubjectPromptDraft):
        return CandidateOwner.PROMPT
    if isinstance(value, CandidateExactLifeQueryDraft):
        return CandidateOwner.EXACT_LIFE_QUERY
    if isinstance(value, CapabilityRequestDraft):
        return CandidateOwner.CAPABILITY
    if isinstance(
        value,
        (
            CreatorReplyDraft,
            OtherHumanReplyDraft,
            OtherHumanEndConversationDraft,
            FormalNoActionDraft,
        ),
    ):
        return CandidateOwner.ACTION
    if isinstance(value, WebResearchRequestDraft):
        return CandidateOwner.WEB_RESEARCH
    if isinstance(value, CodexDelegationDraft):
        return CandidateOwner.CODEX_DELEGATION
    return value.owner


def _implicit_fact_class(
    value: CandidateExperienceDraft
    | CandidateMemoryDraft
    | CandidateMemoryRevisionDraft
    | CandidateOwnerDraft
    | CandidateSubjectPromptDraft
    | CandidateExactLifeQueryDraft
    | CapabilityRequestDraft
    | CreatorReplyDraft
    | OtherHumanReplyDraft
    | OtherHumanEndConversationDraft
    | FormalNoActionDraft
    | WebResearchRequestDraft
    | CodexDelegationDraft
    | CandidateRejection,
) -> CandidateFactClass:
    if isinstance(
        value,
        (
            CandidateExperienceDraft,
            CandidateMemoryDraft,
            CandidateMemoryRevisionDraft,
            CandidateOwnerDraft,
            CandidateSubjectPromptDraft,
            CandidateExactLifeQueryDraft,
            CandidateRejection,
        ),
    ):
        return value.fact_class
    return CandidateFactClass.INFERENCE


async def _assert_lease(
    connection: Any,
    lease: WorkLease,
    snapshot: CandidateEpisodeSnapshot,
) -> None:
    row = await (
        await connection.execute(
            """
            SELECT 1
            FROM armi.durable_work
            WHERE work_id = %s
              AND owner_ref = %s
              AND work_kind = 'cognition.candidate.validate'
              AND status = 'leased'
              AND current_attempt_id = %s
              AND lease_owner = %s
              AND lease_token = %s
              AND lease_expires_at > statement_timestamp()
            """,
            (
                lease.work_id.value,
                snapshot.episode_id,
                lease.attempt_id.value,
                lease.owner,
                lease.token,
            ),
        )
    ).fetchone()
    if row is None:
        raise CandidateViolation("CANDIDATE-WORK-STALE")


async def _artifact_ref(connection: Any, artifact_id: UUID) -> ArtifactRef:
    row = await (
        await connection.execute(
            """
            SELECT
                artifact_id, content_digest, media_type, byte_size,
                logical_kind, privacy_scope, integrity_status
            FROM armi.artifacts
            WHERE artifact_id = %s
              AND retention_status = 'retained'
            """,
            (artifact_id,),
        )
    ).fetchone()
    if row is None:
        raise CandidateViolation("CANDIDATE-ARTIFACT")
    return ArtifactRef(
        ArtifactId(row[0]),
        Digest(str(row[1])),
        int(row[3]),
        str(row[2]),
        str(row[4]),
        ArtifactPrivacyScope(str(row[5])),
        ArtifactIntegrityStatus(str(row[6])),
    )


def _relationship_party_ids(
    purpose: str,
    context_party_id: UUID | None,
) -> tuple[UUID | None, UUID | None]:
    if purpose == "consider_other_human_input":
        return None, context_party_id
    return context_party_id, None


__all__ = (
    "CandidateEpisodeSnapshot",
    "PostgreSQLCandidateValidationRepository",
)
