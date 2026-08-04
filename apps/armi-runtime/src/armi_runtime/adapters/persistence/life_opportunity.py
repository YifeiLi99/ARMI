"""PostgreSQL ownership for autonomous life opportunity admission."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import cast
from uuid import uuid7

import rfc8785
from armi_kernel.application import (
    ActivityHeadSnapshot,
    ActivityStatus,
    ActivityWaitingKind,
    AuditDraft,
    AuditEventId,
    AuditReference,
    AuditResultStatus,
    AuditSensitivity,
    LifeOpportunitySourceKind,
    LifeSchedulingDisposition,
    LifeSchedulingSnapshot,
    LifeViolation,
    OpportunityAdmissionOutcome,
    OpportunityAdmissionStatus,
    PostgreSqlFairLifeScheduler,
)
from armi_kernel.contracts import ActivityId, Digest, Purpose, SubjectId, TraceId

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

    async def admit_activity_attention(
        self,
        unit_of_work: PostgreSQLUnitOfWork,
        *,
        model_concurrency: int,
    ) -> OpportunityAdmissionOutcome:
        fence = unit_of_work.runtime_fence
        if fence is None:
            raise LifeViolation("LIFE-FENCE-REQUIRED")
        connection = unit_of_work._connection_for_repository()  # pyright: ignore[reportPrivateUsage]
        state = await (
            await connection.execute(
                """
                SELECT revision.semantic_payload,
                       EXISTS (
                           SELECT 1 FROM armi.opportunities
                           WHERE subject_id = %s
                             AND purpose = 'consider_activity_attention'
                             AND current_disposition IN ('open', 'selected')
                       ),
                       (SELECT count(*) FROM armi.cognitive_episodes
                        WHERE status NOT IN (
                            'completed', 'stale', 'failed', 'cancelled',
                            'candidate_rejected'
                        ))
                FROM armi.subject_component_heads AS head
                JOIN armi.subject_component_revisions AS revision
                  ON revision.component_revision_id = head.current_revision_id
                WHERE head.subject_id = %s AND head.component_kind = 'life_mode'
                """,
                (fence.subject_id, fence.subject_id),
            )
        ).fetchone()
        if state is None or not isinstance(state[0], dict):
            raise LifeViolation("LIFE-SCHEDULER-STATE")
        life_mode = cast(dict[str, object], state[0])
        active_values = life_mode.get("active_activities")
        if type(active_values) is not list:
            raise LifeViolation("LIFE-SCHEDULER-FOCUS")
        active_list = cast(list[object], active_values)
        if len(active_list) > 1:
            raise LifeViolation("LIFE-SCHEDULER-FOCUS")
        try:
            active_ids = tuple(ActivityId.from_wire(value) for value in active_list)
        except Exception:
            raise LifeViolation("LIFE-SCHEDULER-FOCUS") from None
        rows = await (
            await connection.execute(
                """
                SELECT activity.activity_id, revision.activity_revision_id,
                       revision.revision_no, revision.status, revision.created_at,
                       max(previous.available_after) AS last_considered_at,
                       revision.waiting_condition_kind,
                       revision.resume_not_before,
                       CASE
                         WHEN revision.waiting_condition_kind = 'creator_input' THEN EXISTS (
                           SELECT 1 FROM armi.creator_input_interactions AS input
                           WHERE input.received_at > revision.created_at
                         )
                         WHEN revision.waiting_condition_kind = 'external_evidence' THEN EXISTS (
                           SELECT 1 FROM armi.external_evidence AS evidence
                           WHERE evidence.subject_id = activity.subject_id
                             AND evidence.received_at > revision.created_at
                         )
                         ELSE false
                       END AS waiting_signal_available,
                       revision.goal, revision.progress_summary,
                       revision.next_safe_step, revision.resumption_cue,
                       revision.terminal_reason
                FROM armi.activities AS activity
                JOIN armi.activity_revisions AS revision
                  ON revision.activity_revision_id = activity.current_revision_id
                LEFT JOIN armi.opportunities AS previous
                  ON previous.source_kind = 'activity_revision'
                 AND previous.source_ref = revision.activity_revision_id
                 AND previous.purpose = 'consider_activity_attention'
                WHERE activity.subject_id = %s
                GROUP BY activity.activity_id, revision.activity_revision_id
                """,
                (fence.subject_id,),
            )
        ).fetchall()
        heads = tuple(
            ActivityHeadSnapshot(
                ActivityId(row[0]),
                row[1],
                int(row[2]),
                ActivityStatus(str(row[3])),
                row[4],
                row[5],
                None if row[6] is None else ActivityWaitingKind(str(row[6])),
                row[7],
                bool(row[8]),
            )
            for row in rows
        )
        decision = PostgreSqlFairLifeScheduler().select(
            LifeSchedulingSnapshot(
                datetime.now(UTC),
                heads,
                active_ids,
                bool(state[1]),
                model_concurrency,
                int(state[2]),
            )
        )
        if decision.disposition is not LifeSchedulingDisposition.ADMIT:
            return OpportunityAdmissionOutcome(
                OpportunityAdmissionStatus.REJECTED,
                None,
                decision.reason_code or "LIFE-SCHEDULER-IDLE",
            )
        selected = next(row for row in rows if row[1] == decision.activity_revision_id)
        source_bytes = rfc8785.dumps(
            {
                "schema_version": "armi.activity-revision-source.v1",
                "activity_id": str(selected[0]),
                "activity_revision_id": str(selected[1]),
                "revision_no": int(selected[2]),
                "status": str(selected[3]),
                "goal": str(selected[9]),
                "progress_summary": selected[10],
                "next_safe_step": selected[11],
                "resumption_cue": selected[12],
                "terminal_reason": selected[13],
            }
        )
        source_digest = Digest.from_bytes(source_bytes)
        opportunity_id = uuid7()
        inserted = await (
            await connection.execute(
                """
                INSERT INTO armi.opportunities (
                    opportunity_id, evidence_id, subject_id, scene_id,
                    creator_party_id, purpose, eligibility_status,
                    current_disposition, root_opportunity_id,
                    reconsideration_no, source_kind, source_ref,
                    source_version, source_digest, activity_id, schema_version
                ) VALUES (
                    %s, NULL, %s, NULL, NULL, 'consider_activity_attention',
                    'eligible', 'open', %s, 0, 'activity_revision',
                    %s, %s, %s, %s, 1
                )
                ON CONFLICT (
                    subject_id, source_kind, source_ref, source_version,
                    purpose, reconsideration_no
                ) DO NOTHING RETURNING opportunity_id
                """,
                (
                    opportunity_id,
                    fence.subject_id,
                    opportunity_id,
                    selected[1],
                    int(selected[2]),
                    source_digest.value,
                    selected[0],
                ),
            )
        ).fetchone()
        if inserted is None:
            existing = await (
                await connection.execute(
                    """
                    SELECT opportunity_id, source_digest
                    FROM armi.opportunities
                    WHERE subject_id = %s AND source_kind = 'activity_revision'
                      AND source_ref = %s AND source_version = %s
                      AND purpose = 'consider_activity_attention'
                      AND reconsideration_no = 0
                    """,
                    (fence.subject_id, selected[1], int(selected[2])),
                )
            ).fetchone()
            if existing is None or str(existing[1]) != source_digest.value:
                raise LifeViolation("LIFE-SOURCE-DRIFT")
            return OpportunityAdmissionOutcome(
                OpportunityAdmissionStatus.DUPLICATE, existing[0]
            )
        await unit_of_work.audit.append(
            AuditDraft(
                AuditEventId(uuid7()),
                AuditReference("runtime", unit_of_work.environment_id),
                Purpose("life.attention.opportunity"),
                "life.attention.opportunity.admitted",
                AuditReference("opportunity", opportunity_id),
                AuditResultStatus.APPLIED,
                TraceId(opportunity_id.hex),
                AuditSensitivity.PRIVATE,
                subject_id=SubjectId(fence.subject_id),
                request=AuditReference("activity_revision", selected[1]),
                request_digest=source_digest,
            )
        )
        return OpportunityAdmissionOutcome(
            OpportunityAdmissionStatus.ADMITTED, opportunity_id
        )


__all__ = ("PostgreSQLLifeOpportunityRepository",)
