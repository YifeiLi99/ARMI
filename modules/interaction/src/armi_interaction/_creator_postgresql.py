"""Package-private PostgreSQL owner for Creator input acceptance."""

from __future__ import annotations

from typing import Any
from uuid import UUID, uuid7

from armi_evidence.api import (
    EvidenceDraft,
    EvidenceId,
    EvidencePrivacyScope,
    EvidenceSourceKind,
    EvidenceWritePort,
)
from armi_kernel.contracts import Digest
from armi_opportunity.api import (
    ExternalEvidenceOpportunityDraft,
    OpportunityAdmissionPort,
    OpportunityAdmissionStatus,
    OpportunityPurpose,
)
from armi_runtime_foundation import PostgreSQLRuntimeUnitOfWork

from ._creator_contract import (
    CreatorInputAcceptance,
    CreatorInputContext,
    CreatorInputViolation,
    CreatorInteractionId,
    CreatorOperation,
    CreatorOperationPhase,
    OpportunityId,
)


class CreatorInputRepository:
    """Own the fixed SQL for interaction, evidence, opportunity and timeline."""

    __slots__ = ("_evidence", "_opportunity")

    def __init__(
        self,
        evidence: EvidenceWritePort,
        opportunity: OpportunityAdmissionPort,
    ) -> None:
        self._evidence = evidence
        self._opportunity = opportunity

    async def lock_scene(
        self,
        unit_of_work: PostgreSQLRuntimeUnitOfWork,
        *,
        scene_id: UUID,
    ) -> None:
        connection = unit_of_work.transaction
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
        unit_of_work: PostgreSQLRuntimeUnitOfWork,
        *,
        scene_key: str,
        creator_party_id: UUID,
    ) -> CreatorInputContext:
        connection = unit_of_work.transaction
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
        unit_of_work: PostgreSQLRuntimeUnitOfWork,
        *,
        context: CreatorInputContext,
        idempotency_key: str,
        request_digest: Digest,
    ) -> CreatorInputAcceptance | None:
        connection = unit_of_work.transaction
        row = await (
            await connection.execute(
                """
                SELECT
                    interaction.interaction_id,
                    evidence.evidence_id,
                    interaction.request_digest,
                    COALESCE(interaction.cognition_content_digest,
                             interaction.content_digest)
                FROM armi.party_input_interactions AS interaction
                JOIN armi.external_evidence AS evidence
                  ON evidence.interaction_id
                    = interaction.interaction_id
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
        if str(row[2]) != request_digest.value:
            raise CreatorInputViolation("IDEMPOTENCY-MISMATCH")
        opportunity = await self._opportunity.find_external_evidence(
            connection,
            evidence_id=row[1],
            purpose=OpportunityPurpose.CONSIDER_CREATOR_INPUT,
        )
        if opportunity is None:
            raise CreatorInputViolation("DB-INPUT-STATE")
        return _acceptance(
            (row[0], row[1], opportunity.value, row[2], row[3]),
            newly_accepted=False,
        )

    async def create(
        self,
        unit_of_work: PostgreSQLRuntimeUnitOfWork,
        *,
        context: CreatorInputContext,
        idempotency_key: str,
        request_digest: Digest,
        content_digest: Digest,
        artifact_id: UUID,
        trace_id: str,
        external_binding_id: UUID | None = None,
        external_message_key: str | None = None,
        addressed_to_subject: bool | None = None,
    ) -> CreatorInputAcceptance:
        connection = unit_of_work.transaction
        interaction_id = uuid7()
        evidence_id = uuid7()
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
                trace_id, external_binding_id, external_message_key,
                addressed_to_subject)
            VALUES (%s, %s, %s, %s, 'creator_message', %s, %s, %s, %s,
                    %s, %s, %s)
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
                external_binding_id,
                external_message_key,
                addressed_to_subject,
            ),
        )
        await self._evidence.accept(
            unit_of_work,
            EvidenceDraft(
                evidence_id=EvidenceId(evidence_id),
                subject_id=context.subject_id,
                scene_id=context.scene_id,
                context_party_id=context.creator_party_id,
                artifact_id=artifact_id,
                source_kind=EvidenceSourceKind.CREATOR_INPUT,
                privacy_scope=EvidencePrivacyScope.CREATOR_VISIBLE,
                interaction_id=interaction_id,
            ),
        )
        admitted = await self._opportunity.admit_external_evidence(
            connection,
            ExternalEvidenceOpportunityDraft(
                evidence_id=evidence_id,
                subject_id=context.subject_id,
                scene_id=context.scene_id,
                context_party_id=context.creator_party_id,
                purpose=OpportunityPurpose.CONSIDER_CREATOR_INPUT,
            ),
        )
        if admitted.status is OpportunityAdmissionStatus.REJECTED:
            raise CreatorInputViolation("DB-INPUT-STATE")
        opportunity_id = admitted.opportunity_id
        if opportunity_id is None:
            raise CreatorInputViolation("DB-INPUT-STATE")
        await connection.execute(
            """
            INSERT INTO armi.scene_timeline_items (
                timeline_item_id,
                scene_id,
                source_kind,
                source_ref,
                source_event_no,
                result_status,
                occurred_at)
            VALUES (
                %s, %s, 'creator_input', %s, 1, 'accepted',
                statement_timestamp())
            """,
            (timeline_item_id, context.scene_id, interaction_id),
        )
        boundary = await connection.execute(
            """
            UPDATE armi.interaction_scenes
            SET recent_context_boundary = %s,
                scene_version = scene_version + 1
            WHERE scene_id = %s
              AND current_status = 'open'
              AND closed_at IS NULL
              AND recent_context_boundary IS DISTINCT FROM %s
            """,
            (timeline_item_id, context.scene_id, timeline_item_id),
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
        unit_of_work: PostgreSQLRuntimeUnitOfWork,
        *,
        opportunity_id: OpportunityId,
        creator_party_id: UUID,
    ) -> CreatorOperation:
        connection = unit_of_work.transaction
        row = await (
            await connection.execute(
                """
                SELECT
                    interaction.interaction_id,
                    evidence.evidence_id,
                    requested.opportunity_id,
                    interaction.request_digest,
                    COALESCE(interaction.cognition_content_digest,
                             interaction.content_digest),
                    opportunity.current_disposition,
                    episode.status,
                    episode.failure_code,
                    application.resolution,
                    commit.new_subject_version,
                    opportunity.reconsideration_no
                    , CASE
                        WHEN no_action.action_intent_id IS NULL
                             AND no_action.dialogue_decision_id IS NOT NULL
                          THEN 'no_action'
                        WHEN intent.action_kind = 'party_response' THEN
                          CASE
                            WHEN policy.policy_decision_id IS NULL THEN 'pending'
                            WHEN policy.decision_outcome <> 'allowed'
                              THEN 'unauthorized'
                            WHEN effect.effect_id IS NULL THEN 'accepted'
                            WHEN effect.status = 'registered'
                              THEN 'effect_registered'
                            WHEN effect.status = 'dispatching'
                              THEN 'effect_dispatching'
                            ELSE 'effect_' || effect.status
                          END
                        WHEN intent.action_kind = 'codex_delegation' THEN
                          CASE
                            WHEN policy.policy_decision_id IS NULL
                              THEN 'codex_waiting_grant'
                            WHEN policy.decision_outcome <> 'allowed'
                              THEN 'codex_failed'
                            WHEN effect.effect_id IS NULL
                              THEN 'codex_waiting_grant'
                            WHEN effect.status = 'registered'
                              THEN 'effect_registered'
                            WHEN effect.status = 'dispatching'
                              THEN 'codex_dispatching'
                            WHEN effect.status = 'completed'
                              THEN 'codex_result_pending'
                            ELSE 'codex_' || effect.status
                          END
                      END
                    , policy.reason_code
                    , no_action.decision_kind
                    , effect.effect_id
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
                JOIN armi.artifacts AS evidence_artifact
                  ON evidence_artifact.artifact_id = evidence.artifact_id
                JOIN armi.party_input_interactions AS interaction
                  ON interaction.interaction_id = evidence.interaction_id
                  OR (
                      requested.purpose = 'consider_codex_task'
                      AND evidence.source_kind = 'codex_task_source'
                      AND interaction.subject_id = requested.subject_id
                      AND interaction.scene_id = requested.scene_id
                      AND interaction.source_party_id
                        = requested.context_party_id
                      AND interaction.purpose = 'codex_task_request'
                      AND interaction.content_digest
                        = evidence_artifact.content_digest
                  )
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
                LEFT JOIN armi.action_intents AS intent
                  ON intent.root_opportunity_id = requested.opportunity_id
                LEFT JOIN armi.action_intent_revisions AS revision
                  ON revision.action_intent_revision_id = intent.current_revision_id
                LEFT JOIN armi.policy_decisions AS policy
                  ON policy.action_intent_revision_id =
                     revision.action_intent_revision_id
                 AND policy.is_current
                LEFT JOIN armi.effects AS effect
                  ON effect.action_intent_id = intent.action_intent_id
                LEFT JOIN armi.dialogue_decisions AS no_action
                  ON no_action.opportunity_id = requested.opportunity_id
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
        response_status = None if row[11] is None else str(row[11])
        no_action_kind = None if row[13] is None else str(row[13])
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
        elif response_status == "no_action" and no_action_kind == "silence":
            phase = CreatorOperationPhase.FORMAL_NO_ACTION
        elif response_status == "no_action" and no_action_kind == "defer":
            phase = CreatorOperationPhase.DEFERRED
        elif response_status == "no_action" and no_action_kind == "end_conversation":
            phase = CreatorOperationPhase.COMPLETED
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
            and int(row[10]) == 1
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
                str(row[12])
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
            acceptance=acceptance,
            phase=phase,
            failure_code=failure_code,
            subject_version=int(row[9])
            if phase is CreatorOperationPhase.APPLIED
            else None,
            effect_ref=row[14]
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
