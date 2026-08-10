"""PostgreSQL owner for the minimal T-04 capability policy."""

import asyncio
import base64
import contextlib
import hashlib
import hmac
import json
import secrets
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
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
    CodexDelegatedWorkScope,
    CreatorEventResourceKind,
    CreatorEventViolation,
    CreatorGrantCommand,
    CreatorGrantDecision,
    CreatorGrantResult,
    CreatorProjectionInvalidation,
    CreatorProjectionNotifier,
    CreatorSceneReplyScope,
    GrantStatus,
    PermissionGrant,
    PermissionGrantId,
    RuntimeFence,
    WorkDraft,
    WorkId,
    WorkOwner,
    WorkPayloadRef,
)
from armi_kernel.contracts import (
    Digest,
    IdempotencyKey,
    Instant,
    Purpose,
    SubjectId,
    TraceId,
)

from .unit_of_work import PostgreSQLUnitOfWorkFactory


class PostgreSQLCreatorGrantPolicy:
    """Apply exact Creator decisions; never dispatch or execute the capability."""

    __slots__ = ("_cursor_key", "_environment_id", "_factory", "_notifier", "_stop")

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
        notifier: CreatorProjectionNotifier | None = None,
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
            cursor_key, b"armi.creator.capability-request.cursor-key.v4", hashlib.sha256
        ).digest()
        self._environment_id = environment_id
        self._notifier = notifier
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
                           request.created_at,
                           CASE
                             WHEN request.current_status IN ('granted', 'limited')
                              AND permission.valid_until <= statement_timestamp()
                             THEN permission.valid_until
                             WHEN request.current_status = 'pending'
                             THEN request.created_at
                             ELSE request.resolved_at
                           END,
                           permission.grant_id,
                           capability.availability_status,
                           decision.reason_code,
                           CASE
                             WHEN permission.status = 'active'
                              AND permission.valid_until <= statement_timestamp()
                             THEN 'expired'
                             ELSE permission.status
                           END,
                           CASE
                             WHEN permission.status = 'expired'
                               OR (permission.status = 'active'
                                AND permission.valid_until <= statement_timestamp())
                             THEN permission.valid_until
                             ELSE permission.revoked_at
                           END,
                           permission.valid_from, permission.valid_until,
                           permission.max_uses, permission.consumed_uses,
                           permission.max_payload_bytes,
                           permission.workspace_scope,
                           permission.artifact_scope,
                           permission.network_access
                    FROM armi.capability_requests AS request
                    JOIN armi.capabilities AS capability
                      ON capability.capability_id = request.capability_id
                    LEFT JOIN armi.permission_grants AS permission
                      ON permission.capability_request_id = request.capability_request_id
                    LEFT JOIN LATERAL (
                      SELECT item.reason_code
                      FROM armi.capability_request_decisions AS item
                      WHERE item.capability_request_id = request.capability_request_id
                      ORDER BY item.resulting_request_version DESC
                      LIMIT 1
                    ) AS decision ON true
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
                "status_changed_at": row[17],
                "capability_availability": str(row[19]),
                "resolution_reason_code": (
                    str(row[20]).upper().replace("_", "-")
                    if row[20] is not None
                    else None
                ),
                "effective_grant": (
                    (
                        {
                            "scope_kind": "creator_scene_reply",
                            "grant_ref": str(row[18]),
                            "status": str(row[21]),
                            "ended_at": row[22],
                            "valid_from": row[23],
                            "valid_until": row[24],
                            "max_uses": int(row[25]),
                            "consumed_uses": int(row[26]),
                            "remaining_uses": int(row[25]) - int(row[26]),
                            "max_payload_bytes": int(row[27]),
                        }
                        if str(row[1]) == "creator.scene.reply"
                        else {
                            "scope_kind": "codex_delegated_work",
                            "grant_ref": str(row[18]),
                            "status": str(row[21]),
                            "ended_at": row[22],
                            "valid_from": row[23],
                            "valid_until": row[24],
                            "max_uses": int(row[25]),
                            "consumed_uses": int(row[26]),
                            "remaining_uses": int(row[25]) - int(row[26]),
                            "workspace_scope": row[28],
                            "artifact_scope": row[29],
                            "network_access": row[30],
                        }
                    )
                    if row[18] is not None
                    else None
                ),
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
                               request.workspace_scope, request.artifact_scope,
                               request.network_access,
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
                if int(request[17]) != command.expected_version:
                    raise CapabilityViolation("CONFLICT-POLICY-VERSION")
                current = CapabilityRequestStatus(str(request[16]))
                _validate_transition(command.decision, current)
                capability = CapabilityKind(str(request[5]))
                if str(request[18]) != "available" and command.decision in {
                    CreatorGrantDecision.GRANT,
                    CreatorGrantDecision.LIMIT,
                }:
                    raise CapabilityViolation("CAPABILITY-UNAVAILABLE")

                now_row = await (
                    await connection.execute("SELECT statement_timestamp()")
                ).fetchone()
                if now_row is None:
                    raise CapabilityViolation("POLICY-DATABASE")
                now = now_row[0]
                resulting_version = command.expected_version + 1
                grant: PermissionGrant | None = None
                cancelled_effects: tuple[tuple[UUID, UUID, UUID], ...] = ()
                cancellation_grant_id: UUID | None = None
                result_status: CapabilityRequestStatus
                if command.decision in {
                    CreatorGrantDecision.GRANT,
                    CreatorGrantDecision.LIMIT,
                }:
                    duration = int(request[10])
                    uses = int(request[11])
                    payload_bytes = (
                        int(request[12]) if request[12] is not None else None
                    )
                    if command.decision is CreatorGrantDecision.LIMIT:
                        if capability is CapabilityKind.CREATOR_SCENE_REPLY:
                            assert payload_bytes is not None
                            original = (duration, uses, payload_bytes)
                            duration = _narrow(command.valid_for_seconds, duration)
                            uses = _narrow(command.max_uses, uses)
                            payload_bytes = _narrow(
                                command.max_payload_bytes, payload_bytes
                            )
                            if (duration, uses, payload_bytes) == original:
                                raise CapabilityViolation("POLICY-SCOPE-EXPANSION")
                        else:
                            if (
                                command.max_uses is not None
                                or command.max_payload_bytes is not None
                            ):
                                raise CapabilityViolation("POLICY-SCOPE-EXPANSION")
                            narrowed = _narrow(command.valid_for_seconds, duration)
                            if narrowed == duration:
                                raise CapabilityViolation("POLICY-SCOPE-EXPANSION")
                            duration = narrowed
                        result_status = CapabilityRequestStatus.LIMITED
                    else:
                        result_status = CapabilityRequestStatus.GRANTED
                    scope = (
                        CreatorSceneReplyScope(
                            request[1],
                            request[2],
                            request[3],
                            duration,
                            uses,
                            cast(int, payload_bytes),
                        )
                        if capability is CapabilityKind.CREATOR_SCENE_REPLY
                        else CodexDelegatedWorkScope(
                            duration,
                            str(request[13]),
                            str(request[14]),
                            bool(request[15]),
                            uses,
                        )
                    )
                    grant_id = PermissionGrantId(uuid7())
                    valid_until = now + timedelta(seconds=duration)
                    await connection.execute(
                        """
                        INSERT INTO armi.permission_grants (
                            grant_id, capability_request_id, creator_party_id,
                            capability_id, subject_id, interaction_scene_id,
                            operation_class, audience_scope, data_scope, purpose,
                            workspace_scope, artifact_scope, network_access,
                            valid_from, valid_until, max_uses, max_payload_bytes) VALUES (
                            %s, %s, %s, %s, %s, %s, %s, %s,
                            %s, %s, %s, %s, %s,
                            %s, %s, %s, %s)
                        """,
                        (
                            grant_id.value,
                            request[0],
                            request[3],
                            request[4],
                            request[1],
                            request[2],
                            CapabilityOperation.SEND.value
                            if capability is CapabilityKind.CREATOR_SCENE_REPLY
                            else CapabilityOperation.EXECUTE.value,
                            "creator"
                            if capability is CapabilityKind.CREATOR_SCENE_REPLY
                            else None,
                            "creator_visible_response"
                            if capability is CapabilityKind.CREATOR_SCENE_REPLY
                            else None,
                            "respond_to_creator"
                            if capability is CapabilityKind.CREATOR_SCENE_REPLY
                            else "delegate_codex_work",
                            None
                            if capability is CapabilityKind.CREATOR_SCENE_REPLY
                            else "isolated_ephemeral",
                            None
                            if capability is CapabilityKind.CREATOR_SCENE_REPLY
                            else "explicit_only",
                            None
                            if capability is CapabilityKind.CREATOR_SCENE_REPLY
                            else False,
                            now,
                            valid_until,
                            uses,
                            payload_bytes,
                        ),
                    )
                    grant = PermissionGrant(
                        grant_id,
                        command.request_id,
                        capability,
                        CapabilityOperation.SEND
                        if capability is CapabilityKind.CREATOR_SCENE_REPLY
                        else CapabilityOperation.EXECUTE,
                        UUID(str(request[1])),
                        UUID(str(request[2])),
                        UUID(str(request[3])),
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
                    cancellation_grant_id = UUID(str(revoked[0]))
                    cancelled_effects = await _cancel_registered_effects(
                        connection,
                        grant_id=cancellation_grant_id,
                        reason_code="POLICY-GRANT-REVOKED",
                    )

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
                        reason_code) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        command.decision_id.value,
                        request[0],
                        request[3],
                        command.expected_version,
                        resulting_version,
                        command.decision.value,
                        command_digest.value,
                        command.reason_code,
                    ),
                )
                if (
                    grant is not None
                    and capability is CapabilityKind.CODEX_DELEGATED_WORK
                ):
                    await _activate_codex_registration(
                        unit_of_work,
                        capability_request_id=UUID(str(request[0])),
                        grant_id=grant.grant_id.value,
                        valid_until=grant.valid_until,
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
                        grant=AuditReference("permission_grant", grant.grant_id.value)
                        if grant
                        else None,
                    )
                )
                for (
                    effect_id,
                    subject_id,
                    _root_operation_id,
                ) in cancelled_effects:
                    assert cancellation_grant_id is not None
                    await unit_of_work.audit.append(
                        AuditDraft(
                            AuditEventId(uuid7()),
                            AuditReference("creator", request[3]),
                            Purpose("respond_to_creator"),
                            "effect.cancelled",
                            AuditReference("effect", effect_id),
                            AuditResultStatus.APPLIED,
                            TraceId(secrets.token_hex(16)),
                            AuditSensitivity.PRIVATE,
                            subject_id=SubjectId(subject_id),
                            grant=AuditReference(
                                "permission_grant", cancellation_grant_id
                            ),
                        )
                    )
                return CreatorGrantResult(
                    command.request_id,
                    resulting_version,
                    result_status,
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

        expired_request_ids: list[UUID] = []
        cancelled_projection_refs: list[tuple[UUID, UUID]] = []
        async with self._factory.unit_of_work(LockPlan()) as unit_of_work:
            connection = unit_of_work._connection_for_repository()  # pyright: ignore[reportPrivateUsage]
            rows = await (
                await connection.execute(
                    """
                    SELECT permission.grant_id,
                           permission.capability_request_id,
                           permission.creator_party_id,
                           permission.subject_id,
                           request.request_version
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
                cancelled_effects = await _cancel_registered_effects(
                    connection,
                    grant_id=UUID(str(row[0])),
                    reason_code="POLICY-GRANT-EXPIRED",
                )
                expired_request_ids.append(UUID(str(row[1])))
                await connection.execute(
                    """
                    INSERT INTO armi.capability_request_decisions (
                        capability_decision_id, capability_request_id,
                        creator_party_id, expected_request_version,
                        resulting_request_version, decision_kind, command_digest,
                        reason_code) VALUES (%s, %s, %s, %s, %s, 'expire', %s,
                              'grant_expired')
                    """,
                    (
                        decision_id,
                        row[1],
                        row[2],
                        int(row[4]),
                        int(row[4]) + 1,
                        command_digest.value,
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
                        grant=AuditReference("permission_grant", row[0]),
                    )
                )
                for (
                    effect_id,
                    subject_id,
                    root_operation_id,
                ) in cancelled_effects:
                    cancelled_projection_refs.append((effect_id, root_operation_id))
                    await unit_of_work.audit.append(
                        AuditDraft(
                            AuditEventId(uuid7()),
                            AuditReference("runtime", self._environment_id),
                            Purpose("respond_to_creator"),
                            "effect.cancelled",
                            AuditReference("effect", effect_id),
                            AuditResultStatus.APPLIED,
                            TraceId(secrets.token_hex(16)),
                            AuditSensitivity.PRIVATE,
                            subject_id=SubjectId(subject_id),
                            grant=AuditReference("permission_grant", row[0]),
                        )
                    )
        await self._notify_expiry(expired_request_ids, cancelled_projection_refs)
        return len(expired_request_ids)

    async def _notify_expiry(
        self,
        request_ids: list[UUID],
        cancelled_refs: list[tuple[UUID, UUID]],
    ) -> None:
        if self._notifier is None:
            return
        now = Instant(datetime.now(UTC))
        invalidations = [
            CreatorProjectionInvalidation(
                CreatorEventResourceKind.CAPABILITY_REQUEST,
                str(request_id),
                now,
                "capability-request.v4",
            )
            for request_id in request_ids
        ]
        for effect_id, root_operation_id in cancelled_refs:
            invalidations.extend(
                (
                    CreatorProjectionInvalidation(
                        CreatorEventResourceKind.EFFECT,
                        str(effect_id),
                        now,
                        "creator-effect.v2",
                    ),
                    CreatorProjectionInvalidation(
                        CreatorEventResourceKind.OPERATION,
                        str(root_operation_id),
                        now,
                        "creator-operation.v1",
                    ),
                )
            )
        for invalidation in invalidations:
            try:
                await self._notifier.notify(invalidation)
            except CreatorEventViolation:
                continue


async def _cancel_registered_effects(
    connection: Any,
    *,
    grant_id: UUID,
    reason_code: str,
) -> tuple[tuple[UUID, UUID, UUID], ...]:
    rows = await (
        await connection.execute(
            """
            SELECT effect.effect_id, effect.subject_id,
                   effect.action_intent_revision_id,
                   effect.operation_id,
                   effect.policy_decision_id,
                   response.root_opportunity_id,
                   effect.destination_kind
            FROM armi.effects AS effect
            JOIN armi.action_operations AS response
              ON response.operation_id
               = effect.operation_id
            JOIN armi.policy_decisions AS policy
              ON policy.policy_decision_id = effect.policy_decision_id
             AND policy.is_current
            JOIN armi.effect_outbox_items AS effect_outbox
              ON effect_outbox.effect_id = effect.effect_id
            WHERE policy.matched_grant_id = %s
              AND effect.status = 'registered'
              AND effect_outbox.status = 'ready'
            ORDER BY effect.effect_id
            FOR UPDATE OF effect, policy, effect_outbox
            """,
            (grant_id,),
        )
    ).fetchall()
    cancelled: list[tuple[UUID, UUID, UUID]] = []
    for row in rows:
        effect_id = UUID(str(row[0]))
        subject_id = UUID(str(row[1]))
        action_revision_id = UUID(str(row[2]))
        operation_id = UUID(str(row[3]))
        prior_decision_id = UUID(str(row[4]))
        root_operation_id = UUID(str(row[5]))
        destination_kind = str(row[6])
        decision_id = uuid7()
        cancellation_digest = Digest.from_bytes(
            rfc8785.dumps(
                cast(
                    Any,
                    {
                        "schema_version": "armi.effect-cancellation.v1",
                        "effect_id": str(effect_id),
                        "grant_id": str(grant_id),
                        "reason_code": reason_code,
                    },
                )
            )
        )
        await connection.execute(
            "UPDATE armi.policy_decisions SET is_current=false WHERE policy_decision_id=%s AND is_current",
            (prior_decision_id,),
        )
        await connection.execute(
            """
            INSERT INTO armi.policy_decisions (
                policy_decision_id, action_intent_revision_id,
                operation_id, decision_outcome,
                policy_identity, reason_code,
                supersedes_policy_decision_id) VALUES (
                %s, %s, %s, 'denied', 'armi.policy-engine.deterministic-v1',
                %s, %s)
            """,
            (
                decision_id,
                action_revision_id,
                operation_id,
                reason_code,
                prior_decision_id,
            ),
        )
        await connection.execute(
            """
            INSERT INTO armi.effect_attempts (
                effect_attempt_id, effect_id, attempt_no, adapter_binding,
                claim_token, dispatch_state, result_status,
                error_code, settled_at
            ) VALUES (
                %s, %s, 1, %s, 1, 'settled', 'cancelled', NULL,
                statement_timestamp()
            )
            """,
            (
                attempt_id := uuid7(),
                effect_id,
                (
                    "armi.codex-runner.openai-python-sdk-v1"
                    if destination_kind == "codex_workspace"
                    else "armi.local-inbox-adapter.postgresql-v1"
                ),
            ),
        )
        await connection.execute(
            """
            INSERT INTO armi.effect_observations (
                effect_observation_id, effect_id, effect_attempt_id,
                observation_kind, reliability, receiver_ref,
                observation_digest
            ) VALUES (%s, %s, %s, 'runner_cancelled', 'reliable', NULL, %s)
            """,
            (
                observation_id := uuid7(),
                effect_id,
                attempt_id,
                cancellation_digest.value,
            ),
        )
        await connection.execute(
            """
            UPDATE armi.effects
            SET status='cancelled', verification_status='verified',
                current_attempt_id=%s, current_observation_id=%s,
                settled_at=statement_timestamp(),
                cancelled_at=statement_timestamp()
            WHERE effect_id=%s AND status='registered'
            """,
            (
                attempt_id,
                observation_id,
                effect_id,
            ),
        )
        await connection.execute(
            """
            UPDATE armi.effect_outbox_items
            SET status='cancelled', cancelled_at=statement_timestamp()
            WHERE effect_id=%s AND status='ready'
            """,
            (effect_id,),
        )
        await connection.execute(
            """
            UPDATE armi.action_operations
            SET phase='terminal', outcome='cancelled',
                current_policy_decision_id=%s,
                completed_at=statement_timestamp()
            WHERE operation_id=%s
              AND phase='effect_registered' AND outcome IS NULL
            """,
            (decision_id, operation_id),
        )
        cancelled.append((effect_id, subject_id, root_operation_id))
    return tuple(cancelled)


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


async def _activate_codex_registration(
    unit_of_work: Any,
    *,
    capability_request_id: UUID,
    grant_id: UUID,
    valid_until: datetime,
) -> None:
    connection = unit_of_work._connection_for_repository()  # pyright: ignore[reportPrivateUsage]
    row = await (
        await connection.execute(
            """
            SELECT operation.operation_id, operation.subject_id,
                   revision.task_manifest_digest, revision.codex_task_source_id,
                   commit.trace_id
            FROM armi.capability_requests AS request
            JOIN armi.action_intent_revisions AS revision
              ON revision.subject_commit_id = request.subject_commit_id
             AND revision.capability_kind = 'codex.delegated-work'
            JOIN armi.action_intents AS intent
              ON intent.current_revision_id = revision.action_intent_revision_id
            JOIN armi.action_operations AS operation
              ON operation.action_intent_id = intent.action_intent_id
             AND operation.operation_kind = 'codex_delegation'
            JOIN armi.subject_commits AS commit
              ON commit.subject_commit_id = request.subject_commit_id
            WHERE request.capability_request_id = %s
              AND operation.phase = 'admission_pending'
              AND operation.outcome IS NULL
              AND operation.operation_kind = 'codex_delegation'
            FOR UPDATE OF operation
            """,
            (capability_request_id,),
        )
    ).fetchone()
    if row is None:
        return
    now_row = await (
        await connection.execute("SELECT statement_timestamp()")
    ).fetchone()
    if now_row is None or valid_until <= now_row[0]:
        raise CapabilityViolation("POLICY-GRANT-NOT-ACTIVE")
    registration_work_digest = Digest.from_bytes(
        rfc8785.dumps(
            cast(
                Any,
                {
                    "schema_version": "armi.codex-delegation.v1",
                    "operation_id": str(row[0]),
                    "task_source_id": str(row[3]),
                    "task_manifest_digest": str(row[2]),
                    "grant_id": str(grant_id),
                    "delivery_state": "not_started",
                },
            )
        )
    )
    work_id = WorkId(uuid7())
    await unit_of_work.work.enqueue(
        WorkDraft(
            work_id,
            "effect.register",
            WorkOwner("creator_response_operation", row[0]),
            IdempotencyKey(f"effect-register:{row[0]}"),
            registration_work_digest,
            60,
            Instant(now_row[0]),
            Instant(valid_until),
            2,
            TraceId(str(row[4])),
            subject_id=SubjectId(row[1]),
            payload=WorkPayloadRef("creator_response_operation", row[0]),
        )
    )
    updated = await (
        await connection.execute(
            """
            UPDATE armi.action_operations
            SET phase = 'admitted', outcome = NULL, matched_grant_id = %s,
                completed_at = statement_timestamp(),
                registration_work_id = %s
            WHERE operation_id = %s
              AND phase = 'admission_pending' AND outcome IS NULL
              AND operation_kind = 'codex_delegation'
            RETURNING operation_id
            """,
            (grant_id, work_id.value, row[0]),
        )
    ).fetchone()
    if updated is None:
        raise CapabilityViolation("CONFLICT-POLICY-VERSION")


async def _load_result(
    connection: Any, request_id: CapabilityRequestId
) -> CreatorGrantResult:
    row = await (
        await connection.execute(
            """
            SELECT request.request_version, request.current_status,
                   request.capability_kind,
                   request.operation_class, request.subject_id,
                   request.interaction_scene_id, request.creator_party_id,
                   permission.grant_id, permission.valid_from, permission.valid_until,
                   permission.max_uses, permission.consumed_uses,
                   permission.max_payload_bytes, permission.workspace_scope,
                   permission.artifact_scope, permission.network_access,
                   permission.status
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
        if row[7] is None:
            raise CapabilityViolation("POLICY-RESULT-MISSING")
        capability = CapabilityKind(str(row[2]))
        scope = (
            CreatorSceneReplyScope(
                row[4],
                row[5],
                row[6],
                int((row[9] - row[8]).total_seconds()),
                int(row[10]),
                int(row[12]),
            )
            if capability is CapabilityKind.CREATOR_SCENE_REPLY
            else CodexDelegatedWorkScope(
                int((row[9] - row[8]).total_seconds()),
                str(row[13]),
                str(row[14]),
                bool(row[15]),
                int(row[10]),
            )
        )
        grant = PermissionGrant(
            PermissionGrantId(row[7]),
            request_id,
            capability,
            CapabilityOperation(str(row[3])),
            UUID(str(row[4])),
            UUID(str(row[5])),
            UUID(str(row[6])),
            scope,
            row[8],
            row[9],
            int(row[11]),
            GrantStatus(str(row[16])),
        )
    return CreatorGrantResult(
        request_id,
        int(row[0]),
        status,
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
                "schema_version": "armi.capability-request-cursor.v4",
                "projection_version": "capability-request.v4",
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
                "projection_version",
            }
            or document["schema_version"] != "armi.capability-request-cursor.v4"
            or document["projection_version"] != "capability-request.v4"
            or document["environment_id"] != str(environment_id)
            or document["creator_party_id"] != str(creator_party_id)
            or document["limit"] != limit
        ):
            if document.get("schema_version") in {
                "armi.capability-request-cursor.v1",
                "armi.capability-request-cursor.v2",
                "armi.capability-request-cursor.v3",
            }:
                raise CapabilityViolation("CONFLICT-CAPABILITY-CURSOR-STALE")
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
