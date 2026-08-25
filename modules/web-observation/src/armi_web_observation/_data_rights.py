"""Data-rights participant owned by the web-observation module."""

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

_OWNER = DataRightsOwnerIdentity("web-observation")
_VERSION = DataRightsContributionVersion(1)
_SEGMENTS: tuple[tuple[str, LiteralString], ...] = (
    (
        "observation_attempts",
        """SELECT convert_to(to_jsonb(source)::text || chr(10), 'UTF8')
           FROM armi.observation_attempts AS source ORDER BY to_jsonb(source)::text""",
    ),
    (
        "observation_tool_calls",
        """SELECT convert_to(to_jsonb(source)::text || chr(10), 'UTF8')
           FROM armi.observation_tool_calls AS source ORDER BY to_jsonb(source)::text""",
    ),
    (
        "web_evidence_sources",
        """SELECT convert_to(to_jsonb(source)::text || chr(10), 'UTF8')
           FROM armi.web_evidence_sources AS source ORDER BY to_jsonb(source)::text""",
    ),
    (
        "web_observation_requests",
        """SELECT convert_to(to_jsonb(source)::text || chr(10), 'UTF8')
           FROM armi.web_observation_requests AS source ORDER BY to_jsonb(source)::text""",
    ),
    (
        "web_research_intents",
        """SELECT convert_to(to_jsonb(source)::text || chr(10), 'UTF8')
           FROM armi.web_research_intents AS source ORDER BY to_jsonb(source)::text""",
    ),
)


class PostgreSQLWebObservationDataRightsParticipant:
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
        observed_requests = tuple(
            item.ref for item in request.related_refs if item.kind == "web-observation"
        )
        rows = await (
            await transaction.execute(
                """SELECT web_research_intent_id,web_observation_request_id
                   FROM armi.web_research_intents
                   WHERE creator_party_id=%s
                      OR subject_commit_id=ANY(%s::uuid[])
                      OR web_observation_request_id=ANY(%s::uuid[])
                   ORDER BY web_research_intent_id""",
                (request.party_id, list(commit_ids), list(observed_requests)),
            )
        ).fetchall()
        intent_ids = tuple(row[0] for row in rows)
        request_ids = tuple(
            dict.fromkeys(
                [row[1] for row in rows if row[1] is not None] + list(observed_requests)
            )
        )
        usage_rows = await (
            await transaction.execute(
                """WITH refs AS (
                     SELECT query_artifact_id AS artifact_id,
                            web_research_intent_id=ANY(%s::uuid[]) AS targeted
                     FROM armi.web_research_intents
                     UNION ALL SELECT request_artifact_id,
                            web_observation_request_id=ANY(%s::uuid[])
                     FROM armi.web_observation_requests
                     UNION ALL SELECT result_artifact_id,
                            web_observation_request_id=ANY(%s::uuid[])
                     FROM armi.web_observation_requests
                     UNION ALL SELECT attempt.result_artifact_id,
                            request.web_observation_request_id=ANY(%s::uuid[])
                     FROM armi.observation_attempts AS attempt
                     JOIN armi.web_observation_requests AS request
                       ON request.work_id=attempt.work_id
                     UNION ALL SELECT source.source_artifact_id,
                            request.web_observation_request_id=ANY(%s::uuid[])
                     FROM armi.web_evidence_sources AS source
                     JOIN armi.observation_attempts AS attempt
                       ON attempt.observation_attempt_id=source.observation_attempt_id
                     JOIN armi.web_observation_requests AS request
                       ON request.work_id=attempt.work_id
                   ) SELECT artifact_id,count(*),count(*) FILTER (WHERE targeted)
                     FROM refs WHERE artifact_id IS NOT NULL
                     GROUP BY artifact_id ORDER BY artifact_id""",
                (
                    list(intent_ids),
                    list(request_ids),
                    list(request_ids),
                    list(request_ids),
                    list(request_ids),
                ),
            )
        ).fetchall()
        return DataRightsDiscoveryContribution(
            _OWNER,
            related_refs=tuple(
                [DataRightsRelatedRef("web-research", ref) for ref in intent_ids]
                + [DataRightsRelatedRef("web-observation", ref) for ref in request_ids]
            ),
            targets=tuple(
                DataRightsTargetRef("web_research", ref, "redact") for ref in intent_ids
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
        await transaction.execute(
            """UPDATE armi.web_observation_requests AS observation
               SET status='cancelled',last_error_code='WEB-DATA-RIGHTS-CANCELLED',
                   completed_at=statement_timestamp()
               FROM armi.web_research_intents AS intent
               WHERE observation.web_research_intent_id=intent.web_research_intent_id
                 AND intent.creator_party_id=%s
                 AND observation.status IN ('pending','running')""",
            (request.party_id,),
        )
        await transaction.execute(
            """UPDATE armi.web_research_intents
               SET status='cancelled',completed_at=statement_timestamp()
               WHERE creator_party_id=%s AND status IN ('pending','admitted')""",
            (request.party_id,),
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


__all__ = ("PostgreSQLWebObservationDataRightsParticipant",)
