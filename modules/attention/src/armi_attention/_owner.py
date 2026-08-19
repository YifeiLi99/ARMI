"""PostgreSQL owner ports for opportunity facts shared within a caller UoW."""

from __future__ import annotations

from datetime import datetime
from typing import cast
from uuid import UUID, uuid7

from armi_runtime_foundation import PostgreSQLTransaction
from armi_sleep.api import SleepOpportunityDraft, SleepOpportunityResult

from .api import (
    ExternalEvidenceOpportunityDraft,
    LifeQueryResultOpportunityDraft,
    LifeViolation,
    OpportunityAdmissionOutcome,
    OpportunityAdmissionStatus,
    OpportunityCognitionCandidate,
    OpportunityCognitionSelectionScope,
    OpportunityCommitSnapshot,
    OpportunityId,
    OpportunityOperationSnapshot,
    OpportunityPurpose,
    OpportunitySelectionCursor,
)


class PostgreSQLOpportunityOwner:
    async def admit_sleep(
        self,
        transaction: PostgreSQLTransaction,
        draft: SleepOpportunityDraft,
    ) -> SleepOpportunityResult:
        opportunity_id = uuid7()
        row = await (
            await transaction.execute(
                """
                INSERT INTO armi.opportunities (
                    opportunity_id,evidence_id,subject_id,scene_id,context_party_id,
                    purpose,eligibility_status,current_disposition,root_opportunity_id,
                    predecessor_opportunity_id,reconsideration_no,available_after,
                    expires_at,source_kind,source_ref,source_version,activity_id)
                VALUES (%s,NULL,%s,NULL,NULL,%s,'eligible','open',%s,%s,%s,%s,%s,%s,%s,%s,NULL)
                ON CONFLICT (subject_id,source_kind,source_ref,source_version,purpose,reconsideration_no)
                DO NOTHING RETURNING opportunity_id
                """,
                (
                    opportunity_id,
                    draft.subject_id,
                    draft.purpose,
                    draft.root_id or opportunity_id,
                    draft.predecessor_id,
                    draft.reconsideration_no,
                    draft.available_after,
                    draft.expires_at,
                    draft.source_kind,
                    draft.source_ref,
                    draft.source_version,
                ),
            )
        ).fetchone()
        if row is not None:
            return SleepOpportunityResult(row[0], True)
        existing = await (
            await transaction.execute(
                """SELECT opportunity_id FROM armi.opportunities
                   WHERE subject_id=%s AND source_kind=%s AND source_ref=%s
                     AND source_version=%s AND purpose=%s AND reconsideration_no=%s""",
                (
                    draft.subject_id,
                    draft.source_kind,
                    draft.source_ref,
                    draft.source_version,
                    draft.purpose,
                    draft.reconsideration_no,
                ),
            )
        ).fetchone()
        return SleepOpportunityResult(None if existing is None else existing[0], False)

    async def cancel_sleep_source(
        self,
        transaction: PostgreSQLTransaction,
        *,
        subject_id: UUID,
        source_kind: str,
        source_ref: UUID,
    ) -> None:
        await transaction.execute(
            """UPDATE armi.opportunities SET current_disposition='cancelled',
                      resolved_at=statement_timestamp()
               WHERE subject_id=%s AND source_kind=%s AND source_ref=%s
                 AND current_disposition IN ('open','selected')""",
            (subject_id, source_kind, source_ref),
        )

    async def next_candidate(
        self,
        transaction: PostgreSQLTransaction,
        *,
        scope: OpportunityCognitionSelectionScope,
        after: OpportunitySelectionCursor | None = None,
    ) -> OpportunityCognitionCandidate | None:
        row = await (
            await transaction.execute(
                """
                SELECT opportunity_id, root_opportunity_id, evidence_id,
                       subject_id, scene_id, context_party_id, purpose,
                       source_kind, source_ref, source_version,
                       available_after, expires_at, activity_id
                FROM armi.opportunities
                WHERE subject_id=%s AND eligibility_status='eligible'
                  AND current_disposition='open'
                  AND available_after <= transaction_timestamp()
                  AND (expires_at IS NULL OR expires_at > transaction_timestamp())
                  AND (%s::timestamptz IS NULL OR (available_after, opportunity_id) > (%s, %s))
                  AND (%s::uuid IS NULL OR (
                       source_kind='maintenance_phase_revision'
                       AND source_ref=%s AND source_version=%s AND purpose=%s))
                ORDER BY available_after, opportunity_id
                FOR UPDATE SKIP LOCKED LIMIT 1
                """,
                (
                    scope.subject_id,
                    None if after is None else after.available_after,
                    None if after is None else after.available_after,
                    None if after is None else after.opportunity_id,
                    scope.maintenance_source_ref,
                    scope.maintenance_source_ref,
                    scope.maintenance_source_version,
                    scope.maintenance_purpose,
                ),
            )
        ).fetchone()
        if row is None:
            return None
        return _cognition_candidate(row)

    async def context_snapshot(
        self, transaction: PostgreSQLTransaction, *, opportunity_id: UUID
    ) -> OpportunityCognitionCandidate:
        row = await (
            await transaction.execute(
                """SELECT opportunity_id, root_opportunity_id, evidence_id,
                          subject_id, scene_id, context_party_id, purpose,
                          source_kind, source_ref, source_version,
                          available_after, expires_at, activity_id
                   FROM armi.opportunities WHERE opportunity_id=%s""",
                (opportunity_id,),
            )
        ).fetchone()
        if row is None:
            raise LifeViolation("LIFE-OPPORTUNITY-STATE")
        return _cognition_candidate(row)

    async def select_for_cognition(
        self, transaction: PostgreSQLTransaction, *, opportunity_id: UUID
    ) -> bool:
        row = await (
            await transaction.execute(
                """UPDATE armi.opportunities SET current_disposition='selected',
                      selected_at=transaction_timestamp()
               WHERE opportunity_id=%s AND current_disposition='open'
                 AND (expires_at IS NULL OR expires_at>transaction_timestamp())
               RETURNING opportunity_id""",
                (opportunity_id,),
            )
        ).fetchone()
        return row is not None

    async def resolve_cognition_failure(
        self, transaction: PostgreSQLTransaction, *, opportunity_id: UUID
    ) -> bool:
        row = await (
            await transaction.execute(
                """UPDATE armi.opportunities SET current_disposition='resolved',
                      resolved_at=statement_timestamp()
               WHERE opportunity_id=%s AND current_disposition='selected'
               RETURNING opportunity_id""",
                (opportunity_id,),
            )
        ).fetchone()
        return row is not None

    async def operation_snapshot(
        self,
        transaction: PostgreSQLTransaction,
        *,
        root_opportunity_id: UUID,
        context_party_id: UUID,
    ) -> OpportunityOperationSnapshot | None:
        row = await (
            await transaction.execute(
                """
                SELECT root.opportunity_id, current.opportunity_id,
                       root.evidence_id, current.subject_id, current.scene_id,
                       current.context_party_id, root.purpose,
                       current.current_disposition, current.reconsideration_no
                FROM armi.opportunities AS root
                JOIN LATERAL (
                    SELECT item.* FROM armi.opportunities AS item
                    WHERE item.root_opportunity_id=root.opportunity_id
                    ORDER BY item.reconsideration_no DESC LIMIT 1
                ) AS current ON true
                WHERE root.opportunity_id=%s
                  AND root.root_opportunity_id=root.opportunity_id
                  AND current.context_party_id=%s
                  AND root.purpose IN ('consider_creator_input','consider_codex_task')
                  AND current.eligibility_status='eligible'
                  AND current.expires_at IS NULL
                """,
                (root_opportunity_id, context_party_id),
            )
        ).fetchone()
        if row is None or row[2] is None or row[4] is None or row[5] is None:
            return None
        return OpportunityOperationSnapshot(
            row[0],
            row[1],
            row[2],
            row[3],
            row[4],
            row[5],
            str(row[6]),
            str(row[7]),
            int(row[8]),
        )

    async def subject_commit_snapshot(
        self, transaction: PostgreSQLTransaction, *, opportunity_id: UUID
    ) -> OpportunityCommitSnapshot:
        row = await (
            await transaction.execute(
                """
                SELECT opportunity_id, root_opportunity_id, reconsideration_no,
                       evidence_id, subject_id, scene_id, context_party_id,
                       purpose, source_kind, source_ref, source_version, activity_id,
                       available_after, expires_at
                FROM armi.opportunities
                WHERE opportunity_id = %s
                  AND current_disposition = 'selected'
                """,
                (opportunity_id,),
            )
        ).fetchone()
        if row is None:
            raise LifeViolation("LIFE-OPPORTUNITY-STATE")
        return OpportunityCommitSnapshot(
            opportunity_id=row[0],
            root_opportunity_id=row[1],
            reconsideration_no=int(row[2]),
            evidence_id=row[3],
            subject_id=row[4],
            scene_id=row[5],
            context_party_id=row[6],
            purpose=str(row[7]),
            source_kind=str(row[8]),
            source_ref=row[9],
            source_version=int(row[10]),
            activity_id=row[11],
            available_after=row[12],
            expires_at=row[13],
        )

    async def resolve_subject_commit(
        self,
        transaction: PostgreSQLTransaction,
        *,
        opportunity_id: UUID,
        disposition: str = "resolved",
    ) -> None:
        if disposition not in {"resolved", "superseded"}:
            raise LifeViolation("LIFE-OPPORTUNITY-STATE")
        row = await (
            await transaction.execute(
                """
                UPDATE armi.opportunities
                SET current_disposition = %s, resolved_at = statement_timestamp()
                WHERE opportunity_id = %s AND current_disposition = 'selected'
                RETURNING opportunity_id
                """,
                (disposition, opportunity_id),
            )
        ).fetchone()
        if row is None:
            raise LifeViolation("LIFE-OPPORTUNITY-STATE")

    async def supersede_subject_commit(
        self, transaction: PostgreSQLTransaction, *, opportunity_id: UUID
    ) -> OpportunityId | None:
        source = await self.subject_commit_snapshot(
            transaction, opportunity_id=opportunity_id
        )
        successor: OpportunityId | None = None
        if source.reconsideration_no == 0:
            successor_id = uuid7()
            row = await (
                await transaction.execute(
                    """
                    INSERT INTO armi.opportunities (
                        opportunity_id, evidence_id, subject_id, scene_id,
                        context_party_id, purpose, eligibility_status,
                        current_disposition, root_opportunity_id,
                        predecessor_opportunity_id, reconsideration_no,
                        source_kind, source_ref, source_version, activity_id
                    ) VALUES (
                        %s, %s, %s, %s, %s, %s, 'eligible', 'open',
                        %s, %s, 1, %s, %s, %s, %s
                    )
                    ON CONFLICT (predecessor_opportunity_id) DO NOTHING
                    RETURNING opportunity_id
                    """,
                    (
                        successor_id,
                        source.evidence_id,
                        source.subject_id,
                        source.scene_id,
                        source.context_party_id,
                        source.purpose,
                        source.root_opportunity_id,
                        source.opportunity_id,
                        source.source_kind,
                        source.source_ref,
                        source.source_version,
                        source.activity_id,
                    ),
                )
            ).fetchone()
            if row is None:
                raise LifeViolation("LIFE-ADMISSION-CONFLICT")
            successor = OpportunityId(row[0])
        await self.resolve_subject_commit(
            transaction,
            opportunity_id=opportunity_id,
            disposition="superseded" if successor is not None else "resolved",
        )
        return successor

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
                    root_opportunity_id, reconsideration_no, expires_at)
                VALUES (%s,%s,%s,%s,%s,%s,'external_evidence',%s,1,
                        'eligible','open',%s,0,
                        CASE WHEN %s='consider_visual_observation'
                             THEN statement_timestamp()+interval '5 minutes' END)
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
                    draft.purpose.value,
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


def _cognition_candidate(row: tuple[object, ...]) -> OpportunityCognitionCandidate:
    return OpportunityCognitionCandidate(
        opportunity_id=cast(UUID, row[0]),
        root_opportunity_id=cast(UUID, row[1]),
        evidence_id=cast(UUID | None, row[2]),
        subject_id=cast(UUID, row[3]),
        scene_id=cast(UUID | None, row[4]),
        context_party_id=cast(UUID | None, row[5]),
        purpose=str(row[6]),
        source_kind=str(row[7]),
        source_ref=cast(UUID, row[8]),
        source_version=cast(int, row[9]),
        available_after=cast(datetime, row[10]),
        expires_at=cast(datetime | None, row[11]),
        activity_id=cast(UUID | None, row[12]),
    )
