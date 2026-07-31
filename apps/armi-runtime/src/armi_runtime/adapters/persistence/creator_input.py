"""Package-private PostgreSQL owner for Creator input acceptance."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID, uuid7

from armi_kernel.application import (
    CreatorInputAcceptance,
    CreatorInputViolation,
    CreatorInteractionId,
    CreatorOperation,
    CreatorOperationPhase,
    EvidenceId,
    OpportunityId,
    SubjectCommitId,
    SubjectComponentKind,
    SubjectComponentSummary,
    SubjectSummary,
)
from armi_kernel.contracts import Digest

from .unit_of_work import PostgreSQLUnitOfWork


@dataclass(frozen=True, slots=True)
class CreatorInputContext:
    subject_id: UUID
    scene_id: UUID
    creator_party_id: UUID


class CreatorInputRepository:
    """Own the fixed SQL for interaction, evidence, opportunity and timeline."""

    __slots__ = ()

    async def context(
        self,
        unit_of_work: PostgreSQLUnitOfWork,
        *,
        scene_key: str,
        creator_party_id: UUID,
    ) -> CreatorInputContext:
        connection = unit_of_work._connection_for_repository()  # pyright: ignore[reportPrivateUsage]
        row = await (
            await connection.execute(
                """
                SELECT subject.subject_id, scene.scene_id, scene.primary_party_id
                FROM armi.subjects AS subject
                JOIN armi.interaction_scenes AS scene
                  ON scene.subject_id = subject.subject_id
                 AND scene.scene_key = %s
                 AND scene.scene_kind = 'creator_dialogue'
                 AND scene.audience_scope = 'creator'
                 AND scene.current_status = 'open'
                 AND scene.closed_at IS NULL
                JOIN armi.parties AS creator
                  ON creator.party_id = scene.primary_party_id
                 AND creator.party_kind = 'creator'
                 AND creator.creator_role = 'unique_primary_creator'
                 AND creator.status = 'active'
                WHERE subject.singleton_key = 1
                  AND subject.status = 'active'
                  AND creator.party_id = %s
                """,
                (scene_key, creator_party_id),
            )
        ).fetchone()
        if row is None:
            raise CreatorInputViolation("SCOPE-SCENE-NOT-VISIBLE")
        return CreatorInputContext(row[0], row[1], row[2])

    async def existing(
        self,
        unit_of_work: PostgreSQLUnitOfWork,
        *,
        context: CreatorInputContext,
        idempotency_key: str,
        request_digest: Digest,
    ) -> CreatorInputAcceptance | None:
        connection = unit_of_work._connection_for_repository()  # pyright: ignore[reportPrivateUsage]
        row = await (
            await connection.execute(
                """
                SELECT
                    interaction.creator_interaction_id,
                    evidence.evidence_id,
                    opportunity.opportunity_id,
                    interaction.request_digest,
                    interaction.content_digest
                FROM armi.creator_input_interactions AS interaction
                JOIN armi.external_evidence AS evidence
                  ON evidence.creator_interaction_id
                    = interaction.creator_interaction_id
                JOIN armi.opportunities AS opportunity
                  ON opportunity.evidence_id = evidence.evidence_id
                WHERE interaction.creator_party_id = %s
                  AND interaction.scene_id = %s
                  AND interaction.purpose = 'creator_message'
                  AND interaction.idempotency_key = %s
                """,
                (
                    context.creator_party_id,
                    context.scene_id,
                    idempotency_key,
                ),
            )
        ).fetchone()
        if row is None:
            return None
        if str(row[3]) != request_digest.value:
            raise CreatorInputViolation("IDEMPOTENCY-MISMATCH")
        return _acceptance(row, newly_accepted=False)

    async def create(
        self,
        unit_of_work: PostgreSQLUnitOfWork,
        *,
        context: CreatorInputContext,
        idempotency_key: str,
        request_digest: Digest,
        content_digest: Digest,
        artifact_id: UUID,
        trace_id: str,
    ) -> CreatorInputAcceptance:
        connection = unit_of_work._connection_for_repository()  # pyright: ignore[reportPrivateUsage]
        interaction_id = uuid7()
        evidence_id = uuid7()
        opportunity_id = uuid7()
        timeline_item_id = uuid7()
        await connection.execute(
            """
            INSERT INTO armi.creator_input_interactions (
                creator_interaction_id,
                subject_id,
                scene_id,
                creator_party_id,
                purpose,
                idempotency_key,
                request_digest,
                content_digest,
                trace_id,
                schema_version
            )
            VALUES (%s, %s, %s, %s, 'creator_message', %s, %s, %s, %s, 1)
            """,
            (
                interaction_id,
                context.subject_id,
                context.scene_id,
                context.creator_party_id,
                idempotency_key,
                request_digest.value,
                content_digest.value,
                trace_id,
            ),
        )
        await connection.execute(
            """
            INSERT INTO armi.external_evidence (
                evidence_id,
                creator_interaction_id,
                subject_id,
                scene_id,
                creator_party_id,
                artifact_id,
                source_kind,
                trust_status,
                privacy_scope,
                acceptance_status,
                schema_version
            )
            VALUES (
                %s, %s, %s, %s, %s, %s,
                'creator_input', 'external_claim', 'creator_visible', 'accepted', 1
            )
            """,
            (
                evidence_id,
                interaction_id,
                context.subject_id,
                context.scene_id,
                context.creator_party_id,
                artifact_id,
            ),
        )
        await connection.execute(
            """
            INSERT INTO armi.opportunities (
                opportunity_id,
                evidence_id,
                subject_id,
                scene_id,
                creator_party_id,
                purpose,
                eligibility_status,
                current_disposition,
                root_opportunity_id,
                reconsideration_no,
                schema_version
            )
            VALUES (
                %s, %s, %s, %s, %s,
                'consider_creator_input', 'eligible', 'open', %s, 0, 1
            )
            """,
            (
                opportunity_id,
                evidence_id,
                context.subject_id,
                context.scene_id,
                context.creator_party_id,
                opportunity_id,
            ),
        )
        await connection.execute(
            """
            INSERT INTO armi.scene_timeline_items (
                timeline_item_id,
                scene_id,
                source_kind,
                source_ref,
                source_event_no,
                result_status,
                occurred_at,
                schema_version
            )
            VALUES (
                %s, %s, 'creator_input', %s, 1, 'accepted',
                statement_timestamp(), 1
            )
            """,
            (timeline_item_id, context.scene_id, interaction_id),
        )
        return CreatorInputAcceptance(
            CreatorInteractionId(interaction_id),
            EvidenceId(evidence_id),
            OpportunityId(opportunity_id),
            request_digest,
            content_digest,
            True,
        )

    async def operation(
        self,
        unit_of_work: PostgreSQLUnitOfWork,
        *,
        opportunity_id: OpportunityId,
        creator_party_id: UUID,
    ) -> CreatorOperation:
        connection = unit_of_work._connection_for_repository()  # pyright: ignore[reportPrivateUsage]
        row = await (
            await connection.execute(
                """
                SELECT
                    interaction.creator_interaction_id,
                    evidence.evidence_id,
                    requested.opportunity_id,
                    interaction.request_digest,
                    interaction.content_digest,
                    opportunity.current_disposition,
                    episode.status,
                    episode.failure_code,
                    application.resolution,
                    application.completion_digest,
                    commit.new_subject_version,
                    opportunity.reconsideration_no
                FROM armi.opportunities AS requested
                JOIN LATERAL (
                    SELECT current.*
                    FROM armi.opportunities AS current
                    WHERE current.root_opportunity_id = requested.opportunity_id
                    ORDER BY current.reconsideration_no DESC
                    LIMIT 1
                ) AS opportunity ON true
                JOIN armi.external_evidence AS evidence
                  ON evidence.evidence_id = opportunity.evidence_id
                JOIN armi.creator_input_interactions AS interaction
                  ON interaction.creator_interaction_id
                    = evidence.creator_interaction_id
                JOIN armi.interaction_scenes AS scene
                  ON scene.scene_id = opportunity.scene_id
                 AND scene.primary_party_id = opportunity.creator_party_id
                 AND scene.audience_scope = 'creator'
                LEFT JOIN armi.cognitive_episodes AS episode
                  ON episode.opportunity_id = opportunity.opportunity_id
                LEFT JOIN armi.cognitive_candidate_applications AS application
                  ON application.cognitive_episode_id = episode.cognitive_episode_id
                LEFT JOIN armi.subject_commits AS commit
                  ON commit.subject_commit_id = application.subject_commit_id
                WHERE requested.opportunity_id = %s
                  AND requested.root_opportunity_id = requested.opportunity_id
                  AND opportunity.creator_party_id = %s
                  AND opportunity.purpose = 'consider_creator_input'
                  AND opportunity.eligibility_status = 'eligible'
                  AND opportunity.expires_at IS NULL
                """,
                (opportunity_id.value, creator_party_id),
            )
        ).fetchone()
        if row is None:
            raise CreatorInputViolation("SCOPE-OPERATION-NOT-VISIBLE")
        acceptance = _acceptance(row, newly_accepted=False)
        disposition = str(row[5])
        episode_status = None if row[6] is None else str(row[6])
        application_resolution = None if row[8] is None else str(row[8])
        if disposition == "open" and episode_status is None:
            phase = CreatorOperationPhase.ACCEPTED
        elif disposition == "selected" and episode_status == "preparing":
            phase = CreatorOperationPhase.CONTEXT_PREPARING
        elif disposition == "selected" and episode_status == "prepared":
            phase = CreatorOperationPhase.CONTEXT_PREPARED
        elif disposition == "selected" and episode_status == "calling_model":
            phase = CreatorOperationPhase.MODEL_CALLING
        elif disposition == "selected" and episode_status == "model_returned":
            phase = CreatorOperationPhase.MODEL_RETURNED
        elif disposition == "selected" and episode_status == "validating":
            phase = CreatorOperationPhase.CANDIDATE_VALIDATING
        elif disposition == "selected" and episode_status == "candidate_validated":
            phase = CreatorOperationPhase.CANDIDATE_VALIDATED
        elif disposition == "selected" and episode_status == "committing":
            phase = CreatorOperationPhase.SUBJECT_COMMITTING
        elif disposition == "selected" and episode_status == "candidate_rejected":
            phase = CreatorOperationPhase.CANDIDATE_REJECTED
        elif disposition == "resolved" and application_resolution == "applied":
            phase = CreatorOperationPhase.APPLIED
        elif disposition == "resolved" and application_resolution in {
            "no_change",
            "declined",
        }:
            phase = CreatorOperationPhase.COMPLETED
        elif disposition == "resolved" and application_resolution == "deferred":
            phase = CreatorOperationPhase.DEFERRED
        elif disposition == "resolved" and application_resolution == "need_information":
            phase = CreatorOperationPhase.NEED_INFORMATION
        elif (
            disposition == "resolved"
            and application_resolution == "stale"
            and int(row[11]) == 1
        ):
            phase = CreatorOperationPhase.STALE_CONFLICT
        elif disposition == "selected" and episode_status in {"failed", "cancelled"}:
            phase = CreatorOperationPhase.FAILED
        else:
            raise CreatorInputViolation("DB-INPUT-STATE")
        failure_code = (
            "CONFLICT_SUBJECT_STATE_STALE"
            if phase is CreatorOperationPhase.STALE_CONFLICT
            else (
                str(row[7])
                if phase
                in {
                    CreatorOperationPhase.FAILED,
                    CreatorOperationPhase.CANDIDATE_REJECTED,
                }
                else None
            )
        )
        return CreatorOperation(
            acceptance,
            phase,
            failure_code,
            int(row[10]) if phase is CreatorOperationPhase.APPLIED else None,
            Digest(str(row[9]))
            if phase
            in {
                CreatorOperationPhase.APPLIED,
                CreatorOperationPhase.COMPLETED,
                CreatorOperationPhase.DEFERRED,
                CreatorOperationPhase.NEED_INFORMATION,
                CreatorOperationPhase.STALE_CONFLICT,
            }
            else None,
        )

    async def subject_summary(
        self,
        unit_of_work: PostgreSQLUnitOfWork,
        *,
        creator_party_id: UUID,
    ) -> SubjectSummary:
        connection = unit_of_work._connection_for_repository()  # pyright: ignore[reportPrivateUsage]
        rows = await (
            await connection.execute(
                """
                SELECT subject.subject_version, head.component_kind,
                       head.component_version, commit.subject_commit_id,
                       statement_timestamp()
                FROM armi.subjects AS subject
                JOIN armi.parties AS creator
                  ON creator.party_id = %s
                 AND creator.party_kind = 'creator'
                 AND creator.creator_role = 'unique_primary_creator'
                 AND creator.status = 'active'
                JOIN armi.subject_component_heads AS head
                  ON head.subject_id = subject.subject_id
                LEFT JOIN LATERAL (
                    SELECT subject_commit_id
                    FROM armi.subject_commits
                    WHERE subject_id = subject.subject_id
                    ORDER BY new_subject_version DESC
                    LIMIT 1
                ) AS commit ON true
                WHERE subject.singleton_key = 1 AND subject.status = 'active'
                ORDER BY CASE head.component_kind
                    WHEN 'self' THEN 1 WHEN 'mind' THEN 2 ELSE 3 END
                """,
                (creator_party_id,),
            )
        ).fetchall()
        if len(rows) != 3:
            raise CreatorInputViolation("DB-SUBJECT-SUMMARY")
        schema_by_kind = {
            "self": "armi.self.v1",
            "mind": "armi.mind.v1",
            "life_mode": "armi.life-mode.v1",
        }
        try:
            return SubjectSummary(
                int(rows[0][0]),
                tuple(
                    SubjectComponentSummary(
                        SubjectComponentKind(str(row[1])),
                        int(row[2]),
                        schema_by_kind[str(row[1])],
                    )
                    for row in rows
                ),
                SubjectCommitId(rows[0][3]) if rows[0][3] is not None else None,
                rows[0][4],
            )
        except KeyError, TypeError, ValueError:
            raise CreatorInputViolation("DB-SUBJECT-SUMMARY") from None


def _acceptance(
    row: tuple[Any, ...],
    *,
    newly_accepted: bool,
) -> CreatorInputAcceptance:
    try:
        return CreatorInputAcceptance(
            CreatorInteractionId(row[0]),
            EvidenceId(row[1]),
            OpportunityId(row[2]),
            Digest(str(row[3])),
            Digest(str(row[4])),
            newly_accepted,
        )
    except CreatorInputViolation, TypeError, ValueError:
        raise CreatorInputViolation("DB-INPUT-STATE") from None


__all__ = ()
