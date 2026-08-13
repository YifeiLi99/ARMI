"""Data-rights participant owned by the effect module."""

from __future__ import annotations

from armi_data_rights.api import (
    DataRightsApplyContribution,
    DataRightsApplyRequest,
    DataRightsArtifactUsage,
    DataRightsCanonicalRecord,
    DataRightsContributionVersion,
    DataRightsDiscoveryContribution,
    DataRightsDiscoveryRequest,
    DataRightsExportScope,
    DataRightsExportSegment,
    DataRightsOwnerIdentity,
    DataRightsTargetRef,
    DataRightsTupleRecordStream,
)
from armi_kernel.application import ArtifactId
from armi_runtime_foundation import PostgreSQLTransaction

_OWNER = DataRightsOwnerIdentity("effect")
_VERSION = DataRightsContributionVersion(1)
_SEGMENTS: tuple[tuple[str, str], ...] = (
    (
        "effect_attempts",
        """SELECT convert_to(to_jsonb(source)::text || chr(10), 'UTF8')
           FROM armi.effect_attempts AS source ORDER BY to_jsonb(source)::text""",
    ),
    (
        "effect_observations",
        """SELECT convert_to(to_jsonb(source)::text || chr(10), 'UTF8')
           FROM armi.effect_observations AS source ORDER BY to_jsonb(source)::text""",
    ),
    (
        "effect_outbox_items",
        """SELECT convert_to(to_jsonb(source)::text || chr(10), 'UTF8')
           FROM armi.effect_outbox_items AS source ORDER BY to_jsonb(source)::text""",
    ),
    (
        "effects",
        """SELECT convert_to(to_jsonb(source)::text || chr(10), 'UTF8')
           FROM armi.effects AS source ORDER BY to_jsonb(source)::text""",
    ),
    (
        "local_inbox_deliveries",
        """SELECT convert_to(to_jsonb(source)::text || chr(10), 'UTF8')
           FROM armi.local_inbox_deliveries AS source ORDER BY to_jsonb(source)::text""",
    ),
)


class PostgreSQLEffectDataRightsParticipant:
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
        effect_rows = await (
            await transaction.execute(
                """SELECT effect_id FROM armi.effects
                   WHERE context_party_id = %s OR destination_party_id = %s
                   ORDER BY effect_id""",
                (request.party_id, request.party_id),
            )
        ).fetchall()
        usage_rows = await (
            await transaction.execute(
                """WITH refs AS (
                     SELECT payload_artifact_id AS artifact_id, context_party_id,
                            destination_party_id FROM armi.effects
                     UNION ALL SELECT payload_artifact_id, destination_party_id,
                            destination_party_id FROM armi.local_inbox_deliveries
                   ) SELECT artifact_id, count(*), count(*) FILTER (
                       WHERE context_party_id = %s OR destination_party_id = %s)
                     FROM refs GROUP BY artifact_id ORDER BY artifact_id""",
                (request.party_id, request.party_id),
            )
        ).fetchall()
        return DataRightsDiscoveryContribution(
            _OWNER,
            targets=tuple(
                DataRightsTargetRef("effect", row[0], "retain", "objective_history")
                for row in effect_rows
            ),
            artifact_usages=tuple(
                DataRightsArtifactUsage(ArtifactId(row[0]), int(row[1]), int(row[2]))
                for row in usage_rows
            ),
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


__all__ = ("PostgreSQLEffectDataRightsParticipant",)
