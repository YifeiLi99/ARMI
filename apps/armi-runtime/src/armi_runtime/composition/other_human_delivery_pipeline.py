"""Durable built-in delivery to the process-local other-human inbox."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any
from uuid import UUID, uuid7

import rfc8785
from armi_kernel.application import (
    AuditDraft,
    AuditEventId,
    AuditReference,
    AuditResultStatus,
    AuditSensitivity,
    LockPlan,
    LockTarget,
    RuntimeFence,
    WorkLease,
    WorkResultRef,
    WorkViolation,
)
from armi_kernel.contracts import Digest, Purpose, SubjectId, TraceId

from armi_runtime.adapters.persistence.durable_work import (
    PostgreSQLDurableWorkGateway,
)
from armi_runtime.adapters.persistence.unit_of_work import PostgreSQLUnitOfWorkFactory
from armi_runtime.adapters.transaction_errors import DatabaseTransactionError

from .work_wakeup import OTHER_HUMAN_DELIVER, WorkWakeupBus

_WORK_KIND = "effect.other-human-local.deliver"
Diagnostic = Callable[[str], None]
FaultInjector = Callable[[str], None]


def _ignore_diagnostic(_event: str) -> None:
    return None


class OtherHumanDeliveryPipeline:
    """Turn one registered effect into a local receipt and scene timeline item."""

    __slots__ = (
        "_diagnostic",
        "_factory",
        "_fault_injector",
        "_lease_owner",
        "_stop",
        "_wakeups",
        "_work",
    )

    def __init__(
        self,
        *,
        factory: PostgreSQLUnitOfWorkFactory,
        wakeups: WorkWakeupBus | None = None,
        diagnostic: Diagnostic | None = None,
        fault_injector: FaultInjector | None = None,
    ) -> None:
        self._factory = factory
        self._work = PostgreSQLDurableWorkGateway(factory)
        self._wakeups = wakeups or WorkWakeupBus()
        self._lease_owner = uuid7()
        self._stop = asyncio.Event()
        self._diagnostic = diagnostic or _ignore_diagnostic
        self._fault_injector = fault_injector or _ignore_diagnostic

    async def open(self) -> None:
        await self._factory.open()

    async def close(self) -> None:
        self._stop.set()
        await self._factory.close()

    def stop(self) -> None:
        self._stop.set()

    async def deliver_once(self) -> bool:
        try:
            records = await self._work.claim(
                work_kind=_WORK_KIND,
                lease_owner=self._lease_owner,
                lease_seconds=30,
                limit=1,
            )
        except WorkViolation:
            return False
        if not records:
            return False
        lease = records[0].lease
        assert lease is not None
        try:
            async with self._factory.unit_of_work(LockPlan()) as unit:
                connection = unit._connection_for_repository()  # pyright: ignore[reportPrivateUsage]
                row = await (
                    await connection.execute(
                        """
                        SELECT effect.other_human_effect_id, effect.subject_id,
                               effect.scene_id, effect.other_party_id,
                               effect.payload_artifact_id, effect.payload_digest,
                               effect.registration_digest, work.trace_id,
                               EXISTS (
                                   SELECT 1
                                   FROM armi.relationships AS relationship
                                   JOIN armi.relationship_revisions AS revision
                                     ON revision.relationship_revision_id =
                                        relationship.current_revision_id
                                   WHERE relationship.subject_id = effect.subject_id
                                     AND relationship.other_party_id =
                                         effect.other_party_id
                                     AND relationship.scope = 'other_human_social'
                                     AND (
                                         revision.relationship_status = 'ended'
                                         OR EXISTS (
                                             SELECT 1
                                             FROM jsonb_array_elements(
                                                 revision.boundaries
                                             ) AS boundary
                                             WHERE boundary->>'kind' IN (
                                                 'contact', 'exit'
                                             )
                                         )
                                     )
                               ) AS contact_blocked
                        FROM armi.durable_work AS work
                        JOIN armi.other_human_effects AS effect
                          ON effect.other_human_effect_id = work.owner_ref
                        WHERE work.work_id = %s
                          AND work.work_kind = %s
                          AND work.owner_kind = 'other_human_effect'
                          AND work.status = 'leased'
                          AND work.current_attempt_id = %s
                          AND work.lease_owner = %s
                          AND work.lease_token = %s
                          AND work.lease_expires_at > statement_timestamp()
                          AND effect.status = 'registered'
                        FOR UPDATE OF work, effect
                        """,
                        (
                            lease.work_id.value,
                            _WORK_KIND,
                            lease.attempt_id.value,
                            lease.owner,
                            lease.token,
                        ),
                    )
                ).fetchone()
                if row is None:
                    return True
                if bool(row[8]):
                    settlement = Digest.from_bytes(
                        rfc8785.dumps(
                            {
                                "effect_id": str(row[0]),
                                "registration_digest": str(row[6]),
                                "status": "failed",
                                "reason": "relationship_boundary",
                            }
                        )
                    )
                    await connection.execute(
                        """
                        UPDATE armi.other_human_effects
                        SET status = 'failed', settlement_digest = %s,
                            settled_at = statement_timestamp()
                        WHERE other_human_effect_id = %s AND status = 'registered'
                        """,
                        (settlement.value, row[0]),
                    )
                    await connection.execute(
                        """
                        INSERT INTO armi.scene_timeline_items (
                            timeline_item_id, scene_id, source_kind, source_ref,
                            source_event_no, result_status, occurred_at, schema_version
                        ) VALUES (%s, %s, 'other_human_response', %s, 1,
                                  'failed', statement_timestamp(), 1)
                        """,
                        (uuid7(), row[2], row[0]),
                    )
                    await unit.work.complete(
                        lease,
                        WorkResultRef("other_human_effect", row[0]),
                    )
                    await unit.audit.append(
                        AuditDraft(
                            AuditEventId(uuid7()),
                            AuditReference("runtime", unit.environment_id),
                            Purpose("other_human.local_delivery"),
                            "other_human.delivery.relationship_boundary",
                            AuditReference("other_human_effect", row[0]),
                            AuditResultStatus.REJECTED,
                            TraceId(str(row[7])),
                            AuditSensitivity.PRIVATE,
                            subject_id=SubjectId(row[1]),
                            request_digest=Digest(str(row[6])),
                            response_digest=settlement,
                        )
                    )
                    return True
                self._fault_injector("before_local_delivery")
                receipt_digest = Digest.from_bytes(
                    rfc8785.dumps(
                        {
                            "effect_id": str(row[0]),
                            "scene_id": str(row[2]),
                            "other_party_id": str(row[3]),
                            "payload_digest": str(row[5]),
                            "receiver": "process_local_inbox",
                        }
                    )
                )
                delivery_id = uuid7()
                await connection.execute(
                    """
                    INSERT INTO armi.other_human_local_inbox_deliveries (
                        other_human_local_inbox_delivery_id, other_human_effect_id,
                        scene_id, other_party_id, payload_artifact_id,
                        payload_digest, receipt_digest, schema_version
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, 1)
                    """,
                    (delivery_id, row[0], row[2], row[3], row[4], row[5], receipt_digest.value),
                )
                await connection.execute(
                    """
                    UPDATE armi.other_human_effects
                    SET status = 'completed', settlement_digest = %s,
                        settled_at = statement_timestamp()
                    WHERE other_human_effect_id = %s AND status = 'registered'
                    """,
                    (receipt_digest.value, row[0]),
                )
                await connection.execute(
                    """
                    INSERT INTO armi.scene_timeline_items (
                        timeline_item_id, scene_id, source_kind, source_ref,
                        source_event_no, result_status, occurred_at, schema_version
                    ) VALUES (%s, %s, 'other_human_response', %s, 1,
                              'completed', statement_timestamp(), 1)
                    """,
                    (uuid7(), row[2], row[0]),
                )
                await unit.work.complete(
                    lease,
                    WorkResultRef("other_human_local_delivery", delivery_id),
                )
                await unit.audit.append(
                    AuditDraft(
                        AuditEventId(uuid7()),
                        AuditReference("runtime", unit.environment_id),
                        Purpose("other_human.local_delivery"),
                        "other_human.delivery.completed",
                        AuditReference("other_human_effect", row[0]),
                        AuditResultStatus.COMPLETED,
                        TraceId(str(row[7])),
                        AuditSensitivity.PRIVATE,
                        subject_id=SubjectId(row[1]),
                        request_digest=Digest(str(row[6])),
                        response_digest=receipt_digest,
                    )
                )
            return True
        except TimeoutError:
            await self._settle_delivery_failure(lease, status="unknown")
            return True
        except OSError:
            await self._settle_delivery_failure(lease, status="failed")
            return True
        except DatabaseTransactionError, WorkViolation:
            self._diagnostic("other_human.delivery.transient_failure")
            return True

    async def _settle_delivery_failure(self, lease: WorkLease, *, status: str) -> None:
        if status not in {"failed", "unknown"}:
            return
        try:
            async with self._factory.unit_of_work(LockPlan()) as unit:
                connection = unit._connection_for_repository()  # pyright: ignore[reportPrivateUsage]
                row = await (
                    await connection.execute(
                        """
                        SELECT effect.other_human_effect_id, effect.scene_id,
                               effect.registration_digest
                        FROM armi.durable_work AS work
                        JOIN armi.other_human_effects AS effect
                          ON effect.other_human_effect_id = work.owner_ref
                        WHERE work.work_id = %s AND work.status = 'leased'
                          AND work.current_attempt_id = %s
                          AND work.lease_owner = %s AND work.lease_token = %s
                          AND effect.status = 'registered'
                        FOR UPDATE OF work, effect
                        """,
                        (
                            lease.work_id.value,
                            lease.attempt_id.value,
                            lease.owner,
                            lease.token,
                        ),
                    )
                ).fetchone()
                if row is None:
                    return
                settlement = Digest.from_bytes(
                    rfc8785.dumps(
                        {
                            "effect_id": str(row[0]),
                            "registration_digest": str(row[2]),
                            "status": status,
                        }
                    )
                )
                await connection.execute(
                    """
                    UPDATE armi.other_human_effects
                    SET status = %s, settlement_digest = %s,
                        settled_at = statement_timestamp()
                    WHERE other_human_effect_id = %s AND status = 'registered'
                    """,
                    (status, settlement.value, row[0]),
                )
                await connection.execute(
                    """
                    INSERT INTO armi.scene_timeline_items (
                        timeline_item_id, scene_id, source_kind, source_ref,
                        source_event_no, result_status, occurred_at, schema_version
                    ) VALUES (%s, %s, 'other_human_response', %s, 1,
                              %s, statement_timestamp(), 1)
                    """,
                    (uuid7(), row[1], row[0], status),
                )
                await unit.work.complete(
                    lease,
                    WorkResultRef("other_human_effect", row[0]),
                )
        except DatabaseTransactionError, WorkViolation:
            self._diagnostic("other_human.delivery.failure_settlement_deferred")

    async def run_worker(self) -> None:
        observed = self._wakeups.version(OTHER_HUMAN_DELIVER)
        while not self._stop.is_set():
            worked = await self.deliver_once()
            if worked:
                await asyncio.sleep(0)
                continue
            observed = await self._wakeups.wait(
                OTHER_HUMAN_DELIVER,
                observed,
                stop=self._stop,
                timeout_seconds=1,
            )


def build_other_human_delivery_pipeline(
    conninfo: str,
    *,
    environment_id: UUID,
    pool_min: int,
    pool_max: int,
    acquire_timeout_seconds: int,
    statement_timeout_seconds: int,
    authority_admission: Callable[[], RuntimeFence],
    wakeups: WorkWakeupBus | None = None,
    diagnostic: Diagnostic | None = None,
    fault_injector: FaultInjector | None = None,
) -> OtherHumanDeliveryPipeline:
    async def reject_dynamic_lock(connection: Any, target: LockTarget) -> None:
        del connection, target
        raise WorkViolation("WORK-LOCK")

    return OtherHumanDeliveryPipeline(
        factory=PostgreSQLUnitOfWorkFactory(
            conninfo,
            environment_id=environment_id,
            lock_acquirer=reject_dynamic_lock,
            pool_min=pool_min,
            pool_max=pool_max,
            acquire_timeout_seconds=acquire_timeout_seconds,
            statement_timeout_seconds=statement_timeout_seconds,
            authority_admission=authority_admission,
        ),
        wakeups=wakeups,
        diagnostic=diagnostic,
        fault_injector=fault_injector,
    )


__all__ = (
    "OtherHumanDeliveryPipeline",
    "build_other_human_delivery_pipeline",
)
