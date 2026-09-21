"""Owner-only reads for Codex task and result facts."""

from __future__ import annotations

from uuid import UUID

from armi_kernel.application import ArtifactId
from armi_kernel.contracts import Digest, TraceId
from armi_runtime_foundation import PostgreSQLTransaction

from ._delegation_contract import CodexDelegationViolation
from .api import CodexExecutionSnapshot, CodexTaskSourceSnapshot


class PostgreSQLCodexReadOwner:
    __slots__ = ()

    async def task_source(
        self,
        transaction: PostgreSQLTransaction,
        *,
        task_source_id: UUID,
    ) -> CodexTaskSourceSnapshot:
        row = await (
            await transaction.execute(
                """
                SELECT subject_id, task_manifest_artifact_id, task_manifest_digest,
                       deadline_seconds, trace_id
                FROM armi.codex_task_sources
                WHERE codex_task_source_id=%s
                """,
                (task_source_id,),
            )
        ).fetchone()
        if row is None:
            raise CodexDelegationViolation("CODEX-TASK-SOURCE")
        return CodexTaskSourceSnapshot(
            task_source_id,
            row[0],
            row[1],
            Digest(str(row[2])),
            int(row[3]),
            TraceId(str(row[4])),
        )

    async def find_by_manifest_digest(
        self,
        transaction: PostgreSQLTransaction,
        *,
        manifest_digest: Digest,
    ) -> CodexTaskSourceSnapshot | None:
        row = await (
            await transaction.execute(
                "SELECT codex_task_source_id FROM armi.codex_task_sources "
                "WHERE task_manifest_digest=%s",
                (manifest_digest.value,),
            )
        ).fetchone()
        if row is None:
            return None
        return await self.task_source(transaction, task_source_id=row[0])

    async def execution_for_effect(
        self,
        transaction: PostgreSQLTransaction,
        *,
        effect_id: UUID,
        task_source_id: UUID,
    ) -> CodexExecutionSnapshot | None:
        row = await (
            await transaction.execute(
                """
                SELECT source.codex_task_source_id,
                       verification.codex_verification_id,
                       verification.execution_status,
                       verification.opportunity_id
                FROM armi.codex_task_sources AS source
                LEFT JOIN armi.codex_verification_results AS verification
                  ON verification.effect_id=%s
                WHERE source.codex_task_source_id=%s
                ORDER BY verification.completed_at DESC NULLS LAST
                LIMIT 1
                """,
                (effect_id, task_source_id),
            )
        ).fetchone()
        if row is None:
            return None
        return CodexExecutionSnapshot(
            effect_id,
            row[0],
            row[1],
            None if row[2] is None else str(row[2]),
            None,
            None,
            row[3],
        )

    async def verification_effect_id(
        self,
        transaction: PostgreSQLTransaction,
        *,
        verification_id: UUID,
    ) -> UUID:
        row = await (
            await transaction.execute(
                "SELECT effect_id FROM armi.codex_verification_results "
                "WHERE codex_verification_id=%s",
                (verification_id,),
            )
        ).fetchone()
        if row is None:
            raise CodexDelegationViolation("CODEX-VERIFICATION")
        return row[0]

    async def artifact_ref(
        self,
        transaction: PostgreSQLTransaction,
        *,
        effect_id: UUID,
        kind: str,
    ) -> ArtifactId | None:
        if kind == "final_result":
            row = await (
                await transaction.execute(
                    "SELECT final_result_artifact_id FROM armi.codex_verification_results WHERE effect_id=%s",
                    (effect_id,),
                )
            ).fetchone()
        else:
            raise CodexDelegationViolation("CODEX-ARTIFACT-KIND")
        return None if row is None or row[0] is None else ArtifactId(row[0])


__all__ = ("PostgreSQLCodexReadOwner",)
