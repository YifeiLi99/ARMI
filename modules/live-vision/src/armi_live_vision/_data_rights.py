"""Creator export contribution for private live-vision records."""

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

_OWNER = DataRightsOwnerIdentity("live-vision")
_VERSION = DataRightsContributionVersion(1)
_SEGMENTS: tuple[tuple[str, LiteralString], ...] = (
    (
        "live_vision_sessions",
        """SELECT convert_to(to_jsonb(source)::text || chr(10), 'UTF8')
           FROM armi.live_vision_sessions AS source ORDER BY to_jsonb(source)::text""",
    ),
    (
        "live_vision_observations",
        """SELECT convert_to(to_jsonb(source)::text || chr(10), 'UTF8')
           FROM armi.live_vision_observations AS source ORDER BY to_jsonb(source)::text""",
    ),
    (
        "live_vision_observation_frames",
        """SELECT convert_to(to_jsonb(source)::text || chr(10), 'UTF8')
           FROM armi.live_vision_observation_frames AS source ORDER BY to_jsonb(source)::text""",
    ),
)


class PostgreSQLLiveVisionDataRightsParticipant:
    owner_identity = _OWNER
    schema_version = _VERSION

    async def discover(
        self, transaction: PostgreSQLTransaction, request: DataRightsDiscoveryRequest
    ) -> DataRightsDiscoveryContribution:
        del transaction, request
        return DataRightsDiscoveryContribution(_OWNER)

    async def apply(
        self, transaction: PostgreSQLTransaction, request: DataRightsApplyRequest
    ) -> DataRightsApplyContribution:
        del transaction, request
        return DataRightsApplyContribution(_OWNER)

    async def export(
        self, transaction: PostgreSQLTransaction, scope: DataRightsExportScope
    ) -> tuple[DataRightsExportSegment, ...]:
        del scope
        result: list[DataRightsExportSegment] = []
        for table, statement in _SEGMENTS:
            rows = await (await transaction.execute(statement)).fetchall()
            result.append(
                DataRightsExportSegment(
                    _OWNER,
                    _VERSION,
                    table,
                    "application/x-ndjson",
                    DataRightsTupleRecordStream(
                        tuple(DataRightsCanonicalRecord(bytes(row[0])) for row in rows)
                    ),
                )
            )
        return tuple(result)


__all__ = ("PostgreSQLLiveVisionDataRightsParticipant",)
