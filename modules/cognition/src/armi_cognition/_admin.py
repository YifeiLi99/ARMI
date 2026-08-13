"""Fixed Admin operations owned by Cognition."""

from datetime import datetime
from typing import cast
from uuid import UUID

from armi_runtime_foundation import PostgreSQLAdminTransaction

from .api import CognitionAdminEpisodeSnapshot


class PostgreSQLCognitionAdmin:
    __slots__ = ()

    def opportunity_consumed(
        self, transaction: PostgreSQLAdminTransaction, *, opportunity_id: UUID
    ) -> bool:
        row = transaction.execute(
            "SELECT EXISTS(SELECT 1 FROM armi.cognitive_episodes WHERE opportunity_id=%s)",
            (opportunity_id,),
        ).fetchone()
        return row is not None and bool(row[0])

    def episode(
        self, transaction: PostgreSQLAdminTransaction, *, episode_id: UUID
    ) -> CognitionAdminEpisodeSnapshot | None:
        row = transaction.execute(
            "SELECT cognitive_episode_id,opportunity_id,status,trace_id,prepared_at FROM armi.cognitive_episodes WHERE cognitive_episode_id=%s",
            (episode_id,),
        ).fetchone()
        return (
            None
            if row is None
            else CognitionAdminEpisodeSnapshot(
                cast(UUID, row[0]),
                cast(UUID, row[1]),
                str(row[2]),
                str(row[3]),
                cast(datetime | None, row[4]),
            )
        )

    def inspect_ids(
        self, transaction: PostgreSQLAdminTransaction, *, object_ids: tuple[UUID, ...]
    ) -> tuple[UUID, ...]:
        rows = transaction.execute(
            "SELECT cognitive_episode_id FROM armi.cognitive_episodes WHERE cognitive_episode_id=ANY(%s::uuid[]) ORDER BY cognitive_episode_id",
            (object_ids,),
        ).fetchall()
        return tuple(cast(UUID, row[0]) for row in rows)

    def artifact_reference_count(
        self, transaction: PostgreSQLAdminTransaction, *, artifact_id: UUID
    ) -> int:
        row = transaction.execute(
            "SELECT (SELECT count(*) FROM armi.cognitive_episodes WHERE context_manifest_artifact_id=%s OR compiled_context_artifact_id=%s)+"
            "(SELECT count(*) FROM armi.cognitive_attempts WHERE request_artifact_id=%s OR response_artifact_id=%s)+"
            "(SELECT count(*) FROM armi.cognitive_candidate_validations WHERE change_set_artifact_id=%s)",
            (artifact_id, artifact_id, artifact_id, artifact_id, artifact_id),
        ).fetchone()
        return 0 if row is None else int(cast(int, row[0]))


__all__ = ("PostgreSQLCognitionAdmin",)
