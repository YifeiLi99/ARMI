"""Data Rights ledger owner and fixed participant coordinator."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID, uuid7

from armi_artifact_store.api import ArtifactCatalogPort, ArtifactLifecyclePort
from armi_kernel.application import (
    ArtifactId,
    AuditDraft,
    AuditEventId,
    AuditReference,
    AuditResultStatus,
    AuditSensitivity,
)
from armi_kernel.contracts import Purpose, TraceId
from armi_runtime_foundation import PostgreSQLRuntimeUnitOfWork, PostgreSQLTransaction

from .api import (
    DataRightsApplyRequest,
    DataRightsDiscoveryRequest,
    DataRightsParticipant,
    DataRightsParticipantViolation,
    DataRightsRelatedRef,
    DataRightsTargetRef,
    DataRightsViolation,
)


@dataclass(frozen=True, slots=True)
class DeletionArtifactItem:
    item_id: UUID
    artifact_id: UUID
    deletion_id: UUID


class LocalDataDeletionRepository:
    __slots__ = ("_catalog", "_lifecycle", "_participants")

    def __init__(
        self,
        catalog: ArtifactCatalogPort,
        lifecycle: ArtifactLifecyclePort,
        participants: tuple[DataRightsParticipant, ...],
    ) -> None:
        self._catalog = catalog
        self._lifecycle = lifecycle
        self._participants = participants

    async def pending_order_ids(
        self, unit_of_work: PostgreSQLRuntimeUnitOfWork
    ) -> tuple[UUID, ...]:
        rows = await (
            await unit_of_work.transaction.execute(
                """SELECT deletion_order_id FROM armi.deletion_orders
                   WHERE order_kind = 'delete_related'
                     AND execution_status IN ('pending', 'executing')
                   ORDER BY effective_at, deletion_order_id"""
            )
        ).fetchall()
        return tuple(row[0] for row in rows)

    async def prepare(
        self,
        unit_of_work: PostgreSQLRuntimeUnitOfWork,
        order_id: UUID,
    ) -> tuple[DeletionArtifactItem, ...]:
        transaction = unit_of_work.transaction
        order = await (
            await transaction.execute(
                """SELECT requester_party_id, execution_status
                   FROM armi.deletion_orders
                   WHERE deletion_order_id = %s AND order_kind = 'delete_related'
                   FOR UPDATE""",
                (order_id,),
            )
        ).fetchone()
        if order is None:
            raise DataRightsViolation("DATA-RIGHTS-ORDER-NOT-FOUND")
        party_id = order[0]
        await transaction.execute(
            "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
            (f"data-rights:{party_id}",),
        )
        if str(order[1]) in {"completed", "partial"}:
            return ()
        existing_items = await (
            await transaction.execute(
                """SELECT deletion_item_id,target_ref,artifact_object_deletion_id
                   FROM armi.deletion_items
                   WHERE deletion_order_id = %s
                     AND target_kind = 'artifact'
                     AND required_action = 'delete'
                     AND result_status = 'pending'
                   ORDER BY deletion_item_id""",
                (order_id,),
            )
        ).fetchall()
        item_count = await (
            await transaction.execute(
                """SELECT count(*) FROM armi.deletion_items
                   WHERE deletion_order_id = %s""",
                (order_id,),
            )
        ).fetchone()
        if item_count is None:
            raise DataRightsViolation("DATA-RIGHTS-ITEM-STATE")
        if int(item_count[0]) > 0:
            pending: list[DeletionArtifactItem] = []
            for item_id, artifact_id, deletion_id in existing_items:
                if deletion_id is not None:
                    pending.append(
                        DeletionArtifactItem(item_id, artifact_id, deletion_id)
                    )
            return tuple(pending)
        await transaction.execute(
            """UPDATE armi.deletion_orders SET execution_status = 'executing'
               WHERE deletion_order_id = %s
                 AND execution_status IN ('pending', 'executing')""",
            (order_id,),
        )

        related: list[DataRightsRelatedRef] = []
        targets: dict[tuple[str, UUID], DataRightsTargetRef] = {}
        usages: dict[UUID, tuple[int, int]] = {}
        for participant in self._participants:
            contribution = await participant.discover(
                transaction,
                DataRightsDiscoveryRequest(order_id, party_id, tuple(related)),
            )
            if contribution.owner_identity != participant.owner_identity:
                raise DataRightsParticipantViolation(
                    "DATA-RIGHTS-PARTICIPANT-OWNER-MISMATCH"
                )
            for item in contribution.related_refs:
                if item not in related:
                    related.append(item)
            for target in contribution.targets:
                key = (target.kind, target.ref)
                existing = targets.get(key)
                if existing is not None and existing != target:
                    raise DataRightsParticipantViolation(
                        "DATA-RIGHTS-PARTICIPANT-TARGET-CONFLICT"
                    )
                targets[key] = target
            for usage in contribution.artifact_usages:
                current = usages.get(usage.artifact_id.value, (0, 0))
                usages[usage.artifact_id.value] = (
                    current[0] + usage.total_reference_count,
                    current[1] + usage.target_party_reference_count,
                )

        exclusive_ids = tuple(
            ArtifactId(artifact_id)
            for artifact_id, (total, target) in usages.items()
            if total > 0 and total == target
        )
        apply_request = DataRightsApplyRequest(
            order_id,
            party_id,
            tuple(related),
            tuple(targets.values()),
            exclusive_ids,
        )
        for participant in self._participants:
            contribution = await participant.apply(transaction, apply_request)
            if contribution.owner_identity != participant.owner_identity:
                raise DataRightsParticipantViolation(
                    "DATA-RIGHTS-PARTICIPANT-OWNER-MISMATCH"
                )

        for target in targets.values():
            await self._insert_target(transaction, order_id, target)

        artifact_items: list[DeletionArtifactItem] = []
        for artifact_id, (total, target_count) in sorted(
            usages.items(), key=lambda item: str(item[0])
        ):
            exclusive = total > 0 and total == target_count
            target = DataRightsTargetRef(
                "artifact",
                artifact_id,
                "delete" if exclusive else "retain",
                None if exclusive else "shared_local_reference",
            )
            item_id = await self._insert_target(transaction, order_id, target)
            if exclusive:
                ref = await self._catalog.retained_ref(
                    unit_of_work, ArtifactId(artifact_id)
                )
                if ref is not None:
                    retirement = await self._catalog.retire_artifact(
                        unit_of_work, ArtifactId(artifact_id)
                    )
                    if retirement.shared_local_reference:
                        await transaction.execute(
                            """UPDATE armi.deletion_items
                               SET result_status='completed',
                                   remaining_location='shared_local_reference',
                                   completed_at=statement_timestamp()
                               WHERE deletion_item_id=%s""",
                            (item_id,),
                        )
                    elif retirement.deletion_id is not None:
                        await transaction.execute(
                            """UPDATE armi.deletion_items
                               SET artifact_object_deletion_id=%s
                               WHERE deletion_item_id=%s""",
                            (retirement.deletion_id, item_id),
                        )
                        artifact_items.append(
                            DeletionArtifactItem(
                                item_id, artifact_id, retirement.deletion_id
                            )
                        )
                else:
                    await transaction.execute(
                        """UPDATE armi.deletion_items
                           SET result_status='completed',completed_at=statement_timestamp()
                           WHERE deletion_item_id=%s""",
                        (item_id,),
                    )
        return tuple(artifact_items)

    async def _insert_target(
        self,
        transaction: PostgreSQLTransaction,
        order_id: UUID,
        target: DataRightsTargetRef,
    ) -> UUID:
        item_id = uuid7()
        pending = target.kind == "artifact" and target.required_action == "delete"
        row = await (
            await transaction.execute(
                """INSERT INTO armi.deletion_items (
                     deletion_item_id, deletion_order_id, target_kind, target_ref,
                     required_action, result_status, remaining_location, completed_at
                   ) VALUES (%s,%s,%s,%s,%s,%s,%s,
                     CASE WHEN %s = 'completed' THEN statement_timestamp() END)
                   ON CONFLICT (deletion_order_id,target_kind,target_ref)
                   DO UPDATE SET result_status = armi.deletion_items.result_status
                   RETURNING deletion_item_id""",
                (
                    item_id,
                    order_id,
                    target.kind,
                    target.ref,
                    target.required_action,
                    "pending" if pending else "completed",
                    target.remaining_location,
                    "pending" if pending else "completed",
                ),
            )
        ).fetchone()
        if row is None:
            raise DataRightsViolation("DATA-RIGHTS-ITEM-STATE")
        return row[0]

    async def reconcile_artifacts(
        self,
        unit_of_work: PostgreSQLRuntimeUnitOfWork,
        *,
        order_id: UUID,
    ) -> None:
        rows = await (
            await unit_of_work.transaction.execute(
                """SELECT artifact_object_deletion_id FROM armi.deletion_items
                   WHERE deletion_order_id=%s AND result_status='pending'
                     AND artifact_object_deletion_id IS NOT NULL""",
                (order_id,),
            )
        ).fetchall()
        deletion_ids = tuple(row[0] for row in rows)
        states = await self._lifecycle.deletion_states(
            unit_of_work.transaction, deletion_ids
        )
        for state in states:
            if state.status not in {"completed", "cancelled", "blocked"}:
                continue
            blocked = state.status == "blocked"
            await unit_of_work.transaction.execute(
                """UPDATE armi.deletion_items
                   SET result_status=%s,remaining_location=%s,
                       completed_at=statement_timestamp()
                   WHERE deletion_order_id=%s AND result_status='pending'
                     AND artifact_object_deletion_id=%s""",
                (
                    "partial" if blocked else "completed",
                    "local_artifact_store" if blocked else None,
                    order_id,
                    state.deletion_id,
                ),
            )

    async def finalize(
        self,
        unit_of_work: PostgreSQLRuntimeUnitOfWork,
        order_id: UUID,
    ) -> None:
        transaction = unit_of_work.transaction
        counts = await (
            await transaction.execute(
                """SELECT count(*) FILTER (WHERE result_status = 'pending'),
                          count(*) FILTER (WHERE result_status IN
                            ('partial','too_late','unknown'))
                   FROM armi.deletion_items WHERE deletion_order_id = %s""",
                (order_id,),
            )
        ).fetchone()
        if counts is None or int(counts[0]) != 0:
            return
        final_status = "partial" if int(counts[1]) else "completed"
        row = await (
            await transaction.execute(
                """UPDATE armi.deletion_orders
                   SET execution_status = %s, completed_at = statement_timestamp()
                   WHERE deletion_order_id = %s AND execution_status = 'executing'
                   RETURNING requester_party_id, requester_kind, trace_id""",
                (final_status, order_id),
            )
        ).fetchone()
        if row is None:
            return
        await unit_of_work.audit.append(
            AuditDraft(
                AuditEventId(uuid7()),
                AuditReference(str(row[1]), row[0]),
                Purpose("data.rights.delete"),
                f"data.rights.delete.{final_status}",
                AuditReference("deletion_order", order_id),
                AuditResultStatus.COMPLETED
                if final_status == "completed"
                else AuditResultStatus.FAILED,
                TraceId(str(row[2])),
                AuditSensitivity.RESTRICTED,
            )
        )


__all__ = ("DeletionArtifactItem", "LocalDataDeletionRepository")
