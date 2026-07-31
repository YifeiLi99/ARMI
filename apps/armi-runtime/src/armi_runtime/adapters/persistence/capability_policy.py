"""PostgreSQL owner for the minimal T-04 capability policy."""

import asyncio
import base64
import contextlib
import hashlib
import hmac
import json
import secrets
from collections.abc import Callable
from datetime import timedelta
from typing import Any, cast
from uuid import UUID, uuid7

import rfc8785
from armi_kernel.application import (
    AuditDraft,
    AuditEventId,
    AuditReference,
    AuditResultStatus,
    AuditSensitivity,
    CapabilityKind,
    CapabilityOperation,
    CapabilityRequestId,
    CapabilityRequestStatus,
    CapabilityViolation,
    CreatorGrantCommand,
    CreatorGrantDecision,
    CreatorGrantResult,
    CreatorSceneReplyScope,
    GrantStatus,
    PermissionGrant,
    PermissionGrantId,
    RuntimeFence,
)
from armi_kernel.contracts import Digest, Purpose, SubjectId, TraceId

from .unit_of_work import PostgreSQLUnitOfWorkFactory


class PostgreSQLCreatorGrantPolicy:
    """Apply exact Creator decisions; never dispatch or execute the capability."""

    __slots__ = ("_cursor_key", "_environment_id", "_factory", "_stop")

    def __init__(
        self,
        conninfo: str,
        *,
        environment_id: UUID,
        pool_min: int,
        pool_max: int,
        acquire_timeout_seconds: int,
        statement_timeout_seconds: int,
        authority_admission: Callable[[], RuntimeFence],
        cursor_key: bytes,
    ) -> None:
        async def reject_dynamic_lock(connection: Any, target: Any) -> None:
            del connection, target
            raise CapabilityViolation("POLICY-LOCK")

        self._factory = PostgreSQLUnitOfWorkFactory(
            conninfo,
            environment_id=environment_id,
            lock_acquirer=reject_dynamic_lock,
            pool_min=pool_min,
            pool_max=pool_max,
            acquire_timeout_seconds=acquire_timeout_seconds,
            statement_timeout_seconds=statement_timeout_seconds,
            authority_admission=authority_admission,
        )
        if type(cursor_key) is not bytes or len(cursor_key) < 32:
            raise CapabilityViolation("POLICY-CURSOR-KEY")
        self._cursor_key = hmac.new(
            cursor_key, b"armi.creator.capability-request.cursor-key.v1", hashlib.sha256
        ).digest()
        self._environment_id = environment_id
        self._stop = asyncio.Event()

    async def open(self) -> None:
        await self._factory.open()

    async def close(self) -> None:
        await self._factory.close()

    def stop(self) -> None:
        self._stop.set()

    async def run_expiry_reconciler(self) -> None:
        while not self._stop.is_set():
            await self.expire_once()
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(self._stop.wait(), timeout=1.0)

    async def list_requests(
        self,
        *,
        creator_party_id: UUID,
        limit: int,
        cursor: str | None,
    ) -> dict[str, object]:
        if type(creator_party_id) is not UUID or creator_party_id.version != 7:
            raise CapabilityViolation("SCOPE-CAPABILITY-REQUEST")
        if type(limit) is not int or not 1 <= limit <= 100:
            raise CapabilityViolation("CON-CAPABILITY-PAGE")
        boundary = (
            _decode_cursor(
                cursor,
                key=self._cursor_key,
                environment_id=self._environment_id,
                creator_party_id=creator_party_id,
                limit=limit,
            )
            if cursor is not None
            else None
        )
        from armi_kernel.application import LockPlan

        async with self._factory.unit_of_work(
            LockPlan(), read_only=True
        ) as unit_of_work:
            connection = unit_of_work._connection_for_repository()  # pyright: ignore[reportPrivateUsage]
            rows = await (
                await connection.execute(
                    """
                    SELECT request.capability_request_id, request.capability_kind,
                           request.operation_class, request.subject_id,
                           request.interaction_scene_id, request.audience_scope,
                           request.data_scope, request.purpose,
                           request.workspace_scope, request.artifact_scope,
                           request.network_access,
                           request.requested_valid_for_seconds,
                           request.requested_max_uses,
                           request.requested_max_payload_bytes,
                           CASE
                             WHEN request.current_status IN ('granted', 'limited')
                             AND permission.valid_until <= statement_timestamp()
                             THEN 'expired'
                             ELSE request.current_status
                           END, request.request_version,
                           request.created_at, permission.grant_id
                    FROM armi.capability_requests AS request
                    LEFT JOIN armi.permission_grants AS permission
                      ON permission.capability_request_id = request.capability_request_id
                    WHERE request.creator_party_id = %s
                      AND (%s::timestamptz IS NULL OR
                           (request.created_at, request.capability_request_id) <
                           (%s::timestamptz, %s::uuid))
                    ORDER BY request.created_at DESC, request.capability_request_id DESC
                    LIMIT %s
                    """,
                    (
                        creator_party_id,
                        boundary[0] if boundary else None,
                        boundary[0] if boundary else None,
                        boundary[1] if boundary else None,
                        limit + 1,
                    ),
                )
            ).fetchall()
        visible = rows[:limit]
        items = [
            {
                "capability_request_id": str(row[0]),
                "capability_kind": str(row[1]),
                "operation": str(row[2]),
                "subject_id": str(row[3]),
                "scene_id": str(row[4]),
                "audience_scope": row[5],
                "data_scope": row[6],
                "purpose": str(row[7]),
                "workspace_scope": row[8],
                "artifact_scope": row[9],
                "network_access": row[10],
                "valid_for_seconds": int(row[11]),
                "max_uses": int(row[12]),
                "max_payload_bytes": int(row[13]) if row[13] is not None else None,
                "status": str(row[14]),
                "request_version": int(row[15]),
                "created_at": row[16],
                "grant_ref": str(row[17]) if row[17] is not None else None,
            }
            for row in visible
        ]
        next_cursor = None
        if len(rows) > limit and visible:
            last = visible[-1]
            next_cursor = _encode_cursor(
                key=self._cursor_key,
                environment_id=self._environment_id,
                creator_party_id=creator_party_id,
                limit=limit,
                created_at=last[16],
                request_id=last[0],
            )
        return {"items": items, "next_cursor": next_cursor}

    async def decide(self, command: CreatorGrantCommand) -> CreatorGrantResult:
        try:
            from armi_kernel.application import LockPlan

            async with self._factory.unit_of_work(LockPlan()) as unit_of_work:
                connection = unit_of_work._connection_for_repository()  # pyright: ignore[reportPrivateUsage]
                command_digest = _command_digest(command)
                existing = await (
                    await connection.execute(
                        """
                        SELECT command_digest
                        FROM armi.capability_request_decisions
                        WHERE capability_decision_id = %s
                        """,
                        (command.decision_id.value,),
                    )
                ).fetchone()
                if existing is not None:
                    if str(existing[0]) != command_digest.value:
                        raise CapabilityViolation("CONFLICT-POLICY-IDEMPOTENCY")
                    return await _load_result(connection, command.request_id)

                request = await (
                    await connection.execute(
                        """
                        SELECT request.capability_request_id, request.subject_id,
                               request.interaction_scene_id, request.creator_party_id,
                               request.capability_id, request.capability_kind,
                               request.operation_class, request.audience_scope,
                               request.data_scope, request.purpose,
                               request.requested_valid_for_seconds,
                               request.requested_max_uses,
                               request.requested_max_payload_bytes,
                               request.current_status, request.request_version,
                               capability.availability_status
                        FROM armi.capability_requests AS request
                        JOIN armi.capabilities AS capability
                          ON capability.capability_id = request.capability_id
                         AND capability.capability_kind = request.capability_kind
                         AND capability.operation_class = request.operation_class
                        WHERE request.capability_request_id = %s
                        FOR UPDATE OF request
                        """,
                        (command.request_id.value,),
                    )
                ).fetchone()
                if request is None:
                    raise CapabilityViolation("SCOPE-CAPABILITY-REQUEST")
                if int(request[14]) != command.expected_version:
                    raise CapabilityViolation("CONFLICT-POLICY-VERSION")
                current = CapabilityRequestStatus(str(request[13]))
                _validate_transition(command.decision, current)
                capability = CapabilityKind(str(request[5]))
                if (
                    capability is CapabilityKind.CODEX_DELEGATED_WORK
                    and command.decision
                    in {CreatorGrantDecision.GRANT, CreatorGrantDecision.LIMIT}
                ) or (
                    str(request[15]) != "available"
                    and command.decision
                    in {CreatorGrantDecision.GRANT, CreatorGrantDecision.LIMIT}
                ):
                    raise CapabilityViolation("CAPABILITY-UNAVAILABLE")

                now_row = await (
                    await connection.execute("SELECT statement_timestamp()")
                ).fetchone()
                if now_row is None:
                    raise CapabilityViolation("POLICY-DATABASE")
                now = now_row[0]
                resulting_version = command.expected_version + 1
                grant: PermissionGrant | None = None
                scope_digest: Digest | None = None
                result_status: CapabilityRequestStatus
                if command.decision in {
                    CreatorGrantDecision.GRANT,
                    CreatorGrantDecision.LIMIT,
                }:
                    duration = int(request[10])
                    uses = int(request[11])
                    payload_bytes = int(request[12])
                    if command.decision is CreatorGrantDecision.LIMIT:
                        original = (duration, uses, payload_bytes)
                        duration = _narrow(command.valid_for_seconds, duration)
                        uses = _narrow(command.max_uses, uses)
                        payload_bytes = _narrow(
                            command.max_payload_bytes, payload_bytes
                        )
                        if (duration, uses, payload_bytes) == original:
                            raise CapabilityViolation("POLICY-SCOPE-EXPANSION")
                        result_status = CapabilityRequestStatus.LIMITED
                    else:
                        result_status = CapabilityRequestStatus.GRANTED
                    scope = CreatorSceneReplyScope(
                        request[1],
                        request[2],
                        request[3],
                        duration,
                        uses,
                        payload_bytes,
                    )
                    scope_digest = Digest.from_bytes(
                        rfc8785.dumps(cast(Any, _scope_wire(scope)))
                    )
                    grant_id = PermissionGrantId(uuid7())
                    valid_until = now + timedelta(seconds=duration)
                    await connection.execute(
                        """
                        INSERT INTO armi.permission_grants (
                            grant_id, capability_request_id, creator_party_id,
                            capability_id, subject_id, interaction_scene_id,
                            operation_class, audience_scope, data_scope, purpose,
                            valid_from, valid_until, max_uses, max_payload_bytes,
                            scope_digest, schema_version
                        ) VALUES (
                            %s, %s, %s, %s, %s, %s, 'send', 'creator',
                            'creator_visible_response', 'respond_to_creator',
                            %s, %s, %s, %s, %s, 1
                        )
                        """,
                        (
                            grant_id.value,
                            request[0],
                            request[3],
                            request[4],
                            request[1],
                            request[2],
                            now,
                            valid_until,
                            uses,
                            payload_bytes,
                            scope_digest.value,
                        ),
                    )
                    grant = PermissionGrant(
                        grant_id,
                        command.request_id,
                        capability,
                        CapabilityOperation.SEND,
                        scope,
                        now,
                        valid_until,
                        0,
                        GrantStatus.ACTIVE,
                    )
                elif command.decision is CreatorGrantDecision.DENY:
                    result_status = CapabilityRequestStatus.DENIED
                else:
                    result_status = CapabilityRequestStatus.REVOKED
                    revoked = await (
                        await connection.execute(
                            """
                            UPDATE armi.permission_grants
                            SET status = 'revoked', revoked_at = statement_timestamp()
                            WHERE capability_request_id = %s AND status = 'active'
                              AND valid_until > statement_timestamp()
                            RETURNING grant_id
                            """,
                            (request[0],),
                        )
                    ).fetchone()
                    if revoked is None:
                        raise CapabilityViolation("POLICY-GRANT-NOT-ACTIVE")

                updated = await (
                    await connection.execute(
                        """
                        UPDATE armi.capability_requests
                        SET current_status = %s, request_version = %s,
                            resolved_by_party_id = creator_party_id,
                            resolution_reason_class = %s,
                            resolved_at = statement_timestamp()
                        WHERE capability_request_id = %s AND request_version = %s
                        RETURNING capability_request_id
                        """,
                        (
                            result_status.value,
                            resulting_version,
                            command.reason_code,
                            request[0],
                            command.expected_version,
                        ),
                    )
                ).fetchone()
                if updated is None:
                    raise CapabilityViolation("CONFLICT-POLICY-VERSION")
                await connection.execute(
                    """
                    INSERT INTO armi.capability_request_decisions (
                        capability_decision_id, capability_request_id,
                        creator_party_id, expected_request_version,
                        resulting_request_version, decision_kind, command_digest,
                        scope_digest, reason_code, schema_version
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, 1)
                    """,
                    (
                        command.decision_id.value,
                        request[0],
                        request[3],
                        command.expected_version,
                        resulting_version,
                        command.decision.value,
                        command_digest.value,
                        scope_digest.value if scope_digest else None,
                        command.reason_code,
                    ),
                )
                result_digest = Digest.from_bytes(
                    rfc8785.dumps(
                        cast(
                            Any,
                            {
                                "schema_version": "armi.creator-grant-result.v1",
                                "request_id": str(request[0]),
                                "request_version": resulting_version,
                                "status": result_status.value,
                                "grant_id": str(grant.grant_id.value)
                                if grant
                                else None,
                            },
                        )
                    )
                )
                await unit_of_work.audit.append(
                    AuditDraft(
                        AuditEventId(uuid7()),
                        AuditReference("creator", request[3]),
                        Purpose("capability.manage"),
                        f"capability.request.{result_status.value}",
                        AuditReference("capability_request", request[0]),
                        AuditResultStatus.APPLIED,
                        TraceId(secrets.token_hex(16)),
                        AuditSensitivity.PRIVATE,
                        subject_id=SubjectId(request[1]),
                        request_digest=command_digest,
                        response_digest=result_digest,
                        grant=AuditReference("permission_grant", grant.grant_id.value)
                        if grant
                        else None,
                    )
                )
                return CreatorGrantResult(
                    command.request_id,
                    resulting_version,
                    result_status,
                    command_digest,
                    grant,
                )
        except CapabilityViolation:
            raise
        except Exception as error:
            if error.__class__.__module__.startswith(("psycopg", "psycopg_pool")):
                raise CapabilityViolation("POLICY-DATABASE") from None
            raise

    async def expire_once(self, *, limit: int = 100) -> int:
        if type(limit) is not int or not 1 <= limit <= 100:
            raise CapabilityViolation("CON-CAPABILITY-PAGE")
        from armi_kernel.application import LockPlan

        async with self._factory.unit_of_work(LockPlan()) as unit_of_work:
            connection = unit_of_work._connection_for_repository()  # pyright: ignore[reportPrivateUsage]
            rows = await (
                await connection.execute(
                    """
                    SELECT permission.grant_id,
                           permission.capability_request_id,
                           permission.creator_party_id,
                           permission.subject_id,
                           request.request_version,
                           permission.scope_digest
                    FROM armi.permission_grants AS permission
                    JOIN armi.capability_requests AS request USING (capability_request_id)
                    WHERE permission.status = 'active'
                      AND permission.valid_until <= statement_timestamp()
                    ORDER BY permission.valid_until, permission.grant_id
                    LIMIT %s FOR UPDATE OF permission, request SKIP LOCKED
                    """,
                    (limit,),
                )
            ).fetchall()
            for row in rows:
                decision_id = uuid7()
                command_digest = Digest.from_bytes(
                    rfc8785.dumps(
                        cast(
                            Any,
                            {
                                "schema_version": "armi.grant-expiry.v1",
                                "grant_id": str(row[0]),
                                "capability_request_id": str(row[1]),
                                "expected_request_version": int(row[4]),
                            },
                        )
                    )
                )
                await connection.execute(
                    "UPDATE armi.permission_grants SET status='expired', revoked_at=statement_timestamp() WHERE grant_id=%s AND status='active'",
                    (row[0],),
                )
                await connection.execute(
                    "UPDATE armi.capability_requests SET current_status='expired', request_version=request_version+1, resolved_at=statement_timestamp() WHERE capability_request_id=%s",
                    (row[1],),
                )
                await connection.execute(
                    """
                    INSERT INTO armi.capability_request_decisions (
                        capability_decision_id, capability_request_id,
                        creator_party_id, expected_request_version,
                        resulting_request_version, decision_kind, command_digest,
                        scope_digest, reason_code, schema_version
                    ) VALUES (%s, %s, %s, %s, %s, 'expire', %s, %s,
                              'grant_expired', 1)
                    """,
                    (
                        decision_id,
                        row[1],
                        row[2],
                        int(row[4]),
                        int(row[4]) + 1,
                        command_digest.value,
                        row[5],
                    ),
                )
                await unit_of_work.audit.append(
                    AuditDraft(
                        AuditEventId(uuid7()),
                        AuditReference("runtime", self._environment_id),
                        Purpose("capability.manage"),
                        "capability.request.expired",
                        AuditReference("capability_request", row[1]),
                        AuditResultStatus.APPLIED,
                        TraceId(secrets.token_hex(16)),
                        AuditSensitivity.PRIVATE,
                        subject_id=SubjectId(row[3]),
                        request_digest=command_digest,
                        grant=AuditReference("permission_grant", row[0]),
                    )
                )
            return len(rows)


def _validate_transition(
    decision: CreatorGrantDecision, current: CapabilityRequestStatus
) -> None:
    if decision in {
        CreatorGrantDecision.GRANT,
        CreatorGrantDecision.LIMIT,
        CreatorGrantDecision.DENY,
    }:
        if current is not CapabilityRequestStatus.PENDING:
            raise CapabilityViolation("CONFLICT-POLICY-STATE")
    elif current not in {
        CapabilityRequestStatus.GRANTED,
        CapabilityRequestStatus.LIMITED,
    }:
        raise CapabilityViolation("CONFLICT-POLICY-STATE")


def _narrow(requested: int | None, maximum: int) -> int:
    if requested is None:
        return maximum
    if type(requested) is not int or requested <= 0 or requested > maximum:
        raise CapabilityViolation("POLICY-SCOPE-EXPANSION")
    return requested


def _scope_wire(scope: CreatorSceneReplyScope) -> dict[str, object]:
    return {
        "subject_id": str(scope.subject_id),
        "scene_id": str(scope.scene_id),
        "creator_party_id": str(scope.creator_party_id),
        "audience_scope": scope.audience_scope,
        "data_scope": scope.data_scope,
        "purpose": scope.purpose,
        "valid_for_seconds": scope.valid_for_seconds,
        "max_uses": scope.max_uses,
        "max_payload_bytes": scope.max_payload_bytes,
    }


def _command_digest(command: CreatorGrantCommand) -> Digest:
    return Digest.from_bytes(
        rfc8785.dumps(
            cast(
                Any,
                {
                    "schema_version": "armi.creator-grant-command.v1",
                    "decision_id": str(command.decision_id.value),
                    "request_id": str(command.request_id.value),
                    "expected_version": command.expected_version,
                    "decision": command.decision.value,
                    "valid_for_seconds": command.valid_for_seconds,
                    "max_uses": command.max_uses,
                    "max_payload_bytes": command.max_payload_bytes,
                    "reason_code": command.reason_code,
                },
            )
        )
    )


async def _load_result(
    connection: Any, request_id: CapabilityRequestId
) -> CreatorGrantResult:
    row = await (
        await connection.execute(
            """
            SELECT request.request_version, request.current_status,
                   decision.command_digest, request.capability_kind,
                   request.operation_class, request.subject_id,
                   request.interaction_scene_id, request.creator_party_id,
                   permission.grant_id, permission.valid_from, permission.valid_until,
                   permission.max_uses, permission.consumed_uses,
                   permission.max_payload_bytes, permission.status
            FROM armi.capability_requests AS request
            JOIN armi.capability_request_decisions AS decision
              ON decision.capability_request_id = request.capability_request_id
             AND decision.resulting_request_version = request.request_version
            LEFT JOIN armi.permission_grants AS permission
              ON permission.capability_request_id = request.capability_request_id
            WHERE request.capability_request_id = %s
            """,
            (request_id.value,),
        )
    ).fetchone()
    if row is None:
        raise CapabilityViolation("POLICY-RESULT-MISSING")
    status = CapabilityRequestStatus(str(row[1]))
    grant = None
    if status in {CapabilityRequestStatus.GRANTED, CapabilityRequestStatus.LIMITED}:
        if row[8] is None:
            raise CapabilityViolation("POLICY-RESULT-MISSING")
        scope = CreatorSceneReplyScope(
            row[5],
            row[6],
            row[7],
            int((row[10] - row[9]).total_seconds()),
            int(row[11]),
            int(row[13]),
        )
        grant = PermissionGrant(
            PermissionGrantId(row[8]),
            request_id,
            CapabilityKind(str(row[3])),
            CapabilityOperation(str(row[4])),
            scope,
            row[9],
            row[10],
            int(row[12]),
            GrantStatus(str(row[14])),
        )
    return CreatorGrantResult(
        request_id,
        int(row[0]),
        status,
        Digest(str(row[2])),
        grant,
    )


def _encode_cursor(
    *,
    key: bytes,
    environment_id: UUID,
    creator_party_id: UUID,
    limit: int,
    created_at: Any,
    request_id: UUID,
) -> str:
    payload = rfc8785.dumps(
        cast(
            Any,
            {
                "schema_version": "armi.capability-request-cursor.v1",
                "environment_id": str(environment_id),
                "creator_party_id": str(creator_party_id),
                "limit": limit,
                "created_at": created_at.isoformat(),
                "capability_request_id": str(request_id),
            },
        )
    )
    encoded = base64.urlsafe_b64encode(payload).rstrip(b"=").decode("ascii")
    signature = (
        base64.urlsafe_b64encode(hmac.new(key, payload, hashlib.sha256).digest())
        .rstrip(b"=")
        .decode("ascii")
    )
    return f"v1.{encoded}.{signature}"


def _decode_cursor(
    value: str,
    *,
    key: bytes,
    environment_id: UUID,
    creator_party_id: UUID,
    limit: int,
) -> tuple[str, UUID]:
    try:
        prefix, encoded, signature = value.split(".")
        if prefix != "v1":
            raise ValueError
        payload = base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4))
        actual = base64.urlsafe_b64decode(signature + "=" * (-len(signature) % 4))
        expected = hmac.new(key, payload, hashlib.sha256).digest()
        if not hmac.compare_digest(actual, expected):
            raise ValueError
        raw_document = json.loads(payload)
        if type(raw_document) is not dict:
            raise ValueError
        document = cast(dict[str, object], raw_document)
        if (
            set(document)
            != {
                "schema_version",
                "environment_id",
                "creator_party_id",
                "limit",
                "created_at",
                "capability_request_id",
            }
            or document["schema_version"] != "armi.capability-request-cursor.v1"
            or document["environment_id"] != str(environment_id)
            or document["creator_party_id"] != str(creator_party_id)
            or document["limit"] != limit
        ):
            raise ValueError
        request_id_text = document["capability_request_id"]
        if type(request_id_text) is not str:
            raise ValueError
        request_id = UUID(request_id_text)
        if request_id.version != 7 or str(request_id) != request_id_text:
            raise ValueError
        created_at = document["created_at"]
        if type(created_at) is not str or len(created_at) > 64:
            raise ValueError
        return created_at, request_id
    except TypeError, ValueError, UnicodeDecodeError, json.JSONDecodeError:
        raise CapabilityViolation("CON-CAPABILITY-CURSOR") from None


__all__ = ("PostgreSQLCreatorGrantPolicy",)
