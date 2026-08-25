"""Data-rights participant owned by the activity module."""

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

_OWNER = DataRightsOwnerIdentity("activity")
_VERSION = DataRightsContributionVersion(1)
_SEGMENTS: tuple[tuple[str, LiteralString], ...] = (
    (
        "activities",
        """SELECT convert_to(to_jsonb(source)::text || chr(10), 'UTF8')
           FROM armi.activities AS source ORDER BY to_jsonb(source)::text""",
    ),
    (
        "activity_decisions",
        """SELECT convert_to(to_jsonb(source)::text || chr(10), 'UTF8')
           FROM armi.activity_decisions AS source ORDER BY to_jsonb(source)::text""",
    ),
    (
        "activity_revisions",
        """SELECT convert_to(to_jsonb(source)::text || chr(10), 'UTF8')
           FROM armi.activity_revisions AS source ORDER BY to_jsonb(source)::text""",
    ),
)


class PostgreSQLActivityDataRightsParticipant:
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
                """SELECT DISTINCT activity_id FROM armi.activity_revisions
                   WHERE candidate_validation_id=ANY(%s::uuid[])
                   ORDER BY activity_id""",
                (list(validations),),
            )
        ).fetchall()
        return DataRightsDiscoveryContribution(
            _OWNER,
            related_refs=tuple(
                DataRightsRelatedRef("activity", row[0]) for row in rows
            ),
            targets=tuple(
                DataRightsTargetRef("activity", row[0], "redact") for row in rows
            ),
        )

    async def apply(
        self,
        transaction: PostgreSQLTransaction,
        request: DataRightsApplyRequest,
    ) -> DataRightsApplyContribution:
        activity_ids = tuple(
            item.ref for item in request.related_refs if item.kind == "activity"
        )
        if request.order_kind == "delete_related" and activity_ids:
            await transaction.execute(
                """WITH current AS (
                     SELECT activity.activity_id,activity.current_revision_id,
                            activity.head_version,revision.revision_no
                     FROM armi.activities AS activity
                     JOIN armi.activity_revisions AS revision
                       ON revision.activity_revision_id=activity.current_revision_id
                     WHERE activity.activity_id=ANY(%s::uuid[])
                   ), inserted AS (
                     INSERT INTO armi.activity_revisions (
                       activity_revision_id,activity_id,revision_no,
                       previous_revision_id,goal,status,terminal_reason,
                       transition_kind,data_rights_redacted_at
                     ) SELECT uuidv7(),activity_id,revision_no+1,current_revision_id,
                              NULL,'abandoned',NULL,'data_rights',statement_timestamp()
                       FROM current
                     RETURNING activity_id,activity_revision_id
                   ) UPDATE armi.activities AS activity
                     SET current_revision_id=inserted.activity_revision_id,
                         head_version=activity.head_version+1
                     FROM inserted WHERE activity.activity_id=inserted.activity_id""",
                (list(activity_ids),),
            )
            await transaction.execute(
                """UPDATE armi.activity_revisions
                   SET goal=NULL,progress_summary=NULL,waiting_condition=NULL,
                       waiting_condition_kind=NULL,resumption_cue=NULL,
                       resume_not_before=NULL,next_safe_step=NULL,
                       terminal_reason=NULL,
                       data_rights_redacted_at=statement_timestamp()
                   WHERE activity_id=ANY(%s::uuid[])
                     AND transition_kind<>'data_rights'""",
                (list(activity_ids),),
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


__all__ = ("PostgreSQLActivityDataRightsParticipant",)
