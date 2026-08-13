from typing import cast
from uuid import UUID

from armi_runtime_foundation import PostgreSQLAdminTransaction


class PostgreSQLWebObservationAdmin:
    __slots__ = ()

    def opportunity_consumed(
        self, transaction: PostgreSQLAdminTransaction, *, opportunity_id: UUID
    ) -> bool:
        row = transaction.execute(
            "SELECT EXISTS(SELECT 1 FROM armi.web_research_intents WHERE source_opportunity_id=%s)",
            (opportunity_id,),
        ).fetchone()
        return row is not None and bool(row[0])

    def artifact_reference_count(
        self, transaction: PostgreSQLAdminTransaction, *, artifact_id: UUID
    ) -> int:
        row = transaction.execute(
            "SELECT (SELECT count(*) FROM armi.web_observation_requests WHERE request_artifact_id=%s OR result_artifact_id=%s)+"
            "(SELECT count(*) FROM armi.observation_attempts WHERE result_artifact_id=%s)+"
            "(SELECT count(*) FROM armi.web_research_intents WHERE query_artifact_id=%s)+"
            "(SELECT count(*) FROM armi.web_evidence_sources WHERE source_artifact_id=%s)",
            (artifact_id, artifact_id, artifact_id, artifact_id, artifact_id),
        ).fetchone()
        return 0 if row is None else int(cast(int, row[0]))


__all__ = ("PostgreSQLWebObservationAdmin",)
