"""Data-rights participant owned by Cognition."""

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

_OWNER = DataRightsOwnerIdentity("cognition")
_SEGMENTS: tuple[tuple[str, LiteralString], ...] = (
    (
        "event_appraisals",
        """SELECT convert_to(to_jsonb(source)::text || chr(10), 'UTF8')
           FROM armi.event_appraisals AS source ORDER BY to_jsonb(source)::text""",
    ),
)


class PostgreSQLEventDataRightsParticipant:
    @property
    def owner_identity(self) -> DataRightsOwnerIdentity:
        return _OWNER

    async def discover(
        self,
        transaction: PostgreSQLTransaction,
        request: DataRightsDiscoveryRequest,
    ) -> DataRightsDiscoveryContribution:
        episodes = tuple(
            item.ref for item in request.related_refs if item.kind == "cognition"
        )
        references = [
            str(request.party_id),
            *(str(item.ref) for item in request.related_refs),
        ]
        rows = await (
            await transaction.execute(
                """SELECT event_appraisal_id FROM armi.event_appraisals
                   WHERE cognitive_episode_id=ANY(%s::uuid[])
                      OR source_ref::text=ANY(%s::text[])
                      OR EXISTS (
                          SELECT 1 FROM jsonb_path_query(
                              context_document, '$.context.layers[*].items[*].source.reference'
                          ) reference
                          WHERE reference #>> '{}' = ANY(%s::text[])
                      )
                   ORDER BY event_appraisal_id""",
                (list(episodes), references, references),
            )
        ).fetchall()
        return DataRightsDiscoveryContribution(
            _OWNER,
            related_refs=tuple(
                DataRightsRelatedRef("event-appraisal", row[0]) for row in rows
            ),
            targets=tuple(
                DataRightsTargetRef("cognition", row[0], "redact", "subject_continuity")
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
            await transaction.execute(
                """UPDATE armi.event_appraisals
                   SET mood_result=NULL,mind_result=NULL,context_document=NULL,
                       data_rights_redacted_at=statement_timestamp()
                   WHERE event_appraisal_id=ANY(%s::uuid[])
                     AND data_rights_redacted_at IS NULL""",
                (list(event_ids),),
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


__all__ = ("PostgreSQLEventDataRightsParticipant",)
