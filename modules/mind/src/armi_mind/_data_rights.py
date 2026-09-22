"""Data-rights participant owned by the mind module."""

from __future__ import annotations

from typing import LiteralString

from armi_data_rights.api import (
    DataRightsApplyContribution,
    DataRightsApplyRequest,
    DataRightsCanonicalRecord,
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

_OWNER = DataRightsOwnerIdentity("mind")
_SEGMENTS: tuple[tuple[str, LiteralString], ...] = (
    (
        "mind_revisions",
        """SELECT convert_to(to_jsonb(source)::text || chr(10), 'UTF8')
           FROM armi.mind_revisions AS source ORDER BY to_jsonb(source)::text""",
    ),
)


class PostgreSQLMindDataRightsParticipant:
    @property
    def owner_identity(self) -> DataRightsOwnerIdentity:
        return _OWNER

    async def discover(
        self,
        transaction: PostgreSQLTransaction,
        request: DataRightsDiscoveryRequest,
    ) -> DataRightsDiscoveryContribution:
        refs = [
            str(request.party_id),
            *(str(item.ref) for item in request.related_refs),
        ]
        rows = await (
            await transaction.execute(
                """SELECT mind_revision_id FROM armi.mind_revisions
               WHERE EXISTS (SELECT 1 FROM jsonb_path_query(semantic_payload, '$.objects[*].**') value
                   WHERE jsonb_typeof(value)='string' AND value #>> '{}' = ANY(%s::text[]))
               ORDER BY mind_revision_id""",
                (refs,),
            )
        ).fetchall()
        return DataRightsDiscoveryContribution(
            _OWNER,
            related_refs=tuple(
                DataRightsRelatedRef("subject-component", row[0]) for row in rows
            ),
            targets=tuple(
                DataRightsTargetRef(
                    "subject_component", row[0], "redact", "subject_continuity"
                )
                for row in rows
            ),
        )

    async def apply(
        self,
        transaction: PostgreSQLTransaction,
        request: DataRightsApplyRequest,
    ) -> DataRightsApplyContribution:
        refs = [
            str(request.party_id),
            *(str(item.ref) for item in request.related_refs),
        ]
        if request.order_kind == "delete_related":
            # Removing an evidence source withdraws every associated object and
            # its eligibility, including historical readable projections.
            await transaction.execute(
                """UPDATE armi.mind_revisions r SET semantic_payload=jsonb_set(
                    semantic_payload,'{objects}',COALESCE((
                        SELECT jsonb_agg(item) FROM jsonb_array_elements(r.semantic_payload->'objects') item
                        WHERE NOT EXISTS (SELECT 1 FROM jsonb_path_query(item,'$.**') value
                            WHERE jsonb_typeof(value)='string' AND value #>> '{}' = ANY(%s::text[]))
                    ),'[]'::jsonb)),data_rights_redacted_at=statement_timestamp()
                   WHERE EXISTS (SELECT 1 FROM jsonb_path_query(semantic_payload,'$.objects[*].**') value
                       WHERE jsonb_typeof(value)='string' AND value #>> '{}' = ANY(%s::text[]))""",
                (refs, refs),
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
                    segment_name,
                    "application/x-ndjson",
                    DataRightsTupleRecordStream(records),
                )
            )
        return tuple(segments)


__all__ = ("PostgreSQLMindDataRightsParticipant",)
