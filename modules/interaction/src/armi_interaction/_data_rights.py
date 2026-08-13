"""Data-rights participant owned by the interaction module."""

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

_OWNER = DataRightsOwnerIdentity("interaction")
_VERSION = DataRightsContributionVersion(1)
_SEGMENTS: tuple[tuple[str, LiteralString], ...] = (
    (
        "external_channel_bindings",
        """SELECT convert_to(to_jsonb(source)::text || chr(10), 'UTF8')
           FROM armi.external_channel_bindings AS source ORDER BY to_jsonb(source)::text""",
    ),
    (
        "external_message_parts",
        """SELECT convert_to(to_jsonb(source)::text || chr(10), 'UTF8')
           FROM armi.external_message_parts AS source ORDER BY to_jsonb(source)::text""",
    ),
    (
        "interaction_scenes",
        """SELECT convert_to(to_jsonb(source)::text || chr(10), 'UTF8')
           FROM armi.interaction_scenes AS source ORDER BY to_jsonb(source)::text""",
    ),
    (
        "parties",
        """SELECT convert_to(to_jsonb(source)::text || chr(10), 'UTF8')
           FROM armi.parties AS source ORDER BY to_jsonb(source)::text""",
    ),
    (
        "party_input_interactions",
        """SELECT convert_to(to_jsonb(source)::text || chr(10), 'UTF8')
           FROM armi.party_input_interactions AS source ORDER BY to_jsonb(source)::text""",
    ),
    (
        "scene_participants",
        """SELECT convert_to(to_jsonb(source)::text || chr(10), 'UTF8')
           FROM armi.scene_participants AS source ORDER BY to_jsonb(source)::text""",
    ),
    (
        "scene_timeline_items",
        """SELECT convert_to(to_jsonb(source)::text || chr(10), 'UTF8')
           FROM armi.scene_timeline_items AS source ORDER BY to_jsonb(source)::text""",
    ),
)


class PostgreSQLInteractionDataRightsParticipant:
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
        interaction_rows = await (
            await transaction.execute(
                """SELECT interaction_id FROM armi.party_input_interactions
                   WHERE source_party_id = %s ORDER BY interaction_id""",
                (request.party_id,),
            )
        ).fetchall()
        scene_rows = await (
            await transaction.execute(
                """SELECT scene_id FROM armi.interaction_scenes
                   WHERE primary_party_id = %s ORDER BY scene_id""",
                (request.party_id,),
            )
        ).fetchall()
        part_rows = await (
            await transaction.execute(
                """SELECT part.external_message_part_id
                   FROM armi.external_message_parts AS part
                   JOIN armi.party_input_interactions AS interaction
                     ON interaction.interaction_id = part.interaction_id
                   WHERE interaction.source_party_id = %s
                   ORDER BY part.external_message_part_id""",
                (request.party_id,),
            )
        ).fetchall()
        usage_rows = await (
            await transaction.execute(
                """WITH refs AS (
                     SELECT raw_artifact_id AS artifact_id, interaction_id
                     FROM armi.external_message_parts WHERE raw_artifact_id IS NOT NULL
                     UNION ALL
                     SELECT interpretation_artifact_id, interaction_id
                     FROM armi.external_message_parts
                     WHERE interpretation_artifact_id IS NOT NULL
                   )
                   SELECT refs.artifact_id, count(*),
                          count(*) FILTER (WHERE interaction.source_party_id = %s)
                   FROM refs
                   JOIN armi.party_input_interactions AS interaction
                     ON interaction.interaction_id = refs.interaction_id
                   GROUP BY refs.artifact_id ORDER BY refs.artifact_id""",
                (request.party_id,),
            )
        ).fetchall()
        interactions = tuple(row[0] for row in interaction_rows)
        scenes = tuple(row[0] for row in scene_rows)
        return DataRightsDiscoveryContribution(
            _OWNER,
            tuple(
                [DataRightsRelatedRef("interaction", ref) for ref in interactions]
                + [DataRightsRelatedRef("scene", ref) for ref in scenes]
                + [
                    DataRightsRelatedRef("external-message-part", row[0])
                    for row in part_rows
                ]
            ),
            tuple(
                [
                    DataRightsTargetRef("interaction", ref, "tombstone")
                    for ref in interactions
                ]
                + [DataRightsTargetRef("scene", ref, "tombstone") for ref in scenes]
            ),
            tuple(
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


__all__ = ("PostgreSQLInteractionDataRightsParticipant",)
