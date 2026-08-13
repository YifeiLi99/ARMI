"""Owner reads used to validate candidates against frozen Context."""

from __future__ import annotations

from uuid import UUID

from armi_material.api import MaterialCandidateSourceRef
from armi_runtime_foundation import PostgreSQLTransaction


class PostgreSQLContextCandidateRead:
    __slots__ = ()

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


__all__ = ("PostgreSQLContextCandidateRead",)
