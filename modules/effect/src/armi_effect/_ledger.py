"""PostgreSQL owner for atomic effect registration and ledger reads."""

from __future__ import annotations

from typing import Literal, cast
from uuid import UUID, uuid7

import rfc8785
from armi_expression.api import (
    CodexEffectDraft,
    DeclaredResponseEffectDraft,
)
from armi_kernel.contracts import Digest, Instant
from armi_runtime_foundation import (
    PostgreSQLRuntimeUnitOfWork,
    PostgreSQLTransaction,
)

from .api import (
    EffectId,
    EffectLedgerSnapshot,
    EffectObservationKind,
    EffectObservationReliability,
    EffectStatus,
    EffectVerificationStatus,
    EffectView,
    EffectViolation,
)


class PostgreSQLDeclaredResponseEffectRegistration:
    """Own immediate effect registration for already-admitted social responses."""

    __slots__ = ()

    async def register_codex_delegation(
        self, transaction: PostgreSQLTransaction, draft: CodexEffectDraft
    ) -> UUID:
        task = draft.delegation
        effect_id = uuid7()
        digest = Digest.from_bytes(
            rfc8785.dumps(
                {
                    "action_intent_revision_id": str(draft.action_intent_revision_id),
                    "task_source_id": str(task.task_source_id),
                    "manifest_digest": task.task_manifest_digest.value,
                }
            )
        )
        await transaction.execute(
            """INSERT INTO armi.effects (
                effect_id,action_intent_id,action_intent_revision_id,
                subject_id,scene_id,context_party_id,payload_artifact_id,
                payload_digest,payload_bytes,effect_kind,capability_kind,
                operation_class,purpose,authorization_basis,destination_kind,
                destination_party_id,registration_digest,trace_id,status,verification_status)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,'codex_delegation',
                 'codex.delegated-work','execute','delegate_codex_work',
                 'runtime_configuration','codex_workspace',%s,%s,%s,'registered','not_started')""",
            (
                effect_id,
                draft.action_intent_id,
                draft.action_intent_revision_id,
                task.subject_id,
                task.scene_id,
                task.creator_party_id,
                task.task_manifest_artifact_id,
                task.task_manifest_digest.value,
                task.task_manifest_bytes,
                task.creator_party_id,
                digest.value,
                task.trace_id.value,
            ),
        )
        await transaction.execute(
            """INSERT INTO armi.effect_outbox_items (
                effect_outbox_item_id,effect_id,message_kind,status,dispatch_deadline,max_attempts)
               VALUES (%s,%s,'effect.dispatch','ready',NULL,1)""",
            (uuid7(), effect_id),
        )
        return effect_id

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
                live_voice_turn_id, status, verification_status,
                registration_digest, trace_id) VALUES (
                %s, %s, %s, %s, %s, %s, %s, %s, %s,
                %s, %s, 'send', %s, %s,
                %s, %s, %s, %s, %s,
                %s, 'registered', 'not_started', %s, %s)
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
                "creator_visible_response"
                if draft.effect_kind == "creator_response"
                else "declared_party_response",
                "respond_to_creator"
                if draft.effect_kind == "creator_response"
                else "respond_to_other_human",
                draft.authorization_basis,
                draft.destination_kind,
                draft.destination_party_id,
                draft.destination_binding_id,
                draft.live_voice_turn_id,
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
                CASE WHEN %s THEN NULL ELSE statement_timestamp() + interval '1 hour' END, %s)
            """,
            (
                uuid7(),
                effect_id,
                draft.effect_kind == "creator_response",
                draft.max_attempts,
            ),
        )
        return effect_id


class PostgreSQLEffectLedgerRepository:
    __slots__ = ()

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
                       effect.action_intent_id, effect.subject_id, effect.scene_id, effect.context_party_id,
                       effect.payload_artifact_id, effect.payload_digest,
                       effect.payload_bytes, effect.effect_kind,
                       effect.capability_kind, effect.status,
                       effect.verification_status, effect.registered_at,
                       effect.cancelled_at, effect.settled_at,
                       (SELECT count(*) FROM armi.effect_attempts AS attempt
                        WHERE attempt.effect_id=effect.effect_id),
                       observation.observation_kind, observation.reliability,
                       attempt.effect_attempt_id,attempt.attempt_no,
                       attempt.dispatch_state,observation.effect_observation_id,
                       observation.conclusion,CASE WHEN outbox.last_error_code='EFFECT-RUNTIME-INTERRUPTED' THEN outbox.last_error_code ELSE COALESCE(observation.reason_code,outbox.last_error_code) END,
                       observation.evidence_kind
                FROM armi.effects AS effect
                JOIN armi.effect_outbox_items AS outbox ON outbox.effect_id=effect.effect_id
                LEFT JOIN armi.effect_observations AS observation
                  ON observation.effect_observation_id=effect.current_observation_id
                LEFT JOIN armi.effect_attempts AS attempt
                  ON attempt.effect_attempt_id=effect.current_attempt_id
                WHERE effect.effect_id=%s
                """,
                (effect_id,),
            )
        ).fetchone()
        if row is None:
            return None
        return EffectLedgerSnapshot(
            effect_id=row[0],
            action_intent_revision_id=row[1],
            action_intent_id=row[2],
            subject_id=row[3],
            scene_id=row[4],
            context_party_id=row[5],
            payload_artifact_id=row[6],
            payload_digest=Digest(str(row[7])),
            payload_bytes=int(row[8]),
            effect_kind=str(row[9]),
            capability_kind=str(row[10]),
            status=EffectStatus(str(row[11])),
            verification_status=EffectVerificationStatus(str(row[12])),
            registered_at=Instant(row[13]),
            cancelled_at=None if row[14] is None else Instant(row[14]),
            settled_at=None if row[15] is None else Instant(row[15]),
            attempt_count=int(row[16]),
            current_observation_kind=(
                None if row[17] is None else EffectObservationKind(str(row[17]))
            ),
            current_observation_reliability=(
                None if row[18] is None else EffectObservationReliability(str(row[18]))
            ),
            current_attempt_id=row[19],
            current_attempt_no=None if row[20] is None else int(row[20]),
            current_dispatch_state=None if row[21] is None else str(row[21]),
            current_observation_id=row[22],
            observation_conclusion=None if row[23] is None else str(row[23]),
            observation_reason=None if row[24] is None else str(row[24]),
            observation_evidence_kind=None if row[25] is None else str(row[25]),
        )

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
                   effect.action_intent_revision_id, effect.effect_kind, effect.capability_kind, effect.status,
                   effect.verification_status, effect.registered_at, effect.cancelled_at,
                   (SELECT count(*) FROM armi.effect_attempts AS attempt
                    WHERE attempt.effect_id = effect.effect_id),
                   observation.observation_kind, observation.reliability,
                   effect.settled_at,effect.destination_kind,
                   attempt.effect_attempt_id,attempt.attempt_no,
                   attempt.dispatch_state,observation.effect_observation_id,
                   observation.conclusion,CASE WHEN outbox.last_error_code='EFFECT-RUNTIME-INTERRUPTED' THEN outbox.last_error_code ELSE COALESCE(observation.reason_code,outbox.last_error_code) END,
                   observation.evidence_kind
            FROM armi.effects AS effect
            JOIN armi.effect_outbox_items AS outbox ON outbox.effect_id=effect.effect_id
            LEFT JOIN armi.effect_observations AS observation
              ON observation.effect_observation_id = effect.current_observation_id
            LEFT JOIN armi.effect_attempts AS attempt
              ON attempt.effect_attempt_id=effect.current_attempt_id
            WHERE effect.effect_id=%s AND effect.context_party_id=%s
            """,
                (effect_id.value, creator_party_id),
            )
        ).fetchone()
        if row is None:
            raise EffectViolation("SCOPE-EFFECT-NOT-VISIBLE")
        raw_effect_kind = str(row[3])
        if raw_effect_kind not in {"creator_response", "codex_delegation"}:
            raise EffectViolation("CON-EFFECT-KIND")
        effect_kind = cast(
            Literal["creator_response", "codex_delegation"], raw_effect_kind
        )
        return EffectView(
            effect_id=EffectId(row[0]),
            action_intent_ref=row[1],
            action_intent_revision_ref=row[2],
            effect_kind=effect_kind,
            status=EffectStatus(str(row[5])),
            verification_status=EffectVerificationStatus(str(row[6])),
            registered_at=Instant(row[7]),
            capability_kind=cast(
                Literal["creator.scene.reply", "codex.delegated-work"], str(row[4])
            ),
            cancelled_at=Instant(row[8]) if row[8] is not None else None,
            attempt_count=int(row[9]),
            last_observation_kind=(
                EffectObservationKind(str(row[10])) if row[10] is not None else None
            ),
            last_observation_reliability=(
                EffectObservationReliability(str(row[11]))
                if row[11] is not None
                else None
            ),
            current_attempt_ref=row[14],
            current_attempt_no=None if row[15] is None else int(row[15]),
            current_dispatch_state=None if row[16] is None else str(row[16]),
            current_observation_ref=row[17],
            observation_conclusion=None if row[18] is None else str(row[18]),
            observation_reason=None if row[19] is None else str(row[19]),
            observation_evidence_kind=None if row[20] is None else str(row[20]),
            verification_action=(
                (
                    "verify_codex_result"
                    if effect_kind == "codex_delegation"
                    else "verify_external_delivery"
                    if str(row[13]) in {"external_private", "external_group"}
                    else "verify_local_inbox"
                )
                if str(row[5]) == "unknown" and row[19] != "EFFECT-RUNTIME-INTERRUPTED"
                else None
            ),
            settled_at=Instant(row[12]) if row[12] is not None else None,
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


__all__ = (
    "PostgreSQLDeclaredResponseEffectRegistration",
    "PostgreSQLEffectLedgerRepository",
)
