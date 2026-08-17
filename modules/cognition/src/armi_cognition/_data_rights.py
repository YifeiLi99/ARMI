"""Data-rights participant owned by the cognition module."""

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
    DataRightsTargetRef,
    DataRightsTupleRecordStream,
)
from armi_kernel.application import ArtifactId
from armi_runtime_foundation import PostgreSQLTransaction

_OWNER = DataRightsOwnerIdentity("cognition")
_VERSION = DataRightsContributionVersion(1)
_SEGMENTS: tuple[tuple[str, LiteralString], ...] = (
    (
        "accepted_experiences",
        """SELECT convert_to(to_jsonb(source)::text || chr(10), 'UTF8')
           FROM armi.accepted_experiences AS source ORDER BY to_jsonb(source)::text""",
    ),
    (
        "cognitive_attempts",
        """SELECT convert_to(to_jsonb(source)::text || chr(10), 'UTF8')
           FROM armi.cognitive_attempts AS source ORDER BY to_jsonb(source)::text""",
    ),
    (
        "cognitive_branches",
        """SELECT convert_to(to_jsonb(source)::text || chr(10), 'UTF8')
           FROM armi.cognitive_branches AS source ORDER BY to_jsonb(source)::text""",
    ),
    (
        "cognitive_candidate_applications",
        """SELECT convert_to(to_jsonb(source)::text || chr(10), 'UTF8')
           FROM armi.cognitive_candidate_applications AS source ORDER BY to_jsonb(source)::text""",
    ),
    (
        "cognitive_candidate_basis_links",
        """SELECT convert_to(to_jsonb(source)::text || chr(10), 'UTF8')
           FROM armi.cognitive_candidate_basis_links AS source ORDER BY to_jsonb(source)::text""",
    ),
    (
        "cognitive_candidate_validation_items",
        """SELECT convert_to(to_jsonb(source)::text || chr(10), 'UTF8')
           FROM armi.cognitive_candidate_validation_items AS source ORDER BY to_jsonb(source)::text""",
    ),
    (
        "cognitive_candidate_validations",
        """SELECT convert_to(to_jsonb(source)::text || chr(10), 'UTF8')
           FROM armi.cognitive_candidate_validations AS source ORDER BY to_jsonb(source)::text""",
    ),
    (
        "cognitive_episodes",
        """SELECT convert_to(to_jsonb(source)::text || chr(10), 'UTF8')
           FROM armi.cognitive_episodes AS source ORDER BY to_jsonb(source)::text""",
    ),
    (
        "cognitive_dialogue_aggregates",
        """SELECT convert_to(to_jsonb(source)::text || chr(10), 'UTF8')
           FROM armi.cognitive_dialogue_aggregates AS source ORDER BY to_jsonb(source)::text""",
    ),
    (
        "cognition_maintenance_batch_sources",
        """SELECT convert_to(to_jsonb(source)::text || chr(10), 'UTF8')
           FROM armi.cognition_maintenance_batch_sources AS source
           ORDER BY to_jsonb(source)::text""",
    ),
    (
        "cognition_maintenance_batches",
        """SELECT convert_to(to_jsonb(source)::text || chr(10), 'UTF8')
           FROM armi.cognition_maintenance_batches AS source
           ORDER BY to_jsonb(source)::text""",
    ),
    (
        "cognition_maintenance_cursors",
        """SELECT convert_to(to_jsonb(source)::text || chr(10), 'UTF8')
           FROM armi.cognition_maintenance_cursors AS source
           ORDER BY to_jsonb(source)::text""",
    ),
    (
        "exact_life_query_intents",
        """SELECT convert_to(to_jsonb(source)::text || chr(10), 'UTF8')
           FROM armi.exact_life_query_intents AS source ORDER BY to_jsonb(source)::text""",
    ),
)


class PostgreSQLCognitionDataRightsParticipant:
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
        experience_ids = tuple(
            item.ref for item in request.related_refs if item.kind == "experience"
        )
        usage_rows = await (
            await transaction.execute(
                """WITH refs AS (
                     SELECT context_manifest_artifact_id AS artifact_id, context_party_id
                     FROM armi.cognitive_episodes WHERE context_manifest_artifact_id IS NOT NULL
                     UNION ALL SELECT compiled_context_artifact_id, context_party_id
                     FROM armi.cognitive_episodes WHERE compiled_context_artifact_id IS NOT NULL
                     UNION ALL SELECT attempt.request_artifact_id, episode.context_party_id
                     FROM armi.cognitive_attempts AS attempt JOIN armi.cognitive_episodes AS episode
                       ON episode.cognitive_episode_id = attempt.cognitive_episode_id
                     UNION ALL SELECT attempt.response_artifact_id, episode.context_party_id
                     FROM armi.cognitive_attempts AS attempt JOIN armi.cognitive_episodes AS episode
                       ON episode.cognitive_episode_id = attempt.cognitive_episode_id
                     WHERE attempt.response_artifact_id IS NOT NULL
                     UNION ALL SELECT attempt.late_response_artifact_id,
                                      episode.context_party_id
                     FROM armi.cognitive_attempts AS attempt
                     JOIN armi.cognitive_episodes AS episode
                       ON episode.cognitive_episode_id=attempt.cognitive_episode_id
                     WHERE attempt.late_response_artifact_id IS NOT NULL
                     UNION ALL SELECT aggregate.aggregate_artifact_id,
                                      episode.context_party_id
                     FROM armi.cognitive_dialogue_aggregates AS aggregate
                     JOIN armi.cognitive_episodes AS episode
                       ON episode.cognitive_episode_id=aggregate.cognitive_episode_id
                     UNION ALL SELECT validation.change_set_artifact_id, episode.context_party_id
                     FROM armi.cognitive_candidate_validations AS validation
                     JOIN armi.cognitive_episodes AS episode
                       ON episode.cognitive_episode_id = validation.cognitive_episode_id
                     WHERE validation.change_set_artifact_id IS NOT NULL
                   ) SELECT artifact_id, count(*),
                       count(*) FILTER (WHERE context_party_id = %s)
                     FROM refs GROUP BY artifact_id ORDER BY artifact_id""",
                (request.party_id,),
            )
        ).fetchall()
        return DataRightsDiscoveryContribution(
            _OWNER,
            targets=tuple(
                DataRightsTargetRef("experience", ref, "tombstone")
                for ref in experience_ids
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
        del transaction, request
        return DataRightsApplyContribution(_OWNER)

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


__all__ = ("PostgreSQLCognitionDataRightsParticipant",)
