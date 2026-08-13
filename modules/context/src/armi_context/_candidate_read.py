"""Owner reads used to validate candidates against frozen Context."""

from __future__ import annotations

from uuid import UUID

from armi_kernel.application import CandidateBasis
from armi_material.api import MaterialCandidateSourceRef
from armi_memory.api import MemoryCandidateSourceRef
from armi_runtime_foundation import PostgreSQLTransaction

from .api import (
    ContextBudgetExclusion,
    ContextCandidateBasisSnapshot,
    ContextModelReference,
)


class PostgreSQLContextCandidateRead:
    __slots__ = ()

    async def model_references(
        self, transaction: PostgreSQLTransaction, *, episode_id: UUID
    ) -> tuple[tuple[ContextModelReference, ...], tuple[ContextBudgetExclusion, ...]]:
        rows = await (
            await transaction.execute(
                """SELECT ordinal, section, item_kind, disposition, reason_code
                   FROM armi.cognitive_context_items WHERE cognitive_episode_id=%s
                   ORDER BY ordinal""",
                (episode_id,),
            )
        ).fetchall()
        included = tuple(
            ContextModelReference(int(row[0]), str(row[1]), str(row[2]))
            for row in rows
            if str(row[3]) == "included"
        )
        excluded = tuple(
            ContextBudgetExclusion(int(row[0]), str(row[1]), str(row[2]), str(row[4]))
            for row in rows
            if str(row[3]) == "excluded_budget" and row[4] is not None
        )
        return included, excluded

    async def candidate_bases(
        self, transaction: PostgreSQLTransaction, *, episode_id: UUID
    ) -> tuple[ContextCandidateBasisSnapshot, ...]:
        rows = await (
            await transaction.execute(
                """SELECT context_item_id, ordinal, section, item_kind, source_ref,
                          source_version, trust_class, privacy_scope
                   FROM armi.cognitive_context_items
                   WHERE cognitive_episode_id=%s AND disposition='included'
                   ORDER BY ordinal""",
                (episode_id,),
            )
        ).fetchall()
        result: list[ContextCandidateBasisSnapshot] = []
        for row in rows:
            complete = row[4] is not None and row[5] is not None
            result.append(
                ContextCandidateBasisSnapshot(
                    row[0],
                    CandidateBasis(
                        int(row[1]),
                        str(row[2]),
                        str(row[3]),
                        row[4] if complete else None,
                        int(row[5]) if complete else None,
                        str(row[6]),
                        str(row[7]),
                    ),
                )
            )
        return tuple(result)

    async def material_sources(
        self,
        transaction: PostgreSQLTransaction,
        *,
        episode_id: UUID,
    ) -> tuple[MaterialCandidateSourceRef, ...]:
        rows = await (
            await transaction.execute(
                """SELECT source_ref,source_version
                   FROM armi.cognitive_context_items
                   WHERE cognitive_episode_id=%s AND disposition='included'
                     AND section='material' AND item_kind='current_material'
                     AND source_kind='life_material'
                   ORDER BY ordinal""",
                (episode_id,),
            )
        ).fetchall()
        return tuple(MaterialCandidateSourceRef(row[0], int(row[1])) for row in rows)

    async def memory_sources(
        self,
        transaction: PostgreSQLTransaction,
        *,
        episode_id: UUID,
    ) -> tuple[MemoryCandidateSourceRef, ...]:
        rows = await (
            await transaction.execute(
                """SELECT source_ref,source_version
                   FROM armi.cognitive_context_items
                   WHERE cognitive_episode_id=%s AND disposition='included'
                     AND section='memory' AND item_kind='current_memory'
                     AND source_kind='subjective_memory'
                   ORDER BY ordinal""",
                (episode_id,),
            )
        ).fetchall()
        return tuple(MemoryCandidateSourceRef(row[0], int(row[1])) for row in rows)


__all__ = ("PostgreSQLContextCandidateRead",)
