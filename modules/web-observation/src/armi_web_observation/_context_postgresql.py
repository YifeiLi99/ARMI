"""Web-owned trace reads for cognition Context selection."""

from __future__ import annotations

from uuid import UUID

from armi_kernel.contracts import TraceId
from armi_runtime_foundation import PostgreSQLTransaction

from .api import WebObservationViolation


class PostgreSQLWebContextRead:
    async def request_trace(
        self,
        transaction: PostgreSQLTransaction,
        *,
        request_id: UUID,
    ) -> TraceId:
        row = await (
            await transaction.execute(
                """SELECT intent.trace_id
                   FROM armi.web_observation_requests AS request
                   JOIN armi.web_research_intents AS intent
                     ON intent.web_research_intent_id=request.web_research_intent_id
                   WHERE request.web_observation_request_id=%s""",
                (request_id,),
            )
        ).fetchone()
        if row is None:
            raise WebObservationViolation("WEB-REQUEST-STATE")
        return TraceId(str(row[0]))


__all__ = ("PostgreSQLWebContextRead",)
