"""PostgreSQL custody for exact-life-query cognition intents."""

from __future__ import annotations

from uuid import UUID

from armi_kernel.application import LifeRecordQueryViolation
from armi_kernel.contracts import Digest, TraceId
from armi_runtime_foundation import PostgreSQLTransaction

from .api import CognitionExactLifeQuerySnapshot


class PostgreSQLCognitionExactLifeQuery:
    async def snapshot(
        self,
        transaction: PostgreSQLTransaction,
        *,
        intent_id: UUID,
        subject_id: UUID,
    ) -> CognitionExactLifeQuerySnapshot:
        row = await (
            await transaction.execute(
                """
                SELECT exact_life_query_intent_id, subject_id,
                       source_opportunity_id, scene_id, context_party_id,
                       record_kind, query_text, result_limit,
                       query_digest, trace_id
                FROM armi.exact_life_query_intents
                WHERE exact_life_query_intent_id = %s
                  AND subject_id = %s
                  AND status = 'pending'
                FOR UPDATE
                """,
                (intent_id, subject_id),
            )
        ).fetchone()
        if row is None:
            raise LifeRecordQueryViolation("LIFE-QUERY-WORK-STALE")
        return CognitionExactLifeQuerySnapshot(
            intent_id=row[0],
            subject_id=row[1],
            source_opportunity_id=row[2],
            scene_id=row[3],
            creator_party_id=row[4],
            record_kind=str(row[5]),
            query_text=None if row[6] is None else str(row[6]),
            limit=int(row[7]),
            query_digest=Digest(str(row[8])),
            trace_id=TraceId(str(row[9])),
        )

    async def settle(
        self,
        transaction: PostgreSQLTransaction,
        *,
        intent_id: UUID,
        status: str,
        result_artifact_id: UUID,
        result_count: int,
        failure_code: str | None,
        result_opportunity_id: UUID,
    ) -> None:
        row = await (
            await transaction.execute(
                """
                UPDATE armi.exact_life_query_intents
                SET status = %s, result_artifact_id = %s,
                    result_count = %s, failure_code = %s,
                    result_opportunity_id = %s,
                    completed_at = statement_timestamp()
                WHERE exact_life_query_intent_id = %s AND status = 'pending'
                RETURNING exact_life_query_intent_id
                """,
                (
                    status,
                    result_artifact_id,
                    result_count,
                    failure_code,
                    result_opportunity_id,
                    intent_id,
                ),
            )
        ).fetchone()
        if row is None:
            raise LifeRecordQueryViolation("LIFE-QUERY-WORK-STALE")

    async def fail(
        self,
        transaction: PostgreSQLTransaction,
        *,
        intent_id: UUID,
        code: str,
    ) -> None:
        row = await (
            await transaction.execute(
                """
                UPDATE armi.exact_life_query_intents
                SET status = 'failed', result_count = 0,
                    failure_code = %s, completed_at = statement_timestamp()
                WHERE exact_life_query_intent_id = %s AND status = 'pending'
                RETURNING exact_life_query_intent_id
                """,
                (code, intent_id),
            )
        ).fetchone()
        if row is None:
            raise LifeRecordQueryViolation("LIFE-QUERY-WORK-STALE")


__all__ = ("PostgreSQLCognitionExactLifeQuery",)
