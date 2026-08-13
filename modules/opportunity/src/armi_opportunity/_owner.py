"""PostgreSQL owner ports for opportunity facts shared within a caller UoW."""

from __future__ import annotations

from uuid import UUID, uuid7

from armi_runtime_foundation import PostgreSQLTransaction

from .api import (
    ExternalEvidenceOpportunityDraft,
    LifeQueryResultOpportunityDraft,
    LifeViolation,
    OpportunityAdmissionOutcome,
    OpportunityAdmissionStatus,
    OpportunityId,
    OpportunityPurpose,
)


class PostgreSQLOpportunityOwner:
    async def admit_life_query_result(
        self,
        transaction: PostgreSQLTransaction,
        draft: LifeQueryResultOpportunityDraft,
    ) -> OpportunityId:
        row = await (
            await transaction.execute(
                """
                INSERT INTO armi.opportunities (
                    opportunity_id, evidence_id, subject_id, scene_id,
                    creator_party_id, purpose, source_kind, source_ref,
                    source_version, eligibility_status,
                    current_disposition, root_opportunity_id,
                    predecessor_opportunity_id, reconsideration_no)
                SELECT %s, NULL, %s, %s, %s, 'consider_life_query_result',
                       'life_query_result', %s, 1, 'eligible', 'open',
                       source.root_opportunity_id, %s,
                       source.reconsideration_no + 1
                FROM armi.opportunities AS source
                WHERE source.opportunity_id = %s
                RETURNING opportunity_id
                """,
                (
                    draft.opportunity_id,
                    draft.subject_id,
                    draft.scene_id,
                    draft.creator_party_id,
                    draft.intent_id,
                    draft.source_opportunity_id,
                    draft.source_opportunity_id,
                ),
            )
        ).fetchone()
        if row is None:
            raise LifeViolation("LIFE-ADMISSION-CONFLICT")
        return OpportunityId(row[0])

    async def reconsider_activity(
        self,
        transaction: PostgreSQLTransaction,
        *,
        subject_id: UUID,
        root_opportunity_id: UUID,
        predecessor_opportunity_id: UUID,
        source_ref: UUID,
        source_version: int,
        activity_id: UUID,
    ) -> OpportunityId | None:
        successor_id = uuid7()
        row = await (
            await transaction.execute(
                """
                INSERT INTO armi.opportunities (
                    opportunity_id, evidence_id, subject_id, scene_id,
                    context_party_id, purpose, eligibility_status,
                    current_disposition, available_after, root_opportunity_id,
                    predecessor_opportunity_id, reconsideration_no, source_kind,
                    source_ref, source_version, activity_id) VALUES (
                    %s, NULL, %s, NULL, NULL, 'consider_activity_attention',
                    'eligible', 'open',
                    statement_timestamp() + make_interval(secs => 60),
                    %s, %s, 1, 'activity_revision', %s, %s, %s)
                ON CONFLICT (predecessor_opportunity_id) DO NOTHING
                RETURNING opportunity_id
                """,
                (
                    successor_id,
                    subject_id,
                    root_opportunity_id,
                    predecessor_opportunity_id,
                    source_ref,
                    source_version,
                    activity_id,
                ),
            )
        ).fetchone()
        return None if row is None else OpportunityId(row[0])

    async def reconsider_sleep(
        self,
        transaction: PostgreSQLTransaction,
        *,
        predecessor_opportunity_id: UUID,
    ) -> OpportunityId | None:
        successor_id = uuid7()
        row = await (
            await transaction.execute(
                """
                INSERT INTO armi.opportunities (
                    opportunity_id, evidence_id, subject_id, scene_id,
                    context_party_id, purpose, eligibility_status,
                    current_disposition, available_after, expires_at,
                    root_opportunity_id, predecessor_opportunity_id,
                    reconsideration_no, source_kind, source_ref, source_version,
                    activity_id)
                SELECT %s, NULL, subject_id, NULL, NULL, purpose, 'eligible',
                       'open', statement_timestamp() + make_interval(secs => 3600),
                       expires_at, root_opportunity_id, opportunity_id, 1,
                       source_kind, source_ref, source_version, NULL
                FROM armi.opportunities
                WHERE opportunity_id = %s
                  AND statement_timestamp() + make_interval(secs => 3600)
                      < expires_at
                ON CONFLICT (predecessor_opportunity_id) DO NOTHING
                RETURNING opportunity_id
                """,
                (successor_id, predecessor_opportunity_id),
            )
        ).fetchone()
        return None if row is None else OpportunityId(row[0])

    async def admit_external_evidence(
        self,
        transaction: PostgreSQLTransaction,
        draft: ExternalEvidenceOpportunityDraft,
    ) -> OpportunityAdmissionOutcome:
        opportunity_id = uuid7()
        row = await (
            await transaction.execute(
                """
                INSERT INTO armi.opportunities (
                    opportunity_id, evidence_id, subject_id, scene_id,
                    context_party_id, purpose, source_kind, source_ref,
                    source_version, eligibility_status, current_disposition,
                    root_opportunity_id, reconsideration_no)
                VALUES (%s,%s,%s,%s,%s,%s,'external_evidence',%s,1,
                        'eligible','open',%s,0)
                ON CONFLICT (
                    subject_id, source_kind, source_ref, source_version,
                    purpose, reconsideration_no
                ) DO NOTHING
                RETURNING opportunity_id
                """,
                (
                    opportunity_id,
                    draft.evidence_id,
                    draft.subject_id,
                    draft.scene_id,
                    draft.context_party_id,
                    draft.purpose.value,
                    draft.evidence_id,
                    opportunity_id,
                ),
            )
        ).fetchone()
        if row is not None:
            return OpportunityAdmissionOutcome(
                OpportunityAdmissionStatus.ADMITTED, row[0]
            )
        existing = await self.find_external_evidence(
            transaction,
            evidence_id=draft.evidence_id,
            purpose=draft.purpose,
        )
        if existing is None:
            return OpportunityAdmissionOutcome(
                OpportunityAdmissionStatus.REJECTED,
                None,
                "LIFE-ADMISSION-CONFLICT",
            )
        return OpportunityAdmissionOutcome(
            OpportunityAdmissionStatus.DUPLICATE, existing.value
        )

    async def find_external_evidence(
        self,
        transaction: PostgreSQLTransaction,
        *,
        evidence_id: UUID,
        purpose: OpportunityPurpose,
    ) -> OpportunityId | None:
        row = await (
            await transaction.execute(
                """
                SELECT opportunity_id
                FROM armi.opportunities
                WHERE evidence_id = %s
                  AND source_kind = 'external_evidence'
                  AND source_ref = %s
                  AND source_version = 1
                  AND purpose = %s
                  AND reconsideration_no = 0
                """,
                (evidence_id, evidence_id, purpose.value),
            )
        ).fetchone()
        return None if row is None else OpportunityId(row[0])


__all__ = ("PostgreSQLOpportunityOwner",)
