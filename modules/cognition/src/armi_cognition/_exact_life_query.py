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
                       opportunity_id, scene_id, life_query_creator_party_id,
                       life_query_record_kind, life_query_text, life_query_result_limit,
                       life_query_digest, trace_id
                FROM armi.cognitive_episodes
                WHERE exact_life_query_intent_id = %s
                  AND subject_id = %s
                  AND life_query_status = 'pending'
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
                UPDATE armi.cognitive_episodes
                SET life_query_status = %s, life_query_result_artifact_id = %s,
                    life_query_result_count = %s, life_query_failure_code = %s,
                    life_query_result_opportunity_id = %s,
                    life_query_completed_at = statement_timestamp()
                WHERE exact_life_query_intent_id = %s AND life_query_status = 'pending'
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
                UPDATE armi.cognitive_episodes
                SET life_query_status = 'failed', life_query_result_count = 0,
                    life_query_failure_code = %s, life_query_completed_at = statement_timestamp()
                WHERE exact_life_query_intent_id = %s AND life_query_status = 'pending'
                RETURNING exact_life_query_intent_id
                """,
                (code, intent_id),
            )
        ).fetchone()
        if row is None:
            raise LifeRecordQueryViolation("LIFE-QUERY-WORK-STALE")


__all__ = ("PostgreSQLCognitionExactLifeQuery",)
