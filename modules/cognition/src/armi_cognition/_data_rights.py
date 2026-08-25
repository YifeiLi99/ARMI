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
    DataRightsRelatedRef,
    DataRightsTargetRef,
    DataRightsTupleRecordStream,
)
from armi_kernel.application import ArtifactId
from armi_runtime_foundation import PostgreSQLTransaction

_OWNER = DataRightsOwnerIdentity("cognition")
_VERSION = DataRightsContributionVersion(2)
_SEGMENTS: tuple[tuple[str, LiteralString], ...] = (
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
        context_episode_ids = tuple(
            item.ref
            for item in request.related_refs
            if item.kind == "cognitive-context"
        )
        episode_rows = await (
            await transaction.execute(
                """SELECT cognitive_episode_id
                   FROM armi.cognitive_episodes
                   WHERE context_party_id=%s
                      OR cognitive_episode_id=ANY(%s::uuid[])
                   ORDER BY cognitive_episode_id""",
                (request.party_id, list(context_episode_ids)),
            )
        ).fetchall()
        episode_ids = tuple(row[0] for row in episode_rows)
        validation_rows = await (
            await transaction.execute(
                """SELECT candidate_validation_id
                   FROM armi.cognitive_candidate_validations
                   WHERE cognitive_episode_id=ANY(%s::uuid[])
                   ORDER BY candidate_validation_id""",
                (list(episode_ids),),
            )
        ).fetchall()
        validation_ids = tuple(row[0] for row in validation_rows)
        commit_rows = await (
            await transaction.execute(
                """SELECT DISTINCT application.subject_commit_id
                   FROM armi.cognitive_candidate_applications AS application
                   WHERE application.candidate_validation_id=ANY(%s::uuid[])
                     AND application.subject_commit_id IS NOT NULL
                   ORDER BY application.subject_commit_id""",
                (list(validation_ids),),
            )
        ).fetchall()
        commit_ids = tuple(row[0] for row in commit_rows)
        exact_rows = await (
            await transaction.execute(
                """SELECT exact_life_query_intent_id,result_artifact_id
                   FROM armi.exact_life_query_intents
                   WHERE subject_commit_id=ANY(%s::uuid[])
                      OR creator_party_id=%s
                   ORDER BY exact_life_query_intent_id""",
                (list(commit_ids), request.party_id),
            )
        ).fetchall()
        exact_ids = tuple(row[0] for row in exact_rows)
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
            related_refs=tuple(
                [DataRightsRelatedRef("cognition", ref) for ref in episode_ids]
                + [
                    DataRightsRelatedRef("candidate-validation", ref)
                    for ref in validation_ids
                ]
                + [
                    DataRightsRelatedRef("subject-commit", row[0])
                    for row in commit_rows
                ]
                + [DataRightsRelatedRef("exact-life-query", ref) for ref in exact_ids]
            ),
            targets=tuple(
                DataRightsTargetRef("cognition", ref, "redact") for ref in episode_ids
            )
            + tuple(
                DataRightsTargetRef("cognition", ref, "redact") for ref in exact_ids
            ),
            artifact_usages=tuple(
                [
                    DataRightsArtifactUsage(
                        ArtifactId(row[0]), int(row[1]), int(row[2])
                    )
                    for row in usage_rows
                ]
                + [
                    DataRightsArtifactUsage(ArtifactId(row[1]), 1, 1)
                    for row in exact_rows
                    if row[1] is not None
                ]
            ),
        )

    async def apply(
        self,
        transaction: PostgreSQLTransaction,
        request: DataRightsApplyRequest,
    ) -> DataRightsApplyContribution:
        await transaction.execute(
            """UPDATE armi.cognitive_episodes
               SET status='cancelled',failure_code='DATA-RIGHTS-CANCELLED'
               WHERE context_party_id=%s
                 AND status IN (
                     'preparing','prepared','calling_model','model_returned',
                     'validating','candidate_validated','candidate_rejected',
                     'committing'
                 )
                 AND (
                     %s IN ('stop_use','delete_related')
                     OR purpose IN (
                         'consider_creator_input','consider_other_human_input',
                         'consider_creator_outreach'
                     )
                 )""",
            (request.party_id, request.order_kind),
        )
        if request.order_kind == "delete_related":
            exact_ids = tuple(
                item.ref
                for item in request.related_refs
                if item.kind == "exact-life-query"
            )
            if exact_ids:
                await transaction.execute(
                    """UPDATE armi.exact_life_query_intents SET query_text=NULL
                       WHERE exact_life_query_intent_id=ANY(%s::uuid[])""",
                    (list(exact_ids),),
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


__all__ = ("PostgreSQLCognitionDataRightsParticipant",)
