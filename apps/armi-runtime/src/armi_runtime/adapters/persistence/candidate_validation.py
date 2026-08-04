"""PostgreSQL ownership for deterministic cognition candidate validation."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import timedelta
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
    CandidateBasis,
    CandidateComponentDraft,
    CandidateExperienceDraft,
    CandidateFactClass,
    CandidateMemoryDraft,
    CandidateOwner,
    CandidateRejection,
    CandidateSleepDecisionDraft,
    CandidateValidationResult,
    CandidateValidationStatus,
    CandidateViolation,
    CapabilityRequestDraft,
    CodexDelegationDraft,
    CreatorReplyDraft,
    FormalNoActionDraft,
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
    resource_snapshot_digest: Digest | None = None


class PostgreSQLCandidateValidationRepository:
    """Freeze validation input and atomically preserve its result."""

    __slots__ = ()

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
                    episode.creator_party_id,
                    attempt.response_artifact_id,
                    attempt.candidate_schema_version,
                    episode.trace_id,
                    episode.purpose,
                    episode.opportunity_id
                FROM armi.durable_work AS work
                JOIN armi.cognitive_episodes AS episode
                  ON episode.cognitive_episode_id = work.owner_ref
                JOIN armi.cognitive_attempts AS attempt
                  ON attempt.cognitive_episode_id = episode.cognitive_episode_id
                 AND attempt.model_attempt_id = work.payload_ref
                JOIN armi.subjects AS subject
                  ON subject.subject_id = episode.subject_id
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
                    source_ref, source_version, source_digest,
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
            complete_source = all(value is not None for value in item[4:7])
            bases.append(
                CandidateBasis(
                    int(item[1]),
                    str(item[2]),
                    str(item[3]),
                    item[4] if complete_source else None,
                    int(item[5]) if complete_source else None,
                    Digest(str(item[6])) if complete_source else None,
                    str(item[7]),
                    str(item[8]),
                )
            )
            basis_item_ids.append((int(item[1]), item[0]))
        component_rows = await (
            await connection.execute(
                """
                SELECT
                    head.component_kind,
                    head.component_version,
                    revision.semantic_payload
                FROM armi.subject_component_heads AS head
                JOIN armi.subject_component_revisions AS revision
                  ON revision.component_revision_id = head.current_revision_id
                WHERE head.subject_id = %s
                  AND head.component_kind IN ('self', 'mind', 'life_mode')
                ORDER BY head.component_kind
                """,
                (row[2],),
            )
        ).fetchall()
        components = tuple(
            (
                CandidateOwner(str(item[0])),
                int(item[1]),
                rfc8785.dumps(item[2]),
            )
            for item in component_rows
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
        activity_row = await (
            await connection.execute(
                """
                SELECT opportunity.activity_id, activity.current_revision_id,
                       activity.head_version, revision.status
                FROM armi.cognitive_episodes AS episode
                JOIN armi.opportunities AS opportunity
                  ON opportunity.opportunity_id = episode.opportunity_id
                JOIN armi.activities AS activity
                  ON activity.activity_id = opportunity.activity_id
                JOIN armi.activity_revisions AS revision
                  ON revision.activity_revision_id = activity.current_revision_id
                WHERE episode.cognitive_episode_id = %s
                  AND episode.purpose = 'consider_activity_attention'
                  AND opportunity.source_ref = activity.current_revision_id
                """,
                (row[0],),
            )
        ).fetchone()
        resource_digest = (
            next(
                (
                    basis.source_digest
                    for basis in bases
                    if basis.item_kind == "resource_snapshot"
                    and basis.trust_class == "runtime_authority"
                ),
                None,
            )
            if str(row[13]) == "consider_activity_attention"
            else None
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
            row[9],
            await _artifact_ref(connection, row[10]),
            str(row[11]),
            TraceId(str(row[12])),
            tuple(bases),
            tuple(basis_item_ids),
            components,
            str(row[13]),
            tuple((item[0], Digest(str(item[1])), str(item[2])) for item in codex_rows),
            row[14],
            None if activity_row is None else activity_row[0],
            None if activity_row is None else activity_row[1],
            None if activity_row is None else int(activity_row[2]),
            None if activity_row is None else str(activity_row[3]),
            resource_digest,
        )

    async def settle(
        self,
        unit_of_work: PostgreSQLUnitOfWork,
        *,
        lease: WorkLease,
        snapshot: CandidateEpisodeSnapshot,
        result: CandidateValidationResult,
        candidate_digest: Digest,
        policy_digest: Digest,
        validator_identity: str,
        change_set_artifact_id: ArtifactId | None,
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
                candidate_contract_version, candidate_digest,
                validator_identity, policy_digest, validation_status,
                final_disposition, change_set_artifact_id, change_set_digest,
                accepted_count, rejected_count, error_code,
                validated_by_runtime_instance_id, validation_fence_token,
                schema_version
            )
            VALUES (
                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                %s, %s, %s, 1
            )
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
                candidate_digest.value,
                validator_identity,
                policy_digest.value,
                result.status.value,
                change_set.disposition.value if change_set else None,
                change_set_artifact_id.value if change_set_artifact_id else None,
                change_set.digest.value if change_set else None,
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
        if change_set is not None:
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
                    change_set.digest,
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
                request_digest=candidate_digest,
                response_digest=change_set.digest if change_set else None,
            )
        )


async def _insert_items(
    connection: Any,
    result: CandidateValidationResult,
    snapshot: CandidateEpisodeSnapshot,
) -> None:
    change_set = result.change_set
    assert change_set is not None
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
                    CandidateComponentDraft,
                    CandidateRejection,
                ),
            )
            else None
        )
        semantic = rfc8785.dumps(cast(Any, _item_semantic(draft)))
        await connection.execute(
            """
            INSERT INTO armi.cognitive_candidate_validation_items (
                candidate_validation_id, proposal_ref, atomic_group_ref,
                owner_kind, fact_class, validation_status, reason_code,
                semantic_digest, ordinal, schema_version
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, 1)
            """,
            (
                result.validation_id.value,
                draft.proposal_ref,
                draft.atomic_group_ref,
                owner.value,
                (fact_class or _implicit_fact_class(draft)).value,
                "accepted" if accepted else "rejected",
                None if accepted else draft.code,
                Digest.from_bytes(semantic).value,
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
    | CandidateComponentDraft
    | CapabilityRequestDraft
    | CreatorReplyDraft
    | FormalNoActionDraft
    | WebResearchRequestDraft
    | CodexDelegationDraft
    | CandidateActivityDraft
    | CandidateActivityDecisionDraft
    | CandidateSleepDecisionDraft
    | CandidateRejection,
    ...,
]:
    return (
        *change_set.experiences,
        *change_set.memories,
        *change_set.components,
        *change_set.capability_requests,
        *change_set.action_choices,
        *change_set.web_research_requests,
        *change_set.codex_delegations,
        *change_set.activities,
        *change_set.activity_decisions,
        *change_set.sleep_decisions,
        *change_set.rejections,
    )


def _item_semantic(
    value: CandidateExperienceDraft
    | CandidateMemoryDraft
    | CandidateComponentDraft
    | CapabilityRequestDraft
    | CreatorReplyDraft
    | FormalNoActionDraft
    | WebResearchRequestDraft
    | CodexDelegationDraft
    | CandidateActivityDraft
    | CandidateActivityDecisionDraft
    | CandidateSleepDecisionDraft
    | CandidateRejection,
) -> dict[str, object]:
    result: dict[str, object] = {
        "proposal_ref": value.proposal_ref,
        "atomic_group_ref": value.atomic_group_ref,
        "basis_ordinals": list(value.basis_ordinals),
        "fact_class": _implicit_fact_class(value).value,
    }
    if isinstance(value, CandidateSleepDecisionDraft):
        result.update(
            {
                "owner": "sleep",
                "decision_kind": value.decision_kind.value,
                "cycle_anchor_ref": str(value.cycle_anchor_ref),
                "source_digest": value.source_digest.value,
            }
        )
    elif isinstance(value, CandidateActivityDecisionDraft):
        result.update(
            {
                "owner": "activity",
                "activity_id": str(value.activity_id),
                "current_revision_id": str(value.current_revision_id),
                "expected_head_version": value.expected_head_version,
                "resource_snapshot_digest": value.resource_snapshot_digest.value,
                "decision_kind": value.decision_kind.value,
            }
        )
    elif isinstance(value, CandidateActivityDraft):
        result.update(
            {
                "owner": "activity",
                "activity_id": str(value.activity_id),
                "activity_kind": value.activity_kind,
                "goal": value.goal,
                "next_safe_step": value.next_safe_step,
                "status": value.status.value,
                "privacy_scope": value.privacy_scope,
            }
        )
    elif isinstance(value, CandidateExperienceDraft):
        result.update(
            {
                "owner": "experience",
                "first_person_gist": value.first_person_gist,
                "uncertainty": value.uncertainty,
                "privacy_scope": value.privacy_scope,
            }
        )
    elif isinstance(value, CandidateMemoryDraft):
        result.update(
            {
                "owner": "memory",
                "source_experience_ref": value.source_experience_ref,
                "source_kind": value.source_kind.value,
                "summary": value.summary,
                "mechanism_identity": value.mechanism_identity,
                "privacy_scope": value.privacy_scope,
            }
        )
    elif isinstance(value, CandidateComponentDraft):
        result.update(
            {
                "owner": value.owner.value,
                "expected_version": value.expected_version,
                "next_state": json.loads(value.canonical_next_state),
            }
        )
    elif isinstance(value, CandidateRejection):
        result.update({"owner": value.owner.value, "reason_code": value.code})
    elif isinstance(value, WebResearchRequestDraft):
        result.update(
            {
                "owner": "web_research",
                "purpose": value.purpose,
                "operation_class": value.operation_class,
                "query_digest": value.query_digest.value,
            }
        )
    elif isinstance(value, CodexDelegationDraft):
        result.update(
            {
                "owner": "codex_delegation",
                "task_source_id": str(value.task_source_id.value),
                "task_manifest_digest": value.task_manifest_digest.value,
                "validator_id": value.validator_id,
            }
        )
    else:
        result.update({"owner": _owner(value).value})
    return result


def _owner(
    value: CandidateExperienceDraft
    | CandidateMemoryDraft
    | CandidateComponentDraft
    | CapabilityRequestDraft
    | CreatorReplyDraft
    | FormalNoActionDraft
    | WebResearchRequestDraft
    | CodexDelegationDraft
    | CandidateActivityDraft
    | CandidateActivityDecisionDraft
    | CandidateSleepDecisionDraft
    | CandidateRejection,
) -> CandidateOwner:
    if isinstance(value, CandidateSleepDecisionDraft):
        return CandidateOwner.SLEEP
    if isinstance(value, (CandidateActivityDraft, CandidateActivityDecisionDraft)):
        return CandidateOwner.ACTIVITY
    if isinstance(value, CandidateExperienceDraft):
        return CandidateOwner.EXPERIENCE
    if isinstance(value, CandidateMemoryDraft):
        return CandidateOwner.MEMORY
    if isinstance(value, CapabilityRequestDraft):
        return CandidateOwner.CAPABILITY
    if isinstance(value, (CreatorReplyDraft, FormalNoActionDraft)):
        return CandidateOwner.ACTION
    if isinstance(value, WebResearchRequestDraft):
        return CandidateOwner.WEB_RESEARCH
    if isinstance(value, CodexDelegationDraft):
        return CandidateOwner.CODEX_DELEGATION
    return value.owner


def _implicit_fact_class(
    value: CandidateExperienceDraft
    | CandidateMemoryDraft
    | CandidateComponentDraft
    | CapabilityRequestDraft
    | CreatorReplyDraft
    | FormalNoActionDraft
    | WebResearchRequestDraft
    | CodexDelegationDraft
    | CandidateActivityDraft
    | CandidateActivityDecisionDraft
    | CandidateSleepDecisionDraft
    | CandidateRejection,
) -> CandidateFactClass:
    if isinstance(
        value,
        (
            CandidateExperienceDraft,
            CandidateMemoryDraft,
            CandidateComponentDraft,
            CandidateActivityDraft,
            CandidateRejection,
        ),
    ):
        return value.fact_class
    if isinstance(value, CandidateActivityDecisionDraft):
        return CandidateFactClass.INFERENCE
    if isinstance(value, CandidateSleepDecisionDraft):
        return CandidateFactClass.INFERENCE
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
        1,
    )


__all__ = (
    "CandidateEpisodeSnapshot",
    "PostgreSQLCandidateValidationRepository",
)
