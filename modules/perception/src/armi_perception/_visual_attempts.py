"""Persistence owned by perception for live visual-model calls."""

from uuid import UUID

from armi_runtime_foundation import PostgreSQLRuntimeUnitOfWork


class PostgreSQLVisualRecognitionAttempts:
    async def prepared_attempt_for_observation(
        self,
        unit_of_work: PostgreSQLRuntimeUnitOfWork,
        *,
        observation_id: UUID,
    ) -> UUID | None:
        row = await (
            await unit_of_work.transaction.execute(
                "SELECT visual_attempt_id FROM armi.visual_recognition_attempts "
                "WHERE observation_id=%s AND status='prepared'",
                (observation_id,),
            )
        ).fetchone()
        return None if row is None else UUID(str(row[0]))

    async def settle_interrupted(
        self,
        unit_of_work: PostgreSQLRuntimeUnitOfWork,
        *,
        observation_ids: tuple[UUID, ...],
        error_code: str,
    ) -> None:
        if not observation_ids:
            return
        await unit_of_work.transaction.execute(
            """UPDATE armi.visual_recognition_attempts
               SET status=CASE status WHEN 'prepared' THEN 'failed'
                                      ELSE 'unknown' END,
                   error_code=%s,settled_at=statement_timestamp()
               WHERE observation_id=ANY(%s::uuid[])
                 AND status IN ('prepared','dispatched')""",
            (error_code, list(observation_ids)),
        )

    async def begin(
        self,
        unit_of_work: PostgreSQLRuntimeUnitOfWork,
        *,
        attempt_id: UUID,
        observation_id: UUID,
        request_artifact_id: UUID,
        provider: str,
        model_id: str,
    ) -> None:
        await unit_of_work.transaction.execute(
            """INSERT INTO armi.visual_recognition_attempts
               (visual_attempt_id,observation_id,provider,model_id,request_artifact_id,status)
               VALUES (%s,%s,%s,%s,%s,'prepared')""",
            (attempt_id, observation_id, provider, model_id, request_artifact_id),
        )

    async def mark_dispatched(
        self,
        unit_of_work: PostgreSQLRuntimeUnitOfWork,
        *,
        attempt_id: UUID,
    ) -> None:
        result = await unit_of_work.transaction.execute(
            """UPDATE armi.visual_recognition_attempts
               SET status='dispatched',dispatched_at=statement_timestamp()
               WHERE visual_attempt_id=%s AND status='prepared'""",
            (attempt_id,),
        )
        if result.rowcount != 1:
            raise RuntimeError("VISION-ATTEMPT-STALE")

    async def settle(
        self,
        unit_of_work: PostgreSQLRuntimeUnitOfWork,
        *,
        attempt_id: UUID,
        status: str,
        response_artifact_id: UUID | None,
        provider_request_id: str | None,
        input_tokens: int | None,
        output_tokens: int | None,
        error_code: str | None,
    ) -> None:
        await unit_of_work.transaction.execute(
            """UPDATE armi.visual_recognition_attempts SET status=%s,response_artifact_id=%s,
               provider_request_id=%s,input_tokens=%s,output_tokens=%s,error_code=%s,
               settled_at=statement_timestamp() WHERE visual_attempt_id=%s""",
            (
                status,
                response_artifact_id,
                provider_request_id,
                input_tokens,
                output_tokens,
                error_code,
                attempt_id,
            ),
        )


__all__ = ("PostgreSQLVisualRecognitionAttempts",)
