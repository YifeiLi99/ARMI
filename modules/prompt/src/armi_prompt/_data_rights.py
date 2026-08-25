"""Data-rights participant owned by the prompt module."""

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

_OWNER = DataRightsOwnerIdentity("prompt")
_VERSION = DataRightsContributionVersion(1)
_SEGMENTS: tuple[tuple[str, LiteralString], ...] = (
    (
        "prompt_documents",
        """SELECT convert_to(to_jsonb(source)::text || chr(10), 'UTF8')
           FROM armi.prompt_documents AS source ORDER BY to_jsonb(source)::text""",
    ),
    (
        "prompt_revisions",
        """SELECT convert_to(to_jsonb(source)::text || chr(10), 'UTF8')
           FROM armi.prompt_revisions AS source ORDER BY to_jsonb(source)::text""",
    ),
)


class PostgreSQLPromptDataRightsParticipant:
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
        commit_ids = tuple(
            item.ref for item in request.related_refs if item.kind == "subject-commit"
        )
        rows = await (
            await transaction.execute(
                """SELECT DISTINCT document.prompt_document_id
                   FROM armi.prompt_documents AS document
                   JOIN armi.prompt_revisions AS revision
                     ON revision.prompt_document_id=document.prompt_document_id
                   WHERE document.prompt_kind<>'personality_anchor'
                     AND (revision.author_party_id=%s
                          OR revision.subject_commit_id=ANY(%s::uuid[]))
                   ORDER BY document.prompt_document_id""",
                (request.party_id, list(commit_ids)),
            )
        ).fetchall()
        prompt_ids = tuple(row[0] for row in rows)
        anchor_rows = await (
            await transaction.execute(
                """SELECT prompt_document_id FROM armi.prompt_documents
                   WHERE prompt_kind='personality_anchor' AND status='active'
                   ORDER BY prompt_document_id"""
            )
        ).fetchall()
        usage_rows = await (
            await transaction.execute(
                """SELECT content_artifact_id,count(*),
                          count(*) FILTER (WHERE prompt_document_id=ANY(%s::uuid[]))
                   FROM armi.prompt_revisions GROUP BY content_artifact_id
                   ORDER BY content_artifact_id""",
                (list(prompt_ids),),
            )
        ).fetchall()
        return DataRightsDiscoveryContribution(
            _OWNER,
            related_refs=tuple(
                DataRightsRelatedRef("prompt", ref) for ref in prompt_ids
            ),
            targets=tuple(
                [DataRightsTargetRef("prompt", ref, "redact") for ref in prompt_ids]
                + [
                    DataRightsTargetRef(
                        "prompt", row[0], "retain", "subject_continuity"
                    )
                    for row in anchor_rows
                ]
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
        prompt_ids = tuple(
            item.ref for item in request.related_refs if item.kind == "prompt"
        )
        if request.order_kind == "delete_related" and prompt_ids:
            await transaction.execute(
                """UPDATE armi.prompt_documents
                   SET status='inactive'
                   WHERE prompt_document_id=ANY(%s::uuid[])
                     AND prompt_kind<>'personality_anchor'""",
                (list(prompt_ids),),
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


__all__ = ("PostgreSQLPromptDataRightsParticipant",)
