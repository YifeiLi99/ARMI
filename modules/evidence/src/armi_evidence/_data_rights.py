"""Data-rights participant owned by the evidence module."""

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
    DataRightsRelatedRef,
    DataRightsTargetRef,
    DataRightsTupleRecordStream,
)
from armi_kernel.application import ArtifactId
from armi_runtime_foundation import PostgreSQLTransaction

_OWNER = DataRightsOwnerIdentity("evidence")
_VERSION = DataRightsContributionVersion(1)
_SEGMENTS: tuple[tuple[str, LiteralString], ...] = (
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
        interaction_ids = tuple(
            item.ref for item in request.related_refs if item.kind == "interaction"
        )
        rows = await (
            await transaction.execute(
                """SELECT evidence_id, artifact_id,web_observation_request_id,
                          codex_task_source_id,codex_verification_id,
                          visual_observation_id
                   FROM armi.external_evidence
                   WHERE context_party_id = %s
                      OR interaction_id=ANY(%s::uuid[])
                   ORDER BY evidence_id""",
                (request.party_id, list(interaction_ids)),
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
                          count(*) FILTER (WHERE evidence_id=ANY(%s::uuid[]))
                   FROM armi.external_evidence GROUP BY artifact_id ORDER BY artifact_id""",
                (list(evidence_ids),),
            )
        ).fetchall()
        return DataRightsDiscoveryContribution(
            _OWNER,
            tuple(
                [DataRightsRelatedRef("evidence", ref) for ref in evidence_ids]
                + [DataRightsRelatedRef("experience", row[0]) for row in link_rows]
                + [
                    DataRightsRelatedRef("web-observation", row[2])
                    for row in rows
                    if row[2] is not None
                ]
                + [
                    DataRightsRelatedRef("codex-task", row[3])
                    for row in rows
                    if row[3] is not None
                ]
                + [
                    DataRightsRelatedRef("codex-verification", row[4])
                    for row in rows
                    if row[4] is not None
                ]
                + [
                    DataRightsRelatedRef("visual-observation", row[5])
                    for row in rows
                    if row[5] is not None
                ]
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
        evidence_ids = tuple(
            item.ref for item in request.related_refs if item.kind == "evidence"
        )
        if request.order_kind in {"stop_use", "delete_related"} and evidence_ids:
            await transaction.execute(
                """UPDATE armi.external_evidence
                   SET acceptance_status=CASE WHEN %s='delete_related'
                                              THEN 'redacted' ELSE acceptance_status END,
                       data_rights_order_id=%s,
                       data_rights_hidden_at=statement_timestamp()
                   WHERE evidence_id=ANY(%s::uuid[])
                     AND data_rights_hidden_at IS NULL""",
                (request.order_kind, request.order_id, list(evidence_ids)),
            )
        return DataRightsApplyContribution(
            _OWNER,
            tuple(
                target
                for target in request.targets
                if target.responsible_owner == _OWNER.value
            ),
        )

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
