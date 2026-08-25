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
        binding_rows = await (
            await transaction.execute(
                """SELECT external_binding_id FROM armi.external_channel_bindings
                   WHERE party_id=%s ORDER BY external_binding_id""",
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
        bindings = tuple(row[0] for row in binding_rows)
        return DataRightsDiscoveryContribution(
            _OWNER,
            tuple(
                [DataRightsRelatedRef("interaction", ref) for ref in interactions]
                + [DataRightsRelatedRef("scene", ref) for ref in scenes]
                + [DataRightsRelatedRef("external-binding", ref) for ref in bindings]
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
                + [
                    DataRightsTargetRef("external_binding", ref, "redact")
                    for ref in bindings
                ]
                + [DataRightsTargetRef("party", request.party_id, "redact")]
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
        if request.order_kind in {"stop_use", "delete_related"}:
            await transaction.execute(
                """UPDATE armi.party_input_interactions
                   SET data_rights_order_id=%s,
                       data_rights_hidden_at=statement_timestamp()
                   WHERE source_party_id=%s AND data_rights_hidden_at IS NULL""",
                (request.order_id, request.party_id),
            )
            await transaction.execute(
                """UPDATE armi.external_message_parts AS part
                   SET processing_status='unknown',
                       failure_code='DATA-RIGHTS-RECOGNITION-HIDDEN',
                       settled_at=COALESCE(settled_at,statement_timestamp())
                   FROM armi.party_input_interactions AS interaction
                   WHERE part.interaction_id=interaction.interaction_id
                     AND interaction.source_party_id=%s
                     AND part.processing_status='pending'""",
                (request.party_id,),
            )
        if request.order_kind == "delete_related":
            await transaction.execute(
                """UPDATE armi.external_channel_bindings
                   SET external_key=NULL,display_label=NULL,status='rights_only',
                       last_observed_at=statement_timestamp()
                   WHERE party_id=%s AND status='active'""",
                (request.party_id,),
            )
            await transaction.execute(
                """UPDATE armi.parties
                   SET declared_identity_key=NULL,display_label=NULL,status='rights_only'
                   WHERE party_id=%s AND status='active'
                     AND party_kind IN ('creator','other_human')""",
                (request.party_id,),
            )
            await transaction.execute(
                """UPDATE armi.external_message_parts AS part
                   SET interpretation_text=NULL,interpretation_artifact_id=NULL,
                       processing_status='failed',failure_code='DATA-RIGHTS-REDACTED',
                       settled_at=COALESCE(settled_at,statement_timestamp())
                   FROM armi.party_input_interactions AS interaction
                   WHERE part.interaction_id=interaction.interaction_id
                     AND interaction.source_party_id=%s""",
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


__all__ = ("PostgreSQLInteractionDataRightsParticipant",)
