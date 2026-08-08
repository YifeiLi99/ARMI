"""PostgreSQL Runtime authority lease, heartbeat, release, and fencing."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid7

import psycopg
from armi_kernel.application import (
    AuditDraft,
    AuditEventId,
    AuditReference,
    AuditResultStatus,
    AuditSensitivity,
    AuditViolation,
    RuntimeAuthorityRecord,
    RuntimeAuthorityStatus,
    RuntimeAuthorityViolation,
    RuntimeFence,
    RuntimeInstanceId,
)
from armi_kernel.contracts import Purpose, SubjectId, TraceId
from psycopg.pq import TransactionStatus
from psycopg_pool import AsyncConnectionPool, PoolTimeout

from armi_runtime.adapters.persistence.role_policy import physical_role_name

from .audit_events import PostgreSQLAuditWriter

_SEARCH_PATH = "pg_catalog, armi"
_AUTHORITY_KEY_PREFIX = "armi.runtime-authority:"


async def _configure(
    connection: psycopg.AsyncConnection[tuple[Any, ...]],
) -> None:
    await connection.set_autocommit(True)
    await connection.execute("SET search_path TO pg_catalog, armi")


async def _reset(
    connection: psycopg.AsyncConnection[tuple[Any, ...]],
) -> None:
    if connection.info.transaction_status != TransactionStatus.IDLE:
        await connection.rollback()
    await connection.execute("RESET ROLE")
    await connection.execute("RESET ALL")
    await connection.execute("SET search_path TO pg_catalog, armi")


class PostgreSQLRuntimeAuthority:
    """Own a role-bound pool for explicit authority control transactions."""

    __slots__ = (
        "_environment_id",
        "_expected_bundle_digest",
        "_expected_role",
        "_pool",
        "_pool_timeout_seconds",
    )

    def __init__(
        self,
        conninfo: str,
        *,
        environment_id: UUID,
        expected_bundle_digest: str,
        pool_timeout_seconds: int,
    ) -> None:
        if environment_id.version != 7:
            raise ValueError("environment_id must be UUIDv7")
        if (
            type(expected_bundle_digest) is not str
            or not expected_bundle_digest.startswith("sha256:")
            or len(expected_bundle_digest) != 71
        ):
            raise ValueError("expected_bundle_digest is invalid")
        if type(pool_timeout_seconds) is not int or pool_timeout_seconds <= 0:
            raise ValueError("pool_timeout_seconds must be positive")
        self._environment_id = environment_id
        self._expected_bundle_digest = expected_bundle_digest
        self._expected_role = physical_role_name(environment_id, "runtime")
        self._pool_timeout_seconds = pool_timeout_seconds

        async def check(
            connection: psycopg.AsyncConnection[tuple[Any, ...]],
        ) -> None:
            row = await (
                await connection.execute(
                    "SELECT session_user, current_user, current_setting('search_path')"
                )
            ).fetchone()
            if row != (self._expected_role, self._expected_role, _SEARCH_PATH):
                raise RuntimeAuthorityViolation("AUTH-ROLE-IDENTITY")

        self._pool = AsyncConnectionPool[psycopg.AsyncConnection[tuple[Any, ...]]](
            conninfo,
            min_size=1,
            max_size=2,
            open=False,
            configure=_configure,
            check=check,
            reset=_reset,
            timeout=float(pool_timeout_seconds),
            name="armi-runtime-authority",
        )

    async def open(self) -> None:
        try:
            await self._pool.open(wait=True)
        except psycopg.Error, PoolTimeout:
            raise RuntimeAuthorityViolation("AUTH-DATABASE") from None

    async def close(self) -> None:
        await self._pool.close()

    async def acquire(
        self,
        *,
        runtime_instance_id: RuntimeInstanceId,
        lease_seconds: int,
    ) -> RuntimeAuthorityRecord:
        _require_lease_seconds(lease_seconds)
        commit_may_be_unknown = False
        try:
            async with (
                self._pool.connection(
                    timeout=float(self._pool_timeout_seconds)
                ) as connection,
                connection.transaction(),
            ):
                await connection.execute(
                    "SELECT pg_advisory_xact_lock(pg_catalog.hashtextextended(%s, 0))",
                    (_AUTHORITY_KEY_PREFIX + str(self._environment_id),),
                )
                current = await self._current_subject(connection)
                subject_id, generation_id, activation_id, bundle_digest = current
                for kind, value in (
                    ("subject", subject_id),
                    ("generation", generation_id),
                    ("activation", activation_id),
                ):
                    await connection.execute(
                        """
                        SELECT pg_advisory_xact_lock(
                            pg_catalog.hashtextextended(%s, 0)
                        )
                        """,
                        (f"armi.runtime-authority:{kind}:{value}",),
                    )
                if await self._current_subject(connection) != current:
                    raise RuntimeAuthorityViolation("AUTH-SUBJECT-STATE")
                if str(bundle_digest) != self._expected_bundle_digest:
                    raise RuntimeAuthorityViolation("AUTH-PACKAGE-DRIFT")
                active = await (
                    await connection.execute(
                        """
                            SELECT
                                runtime_instance_id,
                                fence_token,
                                lease_expires_at
                            FROM armi.runtime_instances
                            WHERE life_generation_id = %s
                              AND status = 'active'
                            FOR UPDATE
                            """,
                        (generation_id,),
                    )
                ).fetchone()
                writer = PostgreSQLAuditWriter(connection)
                if active is not None:
                    expired = await (
                        await connection.execute(
                            "SELECT %s <= statement_timestamp()",
                            (active[2],),
                        )
                    ).fetchone()
                    if expired is None or not bool(expired[0]):
                        raise RuntimeAuthorityViolation("AUTH-LEASE-HELD")
                    await connection.execute(
                        """
                            UPDATE armi.runtime_instances
                            SET status = 'fenced',
                                stopped_at = statement_timestamp()
                            WHERE runtime_instance_id = %s
                              AND fence_token = %s
                              AND status = 'active'
                            """,
                        (active[0], active[1]),
                    )
                    await writer.append(
                        _audit_draft(
                            actor_ref=runtime_instance_id.value,
                            operation="runtime.authority.fenced",
                            target_ref=active[0],
                            subject_id=subject_id,
                        )
                    )
                token_row = await (
                    await connection.execute(
                        """
                            SELECT COALESCE(MAX(fence_token), 0) + 1
                            FROM armi.runtime_instances
                            WHERE life_generation_id = %s
                            """,
                        (generation_id,),
                    )
                ).fetchone()
                assert token_row is not None
                fence_token = int(token_row[0])
                row = await (
                    await connection.execute(
                        """
                            INSERT INTO armi.runtime_instances (
                                runtime_instance_id,
                                subject_id,
                                life_generation_id,
                                bundle_activation_id,
                                fence_token,
                                status,
                                lease_expires_at)
                            VALUES (
                                %s, %s, %s, %s, %s, 'active',
                                statement_timestamp()
                                    + make_interval(secs => %s))
                            RETURNING
                                runtime_instance_id,
                                subject_id,
                                life_generation_id,
                                bundle_activation_id,
                                fence_token,
                                status,
                                started_at,
                                last_heartbeat_at,
                                lease_expires_at,
                                stopped_at
                            """,
                        (
                            runtime_instance_id.value,
                            subject_id,
                            generation_id,
                            activation_id,
                            fence_token,
                            lease_seconds,
                        ),
                    )
                ).fetchone()
                assert row is not None
                await writer.append(
                    _audit_draft(
                        actor_ref=runtime_instance_id.value,
                        operation="runtime.authority.acquired",
                        target_ref=runtime_instance_id.value,
                        subject_id=subject_id,
                    )
                )
                commit_may_be_unknown = True
            return _record(row)
        except RuntimeAuthorityViolation:
            raise
        except AuditViolation:
            raise RuntimeAuthorityViolation("AUTH-AUDIT") from None
        except PoolTimeout:
            raise RuntimeAuthorityViolation("AUTH-DATABASE") from None
        except psycopg.OperationalError:
            if not commit_may_be_unknown:
                raise RuntimeAuthorityViolation("AUTH-DATABASE") from None
            recovered = await self._recover_acquire(runtime_instance_id)
            if recovered is not None:
                return recovered
            raise RuntimeAuthorityViolation("AUTH-COMMIT-UNKNOWN") from None
        except psycopg.Error:
            raise RuntimeAuthorityViolation("AUTH-DATABASE") from None

    async def heartbeat(
        self,
        fence: RuntimeFence,
        *,
        lease_seconds: int,
    ) -> RuntimeAuthorityRecord:
        _require_fence(fence)
        _require_lease_seconds(lease_seconds)
        try:
            async with (
                self._pool.connection(
                    timeout=float(self._pool_timeout_seconds)
                ) as connection,
                connection.transaction(),
            ):
                row = await (
                    await connection.execute(
                        """
                            UPDATE armi.runtime_instances AS instance
                            SET last_heartbeat_at = statement_timestamp(),
                                lease_expires_at = statement_timestamp()
                                    + make_interval(secs => %s)
                            FROM armi.subjects AS subject
                            WHERE instance.runtime_instance_id = %s
                              AND instance.fence_token = %s
                              AND instance.status = 'active'
                              AND instance.lease_expires_at
                                  > statement_timestamp()
                              AND subject.singleton_key = 1
                              AND subject.subject_id = instance.subject_id
                              AND subject.current_generation_id
                                  = instance.life_generation_id
                              AND subject.current_bundle_activation_id
                                  = instance.bundle_activation_id
                            RETURNING
                                instance.runtime_instance_id,
                                instance.subject_id,
                                instance.life_generation_id,
                                instance.bundle_activation_id,
                                instance.fence_token,
                                instance.status,
                                instance.started_at,
                                instance.last_heartbeat_at,
                                instance.lease_expires_at,
                                instance.stopped_at
                            """,
                        (
                            lease_seconds,
                            fence.runtime_instance_id.value,
                            fence.fence_token,
                        ),
                    )
                ).fetchone()
                if row is None:
                    raise await self._stale_or_expired(connection, fence)
            return _record(row)
        except RuntimeAuthorityViolation:
            raise
        except AuditViolation:
            raise RuntimeAuthorityViolation("AUTH-AUDIT") from None
        except psycopg.Error, PoolTimeout:
            raise RuntimeAuthorityViolation("AUTH-DATABASE") from None

    async def release(self, fence: RuntimeFence) -> RuntimeAuthorityRecord:
        _require_fence(fence)
        try:
            async with (
                self._pool.connection(
                    timeout=float(self._pool_timeout_seconds)
                ) as connection,
                connection.transaction(),
            ):
                row = await (
                    await connection.execute(
                        """
                            UPDATE armi.runtime_instances
                            SET status = 'stopped',
                                stopped_at = statement_timestamp()
                            WHERE runtime_instance_id = %s
                              AND fence_token = %s
                              AND status = 'active'
                              AND lease_expires_at > statement_timestamp()
                            RETURNING
                                runtime_instance_id,
                                subject_id,
                                life_generation_id,
                                bundle_activation_id,
                                fence_token,
                                status,
                                started_at,
                                last_heartbeat_at,
                                lease_expires_at,
                                stopped_at
                            """,
                        (
                            fence.runtime_instance_id.value,
                            fence.fence_token,
                        ),
                    )
                ).fetchone()
                if row is None:
                    raise await self._stale_or_expired(connection, fence)
                await PostgreSQLAuditWriter(connection).append(
                    _audit_draft(
                        actor_ref=fence.runtime_instance_id.value,
                        operation="runtime.authority.released",
                        target_ref=fence.runtime_instance_id.value,
                        subject_id=fence.subject_id,
                    )
                )
            return _record(row)
        except RuntimeAuthorityViolation:
            raise
        except AuditViolation:
            raise RuntimeAuthorityViolation("AUTH-AUDIT") from None
        except psycopg.Error, PoolTimeout:
            raise RuntimeAuthorityViolation("AUTH-DATABASE") from None

    async def _current_subject(
        self,
        connection: psycopg.AsyncConnection[tuple[Any, ...]],
    ) -> tuple[UUID, UUID, UUID, str]:
        row = await (
            await connection.execute(
                """
                SELECT
                    subject.subject_id,
                    generation.life_generation_id,
                    activation.bundle_activation_id,
                    activation.bundle_digest
                FROM armi.subjects AS subject
                JOIN armi.life_generations AS generation
                  ON generation.life_generation_id
                    = subject.current_generation_id
                 AND generation.subject_id = subject.subject_id
                 AND generation.status = 'active'
                JOIN armi.runtime_bundle_activations AS activation
                  ON activation.bundle_activation_id
                    = subject.current_bundle_activation_id
                 AND activation.subject_id = subject.subject_id
                 AND activation.status = 'current'
                WHERE subject.singleton_key = 1
                  AND subject.status = 'active'
                """
            )
        ).fetchone()
        if row is None:
            raise RuntimeAuthorityViolation("AUTH-SUBJECT-STATE")
        return row[0], row[1], row[2], str(row[3])

    async def _stale_or_expired(
        self,
        connection: psycopg.AsyncConnection[tuple[Any, ...]],
        fence: RuntimeFence,
    ) -> RuntimeAuthorityViolation:
        row = await (
            await connection.execute(
                """
                SELECT
                    status,
                    fence_token,
                    lease_expires_at <= statement_timestamp()
                FROM armi.runtime_instances
                WHERE runtime_instance_id = %s
                """,
                (fence.runtime_instance_id.value,),
            )
        ).fetchone()
        if row is not None and int(row[1]) == fence.fence_token and bool(row[2]):
            return RuntimeAuthorityViolation("AUTH-LEASE-EXPIRED")
        return RuntimeAuthorityViolation("AUTH-FENCE-STALE")

    async def _recover_acquire(
        self,
        runtime_instance_id: RuntimeInstanceId,
    ) -> RuntimeAuthorityRecord | None:
        try:
            async with self._pool.connection(
                timeout=float(self._pool_timeout_seconds)
            ) as connection:
                row = await (
                    await connection.execute(
                        """
                        SELECT
                            runtime_instance_id,
                            subject_id,
                            life_generation_id,
                            bundle_activation_id,
                            fence_token,
                            status,
                            started_at,
                            last_heartbeat_at,
                            lease_expires_at,
                            stopped_at
                        FROM armi.runtime_instances
                        WHERE runtime_instance_id = %s
                        """,
                        (runtime_instance_id.value,),
                    )
                ).fetchone()
                return None if row is None else _record(row)
        except psycopg.Error, PoolTimeout:
            return None


def _require_lease_seconds(value: object) -> None:
    if type(value) is not int or not 1 <= value <= 3600:
        raise RuntimeAuthorityViolation("AUTH-DECLARATION")


def _require_fence(value: object) -> None:
    if type(value) is not RuntimeFence:
        raise RuntimeAuthorityViolation("AUTH-DECLARATION")


def _record(row: tuple[Any, ...]) -> RuntimeAuthorityRecord:
    return RuntimeAuthorityRecord(
        fence=RuntimeFence(
            runtime_instance_id=RuntimeInstanceId(row[0]),
            subject_id=row[1],
            life_generation_id=row[2],
            bundle_activation_id=row[3],
            fence_token=int(row[4]),
        ),
        status=RuntimeAuthorityStatus(str(row[5])),
        started_at=_utc(row[6]),
        last_heartbeat_at=_utc(row[7]),
        lease_expires_at=_utc(row[8]),
        stopped_at=None if row[9] is None else _utc(row[9]),
    )


def _utc(value: datetime) -> datetime:
    return value.astimezone(UTC)


def _audit_draft(
    *,
    actor_ref: UUID,
    operation: str,
    target_ref: UUID,
    subject_id: UUID,
) -> AuditDraft:
    return AuditDraft(
        audit_event_id=AuditEventId(uuid7()),
        actor=AuditReference("runtime", actor_ref),
        purpose=Purpose("runtime.authority"),
        operation=operation,
        target=AuditReference("runtime_instance", target_ref),
        result_status=AuditResultStatus.APPLIED,
        trace_id=TraceId(actor_ref.hex),
        sensitivity=AuditSensitivity.INTERNAL,
        subject_id=SubjectId(subject_id),
    )


__all__ = ("PostgreSQLRuntimeAuthority",)
