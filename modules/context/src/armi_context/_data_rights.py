"""Data-rights participant owned by the context module."""

from __future__ import annotations

from typing import LiteralString

from armi_data_rights.api import (
    DataRightsApplyContribution,
    DataRightsApplyRequest,
    DataRightsCanonicalRecord,
    DataRightsContributionVersion,
    DataRightsDiscoveryContribution,
    DataRightsDiscoveryRequest,
    DataRightsExportScope,
    DataRightsExportSegment,
    DataRightsOwnerIdentity,
    DataRightsTupleRecordStream,
)
from armi_runtime_foundation import PostgreSQLTransaction

_OWNER = DataRightsOwnerIdentity("context")
_VERSION = DataRightsContributionVersion(1)
_SEGMENTS: tuple[tuple[str, LiteralString], ...] = (
    (
        "cognitive_context_items",
        """SELECT convert_to(to_jsonb(source)::text || chr(10), 'UTF8')
           FROM armi.cognitive_context_items AS source ORDER BY to_jsonb(source)::text""",
    ),
    (
        "context_embedding_attempts",
        """SELECT convert_to(to_jsonb(source)::text || chr(10), 'UTF8')
           FROM armi.context_embedding_attempts AS source ORDER BY to_jsonb(source)::text""",
    ),
    (
        "context_embedding_projections",
        """SELECT convert_to(to_jsonb(source)::text || chr(10), 'UTF8')
           FROM armi.context_embedding_projections AS source ORDER BY to_jsonb(source)::text""",
    ),
)


class PostgreSQLContextDataRightsParticipant:
    @property
    def owner_identity(self) -> DataRightsOwnerIdentity:
        return _OWNER

    @property
    def schema_version(self) -> DataRightsContributionVersion:
        return _VERSION

    async def discover(
        self,
        transaction: PostgreSQLTransaction,
        request: DataRightsDiscoveryRequest,
    ) -> DataRightsDiscoveryContribution:
        del transaction, request
        return DataRightsDiscoveryContribution(_OWNER)

    async def apply(
        self,
        transaction: PostgreSQLTransaction,
        request: DataRightsApplyRequest,
    ) -> DataRightsApplyContribution:
        memory_ids = tuple(
            item.ref for item in request.related_refs if item.kind == "memory"
        )
        if memory_ids:
            await transaction.execute(
                """DELETE FROM armi.context_embedding_projections
                   WHERE source_kind = 'subjective_memory'
                     AND source_ref = ANY(%s::uuid[])""",
                (memory_ids,),
            )
        return DataRightsApplyContribution(_OWNER)

    async def export(
        self,
        transaction: PostgreSQLTransaction,
        scope: DataRightsExportScope,
    ) -> tuple[DataRightsExportSegment, ...]:
        del scope
        segments: list[DataRightsExportSegment] = []
        for segment_name, statement in _SEGMENTS:
            rows = await (await transaction.execute(statement)).fetchall()
            records = tuple(DataRightsCanonicalRecord(bytes(row[0])) for row in rows)
            segments.append(
                DataRightsExportSegment(
                    _OWNER,
                    _VERSION,
                    segment_name,
                    "application/x-ndjson",
                    DataRightsTupleRecordStream(records),
                )
            )
        return tuple(segments)


__all__ = ("PostgreSQLContextDataRightsParticipant",)
