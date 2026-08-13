"""Data-rights participant owned by the relationship module."""

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
    DataRightsRelatedRef,
    DataRightsTargetRef,
    DataRightsTupleRecordStream,
)
from armi_runtime_foundation import PostgreSQLTransaction

_OWNER = DataRightsOwnerIdentity("relationship")
_VERSION = DataRightsContributionVersion(1)
_SEGMENTS: tuple[tuple[str, LiteralString], ...] = (
    (
        "relationship_experience_links",
        """SELECT convert_to(to_jsonb(source)::text || chr(10), 'UTF8')
           FROM armi.relationship_experience_links AS source ORDER BY to_jsonb(source)::text""",
    ),
    (
        "relationship_revisions",
        """SELECT convert_to(to_jsonb(source)::text || chr(10), 'UTF8')
           FROM armi.relationship_revisions AS source ORDER BY to_jsonb(source)::text""",
    ),
    (
        "relationships",
        """SELECT convert_to(to_jsonb(source)::text || chr(10), 'UTF8')
           FROM armi.relationships AS source ORDER BY to_jsonb(source)::text""",
    ),
)


class PostgreSQLRelationshipDataRightsParticipant:
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
        rows = await (
            await transaction.execute(
                """SELECT relationship_id FROM armi.relationships
                   WHERE other_party_id = %s AND tombstoned_at IS NULL
                   ORDER BY relationship_id""",
                (request.party_id,),
            )
        ).fetchall()
        return DataRightsDiscoveryContribution(
            _OWNER,
            tuple(DataRightsRelatedRef("relationship", row[0]) for row in rows),
            tuple(
                DataRightsTargetRef("relationship", row[0], "tombstone") for row in rows
            ),
        )

    async def apply(
        self,
        transaction: PostgreSQLTransaction,
        request: DataRightsApplyRequest,
    ) -> DataRightsApplyContribution:
        targets = tuple(
            item
            for item in request.targets
            if item.kind == "relationship" and item.required_action == "tombstone"
        )
        for target in targets:
            await transaction.execute(
                """UPDATE armi.relationships
                   SET tombstoned_at = statement_timestamp(), tombstone_order_id = %s
                   WHERE relationship_id = %s AND tombstoned_at IS NULL""",
                (request.order_id, target.ref),
            )
        return DataRightsApplyContribution(_OWNER, targets)

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


__all__ = ("PostgreSQLRelationshipDataRightsParticipant",)
