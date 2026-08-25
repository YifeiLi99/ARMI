"""Data-rights participant owned by the perception module."""

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

_OWNER = DataRightsOwnerIdentity("perception")
_VERSION = DataRightsContributionVersion(1)
_SEGMENTS: tuple[tuple[str, LiteralString], ...] = (
    (
        "external_content_recognition_attempts",
        """SELECT convert_to(to_jsonb(source)::text || chr(10), 'UTF8')
           FROM armi.external_content_recognition_attempts AS source ORDER BY to_jsonb(source)::text""",
    ),
    (
        "visual_recognition_attempts",
        """SELECT convert_to(to_jsonb(source)::text || chr(10), 'UTF8')
           FROM armi.visual_recognition_attempts AS source ORDER BY to_jsonb(source)::text""",
    ),
)


class PostgreSQLPerceptionDataRightsParticipant:
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
        part_ids = tuple(
            item.ref
            for item in request.related_refs
            if item.kind == "external-message-part"
        )
        attempt_rows = await (
            await transaction.execute(
                """SELECT recognition_attempt_id,external_message_part_id
                   FROM armi.external_content_recognition_attempts
                   WHERE source_party_id=%s OR external_message_part_id=ANY(%s::uuid[])
                   ORDER BY recognition_attempt_id""",
                (request.party_id, list(part_ids)),
            )
        ).fetchall()
        if not attempt_rows:
            return DataRightsDiscoveryContribution(_OWNER)
        target_part_ids = tuple({row[1] for row in attempt_rows})
        rows = await (
            await transaction.execute(
                """WITH refs AS (
                     SELECT request_artifact_id AS artifact_id, external_message_part_id
                     FROM armi.external_content_recognition_attempts
                     UNION ALL
                     SELECT response_artifact_id, external_message_part_id
                     FROM armi.external_content_recognition_attempts
                     WHERE response_artifact_id IS NOT NULL
                   )
                   SELECT artifact_id, count(*),
                          count(*) FILTER (WHERE external_message_part_id = ANY(%s::uuid[]))
                   FROM refs GROUP BY artifact_id ORDER BY artifact_id""",
                (list(target_part_ids),),
            )
        ).fetchall()
        return DataRightsDiscoveryContribution(
            _OWNER,
            related_refs=tuple(
                DataRightsRelatedRef("media-recognition", row[0])
                for row in attempt_rows
            ),
            targets=tuple(
                DataRightsTargetRef("media_recognition", row[0], "redact")
                for row in attempt_rows
            ),
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
        if request.order_kind in {"stop_use", "delete_related"}:
            await transaction.execute(
                """UPDATE armi.external_content_recognition_attempts
                   SET dispatch_status='settled',result_status='unknown',
                       error_code='DATA-RIGHTS-RECOGNITION-HIDDEN',
                       settled_at=statement_timestamp()
                   WHERE source_party_id=%s AND dispatch_status='dispatched'""",
                (request.party_id,),
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


__all__ = ("PostgreSQLPerceptionDataRightsParticipant",)
