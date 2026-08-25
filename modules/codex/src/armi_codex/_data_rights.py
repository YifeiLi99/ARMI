"""Data-rights participant owned by the codex module."""

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

_OWNER = DataRightsOwnerIdentity("codex")
_VERSION = DataRightsContributionVersion(1)
_SEGMENTS: tuple[tuple[str, LiteralString], ...] = (
    (
        "codex_result_sources",
        """SELECT convert_to(to_jsonb(source)::text || chr(10), 'UTF8')
           FROM armi.codex_result_sources AS source ORDER BY to_jsonb(source)::text""",
    ),
    (
        "codex_task_sources",
        """SELECT convert_to(to_jsonb(source)::text || chr(10), 'UTF8')
           FROM armi.codex_task_sources AS source ORDER BY to_jsonb(source)::text""",
    ),
    (
        "codex_verification_results",
        """SELECT convert_to(to_jsonb(source)::text || chr(10), 'UTF8')
           FROM armi.codex_verification_results AS source ORDER BY to_jsonb(source)::text""",
    ),
)


class PostgreSQLCodexDataRightsParticipant:
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
        task_ids = tuple(
            item.ref for item in request.related_refs if item.kind == "codex-task"
        )
        verification_ids = tuple(
            item.ref
            for item in request.related_refs
            if item.kind == "codex-verification"
        )
        if not task_ids and not verification_ids:
            return DataRightsDiscoveryContribution(_OWNER)
        usage_rows = await (
            await transaction.execute(
                """WITH refs AS (
                     SELECT source_bundle_artifact_id AS artifact_id,
                            codex_task_source_id=ANY(%s::uuid[]) AS targeted
                     FROM armi.codex_task_sources
                     UNION ALL SELECT task_manifest_artifact_id,
                            codex_task_source_id=ANY(%s::uuid[])
                     FROM armi.codex_task_sources
                     UNION ALL SELECT event_transcript_artifact_id,
                            codex_verification_id=ANY(%s::uuid[])
                     FROM armi.codex_verification_results
                     UNION ALL SELECT final_result_artifact_id,
                            codex_verification_id=ANY(%s::uuid[])
                     FROM armi.codex_verification_results
                     UNION ALL SELECT patch_artifact_id,
                            codex_verification_id=ANY(%s::uuid[])
                     FROM armi.codex_verification_results
                     UNION ALL SELECT result_bundle_artifact_id,
                            codex_verification_id=ANY(%s::uuid[])
                     FROM armi.codex_verification_results
                     UNION ALL SELECT diagnostics_artifact_id,
                            codex_verification_id=ANY(%s::uuid[])
                     FROM armi.codex_verification_results
                     UNION ALL SELECT validation_report_artifact_id,
                            codex_verification_id=ANY(%s::uuid[])
                     FROM armi.codex_verification_results
                   ) SELECT artifact_id,count(*),count(*) FILTER (WHERE targeted)
                     FROM refs WHERE artifact_id IS NOT NULL
                     GROUP BY artifact_id ORDER BY artifact_id""",
                (
                    list(task_ids),
                    list(task_ids),
                    list(verification_ids),
                    list(verification_ids),
                    list(verification_ids),
                    list(verification_ids),
                    list(verification_ids),
                    list(verification_ids),
                ),
            )
        ).fetchall()
        return DataRightsDiscoveryContribution(
            _OWNER,
            related_refs=tuple(
                [DataRightsRelatedRef("codex-task", ref) for ref in task_ids]
                + [
                    DataRightsRelatedRef("codex-verification", ref)
                    for ref in verification_ids
                ]
            ),
            targets=tuple(
                [DataRightsTargetRef("codex_task", ref, "redact") for ref in task_ids]
                + [
                    DataRightsTargetRef("codex_task", ref, "redact")
                    for ref in verification_ids
                ]
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
        del transaction
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


__all__ = ("PostgreSQLCodexDataRightsParticipant",)
