"""Data-rights participant owned by the memory module."""

from __future__ import annotations

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
    DataRightsRelatedRef,
    DataRightsTargetRef,
    DataRightsTupleRecordStream,
)
from armi_runtime_foundation import PostgreSQLTransaction

_OWNER = DataRightsOwnerIdentity("memory")
_VERSION = DataRightsContributionVersion(1)
_SEGMENTS: tuple[tuple[str, str], ...] = (
    (
        "memory_relations",
        """SELECT convert_to(to_jsonb(source)::text || chr(10), 'UTF8')
           FROM armi.memory_relations AS source ORDER BY to_jsonb(source)::text""",
    ),
    (
        "subjective_memories",
        """SELECT convert_to(to_jsonb(source)::text || chr(10), 'UTF8')
           FROM armi.subjective_memories AS source ORDER BY to_jsonb(source)::text""",
    ),
    (
        "subjective_memory_revisions",
        """SELECT convert_to(to_jsonb(source)::text || chr(10), 'UTF8')
           FROM armi.subjective_memory_revisions AS source ORDER BY to_jsonb(source)::text""",
    ),
)


class PostgreSQLMemoryDataRightsParticipant:
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
        experience_ids = tuple(
            item.ref for item in request.related_refs if item.kind == "experience"
        )
        if not experience_ids:
            return DataRightsDiscoveryContribution(_OWNER)
        rows = await (
            await transaction.execute(
                """SELECT DISTINCT memory_id FROM armi.subjective_memory_revisions
                   WHERE source_experience_id = ANY(%s::uuid[]) ORDER BY memory_id""",
                (experience_ids,),
            )
        ).fetchall()
        return DataRightsDiscoveryContribution(
            _OWNER,
            tuple(DataRightsRelatedRef("memory", row[0]) for row in rows),
            tuple(DataRightsTargetRef("memory", row[0], "tombstone") for row in rows),
        )

    async def apply(
        self,
        transaction: PostgreSQLTransaction,
        request: DataRightsApplyRequest,
    ) -> DataRightsApplyContribution:
        del transaction, request
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


__all__ = ("PostgreSQLMemoryDataRightsParticipant",)
