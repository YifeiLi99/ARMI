"""Precisely bounded Admin maintenance for Runtime/Foundation-owned facts."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import cast
from uuid import UUID

from armi_runtime_foundation import PostgreSQLAdminTransaction


@dataclass(frozen=True, slots=True)
class RuntimeAdminEnvironment:
    environment_id: str
    environment_kind: str
    incarnation: int
    resettable: bool
    test_controls_enabled: bool
    registered_at: datetime


@dataclass(frozen=True, slots=True)
class RuntimeAdminSubject:
    subject_id: UUID
    subject_version: int
    state_epoch: int
    generation_id: UUID
    status: str | None = None
    bundle_activation_id: UUID | None = None


@dataclass(frozen=True, slots=True)
class RuntimeAdminWork:
    work_id: UUID
    status: str
    lease_token: int
    attempt_count: int
    max_attempts: int
    deadline_at: datetime
    lease_expires_at: datetime | None
    runtime_status: str | None
    owner_ref: UUID


class RuntimeFoundationAdminAdapter:
    __slots__ = ("_environment_id", "_incarnation")

    def __init__(self, *, environment_id: str, incarnation: int) -> None:
        self._environment_id = environment_id
        self._incarnation = incarnation

    def authority_lock(self, transaction: PostgreSQLAdminTransaction) -> None:
        transaction.execute(
            "SELECT pg_catalog.pg_advisory_xact_lock(pg_catalog.hashtextextended(%s,0))",
            ("armi.runtime-authority:" + self._environment_id,),
        )

    def diagnostics(self, transaction: PostgreSQLAdminTransaction) -> dict[str, object]:
        work = transaction.execute(
            "SELECT status,count(*),count(*) FILTER (WHERE lease_expires_at < clock_timestamp()),count(*) FILTER (WHERE deadline_at < clock_timestamp()) FROM armi.durable_work GROUP BY status ORDER BY status"
        ).fetchall()
        recovery = transaction.execute(
            "SELECT recovery_run_id,status,blocker_count,started_at,completed_at FROM armi.runtime_recovery_runs ORDER BY started_at DESC,recovery_run_id DESC LIMIT 1"
        ).fetchone()
        leases = transaction.execute(
            "SELECT runtime_instance_id,status,lease_expires_at,last_heartbeat_at FROM armi.runtime_instances WHERE status='active' ORDER BY runtime_instance_id LIMIT 2"
        ).fetchall()
        return {
            "work": [
                {
                    "status": str(row[0]),
                    "count": row[1],
                    "expired_leases": row[2],
                    "past_deadline": row[3],
                }
                for row in work
            ],
            "recovery": None
            if recovery is None
            else {
                "recovery_run_id": recovery[0],
                "status": recovery[1],
                "blocker_count": recovery[2],
                "started_at": recovery[3],
                "completed_at": recovery[4],
            },
            "active_leases": [
                {
                    "runtime_instance_id": row[0],
                    "status": row[1],
                    "lease_expires_at": row[2],
                    "last_heartbeat_at": row[3],
                }
                for row in leases
            ],
        }

    def environment(
        self, transaction: PostgreSQLAdminTransaction
    ) -> RuntimeAdminEnvironment | None:
        row = transaction.execute(
            "SELECT environment_id,environment_kind,incarnation,resettable,test_controls_enabled,registered_at FROM armi.deployment_environments WHERE singleton_key"
        ).fetchone()
        return (
            None
            if row is None
            else RuntimeAdminEnvironment(
                str(row[0]),
                str(row[1]),
                int(cast(int, row[2])),
                bool(row[3]),
                bool(row[4]),
                cast(datetime, row[5]),
            )
        )

    def register_environment(
        self,
        transaction: PostgreSQLAdminTransaction,
        *,
        environment_id: str,
        environment_kind: str,
        incarnation: int,
        resettable: bool,
        test_controls_enabled: bool,
    ) -> None:
        transaction.execute(
            "INSERT INTO armi.deployment_environments (singleton_key,environment_id,environment_kind,incarnation,resettable,test_controls_enabled) VALUES (true,%s,%s,%s,%s,%s)",
            (
                environment_id,
                environment_kind,
                incarnation,
                resettable,
                test_controls_enabled,
            ),
        )

    def latest_runtime(
        self, transaction: PostgreSQLAdminTransaction
    ) -> tuple[object, ...] | None:
        return transaction.execute(
            "SELECT runtime_instance_id,life_generation_id,fence_token,status,last_heartbeat_at,lease_expires_at FROM armi.runtime_instances ORDER BY started_at DESC,runtime_instance_id DESC LIMIT 1"
        ).fetchone()

    def subject(
        self,
        transaction: PostgreSQLAdminTransaction,
        *,
        for_update: bool,
        detailed: bool = False,
    ) -> RuntimeAdminSubject | None:
        if detailed:
            row = transaction.execute(
                "SELECT subject_id,subject_version,state_epoch,current_generation_id,status,current_bundle_activation_id FROM armi.subjects WHERE singleton_key=1"
                + (" FOR UPDATE" if for_update else "")
            ).fetchone()
            return (
                None
                if row is None
                else RuntimeAdminSubject(
                    cast(UUID, row[0]),
                    int(cast(int, row[1])),
                    int(cast(int, row[2])),
                    cast(UUID, row[3]),
                    str(row[4]),
                    cast(UUID | None, row[5]),
                )
            )
        row = transaction.execute(
            "SELECT subject_id,subject_version,state_epoch,current_generation_id FROM armi.subjects WHERE singleton_key=1"
            + (" FOR UPDATE" if for_update else "")
        ).fetchone()
        return (
            None
            if row is None
            else RuntimeAdminSubject(
                cast(UUID, row[0]),
                int(cast(int, row[1])),
                int(cast(int, row[2])),
                cast(UUID, row[3]),
            )
        )

    def validate_generation(
        self, transaction: PostgreSQLAdminTransaction, generation_id: UUID
    ) -> bool:
        return (
            transaction.execute(
                "SELECT life_generation_id FROM armi.life_generations WHERE life_generation_id=%s",
                (generation_id,),
            ).fetchone()
            is not None
        )

    def fence_expired_authority(self, transaction: PostgreSQLAdminTransaction) -> bool:
        rows = transaction.execute(
            "SELECT runtime_instance_id,status,lease_expires_at FROM armi.runtime_instances ORDER BY started_at,runtime_instance_id FOR UPDATE"
        ).fetchall()
        for row in rows:
            if row[1] == "active":
                active = transaction.execute(
                    "SELECT %s > statement_timestamp()", (cast(datetime, row[2]),)
                ).fetchone()
                if active is not None and active[0]:
                    return False
                transaction.execute(
                    "UPDATE armi.runtime_instances SET status='fenced',stopped_at=statement_timestamp() WHERE runtime_instance_id=%s AND status='active'",
                    (cast(UUID, row[0]),),
                )
        return True

    def advance_state_epoch(
        self,
        transaction: PostgreSQLAdminTransaction,
        *,
        subject_id: UUID,
        expected: int,
    ) -> int | None:
        row = transaction.execute(
            "UPDATE armi.subjects SET state_epoch=state_epoch+1 WHERE subject_id=%s AND state_epoch=%s RETURNING state_epoch",
            (subject_id, expected),
        ).fetchone()
        return None if row is None else int(cast(int, row[0]))

    def audit_trace(
        self, transaction: PostgreSQLAdminTransaction, *, trace_id: str
    ) -> tuple[tuple[object, ...], ...]:
        return tuple(
            transaction.execute(
                "SELECT target_kind,target_ref,operation,result_status,occurred_at FROM armi.audit_events WHERE trace_id=%s ORDER BY occurred_at,audit_event_id LIMIT 200",
                (trace_id,),
            ).fetchall()
        )

    def audit_count(
        self, transaction: PostgreSQLAdminTransaction, *, refs: tuple[UUID, ...]
    ) -> int:
        if len(refs) != 3:
            raise ValueError("ADMIN-RUNTIME-AUDIT-SCOPE")
        row = transaction.execute(
            "SELECT count(*) FROM armi.audit_events "
            "WHERE target_ref IN (%s,%s,%s) OR request_ref IN (%s,%s,%s)",
            (*refs, *refs),
        ).fetchone()
        return 0 if row is None else int(cast(int, row[0]))

    def delete_audit(
        self, transaction: PostgreSQLAdminTransaction, *, refs: tuple[UUID, ...]
    ) -> None:
        if len(refs) != 3:
            raise ValueError("ADMIN-RUNTIME-AUDIT-SCOPE")
        transaction.execute(
            "DELETE FROM armi.audit_events "
            "WHERE target_ref IN (%s,%s,%s) OR request_ref IN (%s,%s,%s)",
            (*refs, *refs),
        )

    def work(
        self,
        transaction: PostgreSQLAdminTransaction,
        *,
        work_id: UUID,
        for_update: bool = False,
    ) -> RuntimeAdminWork | None:
        row = transaction.execute(
            "SELECT work.work_id,work.status,work.lease_token,work.attempt_count,work.max_attempts,work.deadline_at,work.lease_expires_at,instance.status,work.owner_ref FROM armi.durable_work AS work LEFT JOIN armi.runtime_instances AS instance ON instance.runtime_instance_id=work.lease_owner WHERE work.work_id=%s"
            + (" FOR UPDATE OF work" if for_update else ""),
            (work_id,),
        ).fetchone()
        return (
            None
            if row is None
            else RuntimeAdminWork(
                cast(UUID, row[0]),
                str(row[1]),
                int(cast(int, row[2])),
                int(cast(int, row[3])),
                int(cast(int, row[4])),
                cast(datetime, row[5]),
                cast(datetime | None, row[6]),
                None if row[7] is None else str(row[7]),
                cast(UUID, row[8]),
            )
        )

    def work_is_stuck(
        self, transaction: PostgreSQLAdminTransaction, work: RuntimeAdminWork
    ) -> bool:
        row = transaction.execute(
            "SELECT %s='leased' AND %s<=statement_timestamp() AND %s>statement_timestamp() AND %s<%s",
            (
                work.status,
                work.lease_expires_at,
                work.deadline_at,
                work.attempt_count,
                work.max_attempts,
            ),
        ).fetchone()
        return (
            row is not None
            and bool(row[0])
            and work.runtime_status in {"stopped", "fenced"}
        )

    def requeue(
        self,
        transaction: PostgreSQLAdminTransaction,
        *,
        work_id: UUID,
        lease_token: int,
    ) -> bool:
        return (
            transaction.execute(
                "UPDATE armi.durable_work SET status='ready',not_before=statement_timestamp(),current_attempt_id=NULL,lease_owner=NULL,lease_expires_at=NULL,lease_token=lease_token+1,last_error_code=NULL,updated_at=statement_timestamp() WHERE work_id=%s AND status='leased' AND lease_token=%s",
                (work_id, lease_token),
            ).rowcount
            == 1
        )

    def work_state(
        self, transaction: PostgreSQLAdminTransaction, *, work_id: UUID
    ) -> tuple[str, int] | None:
        row = transaction.execute(
            "SELECT status,lease_token FROM armi.durable_work WHERE work_id=%s",
            (work_id,),
        ).fetchone()
        return None if row is None else (str(row[0]), int(cast(int, row[1])))

    def existing_cleanup_work(
        self, transaction: PostgreSQLAdminTransaction, *, work_id: UUID
    ) -> UUID | None:
        row = transaction.execute(
            "SELECT work_id FROM armi.durable_work WHERE work_id=%s AND work_kind='artifact.object.delete'",
            (work_id,),
        ).fetchone()
        return None if row is None else cast(UUID, row[0])

    def create_artifact_deletion_work(
        self,
        transaction: PostgreSQLAdminTransaction,
        *,
        deletion_id: UUID,
        artifact_object_id: UUID,
        content_digest: str,
        trace_id: UUID,
    ) -> None:
        transaction.execute(
            "INSERT INTO armi.durable_work (work_id,work_kind,owner_kind,owner_ref,idempotency_key,payload_kind,payload_ref,payload_digest,priority,not_before,deadline_at,status,max_attempts,attempt_count,lease_token,trace_id) VALUES (%s,'artifact.object.delete','artifact_object_deletion',%s,%s,'artifact_object',%s,%s,50,statement_timestamp(),statement_timestamp()+interval '59 minutes','ready',8,0,0,%s) ON CONFLICT (work_id) DO NOTHING",
            (
                deletion_id,
                deletion_id,
                f"artifact-delete:{deletion_id.hex}",
                artifact_object_id,
                content_digest,
                trace_id,
            ),
        )

    def side_work(
        self, transaction: PostgreSQLAdminTransaction, *, work_id: UUID
    ) -> tuple[UUID, UUID, str, str] | None:
        row = transaction.execute(
            "SELECT work_id,payload_ref,payload_digest,status FROM armi.durable_work WHERE work_id=%s AND work_kind='artifact.object.delete' AND owner_kind='artifact_object_deletion'",
            (work_id,),
        ).fetchone()
        return (
            None
            if row is None
            else (cast(UUID, row[0]), cast(UUID, row[1]), str(row[2]), str(row[3]))
        )

    def inspect_work_ids(
        self, transaction: PostgreSQLAdminTransaction, *, object_ids: tuple[UUID, ...]
    ) -> tuple[UUID, ...]:
        rows = transaction.execute(
            "SELECT work_id FROM armi.durable_work WHERE work_id=ANY(%s::uuid[]) ORDER BY work_id",
            (object_ids,),
        ).fetchall()
        return tuple(cast(UUID, row[0]) for row in rows)

    def inspect_subject_ids(
        self, transaction: PostgreSQLAdminTransaction, *, object_ids: tuple[UUID, ...]
    ) -> tuple[UUID, ...]:
        rows = transaction.execute(
            "SELECT subject_id FROM armi.subjects WHERE subject_id=ANY(%s::uuid[]) ORDER BY subject_id",
            (object_ids,),
        ).fetchall()
        return tuple(cast(UUID, row[0]) for row in rows)

    def artifact_reference_count(
        self, transaction: PostgreSQLAdminTransaction, *, artifact_id: UUID
    ) -> int:
        del transaction, artifact_id
        # The current baseline does not give Runtime a manifest artifact foreign key. Runtime
        # currently owns no artifact reference that participates in this correction.
        return 0


__all__ = (
    "RuntimeAdminEnvironment",
    "RuntimeAdminSubject",
    "RuntimeAdminWork",
    "RuntimeFoundationAdminAdapter",
)
