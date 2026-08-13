"""PostgreSQL persistence owned by the evidence module."""

from __future__ import annotations

from uuid import UUID

from armi_runtime_foundation import PostgreSQLTransactionAccess

from .api import (
    EvidenceDraft,
    EvidenceId,
    EvidenceSnapshot,
    EvidenceViolation,
    ExperienceEvidenceLink,
)


class PostgreSQLEvidenceWriter:
    __slots__ = ()

    async def accept(
        self,
        transaction: PostgreSQLTransactionAccess,
        draft: EvidenceDraft,
    ) -> EvidenceId:
        await transaction.transaction.execute(
            """
            INSERT INTO armi.external_evidence (
                evidence_id, interaction_id, subject_id, scene_id,
                context_party_id, artifact_id, source_kind, trust_status,
                privacy_scope, acceptance_status, web_observation_request_id,
                observation_attempt_id, codex_task_source_id,
                codex_verification_id)
            VALUES (%s,%s,%s,%s,%s,%s,%s,'external_claim',%s,'accepted',
                    %s,%s,%s,%s)
            """,
            (
                draft.evidence_id.value,
                draft.interaction_id,
                draft.subject_id,
                draft.scene_id,
                draft.context_party_id,
                draft.artifact_id,
                draft.source_kind.value,
                draft.privacy_scope.value,
                draft.web_observation_request_id,
                draft.observation_attempt_id,
                draft.codex_task_source_id,
                draft.codex_verification_id,
            ),
        )
        return draft.evidence_id

    async def link_experience(
        self,
        transaction: PostgreSQLTransactionAccess,
        link: ExperienceEvidenceLink,
    ) -> None:
        await transaction.transaction.execute(
            """
            INSERT INTO armi.experience_evidence_links (
                experience_id, evidence_id, context_item_id, link_kind, ordinal)
            VALUES (%s, %s, %s, 'relied_on', %s)
            """,
            (
                link.experience_id,
                link.evidence_id.value,
                link.context_item_id,
                link.ordinal,
            ),
        )

    async def find_by_interaction(
        self,
        transaction: PostgreSQLTransactionAccess,
        *,
        interaction_id: UUID,
    ) -> EvidenceId | None:
        row = await (
            await transaction.transaction.execute(
                """
                SELECT evidence_id
                FROM armi.external_evidence
                WHERE interaction_id = %s
                """,
                (interaction_id,),
            )
        ).fetchone()
        return None if row is None else EvidenceId(row[0])

    async def snapshot(
        self,
        transaction: PostgreSQLTransactionAccess,
        *,
        evidence_id: EvidenceId,
    ) -> EvidenceSnapshot:
        row = await (
            await transaction.transaction.execute(
                """
                SELECT received_at
                FROM armi.external_evidence
                WHERE evidence_id = %s AND acceptance_status = 'accepted'
                """,
                (evidence_id.value,),
            )
        ).fetchone()
        if row is None:
            raise EvidenceViolation("EVIDENCE-NOT-FOUND")
        return EvidenceSnapshot(evidence_id, row[0])


__all__ = ("PostgreSQLEvidenceWriter",)
