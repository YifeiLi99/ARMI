"""Package-private PostgreSQL owner for Creator input acceptance."""

from __future__ import annotations

from typing import Any
from uuid import UUID, uuid7

from armi_attention.api import (
    ExternalEvidenceOpportunityDraft,
    OpportunityAdmissionPort,
    OpportunityAdmissionStatus,
    OpportunityPurpose,
)
from armi_evidence.api import (
    EvidenceDraft,
    EvidenceId,
    EvidencePrivacyScope,
    EvidenceReadPort,
    EvidenceSourceKind,
    EvidenceWritePort,
)
from armi_kernel.contracts import Digest, TraceId
from armi_runtime_foundation import PostgreSQLRuntimeUnitOfWork, PostgreSQLTransaction

from ._creator_contract import (
    CreatorInputAcceptance,
    CreatorInputContext,
    CreatorInputViolation,
    CreatorInteractionId,
    CreatorVoiceInputAcceptance,
    OpportunityId,
)


class CreatorInputRepository:
    """Own the fixed SQL for interaction, evidence, opportunity and timeline."""

    __slots__ = ("_evidence", "_evidence_read", "_opportunity")

    def __init__(
        self,
        evidence: EvidenceWritePort,
        evidence_read: EvidenceReadPort,
        opportunity: OpportunityAdmissionPort,
    ) -> None:
        self._evidence = evidence
        self._evidence_read = evidence_read
        self._opportunity = opportunity

    async def timeline_input_purpose(
        self, transaction: PostgreSQLTransaction, *, interaction_id: UUID
    ) -> str | None:
        row = await (
            await transaction.execute(
                """SELECT purpose FROM armi.party_input_interactions
                   WHERE interaction_id = %s""",
                (interaction_id,),
            )
        ).fetchone()
        return None if row is None else str(row[0])

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
                SELECT scene.subject_id, scene.scene_id, scene.primary_party_id
                FROM armi.interaction_scenes AS scene
                JOIN armi.parties AS creator
                  ON creator.party_id = scene.primary_party_id
                 AND creator.party_kind = 'creator'
                 AND creator.creator_role = 'unique_primary_creator'
                 AND creator.status = 'active'
                WHERE scene.scene_key = %s
                 AND scene.scene_kind = 'creator_dialogue'
                 AND scene.audience_scope = 'creator'
                 AND scene.current_status = 'open'
                 AND scene.closed_at IS NULL
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
                SELECT interaction.interaction_id, interaction.request_digest,
                    COALESCE(interaction.cognition_content_digest,
                             interaction.content_digest)
                FROM armi.party_input_interactions AS interaction
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
        if str(row[1]) != request_digest.value:
            raise CreatorInputViolation("IDEMPOTENCY-MISMATCH")
        evidence_id = await self._evidence_read.find_by_interaction(
            connection,
            interaction_id=row[0],
        )
        if evidence_id is None:
            raise CreatorInputViolation("DB-INPUT-STATE")
        opportunity = await self._opportunity.find_external_evidence(
            connection,
            evidence_id=evidence_id.value,
            purpose=OpportunityPurpose.CONSIDER_CREATOR_INPUT,
        )
        if opportunity is None:
            raise CreatorInputViolation("DB-INPUT-STATE")
        return _acceptance(
            (row[0], evidence_id.value, opportunity.value, row[1], row[2]),
            newly_accepted=False,
        )

    async def existing_voice(
        self,
        unit_of_work: PostgreSQLRuntimeUnitOfWork,
        *,
        context: CreatorInputContext,
        idempotency_key: str,
        request_digest: Digest,
    ) -> CreatorVoiceInputAcceptance | None:
        row = await (
            await unit_of_work.transaction.execute(
                """
                SELECT interaction_id,request_digest,
                       COALESCE(cognition_content_digest,content_digest)
                FROM armi.party_input_interactions
                WHERE source_party_id=%s AND scene_id=%s
                  AND purpose='creator_message' AND modality='live_voice'
                  AND idempotency_key=%s
                """,
                (context.creator_party_id, context.scene_id, idempotency_key),
            )
        ).fetchone()
        if row is None:
            return None
        if str(row[1]) != request_digest.value:
            raise CreatorInputViolation("IDEMPOTENCY-MISMATCH")
        evidence_id = await self._evidence_read.find_by_interaction(
            unit_of_work.transaction,
            interaction_id=row[0],
        )
        if evidence_id is None:
            raise CreatorInputViolation("DB-INPUT-STATE")
        return CreatorVoiceInputAcceptance(
            CreatorInteractionId(row[0]),
            evidence_id,
            Digest(str(row[1])),
            Digest(str(row[2])),
            False,
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

    async def create_voice(
        self,
        unit_of_work: PostgreSQLRuntimeUnitOfWork,
        *,
        context: CreatorInputContext,
        idempotency_key: str,
        request_digest: Digest,
        content_digest: Digest,
        artifact_id: UUID,
        trace_id: str,
    ) -> CreatorVoiceInputAcceptance:
        """Persist voice evidence once; a later route owns successor admission."""

        connection = unit_of_work.transaction
        interaction_id = uuid7()
        evidence_id = uuid7()
        timeline_item_id = uuid7()
        await connection.execute(
            """
            INSERT INTO armi.party_input_interactions (
                interaction_id,subject_id,scene_id,source_party_id,purpose,
                idempotency_key,request_digest,content_digest,trace_id,modality)
            VALUES (%s,%s,%s,%s,'creator_message',%s,%s,%s,%s,'live_voice')
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
        await connection.execute(
            """
            INSERT INTO armi.scene_timeline_items (
                timeline_item_id,scene_id,source_kind,source_ref,
                source_event_no,result_status,occurred_at)
            VALUES (%s,%s,'creator_input',%s,1,'accepted',statement_timestamp())
            """,
            (timeline_item_id, context.scene_id, interaction_id),
        )
        boundary = await connection.execute(
            """
            UPDATE armi.interaction_scenes
            SET recent_context_boundary=%s,scene_version=scene_version+1
            WHERE scene_id=%s AND current_status='open' AND closed_at IS NULL
              AND recent_context_boundary IS DISTINCT FROM %s
            """,
            (timeline_item_id, context.scene_id, timeline_item_id),
        )
        if boundary.rowcount != 1:
            raise CreatorInputViolation("SCOPE-SCENE-NOT-VISIBLE")
        return CreatorVoiceInputAcceptance(
            CreatorInteractionId(interaction_id),
            EvidenceId(evidence_id),
            request_digest,
            content_digest,
            True,
        )

    async def admit_voice_slow(
        self,
        unit_of_work: PostgreSQLRuntimeUnitOfWork,
        acceptance: CreatorVoiceInputAcceptance,
    ) -> OpportunityId:
        return await self._admit_voice_successor(
            unit_of_work,
            acceptance,
            purpose=OpportunityPurpose.CONSIDER_CREATOR_INPUT,
        )

    async def admit_voice_appraisal(
        self,
        unit_of_work: PostgreSQLRuntimeUnitOfWork,
        acceptance: CreatorVoiceInputAcceptance,
    ) -> OpportunityId:
        return await self._admit_voice_successor(
            unit_of_work,
            acceptance,
            purpose=OpportunityPurpose.CONSIDER_CREATOR_VOICE_APPRAISAL,
        )

    async def _admit_voice_successor(
        self,
        unit_of_work: PostgreSQLRuntimeUnitOfWork,
        acceptance: CreatorVoiceInputAcceptance,
        *,
        purpose: OpportunityPurpose,
    ) -> OpportunityId:
        row = await (
            await unit_of_work.transaction.execute(
                """SELECT subject_id,scene_id,source_party_id
                   FROM armi.party_input_interactions
                   WHERE interaction_id=%s AND modality='live_voice'""",
                (acceptance.interaction_id.value,),
            )
        ).fetchone()
        if row is None:
            raise CreatorInputViolation("DB-INPUT-STATE")
        admitted = await self._opportunity.admit_external_evidence(
            unit_of_work.transaction,
            ExternalEvidenceOpportunityDraft(
                evidence_id=acceptance.evidence_id.value,
                subject_id=row[0],
                scene_id=row[1],
                context_party_id=row[2],
                purpose=purpose,
            ),
        )
        if admitted.opportunity_id is None:
            raise CreatorInputViolation("DB-INPUT-STATE")
        return OpportunityId(admitted.opportunity_id)

    async def find_codex_task_input(
        self,
        transaction: PostgreSQLTransaction,
        *,
        creator_party_id: UUID,
        scene_id: UUID,
        idempotency_key: str,
    ) -> tuple[UUID, Digest, Digest] | None:
        row = await (
            await transaction.execute(
                """
                SELECT interaction_id, request_digest, content_digest
                FROM armi.party_input_interactions
                WHERE source_party_id=%s AND scene_id=%s
                  AND purpose='codex_task_request' AND idempotency_key=%s
                """,
                (creator_party_id, scene_id, idempotency_key),
            )
        ).fetchone()
        if row is None:
            return None
        return row[0], Digest(str(row[1])), Digest(str(row[2]))

    async def operation_acceptance(
        self,
        transaction: PostgreSQLTransaction,
        *,
        interaction_id: UUID | None,
        scene_id: UUID,
        creator_party_id: UUID,
        codex_content_digest: Digest | None,
        evidence_id: UUID,
        opportunity_id: UUID,
    ) -> CreatorInputAcceptance | None:
        if interaction_id is not None:
            row = await (
                await transaction.execute(
                    """
                    SELECT interaction_id, request_digest,
                           COALESCE(cognition_content_digest, content_digest)
                    FROM armi.party_input_interactions
                    WHERE interaction_id=%s AND scene_id=%s
                      AND source_party_id=%s
                    """,
                    (interaction_id, scene_id, creator_party_id),
                )
            ).fetchone()
        elif codex_content_digest is not None:
            row = await (
                await transaction.execute(
                    """
                    SELECT interaction_id, request_digest, content_digest
                    FROM armi.party_input_interactions
                    WHERE scene_id=%s AND source_party_id=%s
                      AND purpose='codex_task_request' AND content_digest=%s
                    """,
                    (scene_id, creator_party_id, codex_content_digest.value),
                )
            ).fetchone()
        else:
            return None
        if row is None:
            return None
        return _acceptance(
            (row[0], evidence_id, opportunity_id, row[1], row[2]),
            newly_accepted=False,
        )

    async def record_codex_task_input(
        self,
        transaction: PostgreSQLTransaction,
        *,
        interaction_id: UUID,
        subject_id: UUID,
        scene_id: UUID,
        creator_party_id: UUID,
        idempotency_key: str,
        request_digest: Digest,
        content_digest: Digest,
        trace_id: TraceId,
    ) -> None:
        timeline_id = uuid7()
        await transaction.execute(
            """
            INSERT INTO armi.party_input_interactions (
                interaction_id, subject_id, scene_id, source_party_id,
                purpose, idempotency_key, request_digest, content_digest,
                trace_id) VALUES (%s,%s,%s,%s,'codex_task_request',%s,%s,%s,%s)
            """,
            (
                interaction_id,
                subject_id,
                scene_id,
                creator_party_id,
                idempotency_key,
                request_digest.value,
                content_digest.value,
                trace_id.value,
            ),
        )
        await transaction.execute(
            """
            INSERT INTO armi.scene_timeline_items (
                timeline_item_id, scene_id, source_kind, source_ref,
                source_event_no, result_status, occurred_at)
            VALUES (%s,%s,'creator_input',%s,1,'accepted',statement_timestamp())
            """,
            (timeline_id, scene_id, interaction_id),
        )
        await transaction.execute(
            """
            UPDATE armi.interaction_scenes SET recent_context_boundary=%s,
                scene_version=scene_version+1
            WHERE scene_id=%s AND current_status='open' AND closed_at IS NULL
              AND recent_context_boundary IS DISTINCT FROM %s
            """,
            (timeline_id, scene_id, timeline_id),
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
