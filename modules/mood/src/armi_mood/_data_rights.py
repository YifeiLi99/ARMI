"""Data-rights participant owned by the mood module."""

from __future__ import annotations

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
    DataRightsRelatedRef,
    DataRightsTargetRef,
    DataRightsTupleRecordStream,
)
from armi_runtime_foundation import PostgreSQLTransaction

_OWNER = DataRightsOwnerIdentity("mood")
_VERSION = DataRightsContributionVersion(1)
_SEGMENTS: tuple[tuple[str, LiteralString], ...] = (
    (
        "mood_appraisal_events",
        """SELECT convert_to(to_jsonb(source)::text || chr(10), 'UTF8')
           FROM armi.mood_appraisal_events AS source
           ORDER BY to_jsonb(source)::text""",
    ),
    (
        "mood_heads",
        """SELECT convert_to(to_jsonb(source)::text || chr(10), 'UTF8')
           FROM armi.mood_heads AS source ORDER BY to_jsonb(source)::text""",
    ),
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

    @property
    def schema_version(self) -> DataRightsContributionVersion:
        return _VERSION

    async def discover(
        self,
        transaction: PostgreSQLTransaction,
        request: DataRightsDiscoveryRequest,
    ) -> DataRightsDiscoveryContribution:
        episodes = tuple(
            item.ref for item in request.related_refs if item.kind == "cognition"
        )
        if not episodes:
            return DataRightsDiscoveryContribution(_OWNER)
        rows = await (
            await transaction.execute(
                """SELECT mood_appraisal_event_id FROM armi.mood_appraisal_events
                   WHERE mood_episode_id=ANY(%s::uuid[])
                   ORDER BY mood_appraisal_event_id""",
                (list(episodes),),
            )
        ).fetchall()
        return DataRightsDiscoveryContribution(
            _OWNER,
            related_refs=tuple(DataRightsRelatedRef("mood", row[0]) for row in rows),
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
            item.ref for item in request.related_refs if item.kind == "mood"
        )
        if request.order_kind == "delete_related" and event_ids:
            await transaction.execute(
                """UPDATE armi.mood_appraisal_events
                   SET gist=NULL,appraisal_payload=NULL,derived_appraisal_payload=NULL,
                       data_rights_redacted_at=statement_timestamp()
                   WHERE mood_appraisal_event_id=ANY(%s::uuid[])
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
                    _VERSION,
                    segment_name,
                    "application/x-ndjson",
                    DataRightsTupleRecordStream(records),
                )
            )
        return tuple(segments)


__all__ = ("PostgreSQLMoodDataRightsParticipant",)
