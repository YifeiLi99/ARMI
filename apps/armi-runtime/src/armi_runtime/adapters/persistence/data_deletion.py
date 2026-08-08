"""PostgreSQL resolver and settlement owner for local related-data deletion."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID, uuid7

from armi_kernel.application import (
    ArtifactId,
    ArtifactIntegrityStatus,
    ArtifactPrivacyScope,
    ArtifactRef,
    AuditDraft,
    AuditEventId,
    AuditReference,
    AuditResultStatus,
    AuditSensitivity,
    DataRightsViolation,
)
from armi_kernel.contracts import Digest, Purpose, TraceId
from psycopg import sql

from .unit_of_work import PostgreSQLUnitOfWork


@dataclass(frozen=True, slots=True)
class DeletionArtifactItem:
    item_id: UUID
    ref: ArtifactRef
    exclusive: bool


class LocalDataDeletionRepository:
    __slots__ = ()

    async def pending_order_ids(
        self, unit_of_work: PostgreSQLUnitOfWork
    ) -> tuple[UUID, ...]:
        connection = unit_of_work._connection_for_repository()  # pyright: ignore[reportPrivateUsage]
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
        unit_of_work: PostgreSQLUnitOfWork,
        order_id: UUID,
    ) -> tuple[DeletionArtifactItem, ...]:
        connection = unit_of_work._connection_for_repository()  # pyright: ignore[reportPrivateUsage]
        order = await (
            await connection.execute(
                """
                SELECT requester_party_id, execution_status, request_digest
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
        order_digest = str(order[2])
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
        await self._insert_logical_items(connection, order_id, party_id, order_digest)
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
                        remaining_location, execution_digest, completed_at
                    ) VALUES (
                        %s, %s, 'artifact', %s, %s, %s, %s,
                        CASE WHEN %s = 'completed' THEN %s END,
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
                        order_digest,
                        "pending" if exclusive else "completed",
                    ),
                )
            ).fetchone()
            if row is not None and str(row[1]) == "pending" and str(row[2]) == "delete":
                ref = await self._artifact_ref(connection, artifact_id)
                if ref is not None:
                    items.append(DeletionArtifactItem(row[0], ref, True))
        return tuple(items)

    async def settle_artifact(
        self,
        unit_of_work: PostgreSQLUnitOfWork,
        *,
        order_id: UUID,
        item_id: UUID,
        artifact_id: UUID,
        completed: bool,
    ) -> None:
        connection = unit_of_work._connection_for_repository()  # pyright: ignore[reportPrivateUsage]
        status = "completed" if completed else "partial"
        remaining = None if completed else "local_artifact_store"
        await connection.execute(
            """
            UPDATE armi.artifacts
            SET retention_status = 'deleted', deleted_at = statement_timestamp()
            WHERE artifact_id = %s AND retention_status = 'retained' AND %s
            """,
            (artifact_id, completed),
        )
        execution_digest = Digest.from_bytes(
            f"{status}:{order_id}:{artifact_id}".encode()
        )
        updated = await (
            await connection.execute(
                """
                UPDATE armi.deletion_items
                SET result_status = %s, remaining_location = %s,
                    execution_digest = %s,
                    completed_at = statement_timestamp()
                WHERE deletion_item_id = %s
                  AND deletion_order_id = %s
                  AND result_status = 'pending'
                RETURNING deletion_item_id
                """,
                (
                    status,
                    remaining,
                    execution_digest.value,
                    item_id,
                    order_id,
                ),
            )
        ).fetchone()
        if updated is None:
            raise DataRightsViolation("DATA-RIGHTS-ITEM-STATE")

    async def finalize(
        self,
        unit_of_work: PostgreSQLUnitOfWork,
        order_id: UUID,
    ) -> None:
        connection = unit_of_work._connection_for_repository()  # pyright: ignore[reportPrivateUsage]
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
        completion = Digest.from_bytes(
            f"{final_status}:{order_id}:{int(counts[1])}".encode()
        )
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
                request_digest=Digest(str(finalized[3])),
                response_digest=completion,
            )
        )

    async def _insert_logical_items(
        self,
        connection: Any,
        order_id: UUID,
        party_id: UUID,
        order_digest: str,
    ) -> None:
        await connection.execute(
            """
            WITH targets(target_kind, target_ref, required_action,
                         remaining_location) AS (
                SELECT 'interaction', creator_interaction_id, 'tombstone', NULL
                FROM armi.creator_input_interactions WHERE creator_party_id = %s
                UNION ALL
                SELECT 'interaction', other_human_interaction_id, 'tombstone', NULL
                FROM armi.other_human_input_interactions WHERE other_party_id = %s
                UNION ALL
                SELECT 'evidence', evidence_id, 'tombstone', NULL
                FROM armi.external_evidence
                WHERE COALESCE(other_party_id, creator_party_id) = %s
                UNION ALL
                SELECT DISTINCT 'experience', link.experience_id, 'tombstone', NULL
                FROM armi.experience_evidence_links AS link
                JOIN armi.external_evidence AS evidence
                  ON evidence.evidence_id = link.evidence_id
                WHERE COALESCE(evidence.other_party_id, evidence.creator_party_id) = %s
                UNION ALL
                SELECT DISTINCT 'memory', revision.memory_id, 'tombstone', NULL
                FROM armi.subjective_memory_revisions AS revision
                JOIN armi.experience_evidence_links AS link
                  ON link.experience_id = revision.source_experience_id
                JOIN armi.external_evidence AS evidence
                  ON evidence.evidence_id = link.evidence_id
                WHERE COALESCE(evidence.other_party_id, evidence.creator_party_id) = %s
                UNION ALL
                SELECT 'relationship', relationship_id, 'tombstone', NULL
                FROM armi.relationships WHERE other_party_id = %s
                UNION ALL
                SELECT 'scene', scene_id, 'tombstone', NULL
                FROM armi.interaction_scenes WHERE primary_party_id = %s
                UNION ALL
                SELECT 'effect', effect_id, 'retain', 'objective_history'
                FROM armi.effects WHERE creator_party_id = %s
                UNION ALL
                SELECT 'effect', other_human_effect_id, 'retain', 'objective_history'
                FROM armi.other_human_effects WHERE other_party_id = %s
            )
            INSERT INTO armi.deletion_items (
                deletion_item_id, deletion_order_id, target_kind, target_ref,
                required_action, result_status, remaining_location,
                execution_digest, completed_at
            )
            SELECT uuidv7(), %s, target_kind, target_ref, required_action,
                   'completed', remaining_location,
                   %s,
                   statement_timestamp()
            FROM targets
            ON CONFLICT (deletion_order_id, target_kind, target_ref) DO NOTHING
            """,
            (party_id,) * 9 + (order_id, order_digest),
        )

    async def _related_artifact_ids(
        self, connection: Any, party_id: UUID
    ) -> tuple[UUID, ...]:
        rows = await (
            await connection.execute(
                """
                SELECT artifact_id FROM armi.external_evidence
                WHERE COALESCE(other_party_id, creator_party_id) = %s
                UNION
                SELECT episode.context_manifest_artifact_id
                FROM armi.cognitive_episodes AS episode
                WHERE COALESCE(episode.other_party_id, episode.creator_party_id) = %s
                  AND episode.context_manifest_artifact_id IS NOT NULL
                UNION
                SELECT episode.compiled_context_artifact_id
                FROM armi.cognitive_episodes AS episode
                WHERE COALESCE(episode.other_party_id, episode.creator_party_id) = %s
                  AND episode.compiled_context_artifact_id IS NOT NULL
                UNION
                SELECT attempt.request_artifact_id
                FROM armi.cognitive_attempts AS attempt
                JOIN armi.cognitive_episodes AS episode
                  ON episode.cognitive_episode_id = attempt.cognitive_episode_id
                WHERE COALESCE(episode.other_party_id, episode.creator_party_id) = %s
                UNION
                SELECT attempt.response_artifact_id
                FROM armi.cognitive_attempts AS attempt
                JOIN armi.cognitive_episodes AS episode
                  ON episode.cognitive_episode_id = attempt.cognitive_episode_id
                WHERE COALESCE(episode.other_party_id, episode.creator_party_id) = %s
                  AND attempt.response_artifact_id IS NOT NULL
                UNION
                SELECT validation.change_set_artifact_id
                FROM armi.cognitive_candidate_validations AS validation
                JOIN armi.cognitive_episodes AS episode
                  ON episode.cognitive_episode_id = validation.cognitive_episode_id
                WHERE COALESCE(episode.other_party_id, episode.creator_party_id) = %s
                  AND validation.change_set_artifact_id IS NOT NULL
                UNION
                SELECT revision.response_artifact_id
                FROM armi.action_intent_revisions AS revision
                JOIN armi.action_intents AS intent
                  ON intent.action_intent_id = revision.action_intent_id
                WHERE intent.creator_party_id = %s
                UNION
                SELECT revision.response_artifact_id
                FROM armi.other_human_action_intent_revisions AS revision
                JOIN armi.other_human_action_intents AS intent
                  ON intent.other_human_action_intent_id =
                     revision.other_human_action_intent_id
                WHERE intent.other_party_id = %s
                """,
                (party_id,) * 8,
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

    async def _artifact_ref(
        self, connection: Any, artifact_id: UUID
    ) -> ArtifactRef | None:
        row = await (
            await connection.execute(
                """
                SELECT artifact_id, content_digest, byte_size, media_type,
                       logical_kind, privacy_scope, integrity_status
                FROM armi.artifacts
                WHERE artifact_id = %s AND retention_status = 'retained'
                """,
                (artifact_id,),
            )
        ).fetchone()
        if row is None:
            return None
        return ArtifactRef(
            ArtifactId(row[0]),
            Digest(str(row[1])),
            int(row[2]),
            str(row[3]),
            str(row[4]),
            ArtifactPrivacyScope(str(row[5])),
            ArtifactIntegrityStatus(str(row[6])),
            1,
        )


__all__ = ("DeletionArtifactItem", "LocalDataDeletionRepository")
