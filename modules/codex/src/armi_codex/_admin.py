from typing import cast
from uuid import UUID

from armi_kernel.contracts import Digest
from armi_runtime_foundation import PostgreSQLAdminTransaction


class PostgreSQLCodexAdmin:
    __slots__ = ()

    def verification_for_effect(
        self, transaction: PostgreSQLAdminTransaction, *, effect_id: UUID
    ) -> tuple[UUID, str, Digest] | None:
        row = transaction.execute(
            "SELECT codex_verification_id,execution_status,"
            "CASE WHEN execution_status='verified' THEN final_tree_digest "
            "ELSE source_tree_digest END FROM armi.codex_verification_results "
            "WHERE effect_id=%s ORDER BY completed_at DESC LIMIT 1",
            (effect_id,),
        ).fetchone()
        if row is None or row[2] is None:
            return None
        return cast(UUID, row[0]), str(row[1]), Digest(str(row[2]))

    def artifact_reference_count(
        self, transaction: PostgreSQLAdminTransaction, *, artifact_id: UUID
    ) -> int:
        row = transaction.execute(
            "SELECT count(*) FROM armi.codex_verification_results WHERE "
            "event_transcript_artifact_id=%s OR final_result_artifact_id=%s OR "
            "patch_artifact_id=%s OR result_bundle_artifact_id=%s OR "
            "diagnostics_artifact_id=%s OR validation_report_artifact_id=%s",
            (artifact_id,) * 6,
        ).fetchone()
        return 0 if row is None else int(cast(int, row[0]))


__all__ = ("PostgreSQLCodexAdmin",)
