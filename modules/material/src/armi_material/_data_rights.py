"""Data-rights participant owned by the material module."""

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

_OWNER = DataRightsOwnerIdentity("material")
_VERSION = DataRightsContributionVersion(1)
_SEGMENTS: tuple[tuple[str, LiteralString], ...] = (
    (
        "life_material_revisions",
        """SELECT convert_to(to_jsonb(source)::text || chr(10), 'UTF8')
           FROM armi.life_material_revisions AS source ORDER BY to_jsonb(source)::text""",
    ),
    (
        "life_materials",
        """SELECT convert_to(to_jsonb(source)::text || chr(10), 'UTF8')
           FROM armi.life_materials AS source ORDER BY to_jsonb(source)::text""",
    ),
)


class PostgreSQLMaterialDataRightsParticipant:
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
        validations = tuple(
            item.ref
            for item in request.related_refs
            if item.kind == "candidate-validation"
        )
        if not validations:
            return DataRightsDiscoveryContribution(_OWNER)
        rows = await (
            await transaction.execute(
                """SELECT DISTINCT life_material_id FROM armi.life_material_revisions
                   WHERE candidate_validation_id=ANY(%s::uuid[])
                   ORDER BY life_material_id""",
                (list(validations),),
            )
        ).fetchall()
        material_ids = tuple(row[0] for row in rows)
        usage_rows = await (
            await transaction.execute(
                """SELECT artifact_id,count(*),
                          count(*) FILTER (WHERE life_material_id=ANY(%s::uuid[]))
                   FROM armi.life_material_revisions
                   WHERE artifact_id IS NOT NULL
                   GROUP BY artifact_id ORDER BY artifact_id""",
                (list(material_ids),),
            )
        ).fetchall()
        return DataRightsDiscoveryContribution(
            _OWNER,
            related_refs=tuple(
                DataRightsRelatedRef("material", row[0]) for row in rows
            ),
            targets=tuple(
                DataRightsTargetRef("material", row[0], "redact") for row in rows
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
        material_ids = tuple(
            item.ref for item in request.related_refs if item.kind == "material"
        )
        if request.order_kind == "delete_related" and material_ids:
            await transaction.execute(
                """UPDATE armi.life_material_revisions
                   SET artifact_id=NULL,title=NULL,metadata=NULL,
                       data_rights_redacted_at=statement_timestamp()
                   WHERE life_material_id=ANY(%s::uuid[])
                     AND data_rights_redacted_at IS NULL""",
                (list(material_ids),),
            )
            await transaction.execute(
                """UPDATE armi.life_materials
                   SET deleted_at=COALESCE(deleted_at,statement_timestamp()),
                       updated_at=statement_timestamp()
                   WHERE life_material_id=ANY(%s::uuid[])""",
                (list(material_ids),),
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


__all__ = ("PostgreSQLMaterialDataRightsParticipant",)
