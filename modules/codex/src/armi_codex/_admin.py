from typing import cast
from uuid import UUID

from armi_artifact_store.api import ArtifactAdminPort
from armi_kernel.contracts import Digest
from armi_runtime_foundation import PostgreSQLAdminTransaction


class PostgreSQLCodexAdmin:
    __slots__ = ("_artifacts",)

    def __init__(self, artifacts: ArtifactAdminPort) -> None:
        self._artifacts = artifacts

    def verification_for_effect(
        self, transaction: PostgreSQLAdminTransaction, *, effect_id: UUID
    ) -> tuple[UUID, str, Digest] | None:
        row = transaction.execute(
            "SELECT codex_verification_id,execution_status,final_result_artifact_id "
            "FROM armi.codex_task_sources "
            "WHERE effect_id=%s",
            (effect_id,),
        ).fetchone()
        if row is None or row[2] is None:
            return None
        artifact = self._artifacts.snapshot(transaction, artifact_id=cast(UUID, row[2]))
        if artifact is None:
            return None
        return cast(UUID, row[0]), str(row[1]), Digest(artifact.content_digest)

    def artifact_reference_count(
        self, transaction: PostgreSQLAdminTransaction, *, artifact_id: UUID
    ) -> int:
        row = transaction.execute(
            "SELECT count(*) FROM armi.codex_task_sources WHERE "
            "final_result_artifact_id=%s",
            (artifact_id,),
        ).fetchone()
        return 0 if row is None else int(cast(int, row[0]))


__all__ = ("PostgreSQLCodexAdmin",)
