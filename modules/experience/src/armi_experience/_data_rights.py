"""Data-rights participant owned by the Experience module."""

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
    DataRightsTargetRef,
    DataRightsTupleRecordStream,
)
from armi_runtime_foundation import PostgreSQLTransaction

_OWNER = DataRightsOwnerIdentity("experience")
_VERSION = DataRightsContributionVersion(1)
_SEGMENTS: tuple[tuple[str, LiteralString], ...] = (
    (
        "accepted_experiences",
        """SELECT convert_to(to_jsonb(source)::text || chr(10), 'UTF8')
           FROM armi.accepted_experiences AS source
           ORDER BY to_jsonb(source)::text""",
    ),
)


class PostgreSQLExperienceDataRightsParticipant:
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
        del transaction
        return DataRightsDiscoveryContribution(
            _OWNER,
            targets=tuple(
                DataRightsTargetRef("experience", item.ref, "tombstone")
                for item in request.related_refs
                if item.kind == "experience"
            ),
        )

    async def apply(
        self,
        transaction: PostgreSQLTransaction,
        request: DataRightsApplyRequest,
    ) -> DataRightsApplyContribution:
        experience_ids = tuple(
            item.ref for item in request.related_refs if item.kind == "experience"
        )
        if request.order_kind in {"stop_use", "delete_related"} and experience_ids:
            await transaction.execute(
                """UPDATE armi.accepted_experiences
                   SET first_person_gist=CASE WHEN %s='delete_related'
                                              THEN NULL ELSE first_person_gist END,
                       uncertainty=CASE WHEN %s='delete_related'
                                        THEN NULL ELSE uncertainty END,
                       data_rights_order_id=%s,
                       data_rights_hidden_at=statement_timestamp()
                   WHERE experience_id=ANY(%s::uuid[])
                     AND data_rights_hidden_at IS NULL""",
                (
                    request.order_kind,
                    request.order_kind,
                    request.order_id,
                    list(experience_ids),
                ),
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


__all__ = ("PostgreSQLExperienceDataRightsParticipant",)
