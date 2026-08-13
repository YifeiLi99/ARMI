"""PostgreSQL resolver and settlement owner for local related-data deletion."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid7

from armi_artifact_store.api import ArtifactCatalogPort
from armi_kernel.application import (
    ArtifactId,
    ArtifactRef,
    AuditDraft,
    AuditEventId,
    AuditReference,
    AuditResultStatus,
    AuditSensitivity,
)
from armi_kernel.contracts import Purpose, TraceId
from armi_runtime_foundation import PostgreSQLRuntimeUnitOfWork
from psycopg import sql

from .api import (
    DataRightsMemoryPort,
    DataRightsProjectionInvalidationPort,
    DataRightsRelationshipPort,
    DataRightsViolation,
)


@dataclass(frozen=True, slots=True)
class DeletionArtifactItem:
    item_id: UUID
    ref: ArtifactRef
    exclusive: bool


class LocalDataDeletionRepository:
    __slots__ = ("_catalog", "_context_projections", "_memories", "_relationships")

    def __init__(
        self,
        memories: DataRightsMemoryPort,
        relationships: DataRightsRelationshipPort,
        context_projections: DataRightsProjectionInvalidationPort,
        catalog: ArtifactCatalogPort,
    ) -> None:
        self._memories = memories
        self._relationships = relationships
        self._context_projections = context_projections
        self._catalog = catalog

    async def pending_order_ids(
        self, unit_of_work: PostgreSQLRuntimeUnitOfWork
    ) -> tuple[UUID, ...]:
        connection = unit_of_work.transaction
        rows = await (
            await connection.execute(
                """
                SELECT deletion_order_id
                FROM armi.deletion_orders
                WHERE order_kind = 'delete_related'
                  AND execution_status IN ('pending', 'executing')
                ORDER BY effective_at, deletion_order_id
                """
            )
        ).fetchall()
        return tuple(row[0] for row in rows)

    async def prepare(
        self,
        unit_of_work: PostgreSQLRuntimeUnitOfWork,
        order_id: UUID,
    ) -> tuple[DeletionArtifactItem, ...]:
        connection = unit_of_work.transaction
        order = await (
            await connection.execute(
                """
                SELECT requester_party_id, execution_status
                FROM armi.deletion_orders
                WHERE deletion_order_id = %s AND order_kind = 'delete_related'
                FOR UPDATE
                """,
                (order_id,),
            )
        ).fetchone()
        if order is None:
            raise DataRightsViolation("DATA-RIGHTS-ORDER-NOT-FOUND")
        party_id = order[0]
        await connection.execute(
            "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
            (f"data-rights:{party_id}",),
        )
        if str(order[1]) in {"completed", "partial"}:
            return ()
        await connection.execute(
            """
            UPDATE armi.deletion_orders
            SET execution_status = 'executing'
            WHERE deletion_order_id = %s
              AND execution_status IN ('pending', 'executing')
            """,
            (order_id,),
        )
        await self._insert_logical_items(connection, order_id, party_id)
        memory_ids = await self._memories.find_for_party(
            unit_of_work.transaction, party_id
        )
        for memory_id in memory_ids:
            await connection.execute(
                """INSERT INTO armi.deletion_items (
                       deletion_item_id,deletion_order_id,target_kind,target_ref,
                       required_action,result_status,completed_at)
                   VALUES (%s,%s,'memory',%s,'tombstone','completed',statement_timestamp())
                   ON CONFLICT (deletion_order_id,target_kind,target_ref) DO NOTHING""",
                (uuid7(), order_id, memory_id),
            )
        await self._context_projections.invalidate(
            unit_of_work.transaction,
            source_kind="subjective_memory",
            source_refs=memory_ids,
        )
        relationship_ids = await self._relationships.find_for_party(
            unit_of_work.transaction, party_id
        )
        for relationship_id in relationship_ids:
            await connection.execute(
                """
                INSERT INTO armi.deletion_items (
                    deletion_item_id, deletion_order_id, target_kind,
                    target_ref, required_action, result_status, completed_at
                ) VALUES (%s, %s, 'relationship', %s, 'tombstone',
                          'completed', statement_timestamp())
                ON CONFLICT (deletion_order_id, target_kind, target_ref) DO NOTHING
                """,
                (uuid7(), order_id, relationship_id),
            )
            await self._relationships.tombstone(
                unit_of_work.transaction,
                relationship_id=relationship_id,
                order_id=order_id,
                tombstoned_at=datetime.now(UTC),
            )
        artifact_ids = await self._related_artifact_ids(connection, party_id)
        reference_columns = await self._artifact_reference_columns(connection)
        items: list[DeletionArtifactItem] = []
        for artifact_id in artifact_ids:
            reference_count = await self._reference_count(
                connection, artifact_id, reference_columns
            )
            exclusive = reference_count == 1
            item_id = uuid7()
            row = await (
                await connection.execute(
                    """
                    INSERT INTO armi.deletion_items (
                        deletion_item_id, deletion_order_id, target_kind,
                        target_ref, required_action, result_status,
                        remaining_location, completed_at
                    ) VALUES (
                        %s, %s, 'artifact', %s, %s, %s, %s,
                        CASE WHEN %s = 'completed' THEN statement_timestamp() END
                    )
                    ON CONFLICT (deletion_order_id, target_kind, target_ref)
                    DO UPDATE SET result_status = armi.deletion_items.result_status
                    RETURNING deletion_item_id, result_status, required_action
                    """,
                    (
                        item_id,
                        order_id,
                        artifact_id,
                        "delete" if exclusive else "retain",
                        "pending" if exclusive else "completed",
                        None if exclusive else "shared_local_reference",
                        "pending" if exclusive else "completed",
                    ),
                )
            ).fetchone()
            if row is not None and str(row[1]) == "pending" and str(row[2]) == "delete":
                ref = await self._catalog.retained_ref(
                    unit_of_work,
                    ArtifactId(artifact_id),
                )
                if ref is not None:
                    items.append(DeletionArtifactItem(row[0], ref, True))
        return tuple(items)

    async def settle_artifact(
        self,
        unit_of_work: PostgreSQLRuntimeUnitOfWork,
        *,
        order_id: UUID,
        item_id: UUID,
        artifact_id: UUID,
        completed: bool,
    ) -> None:
        connection = unit_of_work.transaction
        status = "completed" if completed else "partial"
        remaining = None if completed else "local_artifact_store"
        if completed:
            await self._catalog.mark_deleted(unit_of_work, ArtifactId(artifact_id))
        updated = await (
            await connection.execute(
                """
                UPDATE armi.deletion_items
                SET result_status = %s, remaining_location = %s,
                    completed_at = statement_timestamp()
                WHERE deletion_item_id = %s
                  AND deletion_order_id = %s
                  AND result_status = 'pending'
                RETURNING deletion_item_id
                """,
                (
                    status,
                    remaining,
                    item_id,
                    order_id,
                ),
            )
        ).fetchone()
        if updated is None:
            raise DataRightsViolation("DATA-RIGHTS-ITEM-STATE")

    async def finalize(
        self,
        unit_of_work: PostgreSQLRuntimeUnitOfWork,
        order_id: UUID,
    ) -> None:
        connection = unit_of_work.transaction
        counts = await (
            await connection.execute(
                """
                SELECT count(*) FILTER (WHERE result_status = 'pending'),
                       count(*) FILTER (WHERE result_status IN (
                           'partial', 'too_late', 'unknown'
                       ))
                FROM armi.deletion_items
                WHERE deletion_order_id = %s
                """,
                (order_id,),
            )
        ).fetchone()
        if counts is None or int(counts[0]) != 0:
            return
        final_status = "partial" if int(counts[1]) else "completed"
        finalized = await (
            await connection.execute(
                """
            UPDATE armi.deletion_orders AS deletion_order
            SET execution_status = %s, completed_at = statement_timestamp()
            WHERE deletion_order.deletion_order_id = %s
              AND deletion_order.execution_status = 'executing'
            RETURNING deletion_order.requester_party_id,
                      deletion_order.requester_kind,
                      deletion_order.trace_id,
                      deletion_order.request_digest
                """,
                (final_status, order_id),
            )
        ).fetchone()
        if finalized is None:
            return
        await unit_of_work.audit.append(
            AuditDraft(
                AuditEventId(uuid7()),
                AuditReference(str(finalized[1]), finalized[0]),
                Purpose("data.rights.delete"),
                f"data.rights.delete.{final_status}",
                AuditReference("deletion_order", order_id),
                (
                    AuditResultStatus.COMPLETED
                    if final_status == "completed"
                    else AuditResultStatus.FAILED
                ),
                TraceId(str(finalized[2])),
                AuditSensitivity.RESTRICTED,
            )
        )

    async def _insert_logical_items(
        self,
        connection: Any,
        order_id: UUID,
        party_id: UUID,
    ) -> None:
        await connection.execute(
            """
            WITH targets(target_kind, target_ref, required_action,
                         remaining_location) AS (
                SELECT 'interaction', interaction_id, 'tombstone', NULL
                FROM armi.party_input_interactions WHERE source_party_id = %s
                UNION ALL
                SELECT 'evidence', evidence_id, 'tombstone', NULL
                FROM armi.external_evidence
                WHERE context_party_id = %s
                UNION ALL
                SELECT DISTINCT 'experience', link.experience_id, 'tombstone', NULL
                FROM armi.experience_evidence_links AS link
                JOIN armi.external_evidence AS evidence
                  ON evidence.evidence_id = link.evidence_id
                WHERE evidence.context_party_id = %s
                UNION ALL
                SELECT 'scene', scene_id, 'tombstone', NULL
                FROM armi.interaction_scenes WHERE primary_party_id = %s
                UNION ALL
                SELECT 'effect', effect_id, 'retain', 'objective_history'
                FROM armi.effects
                WHERE context_party_id = %s OR destination_party_id = %s
            )
            INSERT INTO armi.deletion_items (
                deletion_item_id, deletion_order_id, target_kind, target_ref,
                required_action, result_status, remaining_location, completed_at
            )
            SELECT uuidv7(), %s, target_kind, target_ref, required_action,
                   'completed', remaining_location,
                   statement_timestamp()
            FROM targets
            ON CONFLICT (deletion_order_id, target_kind, target_ref) DO NOTHING
            """,
            (party_id,) * 6 + (order_id,),
        )

    async def _related_artifact_ids(
        self, connection: Any, party_id: UUID
    ) -> tuple[UUID, ...]:
        rows = await (
            await connection.execute(
                """
                SELECT artifact_id FROM armi.external_evidence
                WHERE context_party_id = %s
                UNION
                SELECT episode.context_manifest_artifact_id
                FROM armi.cognitive_episodes AS episode
                WHERE episode.context_party_id = %s
                  AND episode.context_manifest_artifact_id IS NOT NULL
                UNION
                SELECT episode.compiled_context_artifact_id
                FROM armi.cognitive_episodes AS episode
                WHERE episode.context_party_id = %s
                  AND episode.compiled_context_artifact_id IS NOT NULL
                UNION
                SELECT attempt.request_artifact_id
                FROM armi.cognitive_attempts AS attempt
                JOIN armi.cognitive_episodes AS episode
                  ON episode.cognitive_episode_id = attempt.cognitive_episode_id
                WHERE episode.context_party_id = %s
                UNION
                SELECT attempt.response_artifact_id
                FROM armi.cognitive_attempts AS attempt
                JOIN armi.cognitive_episodes AS episode
                  ON episode.cognitive_episode_id = attempt.cognitive_episode_id
                WHERE episode.context_party_id = %s
                  AND attempt.response_artifact_id IS NOT NULL
                UNION
                SELECT validation.change_set_artifact_id
                FROM armi.cognitive_candidate_validations AS validation
                JOIN armi.cognitive_episodes AS episode
                  ON episode.cognitive_episode_id = validation.cognitive_episode_id
                WHERE episode.context_party_id = %s
                  AND validation.change_set_artifact_id IS NOT NULL
                UNION
                SELECT revision.response_artifact_id
                FROM armi.action_intent_revisions AS revision
                JOIN armi.action_intents AS intent
                  ON intent.action_intent_id = revision.action_intent_id
                WHERE intent.context_party_id = %s
                UNION
                SELECT part.raw_artifact_id
                FROM armi.external_message_parts AS part
                JOIN armi.party_input_interactions AS interaction
                  ON interaction.interaction_id = part.interaction_id
                WHERE interaction.source_party_id = %s
                  AND part.raw_artifact_id IS NOT NULL
                UNION
                SELECT part.interpretation_artifact_id
                FROM armi.external_message_parts AS part
                JOIN armi.party_input_interactions AS interaction
                  ON interaction.interaction_id = part.interaction_id
                WHERE interaction.source_party_id = %s
                  AND part.interpretation_artifact_id IS NOT NULL
                UNION
                SELECT attempt.request_artifact_id
                FROM armi.external_content_recognition_attempts AS attempt
                JOIN armi.external_message_parts AS part
                  ON part.external_message_part_id = attempt.external_message_part_id
                JOIN armi.party_input_interactions AS interaction
                  ON interaction.interaction_id = part.interaction_id
                WHERE interaction.source_party_id = %s
                UNION
                SELECT attempt.response_artifact_id
                FROM armi.external_content_recognition_attempts AS attempt
                JOIN armi.external_message_parts AS part
                  ON part.external_message_part_id = attempt.external_message_part_id
                JOIN armi.party_input_interactions AS interaction
                  ON interaction.interaction_id = part.interaction_id
                WHERE interaction.source_party_id = %s
                  AND attempt.response_artifact_id IS NOT NULL
                """,
                (party_id,) * 11,
            )
        ).fetchall()
        return tuple(row[0] for row in rows)

    async def _artifact_reference_columns(
        self, connection: Any
    ) -> tuple[tuple[str, str, str], ...]:
        rows = await (
            await connection.execute(
                """
                SELECT namespace.nspname, relation.relname, attribute.attname
                FROM pg_constraint AS constraint_row
                JOIN pg_class AS relation
                  ON relation.oid = constraint_row.conrelid
                JOIN pg_namespace AS namespace
                  ON namespace.oid = relation.relnamespace
                JOIN unnest(constraint_row.conkey) WITH ORDINALITY
                     AS local_key(attnum, ordinal) ON TRUE
                JOIN pg_attribute AS attribute
                  ON attribute.attrelid = relation.oid
                 AND attribute.attnum = local_key.attnum
                JOIN unnest(constraint_row.confkey) WITH ORDINALITY
                     AS foreign_key(attnum, ordinal)
                  ON foreign_key.ordinal = local_key.ordinal
                JOIN pg_attribute AS foreign_attribute
                  ON foreign_attribute.attrelid = constraint_row.confrelid
                 AND foreign_attribute.attnum = foreign_key.attnum
                WHERE constraint_row.contype = 'f'
                  AND constraint_row.confrelid = 'armi.artifacts'::regclass
                  AND foreign_attribute.attname = 'artifact_id'
                ORDER BY namespace.nspname, relation.relname, attribute.attname
                """
            )
        ).fetchall()
        return tuple((str(row[0]), str(row[1]), str(row[2])) for row in rows)

    async def _reference_count(
        self,
        connection: Any,
        artifact_id: UUID,
        columns: tuple[tuple[str, str, str], ...],
    ) -> int:
        count = 0
        for schema_name, table_name, column_name in columns:
            statement = sql.SQL("SELECT count(*) FROM {}.{} WHERE {} = %s").format(
                sql.Identifier(schema_name),
                sql.Identifier(table_name),
                sql.Identifier(column_name),
            )
            row = await (await connection.execute(statement, (artifact_id,))).fetchone()
            count += 0 if row is None else int(row[0])
            if count > 1:
                return count
        return count


__all__ = ("DeletionArtifactItem", "LocalDataDeletionRepository")
