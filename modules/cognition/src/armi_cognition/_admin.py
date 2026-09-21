"""Fixed Admin operations owned by Cognition."""

import json
from datetime import datetime
from typing import cast
from uuid import UUID

from armi_runtime_foundation import PostgreSQLAdminTransaction

from .api import CognitionAdminAttempt, CognitionAdminEpisodeSnapshot


class PostgreSQLCognitionAdmin:
    __slots__ = ()

    def autonomous_commit_ids(
        self,
        transaction: PostgreSQLAdminTransaction,
        *,
        commit_ids: tuple[UUID, ...],
    ) -> frozenset[UUID]:
        if not commit_ids:
            return frozenset()
        rows = transaction.execute(
            """SELECT subject_commit_id FROM armi.cognitive_episodes
               WHERE subject_commit_id IN (SELECT value::uuid FROM jsonb_array_elements_text(%s::jsonb)) AND purpose='consider_autonomous_life'""",
            (json.dumps([str(value) for value in commit_ids]),),
        ).fetchall()
        return frozenset(cast(UUID, row[0]) for row in rows)

    def attempts(
        self, transaction: PostgreSQLAdminTransaction, *, episode_id: UUID
    ) -> tuple[CognitionAdminAttempt, ...]:
        rows = transaction.execute(
            "SELECT model_attempt_id,attempt_no,model_id,request_schema_version,"
            "candidate_schema_version,request_artifact_id,response_artifact_id,"
            "dispatch_status,result_status,error_code FROM armi.cognitive_attempts "
            "WHERE cognitive_episode_id=%s ORDER BY attempt_no",
            (episode_id,),
        ).fetchall()
        return tuple(
            CognitionAdminAttempt(
                cast(UUID, row[0]),
                int(cast(int, row[1])),
                str(row[2]),
                str(row[3]),
                str(row[4]),
                cast(UUID | None, row[5]),
                cast(UUID | None, row[6]),
                str(row[7]),
                cast(str | None, row[8]),
                cast(str | None, row[9]),
            )
            for row in rows
        )

    def content_busy(
        self, transaction: PostgreSQLAdminTransaction, *, subject_id: UUID
    ) -> bool:
        row = transaction.execute(
            "SELECT EXISTS(SELECT 1 FROM armi.cognitive_episodes WHERE subject_id=%s "
            "AND status IN ('preparing','prepared','calling_model','finalizing'))",
            (subject_id,),
        ).fetchone()
        return row is not None and bool(row[0])

    def artifact_episodes(
        self, transaction: PostgreSQLAdminTransaction, *, artifact_id: UUID
    ) -> tuple[UUID, ...]:
        rows = transaction.execute(
            "SELECT cognitive_episode_id FROM armi.cognitive_episodes WHERE context_manifest_artifact_id=%s OR compiled_context_artifact_id=%s OR change_set_artifact_id=%s ORDER BY cognitive_episode_id LIMIT 201",
            (artifact_id, artifact_id, artifact_id),
        ).fetchall()
        return tuple(cast(UUID, row[0]) for row in rows)

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
            "SELECT cognitive_episode_id,opportunity_id,status,trace_id,prepared_at,context_manifest_artifact_id,compiled_context_artifact_id, "
            "ARRAY(SELECT response_artifact_id FROM armi.cognitive_attempts a WHERE a.cognitive_episode_id=e.cognitive_episode_id AND response_artifact_id IS NOT NULL ORDER BY attempt_no) "
            "FROM armi.cognitive_episodes e WHERE cognitive_episode_id=%s",
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
                cast(UUID | None, row[5]),
                cast(UUID | None, row[6]),
                tuple(cast(list[UUID], row[7])),
            )
        )

    def episode_for_opportunity(
        self, transaction: PostgreSQLAdminTransaction, *, opportunity_id: UUID
    ) -> CognitionAdminEpisodeSnapshot | None:
        row = transaction.execute(
            "SELECT cognitive_episode_id FROM armi.cognitive_episodes WHERE opportunity_id=%s",
            (opportunity_id,),
        ).fetchone()
        return (
            None
            if row is None
            else self.episode(transaction, episode_id=cast(UUID, row[0]))
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
            "(SELECT count(*) FROM armi.cognitive_episodes WHERE change_set_artifact_id=%s)",
            (
                artifact_id,
                artifact_id,
                artifact_id,
                artifact_id,
                artifact_id,
            ),
        ).fetchone()
        return 0 if row is None else int(cast(int, row[0]))


__all__ = ("PostgreSQLCognitionAdmin",)
