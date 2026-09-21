"""PostgreSQL owner for atomic effect registration and ledger reads."""

from __future__ import annotations

from typing import Literal, cast
from uuid import UUID, uuid7

from armi_expression.api import (
    CodexEffectDraft,
    DeclaredResponseEffectDraft,
)
from armi_kernel.contracts import Digest, Instant
from armi_runtime_foundation import (
    PostgreSQLRuntimeUnitOfWork,
    PostgreSQLTransaction,
)

from ._family import effect_family
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
        # Intent, dispatch lease and delivery result share one row; see DESIGN.md.
        task = draft.delegation
        effect_id = uuid7()
        await transaction.execute(
            """INSERT INTO armi.effects (
                effect_id,action_intent_id,max_attempts,
                root_opportunity_id,operation_ref,candidate_validation_id,proposal_ref,subject_commit_id,codex_task_source_id,
                subject_id,scene_id,context_party_id,payload_artifact_id,
                payload_digest,payload_bytes,effect_kind,destination_kind,
                destination_party_id,trace_id,status,verification_status)
               VALUES (%s,%s,1,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'codex_delegation',
                 'codex_workspace',%s,%s,'registered','not_started')""",
            (
                effect_id,
                draft.action_intent_id,
                task.root_opportunity_id,
                task.operation_ref,
                task.validation_id,
                task.proposal_ref,
                draft.subject_commit_id,
                task.task_source_id,
                task.subject_id,
                task.scene_id,
                task.creator_party_id,
                task.task_manifest_artifact_id,
                task.task_manifest_digest.value,
                task.task_manifest_bytes,
                task.creator_party_id,
                task.trace_id.value,
            ),
        )
        return effect_id

    async def register_declared_response(
        self,
        transaction: PostgreSQLTransaction,
        draft: DeclaredResponseEffectDraft,
    ) -> UUID:
        effect_id = uuid7()
        await transaction.execute(
            """
            INSERT INTO armi.effects (
                effect_id, action_intent_id, dispatch_deadline, max_attempts,
                root_opportunity_id,operation_ref,candidate_validation_id,proposal_ref,subject_commit_id,
                subject_id, scene_id, context_party_id, payload_artifact_id,
                payload_digest, payload_bytes,
                effect_kind, destination_kind,
                destination_party_id, destination_binding_id,
                live_voice_turn_id, status, verification_status,
                trace_id) VALUES (
                %s, %s, CASE WHEN %s THEN NULL ELSE statement_timestamp() + interval '1 hour' END, %s,
                %s, %s, %s, %s, %s, %s,
                %s, %s, %s, %s, %s,
                %s, %s, %s, %s,
                %s, 'registered', 'not_started', %s)
            """,
            (
                effect_id,
                draft.action_intent_id,
                draft.effect_kind == "creator_response",
                draft.max_attempts,
                draft.root_opportunity_id,
                draft.operation_ref,
                draft.candidate_validation_id,
                draft.proposal_ref,
                draft.subject_commit_id,
                draft.subject_id,
                draft.scene_id,
                draft.context_party_id,
                draft.payload_artifact_id,
                draft.payload_digest.value,
                draft.payload_bytes,
                draft.effect_kind,
                draft.destination_kind,
                draft.destination_party_id,
                draft.destination_binding_id,
                draft.live_voice_turn_id,
                draft.trace_id.value,
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
                SELECT effect.effect_id,
                       effect.action_intent_id, effect.subject_id, effect.scene_id, effect.context_party_id,
                       effect.payload_artifact_id, effect.payload_digest,
                       effect.payload_bytes, effect.effect_kind,
                       effect.status,
                       effect.verification_status, effect.registered_at,
                       effect.cancelled_at, effect.settled_at,
                       (SELECT count(*) FROM armi.effect_attempts AS attempt
                        WHERE attempt.effect_id=effect.effect_id),
                       observation.observation_kind, observation.reliability,
                       attempt.effect_attempt_id,attempt.attempt_no,
                       attempt.dispatch_state,observation.effect_observation_id,
                       observation.conclusion,CASE WHEN effect.last_error_code='EFFECT-RUNTIME-INTERRUPTED' THEN effect.last_error_code ELSE COALESCE(observation.reason_code,effect.last_error_code) END,
                       observation.evidence_kind
                FROM armi.effects AS effect

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
            action_intent_id=row[1],
            subject_id=row[2],
            scene_id=row[3],
            context_party_id=row[4],
            payload_artifact_id=row[5],
            payload_digest=Digest(str(row[6])),
            payload_bytes=int(row[7]),
            effect_kind=str(row[8]),
            capability_kind=effect_family(str(row[8])).capability_kind,
            status=EffectStatus(str(row[9])),
            verification_status=EffectVerificationStatus(str(row[10])),
            registered_at=Instant(row[11]),
            cancelled_at=None if row[12] is None else Instant(row[12]),
            settled_at=None if row[13] is None else Instant(row[13]),
            attempt_count=int(row[14]),
            current_observation_kind=(
                None if row[15] is None else EffectObservationKind(str(row[15]))
            ),
            current_observation_reliability=(
                None if row[16] is None else EffectObservationReliability(str(row[16]))
            ),
            current_attempt_id=row[17],
            current_attempt_no=None if row[18] is None else int(row[18]),
            current_dispatch_state=None if row[19] is None else str(row[19]),
            current_observation_id=row[20],
            observation_conclusion=None if row[21] is None else str(row[21]),
            observation_reason=None if row[22] is None else str(row[22]),
            observation_evidence_kind=None if row[23] is None else str(row[23]),
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
                   effect.effect_kind, effect.status,
                   effect.verification_status, effect.registered_at, effect.cancelled_at,
                   (SELECT count(*) FROM armi.effect_attempts AS attempt
                    WHERE attempt.effect_id = effect.effect_id),
                   observation.observation_kind, observation.reliability,
                   effect.settled_at,effect.destination_kind,
                   attempt.effect_attempt_id,attempt.attempt_no,
                   attempt.dispatch_state,observation.effect_observation_id,
                   observation.conclusion,CASE WHEN effect.last_error_code='EFFECT-RUNTIME-INTERRUPTED' THEN effect.last_error_code ELSE COALESCE(observation.reason_code,effect.last_error_code) END,
                   observation.evidence_kind
            FROM armi.effects AS effect

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
        raw_effect_kind = str(row[2])
        if raw_effect_kind not in {"creator_response", "codex_delegation"}:
            raise EffectViolation("CON-EFFECT-KIND")
        effect_kind = cast(
            Literal["creator_response", "codex_delegation"], raw_effect_kind
        )
        return EffectView(
            effect_id=EffectId(row[0]),
            action_intent_ref=row[1],
            effect_kind=effect_kind,
            status=EffectStatus(str(row[3])),
            verification_status=EffectVerificationStatus(str(row[4])),
            registered_at=Instant(row[5]),
            capability_kind=cast(
                Literal["creator.scene.reply", "codex.delegated-work"],
                effect_family(raw_effect_kind).capability_kind,
            ),
            cancelled_at=Instant(row[6]) if row[6] is not None else None,
            attempt_count=int(row[7]),
            last_observation_kind=(
                EffectObservationKind(str(row[8])) if row[8] is not None else None
            ),
            last_observation_reliability=(
                EffectObservationReliability(str(row[9]))
                if row[9] is not None
                else None
            ),
            current_attempt_ref=row[12],
            current_attempt_no=None if row[13] is None else int(row[13]),
            current_dispatch_state=None if row[14] is None else str(row[14]),
            current_observation_ref=row[15],
            observation_conclusion=None if row[16] is None else str(row[16]),
            observation_reason=None if row[17] is None else str(row[17]),
            observation_evidence_kind=None if row[18] is None else str(row[18]),
            verification_action=(
                (
                    "verify_codex_result"
                    if effect_kind == "codex_delegation"
                    else "verify_external_delivery"
                    if str(row[11]) in {"external_private", "external_group"}
                    else "verify_local_inbox"
                )
                if str(row[3]) == "unknown" and row[17] != "EFFECT-RUNTIME-INTERRUPTED"
                else None
            ),
            settled_at=Instant(row[10]) if row[10] is not None else None,
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
