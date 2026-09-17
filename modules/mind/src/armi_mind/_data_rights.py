"""Data-rights participant owned by the mind module."""

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

_OWNER = DataRightsOwnerIdentity("mind")
_VERSION = DataRightsContributionVersion(1)
_SEGMENTS: tuple[tuple[str, LiteralString], ...] = (
    (
        "mind_heads",
        """SELECT convert_to(to_jsonb(source)::text || chr(10), 'UTF8')
           FROM armi.mind_heads AS source ORDER BY to_jsonb(source)::text""",
    ),
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
                """SELECT mind_revision_id FROM armi.mind_revisions
                   WHERE subject_commit_id=ANY(%s::uuid[])
                   ORDER BY mind_revision_id""",
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
                     SELECT subject_id,min(mind_version) AS first_version
                     FROM armi.mind_revisions
                     WHERE mind_revision_id=ANY(%s::uuid[])
                     GROUP BY subject_id
                   ), safe AS (
                     SELECT affected.subject_id,
                            affected.first_version,
                            revision.mind_revision_id AS safe_revision_id,
                            revision.semantic_payload
                     FROM affected
                     JOIN armi.mind_revisions AS revision
                       ON revision.subject_id=affected.subject_id
                      AND revision.mind_version=affected.first_version-1
                   ), inserted AS (
                     INSERT INTO armi.mind_revisions (
                       mind_revision_id,subject_id,mind_version,
                       previous_revision_id,origin_kind,origin_ref,semantic_payload,
                       privacy_scope
                     ) SELECT uuidv7(),head.subject_id,
                              head.mind_version+1,head.current_revision_id,
                              'data_rights',%s,
                              jsonb_set(safe.semantic_payload,'{schema_version}','"armi.mind.v4"'::jsonb)
                                || jsonb_build_object('concerns',COALESCE(safe.semantic_payload->'concerns','[]'::jsonb),
                                    'motivation_states',COALESCE(safe.semantic_payload->'motivation_states','[]'::jsonb)),
                              'private'
                       FROM armi.mind_heads AS head
                       JOIN safe ON safe.subject_id=head.subject_id
                     RETURNING subject_id,mind_revision_id
                   ) UPDATE armi.mind_heads AS head
                     SET current_revision_id=inserted.mind_revision_id,
                         mind_version=head.mind_version+1
                     FROM inserted WHERE head.subject_id=inserted.subject_id
                       """,
                (list(revision_ids), request.order_id),
            )
            await transaction.execute(
                """WITH affected AS (
                     SELECT subject_id,min(mind_version) AS first_version
                     FROM armi.mind_revisions
                     WHERE mind_revision_id=ANY(%s::uuid[])
                     GROUP BY subject_id
                   ) UPDATE armi.mind_revisions AS revision
                     SET semantic_payload='{}'::jsonb,
                         data_rights_redacted_at=statement_timestamp()
                     FROM affected
                     WHERE revision.subject_id=affected.subject_id
                        AND revision.mind_version>=affected.first_version
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


__all__ = ("PostgreSQLMindDataRightsParticipant",)
