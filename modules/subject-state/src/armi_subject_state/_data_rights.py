"""Data-rights participant owned by the subject-state module."""

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

_OWNER = DataRightsOwnerIdentity("subject-state")
_VERSION = DataRightsContributionVersion(1)
_SEGMENTS: tuple[tuple[str, LiteralString], ...] = (
    (
        "subject_component_heads",
        """SELECT convert_to(to_jsonb(source)::text || chr(10), 'UTF8')
           FROM armi.subject_component_heads AS source ORDER BY to_jsonb(source)::text""",
    ),
    (
        "subject_component_revisions",
        """SELECT convert_to(to_jsonb(source)::text || chr(10), 'UTF8')
           FROM armi.subject_component_revisions AS source ORDER BY to_jsonb(source)::text""",
    ),
)


class PostgreSQLSubjectStateDataRightsParticipant:
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
        commits = tuple(
            item.ref for item in request.related_refs if item.kind == "subject-commit"
        )
        if not commits:
            return DataRightsDiscoveryContribution(_OWNER)
        rows = await (
            await transaction.execute(
                """SELECT component_revision_id FROM armi.subject_component_revisions
                   WHERE subject_commit_id=ANY(%s::uuid[])
                   ORDER BY component_revision_id""",
                (list(commits),),
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
        revision_ids = tuple(
            item.ref
            for item in request.related_refs
            if item.kind == "subject-component"
        )
        if request.order_kind == "delete_related" and revision_ids:
            activity_ids = tuple(
                item.ref for item in request.related_refs if item.kind == "activity"
            )
            await transaction.execute(
                """WITH affected AS (
                     SELECT subject_id,component_kind,min(component_version) AS first_version
                     FROM armi.subject_component_revisions
                     WHERE component_revision_id=ANY(%s::uuid[])
                     GROUP BY subject_id,component_kind
                   ), safe AS (
                     SELECT affected.subject_id,affected.component_kind,
                            affected.first_version,
                            revision.component_revision_id AS safe_revision_id,
                            revision.semantic_payload
                     FROM affected
                     JOIN armi.subject_component_revisions AS revision
                       ON revision.subject_id=affected.subject_id
                      AND revision.component_kind=affected.component_kind
                      AND revision.component_version=affected.first_version-1
                   ), inserted AS (
                     INSERT INTO armi.subject_component_revisions (
                       component_revision_id,subject_id,component_kind,component_version,
                       previous_revision_id,origin_kind,origin_ref,semantic_payload,
                       privacy_scope
                     ) SELECT uuidv7(),head.subject_id,head.component_kind,
                              head.component_version+1,head.current_revision_id,
                              'data_rights',%s,
                              CASE WHEN head.component_kind='life_mode' THEN
                                jsonb_set(
                                  current_revision.semantic_payload,
                                  '{active_activities}',
                                  COALESCE((
                                    SELECT jsonb_agg(value)
                                    FROM jsonb_array_elements_text(
                                      current_revision.semantic_payload->'active_activities'
                                    ) AS value
                                    WHERE value::uuid<>ALL(%s::uuid[])
                                  ),'[]'::jsonb)
                                )
                              ELSE safe.semantic_payload END,
                              'private'
                       FROM armi.subject_component_heads AS head
                       JOIN safe ON safe.subject_id=head.subject_id
                                AND safe.component_kind=head.component_kind
                       JOIN armi.subject_component_revisions AS current_revision
                         ON current_revision.component_revision_id=head.current_revision_id
                     RETURNING subject_id,component_kind,component_revision_id
                   ) UPDATE armi.subject_component_heads AS head
                     SET current_revision_id=inserted.component_revision_id,
                         component_version=head.component_version+1
                     FROM inserted WHERE head.subject_id=inserted.subject_id
                       AND head.component_kind=inserted.component_kind""",
                (list(revision_ids), request.order_id, list(activity_ids)),
            )
            await transaction.execute(
                """WITH affected AS (
                     SELECT subject_id,component_kind,min(component_version) AS first_version
                     FROM armi.subject_component_revisions
                     WHERE component_revision_id=ANY(%s::uuid[])
                     GROUP BY subject_id,component_kind
                   ) UPDATE armi.subject_component_revisions AS revision
                     SET semantic_payload='{}'::jsonb,
                         data_rights_redacted_at=statement_timestamp()
                     FROM affected
                     WHERE revision.subject_id=affected.subject_id
                       AND revision.component_kind=affected.component_kind
                       AND revision.component_version>=affected.first_version
                       AND revision.origin_kind<>'data_rights'
                       AND revision.data_rights_redacted_at IS NULL""",
                (list(revision_ids),),
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


__all__ = ("PostgreSQLSubjectStateDataRightsParticipant",)
