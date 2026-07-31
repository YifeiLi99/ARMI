"""PostgreSQL owner for the T-03 subject commit transaction."""

from __future__ import annotations

import json
from dataclasses import dataclass
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
    CandidateApplicationId,
    CandidateApplicationStatus,
    CandidateDisposition,
    CandidateOwner,
    CapabilityRequestDraft,
    CodexDelegatedWorkScope,
    CreatorSceneReplyScope,
    ExperienceId,
    SubjectChangeSet,
    SubjectCommitId,
    SubjectCommitResult,
    SubjectCommitViolation,
    WorkLease,
    WorkResultRef,
)
from armi_kernel.contracts import Digest, Purpose, SubjectId, TraceId

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
    evidence_id: UUID
    scene_id: UUID
    scene_key: str
    creator_party_id: UUID
    change_set_artifact: ArtifactRef
    change_set_digest: Digest
    base_subject_version: int
    base_state_epoch: int
    context_digest: Digest
    trace_id: TraceId


class PostgreSQLSubjectCommitRepository:
    """Read one validated ChangeSet and atomically apply or settle it."""

    __slots__ = ()

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
                    opportunity.creator_party_id,
                    validation.change_set_artifact_id,
                    validation.change_set_digest,
                    validation.base_subject_version,
                    validation.base_state_epoch,
                    validation.context_digest,
                    episode.trace_id
                FROM armi.durable_work AS work
                JOIN armi.cognitive_episodes AS episode
                  ON episode.cognitive_episode_id = work.owner_ref
                JOIN armi.cognitive_candidate_validations AS validation
                  ON validation.cognitive_episode_id = episode.cognitive_episode_id
                JOIN armi.opportunities AS opportunity
                  ON opportunity.opportunity_id = episode.opportunity_id
                JOIN armi.interaction_scenes AS scene
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
                  AND validation.change_set_digest IS NOT NULL
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
            str(row[10]),
            row[11],
            await _artifact_ref(connection, row[12]),
            Digest(str(row[13])),
            int(row[14]),
            int(row[15]),
            Digest(str(row[16])),
            TraceId(str(row[17])),
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
                       completion_digest, subject_commit_id,
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
        commit_id = SubjectCommitId(row[3]) if row[3] is not None else None
        return SubjectCommitResult(
            CandidateApplicationId(row[0]),
            status,
            Digest(str(row[2])),
            commit_id,
            int(row[4]) if commit_id is not None else None,
            row[5],
        )

    async def settle(
        self,
        unit_of_work: PostgreSQLUnitOfWork,
        *,
        lease: WorkLease,
        snapshot: SubjectCommitSnapshot,
        change_set: SubjectChangeSet,
    ) -> SubjectCommitResult:
        connection = unit_of_work._connection_for_repository()  # pyright: ignore[reportPrivateUsage]
        await _assert_lease(connection, lease, snapshot.episode_id)
        fence = unit_of_work.runtime_fence
        if fence is None:
            raise SubjectCommitViolation("SUBJECT-FENCE")
        if (
            change_set.digest != snapshot.change_set_digest
            or change_set.subject_id != snapshot.subject_id
            or change_set.generation_id != snapshot.generation_id
            or change_set.episode_id != snapshot.episode_id
            or change_set.bundle_activation_id != snapshot.activation_id
            or change_set.base_subject_version != snapshot.base_subject_version
            or change_set.base_state_epoch != snapshot.base_state_epoch
            or change_set.context_digest != snapshot.context_digest
        ):
            raise SubjectCommitViolation("SUBJECT-CHANGE-SET-IDENTITY")

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
        stale = (
            int(subject[0]) != change_set.base_subject_version
            or int(subject[1]) != change_set.base_state_epoch
            or subject[2] != change_set.generation_id
            or subject[3] != change_set.bundle_activation_id
            or any(
                heads.get(component.owner) != component.expected_version
                for component in change_set.components
            )
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
        )

    async def _settle_current(
        self,
        unit_of_work: PostgreSQLUnitOfWork,
        *,
        lease: WorkLease,
        snapshot: SubjectCommitSnapshot,
        change_set: SubjectChangeSet,
    ) -> SubjectCommitResult:
        connection = unit_of_work._connection_for_repository()  # pyright: ignore[reportPrivateUsage]
        disposition_map = {
            CandidateDisposition.NO_CHANGE: CandidateApplicationStatus.NO_CHANGE,
            CandidateDisposition.DEFER: CandidateApplicationStatus.DEFERRED,
            CandidateDisposition.DECLINE: CandidateApplicationStatus.DECLINED,
            CandidateDisposition.NEED_INFORMATION: CandidateApplicationStatus.NEED_INFORMATION,
        }
        if change_set.disposition is not CandidateDisposition.CHANGE:
            status = disposition_map[change_set.disposition]
            return await _settle_without_commit(
                unit_of_work,
                lease=lease,
                snapshot=snapshot,
                status=status,
                observed_version=change_set.base_subject_version,
            )
        if (
            not change_set.experiences
            and not change_set.components
            and not change_set.capability_requests
        ):
            raise SubjectCommitViolation("SUBJECT-EMPTY-COMMIT")

        commit_id = SubjectCommitId(uuid7())
        new_version = change_set.base_subject_version + 1
        commit_digest = _completion_digest(
            "applied", snapshot.validation_id, change_set.digest, new_version
        )
        fence = unit_of_work.runtime_fence
        assert fence is not None
        await connection.execute(
            """
            INSERT INTO armi.subject_commits (
                subject_commit_id, candidate_validation_id,
                cognitive_episode_id, subject_id, life_generation_id,
                bundle_activation_id, base_subject_version,
                new_subject_version, base_state_epoch, change_set_digest,
                commit_digest, runtime_instance_id, fence_token, trace_id,
                schema_version
            ) VALUES (
                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                %s, %s, %s, %s, 1
            )
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
                change_set.digest.value,
                commit_digest.value,
                fence.runtime_instance_id.value,
                fence.fence_token,
                snapshot.trace_id.value,
            ),
        )
        for experience in change_set.experiences:
            experience_id = ExperienceId(uuid7())
            evidence_links = await _evidence_links(
                connection,
                snapshot=snapshot,
                proposal_ref=experience.proposal_ref,
            )
            if not evidence_links:
                raise SubjectCommitViolation("SUBJECT-EXPERIENCE-BASIS")
            received_at = evidence_links[0][2]
            await connection.execute(
                """
                INSERT INTO armi.accepted_experiences (
                    experience_id, subject_commit_id, cognitive_episode_id,
                    proposal_ref, experience_kind, fact_class,
                    first_person_gist, scene_id, occurred_at, learned_at,
                    source_perspective, uncertainty, privacy_scope,
                    schema_version
                ) VALUES (
                    %s, %s, %s, %s, 'creator_input', 'external_claim',
                    %s, %s, %s, %s, 'creator_claim', %s, 'private', 1
                )
                """,
                (
                    experience_id.value,
                    commit_id.value,
                    snapshot.episode_id,
                    experience.proposal_ref,
                    experience.first_person_gist,
                    snapshot.scene_id,
                    received_at,
                    received_at,
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
                    semantic_digest, semantic_payload, privacy_scope
                ) VALUES (
                    %s, %s, %s, %s, %s, 'subject_commit', %s,
                    %s, %s, %s, %s, 'private'
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
                    component.next_state_digest.value,
                    json.loads(component.canonical_next_state),
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

        await _insert_capability_requests(
            unit_of_work,
            snapshot=snapshot,
            commit_id=commit_id,
            requests=change_set.capability_requests,
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
            completion_digest=commit_digest,
            commit_id=commit_id,
        )
        timeline_item_id = uuid7()
        await connection.execute(
            """
            INSERT INTO armi.scene_timeline_items (
                timeline_item_id, scene_id, source_kind, source_ref,
                source_event_no, result_status, occurred_at, schema_version
            ) VALUES (
                %s, %s, 'subject_commit', %s, 1, 'applied',
                statement_timestamp(), 1
            )
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
                commit_digest,
            )
        )
        return SubjectCommitResult(
            application_id,
            CandidateApplicationStatus.APPLIED,
            commit_digest,
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
                    creator_party_id, purpose, eligibility_status,
                    current_disposition, root_opportunity_id,
                    predecessor_opportunity_id, reconsideration_no,
                    schema_version
                ) VALUES (
                    %s, %s, %s, %s, %s, 'consider_creator_input',
                    'eligible', 'open', %s, %s, 1, 1
                )
                """,
                (
                    successor,
                    snapshot.evidence_id,
                    snapshot.subject_id,
                    snapshot.scene_id,
                    snapshot.creator_party_id,
                    snapshot.root_opportunity_id,
                    snapshot.opportunity_id,
                ),
            )
        completion = _completion_digest(
            "stale",
            snapshot.validation_id,
            snapshot.change_set_digest,
            observed_version,
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
            completion_digest=completion,
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
                completion,
            )
        )
        return SubjectCommitResult(
            application_id,
            CandidateApplicationStatus.STALE,
            completion,
            successor_opportunity_id=successor,
        )


async def _settle_without_commit(
    unit_of_work: PostgreSQLUnitOfWork,
    *,
    lease: WorkLease,
    snapshot: SubjectCommitSnapshot,
    status: CandidateApplicationStatus,
    observed_version: int,
) -> SubjectCommitResult:
    connection = unit_of_work._connection_for_repository()  # pyright: ignore[reportPrivateUsage]
    completion = _completion_digest(
        status.value,
        snapshot.validation_id,
        snapshot.change_set_digest,
        observed_version,
    )
    application_id = CandidateApplicationId(uuid7())
    await _insert_application(
        connection,
        unit_of_work=unit_of_work,
        application_id=application_id,
        snapshot=snapshot,
        lease=lease,
        status=status,
        observed_version=observed_version,
        completion_digest=completion,
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
        in {CandidateApplicationStatus.NO_CHANGE, CandidateApplicationStatus.DECLINED}
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
            completion,
        )
    )
    return SubjectCommitResult(application_id, status, completion)


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
    completion_digest: Digest,
    commit_id: SubjectCommitId | None = None,
    successor_id: UUID | None = None,
) -> None:
    fence = unit_of_work.runtime_fence
    assert fence is not None
    await connection.execute(
        """
        INSERT INTO armi.cognitive_candidate_applications (
            candidate_application_id, candidate_validation_id,
            cognitive_episode_id, work_id, resolution, subject_commit_id,
            successor_opportunity_id, base_subject_version,
            observed_subject_version, completion_digest,
            runtime_instance_id, fence_token, schema_version
        ) VALUES (
            %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 1
        )
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
            completion_digest.value,
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
        request_value = {
            "schema_version": "armi.capability-request.v1",
            "subject_commit_id": str(commit_id.value),
            "proposal_ref": draft.proposal_ref,
            "subject_id": str(snapshot.subject_id),
            "scene_id": str(snapshot.scene_id),
            "creator_party_id": str(snapshot.creator_party_id),
            "capability_kind": draft.capability.value,
            "operation": draft.operation.value,
            "scope": json.loads(rfc8785.dumps(cast(Any, _scope_wire(scope)))),
        }
        request_digest = Digest.from_bytes(rfc8785.dumps(cast(Any, request_value)))
        await connection.execute(
            """
            INSERT INTO armi.capability_requests (
                capability_request_id, subject_commit_id, proposal_ref,
                subject_id, interaction_scene_id, creator_party_id,
                capability_id, capability_kind, operation_class,
                audience_scope, data_scope, purpose, workspace_scope,
                artifact_scope, network_access, requested_valid_for_seconds,
                requested_max_uses, requested_max_payload_bytes,
                request_digest, schema_version
            ) VALUES (
                %s, %s, %s, %s, %s, %s, %s, %s, %s,
                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 1
            )
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
                request_digest.value,
            ),
        )
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
                request_digest,
            )
        )


def _scope_wire(
    scope: CreatorSceneReplyScope | CodexDelegatedWorkScope,
) -> dict[str, object]:
    if isinstance(scope, CreatorSceneReplyScope):
        return {
            "subject_id": str(scope.subject_id),
            "scene_id": str(scope.scene_id),
            "creator_party_id": str(scope.creator_party_id),
            "audience_scope": scope.audience_scope,
            "data_scope": scope.data_scope,
            "purpose": scope.purpose,
            "valid_for_seconds": scope.valid_for_seconds,
            "max_uses": scope.max_uses,
            "max_payload_bytes": scope.max_payload_bytes,
        }
    return {
        "workspace_scope": scope.workspace_scope,
        "artifact_scope": scope.artifact_scope,
        "network_access": scope.network_access,
        "valid_for_seconds": scope.valid_for_seconds,
        "max_uses": scope.max_uses,
    }


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
        1,
    )


def _completion_digest(
    status: str,
    validation_id: UUID,
    change_set_digest: Digest,
    observed_version: int,
) -> Digest:
    return Digest.from_bytes(
        rfc8785.dumps(
            cast(
                Any,
                {
                    "schema_version": "armi.candidate-application.v1",
                    "resolution": status,
                    "candidate_validation_id": str(validation_id),
                    "change_set_digest": change_set_digest.value,
                    "observed_subject_version": observed_version,
                },
            )
        )
    )


def _audit(
    unit_of_work: PostgreSQLUnitOfWork,
    snapshot: SubjectCommitSnapshot,
    operation: str,
    target_kind: str,
    target_ref: UUID,
    result: AuditResultStatus,
    digest: Digest,
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
        response_digest=digest,
    )


__all__ = ("PostgreSQLSubjectCommitRepository", "SubjectCommitSnapshot")
