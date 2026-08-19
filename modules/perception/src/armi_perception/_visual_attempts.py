"""Persistence owned by perception for live visual-model calls."""

from uuid import UUID

from armi_runtime_foundation import PostgreSQLRuntimeUnitOfWork


class PostgreSQLVisualRecognitionAttempts:
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
               (visual_attempt_id,observation_id,provider,model_id,request_artifact_id,status,dispatched_at)
               VALUES (%s,%s,%s,%s,%s,'dispatched',statement_timestamp())""",
            (attempt_id, observation_id, provider, model_id, request_artifact_id),
        )

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
