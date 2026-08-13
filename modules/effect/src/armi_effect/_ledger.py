"""PostgreSQL owner for T-05 policy and effect registration."""

from __future__ import annotations

from typing import Any, Literal, cast
from uuid import UUID, uuid7

import rfc8785
from armi_capability.api import (
    CapabilityAuthorizationOutcome,
    CapabilityConsumptionRequest,
    CapabilityEffectAuthorizationPort,
)
from armi_expression.api import (
    DeclaredResponseEffectDraft,
    ExpressionEffectLinkPort,
    ExpressionIntentReadPort,
)
from armi_kernel.application import (
    AuditDraft,
    AuditEventId,
    AuditReference,
    AuditResultStatus,
    AuditSensitivity,
    WorkLease,
    WorkRecord,
    WorkResultRef,
)
from armi_kernel.contracts import Digest, Instant, Purpose, SubjectId
from armi_runtime_foundation import (
    PostgreSQLRuntimeUnitOfWork,
    PostgreSQLTransaction,
)

from .api import (
    EffectId,
    EffectLedgerSnapshot,
    EffectObservationKind,
    EffectObservationReliability,
    EffectRegistrationContext,
    EffectRegistrationResult,
    EffectStatus,
    EffectVerificationStatus,
    EffectView,
    EffectViolation,
    PolicyDecisionId,
)


class PostgreSQLDeclaredResponseEffectRegistration:
    """Own immediate effect registration for already-admitted social responses."""

    __slots__ = ()

    async def register_declared_response(
        self,
        transaction: PostgreSQLTransaction,
        draft: DeclaredResponseEffectDraft,
    ) -> UUID:
        effect_id = uuid7()
        registration_digest = Digest.from_bytes(
            rfc8785.dumps(
                {
                    "effect_id": str(effect_id),
                    "revision_id": str(draft.action_intent_revision_id),
                    "scene_id": str(draft.scene_id),
                    "other_party_id": str(draft.context_party_id),
                    "destination_party_id": str(draft.destination_party_id),
                    "destination_binding_id": (
                        None
                        if draft.destination_binding_id is None
                        else str(draft.destination_binding_id)
                    ),
                    "response_digest": draft.payload_digest.value,
                }
            )
        )
        await transaction.execute(
            """
            INSERT INTO armi.effects (
                effect_id, action_intent_revision_id, action_intent_id,
                subject_id, scene_id, context_party_id, payload_artifact_id,
                payload_digest, payload_bytes,
                effect_kind, capability_kind, operation_class, audience_scope,
                data_scope, purpose, authorization_basis, destination_kind,
                destination_party_id, destination_binding_id,
                status, verification_status,
                registration_digest, trace_id) VALUES (
                %s, %s, %s, %s, %s, %s, %s, %s, %s,
                %s, %s, 'send', %s, 'declared_party_response',
                'respond_to_other_human', %s, %s, %s, %s,
                'registered', 'not_started', %s, %s)
            """,
            (
                effect_id,
                draft.action_intent_revision_id,
                draft.action_intent_id,
                draft.subject_id,
                draft.scene_id,
                draft.context_party_id,
                draft.payload_artifact_id,
                draft.payload_digest.value,
                draft.payload_bytes,
                draft.effect_kind,
                draft.capability_kind,
                draft.audience_scope,
                draft.authorization_basis,
                draft.destination_kind,
                draft.destination_party_id,
                draft.destination_binding_id,
                registration_digest.value,
                draft.trace_id.value,
            ),
        )
        await transaction.execute(
            """
            INSERT INTO armi.effect_outbox_items (
                effect_outbox_item_id, effect_id, message_kind,
                status, dispatch_deadline, max_attempts) VALUES (
                %s, %s, 'effect.dispatch', 'ready',
                statement_timestamp() + interval '1 hour', %s)
            """,
            (uuid7(), effect_id, draft.max_attempts),
        )
        return effect_id


class PostgreSQLEffectLedgerRepository:
    __slots__ = ("_authorization", "_effect_links", "_intents")

    def __init__(
        self,
        authorization: CapabilityEffectAuthorizationPort,
        intents: ExpressionIntentReadPort,
        effect_links: ExpressionEffectLinkPort,
    ) -> None:
        self._authorization = authorization
        self._intents = intents
        self._effect_links = effect_links

    async def by_action_intent(
        self,
        transaction: PostgreSQLTransaction,
        *,
        action_intent_id: UUID,
    ) -> EffectLedgerSnapshot | None:
        row = await (
            await transaction.execute(
                "SELECT effect_id FROM armi.effects WHERE action_intent_id=%s",
                (action_intent_id,),
            )
        ).fetchone()
        return (
            None
            if row is None
            else await self.by_effect_id(transaction, effect_id=row[0])
        )

    async def by_effect_id(
        self,
        transaction: PostgreSQLTransaction,
        *,
        effect_id: UUID,
    ) -> EffectLedgerSnapshot | None:
        row = await (
            await transaction.execute(
                """
                SELECT effect.effect_id, effect.action_intent_revision_id,
                       effect.action_intent_id, effect.policy_decision_id,
                       effect.subject_id, effect.scene_id, effect.context_party_id,
                       effect.payload_artifact_id, effect.payload_digest,
                       effect.payload_bytes, effect.effect_kind,
                       effect.capability_kind, effect.status,
                       effect.verification_status, effect.registered_at,
                       effect.cancelled_at, effect.settled_at,
                       (SELECT count(*) FROM armi.effect_attempts AS attempt
                        WHERE attempt.effect_id=effect.effect_id),
                       observation.observation_kind, observation.reliability
                FROM armi.effects AS effect
                LEFT JOIN armi.effect_observations AS observation
                  ON observation.effect_observation_id=effect.current_observation_id
                WHERE effect.effect_id=%s
                """,
                (effect_id,),
            )
        ).fetchone()
        if row is None:
            return None
        return EffectLedgerSnapshot(
            row[0],
            row[1],
            row[2],
            row[3],
            row[4],
            row[5],
            row[6],
            row[7],
            Digest(str(row[8])),
            int(row[9]),
            str(row[10]),
            str(row[11]),
            EffectStatus(str(row[12])),
            EffectVerificationStatus(str(row[13])),
            Instant(row[14]),
            None if row[15] is None else Instant(row[15]),
            None if row[16] is None else Instant(row[16]),
            int(row[17]),
            None if row[18] is None else EffectObservationKind(str(row[18])),
            None if row[19] is None else EffectObservationReliability(str(row[19])),
        )

    async def settle_current_work(
        self,
        unit_of_work: PostgreSQLRuntimeUnitOfWork,
        work: WorkRecord,
    ) -> None:
        connection = unit_of_work.transaction
        lease = work.lease
        if lease is None:
            return
        row = await (
            await connection.execute(
                """
                SELECT effect_id FROM armi.effects
                WHERE action_intent_id=%s
                """,
                (work.draft.owner.reference,),
            )
        ).fetchone()
        if row is not None:
            await unit_of_work.work.complete(
                lease,
                WorkResultRef("effect", row[0]),
            )
            return
        await self._fail_locked(unit_of_work, lease, "EFFECT-REGISTRATION-STATE")

    async def fail_current_work(
        self,
        unit_of_work: PostgreSQLRuntimeUnitOfWork,
        work: WorkRecord,
        *,
        code: str,
    ) -> None:
        lease = work.lease
        if lease is None:
            return
        await self._fail_locked(unit_of_work, lease, code)

    async def _fail_locked(
        self,
        unit_of_work: PostgreSQLRuntimeUnitOfWork,
        lease: WorkLease,
        code: str,
    ) -> None:
        await unit_of_work.work.fail(lease, error_code=code)

    async def settle(
        self,
        uow: PostgreSQLRuntimeUnitOfWork,
        *,
        lease: WorkLease,
        snapshot: EffectRegistrationContext,
        integrity_ok: bool,
    ) -> EffectRegistrationResult | None:
        connection = uow.transaction
        if uow.runtime_fence is None:
            raise EffectViolation("EFFECT-FENCE")
        intent = await self._intents.intent_snapshot(
            connection,
            action_intent_id=snapshot.action_intent_id,
        )
        if intent.operation_ref != snapshot.operation_ref:
            raise EffectViolation("EFFECT-WORK-STALE")
        registration_digest = _registration_digest(snapshot)
        existing = await self._existing(connection, snapshot, registration_digest)
        if existing is not None:
            await uow.work.complete(
                lease, WorkResultRef("effect", existing.effect_id.value)
            )
            return existing

        if integrity_ok:
            authorization = await self._authorization.authorize_effect(
                connection,
                action_intent_revision_id=snapshot.action_intent_revision_id,
                request=CapabilityConsumptionRequest(
                    capability_kind=snapshot.capability_kind,
                    operation_class=snapshot.operation_class,
                    subject_id=snapshot.subject_id,
                    scene_id=snapshot.scene_id,
                    creator_party_id=snapshot.context_party_id,
                    purpose=snapshot.purpose,
                    effect_kind=snapshot.effect_kind,
                    payload_bytes=snapshot.payload_bytes,
                ),
            )
        else:
            authorization = await self._authorization.record_effect_outcome(
                connection,
                action_intent_revision_id=snapshot.action_intent_revision_id,
                outcome=CapabilityAuthorizationOutcome.UNAVAILABLE,
                reason_code="POLICY-PAYLOAD-UNAVAILABLE",
            )
        outcome = authorization.outcome.value
        grant_id = authorization.grant_id
        valid_until = authorization.valid_until
        if authorization.outcome is CapabilityAuthorizationOutcome.ALLOWED:
            assert grant_id is not None and valid_until is not None

        decision_id = authorization.policy_decision_id
        result: EffectRegistrationResult | None = None
        if outcome == "allowed":
            effect_id, outbox_id = uuid7(), uuid7()
            row = await (
                await connection.execute(
                    """
                INSERT INTO armi.effects (
                    effect_id, action_intent_revision_id, action_intent_id,
                    policy_decision_id, subject_id, scene_id, context_party_id,
                    payload_artifact_id, payload_digest, payload_bytes, effect_kind,
                    capability_kind, operation_class, audience_scope, data_scope, purpose,
                    authorization_basis, destination_kind, destination_party_id,
                    destination_binding_id,
                    registration_digest, trace_id, status, verification_status) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,
                    %s,%s,%s,%s,%s,'creator_grant',%s,%s,%s,%s,%s,
                    'registered','not_started')
                RETURNING registered_at
                """,
                    (
                        effect_id,
                        snapshot.action_intent_revision_id,
                        snapshot.action_intent_id,
                        decision_id,
                        snapshot.subject_id,
                        snapshot.scene_id,
                        snapshot.context_party_id,
                        snapshot.payload_artifact_id,
                        snapshot.payload_digest.value,
                        snapshot.payload_bytes,
                        snapshot.effect_kind,
                        snapshot.capability_kind,
                        snapshot.operation_class,
                        "creator"
                        if snapshot.effect_kind == "creator_response"
                        else None,
                        "creator_visible_response"
                        if snapshot.effect_kind == "creator_response"
                        else None,
                        snapshot.purpose,
                        "creator_inbox"
                        if snapshot.effect_kind == "creator_response"
                        and snapshot.destination_binding_id is None
                        else "external_private"
                        if snapshot.effect_kind == "creator_response"
                        else "codex_workspace",
                        snapshot.destination_party_id,
                        snapshot.destination_binding_id,
                        registration_digest.value,
                        snapshot.trace_id.value,
                    ),
                )
            ).fetchone()
            row = cast(tuple[Any, ...], row)
            if snapshot.effect_kind == "creator_response":
                await self._effect_links.link_effect(
                    connection,
                    action_intent_id=snapshot.action_intent_id,
                    effect_id=effect_id,
                )
            await connection.execute(
                """
                INSERT INTO armi.effect_outbox_items (
                    effect_outbox_item_id, effect_id, message_kind,
                    status, dispatch_deadline, max_attempts) VALUES (%s, %s, 'effect.dispatch', 'ready', %s, %s)
                """,
                (
                    outbox_id,
                    effect_id,
                    valid_until,
                    1
                    if snapshot.effect_kind == "codex_delegation"
                    or snapshot.destination_binding_id is not None
                    else 2,
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
            await uow.work.complete(
                lease,
                WorkResultRef("creator_response_operation", snapshot.operation_ref),
            )
        await uow.audit.append(
            AuditDraft(
                AuditEventId(uuid7()),
                AuditReference("runtime", uow.environment_id),
                Purpose("effect.registration"),
                "effect.registration.settled",
                AuditReference("creator_response_operation", snapshot.operation_ref),
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
                grant=AuditReference("permission_grant", grant_id)
                if grant_id is not None
                else None,
            )
        )
        return result

    async def get_effect(
        self,
        uow: PostgreSQLRuntimeUnitOfWork,
        effect_id: EffectId,
        creator_party_id: UUID,
    ) -> EffectView:
        connection = uow.transaction
        row = await (
            await connection.execute(
                """
            SELECT effect.effect_id, effect.action_intent_id,
                   effect.action_intent_revision_id, effect.policy_decision_id,
                   effect.effect_kind, effect.capability_kind, effect.status,
                   effect.verification_status, effect.registered_at, effect.cancelled_at,
                   (SELECT count(*) FROM armi.effect_attempts AS attempt
                    WHERE attempt.effect_id = effect.effect_id),
                   observation.observation_kind, observation.reliability,
                   effect.settled_at
            FROM armi.effects AS effect
            LEFT JOIN armi.effect_observations AS observation
              ON observation.effect_observation_id = effect.current_observation_id
            WHERE effect.effect_id=%s AND effect.context_party_id=%s
            """,
                (effect_id.value, creator_party_id),
            )
        ).fetchone()
        if row is None:
            raise EffectViolation("SCOPE-EFFECT-NOT-VISIBLE")
        raw_effect_kind = str(row[4])
        if raw_effect_kind not in {"creator_response", "codex_delegation"}:
            raise EffectViolation("CON-EFFECT-KIND")
        effect_kind = cast(
            Literal["creator_response", "codex_delegation"], raw_effect_kind
        )
        return EffectView(
            effect_id=EffectId(row[0]),
            action_intent_ref=row[1],
            action_intent_revision_ref=row[2],
            policy_decision_ref=row[3],
            effect_kind=effect_kind,
            status=EffectStatus(str(row[6])),
            verification_status=EffectVerificationStatus(str(row[7])),
            registered_at=Instant(row[8]),
            capability_kind=cast(
                Literal["creator.scene.reply", "codex.delegated-work"], str(row[5])
            ),
            cancelled_at=Instant(row[9]) if row[9] is not None else None,
            attempt_count=int(row[10]),
            last_observation_kind=(
                EffectObservationKind(str(row[11])) if row[11] is not None else None
            ),
            last_observation_reliability=(
                EffectObservationReliability(str(row[12]))
                if row[12] is not None
                else None
            ),
            verification_action=(
                (
                    "verify_codex_result"
                    if effect_kind == "codex_delegation"
                    else "verify_creator_inbox"
                )
                if str(row[6]) == "unknown"
                else None
            ),
            settled_at=Instant(row[13]) if row[13] is not None else None,
        )

    async def payload_reference(
        self, uow: PostgreSQLRuntimeUnitOfWork, effect_id: EffectId
    ) -> tuple[UUID, Digest, int]:
        connection = uow.transaction
        row = await (
            await connection.execute(
                "SELECT payload_artifact_id, payload_digest, payload_bytes FROM armi.effects WHERE effect_id=%s AND status='completed'",
                (effect_id.value,),
            )
        ).fetchone()
        if row is None:
            raise EffectViolation("EFFECT-PAYLOAD-UNAVAILABLE")
        return row[0], Digest(str(row[1])), int(row[2])

    async def _existing(
        self,
        connection: Any,
        snapshot: EffectRegistrationContext,
        registration_digest: Digest,
    ) -> EffectRegistrationResult | None:
        row = await (
            await connection.execute(
                """
            SELECT effect.effect_id, effect.policy_decision_id, effect.status,
                   effect.verification_status, effect.registration_digest, effect.registered_at
            FROM armi.effects AS effect
            WHERE effect.action_intent_revision_id=%s AND effect.effect_kind=%s
            """,
                (snapshot.action_intent_revision_id, snapshot.effect_kind),
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


def _registration_digest(snapshot: EffectRegistrationContext) -> Digest:
    return Digest.from_bytes(
        rfc8785.dumps(
            cast(
                Any,
                {
                    "schema_version": "armi.effect-registration.v1",
                    "action_intent_revision_id": str(
                        snapshot.action_intent_revision_id
                    ),
                    "effect_kind": snapshot.effect_kind,
                    "subject_id": str(snapshot.subject_id),
                    "scene_id": str(snapshot.scene_id),
                    "creator_party_id": str(snapshot.context_party_id),
                    "payload_digest": snapshot.payload_digest.value,
                    "payload_bytes": snapshot.payload_bytes,
                    "purpose": snapshot.purpose,
                },
            )
        )
    )


__all__ = (
    "PostgreSQLDeclaredResponseEffectRegistration",
    "PostgreSQLEffectLedgerRepository",
)
