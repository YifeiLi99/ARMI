"""Data-rights participant owned by the evidence module."""

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
    DataRightsRelatedRef,
    DataRightsTargetRef,
    DataRightsTupleRecordStream,
)
from armi_kernel.application import ArtifactId
from armi_runtime_foundation import PostgreSQLTransaction

_OWNER = DataRightsOwnerIdentity("evidence")
_VERSION = DataRightsContributionVersion(1)
_SEGMENTS: tuple[tuple[str, str], ...] = (
    (
        "experience_evidence_links",
        """SELECT convert_to(to_jsonb(source)::text || chr(10), 'UTF8')
           FROM armi.experience_evidence_links AS source ORDER BY to_jsonb(source)::text""",
    ),
    (
        "external_evidence",
        """SELECT convert_to(to_jsonb(source)::text || chr(10), 'UTF8')
           FROM armi.external_evidence AS source ORDER BY to_jsonb(source)::text""",
    ),
)


class PostgreSQLEvidenceDataRightsParticipant:
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
                """SELECT evidence_id, artifact_id FROM armi.external_evidence
                   WHERE context_party_id = %s ORDER BY evidence_id""",
                (request.party_id,),
            )
        ).fetchall()
        evidence_ids = tuple(row[0] for row in rows)
        link_rows = await (
            await transaction.execute(
                """SELECT DISTINCT link.experience_id
                   FROM armi.experience_evidence_links AS link
                   JOIN armi.external_evidence AS evidence
                     ON evidence.evidence_id = link.evidence_id
                   WHERE evidence.context_party_id = %s ORDER BY link.experience_id""",
                (request.party_id,),
            )
        ).fetchall()
        usage_rows = await (
            await transaction.execute(
                """SELECT artifact_id, count(*),
                          count(*) FILTER (WHERE context_party_id = %s)
                   FROM armi.external_evidence GROUP BY artifact_id ORDER BY artifact_id""",
                (request.party_id,),
            )
        ).fetchall()
        return DataRightsDiscoveryContribution(
            _OWNER,
            tuple(
                [DataRightsRelatedRef("evidence", ref) for ref in evidence_ids]
                + [DataRightsRelatedRef("experience", row[0]) for row in link_rows]
            ),
            tuple(
                DataRightsTargetRef("evidence", ref, "tombstone")
                for ref in evidence_ids
            ),
            tuple(
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


__all__ = ("PostgreSQLEvidenceDataRightsParticipant",)
