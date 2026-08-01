"""PostgreSQL owner for T-05 policy and effect registration."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, cast
from uuid import UUID, uuid7

import rfc8785
from armi_kernel.application import (
    AuditDraft,
    AuditEventId,
    AuditReference,
    AuditResultStatus,
    AuditSensitivity,
    EffectId,
    EffectRegistrationResult,
    EffectStatus,
    EffectVerificationStatus,
    EffectView,
    EffectViolation,
    PolicyDecisionId,
    WorkLease,
    WorkResultRef,
)
from armi_kernel.contracts import Digest, Instant, Purpose, SubjectId, TraceId

from .unit_of_work import PostgreSQLUnitOfWork


@dataclass(frozen=True, slots=True)
class EffectRegistrationSnapshot:
    operation_id: UUID
    root_operation_id: UUID
    action_revision_id: UUID
    subject_id: UUID
    scene_id: UUID
    creator_party_id: UUID
    artifact_id: UUID
    payload_digest: Digest
    payload_bytes: int
    trace_id: TraceId


class PostgreSQLEffectLedgerRepository:
    __slots__ = ()

    async def snapshot(
        self, uow: PostgreSQLUnitOfWork, lease: WorkLease
    ) -> EffectRegistrationSnapshot:
        connection = uow._connection_for_repository()  # pyright: ignore[reportPrivateUsage]
        row = await (
            await connection.execute(
                """
            SELECT operation.creator_response_operation_id, operation.root_opportunity_id,
                   revision.action_intent_revision_id, operation.subject_id,
                   operation.interaction_scene_id, operation.creator_party_id,
                   revision.response_artifact_id, revision.response_digest,
                   revision.response_bytes, work.trace_id
            FROM armi.durable_work AS work
            JOIN armi.creator_response_operations AS operation
              ON operation.registration_work_id = work.work_id
             AND operation.current_status = 'accepted'
            JOIN armi.action_intents AS intent ON intent.action_intent_id = operation.action_intent_id
            JOIN armi.action_intent_revisions AS revision
              ON revision.action_intent_revision_id = intent.current_revision_id
            WHERE work.work_id = %s AND work.work_kind = 'effect.register'
              AND work.status = 'leased' AND work.current_attempt_id = %s
              AND work.lease_owner = %s AND work.lease_token = %s
              AND work.lease_expires_at > statement_timestamp()
            """,
                (lease.work_id.value, lease.attempt_id.value, lease.owner, lease.token),
            )
        ).fetchone()
        if row is None:
            raise EffectViolation("EFFECT-WORK-STALE")
        return EffectRegistrationSnapshot(
            row[0],
            row[1],
            row[2],
            row[3],
            row[4],
            row[5],
            row[6],
            Digest(str(row[7])),
            int(row[8]),
            TraceId(str(row[9])),
        )

    async def settle(
        self,
        uow: PostgreSQLUnitOfWork,
        *,
        lease: WorkLease,
        snapshot: EffectRegistrationSnapshot,
        integrity_ok: bool,
    ) -> EffectRegistrationResult | None:
        connection = uow._connection_for_repository()  # pyright: ignore[reportPrivateUsage]
        if uow.runtime_fence is None:
            raise EffectViolation("EFFECT-FENCE")
        locked = await (
            await connection.execute(
                "SELECT current_status FROM armi.creator_response_operations WHERE creator_response_operation_id = %s FOR UPDATE",
                (snapshot.operation_id,),
            )
        ).fetchone()
        if locked is None:
            raise EffectViolation("EFFECT-WORK-STALE")
        registration_digest = _registration_digest(snapshot)
        existing = await self._existing(connection, snapshot, registration_digest)
        if existing is not None:
            await uow.work.complete(
                lease, WorkResultRef("effect", existing.effect_id.value)
            )
            return existing

        outcome = "denied"
        reason = "POLICY-GRANT-NOT-CURRENT"
        grant_id: UUID | None = None
        valid_until = None
        if not integrity_ok:
            outcome, reason = "unavailable", "POLICY-PAYLOAD-UNAVAILABLE"
        else:
            capability = await (
                await connection.execute(
                    "SELECT availability_status FROM armi.capabilities WHERE capability_kind = 'creator.scene.reply' AND operation_class = 'send'"
                )
            ).fetchone()
            if capability is None or str(capability[0]) != "available":
                outcome, reason = "unavailable", "POLICY-CAPABILITY-UNAVAILABLE"
            else:
                grant = await (
                    await connection.execute(
                        """
                    SELECT grant_id, valid_until FROM armi.permission_grants
                    WHERE subject_id = %s AND interaction_scene_id = %s AND creator_party_id = %s
                      AND operation_class = 'send' AND audience_scope = 'creator'
                      AND data_scope = 'creator_visible_response' AND purpose = 'respond_to_creator'
                      AND status = 'active' AND valid_from <= statement_timestamp()
                      AND statement_timestamp() < valid_until AND consumed_uses < max_uses
                      AND %s <= max_payload_bytes
                    ORDER BY valid_until, grant_id LIMIT 1 FOR UPDATE
                    """,
                        (
                            snapshot.subject_id,
                            snapshot.scene_id,
                            snapshot.creator_party_id,
                            snapshot.payload_bytes,
                        ),
                    )
                ).fetchone()
                if grant is not None:
                    grant_id, valid_until = grant[0], grant[1]
                    consumed = await (
                        await connection.execute(
                            """
                        UPDATE armi.permission_grants SET consumed_uses = consumed_uses + 1
                        WHERE grant_id = %s AND status = 'active'
                          AND statement_timestamp() < valid_until AND consumed_uses < max_uses
                        RETURNING consumed_uses
                        """,
                            (grant_id,),
                        )
                    ).fetchone()
                    if consumed is not None:
                        outcome, reason = "allowed", "POLICY-GRANT-ALLOWED"
                    else:
                        grant_id, valid_until = None, None

        decision_digest = Digest.from_bytes(
            rfc8785.dumps(
                cast(
                    Any,
                    {
                        "schema_version": "armi.policy-decision.v1",
                        "registration_digest": registration_digest.value,
                        "outcome": outcome,
                        "grant_ref": str(grant_id) if grant_id is not None else None,
                        "reason": reason,
                    },
                )
            )
        )
        decision_id = uuid7()
        await connection.execute(
            """
            INSERT INTO armi.policy_decisions (
                policy_decision_id, action_intent_revision_id, creator_response_operation_id,
                matched_grant_id, decision_outcome, policy_identity, decision_digest,
                reason_code, valid_until, schema_version
            ) VALUES (%s, %s, %s, %s, %s, 'armi.policy-engine.deterministic-v1', %s, %s, %s, 1)
            """,
            (
                decision_id,
                snapshot.action_revision_id,
                snapshot.operation_id,
                grant_id,
                outcome,
                decision_digest.value,
                reason,
                valid_until,
            ),
        )
        result: EffectRegistrationResult | None = None
        if outcome == "allowed":
            effect_id, outbox_id = uuid7(), uuid7()
            row = await (
                await connection.execute(
                    """
                INSERT INTO armi.effects (
                    effect_id, action_intent_revision_id, creator_response_operation_id,
                    policy_decision_id, subject_id, interaction_scene_id, creator_party_id,
                    payload_artifact_id, payload_digest, payload_bytes, effect_kind,
                    capability_kind, operation_class, audience_scope, data_scope, purpose,
                    registration_digest, status, verification_status, schema_version
                ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'creator_response',
                    'creator.scene.reply','send','creator','creator_visible_response',
                    'respond_to_creator',%s,'registered','not_started',1)
                RETURNING registered_at
                """,
                    (
                        effect_id,
                        snapshot.action_revision_id,
                        snapshot.operation_id,
                        decision_id,
                        snapshot.subject_id,
                        snapshot.scene_id,
                        snapshot.creator_party_id,
                        snapshot.artifact_id,
                        snapshot.payload_digest.value,
                        snapshot.payload_bytes,
                        registration_digest.value,
                    ),
                )
            ).fetchone()
            assert row is not None
            await connection.execute(
                "INSERT INTO armi.effect_outbox_items (effect_outbox_item_id,effect_id,message_kind,payload_digest,status,schema_version) VALUES (%s,%s,'effect.dispatch',%s,'ready',1)",
                (outbox_id, effect_id, registration_digest.value),
            )
            await connection.execute(
                """
                UPDATE armi.creator_response_operations SET current_status='effect_registered',
                    current_policy_decision_id=%s, effect_id=%s,
                    effect_registration_digest=%s, effect_registered_at=%s
                WHERE creator_response_operation_id=%s AND current_status='accepted'
                """,
                (
                    decision_id,
                    effect_id,
                    registration_digest.value,
                    row[0],
                    snapshot.operation_id,
                ),
            )
            await uow.work.complete(lease, WorkResultRef("effect", effect_id))
            result = EffectRegistrationResult(
                EffectId(effect_id),
                PolicyDecisionId(decision_id),
                EffectStatus.REGISTERED,
                EffectVerificationStatus.NOT_STARTED,
                registration_digest,
                Instant(row[0]),
            )
        else:
            status = "unauthorized" if outcome == "denied" else "unavailable"
            await connection.execute(
                "UPDATE armi.creator_response_operations SET current_status=%s, current_policy_decision_id=%s, reason_code=%s, completed_at=statement_timestamp() WHERE creator_response_operation_id=%s AND current_status='accepted'",
                (status, decision_id, reason, snapshot.operation_id),
            )
            await uow.work.complete(
                lease,
                WorkResultRef("creator_response_operation", snapshot.operation_id),
            )
        await uow.audit.append(
            AuditDraft(
                AuditEventId(uuid7()),
                AuditReference("runtime", uow.environment_id),
                Purpose("effect.registration"),
                "effect.registration.settled",
                AuditReference("creator_response_operation", snapshot.operation_id),
                AuditResultStatus.ACCEPTED
                if outcome == "allowed"
                else (
                    AuditResultStatus.REJECTED
                    if outcome == "denied"
                    else AuditResultStatus.UNAVAILABLE
                ),
                snapshot.trace_id,
                AuditSensitivity.PRIVATE,
                subject_id=SubjectId(snapshot.subject_id),
                request_digest=snapshot.payload_digest,
                response_digest=decision_digest,
                grant=AuditReference("permission_grant", grant_id)
                if grant_id is not None
                else None,
            )
        )
        return result

    async def get_effect(
        self, uow: PostgreSQLUnitOfWork, effect_id: EffectId, creator_party_id: UUID
    ) -> EffectView:
        connection = uow._connection_for_repository()  # pyright: ignore[reportPrivateUsage]
        row = await (
            await connection.execute(
                """
            SELECT effect_id, operation.root_opportunity_id, effect_kind, effect.status,
                   verification_status, registered_at, cancelled_at
            FROM armi.effects AS effect
            JOIN armi.creator_response_operations AS operation
              ON operation.creator_response_operation_id = effect.creator_response_operation_id
            WHERE effect.effect_id=%s AND effect.creator_party_id=%s
            """,
                (effect_id.value, creator_party_id),
            )
        ).fetchone()
        if row is None:
            raise EffectViolation("SCOPE-EFFECT-NOT-VISIBLE")
        return EffectView(
            EffectId(row[0]),
            row[1],
            str(row[2]),
            EffectStatus(str(row[3])),
            EffectVerificationStatus(str(row[4])),
            Instant(row[5]),
            Instant(row[6]) if row[6] is not None else None,
        )

    async def _existing(
        self,
        connection: Any,
        snapshot: EffectRegistrationSnapshot,
        registration_digest: Digest,
    ) -> EffectRegistrationResult | None:
        row = await (
            await connection.execute(
                """
            SELECT effect.effect_id, effect.policy_decision_id, effect.status,
                   effect.verification_status, effect.registration_digest, effect.registered_at
            FROM armi.effects AS effect
            WHERE effect.action_intent_revision_id=%s AND effect.effect_kind='creator_response'
            """,
                (snapshot.action_revision_id,),
            )
        ).fetchone()
        if row is None:
            return None
        if str(row[4]) != registration_digest.value:
            raise EffectViolation("EFFECT-IDEMPOTENCY-CONFLICT")
        return EffectRegistrationResult(
            EffectId(row[0]),
            PolicyDecisionId(row[1]),
            EffectStatus(str(row[2])),
            EffectVerificationStatus(str(row[3])),
            Digest(str(row[4])),
            Instant(row[5]),
        )


def _registration_digest(snapshot: EffectRegistrationSnapshot) -> Digest:
    return Digest.from_bytes(
        rfc8785.dumps(
            cast(
                Any,
                {
                    "schema_version": "armi.effect-registration.v1",
                    "action_intent_revision_id": str(snapshot.action_revision_id),
                    "effect_kind": "creator_response",
                    "subject_id": str(snapshot.subject_id),
                    "scene_id": str(snapshot.scene_id),
                    "creator_party_id": str(snapshot.creator_party_id),
                    "payload_digest": snapshot.payload_digest.value,
                    "payload_bytes": snapshot.payload_bytes,
                    "purpose": "respond_to_creator",
                },
            )
        )
    )


__all__ = ("EffectRegistrationSnapshot", "PostgreSQLEffectLedgerRepository")
