"""Data-rights participant owned by the expression module."""

from __future__ import annotations

from typing import LiteralString

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
    DataRightsTupleRecordStream,
)
from armi_kernel.application import ArtifactId
from armi_runtime_foundation import PostgreSQLTransaction

_OWNER = DataRightsOwnerIdentity("expression")
_VERSION = DataRightsContributionVersion(1)
_SEGMENTS: tuple[tuple[str, LiteralString], ...] = (
    (
        "action_intent_revisions",
        """SELECT convert_to(to_jsonb(source)::text || chr(10), 'UTF8')
           FROM armi.action_intent_revisions AS source ORDER BY to_jsonb(source)::text""",
    ),
    (
        "action_intents",
        """SELECT convert_to(to_jsonb(source)::text || chr(10), 'UTF8')
           FROM armi.action_intents AS source ORDER BY to_jsonb(source)::text""",
    ),
    (
        "dialogue_decisions",
        """SELECT convert_to(to_jsonb(source)::text || chr(10), 'UTF8')
           FROM armi.dialogue_decisions AS source ORDER BY to_jsonb(source)::text""",
    ),
)


class PostgreSQLExpressionDataRightsParticipant:
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
                """SELECT revision.response_artifact_id, count(*),
                          count(*) FILTER (WHERE intent.context_party_id = %s)
                   FROM armi.action_intent_revisions AS revision
                   JOIN armi.action_intents AS intent
                     ON intent.action_intent_id = revision.action_intent_id
                   WHERE revision.response_artifact_id IS NOT NULL
                   GROUP BY revision.response_artifact_id
                   ORDER BY revision.response_artifact_id""",
                (request.party_id,),
            )
        ).fetchall()
        return DataRightsDiscoveryContribution(
            _OWNER,
            artifact_usages=tuple(
                DataRightsArtifactUsage(ArtifactId(row[0]), int(row[1]), int(row[2]))
                for row in rows
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


__all__ = ("PostgreSQLExpressionDataRightsParticipant",)
