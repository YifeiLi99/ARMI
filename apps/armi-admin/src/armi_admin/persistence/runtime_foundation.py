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
                "SELECT subject_id,subject_version,state_epoch,current_generation_id,status,current_bundle_activation_id FROM armi.subjects WHERE singleton_key"
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
            "SELECT work_id FROM armi.durable_work WHERE work_id=%s AND work_kind='admin.correction.artifact-cleanup'",
            (work_id,),
        ).fetchone()
        return None if row is None else cast(UUID, row[0])

    def create_cleanup_work(
        self,
        transaction: PostgreSQLAdminTransaction,
        *,
        work_id: UUID,
        result_id: UUID,
        subject_id: UUID,
        artifact_id: UUID,
        content_digest: str,
    ) -> None:
        transaction.execute(
            "INSERT INTO armi.durable_work (work_id,work_kind,owner_kind,owner_ref,subject_id,idempotency_key,payload_kind,payload_ref,payload_digest,priority,not_before,deadline_at,status,max_attempts,attempt_count,lease_token,trace_id) VALUES (%s,'admin.correction.artifact-cleanup','admin_correction',%s,%s,%s,'artifact',%s,%s,100,statement_timestamp(),statement_timestamp()+interval '24 hours','ready',1,0,0,%s)",
            (
                work_id,
                result_id,
                subject_id,
                str(result_id),
                artifact_id,
                content_digest,
                work_id.hex,
            ),
        )

    def side_work(
        self, transaction: PostgreSQLAdminTransaction, *, work_id: UUID
    ) -> tuple[UUID, UUID, str, str] | None:
        row = transaction.execute(
            "SELECT work_id,payload_ref,payload_digest,status FROM armi.durable_work WHERE work_id=%s AND work_kind='admin.correction.artifact-cleanup' AND owner_kind='admin_correction'",
            (work_id,),
        ).fetchone()
        return (
            None
            if row is None
            else (cast(UUID, row[0]), cast(UUID, row[1]), str(row[2]), str(row[3]))
        )

    def settle_cleanup(
        self,
        transaction: PostgreSQLAdminTransaction,
        *,
        work_id: UUID,
        content_digest: str,
    ) -> str | None:
        row = transaction.execute(
            "SELECT status,payload_digest FROM armi.durable_work WHERE work_id=%s AND work_kind='admin.correction.artifact-cleanup' FOR UPDATE",
            (work_id,),
        ).fetchone()
        if row is None or row[1] != content_digest:
            return None
        if row[0] == "completed":
            return "completed"
        if row[0] != "ready":
            return str(row[0])
        changed = transaction.execute(
            "UPDATE armi.durable_work SET status='completed',result_kind='artifact_cleanup',result_ref=work_id,last_error_code=NULL,updated_at=statement_timestamp() WHERE work_id=%s AND status='ready'",
            (work_id,),
        ).rowcount
        return "completed" if changed == 1 else None

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
