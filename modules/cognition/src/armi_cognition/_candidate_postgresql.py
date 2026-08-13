"""PostgreSQL ownership for deterministic cognition candidate validation."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import cast
from uuid import UUID, uuid7

from armi_activity.api import ActivityReadPort
from armi_capability.api import CapabilityRequestDraft
from armi_codex.api import CodexDelegationDraft, CodexTaskSourceReadPort
from armi_context.api import ContextCognitionReadPort
from armi_evidence.api import EvidenceId, EvidenceReadPort
from armi_expression.api import (
    CreatorReplyDraft,
    FormalNoActionDraft,
    OtherHumanEndConversationDraft,
    OtherHumanReplyDraft,
)
from armi_interaction.api import InteractionCognitionReadPort
from armi_kernel.application import (
    ArtifactId,
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
    CandidateViolation,
    WorkDraft,
    WorkId,
    WorkLease,
    WorkOwner,
    WorkPayloadRef,
    WorkRecord,
    WorkResultRef,
    WorkStatus,
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
    MaterialCandidateContextPort,
    MaterialCandidateSource,
    MaterialReadPort,
)
from armi_memory.api import (
    CandidateMemoryDraft,
    CandidateMemoryRevisionDraft,
    MemoryCandidateContextPort,
    MemoryReadPort,
)
from armi_mood.api import MoodReadPort
from armi_opportunity.api import (
    OpportunityCognitionSelectionPort,
    OpportunityContextReadPort,
)
from armi_prompt.api import PromptReadPort, PromptViolation
from armi_relationship.api import RelationshipReadPort
from armi_runtime_foundation import (
    PostgreSQLRuntimeUnitOfWork,
    PostgreSQLTransaction,
)
from armi_sleep.api import SleepReadPort
from armi_subject_state.api import SubjectStateReadPort
from armi_web_observation.api import WebResearchRequestDraft

from ._contracts import (
    CandidateValidationResult,
    CandidateValidationStatus,
    SubjectChangeSet,
)
from .api import CognitionArtifactCatalogPort, CognitionRuntimeStatePort

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
        "_catalog",
        "_codex",
        "_context",
        "_evidence",
        "_interaction",
        "_material_context",
        "_materials",
        "_memories",
        "_memory_context",
        "_mood",
        "_opportunity_context",
        "_opportunity_transitions",
        "_prompts",
        "_relationships",
        "_runtime_state",
        "_sleep",
        "_subject_state",
    )

    def __init__(
        self,
        relationships: RelationshipReadPort,
        sleep: SleepReadPort,
        activities: ActivityReadPort,
        material_context: MaterialCandidateContextPort,
        memory_context: MemoryCandidateContextPort,
        context: ContextCognitionReadPort,
        runtime_state: CognitionRuntimeStatePort,
        interaction: InteractionCognitionReadPort,
        opportunity_context: OpportunityContextReadPort,
        opportunity_transitions: OpportunityCognitionSelectionPort,
        evidence: EvidenceReadPort,
        codex: CodexTaskSourceReadPort,
        catalog: CognitionArtifactCatalogPort,
        memories: MemoryReadPort | None = None,
        mood: MoodReadPort | None = None,
        prompts: PromptReadPort | None = None,
        materials: MaterialReadPort | None = None,
        subject_state: SubjectStateReadPort | None = None,
    ) -> None:
        self._activities = activities
        self._catalog = catalog
        self._codex = codex
        self._context = context
        self._evidence = evidence
        self._interaction = interaction
        self._material_context = material_context
        self._memories = memories
        self._memory_context = memory_context
        self._mood = mood
        self._prompts = prompts
        self._materials = materials
        self._relationships = relationships
        self._runtime_state = runtime_state
        self._sleep = sleep
        self._subject_state = subject_state
        self._opportunity_context = opportunity_context
        self._opportunity_transitions = opportunity_transitions

    async def snapshot(
        self,
        unit_of_work: PostgreSQLRuntimeUnitOfWork,
        work: WorkRecord,
    ) -> CandidateEpisodeSnapshot:
        connection = unit_of_work.transaction
        if (
            work.status is not WorkStatus.LEASED
            or work.lease is None
            or work.draft.work_kind != _WORK_KIND
            or work.draft.owner.kind != "cognitive_episode"
            or work.draft.payload is None
            or work.draft.payload.kind != "model_attempt"
        ):
            raise CandidateViolation("CANDIDATE-WORK-STALE")
        row = await (
            await connection.execute(
                """
                SELECT
                    episode.cognitive_episode_id,
                    attempt.model_attempt_id,
                    episode.subject_id,
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
                    episode.opportunity_id
                FROM armi.cognitive_episodes AS episode
                JOIN armi.cognitive_attempts AS attempt
                  ON attempt.cognitive_episode_id = episode.cognitive_episode_id
                 AND attempt.model_attempt_id = %s
                WHERE episode.cognitive_episode_id = %s
                  AND episode.status IN ('model_returned', 'validating')
                  AND attempt.dispatch_status = 'settled'
                  AND attempt.result_status = 'succeeded'
                  AND attempt.response_artifact_id IS NOT NULL
                FOR UPDATE OF episode
                """,
                (
                    work.draft.payload.reference,
                    work.draft.owner.reference,
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
        state = await self._runtime_state.current_state(connection, subject_id=row[2])
        if (
            state.subject_version != int(row[4])
            or state.state_epoch != int(row[5])
            or state.bundle_activation_id != row[3]
        ):
            raise CandidateViolation("CANDIDATE-SUBJECT-STALE")
        context_items = await self._context.candidate_bases(
            connection, episode_id=row[0]
        )
        bases = tuple(item.basis for item in context_items)
        basis_item_ids = tuple(
            (item.basis.ordinal, item.context_item_id) for item in context_items
        )
        interaction = await self._interaction.cognition_snapshot(
            connection,
            subject_id=row[2],
            scene_id=row[7],
            context_party_id=row[8],
        )
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
        opportunity = await self._opportunity_context.context_snapshot(
            connection, opportunity_id=row[13]
        )
        codex_sources: tuple[tuple[UUID, Digest, str], ...] = ()
        if opportunity.evidence_id is not None:
            evidence = await self._evidence.snapshot(
                connection, evidence_id=EvidenceId(opportunity.evidence_id)
            )
            if evidence.codex_task_source_id is not None:
                source = await self._codex.task_source(
                    connection, task_source_id=evidence.codex_task_source_id
                )
                codex_sources = (
                    (
                        source.task_source_id,
                        source.task_manifest_digest,
                        source.validator_id,
                    ),
                )
        activity_row = await self._activities.candidate_head(
            unit_of_work.transaction,
            activity_id=opportunity.activity_id,
            expected_revision_id=(
                opportunity.source_ref
                if opportunity.source_kind == "activity_revision"
                else None
            ),
            expected_revision_no=(
                opportunity.source_version
                if opportunity.source_kind == "activity_revision"
                else None
            ),
        )
        maintenance = await self._sleep.candidate_maintenance(
            connection, episode_id=row[0]
        )
        if self._memories is None:
            raise CandidateViolation("CANDIDATE-MEMORY-CONTEXT")
        memory_context_sources = await self._memory_context.memory_sources(
            connection, episode_id=row[0]
        )
        memory_rows = await self._memories.candidate_context(
            connection, subject_id=row[2], sources=memory_context_sources
        )
        relationship_basis = next(
            (
                item
                for item in bases
                if item.section == "relationship"
                and item.item_kind == "current_relationship"
            ),
            None,
        )
        relationship_snapshot = (
            None
            if relationship_basis is None or row[8] is None
            else await self._relationships.current_for_party(
                unit_of_work.transaction,
                subject_id=row[2],
                generation_id=state.generation_id,
                other_party_id=row[8],
                scope=(
                    "other_human_social"
                    if row[12] == "consider_other_human_input"
                    else "creator_social"
                ),
                expected_head_version=relationship_basis.source_version,
            )
        )
        if relationship_basis is not None and (
            relationship_snapshot is None
            or relationship_snapshot.relationship_id != relationship_basis.source_ref
        ):
            raise CandidateViolation("CANDIDATE-RELATIONSHIP-CONTEXT")
        if self._materials is None:
            raise CandidateViolation("CANDIDATE-MATERIAL-OWNER")
        material_context_sources = await self._material_context.material_sources(
            unit_of_work.transaction,
            episode_id=row[0],
        )
        material_rows = await self._materials.candidate_sources(
            unit_of_work.transaction,
            subject_id=row[2],
            generation_id=state.generation_id,
            sources=material_context_sources,
        )
        if self._prompts is None:
            raise CandidateViolation("CANDIDATE-SUBJECT-PROMPT-CONTEXT")
        prompt_basis = next(
            (
                item
                for item in bases
                if item.section == "prompt"
                and item.item_kind == "subject_prompt"
                and item.trust_class == "policy"
            ),
            None,
        )
        try:
            subject_prompt = await self._prompts.candidate_subject(
                unit_of_work.transaction,
                subject_id=row[2],
                expected_revision_id=(
                    None if prompt_basis is None else prompt_basis.source_ref
                ),
                expected_revision_no=(
                    None if prompt_basis is None else prompt_basis.source_version
                ),
            )
        except PromptViolation:
            raise CandidateViolation("CANDIDATE-SUBJECT-PROMPT-CONTEXT") from None
        creator_party_id, other_party_id = _relationship_party_ids(
            str(row[12]),
            row[8],
        )
        return CandidateEpisodeSnapshot(
            row[0],
            row[1],
            row[2],
            state.generation_id,
            row[3],
            int(row[4]),
            int(row[5]),
            Digest(str(row[6])),
            row[7],
            creator_party_id,
            other_party_id,
            await self._artifact_ref(unit_of_work, row[9]),
            str(row[10]),
            TraceId(str(row[11])),
            tuple(bases),
            tuple(basis_item_ids),
            components,
            str(row[12]),
            codex_sources,
            row[13],
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
            interaction.subject_party_id,
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
                subject_prompt.prompt_document_id,
                subject_prompt.current_revision_id,
                subject_prompt.revision_no,
            ),
            None if maintenance is None else maintenance.session_id,
            None if maintenance is None else maintenance.current_revision_id,
            None if maintenance is None else maintenance.head_version,
            None if maintenance is None else maintenance.phase.value,
            interaction.scene_kind,
            interaction.context_party_kind,
        )

    async def fail(
        self,
        unit_of_work: PostgreSQLRuntimeUnitOfWork,
        *,
        work: WorkRecord,
        error_code: str,
    ) -> None:
        """Terminally fail deterministic validation work and its episode."""

        if (
            work.status is not WorkStatus.LEASED
            or work.lease is None
            or work.draft.work_kind != _WORK_KIND
            or work.draft.owner.kind != "cognitive_episode"
        ):
            raise CandidateViolation("CANDIDATE-WORK-STALE")
        connection = unit_of_work.transaction
        lease = work.lease
        episode_id = work.draft.owner.reference
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
        unit_of_work: PostgreSQLRuntimeUnitOfWork,
        *,
        lease: WorkLease,
        snapshot: CandidateEpisodeSnapshot,
        result: CandidateValidationResult,
        validator_identity: str,
        change_set_artifact: ArtifactRef | None,
    ) -> None:
        connection = unit_of_work.transaction
        _assert_lease(lease, snapshot)
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
        if result.status is CandidateValidationStatus.REJECTED and (
            snapshot.opportunity_id is None
            or not await self._opportunity_transitions.resolve_cognition_failure(
                connection, opportunity_id=snapshot.opportunity_id
            )
        ):
            raise CandidateViolation("CANDIDATE-OPPORTUNITY-STATE")
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

    async def _artifact_ref(
        self,
        unit_of_work: PostgreSQLRuntimeUnitOfWork,
        artifact_id: UUID,
    ) -> ArtifactRef:
        ref = await self._catalog.retained_ref(unit_of_work, ArtifactId(artifact_id))
        if ref is None:
            raise CandidateViolation("CANDIDATE-ARTIFACT")
        return ref


async def _insert_items(
    connection: PostgreSQLTransaction,
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
            CandidateExactLifeQueryDraft,
            CandidateRejection,
        ),
    ):
        return value.fact_class
    return CandidateFactClass.INFERENCE


def _assert_lease(
    lease: WorkLease,
    snapshot: CandidateEpisodeSnapshot,
) -> None:
    if lease.token <= 0 or snapshot.episode_id.version != 7:
        raise CandidateViolation("CANDIDATE-WORK-STALE")


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
