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

    async def lock_scene(
        self,
        unit_of_work: PostgreSQLUnitOfWork,
        *,
        scene_id: UUID,
    ) -> None:
        connection = unit_of_work._connection_for_repository()  # pyright: ignore[reportPrivateUsage]
        row = await (
            await connection.execute(
                """
                SELECT scene_id
                FROM armi.interaction_scenes
                WHERE scene_id = %s
                FOR UPDATE
                """,
                (scene_id,),
            )
        ).fetchone()
        if row is None:
            raise CreatorInputViolation("SCOPE-SCENE-NOT-VISIBLE")

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
                    interaction.interaction_id,
                    evidence.evidence_id,
                    opportunity.opportunity_id,
                    interaction.request_digest,
                    interaction.content_digest
                FROM armi.party_input_interactions AS interaction
                JOIN armi.external_evidence AS evidence
                  ON evidence.interaction_id
                    = interaction.interaction_id
                JOIN armi.opportunities AS opportunity
                  ON opportunity.evidence_id = evidence.evidence_id
                WHERE interaction.source_party_id = %s
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
            INSERT INTO armi.party_input_interactions (
                interaction_id,
                subject_id,
                scene_id,
                source_party_id,
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
                interaction_id,
                subject_id,
                scene_id,
                context_party_id,
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
                context_party_id,
                purpose,
                source_kind,
                source_ref,
                source_version,
                source_digest,
                eligibility_status,
                current_disposition,
                root_opportunity_id,
                reconsideration_no,
                schema_version
            )
            VALUES (
                %s, %s, %s, %s, %s,
                'consider_creator_input', 'external_evidence', %s, 1, %s,
                'eligible', 'open', %s, 0, 1
            )
            """,
            (
                opportunity_id,
                evidence_id,
                context.subject_id,
                context.scene_id,
                context.creator_party_id,
                evidence_id,
                content_digest.value,
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
        boundary = await connection.execute(
            """
            UPDATE armi.interaction_scenes
            SET recent_context_boundary = %s
            WHERE scene_id = %s
              AND current_status = 'open'
              AND closed_at IS NULL
            """,
            (timeline_item_id, context.scene_id),
        )
        if boundary.rowcount != 1:
            raise CreatorInputViolation("SCOPE-SCENE-NOT-VISIBLE")
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
                    interaction.interaction_id,
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
                    , CASE
                        WHEN response.operation_kind = 'party_response' THEN
                            CASE response.phase
                                WHEN 'admission_pending' THEN 'pending'
                                WHEN 'admitted' THEN 'accepted'
                                WHEN 'effect_registered' THEN 'effect_registered'
                                WHEN 'dispatching' THEN 'effect_dispatching'
                                WHEN 'terminal' THEN
                                    CASE response.outcome
                                        WHEN 'completed' THEN 'effect_completed'
                                        WHEN 'failed' THEN 'effect_failed'
                                        WHEN 'unknown' THEN 'effect_unknown'
                                        WHEN 'cancelled' THEN 'effect_cancelled'
                                        WHEN 'denied' THEN 'unauthorized'
                                        WHEN 'no_action' THEN 'no_action'
                                        ELSE response.outcome
                                    END
                                ELSE response.phase
                            END
                        WHEN response.operation_kind = 'codex_delegation' THEN
                            CASE response.phase
                                WHEN 'admission_pending' THEN 'codex_waiting_grant'
                                WHEN 'dispatching' THEN 'codex_dispatching'
                                WHEN 'result_pending' THEN 'codex_result_pending'
                                WHEN 'terminal' THEN
                                    CASE response.outcome
                                        WHEN 'completed' THEN 'codex_result_accepted'
                                        WHEN 'rejected' THEN 'codex_result_rejected'
                                        WHEN 'failed' THEN 'codex_failed'
                                        WHEN 'unknown' THEN 'codex_unknown'
                                        WHEN 'cancelled' THEN 'codex_cancelled'
                                        ELSE response.outcome
                                    END
                                ELSE response.phase
                            END
                      END
                    , response.completion_digest
                    , response.reason_code
                    , no_action.decision_kind
                    , response.effect_id
                    , effect.settlement_digest
                FROM armi.opportunities AS requested
                JOIN LATERAL (
                    SELECT current.*
                    FROM armi.opportunities AS current
                    WHERE current.root_opportunity_id = requested.opportunity_id
                    ORDER BY current.reconsideration_no DESC
                    LIMIT 1
                ) AS opportunity ON true
                JOIN armi.external_evidence AS evidence
                  ON evidence.evidence_id = requested.evidence_id
                JOIN armi.party_input_interactions AS interaction
                  ON interaction.interaction_id
                    = evidence.interaction_id
                JOIN armi.interaction_scenes AS scene
                  ON scene.scene_id = opportunity.scene_id
                 AND scene.primary_party_id = opportunity.context_party_id
                 AND scene.audience_scope = 'creator'
                LEFT JOIN armi.cognitive_episodes AS episode
                  ON episode.opportunity_id = opportunity.opportunity_id
                LEFT JOIN armi.cognitive_candidate_applications AS application
                  ON application.cognitive_episode_id = episode.cognitive_episode_id
                LEFT JOIN armi.subject_commits AS commit
                  ON commit.subject_commit_id = application.subject_commit_id
                LEFT JOIN armi.action_operations AS response
                  ON response.root_opportunity_id = requested.opportunity_id
                LEFT JOIN armi.dialogue_decisions AS no_action
                  ON no_action.dialogue_decision_id = response.dialogue_decision_id
                LEFT JOIN armi.effects AS effect ON effect.effect_id = response.effect_id
                WHERE requested.opportunity_id = %s
                  AND requested.root_opportunity_id = requested.opportunity_id
                  AND opportunity.context_party_id = %s
                  AND requested.purpose IN (
                      'consider_creator_input', 'consider_codex_task'
                  )
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
        response_status = None if row[12] is None else str(row[12])
        no_action_kind = None if row[15] is None else str(row[15])
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
        elif (
            disposition in {"selected", "resolved"}
            and episode_status == "candidate_rejected"
        ):
            phase = CreatorOperationPhase.CANDIDATE_REJECTED
        elif response_status == "pending":
            phase = CreatorOperationPhase.RESPONSE_ADMISSION
        elif response_status == "accepted":
            phase = CreatorOperationPhase.EFFECT_REGISTRATION
        elif response_status == "effect_registered":
            phase = CreatorOperationPhase.EFFECT_REGISTERED
        elif response_status == "effect_dispatching":
            phase = CreatorOperationPhase.EFFECT_DISPATCHING
        elif response_status == "effect_completed":
            phase = CreatorOperationPhase.EFFECT_COMPLETED
        elif response_status == "effect_failed":
            phase = CreatorOperationPhase.EFFECT_FAILED
        elif response_status == "effect_unknown":
            phase = CreatorOperationPhase.EFFECT_UNKNOWN
        elif response_status == "effect_cancelled":
            phase = CreatorOperationPhase.EFFECT_CANCELLED
        elif response_status == "codex_waiting_grant":
            phase = CreatorOperationPhase.CODEX_CAPABILITY_DECISION
        elif response_status == "codex_dispatching":
            phase = CreatorOperationPhase.CODEX_DISPATCHING
        elif response_status == "codex_verifying":
            phase = CreatorOperationPhase.CODEX_VERIFYING
        elif response_status == "codex_result_pending":
            phase = CreatorOperationPhase.CODEX_RESULT_ACCEPTANCE
        elif response_status == "codex_result_rejected":
            phase = CreatorOperationPhase.CODEX_RESULT_REJECTED
        elif response_status in {"codex_completed", "codex_result_accepted"}:
            phase = CreatorOperationPhase.CODEX_COMPLETED
        elif response_status == "codex_failed":
            phase = CreatorOperationPhase.CODEX_FAILED
        elif response_status == "codex_unknown":
            phase = CreatorOperationPhase.CODEX_UNKNOWN
        elif response_status == "codex_cancelled":
            phase = CreatorOperationPhase.CODEX_CANCELLED
        elif response_status == "no_action" and no_action_kind == "decline":
            phase = CreatorOperationPhase.FORMAL_DECLINED
        elif response_status == "no_action" and no_action_kind == "no_action":
            phase = CreatorOperationPhase.FORMAL_NO_ACTION
        elif response_status == "unauthorized":
            phase = CreatorOperationPhase.RESPONSE_UNAUTHORIZED
        elif response_status == "unavailable":
            phase = CreatorOperationPhase.RESPONSE_UNAVAILABLE
        elif response_status == "failed":
            phase = CreatorOperationPhase.RESPONSE_FAILED
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
        elif disposition in {
            "selected",
            "resolved",
            "cancelled",
        } and episode_status in {"failed", "cancelled"}:
            phase = CreatorOperationPhase.FAILED
        else:
            raise CreatorInputViolation("DB-INPUT-STATE")
        failure_code = (
            "CONFLICT_SUBJECT_STATE_STALE"
            if phase is CreatorOperationPhase.STALE_CONFLICT
            else (
                str(row[14])
                if phase
                in {
                    CreatorOperationPhase.RESPONSE_UNAUTHORIZED,
                    CreatorOperationPhase.RESPONSE_UNAVAILABLE,
                    CreatorOperationPhase.RESPONSE_FAILED,
                    CreatorOperationPhase.EFFECT_FAILED,
                    CreatorOperationPhase.EFFECT_UNKNOWN,
                    CreatorOperationPhase.CODEX_FAILED,
                    CreatorOperationPhase.CODEX_UNKNOWN,
                }
                else str(row[7])
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
            Digest(
                str(row[17])
                if phase
                in {
                    CreatorOperationPhase.EFFECT_COMPLETED,
                    CreatorOperationPhase.EFFECT_FAILED,
                    CreatorOperationPhase.EFFECT_UNKNOWN,
                    CreatorOperationPhase.CODEX_COMPLETED,
                    CreatorOperationPhase.CODEX_FAILED,
                    CreatorOperationPhase.CODEX_UNKNOWN,
                    CreatorOperationPhase.CODEX_CANCELLED,
                }
                else str(row[13])
                if phase
                in {
                    CreatorOperationPhase.RESPONSE_ACCEPTED,
                    CreatorOperationPhase.EFFECT_REGISTERED,
                    CreatorOperationPhase.EFFECT_CANCELLED,
                    CreatorOperationPhase.FORMAL_DECLINED,
                    CreatorOperationPhase.FORMAL_NO_ACTION,
                    CreatorOperationPhase.RESPONSE_UNAUTHORIZED,
                    CreatorOperationPhase.RESPONSE_UNAVAILABLE,
                    CreatorOperationPhase.RESPONSE_FAILED,
                }
                else str(row[9])
            )
            if phase
            in {
                CreatorOperationPhase.APPLIED,
                CreatorOperationPhase.COMPLETED,
                CreatorOperationPhase.DEFERRED,
                CreatorOperationPhase.NEED_INFORMATION,
                CreatorOperationPhase.STALE_CONFLICT,
                CreatorOperationPhase.RESPONSE_ACCEPTED,
                CreatorOperationPhase.EFFECT_REGISTERED,
                CreatorOperationPhase.EFFECT_COMPLETED,
                CreatorOperationPhase.EFFECT_FAILED,
                CreatorOperationPhase.EFFECT_UNKNOWN,
                CreatorOperationPhase.EFFECT_CANCELLED,
                CreatorOperationPhase.CODEX_COMPLETED,
                CreatorOperationPhase.CODEX_FAILED,
                CreatorOperationPhase.CODEX_UNKNOWN,
                CreatorOperationPhase.CODEX_CANCELLED,
                CreatorOperationPhase.FORMAL_DECLINED,
                CreatorOperationPhase.FORMAL_NO_ACTION,
                CreatorOperationPhase.RESPONSE_UNAUTHORIZED,
                CreatorOperationPhase.RESPONSE_UNAVAILABLE,
                CreatorOperationPhase.RESPONSE_FAILED,
            }
            else None,
            row[16]
            if phase
            in {
                CreatorOperationPhase.EFFECT_REGISTERED,
                CreatorOperationPhase.EFFECT_DISPATCHING,
                CreatorOperationPhase.EFFECT_COMPLETED,
                CreatorOperationPhase.EFFECT_FAILED,
                CreatorOperationPhase.EFFECT_UNKNOWN,
                CreatorOperationPhase.EFFECT_CANCELLED,
                CreatorOperationPhase.CODEX_DISPATCHING,
                CreatorOperationPhase.CODEX_VERIFYING,
                CreatorOperationPhase.CODEX_RESULT_ACCEPTANCE,
                CreatorOperationPhase.CODEX_COMPLETED,
                CreatorOperationPhase.CODEX_FAILED,
                CreatorOperationPhase.CODEX_UNKNOWN,
                CreatorOperationPhase.CODEX_CANCELLED,
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
