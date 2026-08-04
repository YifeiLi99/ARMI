"""PostgreSQL ownership for autonomous life opportunity admission."""

from __future__ import annotations

from uuid import uuid7

import rfc8785
from armi_kernel.application import (
    AuditDraft,
    AuditEventId,
    AuditReference,
    AuditResultStatus,
    AuditSensitivity,
    LifeOpportunitySourceKind,
    LifeViolation,
    OpportunityAdmissionOutcome,
    OpportunityAdmissionStatus,
)
from armi_kernel.contracts import Digest, Purpose, SubjectId, TraceId

from .unit_of_work import PostgreSQLUnitOfWork


class PostgreSQLLifeOpportunityRepository:
    """Admit one source-backed root opportunity under the active Runtime fence."""

    async def admit_generation_available(
        self,
        unit_of_work: PostgreSQLUnitOfWork,
    ) -> OpportunityAdmissionOutcome:
        fence = unit_of_work.runtime_fence
        if fence is None:
            raise LifeViolation("LIFE-FENCE-REQUIRED")
        connection = unit_of_work._connection_for_repository()  # pyright: ignore[reportPrivateUsage]
        row = await (
            await connection.execute(
                """
                SELECT generation_no, activation_reason
                FROM armi.life_generations
                WHERE life_generation_id = %s
                  AND subject_id = %s
                  AND status = 'active'
                """,
                (fence.life_generation_id, fence.subject_id),
            )
        ).fetchone()
        if row is None:
            raise LifeViolation("LIFE-SOURCE-STALE")
        source_bytes = rfc8785.dumps(
            {
                "schema_version": "armi.life-opportunity-source.v1",
                "kind": LifeOpportunitySourceKind.LIFE_GENERATION_AVAILABLE.value,
                "subject_id": str(fence.subject_id),
                "life_generation_id": str(fence.life_generation_id),
                "generation_no": int(row[0]),
                "activation_reason": str(row[1]),
            }
        )
        digest = Digest.from_bytes(source_bytes)
        opportunity_id = uuid7()
        inserted = await (
            await connection.execute(
                """
                INSERT INTO armi.opportunities (
                    opportunity_id, evidence_id, subject_id, scene_id,
                    creator_party_id, purpose, eligibility_status,
                    current_disposition, root_opportunity_id,
                    reconsideration_no, source_kind, source_ref,
                    source_version, source_digest, schema_version
                )
                VALUES (
                    %s, NULL, %s, NULL, NULL, 'consider_autonomous_life',
                    'eligible', 'open', %s, 0,
                    'life_generation_available', %s, %s, %s, 1
                )
                ON CONFLICT (
                    subject_id, source_kind, source_ref, source_version,
                    purpose, reconsideration_no
                ) DO NOTHING
                RETURNING opportunity_id
                """,
                (
                    opportunity_id,
                    fence.subject_id,
                    opportunity_id,
                    fence.life_generation_id,
                    int(row[0]),
                    digest.value,
                ),
            )
        ).fetchone()
        if inserted is None:
            existing = await (
                await connection.execute(
                    """
                    SELECT opportunity_id, source_digest
                    FROM armi.opportunities
                    WHERE subject_id = %s
                      AND source_kind = 'life_generation_available'
                      AND source_ref = %s
                      AND source_version = %s
                      AND purpose = 'consider_autonomous_life'
                      AND reconsideration_no = 0
                    """,
                    (fence.subject_id, fence.life_generation_id, int(row[0])),
                )
            ).fetchone()
            if existing is None or str(existing[1]) != digest.value:
                raise LifeViolation("LIFE-SOURCE-DRIFT")
            return OpportunityAdmissionOutcome(
                OpportunityAdmissionStatus.DUPLICATE,
                existing[0],
            )
        trace_id = TraceId(opportunity_id.hex)
        await unit_of_work.audit.append(
            AuditDraft(
                AuditEventId(uuid7()),
                AuditReference("runtime", unit_of_work.environment_id),
                Purpose("life.opportunity"),
                "life.opportunity.admitted",
                AuditReference("opportunity", opportunity_id),
                AuditResultStatus.APPLIED,
                trace_id,
                AuditSensitivity.PRIVATE,
                subject_id=SubjectId(fence.subject_id),
                request=AuditReference("life_generation", fence.life_generation_id),
                request_digest=digest,
            )
        )
        return OpportunityAdmissionOutcome(
            OpportunityAdmissionStatus.ADMITTED,
            opportunity_id,
        )


__all__ = ("PostgreSQLLifeOpportunityRepository",)
