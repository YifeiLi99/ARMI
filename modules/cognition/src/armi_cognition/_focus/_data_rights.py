"""Data-rights participant owned by the focus module."""

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
        "focus_revisions",
        """SELECT convert_to(to_jsonb(source)::text || chr(10), 'UTF8')
           FROM armi.focus_revisions AS source ORDER BY to_jsonb(source)::text""",
    ),
)


class PostgreSQLFocusDataRightsParticipant:
    @property
    def owner_identity(self) -> DataRightsOwnerIdentity:
        return _OWNER

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
                """SELECT focus_revision_id FROM armi.focus_revisions
                   WHERE subject_commit_id=ANY(%s::uuid[])
                   ORDER BY focus_revision_id""",
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
            await transaction.execute(
                """WITH affected AS (
                     SELECT subject_id,min(focus_version) AS first_version
                     FROM armi.focus_revisions
                     WHERE focus_revision_id=ANY(%s::uuid[])
                     GROUP BY subject_id
                   ), safe AS (
                     SELECT affected.subject_id,
                            affected.first_version,
                            revision.focus_revision_id AS safe_revision_id,
                            revision.semantic_payload
                     FROM affected
                     JOIN armi.focus_revisions AS revision
                       ON revision.subject_id=affected.subject_id
                      AND revision.focus_version=affected.first_version-1
                   ), retired AS (
                     UPDATE armi.focus_revisions AS head SET is_current=false
                     FROM safe WHERE head.subject_id=safe.subject_id
                       AND head.is_current
                     RETURNING head.*
                   )
                     INSERT INTO armi.focus_revisions (
                       focus_revision_id,subject_id,focus_version,
                       previous_revision_id,origin_kind,origin_ref,semantic_payload,
                       is_current
                     ) SELECT uuidv7(),head.subject_id,
                              head.focus_version+1,head.focus_revision_id,
                              'data_rights',%s,
                              safe.semantic_payload,
                              true
                       FROM retired AS head
                       JOIN safe ON safe.subject_id=head.subject_id""",
                (list(revision_ids), request.order_id),
            )
            await transaction.execute(
                """WITH affected AS (
                     SELECT subject_id,min(focus_version) AS first_version
                     FROM armi.focus_revisions
                     WHERE focus_revision_id=ANY(%s::uuid[])
                     GROUP BY subject_id
                   ) UPDATE armi.focus_revisions AS revision
                     SET semantic_payload='{}'::jsonb,
                         data_rights_redacted_at=statement_timestamp()
                     FROM affected
                     WHERE revision.subject_id=affected.subject_id
                        AND revision.focus_version>=affected.first_version
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
                    segment_name,
                    "application/x-ndjson",
                    DataRightsTupleRecordStream(records),
                )
            )
        return tuple(segments)


__all__ = ("PostgreSQLFocusDataRightsParticipant",)
