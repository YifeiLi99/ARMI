from typing import cast
from uuid import UUID

from armi_runtime_foundation import PostgreSQLAdminTransaction


class PostgreSQLPerceptionAdmin:
    __slots__ = ()

    def artifact_reference_count(
        self, transaction: PostgreSQLAdminTransaction, *, artifact_id: UUID
    ) -> int:
        row = transaction.execute(
            "SELECT count(*) FROM armi.external_content_recognition_attempts WHERE request_artifact_id=%s OR response_artifact_id=%s",
            (artifact_id, artifact_id),
        ).fetchone()
        return 0 if row is None else int(cast(int, row[0]))


__all__ = ("PostgreSQLPerceptionAdmin",)
