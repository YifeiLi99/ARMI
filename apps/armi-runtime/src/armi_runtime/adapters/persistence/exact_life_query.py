"""PostgreSQL custody for committed subject exact-life queries."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID, uuid7

from armi_kernel.application import (
    ArtifactId,
    AuditDraft,
    AuditEventId,
    AuditReference,
    AuditResultStatus,
    AuditSensitivity,
    LifeRecordKind,
    LifeRecordQueryViolation,
    WorkLease,
    WorkResultRef,
)
from armi_kernel.contracts import Digest, Purpose, SubjectId, TraceId

from .unit_of_work import PostgreSQLUnitOfWork


@dataclass(frozen=True, slots=True)
class ExactLifeQuerySnapshot:
    intent_id: UUID
    subject_id: UUID
    source_opportunity_id: UUID
    scene_id: UUID
    creator_party_id: UUID
    record_kind: LifeRecordKind
    query_text: str | None
    limit: int
    query_digest: Digest
    trace_id: TraceId


class PostgreSQLExactLifeQueryRepository:
    """Select and settle one durable query without owning life records."""

    __slots__ = ()

    async def snapshot(
        self,
        unit_of_work: PostgreSQLUnitOfWork,
        lease: WorkLease,
    ) -> ExactLifeQuerySnapshot:
        fence = unit_of_work.runtime_fence
        if fence is None:
            raise LifeRecordQueryViolation("LIFE-QUERY-FENCE")
        connection = unit_of_work._connection_for_repository()  # pyright: ignore[reportPrivateUsage]
        row = await (
            await connection.execute(
                """
                SELECT intent.exact_life_query_intent_id, intent.subject_id,
                       intent.source_opportunity_id, intent.scene_id,
                       intent.context_party_id, intent.record_kind,
                       intent.query_text, intent.result_limit,
                       intent.query_digest, intent.trace_id
                FROM armi.durable_work AS work
                JOIN armi.exact_life_query_intents AS intent
                  ON intent.execution_work_id = work.work_id
                WHERE work.work_id = %s
                  AND work.work_kind = 'life.query.execute'
                  AND work.owner_kind = 'exact_life_query_intent'
                  AND work.status = 'leased'
                  AND work.current_attempt_id = %s
                  AND work.lease_owner = %s
                  AND work.lease_token = %s
                  AND work.lease_expires_at > statement_timestamp()
                  AND intent.status = 'pending'
                FOR UPDATE OF work, intent
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
            raise LifeRecordQueryViolation("LIFE-QUERY-WORK-STALE")
        if row[1] != fence.subject_id:
            raise LifeRecordQueryViolation("LIFE-QUERY-FENCE")
        return ExactLifeQuerySnapshot(
            intent_id=row[0],
            subject_id=row[1],
            source_opportunity_id=row[2],
            scene_id=row[3],
            creator_party_id=row[4],
            record_kind=LifeRecordKind(str(row[5])),
            query_text=None if row[6] is None else str(row[6]),
            limit=int(row[7]),
            query_digest=Digest(str(row[8])),
            trace_id=TraceId(str(row[9])),
        )

    async def settle(
        self,
        unit_of_work: PostgreSQLUnitOfWork,
        *,
        lease: WorkLease,
        snapshot: ExactLifeQuerySnapshot,
        status: str,
        result_artifact_id: ArtifactId,
        result_count: int,
        failure_code: str | None,
    ) -> UUID:
        if status not in {"succeeded", "empty", "failed", "denied"}:
            raise LifeRecordQueryViolation("LIFE-QUERY-RESULT")
        if (status in {"failed", "denied"}) != (failure_code is not None):
            raise LifeRecordQueryViolation("LIFE-QUERY-RESULT")
        if (status == "succeeded") != (result_count > 0):
            raise LifeRecordQueryViolation("LIFE-QUERY-RESULT")
        connection = unit_of_work._connection_for_repository()  # pyright: ignore[reportPrivateUsage]
        current = await (
            await connection.execute(
                """
                SELECT 1
                FROM armi.durable_work AS work
                JOIN armi.exact_life_query_intents AS intent
                  ON intent.execution_work_id = work.work_id
                WHERE work.work_id = %s
                  AND work.work_kind = 'life.query.execute'
                  AND work.owner_kind = 'exact_life_query_intent'
                  AND work.status = 'leased'
                  AND work.current_attempt_id = %s
                  AND work.lease_owner = %s
                  AND work.lease_token = %s
                  AND work.lease_expires_at > statement_timestamp()
                  AND intent.exact_life_query_intent_id = %s
                  AND intent.status = 'pending'
                FOR UPDATE OF work, intent
                """,
                (
                    lease.work_id.value,
                    lease.attempt_id.value,
                    lease.owner,
                    lease.token,
                    snapshot.intent_id,
                ),
            )
        ).fetchone()
        if current is None:
            raise LifeRecordQueryViolation("LIFE-QUERY-WORK-STALE")
        opportunity_id = uuid7()
        await connection.execute(
            """
            INSERT INTO armi.opportunities (
                opportunity_id, evidence_id, subject_id, scene_id,
                creator_party_id, purpose, source_kind, source_ref,
                source_version, eligibility_status,
                current_disposition, root_opportunity_id,
                predecessor_opportunity_id, reconsideration_no
            )
            SELECT %s, NULL, %s, %s, %s, 'consider_life_query_result',
                   'life_query_result', %s, 1,
                   'eligible', 'open', source.root_opportunity_id,
                   %s, source.reconsideration_no + 1
            FROM armi.opportunities AS source
            WHERE source.opportunity_id = %s
            """,
            (
                opportunity_id,
                snapshot.subject_id,
                snapshot.scene_id,
                snapshot.creator_party_id,
                snapshot.intent_id,
                snapshot.source_opportunity_id,
                snapshot.source_opportunity_id,
            ),
        )
        updated = await (
            await connection.execute(
                """
                UPDATE armi.exact_life_query_intents
                SET status = %s, result_artifact_id = %s,
                    result_count = %s,
                    failure_code = %s, result_opportunity_id = %s,
                    completed_at = statement_timestamp()
                WHERE exact_life_query_intent_id = %s AND status = 'pending'
                RETURNING exact_life_query_intent_id
                """,
                (
                    status,
                    result_artifact_id.value,
                    result_count,
                    failure_code,
                    opportunity_id,
                    snapshot.intent_id,
                ),
            )
        ).fetchone()
        if updated is None:
            raise LifeRecordQueryViolation("LIFE-QUERY-WORK-STALE")
        await unit_of_work.work.complete(
            lease,
            WorkResultRef("exact_life_query_result", snapshot.intent_id),
        )
        await unit_of_work.audit.append(
            AuditDraft(
                AuditEventId(uuid7()),
                AuditReference("runtime", unit_of_work.environment_id),
                Purpose("exact_life_query"),
                f"life.query.{status}",
                AuditReference("exact_life_query_intent", snapshot.intent_id),
                (
                    AuditResultStatus.COMPLETED
                    if status in {"succeeded", "empty"}
                    else AuditResultStatus.REJECTED
                    if status == "denied"
                    else AuditResultStatus.FAILED
                ),
                snapshot.trace_id,
                AuditSensitivity.PRIVATE,
                subject_id=SubjectId(snapshot.subject_id),
                request=AuditReference("exact_life_query_intent", snapshot.intent_id),
            )
        )
        return opportunity_id


__all__ = ("ExactLifeQuerySnapshot", "PostgreSQLExactLifeQueryRepository")
