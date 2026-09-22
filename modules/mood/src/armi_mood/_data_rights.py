"""Data-rights participant owned by the mood module."""

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

_OWNER = DataRightsOwnerIdentity("mood")
_SEGMENTS: tuple[tuple[str, LiteralString], ...] = (
    (
        "mood_revisions",
        """SELECT convert_to(to_jsonb(source)::text || chr(10), 'UTF8')
           FROM armi.mood_revisions AS source ORDER BY to_jsonb(source)::text""",
    ),
)


class PostgreSQLMoodDataRightsParticipant:
    @property
    def owner_identity(self) -> DataRightsOwnerIdentity:
        return _OWNER

    async def discover(
        self,
        transaction: PostgreSQLTransaction,
        request: DataRightsDiscoveryRequest,
    ) -> DataRightsDiscoveryContribution:
        rows = [
            (item.ref,)
            for item in request.related_refs
            if item.kind == "event-appraisal"
        ]
        return DataRightsDiscoveryContribution(
            _OWNER,
            related_refs=tuple(
                DataRightsRelatedRef("event-appraisal", row[0]) for row in rows
            ),
            targets=tuple(
                DataRightsTargetRef("mood", row[0], "redact", "subject_continuity")
                for row in rows
            ),
        )

    async def apply(
        self,
        transaction: PostgreSQLTransaction,
        request: DataRightsApplyRequest,
    ) -> DataRightsApplyContribution:
        event_ids = tuple(
            item.ref for item in request.related_refs if item.kind == "event-appraisal"
        )
        if request.order_kind == "delete_related" and event_ids:
            # Preserve accumulated affect while removing the event's retrievable content.
            await transaction.execute(
                """UPDATE armi.mood_revisions r SET semantic_payload=jsonb_set(
                       semantic_payload,'{episodes}',COALESCE((
                           SELECT jsonb_agg(CASE WHEN item->>'event_id'=ANY(%s::text[])
                               THEN jsonb_set(item,'{summary}','\"\"'::jsonb) ELSE item END)
                           FROM jsonb_array_elements(r.semantic_payload->'episodes') item
                       ),'[]'::jsonb))
                   WHERE EXISTS (SELECT 1 FROM jsonb_array_elements(r.semantic_payload->'episodes') item
                       WHERE item->>'event_id'=ANY(%s::text[]))""",
                (
                    [str(value) for value in event_ids],
                    [str(value) for value in event_ids],
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
                    segment_name,
                    "application/x-ndjson",
                    DataRightsTupleRecordStream(records),
                )
            )
        return tuple(segments)


__all__ = ("PostgreSQLMoodDataRightsParticipant",)
